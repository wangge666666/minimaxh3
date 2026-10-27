import copy
import json
import math
from pathlib import Path


class WorkflowError(ValueError):
    pass


def h3_parameters(values: dict) -> dict:
    values = {"frames": 124, "fps": 24, "steps": 20, "refImageSize": "match", **values}
    width, height = values["width"], values["height"]
    sizes = {(640, 384)}  # Historical jobs remain recoverable.
    for edge in (360, 576, 720):
        long = edge * 16 // 9
        sizes.update(((edge, edge), (long, edge), (edge, long)))
    if (width, height) not in sizes or any(type(v) is not int for v in (width, height)):
        raise WorkflowError("视频比例或分辨率不支持")
    frames = values["frames"]
    if type(frames) is not int or not 107 <= frames <= 362 or frames % 17 != 5:
        raise WorkflowError("视频帧数不支持")
    requested = values.get("durationSeconds")
    if requested is not None:
        if (
            type(requested) not in (int, float)
            or not math.isfinite(requested)
            or not 4 <= requested <= 15
        ):
            raise WorkflowError("时长必须在 4–15 秒之间")
        aligned = 5 + 17 * math.ceil((math.ceil(requested * 24 - 1e-9) - 5) / 17)
        if aligned != frames:
            raise WorkflowError("帧数与所选时长不一致")
    if values["fps"] != 24 or values["steps"] not in (12, 20, 30):
        raise WorkflowError("视频帧率或步数不支持")
    values["width"] = (width + 31) // 32 * 32
    values["height"] = (height + 31) // 32 * 32
    return values


def attach_h3_assets(workflow: dict, mode: str, assets: list[dict], video_audio: bool):
    conditioner_id, conditioner = next(
        (k, v)
        for k, v in workflow.items()
        if v["class_type"] in {"MiniMaxH3ImageToVideo", "MiniMaxH3ReferenceToVideo"}
    )
    inputs = conditioner["inputs"]
    # Remove the handoff's single image before assembling the reviewed node types.
    for key in list(workflow):
        if workflow[key]["class_type"] == "LoadImage":
            del workflow[key]
    for key in list(inputs):
        if key in {"first_frame", "last_frame"} or key.startswith("ref_") and "." in key:
            del inputs[key]
    seen = set()
    for asset in assets:
        key, kind, path = asset["key"], asset["kind"], asset["path"]
        if (
            key in seen
            or not isinstance(path, str)
            or ".." in path
            or "\\" in path
            or path.startswith("/")
        ):
            raise WorkflowError("参考素材编号或路径无效")
        seen.add(key)
        node = f"hub:{key}"
        if mode == "h3_i2v" and key in {"first_frame", "last_frame"} and kind == "image":
            workflow[node] = {"class_type": "LoadImage", "inputs": {"image": path}}
            inputs[key] = [node, 0]
        elif mode == "h3_r2v" and kind == "image" and key in {f"ref_image_{i}" for i in range(9)}:
            workflow[node] = {"class_type": "LoadImage", "inputs": {"image": path}}
            inputs[f"ref_images.{key}"] = [node, 0]
        elif mode == "h3_r2v" and kind == "video" and key in {f"ref_video_{i}" for i in range(3)}:
            workflow[node] = {"class_type": "LoadVideo", "inputs": {"file": path}}
            workflow[node + ":parts"] = {
                "class_type": "GetVideoComponents",
                "inputs": {"video": [node, 0]},
            }
            inputs[f"ref_videos.{key}"] = [node + ":parts", 0]
            if video_audio and asset.get("has_audio"):
                index = key.rsplit("_", 1)[-1]
                inputs[f"ref_video_audios.ref_video_audio_{index}"] = [node + ":parts", 1]
        elif mode == "h3_r2v" and kind == "audio" and key in {f"ref_audio_{i}" for i in range(3)}:
            workflow[node] = {"class_type": "LoadAudio", "inputs": {"audio": path}}
            inputs[f"ref_audios.{key}"] = [node, 0]
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


def load_workflow(directory: Path, mode: str, values: dict) -> tuple[dict, list[str]]:
    if mode not in {"text", "img2img", "h3_i2v", "h3_r2v", "h3_t2v"}:
        raise WorkflowError("不支持的工作流")
    if mode.startswith("h3_"):
        values = h3_parameters(values)
    stem = mode if mode.startswith("h3_") else f"z_image_turbo_{mode}"
    mapping = json.loads((directory / f"{stem}_mapping.json").read_text())
    template = (directory / mapping["template"]).resolve()
    if template.parent != directory.resolve():
        raise WorkflowError("模板路径越界")
    workflow = copy.deepcopy(json.loads(template.read_text()))
    if mapping.get("version") != "1":
        raise WorkflowError("不支持的映射版本")
    for name, spec in mapping["fields"].items():
        node = workflow.get(spec["node"], {})
        if spec["input"] not in node.get("inputs", {}):
            raise WorkflowError(f"映射节点或字段不存在：{name}")
        if name not in values:
            raise WorkflowError(f"缺少参数：{name}")
        value = values[name]
        types = {"string": str, "integer": int, "number": (int, float)}
        expected = types.get(spec["type"])
        if expected is None or isinstance(value, bool) or not isinstance(value, expected):
            raise WorkflowError(f"参数类型不匹配：{name}")
        old = node["inputs"][spec["input"]]
        if isinstance(old, list) or not isinstance(old, expected):
            raise WorkflowError(f"模板字段类型不匹配：{name}")
        if spec["type"] == "string" and (not value or len(value) > 2000):
            raise WorkflowError(f"字符串参数无效：{name}")
        if "enum" in spec and value not in spec["enum"]:
            raise WorkflowError(f"参数不在允许列表：{name}")
        if "min" in spec and not spec["min"] <= value <= spec["max"]:
            raise WorkflowError(f"参数超出范围：{name}")
        node["inputs"][spec["input"]] = value
    if mode.startswith("h3_") and "assets" in values:
        attach_h3_assets(workflow, mode, values["assets"], values.get("referenceVideoAudio", True))
    for node_id in mapping["outputs"]:
        expected_output = "SaveVideo" if mapping.get("output_kind") == "video" else "SaveImage"
        if workflow.get(node_id, {}).get("class_type") != expected_output:
            raise WorkflowError(f"输出节点必须为 {expected_output}")
    return workflow, mapping["outputs"]
