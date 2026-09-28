"""Hash source, Linux build, dependencies and worker wheel for the release installer."""

import hashlib
import json
from pathlib import Path
import re
import sys


def main():
    revision = sys.argv[1]
    if not re.fullmatch("[0-9a-f]{40}", revision):
        raise SystemExit("Full commit revision required")
    root = Path.cwd()
    if (root / "source-revision.txt").read_text().strip() != revision:
        raise SystemExit("Source identity differs")
    files = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink() or not path.is_file():
            continue
        if any(
            part in (".git", ".build-venv", "__pycache__", "cache")
            for part in relative.parts
        ):
            continue
        if relative.name in ("source.tar", "reviewed-release.json"):
            continue
        if relative.parts[0].startswith(".env") and relative.name != ".env.example":
            raise SystemExit("Unapproved environment file")
        with path.open("rb") as stream:
            files[str(relative)] = hashlib.file_digest(stream, "sha256").hexdigest()
    (root / "reviewed-release.json").write_text(
        json.dumps({"revision": revision, "files": files}, indent=2) + "\n"
    )
    print("Reviewed files:", len(files))


if __name__ == "__main__":
    main()
