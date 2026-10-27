"""Start/stop the Mac studio in independent OS sessions, outside the chat terminal."""

import argparse
import fcntl
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".local-data/services"


def running(name):
    path = RUNTIME / f"{name}.pid.json"
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    pid = record["pid"]
    if record.get("root") != str(ROOT) or type(pid) is not int or pid <= 1:
        raise RuntimeError("服务 PID 记录与当前项目不匹配")
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "state=", "-o", "command="],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode or result.stdout.lstrip().startswith("Z"):
        return None
    markers = (
        ("next-server", "next/dist/bin/next")
        if name == "web"
        else ("comfy_hub_worker",)
    )
    cwd = subprocess.run(
        ["/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        capture_output=True,
        text=True,
        check=False,
    )
    expected = ROOT / ("apps/web" if name == "web" else "apps/worker")
    directories = [line[1:] for line in cwd.stdout.splitlines() if line.startswith("n")]
    if not any(marker in result.stdout for marker in markers) or not any(
        Path(d) == expected for d in directories
    ):
        raise RuntimeError("服务进程身份不匹配，未操作该进程")
    return pid


def check_idle():
    database = ROOT / "apps/web/.local-data/mvp.sqlite"
    if database.exists():
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as db:
            active = db.execute(
                "SELECT count(*) FROM jobs WHERE status IN ('queued','claimed','running','uploading')"
            ).fetchone()[0]
        if active:
            raise RuntimeError("队列中还有任务，请等待完成后再停止服务")


def start():
    bundled = (
        Path.home()
        / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
    )
    node = (
        bundled if bundled.is_file() else Path(shutil.which("node") or "node-not-found")
    )
    python = (
        ROOT / ".venv/bin/python"
    )  # Preserve the venv path instead of resolving its symlink.
    next_cli = ROOT / "apps/web/node_modules/next/dist/bin/next"
    if not all(p.is_file() for p in (node, python, next_cli)):
        raise RuntimeError("缺少 Node、项目 Python 虚拟环境或已安装的 Next.js")
    if not (ROOT / "apps/web/.next/BUILD_ID").is_file():
        raise RuntimeError("请先运行 pnpm build")
    if not running("web"):
        try:
            with socket.create_connection(("127.0.0.1", 3000), timeout=1):
                raise RuntimeError("3000 已由其他进程占用，未启动第二个网站进程")
        except (ConnectionRefusedError, TimeoutError):
            pass
    commands = {
        "web": (
            [
                str(node),
                str(next_cli),
                "start",
                "--hostname",
                "127.0.0.1",
                "--port",
                "3000",
            ],
            ROOT / "apps/web",
        ),
        "worker": (
            [str(python), "-m", "comfy_hub_worker", "--run"],
            ROOT / "apps/worker",
        ),
    }
    for name, (command, directory) in commands.items():
        pid = running(name)
        if pid:
            print(name, "已运行，保留 PID", pid)
            continue
        with (
            (RUNTIME / f"{name}.stdout.log").open("ab") as out,
            (RUNTIME / f"{name}.stderr.log").open("ab") as err,
        ):
            process = subprocess.Popen(
                command,
                cwd=directory,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                start_new_session=True,
                close_fds=True,
                env={
                    **os.environ,
                    "PATH": f"{node.parent}:" + os.environ.get("PATH", ""),
                },
            )
        path = RUNTIME / f"{name}.pid.json"
        path.write_text(json.dumps({"pid": process.pid, "root": str(ROOT)}))
        path.chmod(0o600)
        print(name, "已独立启动，PID", process.pid)
    opener = build_opener(ProxyHandler({}))
    for attempt in range(10):
        try:
            with opener.open("http://127.0.0.1:3000/api/health", timeout=2) as response:
                if response.status == 200 and running("worker"):
                    print("网站和 Worker 已启动；日志：.local-data/services/")
                    return
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError("服务尚未正常就绪，请检查 .local-data/services/ 下的日志")


def stop():
    check_idle()
    for name in ("worker", "web"):
        pid = running(name)
        if pid:
            os.kill(pid, signal.SIGTERM)
            for _ in range(20):
                state = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "state="],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if state.returncode or state.stdout.lstrip().startswith("Z"):
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError(f"{name} 尚未停止，未强制结束")
        (RUNTIME / f"{name}.pid.json").unlink(missing_ok=True)
        print(name, "已停止")


def status():
    for name in ("web", "worker"):
        pid = running(name)
        print(name, f"运行中 PID {pid}" if pid else "未启动")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status"])
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("此脚本仅用于 Mac")
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with (RUNTIME / "control.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            {"start": start, "stop": stop, "status": status}[args.action]()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
