// Preserve source settings and credentials, overriding only destination addresses.
// Never connects to databases, installs services, creates cutover markers, or starts jobs.
import { readFileSync, writeFileSync, mkdirSync, statSync } from 'node:fs';
import { homedir, hostname } from 'node:os';
import { join } from 'node:path';
import { parseEnv } from 'node:util';

if (hostname().split('.')[0] !== 'a1347-m') throw Error('Run only on a1347-m');
const home = homedir();
const staging = join(home, 'app-migration-20260924');
const selected = process.argv[2];
if (selected && !['job-watch', 'app-demand-radar'].includes(selected)) throw Error('Unknown app');
for (const [app, sourceName, database] of [
  ['job-watch', 'jobwatch-source.env', 'jobwatch'],
  ['app-demand-radar', 'radar-source.env', 'app_demand_radar'],
]) {
  if (selected && app !== selected) continue;
  const sourcePath = join(staging, sourceName);
  if (statSync(sourcePath).mode & 0o077) throw Error(`${app}: source config must be private`);
  const source = readFileSync(sourcePath, 'utf8');
  const original = parseEnv(source);
  const databaseUrl = parseEnv(readFileSync(join(home, '.config/app-migration', database + '.env'), 'utf8')).DATABASE_URL;
  const url = new URL(databaseUrl);
  if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) ||
      url.pathname !== '/' + database || url.port !== '5432') throw Error('Unexpected target database');
  const directory = join(home, '.config', app);
  const runtime = join(directory, 'runtime.env');
  const overrides = { DATABASE_URL: databaseUrl, NODE_ENV: 'production' };
  if (app === 'job-watch') {
    Object.assign(overrides, { JOBWATCH_LAN_ADDRESS: '192.168.4.35', JOBWATCH_TRUSTED_HOSTNAMES: 'jobwatch.home.arpa' });
  } else {
    const origins = (original.APP_DEMAND_ALLOWED_ORIGINS || 'http://localhost:5173,http://127.0.0.1:5173').split(',').map(x => x.trim()).filter(Boolean);
    origins.push('http://radar.home.arpa:5210', 'http://192.168.4.35:5210', 'http://127.0.0.1:5210', 'http://localhost:5210');
    Object.assign(overrides, { HOST: '0.0.0.0', PORT: '5210', ENV_FILE: runtime,
      APP_DEMAND_ALLOWED_ORIGINS: [...new Set(origins)].join(',') });
  }
  const output = source + '\n# Destination overrides; source settings retained above.\n' +
    Object.entries(overrides).map(([key, value]) => `${key}=${JSON.stringify(value)}`).join('\n') + '\n';
  const parsed = parseEnv(output);
  for (const [key, value] of Object.entries({ ...original, ...overrides })) {
    if (parsed[key] !== value) throw Error(`${app}: configuration serialization failed for ${key}`);
  }
  mkdirSync(directory, { mode: 0o700 }); // Refuse replacing existing app config.
  writeFileSync(runtime, output, { mode: 0o600, flag: 'wx' });
  console.log(`${app}: protected configuration staged; services not started`);
}
