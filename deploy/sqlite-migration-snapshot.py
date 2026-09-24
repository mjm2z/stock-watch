#!/usr/bin/env python3
"""Create or verify a consistent migration snapshot without changing its source.

Run as the database owner. Quiesce ALL writers before taking a final cutover
snapshot; the online backup API also supports preliminary live rehearsals.
This tool never stops services, prunes files, or activates a restored database.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys


def read_only(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def fingerprint(path):
    with closing(read_only(path)) as db:
        integrity = [row[0] for row in db.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            raise RuntimeError("Snapshot failed SQLite integrity_check")
        tables = {}
        for (name,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall():
            quoted = '"' + name.replace('"', '""') + '"'
            tables[name] = db.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0]
        # Record existing FK violations as a baseline, rather than hiding them.
        fk_count = sum(1 for _ in db.execute("PRAGMA foreign_key_check"))
        user_version = db.execute("PRAGMA user_version").fetchone()[0]
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return dict(format_version=1, bytes=path.stat().st_size,
                sha256=digest.hexdigest(), tables=tables,
                foreign_key_violations=fk_count, user_version=user_version)


def snapshot(source, destination, manifest):
    if not source.is_file():
        raise ValueError("Source database does not exist")
    if source.resolve() in (destination.resolve(), manifest.resolve()):
        raise ValueError("Output must not overwrite the source")
    if destination.resolve() == manifest.resolve():
        raise ValueError("Snapshot and manifest must have distinct paths")
    # Exclusive creation prevents replacing an earlier recovery point.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    with manifest.open("x", encoding="utf-8") as output:
        os.chmod(manifest, 0o600)
        src = read_only(source)
        dst = sqlite3.connect(destination)
        try:
            src.backup(dst, pages=1024, sleep=0.1)
            dst.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst.close()
            src.close()
        with destination.open("rb") as database:
            os.fsync(database.fileno())
        record = fingerprint(destination)
        json.dump(record, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    return record


def verify(database, manifest):
    expected = json.loads(manifest.read_text(encoding="utf-8"))
    actual = fingerprint(database)
    if actual != expected:
        raise RuntimeError("Snapshot differs from its manifest; do not activate")
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("source", type=Path)
    create.add_argument("destination", type=Path)
    create.add_argument("manifest", type=Path)
    check = sub.add_parser("verify")
    check.add_argument("database", type=Path)
    check.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "create":
            record = snapshot(args.source, args.destination, args.manifest)
        else:
            record = verify(args.database, args.manifest)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"verified": True, "bytes": record["bytes"],
                      "sha256": record["sha256"],
                      "foreign_key_violations": record["foreign_key_violations"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
