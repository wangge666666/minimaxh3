import asyncio
import io
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath

import httpx
from PIL import Image
from websockets.asyncio.client import connect

Image.MAX_IMAGE_PIXELS = 16_000_000


def validate_image(data: bytes) -> bytes:
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("图片超过大小限制")
    with Image.open(io.BytesIO(data)) as image:
        if image.format not in {"PNG", "JPEG", "WEBP"} or getattr(image, "n_frames", 1) != 1:
            raise ValueError("不支持的图片格式")
        if image.width * image.height > 16_000_000:
            raise ValueError("图片像素过大")
        image.load()
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        return buffer.getvalue()


async def limited_get(
    client: httpx.AsyncClient, path: str, limit: int = 16 * 1024 * 1024, **kwargs
) -> bytes:
    async with client.stream("GET", path, **kwargs) as response:
        response.raise_for_status()
        chunks = []
        length = 0
        async for chunk in response.aiter_bytes():
            length += len(chunk)
            if length > limit:
                raise ValueError("图片超过下载限制")
            chunks.append(chunk)
        return b"".join(chunks)


class Comfy:
    def __init__(self, client: httpx.AsyncClient):
        self.http = client

    async def check(self, workflow: dict) -> None:
        (await self.http.get("/system_stats")).raise_for_status()
        response = await self.http.get("/object_info")
        response.raise_for_status()
        info = response.json()
        for node in workflow.values():
            class_type = node["class_type"]
            if class_type not in info:
                raise ValueError(f"ComfyUI 缺少节点：{class_type}")
            required = info[class_type]["input"].get("required", {})
            for key, value in node["inputs"].items():
                spec = required.get(key)
                # LoadImage 的枚举是已上传文件，运行时由 /upload/image 填入。
                if (
                    spec
                    and isinstance(spec[0], list)
                    and class_type not in {"LoadImage", "LoadVideo", "LoadAudio"}
                ):
                    if not isinstance(value, list) and value not in spec[0]:
                        raise ValueError(f"ComfyUI 缺少模型或参数选项：{class_type}.{key}")

    async def upload(self, job_id: str, data: bytes) -> str:
        png = validate_image(data)
        return await self.upload_media(job_id + ".png", png, "image/png")

    async def upload_media(self, filename: str, data: bytes, mime: str) -> str:
        response = await self.http.post(
            "/upload/image",
            files={
                "image": (filename, data, mime),
            },
            data={"type": "input", "overwrite": "true", "subfolder": "hub"},
            timeout=45,
        )
        response.raise_for_status()
        result = response.json()
        name = result["name"]
        subfolder = result.get("subfolder", "")
        path = PurePosixPath(subfolder) / name
        if path.is_absolute() or ".." in path.parts or "\\" in str(path):
            raise ValueError("ComfyUI 返回了不安全的图片路径")
        return str(path)

    async def submit(self, workflow: dict, job_id: str) -> str:
        # 绝不自动重试 /prompt：HTTP 响应丢失时任务可能已执行。
        response = await self.http.post(
            "/prompt",
            json={
                "prompt": workflow,
                "client_id": job_id,
                "extra_data": {"hub_job_id": job_id},
            },
        )
        response.raise_for_status()
        result = response.json()
        if result.get("error") or not result.get("prompt_id"):
            raise ValueError("ComfyUI 拒绝工作流，请检查模型与节点参数")
        return result["prompt_id"]

    async def find_submission(self, job_id: str) -> str | None:
        queue = await self.http.get("/queue")
        queue.raise_for_status()
        history = await self.http.get("/history", params={"max_items": 200})
        history.raise_for_status()
        entries = queue.json().get("queue_running", []) + queue.json().get("queue_pending", [])
        entries += [item.get("prompt", []) for item in history.json().values()]
        matches = [
            item[1]
            for item in entries
            if len(item) > 3 and isinstance(item[3], dict) and item[3].get("hub_job_id") == job_id
        ]
        if len(set(matches)) > 1:
            raise ValueError("发现多个 ComfyUI 任务，请人工核对")
        return matches[0] if matches else None

    async def watch_nodes(
        self, job_id: str, messages: asyncio.Queue, workflow: dict | None = None
    ) -> None:
        url = (
            str(self.http.base_url)
            .rstrip("/")
            .replace("http://", "ws://")
            .replace("https://", "wss://")
            + f"/ws?clientId={job_id}"
        )
        try:
            async with connect(url, max_size=2 * 1024 * 1024, open_timeout=5, proxy=None) as ws:
                async for raw in ws:
                    if not isinstance(raw, str):
                        continue
                    event = json.loads(raw)
                    data = event.get("data", {})
                    if (
                        event.get("type") == "progress"
                        and isinstance(data.get("value"), int)
                        and isinstance(data.get("max"), int)
                        and data["max"] > 0
                    ):
                        if messages.full():
                            messages.get_nowait()
                        messages.put_nowait(f"正在生成（采样 {data['value']} / {data['max']}）")
                    if event.get("type") == "executing" and data.get("node"):
                        if messages.full():
                            messages.get_nowait()
                        node = (workflow or {}).get(str(data["node"]), {}).get("class_type")
                        labels = {
                            "CLIPTextEncode": "正在理解提示词",
                            "KSampler": "正在生成图片",
                            "SamplerCustomAdvanced": "正在生成视频",
                            "MiniMaxH3ImageToVideo": "正在理解提示词和首帧",
                            "MiniMaxH3ReferenceToVideo": "正在编码参考图片",
                            "SaveVideo": "正在编码 MP4 视频",
                            "LoadImage": "正在加载参考图",
                            "ImageScale": "正在调整参考图",
                            "VAEEncode": "正在编码参考图",
                            "VAEDecode": "正在解码图片",
                            "SaveImage": "正在保存图片",
                        }
                        messages.put_nowait(labels.get(node, "正在执行工作流"))
        except Exception:
            # WebSocket 断开时由历史接口继续核对，不能据此重复提交。
            return

    async def result(
        self,
        prompt_id: str,
        outputs: list[str],
        tick: Callable[[str], Awaitable[None]],
        messages: asyncio.Queue,
        timeout: float = 1800,
        media_kind: str = "image",
    ) -> bytes:
        deadline = time.monotonic() + timeout
        errors = 0
        message = "ComfyUI 已接收，正在加载模型或生成"
        while time.monotonic() < deadline:
            while not messages.empty():
                message = messages.get_nowait()
            await tick(message)
            try:
                response = await self.http.get(f"/history/{prompt_id}")
                response.raise_for_status()
                record = response.json().get(prompt_id)
                errors = 0
            except httpx.HTTPError:
                errors += 1
                if errors >= 5:
                    raise RuntimeError("ComfyUI 连接中断；结果不确定，请核对历史记录") from None
                await asyncio.sleep(min(2**errors, 10))
                continue
            if record:
                status = record.get("status", {})
                if status.get("status_str") == "error":
                    reason = "请查看 ComfyUI 日志"
                    for kind, detail in status.get("messages", []):
                        if kind == "execution_error":
                            reason = str(detail.get("exception_message", reason))[:300]
                    raise RuntimeError(f"ComfyUI 执行失败：{reason}")
                if status.get("completed"):
                    images = [
                        image
                        for node in outputs
                        for image in record.get("outputs", {}).get(node, {}).get("images", [])
                    ]
                    if len(images) != 1:
                        raise ValueError("预期生成 1 个结果，但输出数量不匹配")
                    image = images[0]
                    if image.get("type") != "output":
                        raise ValueError("工作流没有输出持久化结果")
                    for key in ("filename", "subfolder"):
                        path = PurePosixPath(image.get(key, ""))
                        if path.is_absolute() or ".." in path.parts:
                            raise ValueError("不安全的 ComfyUI 输出路径")
                    params = {key: image.get(key, "") for key in ("filename", "subfolder", "type")}
                    if media_kind == "video":
                        if not image["filename"].lower().endswith(".mp4"):
                            raise ValueError("H3 未输出 MP4")
                        return await limited_get(
                            self.http, "/view", params=params, limit=64 * 1024 * 1024
                        )
                    return validate_image(await limited_get(self.http, "/view", params=params))
            await asyncio.sleep(2)
        raise TimeoutError("生成超过 30 分钟，结果不确定，请核对 ComfyUI 历史")
