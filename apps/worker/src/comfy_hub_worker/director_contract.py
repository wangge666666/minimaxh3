"""Metadata boundary for the application adapter and the reviewed graph loader."""

import hashlib
import json
from pathlib import Path

from comfy_hub_worker.mapping import WorkflowError

DIRECTOR_REVISION = "director-v1.0.0"
H3_MODES = {"h3_t2v", "h3_i2v", "h3_r2v"}


def native_workflow_revision(directory: Path, mode: str) -> str:
    """Match director-app's native-sha256 protocol on Windows and Unix."""
    if mode not in H3_MODES | {"text", "img2img"}:
        raise WorkflowError("不支持的工作流")
    stem = mode if mode.startswith("h3_") else f"z_image_turbo_{mode}"
    digest = hashlib.sha256()
    try:
        for name in (f"{stem}_api.json", f"{stem}_mapping.json"):
            text = (directory / name).read_text(encoding="utf-8").replace("\r\n", "\n")
            digest.update((name + "\0" + text + "\0").encode("utf-8"))
    except OSError as exc:
        raise WorkflowError("原生工作流文件缺失或不可用") from exc
    return "native-sha256:" + digest.hexdigest()


def director_metadata(directory: Path, mode: str) -> tuple[str, list[str]]:
    """Resolve only this installed, accepted revision; never choose a replacement."""
    if mode not in H3_MODES:
        raise WorkflowError("导演台只支持 H3 视频模式")
    try:
        registry = json.loads((directory / "h3_capabilities.json").read_text(encoding="utf-8"))
        engine = registry["engines"]["director"]
        capability = engine["modes"][mode]
        if registry["schemaVersion"] != 1 or engine["revision"] != DIRECTOR_REVISION:
            raise WorkflowError("导演台能力注册表版本无效")
        if capability["available"] is not True:
            raise WorkflowError("导演台模式尚未验收或不可用")
        if capability["revision"] != DIRECTOR_REVISION:
            raise WorkflowError("导演台工作流修订不可用")
        builder_files = {"mapping.py", "director_workflow.py", "director_contract.py"}
        if set(engine["builderFilesSha256"]) != builder_files:
            raise WorkflowError("导演台构图层版本信息无效")
        for name in builder_files:
            source = Path(__file__).with_name(name).read_text(encoding="utf-8")
            if (
                hashlib.sha256(source.replace("\r\n", "\n").encode()).hexdigest()
                != engine["builderFilesSha256"][name]
            ):
                raise WorkflowError("导演台构图层版本不匹配，不能替换排队任务")
        stem = mode.replace("h3_", "h3_director_", 1)
        if (
            capability["template"] != f"{stem}_api.json"
            or capability["mapping"] != f"{stem}_mapping.json"
        ):
            raise WorkflowError("导演台模板或映射路径无效")
        sources = []
        for name in (capability["template"], capability["mapping"]):
            source = (directory / name).read_text(encoding="utf-8").replace("\r\n", "\n")
            if hashlib.sha256(source.encode()).hexdigest() != capability["fileSha256"][name]:
                raise WorkflowError("导演台工作流文件校验失败，不能替换排队任务的模板")
            sources.append(json.loads(source))
        template, mapping = sources
        if (
            mapping["version"] != "1"
            or mapping["revision"] != DIRECTOR_REVISION
            or mapping["template"] != capability["template"]
            or mapping["outputs"] != ["8"]
            or capability["outputNodeIds"] != ["8"]
            or template["8"]["class_type"] != "SaveVideo"
        ):
            raise WorkflowError("导演台工作流输出或映射契约无效")
        return DIRECTOR_REVISION, ["8"]
    except WorkflowError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise WorkflowError("导演台工作流包缺失或损坏") from exc
