import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

script = Path(__file__).resolve().parents[3] / "scripts/prepare-director-app.py"
spec = importlib.util.spec_from_file_location("app_release", script)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_consistent_backup_keeps_old_new_rows_and_media_without_changing_source(tmp_path):
    database = tmp_path / "isolated.sqlite"
    with sqlite3.connect(database) as db:
        db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE jobs(id TEXT PRIMARY KEY, status TEXT, params TEXT, output BLOB);
            CREATE TABLE job_assets(job_id TEXT, data BLOB);
        """)
        db.executemany("INSERT INTO jobs VALUES(?,?,?,?)", [
            ("old", "completed", '{"mode":"text"}', b"historical-output"),
            ("new", "running", json.dumps({"workflowEngine": "native",
                                          "workflowRevision": "fixed"}), b"new-output"),
        ])
        db.execute("INSERT INTO job_assets VALUES('old',?)", (b"private-reference",))
    before = database.read_bytes()
    backup = tmp_path / "backups/consistent.sqlite"
    result = release.inspect(database, backup)
    assert result == {
        "integrity": "ok", "jobs_by_status": {"completed": 1, "running": 1},
        "jobs_by_engine": {"native": 2}, "legacy_jobs_without_revision": 1,
        "executing_jobs": 1, "assets": 1, "backup_created": True,
        "schema_migration_required": False,
    }
    assert database.read_bytes() == before
    cli = subprocess.run(
        [sys.executable, str(script), "--database", str(database)],
        capture_output=True, text=True, check=False,
    )
    assert cli.returncode == 2 and "natural completion" in cli.stderr
    assert "historical-output" not in cli.stdout and "private-reference" not in cli.stdout
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT output FROM jobs ORDER BY id").fetchall() == [
            (b"new-output",), (b"historical-output",),
        ]
        assert db.execute("SELECT data FROM job_assets").fetchone()[0] == b"private-reference"
    with pytest.raises(FileExistsError):
        release.inspect(database, backup)
    with pytest.raises(FileExistsError):
        release.inspect(database, database)


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / "absent.sqlite"
    with pytest.raises(FileNotFoundError):
        release.inspect(path)
    assert not path.exists()
