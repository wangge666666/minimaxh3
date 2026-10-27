"""Back up and append a consistent historical snapshot; never replace existing rows."""
import datetime
import hashlib
import json
import sqlite3
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = root / 'migration/mvp.sqlite'
target = root / 'apps/web/.local-data/mvp.sqlite'
backup_dir = root / '.local-data/deployment/backups'
backup_dir.mkdir(parents=True, exist_ok=True)
stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
manifest = json.loads((root / 'migration/snapshot.json').read_text(encoding='utf8'))
if hashlib.sha256(source.read_bytes()).hexdigest() != manifest['sha256']:
    raise SystemExit('Snapshot SHA256 mismatch.')
for path in (source, target):
    if path.exists():
        with sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise SystemExit('Database integrity failure.')
            if db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','claimed','running','uploading')").fetchone()[0]:
                raise SystemExit('Active queue detected. Stop services and finish tasks first.')
            backup = backup_dir / f'{"source" if path == source else "target"}-{stamp}.sqlite'
            with sqlite3.connect(backup) as destination:
                db.backup(destination)
target.parent.mkdir(parents=True, exist_ok=True)
new_database = not target.exists()
if new_database:
    with sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    # Historical worker heartbeat belongs to the old host; do not advertise it here.
    with sqlite3.connect(target) as dst:
        dst.execute('DELETE FROM worker')
    added = manifest['total_jobs']
else:
    with sqlite3.connect(target) as dst:
        dst.execute('ATTACH DATABASE ? AS snapshot', (str(source),))
        dst.execute('BEGIN IMMEDIATE')
        added = 0
        for table, keys in [('jobs', ('id',)), ('job_assets', ('job_id', 'key'))]:
            cols = [r[1] for r in dst.execute(f'PRAGMA snapshot.table_info({table})')]
            for row in dst.execute(f'SELECT * FROM snapshot.{table}').fetchall():
                conditions = ' AND '.join(f'{key}=?' for key in keys)
                values = tuple(row[cols.index(key)] for key in keys)
                existing = dst.execute(f'SELECT * FROM main.{table} WHERE {conditions}', values).fetchone()
                if existing is not None:
                    if existing != row:
                        raise RuntimeError(f'Conflicting existing {table} row {values}; nothing overwritten.')
                    continue
                dst.execute(f'INSERT INTO main.{table} ({",".join(cols)}) VALUES ({",".join("?" for _ in cols)})', row)
                if table == 'jobs':
                    added += 1
        dst.commit()
with sqlite3.connect(target) as db:
    result = {'imported_new_jobs': added, 'total_jobs': db.execute('SELECT count(*) FROM jobs').fetchone()[0], 'jobs_by_status': dict(db.execute('SELECT status,count(*) FROM jobs GROUP BY status')), 'assets': db.execute('SELECT count(*) FROM job_assets').fetchone()[0], 'completed_outputs': db.execute('SELECT count(*) FROM jobs WHERE output IS NOT NULL').fetchone()[0], 'integrity_check': db.execute('PRAGMA integrity_check').fetchone()[0], 'database': str(target), 'new_database': new_database}
(root / '.local-data/deployment/migration-result.json').write_text(json.dumps(result, indent=2), encoding='utf8')
print(json.dumps(result, indent=2))
