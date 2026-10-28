"""Contract and executed-path checks for the three reviewed Director entry points."""

import hashlib
import json
from pathlib import Path

import pytest

from comfy_hub_worker.director_contract import director_metadata, native_workflow_revision
from comfy_hub_worker.director_workflow import DIRECTOR_REVISION
from comfy_hub_worker.mapping import WorkflowError, load_workflow

DIRECTORY = Path(__file__).resolve().parents[3] / "workflows"
VALUES = {
    "prompt": "The subject in <Picture 1> moves as in <Video 1>, with <Audio 1>.",
    "seed": 42,
    "width": 640,
    "height": 360,
    "frames": 124,
    "fps": 24,
    "steps": 20,
    "durationSeconds": 5,
    "workflowEngine": "director",
    "workflowRevision": DIRECTOR_REVISION,
    "refImageSize": "match",
}


def asset(key, kind=None, **extra):
    kind = kind or ("image" if key in {"first_frame", "last_frame"} else key.split("_")[1])
    return {"key": key, "kind": kind, "path": f"hub/{key}.bin", **extra}


@pytest.fixture
def candidate(tmp_path):
    # A pending release can be exercised only in this explicitly isolated test copy.
    for source in DIRECTORY.glob("*.json"):
        (tmp_path / source.name).write_bytes(source.read_bytes())
    registry = json.loads((tmp_path / "h3_capabilities.json").read_text(encoding="utf-8"))
    for mode in registry["engines"]["director"]["modes"].values():
        mode["available"] = True
    (tmp_path / "h3_capabilities.json").write_text(json.dumps(registry), encoding="utf-8")
    return tmp_path


def load(directory, mode="h3_r2v", assets=None, **extra):
    if assets is None:
        assets = (
            [asset("ref_image_0")]
            if mode == "h3_r2v"
            else ([asset("first_frame")] if mode == "h3_i2v" else [])
        )
    return load_workflow(directory, mode, {**VALUES, "assets": assets, **extra})


def ancestors(graph, node):
    found = set()

    def visit(node_id):
        if node_id in found:
            return
        found.add(node_id)
        for value in graph[node_id]["inputs"].values():
            if isinstance(value, list):
                visit(value[0])

    visit(node)
    return found


@pytest.mark.parametrize("mode", ["h3_t2v", "h3_i2v", "h3_r2v"])
def test_models_group_conditioning_and_audio_reach_saved_video(candidate, mode):
    graph, outputs = load(candidate, mode)
    assert outputs == ["8"]
    assert ancestors(graph, "8") == set(graph)
    assert graph["7"]["inputs"]["audio"] == ["6", 1]
    assert graph["7"]["inputs"]["fps"] == ["6", 2]
    assert graph["6"]["inputs"]["steps"] == 20
    assert graph["6"]["inputs"]["total_frames"] == 124
    assert graph["5"]["inputs"]["duration_sec"] == 124 / 24
    assert graph["5"]["inputs"]["prompt"] == VALUES["prompt"]
    family = "ref2va" if mode == "h3_r2v" else "fl2va"
    assert family in graph["1"]["inputs"]["unet_name"]
    timeline = json.loads(graph["6"]["inputs"]["timeline_data"])
    assert timeline["output"]["mode"] == "fixed"
    assert timeline["output"]["height"] == 384
    assert timeline["output"]["audioMode"] == "generate"
    assert not set(graph["6"]["inputs"]) & {
        "refine",
        "selflift",
        "face_refine",
        "semantic_bridge",
        "sigmas",
    }


