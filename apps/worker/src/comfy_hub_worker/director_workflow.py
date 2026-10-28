"""Reviewed single-shot Director graphs; no application scheduling or media transport."""

import copy
import json
import re
from pathlib import Path, PurePosixPath

from comfy_hub_worker.director_contract import DIRECTOR_REVISION, director_metadata
from comfy_hub_worker.mapping import WorkflowError, h3_parameters

MODES = {"h3_t2v", "h3_i2v", "h3_r2v"}


def _read_object(directory: Path, filename: str) -> dict:
    path = (directory / filename).resolve()
    if path.parent != directory.resolve():
        raise WorkflowError("导演台模板路径越界")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorkflowError("导演台工作流包缺失或损坏") from exc
    if not isinstance(data, dict):
        raise WorkflowError("导演台工作流包格式无效")
    return data


def _asset_nodes(workflow: dict, mode: str, assets: list, video_audio: bool) -> None:
    if not isinstance(assets, list):
        raise WorkflowError("参考素材必须为列表")
    group = workflow["5"]["inputs"]
    # Templates remain directly editable examples; runtime uses only reviewed assets.
    for node_id in list(workflow):
        if workflow[node_id]["class_type"] in {"LoadImage", "LoadVideo", "LoadAudio"}:
            del workflow[node_id]
    for key in list(group):
        if key in {"first_frame", "last_frame"} or key.startswith("ref_") and "." in key:
            del group[key]
    seen = set()
    # Numbered tags follow slot indices even if a caller's descriptor list is reordered.
    ordered = sorted(assets, key=lambda a: str(a.get("key", "")) if isinstance(a, dict) else "")
    for asset in ordered:
        if not isinstance(asset, dict):
            raise WorkflowError("参考素材描述无效")
        key, kind, path = (asset.get(k) for k in ("key", "kind", "path"))
        if (
            not isinstance(key, str)
            or key in seen
            or not isinstance(path, str)
            or not path
            or len(path) > 512
            or PurePosixPath(path).is_absolute()
            or any(p in {".", "..", ""} for p in path.split("/"))
            or any(c in path for c in "\\:\x00\r\n?#[]")
        ):
            raise WorkflowError("参考素材编号或路径无效")
        node = f"hub:{key}"
        seen.add(key)
        if mode == "h3_i2v" and key in {"first_frame", "last_frame"} and kind == "image":
            workflow[node] = {"class_type": "LoadImage", "inputs": {"image": path}}
            group[key] = [node, 0]
        elif mode == "h3_r2v" and kind == "image" and re.fullmatch(r"ref_image_[0-8]", key):
            workflow[node] = {"class_type": "LoadImage", "inputs": {"image": path}}
            group[f"ref_images.{key}"] = [node, 0]
        elif mode == "h3_r2v" and kind == "video" and re.fullmatch(r"ref_video_[0-2]", key):
            workflow[node] = {"class_type": "LoadVideo", "inputs": {"file": path}}
            workflow[node + ":parts"] = {
                "class_type": "GetVideoComponents",
                "inputs": {"video": [node, 0]},
            }
            group[f"ref_videos.{key}"] = [node + ":parts", 0]
            if type(asset.get("has_audio", False)) is not bool:
                raise WorkflowError("参考视频音轨标记无效")
            if video_audio and asset.get("has_audio", False):
                index = key.rsplit("_", 1)[-1]
                group[f"ref_video_audios.ref_video_audio_{index}"] = [node + ":parts", 1]
        elif mode == "h3_r2v" and kind == "audio" and re.fullmatch(r"ref_audio_[0-2]", key):
            workflow[node] = {"class_type": "LoadAudio", "inputs": {"audio": path}}
            group[f"ref_audios.{key}"] = [node, 0]
        else:
            raise WorkflowError("当前模式不支持这种参考素材")
    if mode == "h3_i2v" and "first_frame" not in seen:
        raise WorkflowError("请上传首帧图片")
    if mode == "h3_r2v" and not seen:
        raise WorkflowError("请至少上传一项参考素材")
    for prefix in ("ref_image_", "ref_video_", "ref_audio_"):
        indices = sorted(int(k.rsplit("_", 1)[-1]) for k in seen if k.startswith(prefix))
        if indices != list(range(len(indices))):
            raise WorkflowError("参考素材编号必须连续")


