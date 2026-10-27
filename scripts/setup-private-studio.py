"""生成本地私网生图配置；不会下载模型或修改 Tailscale 网络。"""
import argparse
import os
import secrets
import uuid
from pathlib import Path
from urllib.parse import urlparse

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--origin", required=True, help="Tailscale HTTPS 入口，例如 https://device.example.ts.net:8443")
args = parser.parse_args()
url = urlparse(args.origin)
if (url.scheme != "https" or not (url.hostname or "").endswith(".ts.net")
        or url.username or url.password or url.query or url.fragment or url.path not in ("", "/")):
    parser.error("入口必须为不含凭证、路径和查询参数的 Tailscale HTTPS 地址")
origin = f"https://{url.netloc}"
web = root / "apps/web/.env.local"
worker = root / "apps/worker/.env"


def read(path):
    if not path.exists():
        return {}
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if "=" in line and not line.lstrip().startswith("#"))


w, p = read(web), read(worker)
known = {v for v in (w.get("MVP_WORKER_TOKEN"), p.get("WORKER_API_TOKEN")) if v}
if len(known) > 1:
    parser.error("现有网站和 Worker 令牌不匹配，请先核对配置；未覆盖文件")
token = next(iter(known), secrets.token_urlsafe(48))
w.update(MVP_LOCAL_ENABLED="1", MVP_WORKER_TOKEN=token, MVP_ALLOWED_ORIGIN=origin)
p.update(CLOUD_API_BASE_URL="http://127.0.0.1:3000", WORKER_API_TOKEN=token)
p.setdefault("WORKER_ID", str(uuid.uuid4()))
p.setdefault("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
p.setdefault("POLL_INTERVAL_SECONDS", "2")
p.setdefault("MAX_CONCURRENT_JOBS", "1")
p.setdefault("WORKFLOW_DIRECTORY", "../../workflows")
p.setdefault("WORKER_STATE_DIRECTORY", "./worker-state")
for path, values in ((web, w), (worker, p)):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as stream:
        if os.name != "nt":
            os.chmod(path, 0o600)
        stream.write("".join(f"{key}={value}\n" for key, value in values.items()))
print("私网配置已写入两个被 Git 忽略的文件；未输出机器令牌。")