def test_all_fifteen_references_and_video_soundtracks_are_connected(candidate):
    assets = [asset(f"ref_image_{i}") for i in range(9)]
    assets += [asset(f"ref_video_{i}", has_audio=i != 1) for i in range(3)]
    assets += [asset(f"ref_audio_{i}") for i in range(3)]
    graph, _ = load(candidate, assets=assets)
    group = graph["5"]["inputs"]
    assert len([k for k in group if k.startswith("ref_images.")]) == 9
    assert len([k for k in group if k.startswith("ref_videos.")]) == 3
    assert len([k for k in group if k.startswith("ref_audios.")]) == 3
    assert len([k for k in group if k.startswith("ref_video_audios.")]) == 2
    assert ancestors(graph, "8") == set(graph)
    graph, _ = load(candidate, assets=assets, referenceVideoAudio=False, sound=False)
    assert not any(k.startswith("ref_video_audios.") for k in graph["5"]["inputs"])
    # Raw output always contains generated AAC; existing finalizer removes it for sound=False.
    assert graph["7"]["inputs"]["audio"] == ["6", 1]


@pytest.mark.parametrize("kind", ["image", "video", "audio"])
def test_each_reference_kind_alone_reaches_director(candidate, kind):
    graph, _ = load(candidate, assets=[asset(f"ref_{kind}_0")])
    assert "hub:ref_" + kind + "_0" in ancestors(graph, "6")
    assert not any(n["class_type"] == "LoadImage" for n in graph.values()) or kind == "image"


def test_first_last_remain_h3_i2v_and_both_reach_group(candidate):
    graph, _ = load(candidate, "h3_i2v", [asset("first_frame"), asset("last_frame")])
    assert graph["5"]["inputs"]["first_frame"] == ["hub:first_frame", 0]
    assert graph["5"]["inputs"]["last_frame"] == ["hub:last_frame", 0]
    assert graph["6"]["inputs"]["task_type"].startswith("fl2v")


@pytest.mark.parametrize("frames", range(107, 363, 17))
@pytest.mark.parametrize("steps", [12, 20, 30])
def test_aligned_frames_steps_and_fractional_duration_are_preserved(candidate, frames, steps):
    graph, _ = load(
        candidate, "h3_t2v", frames=frames, durationSeconds=min(15, frames / 24), steps=steps
    )
    assert graph["6"]["inputs"]["total_frames"] == frames
    assert graph["5"]["inputs"]["duration_sec"] * 24 == frames
    assert graph["6"]["inputs"]["steps"] == steps


@pytest.mark.parametrize(
    "width,height",
    [
        (640, 360),
        (360, 640),
        (360, 360),
        (1024, 576),
        (576, 1024),
        (576, 576),
        (1280, 720),
        (720, 1280),
        (720, 720),
        (640, 384),
    ],
)
def test_all_existing_sizes_keep_aligned_canvas(candidate, width, height):
    graph, _ = load(candidate, "h3_t2v", width=width, height=height)
    assert graph["6"]["inputs"]["width"] == (width + 31) // 32 * 32
    assert graph["6"]["inputs"]["height"] == (height + 31) // 32 * 32


@pytest.mark.parametrize(
    "mode,assets",
    [
        ("h3_i2v", []),
        ("h3_i2v", [asset("last_frame")]),
        ("h3_r2v", []),
        ("h3_t2v", [asset("ref_image_0")]),
        ("h3_r2v", [asset("ref_image_9")]),
        ("h3_r2v", [asset("ref_video_3")]),
        ("h3_r2v", [asset("ref_audio_3")]),
        ("h3_r2v", [asset("ref_audio_1")]),
        ("h3_r2v", [asset("ref_image_0"), asset("ref_image_0")]),
        ("h3_r2v", [asset("ref_image_0", kind="video")]),
        ("h3_r2v", [asset("ref_video_0", has_audio="yes")]),
        ("h3_r2v", [None]),
        ("h3_r2v", {}),
    ],
)
def test_unsupported_or_missing_assets_fail_before_submit(candidate, mode, assets):
    with pytest.raises(WorkflowError):
        load(candidate, mode, assets)


@pytest.mark.parametrize(
    "path",
    [
        "../a.png",
        "hub/../a.png",
        "C:/a.png",
        "/a.png",
        "hub\\a.png",
        "https://a",
        "hub/a.png [output]",
        "",
        "a\n",
    ],
)
def test_assets_cannot_select_arbitrary_paths(candidate, path):
    with pytest.raises(WorkflowError):
        load(candidate, assets=[asset("ref_image_0", path=path)])