def load_director_workflow(directory: Path, mode: str, values: dict) -> tuple[dict, list[str]]:
    if mode not in MODES:
        raise WorkflowError("导演台只支持 H3 视频模式")
    if values.get("workflowRevision") != DIRECTOR_REVISION:
        raise WorkflowError("导演台工作流修订缺失或不可用")
    if values.get("workflowOutputNodeIds") not in (None, ["8"]):
        raise WorkflowError("任务固定的输出与导演台版本不匹配")
    director_metadata(directory, mode)
    registry = _read_object(directory, "h3_capabilities.json")
    try:
        engine = registry["engines"]["director"]
        capability = engine["modes"][mode]
        valid = (
            registry["schemaVersion"] == 1
            and engine["revision"] == DIRECTOR_REVISION
            and capability["available"] is True
        )
    except (KeyError, TypeError) as exc:
        raise WorkflowError("导演台能力注册表无效") from exc
    if not valid:
        raise WorkflowError("导演台模式尚未验收或不可用")
    try:
        values = h3_parameters(values)
    except (KeyError, TypeError) as exc:
        raise WorkflowError("导演台参数缺失或格式无效") from exc
    for flag in ("sound", "referenceVideoAudio"):
        if type(values.get(flag, True)) is not bool:
            raise WorkflowError(f"声音开关类型无效：{flag}")
    mapping = _read_object(directory, capability["mapping"])
    if mapping.get("version") != "1" or mapping.get("revision") != DIRECTOR_REVISION:
        raise WorkflowError("导演台映射版本不可用")
    if mapping.get("template") != capability["template"]:
        raise WorkflowError("导演台模板与能力注册表不一致")
    workflow = copy.deepcopy(_read_object(directory, mapping["template"]))
    if values["refImageSize"] not in ("match", "max"):
        raise WorkflowError("参考图尺寸不支持")
    # Director has repeated fields (prompt/fps); mirror those explicitly below.
    types = {"string": str, "integer": int, "number": (int, float)}
    for name, spec in mapping["fields"].items():
        value = values.get(name)
        expected = types.get(spec["type"])
        if (
            expected is None
            or isinstance(value, bool)
            or not isinstance(value, expected)
            or isinstance(value, str)
            and (not value.strip() or len(value) > 2000)
            or "enum" in spec
            and value not in spec["enum"]
            or "min" in spec
            and not spec["min"] <= value <= spec["max"]
        ):
            raise WorkflowError(f"导演台参数无效：{name}")
        try:
            old = workflow[spec["node"]]["inputs"][spec["input"]]
            if isinstance(old, list) or not isinstance(old, expected):
                raise KeyError(name)
            workflow[spec["node"]]["inputs"][spec["input"]] = value
        except (KeyError, TypeError) as exc:
            raise WorkflowError(f"映射节点或字段不存在：{name}") from exc
    group, director = workflow["5"]["inputs"], workflow["6"]["inputs"]
    group["prompt"] = values["prompt"]
    # Feed the ALIGNED frame duration, avoiding the plugin's round() vs Hub ceil().
    group["duration_sec"] = values["frames"] / values["fps"]
    if mode == "h3_r2v":
        group["ref_image_size"] = values["refImageSize"]
    director["ref_max_size"] = max(values["width"], values["height"])
    director["timeline_data"] = json.dumps(
        {
            "version": 4,
            "frameRate": 24,
            "totalFrames": values["frames"],
            "width": values["width"],
            "height": values["height"],
            "output": {
                "mode": "fixed",
                "width": values["width"],
                "height": values["height"],
                "longEdge": director["ref_max_size"],
                "exportMode": "all",
                "maxExportFrames": 0,
                "audioMode": "generate",
                "refImageSize": values["refImageSize"],
            },
            "global": {"prompt": values["prompt"], "commonEnabled": False},
            "segments": [],
        },
        ensure_ascii=False,
    )
    _asset_nodes(workflow, mode, values.get("assets", []), values.get("referenceVideoAudio", True))
    if mapping.get("outputs") != ["8"] or workflow.get("8", {}).get("class_type") != "SaveVideo":
        raise WorkflowError("导演台输出节点必须为 SaveVideo 8")
    return workflow, mapping["outputs"]
