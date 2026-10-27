import os
import subprocess
import sys


def test_cli_never_echoes_secret(tmp_path):
    secret = "do-not-print-this-token-value-123456789"
    env = {
        **os.environ,
        "CLOUD_API_BASE_URL": "http://remote.invalid",
        "WORKER_ID": "invalid",
        "WORKER_API_TOKEN": secret,
        "WORKFLOW_DIRECTORY": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, "-m", "comfy_hub_worker", "--check-config"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "配置错误" in result.stderr
    assert secret not in result.stdout + result.stderr


def test_cli_refuses_to_pretend_worker_is_running(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "comfy_hub_worker"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "尚未启动" in result.stderr
