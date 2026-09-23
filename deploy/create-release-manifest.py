"""Hash the tested source, tests, deployment files and production build."""
import hashlib
from pathlib import Path

root = Path.cwd()
paths = []
for directory in ('app','components','lib','types','worker','deploy','tests','.next'):
    paths.extend(path for path in (root/directory).rglob('*') if path.is_file()
                 and not any(part in {'__pycache__','.venv','node_modules','cache'}
                             for part in path.relative_to(root).parts))
paths.extend(root/name for name in ('package.json','package-lock.json','next.config.mjs','tsconfig.json'))
with (root/'release.sha256').open('w') as output:
    for path in sorted(set(paths)):
        with path.open('rb') as content:
            digest = hashlib.file_digest(content,'sha256').hexdigest()
        output.write(digest+'  '+str(path.relative_to(root))+'\n')
print('Hashed',len(set(paths)),'release files')
