import json
from pathlib import Path

import pytest

from comfy_hub_worker.mapping import WorkflowError, load_workflow

DIRECTORY = Path(__file__).resolve().parents[3] / "workflows"
VALUES = {
    "prompt": "a quiet lake",
    "seed": 42,
    "width": 512,
    "height": 512,
    "denoise": 0.6,
    "image": "hub/reference.png",
}


def test_text_and_image_templates_use_correct_latent_source():
    text, _ = load_workflow(DIRECTORY, "text", VALUES)
    image, outputs = load_workflow(DIRECTORY, "img2img", VALUES)
    assert text["57:3"]["inputs"]["latent_image"] == ["57:13", 0]
    assert image["57:3"]["inputs"]["latent_image"] == ["hub:encode", 0]
    assert image["hub:load"]["inputs"]["image"] == "hub/reference.png"
    assert image["57:27"]["inputs"]["text"] == "a quiet lake"
    assert outputs == ["9"]


@pytest.mark.parametrize(
    "name,value", [("width", 9999), ("seed", -1), ("seed", True), ("denoise", 2), ("prompt", "")]
)
def test_invalid_values_fail(name, value):
    with pytest.raises(WorkflowError):
        load_workflow(DIRECTORY, "img2img", {**VALUES, name: value})


def test_missing_node_fails_clearly(tmp_path):
    for name in ("z_image_turbo_text_api.json", "z_image_turbo_text_mapping.json"):
        (tmp_path / name).write_text((DIRECTORY / name).read_text())
    template = tmp_path / "z_image_turbo_text_api.json"
    content = json.loads(template.read_text())
    del content["57:27"]
    template.write_text(json.dumps(content))
    with pytest.raises(WorkflowError, match="节点或字段不存在"):
        load_workflow(tmp_path, "text", VALUES)


@pytest.mark.parametrize("mode", ["h3_i2v", "h3_r2v", "h3_t2v"])
def test_h3_templates_use_exported_nodes_and_save_video(mode):
    values = {**VALUES, "width": 640, "height": 384, "frames": 124, "fps": 24}
    graph, outputs = load_workflow(DIRECTORY, mode, values)
    assert graph[outputs[0]]["class_type"] == "SaveVideo"
    conditioner = next(n for n in graph.values() if n["class_type"].startswith("MiniMaxH3"))
    assert conditioner["inputs"]["prompt"] == "a quiet lake"
    assert conditioner["inputs"]["length"] == 124
    if mode == "h3_i2v":
        assert "first_frame" in conditioner["inputs"]
    if mode == "h3_r2v":
        assert "ref_images.ref_image_0" in conditioner["inputs"]
    if mode == "h3_t2v":
        assert not any(n["class_type"] == "LoadImage" for n in graph.values())


def test_h3_rejects_unverified_dimensions():
    with pytest.raises(WorkflowError):
        load_workflow(DIRECTORY, "h3_i2v", {**VALUES, "frames": 124, "fps": 24})


@pytest.mark.parametrize("width,height", [(640, 360), (360, 640), (720, 720), (1280, 720)])
def test_h3_exact_output_size_maps_to_native_canvas(width, height):
    graph, _ = load_workflow(
        DIRECTORY,
        "h3_t2v",
        {
            **VALUES,
            "width": width,
            "height": height,
            "frames": 243,
            "fps": 24,
            "steps": 30,
            "assets": [],
        },
    )
    inputs = graph["131"]["inputs"]
    assert inputs["width"] == (width + 31) // 32 * 32
    assert inputs["height"] == (height + 31) // 32 * 32
    assert inputs["length"] == 243
    assert (
        next(n for n in graph.values() if n["class_type"] == "BasicScheduler")["inputs"]["steps"]
        == 30
    )


def test_h3_first_and_last_frame_are_connected():
    assets = [
        {"key": k, "kind": "image", "path": f"hub/{k}.png"} for k in ("first_frame", "last_frame")
    ]
    graph, _ = load_workflow(
        DIRECTORY, "h3_i2v", {**VALUES, "width": 640, "height": 360, "assets": assets}
    )
    assert graph["104"]["inputs"]["last_frame"] == ["hub:last_frame", 0]
    assert graph["hub:first_frame"]["class_type"] == "LoadImage"


