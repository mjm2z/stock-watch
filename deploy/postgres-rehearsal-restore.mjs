// Restore ONLY an empty rehearsal database, then compare every table's rows.
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const [root, prefix, inspection] = process.argv.slice(2);
if (!root || !prefix || !inspection)
  throw new Error('Usage: script APP_ROOT SNAPSHOT_PREFIX NEW_INSPECTION_PREFIX');
const url = new URL(process.env.DATABASE_URL);
const database = decodeURIComponent(url.pathname.slice(1));
if (!['jobwatch_rehearsal', 'radar_rehearsal'].includes(database) || url.hostname !== '127.0.0.1')
  throw new Error('Only a loopback rehearsal database is permitted');
const expected = JSON.parse(await readFile(prefix + '.json', 'utf8'));
if (expected.format !== 3 || expected.serialization !== 'UTC/ISO-YMD/postgres/float3/PK' || !expected.tables || !expected.dump_sha256)
  throw new Error('Missing complete source manifest');
const hash = createHash('sha256');
for await (const chunk of createReadStream(prefix + '.dump')) hash.update(chunk);
if (hash.digest('hex') !== expected.dump_sha256) throw new Error('Transferred dump checksum mismatch');
const { Client } = createRequire(path.resolve(root, 'package.json'))('pg');
const client = new Client({ connectionString: process.env.DATABASE_URL });
try {
  await client.connect();
  const result = await client.query(`SELECT count(*)::int AS count FROM pg_class c
    JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p','S','v','m')
    AND n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'`);
  if (result.rows[0].count !== 0) throw new Error('Rehearsal database is not empty; refusing replacement');
} finally { await client.end(); }
const env = { ...process.env, PGHOST: url.hostname, PGPORT: url.port || '5432',
  PGUSER: decodeURIComponent(url.username), PGPASSWORD: decodeURIComponent(url.password),
  PGDATABASE: database };
async function run(command, args) {
  await new Promise((resolve, reject) => {
    const child = spawn(command, args, { env, stdio: 'inherit' });
    child.once('error', reject);
    child.once('exit', code => code === 0 ? resolve() : reject(new Error(command + ' failed')));
  });
}
await run('pg_restore', ['--exit-on-error', '--single-transaction', '--no-owner', '--no-privileges',
  '--dbname=' + database, prefix + '.dump']);
await run(process.execPath, [fileURLToPath(new URL('./postgres-migration-snapshot.mjs', import.meta.url)),
  root, inspection, 'inspect']);
const actual = JSON.parse(await readFile(inspection + '.json', 'utf8'));
if (JSON.stringify(actual.tables) !== JSON.stringify(expected.tables))
  throw new Error('Restored history differs from source snapshot; do not activate');
console.log(JSON.stringify({ restored: database, all_table_fingerprints_match: true,
  tables: Object.keys(expected.tables).length }));
