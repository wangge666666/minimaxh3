import asyncio
import contextlib
import json
import logging
import os
import subprocess
from pathlib import Path

import httpx

from comfy_hub_worker.comfy import Comfy, limited_get
from comfy_hub_worker.config import Settings
from comfy_hub_worker.mapping import load_workflow
from comfy_hub_worker.references import normalize_reference
from comfy_hub_worker.video import finalize_video, make_poster
from comfy_hub_worker.workflow_dispatch import prepare_submission, recovery_outputs

log = logging.getLogger("comfy_hub_worker")


class Journal:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "current.json"

    def read(self):
        return json.loads(self.path.read_text()) if self.path.exists() else None

    def save(self, data: dict):
        temp = self.path.with_suffix(".tmp")
        with temp.open("w") as stream:
            os.chmod(temp, 0o600)
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(self.path)

    def clear(self):
        self.path.unlink(missing_ok=True)


@contextlib.contextmanager
def single_process(directory: Path):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "worker.lock").open("a+b") as file:
        try:
            if os.name == "nt":
                import msvcrt

                file.seek(0)
                file.write(b"0")
                file.flush()
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("同一状态目录已有 Worker 运行") from None
        yield


class Cloud:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    async def post(self, path: str, data: dict):
        # claim 不重试，避免领取响应丢失后悄悄领取第二个任务。
        for attempt in range(3):
            try:
                response = await self.http.post(f"/api/mvp/worker/{path}", json=data)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as exc:
                if (
                    path == "claim"
                    or (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500)
                    or attempt == 2
                ):
                    raise
                await asyncio.sleep(2**attempt)

    async def progress(self, job: dict, status: str, message: str, prompt_id=None):
        payload = {
            "id": job["id"],
            "lease": job["lease"],
            "status": status,
            "message": message[:500],
        }
        if prompt_id:
            payload["prompt_id"] = prompt_id
        return await self.post("progress", payload)

    async def complete(self, job: dict, data: bytes):
        headers = {"x-job-id": job["id"], "x-lease-id": job["lease"]}
        video = job["mode"].startswith("h3_")
        poster = None
        if video:
            try:
                poster = await asyncio.to_thread(make_poster, data)
            except (ValueError, OSError, subprocess.SubprocessError):
                log.warning("封面提取失败，保留有效视频结果")
        payload = (
            {
                "files": {
                    "video": ("result.mp4", data, "video/mp4"),
                    "poster": ("poster.jpg", poster, "image/jpeg"),
                }
            }
            if poster
            else {"content": data}
        )
        if not poster:
            headers["Content-Type"] = "video/mp4" if video else "image/png"
        for attempt in range(3):
            try:
                response = await self.http.post(
                    "/api/mvp/worker/complete", headers=headers, **payload
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError:
                if attempt == 2:
                    raise
                await asyncio.sleep(2**attempt)


def workflow_values(job: dict) -> dict:
    values = {"image": "validated-reference.png", "frames": 124, "fps": 24, "steps": 20, **job}
    if "assets" in job:
        values["assets"] = [{**a, "path": f"hub/{a['key']}.png"} for a in job["assets"]]
    return values


async def export_with_lease(data: bytes, job: dict, cloud: Cloud):
    async def renew():
        while True:
            await asyncio.sleep(20)
            await cloud.progress(job, "uploading", "正在裁剪、解码并验证视频", job["prompt_id"])

    task = asyncio.create_task(renew())
    try:
        return await asyncio.to_thread(finalize_video, data, job)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def execute(job: dict, journal: Journal, cloud: Cloud, comfy: Comfy, settings: Settings):
    prompt_id = job.get("prompt_id")
    if job.get("submission_pending") and not prompt_id:
        prompt_id = await comfy.find_submission(job["id"])
        if not prompt_id:
            raise RuntimeError(
                "上次提交结果不确定，未在队列与最近历史中找到。请人工核对，禁止直接重试"
            )
    workflow = None
    if prompt_id:
        outputs = recovery_outputs(job, settings.workflow_directory)
        job.update(prompt_id=prompt_id, workflowOutputNodeIds=outputs)
        journal.save(job)
    else:
        prepare_submission(
            job, settings.workflow_directory,
            director_enabled=getattr(settings, "director_enabled", False),
        )
        values = workflow_values(job)
        workflow, outputs = load_workflow(settings.workflow_directory, job["mode"], values)
    state = await cloud.progress(job, "running", "正在准备工作流", prompt_id)
    if state["status"] != "running":
        raise RuntimeError("云端任务状态已变化")
    if not prompt_id:
        await comfy.check(workflow)
        if job.get("assets"):
            prepared = []
            for asset in job["assets"]:
                await cloud.progress(job, "running", f"正在接收参考素材：{asset['key']}")
                data = await limited_get(
                    cloud.http,
                    f"/api/mvp/worker/input/{job['id']}/{asset['key']}",
                    limit=20 * 1024 * 1024,
                    headers={"x-lease-id": job["lease"]},
                )
                await cloud.progress(job, "running", f"正在解码参考素材：{asset['key']}")
                canvas = None
                if asset["key"] in {"first_frame", "last_frame"}:
                    canvas = tuple((job[k] + 31) // 32 * 32 for k in ("width", "height"))
                data, suffix, mime, has_audio = await asyncio.to_thread(
                    normalize_reference,
                    data,
                    asset["kind"],
                    canvas=canvas,
                    max_duration=job.get("frames", 124) / 24 if asset["kind"] == "video" else 15,
                )
                await cloud.progress(job, "running", f"正在上传已校验素材：{asset['key']}")
                path = await comfy.upload_media(f"{job['id']}_{asset['key']}{suffix}", data, mime)
                prepared.append({**asset, "path": path, "has_audio": has_audio})
                if asset["kind"] == "image":
                    values["image"] = path
            values["assets"] = prepared
            workflow, outputs = load_workflow(settings.workflow_directory, job["mode"], values)
        elif job["mode"] in {"img2img", "h3_i2v", "h3_r2v"}:
            reference = await limited_get(
                cloud.http,
                f"/api/mvp/worker/input/{job['id']}",
                headers={"x-lease-id": job["lease"]},
            )
            values["image"] = await comfy.upload(job["id"], reference)
            workflow, outputs = load_workflow(settings.workflow_directory, job["mode"], values)
        # Media normalization may take time. Refuse a template/configuration
        # replacement between the initial check and the actual submission.
        prepare_submission(
            job, settings.workflow_directory,
            director_enabled=getattr(settings, "director_enabled", False),
        )
        if outputs != job["workflowOutputNodeIds"]:
            raise ValueError("工作流输出与持久化版本不匹配，禁止提交")
        job["submission_pending"] = True
        journal.save(job)  # 在 /prompt 之前持久化意图。
        try:
            prompt_id = await comfy.submit(workflow, job["id"])
        except httpx.HTTPError:
            prompt_id = await comfy.find_submission(job["id"])
            if not prompt_id:
                raise RuntimeError(
                    "ComfyUI 提交失败或结果不确定，请检查队列与历史后再操作"
                ) from None
        job["prompt_id"] = prompt_id
        journal.save(job)
        await cloud.progress(job, "running", "ComfyUI 已接收任务", prompt_id)
    job["prompt_id"] = prompt_id
    journal.save(job)
    messages = asyncio.Queue(maxsize=1)
    watcher = asyncio.create_task(comfy.watch_nodes(job["id"], messages, workflow))

    async def tick(message):
        await cloud.progress(job, "running", message, prompt_id)

    try:
        png = await comfy.result(
            prompt_id,
            outputs,
            tick,
            messages,
            media_kind="video" if job["mode"].startswith("h3_") else "image",
        )
    finally:
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
    await cloud.progress(job, "uploading", "正在验证并保存结果", prompt_id)
    if job["mode"].startswith("h3_"):
        png = await export_with_lease(png, job, cloud)
    # Completing an existing lease is idempotent; no GPU resubmission.
    await cloud.complete(job, png)
    journal.clear()
    log.info("任务 %s completed", job["id"])


async def online(client: httpx.AsyncClient) -> bool:
    try:
        response = await client.get("/system_stats", timeout=5)
        response.raise_for_status()
        return isinstance(response.json().get("system"), dict)
    except (httpx.HTTPError, ValueError):
        return False


async def run(settings: Settings, once=False):
    if settings.max_concurrent_jobs != 1:
        raise ValueError("个人私网版本只支持 MAX_CONCURRENT_JOBS=1")
    journal = Journal(settings.worker_state_directory)
    with single_process(settings.worker_state_directory):
        async with (
            httpx.AsyncClient(
                base_url=str(settings.cloud_api_base_url),
                timeout=20,
                trust_env=False,
                headers={"Authorization": "Bearer " + settings.worker_api_token.get_secret_value()},
            ) as http,
            httpx.AsyncClient(
                base_url=str(settings.comfyui_base_url), timeout=30, trust_env=False
            ) as local_http,
            httpx.AsyncClient(
                base_url=str(settings.h3_comfyui_base_url or settings.comfyui_base_url),
                timeout=30,
                trust_env=False,
            ) as h3_http,
        ):
            cloud = Cloud(http)
            # 所有工作流仍从本机审核过的固定文件读取，不接收用户 JSON。
            values = {
                "prompt": "check",
                "seed": 0,
                "width": 512,
                "height": 512,
                "denoise": 0.6,
                "image": "check.png",
                "frames": 124,
                "fps": 24,
            }
            if journal.read() is None:
                for mode in (("text", "img2img") if settings.image_generation_enabled else ()):
                    load_workflow(settings.workflow_directory, mode, values)
                if settings.h3_comfyui_base_url:
                    for mode in ("h3_i2v", "h3_r2v", "h3_t2v"):
                        load_workflow(
                            settings.workflow_directory, mode,
                            {**values, "width": 640, "height": 384},
                        )
            log.info("Worker 启动；优先恢复持久任务，新提交前校验固定工作流")
            while True:
                job = None
                try:
                    local_ok = (
                        await online(local_http) if settings.image_generation_enabled else False
                    )
                    h3_ok = bool(settings.h3_comfyui_base_url) and await online(h3_http)
                    await cloud.post(
                        "heartbeat",
                        {
                            "worker_id": str(settings.worker_id),
                            "local_online": local_ok,
                            "h3_online": h3_ok,
                        },
                    )
                    job = journal.read()
                    if job:
                        response = await http.get("/api/mvp/state")
                        response.raise_for_status()
                        current = next(
                            (j for j in response.json()["jobs"] if j["id"] == job["id"]), None
                        )
                        if not current or current["status"] in {"completed", "failed", "canceled"}:
                            journal.clear()
                            job = None
                    if job is None:
                        available = (["text", "img2img"] if local_ok else []) + (
                            ["h3_i2v", "h3_r2v", "h3_t2v"] if h3_ok else []
                        )
                        job = (
                            await cloud.post(
                                "claim",
                                {
                                    "worker_id": str(settings.worker_id),
                                    "available_modes": available,
                                },
                            )
                        )["job"]
                        if job:
                            journal.save(job)
                    if job:
                        video = job["mode"].startswith("h3_")
                        if video and not settings.h3_comfyui_base_url:
                            raise ValueError("尚未配置 H3_COMFYUI_BASE_URL")
                        comfy = Comfy(h3_http if video else local_http)
                        log.info(
                            "任务 %s 执行或恢复，目标 %s",
                            job["id"],
                            "Windows H3" if video else "Mac Z-Image",
                        )
                        await resume_or_execute(job, journal, cloud, comfy, settings)
                    if once:
                        return
                except httpx.HTTPError:
                    log.warning("网络或接口错误；保留当前日志，不重新提交生成任务")
                    if once:
                        raise
                except Exception as exc:
                    log.error(
                        "任务 %s 失败：%s", job["id"] if job else "startup", type(exc).__name__
                    )
                    if job:
                        message = str(exc)[:450].replace(
                            settings.worker_api_token.get_secret_value(), "[已隐藏]"
                        )
                        try:
                            await cloud.progress(job, "failed", message or "执行失败，请查看日志")
                            journal.clear()
                        except httpx.HTTPError:
                            pass
                    if once:
                        raise
                await asyncio.sleep(settings.poll_interval_seconds)


async def resume_or_execute(job, journal, cloud, comfy, settings):
    response = await cloud.http.get("/api/mvp/state")
    response.raise_for_status()
    current = next((j for j in response.json()["jobs"] if j["id"] == job["id"]), None)
    if current:
        for key in ("mode", "workflowEngine", "workflowRevision", "prompt_id"):
            if current.get(key) is not None and job.get(key) is not None:
                if current[key] != job[key]:
                    raise ValueError("恢复信息与云端任务不一致，请人工核对；禁止重新提交")
            if current.get(key) is not None:
                job[key] = current[key]
        if not job.get("workflowOutputNodeIds") and current.get("workflowOutputNodeIds"):
            job["workflowOutputNodeIds"] = current["workflowOutputNodeIds"]
    if current and current["status"] == "uploading":
        if not job.get("prompt_id"):
            raise ValueError("上传恢复缺少原 prompt ID，禁止重新提交")
        outputs = recovery_outputs(job, settings.workflow_directory)

        async def tick(message):
            await cloud.progress(job, "uploading", message, job["prompt_id"])

        video = job["mode"].startswith("h3_")
        data = await comfy.result(
            job["prompt_id"],
            outputs,
            tick,
            asyncio.Queue(maxsize=1),
            media_kind="video" if video else "image",
        )
        if video:
            data = await export_with_lease(data, job, cloud)
        await cloud.complete(job, data)
        journal.clear()
        return
    await execute(job, journal, cloud, comfy, settings)
