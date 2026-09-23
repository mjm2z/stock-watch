"""Hash the tested source and Linux build for the root installer."""
from pathlib import Path
import hashlib
root = Path(__file__).resolve().parents[1]
files = []
for directory in ("app", "components", "lib", "types", "worker/src", "worker/migrations", ".next"):
    for path in sorted((root / directory).rglob("*")):
        if path.is_file() and not {"cache", "__pycache__"}.intersection(path.parts):
            files.append(path)
files += [root / "package-lock.json", root / "deploy/install-evaluation-root.sh"]
if (root / "deploy/install-status-root.sh").exists():
    files.append(root / "deploy/install-status-root.sh")
if (root / "deploy/install-assessment-root.sh").exists():
    files.append(root / "deploy/install-assessment-root.sh")
with (root / "release.sha256").open("w") as output:
    for path in files:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        output.write(f"{digest}  {path.relative_to(root)}\n")
print(f"Recorded {len(files)} release hashes.")
