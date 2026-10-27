"""Add small video covers to existing completed jobs, without generating or changing videos."""

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from comfy_hub_worker.video import make_poster, validate_video

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    db = sqlite3.connect(ROOT / "apps/web/.local-data/mvp.sqlite", timeout=10)
    columns = {c[1] for c in db.execute("PRAGMA table_info(jobs)")}
    if "poster" not in columns:
        raise SystemExit("请先部署新版网站，使封面字段迁移完成")
    ids = [
        row[0]
        for row in db.execute(
            "SELECT id FROM jobs WHERE status='completed' AND poster IS NULL AND json_extract(params,'$.mode') LIKE 'h3_%'"
        )
    ]
    print("需要补封面的视频：", len(ids))
    if args.write and ids:
        backup = (
            ROOT
            / ".local-data"
            / (
                "mvp-before-posters-"
                + datetime.now().strftime("%Y%m%d-%H%M%S")
                + ".sqlite"
            )
        )
        with sqlite3.connect(backup) as target:
            db.backup(target)
        for job_id in ids:
            params, data = db.execute(
                "SELECT params,output FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            validate_video(data, json.loads(params))
            original_hash = hashlib.sha256(data).digest()
            poster = make_poster(data)
            db.execute(
                "UPDATE jobs SET poster=? WHERE id=? AND status='completed' AND poster IS NULL",
                (poster, job_id),
            )
            db.commit()
            actual = db.execute(
                "SELECT output FROM jobs WHERE id=?", (job_id,)
            ).fetchone()[0]
            assert hashlib.sha256(actual).digest() == original_hash
            print(job_id, "JPEG bytes", len(poster), "原视频 SHA256 保持一致")
    db.close()
