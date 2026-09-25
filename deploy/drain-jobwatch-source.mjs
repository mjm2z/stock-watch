// Source-only cutover helper. Default mode is read-only; no database rows change.
import { createRequire } from 'node:module';
import { hostname, platform, homedir } from 'node:os';
import { spawnSync } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

const [root, mode = 'review'] = process.argv.slice(2);
if (!root || !['review','stop-source'].includes(mode)) throw Error('Usage: script APP_ROOT [review|stop-source]');
const url = new URL(process.env.DATABASE_URL);
if (platform() !== 'darwin' || url.hostname !== '127.0.0.1' || url.port !== '55432')
  throw Error('Only the original Mac loopback PostgreSQL cluster on port 55432 is permitted');
const { Client } = createRequire(path.resolve(root, 'package.json'))('pg');
const client = new Client({ connectionString: process.env.DATABASE_URL });
const domain = 'gui/' + process.getuid();
function launchctl(...args) {
  const result = spawnSync('/bin/launchctl', args, { encoding: 'utf8' });
  if (result.status !== 0) throw Error('launchctl operation failed: ' + args[0] + '\n' + result.stderr);
  return result.stdout;
}
await client.connect();
try {
  const names = ['com.mike.job-watch-web','com.mike.job-watch-worker'];
  const original = Object.fromEntries(names.map(name => [name, launchctl('print', domain+'/'+name)]));
  const keys = (await client.query('SELECT id::text AS id FROM companies UNION SELECT id::text FROM source_subscriptions ORDER BY id')).rows;
  console.log(JSON.stringify({mode, source_host:hostname(), subscription_and_company_locks:keys.length}));
  if (mode === 'stop-source') {
    const clock = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
      timeZone:'America/New_York', weekday:'short',hour:'2-digit',minute:'2-digit',hourCycle:'h23'
    }).formatToParts(new Date()).map(p=>[p.type,p.value]));
    const minute=Number(clock.hour)*60+Number(clock.minute);
    if (!['Sat','Sun'].includes(clock.weekday) && minute>=570 && minute<960)
      throw Error('Refusing migration cutover during market hours');
    const directory=path.join(homedir(),'.local/state/job-watch-migration','source-stop-'+Date.now());
    await mkdir(directory,{recursive:true,mode:0o700});
    await writeFile(path.join(directory,'launchd-before.json'),JSON.stringify(original,null,2),{mode:0o600,flag:'wx'});
    launchctl('disable',domain+'/'+names[0]);
    launchctl('bootout',domain+'/'+names[0]);
    // Take exactly the locks used by syncSubscription and processMatches. Waiting
    // lets existing fetches finish; holding them prevents new work during unload.
    await client.query("SET statement_timeout = '30min'");
    const timer=setInterval(()=>console.log('Waiting for source sync/matching locks to drain...'),30000);
    try {
      await client.query('SELECT pg_advisory_lock(8263102)');
      // Refresh after web shutdown so any just-created subscription is included.
      const current=(await client.query('SELECT id::text AS id FROM companies UNION SELECT id::text FROM source_subscriptions ORDER BY id')).rows;
      for (const {id} of current) await client.query('SELECT pg_advisory_lock(hashtext($1))',[id]);
    } finally { clearInterval(timer); }
    launchctl('disable',domain+'/'+names[1]);
    launchctl('bootout',domain+'/'+names[1]);
    for (const name of names) {
      // bootout can return while launchd still reports an exiting process.
      const deadline=Date.now()+60000;
      while (spawnSync('/bin/launchctl',['print',domain+'/'+name],{stdio:'ignore'}).status===0 && Date.now()<deadline)
        await sleep(250);
      if (spawnSync('/bin/launchctl',['print',domain+'/'+name]).status===0)
        throw Error('Source service remains loaded: '+name);
    }
    const connections=(await client.query(`SELECT count(*)::int AS count FROM pg_stat_activity
      WHERE datname=current_database() AND backend_type='client backend' AND pid<>pg_backend_pid()`)).rows[0].count;
    if (connections) throw Error('Other source database clients remain; inspect before final snapshot');
    await writeFile(path.join(directory,'stopped.json'),JSON.stringify({
      source_services_stopped:true,at:new Date().toISOString(),database_server_retained:true,
      next:'Create and verify the final PostgreSQL snapshot before target activation'
    },null,2),{mode:0o600,flag:'wx'});
    console.log('Source web and worker stopped after acquiring their work locks. Original database remains intact.');
  }
} finally { await client.end(); }
