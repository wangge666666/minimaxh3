"""从仓库根目录运行：python scripts/check-worker.py。"""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
raise SystemExit(subprocess.call(
    [sys.executable, "-m", "comfy_hub_worker", "--check-config"],
    cwd=root / "apps" / "worker",
))
