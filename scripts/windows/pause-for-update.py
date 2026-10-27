"""Pause Hub between GPU jobs, retaining queued jobs for a deployment update."""
import json
import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path

root = Path(__file__).resolve().parents[2]
database = root / 'apps/web/.local-data/mvp.sqlite'
deadline = time.monotonic() + 900
print('Waiting for the current job to finish; queued jobs will be preserved.', flush=True)
while time.monotonic() < deadline:
    with closing(sqlite3.connect(database, timeout=15)) as db:
        # Block the next claim while stopping only the project services.
        db.execute('BEGIN IMMEDIATE')
        processing = db.execute(
            "SELECT id FROM jobs WHERE status IN ('claimed','running','uploading')"
        ).fetchall()
        if not processing:
            queued = [row[0] for row in db.execute(
                "SELECT id FROM jobs WHERE status='queued' ORDER BY created_at,rowid"
            )]
            result = subprocess.run(
                ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
                 'Bypass', '-File', str(root / 'scripts/windows/stop-processes.ps1')],
                capture_output=True,
            )
            if result.returncode:
                raise SystemExit('Project service stop failed; inspect before updating.')
            db.commit()
            output = {'stopped_between_jobs': True, 'queued_preserved': queued,
                      'processing_jobs_at_stop': 0, 'comfyui_untouched': True}
            path = root / '.local-data/deployment/queue500-20261028/pause-result.json'
            path.write_text(json.dumps(output, indent=2), encoding='utf8')
            print(json.dumps(output), flush=True)
            break
        db.rollback()
    time.sleep(0.2)
else:
    raise SystemExit('No idle boundary reached; services were not stopped.')
