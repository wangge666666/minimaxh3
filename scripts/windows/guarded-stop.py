"""Stop only this deployment's scheduled tasks while SQLite blocks new claims."""
import json
import sqlite3
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]
database = root / 'apps/web/.local-data/mvp.sqlite'
if not database.exists():
    raise SystemExit('Database missing; refusing an unguarded stop.')
with sqlite3.connect(database, timeout=15) as db:
    db.execute('BEGIN IMMEDIATE')
    active = db.execute("SELECT id,status FROM jobs WHERE status IN ('queued','claimed','running','uploading')").fetchall()
    if active:
        print(json.dumps({'stopped': False, 'reason': 'Tasks are active; wait for completion or cancel queued jobs in the page.', 'active': active}))
        raise SystemExit(2)
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(root / 'scripts/windows/stop-processes.ps1')], capture_output=True)
    if result.returncode:
        raise SystemExit('Unable to stop verified project processes; inspect Task Scheduler and logs.')
    db.commit()
print(json.dumps({'stopped': True, 'database': str(database), 'comfyui_untouched': True}))