@pytest.mark.parametrize(
    "extra",
    [
        {"workflowEngine": "unknown"},
        {"workflowRevision": "future"},
        {"workflowRevision": None},
        {"prompt": ""},
        {"seed": True},
        {"steps": 8},
        {"frames": 120},
        {"durationSeconds": 6},
        {"referenceVideoAudio": 1},
        {"sound": "false"},
        {"refImageSize": "1024"},
    ],
)
def test_invalid_engine_revision_and_settings_fail(candidate, extra):
    with pytest.raises(WorkflowError):
        load(candidate, **extra)


def test_unavailable_mode_and_missing_registry_never_fall_back(candidate):
    path = candidate / "h3_capabilities.json"
    registry = json.loads(path.read_text())
    registry["engines"]["director"]["modes"]["h3_r2v"]["available"] = False
    path.write_text(json.dumps(registry))
    with pytest.raises(WorkflowError, match="尚未验收"):
        load(candidate)
    path.unlink()
    with pytest.raises(WorkflowError, match="缺失或损坏"):
        load(candidate)


def test_missing_engine_is_native_and_does_not_require_registry(tmp_path):
    for path in DIRECTORY.glob("h3_t2v_*.json"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    values = {k: v for k, v in VALUES.items() if k not in {"workflowEngine", "workflowRevision"}}
    graph, outputs = load_workflow(tmp_path, "h3_t2v", values)
    explicit, _ = load_workflow(tmp_path, "h3_t2v", {**values, "workflowEngine": "native"})
    assert graph == explicit
    assert outputs == ["92"]


def test_native_baseline_templates_and_mappings_are_byte_identical():
    baseline = json.loads((DIRECTORY.parent / "docs/baselines/v1.0.0.json").read_text())
    for item in baseline["workflow_files"]:
        path = DIRECTORY.parent / item["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]


def test_native_revision_matches_application_protocol_and_canonical_lf(tmp_path):
    import shutil

    expected = native_workflow_revision(DIRECTORY, "h3_t2v")
    for name in ("h3_t2v_api.json", "h3_t2v_mapping.json"):
        shutil.copyfile(DIRECTORY / name, tmp_path / name)
        source = (tmp_path / name).read_text(encoding="utf-8")
        (tmp_path / name).write_bytes(source.replace("\n", "\r\n").encode())
    assert native_workflow_revision(tmp_path, "h3_t2v") == expected
    values = {**VALUES, "workflowEngine": "native", "workflowRevision": expected, "assets": []}
    assert load_workflow(tmp_path, "h3_t2v", values)[1] == ["92"]
    with pytest.raises(WorkflowError, match="修订不可用"):
        load_workflow(tmp_path, "h3_t2v", {**values, "workflowRevision": "native-sha256:bad"})


def test_metadata_is_fixed_and_changed_files_cannot_reuse_revision(candidate):
    assert director_metadata(candidate, "h3_r2v") == (DIRECTOR_REVISION, ["8"])
    path = candidate / "h3_director_r2v_api.json"
    graph = json.loads(path.read_text(encoding="utf-8"))
    graph["1"]["inputs"]["unet_name"] = "different-model.safetensors"
    path.write_text(json.dumps(graph))
    with pytest.raises(WorkflowError, match="校验失败"):
        load(candidate)


def test_persisted_output_snapshot_must_match_director(candidate):
    with pytest.raises(WorkflowError, match="输出与导演台版本不匹配"):
        load(candidate, workflowOutputNodeIds=["92"])


def test_reordered_assets_keep_numbered_tag_order(candidate):
    assets = [
        asset("ref_image_1"),
        asset("ref_image_0"),
        asset("ref_video_1"),
        asset("ref_video_0", has_audio=True),
        asset("ref_audio_1"),
        asset("ref_audio_0"),
    ]
    graph, _ = load(candidate, assets=assets)
    keys = list(graph["5"]["inputs"])
    for prefix in ("ref_images.ref_image_", "ref_videos.ref_video_", "ref_audios.ref_audio_"):
        assert [key for key in keys if key.startswith(prefix)] == [prefix + "0", prefix + "1"]
