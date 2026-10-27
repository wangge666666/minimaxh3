"""Read-only comparison against the version 1.0 workflow SHA256 manifest."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
manifest = json.loads((root / 'docs/baselines/v1.0.0.json').read_text(encoding='utf8'))
changed = []
for item in manifest['workflow_files']:
    path = root / item['path']
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
        changed.append(item['path'])
print(json.dumps({'baseline': manifest['version'], 'workflow_files': len(manifest['workflow_files']),
                  'unchanged': not changed, 'changed_or_missing': changed}, indent=2))
raise SystemExit(1 if changed else 0)
