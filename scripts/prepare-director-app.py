"""Inspect an explicit SQLite DB and optionally create a consistent private backup.

No service controls, network requests, queue updates or schema migrations.
"""

import argparse
import json
import os
import sqlite3
from pathlib import Path


def inspect(database: Path, backup: Path | None = None) -> dict:
    database = database.resolve(strict=True)
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as source:
        source.execute("BEGIN")
        integrity = source.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError("Database integrity check failed")
        counts = dict(source.execute("SELECT status,count(*) FROM jobs GROUP BY status"))
        # Inspect metadata without opening or returning media, prompts or credentials.
        engines: dict[str, int] = {}
        legacy = 0
        for (raw,) in source.execute("SELECT params FROM jobs"):
            params = json.loads(raw)
            engine = params.get("workflowEngine", "native")
            if engine not in {"native", "director"}:
                raise ValueError("Database contains an unknown workflow engine")
            engines[engine] = engines.get(engine, 0) + 1
            legacy += int("workflowRevision" not in params)
        result = {
            "integrity": integrity,
            "jobs_by_status": counts,
            "jobs_by_engine": engines,
            "legacy_jobs_without_revision": legacy,
            "executing_jobs": sum(counts.get(s, 0) for s in ("claimed", "running", "uploading")),
            "assets": source.execute("SELECT count(*) FROM job_assets").fetchone()[0],
            "backup_created": False,
            "schema_migration_required": False,
        }
        if backup is not None:
            backup = backup.resolve()
            backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Never overwrite a prior snapshot, including the original database.
            descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            try:
                with sqlite3.connect(backup) as destination:
                    source.backup(destination)
                    if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError("Backup integrity check failed")
            except Exception:
                backup.unlink(missing_ok=True)
                raise
            result["backup_created"] = True
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    try:
        result = inspect(args.database, args.backup)
    except (OSError, ValueError, sqlite3.Error):
        parser.exit(1, "Database inspection/backup failed; check paths, schema and permissions.\n")
    print(json.dumps(result, indent=2))
    if result["executing_jobs"]:
        parser.exit(2, "Executing jobs remain. Wait for natural completion before service changes.\n")


if __name__ == "__main__":
    main()
