"""Validate persisted application metadata before constructing a reviewed graph."""

import hashlib
import json
import re
from pathlib import Path

from comfy_hub_worker.director_contract import director_metadata

MODES = {"text", "img2img", "h3_t2v", "h3_i2v", "h3_r2v"}


def engine_for(job: dict) -> str:
    engine = job.get("workflowEngine", "native")
    if engine not in ("native", "director"):
        raise ValueError("未知工作流引擎，禁止降级或重新提交")
    return engine


def output_ids(value) -> list[str]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 16
        or any(
            not isinstance(v, str) or not re.fullmatch(r"[a-zA-Z0-9_:-]{1,128}", v) for v in value
        )
        or len(set(value)) != len(value)
    ):
        raise ValueError("持久化输出信息无效，禁止重新提交")
    return value


def native_metadata(directory: Path, mode: str) -> tuple[str, list[str]]:
    if mode not in MODES:
        raise ValueError("不支持的工作流")
    stem = mode if mode.startswith("h3_") else f"z_image_turbo_{mode}"
    digest = hashlib.sha256()
    sources = []
    try:
        for name in (f"{stem}_api.json", f"{stem}_mapping.json"):
            source = (directory / name).read_text(encoding="utf-8").replace("\r\n", "\n")
            digest.update((name + "\0" + source + "\0").encode("utf-8"))
            sources.append(json.loads(source))
        template, mapping = sources
        outputs = output_ids(mapping["outputs"])
        if mapping["version"] != "1" or mapping["template"] != f"{stem}_api.json":
            raise ValueError()
        expected = "SaveVideo" if mode.startswith("h3_") else "SaveImage"
        if any(template.get(node, {}).get("class_type") != expected for node in outputs):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("原生工作流文件缺失或不可用，请检查安装") from None
    return "native-sha256:" + digest.hexdigest(), outputs


def validate_assets(job: dict):
    """Reject unsupported descriptors before downloading/uploading any reference."""
    assets = job.get("assets", [])
    if not isinstance(assets, list):
        raise ValueError("参考素材描述无效")
    seen = set()
    mode = job["mode"]
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("参考素材描述无效")
        key, kind = asset.get("key"), asset.get("kind")
        if not isinstance(key, str) or not isinstance(kind, str):
            raise ValueError("参考素材描述无效")
        allowed = (
            mode == "img2img" and key == "reference" and kind == "image"
            or mode == "h3_i2v" and key in {"first_frame", "last_frame"} and kind == "image"
            or mode == "h3_r2v" and any(
                kind == category and key in {f"ref_{category}_{i}" for i in range(limit)}
                for category, limit in (("image", 9), ("video", 3), ("audio", 3))
            )
        )
        if not allowed or key in seen:
            raise ValueError("当前模式不支持这种参考素材或编号重复；不能丢弃素材")
        seen.add(key)
    for category in ("image", "video", "audio"):
        keys = sorted(k for k in seen if k.startswith(f"ref_{category}_"))
        if keys != [f"ref_{category}_{i}" for i in range(len(keys))]:
            raise ValueError("参考素材编号必须连续")
    if assets and mode == "h3_i2v" and "first_frame" not in seen:
        raise ValueError("请上传首帧图片")


def prepare_submission(job: dict, directory: Path, *, director_enabled=False):
    engine = engine_for(job)
    if engine == "director":
        if not director_enabled:
            raise ValueError("导演台尚未启用，禁止提交或降级")
        revision, outputs = director_metadata(directory, job["mode"])
        if job.get("workflowRevision") is None or job.get("workflowOutputNodeIds") is None:
            raise ValueError("导演台任务缺少固定版本或输出，禁止重新选择版本")
        if job["mode"] != "h3_t2v" and not job.get("assets"):
            raise ValueError("导演台参考任务缺少素材")
    else:
        revision, outputs = native_metadata(directory, job["mode"])
    if job.get("workflowRevision") is not None and job["workflowRevision"] != revision:
        raise ValueError("任务固定的工作流版本不可用，禁止使用当前模板替换")
    if job.get("workflowOutputNodeIds") is not None:
        if output_ids(job["workflowOutputNodeIds"]) != outputs:
            raise ValueError("任务固定的输出与工作流版本不匹配")
    validate_assets(job)
    job.update(workflowEngine=engine, workflowRevision=revision, workflowOutputNodeIds=outputs)


def recovery_outputs(job: dict, directory: Path) -> list[str]:
    engine = engine_for(job)
    if "workflowOutputNodeIds" in job:
        return output_ids(job["workflowOutputNodeIds"])
    if engine != "native":
        raise ValueError("缺少原任务的持久化输出信息，请人工核对；禁止重新提交")
    # Legacy native journals predate output snapshots. Read only their fixed
    # output mapping; do not build a graph or apply today's capability gate.
    mode = job["mode"]
    if mode not in MODES:
        raise ValueError("不支持的工作流")
    stem = mode if mode.startswith("h3_") else f"z_image_turbo_{mode}"
    mapping = json.loads((directory / f"{stem}_mapping.json").read_text(encoding="utf-8"))
    return output_ids(mapping["outputs"])
