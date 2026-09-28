"""Hash source, Linux build, dependencies and worker wheel for the release installer."""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
from pathlib import Path
import re
import sys


def release_files(root):
    # DirEntry type information avoids separate stat calls for every dependency.
    # Prune excluded trees before traversing them, including large Next caches.
    def walk(directory):
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name in (".git", ".build-venv", "__pycache__", "cache"):
                    continue
                if entry.is_symlink():
                    continue
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    yield from walk(path)
                elif entry.is_file(follow_symlinks=False):
                    relative = path.relative_to(root)
                    if relative.name in ("source.tar", "reviewed-release.json"):
                        continue
                    if relative.parts[0].startswith(".env") and relative.name != ".env.example":
                        raise SystemExit("Unapproved environment file")
                    yield path, str(relative)
    yield from walk(root)


def file_hash(item):
    path, relative = item
    with path.open("rb") as stream:
        return relative, hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    revision = sys.argv[1]
    if not re.fullmatch("[0-9a-f]{40}", revision):
        raise SystemExit("Full commit revision required")
    root = Path.cwd()
    if (root / "source-revision.txt").read_text().strip() != revision:
        raise SystemExit("Source identity differs")
    files = {}
    paths = iter(release_files(root))
    with ThreadPoolExecutor(max_workers=8) as pool:
        while batch := list(islice(paths, 128)):
            files.update(pool.map(file_hash, batch))
            if len(files) % 4096 == 0:
                print("Hashed files:", len(files), flush=True)
    (root / "reviewed-release.json").write_text(
        json.dumps({"revision": revision, "files": files}, indent=2, sort_keys=True) + "\n"
    )
    print("Reviewed files:", len(files))


if __name__ == "__main__":
    main()