def test_h3_multimodal_references_connect_soundtracks_only_when_present():
    assets = [
        {"key": "ref_image_0", "kind": "image", "path": "hub/a.png"},
        {"key": "ref_video_0", "kind": "video", "path": "hub/b.mp4", "has_audio": True},
        {"key": "ref_audio_0", "kind": "audio", "path": "hub/c.wav"},
    ]
    values = {**VALUES, "width": 640, "height": 360, "assets": assets}
    graph, _ = load_workflow(DIRECTORY, "h3_r2v", values)
    inputs = graph["136"]["inputs"]
    assert inputs["ref_images.ref_image_0"] == ["hub:ref_image_0", 0]
    assert inputs["ref_videos.ref_video_0"] == ["hub:ref_video_0:parts", 0]
    assert inputs["ref_video_audios.ref_video_audio_0"] == ["hub:ref_video_0:parts", 1]
    assert inputs["ref_audios.ref_audio_0"] == ["hub:ref_audio_0", 0]
    graph, _ = load_workflow(DIRECTORY, "h3_r2v", {**values, "referenceVideoAudio": False})
    assert "ref_video_audios.ref_video_audio_0" not in graph["136"]["inputs"]


def test_h3_audio_only_and_invalid_reference_roles():
    values = {
        **VALUES,
        "width": 640,
        "height": 360,
        "assets": [{"key": "ref_audio_0", "kind": "audio", "path": "hub/voice.wav"}],
    }
    graph, _ = load_workflow(DIRECTORY, "h3_r2v", values)
    assert not any(n["class_type"] == "LoadImage" for n in graph.values())
    for assets in (
        [],
        [{"key": "ref_audio_3", "kind": "audio", "path": "hub/v.wav"}],
        [{"key": "ref_audio_0", "kind": "audio", "path": "../v.wav"}],
    ):
        with pytest.raises(WorkflowError):
            load_workflow(DIRECTORY, "h3_r2v", {**values, "assets": assets})


@pytest.mark.parametrize("mode", ["h3_t2v", "h3_i2v", "h3_r2v"])
@pytest.mark.parametrize(
    "seconds,frames",
    [
        (4, 107),
        (4.35, 107),
        (5, 124),
        (5.17, 141),
        (6, 158),
        (7.5, 192),
        (8, 192),
        (10, 243),
        (15, 362),
    ],
)
def test_h3_custom_duration_reaches_existing_conditioner(mode, seconds, frames):
    graph, _ = load_workflow(
        DIRECTORY,
        mode,
        {**VALUES, "width": 640, "height": 360, "durationSeconds": seconds, "frames": frames},
    )
    conditioner = next(n for n in graph.values() if n["class_type"].startswith("MiniMaxH3"))
    assert conditioner["inputs"]["length"] == frames
    video = next(n for n in graph.values() if n["class_type"] == "CreateVideo")
    assert video["inputs"]["fps"] == 24


@pytest.mark.parametrize("frames", range(107, 363, 17))
def test_h3_duration_at_native_frame_boundaries(frames):
    graph, _ = load_workflow(
        DIRECTORY,
        "h3_t2v",
        {
            **VALUES,
            "width": 640,
            "height": 360,
            "durationSeconds": min(15, frames / 24),
            "frames": frames,
        },
    )
    assert graph["131"]["inputs"]["length"] == frames


@pytest.mark.parametrize(
    "extra",
    [
        {"durationSeconds": 3.99, "frames": 107},
        {"durationSeconds": 15.01, "frames": 362},
        {"durationSeconds": 6, "frames": 124},
        {"durationSeconds": "6", "frames": 158},
        {"durationSeconds": float("nan"), "frames": 158},
        {"durationSeconds": float("inf"), "frames": 158},
        {"durationSeconds": True, "frames": 158},
        {"frames": 106},
        {"frames": 363},
        {"frames": 158.5},
        {"frames": 120},
    ],
)
def test_h3_invalid_custom_duration_fails_before_submission(extra):
    with pytest.raises(WorkflowError):
        load_workflow(DIRECTORY, "h3_t2v", {**VALUES, "width": 640, "height": 360, **extra})
