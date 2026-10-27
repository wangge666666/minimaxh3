import argparse
import asyncio
import logging
import sys

from pydantic import ValidationError

from comfy_hub_worker.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="ComfyUI Cloud Hub Worker")
    parser.add_argument("--check-config", action="store_true", help="离线校验配置，不连接服务")
    parser.add_argument("--run", action="store_true", help="运行本地 MVP Worker")
    parser.add_argument("--once", action="store_true", help="仅领取/恢复一个任务，用于验证")
    args = parser.parse_args()
    if not args.check_config and not args.run:
        parser.exit(2, "执行器默认尚未启动；使用 --run 或 --check-config。\n")
    try:
        settings = Settings()
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_url=False):
            field = ".".join(map(str, error["loc"])) or "configuration"
            print(f"配置错误：{field}（{error['type']}）", file=sys.stderr)
        raise SystemExit(1) from None
    if args.check_config:
        print("配置校验通过；尚未连接云端或 ComfyUI。")
        return
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    from comfy_hub_worker.runner import run

    try:
        asyncio.run(run(settings, once=args.once))
    except KeyboardInterrupt:
        print("Worker 已停止；持久化记录保留供恢复。")
    except Exception as exc:
        print(f"Worker 退出（{type(exc).__name__}），请检查配置或服务连接。", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
