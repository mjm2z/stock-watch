// Run with node --env-file=PRIVATE_ENV this-script APP_ROOT OUTPUT_PREFIX.
// APP_ROOT must provide the pg dependency. Source credentials never reach argv.
// Creates a custom dump and row fingerprints from the SAME exported snapshot.
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { open, writeFile } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import path from 'node:path';

const [root, prefix, mode = 'create'] = process.argv.slice(2);
if (!root || !prefix || !['create', 'inspect'].includes(mode))
  throw new Error('Usage: script APP_ROOT OUTPUT_PREFIX [create|inspect]');
process.umask(0o077);
const { Client } = createRequire(path.resolve(root, 'package.json'))('pg');
const client = new Client({ connectionString: process.env.DATABASE_URL });
const quote = value => '"' + value.replaceAll('"', '""') + '"';
const output = path.resolve(prefix);
// Reserve output names before connecting; never overwrite a recovery point.
const manifestFile = await open(output + '.json', 'wx', 0o600);
await manifestFile.close();
let dumpFile;
if (mode === 'create') dumpFile = await open(output + '.dump', 'wx', 0o600);
try {
  await client.connect();
  await client.query('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY');
  await client.query("SET LOCAL TIME ZONE 'UTC'");
  await client.query("SET LOCAL DateStyle = 'ISO, YMD'");
  await client.query("SET LOCAL IntervalStyle = 'postgres'");
  await client.query('SET LOCAL extra_float_digits = 3');
  const snapshot = (await client.query('SELECT pg_export_snapshot() AS id')).rows[0].id;
  if (mode === 'create') {
    const url = new URL(process.env.DATABASE_URL);
    const env = { ...process.env, PGHOST: url.hostname, PGPORT: url.port || '5432',
      PGUSER: decodeURIComponent(url.username), PGPASSWORD: decodeURIComponent(url.password),
      PGDATABASE: decodeURIComponent(url.pathname.slice(1)) };
    await new Promise((resolve, reject) => {
      const child = spawn(process.env.PG_DUMP || 'pg_dump',
        ['--format=custom', '--no-owner', '--no-acl', '--snapshot=' + snapshot],
        { env, stdio: ['ignore', dumpFile.fd, 'inherit'] });
      child.once('error', reject);
      child.once('exit', code => code === 0 ? resolve() : reject(new Error('pg_dump failed')));
    });
    await dumpFile.sync();
    await dumpFile.close();
    dumpFile = undefined;
  }
  const tables = (await client.query(`SELECT n.nspname AS schema, c.relname AS name
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE c.relkind IN ('r','p') AND n.nspname NOT LIKE 'pg_%'
    AND n.nspname <> 'information_schema' ORDER BY 1,2`)).rows;
  const fingerprints = {};
  for (const table of tables) {
    const name = quote(table.schema) + '.' + quote(table.name);
    // Prefer indexed primary-key order: sorting entire JSON rows spills large
    // history tables to disk. Text keys use C collation across both machines.
    const keys = (await client.query(`SELECT a.attname AS name, a.attcollation <> 0 AS collated
      FROM pg_index i CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum, position)
      JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum
      WHERE i.indrelid=$1::regclass AND i.indisprimary AND k.position<=i.indnkeyatts
      ORDER BY k.position`, [name])).rows;
    const order = keys.length ? keys.map(key => 't.' + quote(key.name) +
      (key.collated ? ' COLLATE "C"' : '')).join(', ') : 'row_to_json(t)::text COLLATE "C"';
    // Text serialization avoids JS numeric precision loss.
    await client.query(`DECLARE migration_rows NO SCROLL CURSOR FOR
      SELECT row_to_json(t)::text AS value FROM ${name} t
      ORDER BY ${order}`);
    const hash = createHash('sha256');
    let count = 0;
    for (;;) {
      const { rows } = await client.query('FETCH 1000 FROM migration_rows');
      if (!rows.length) break;
      for (const row of rows) hash.update(row.value + '\n');
      count += rows.length;
    }
    await client.query('CLOSE migration_rows');
    fingerprints[name] = { rows: count, sha256: hash.digest('hex') };
    console.log(JSON.stringify({ fingerprinted: name, rows: count }));
  }
  await client.query('COMMIT');
  const manifest = { format: 3, serialization: 'UTC/ISO-YMD/postgres/float3/PK', tables: fingerprints };
  if (mode === 'create') {
    const hash = createHash('sha256');
    for await (const chunk of createReadStream(output + '.dump')) hash.update(chunk);
    manifest.dump_sha256 = hash.digest('hex');
  }
  await writeFile(output + '.json', JSON.stringify(manifest, null, 2) + '\n', { mode: 0o600 });
  console.log(JSON.stringify({ complete: true, tables: tables.length, manifest: output + '.json' }));
} finally {
  if (dumpFile) await dumpFile.close();
  await client.end();
}
