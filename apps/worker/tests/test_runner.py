import asyncio
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from types import SimpleNamespace

import httpx
import respx

from comfy_hub_worker.runner import Cloud, Journal, execute


async def test_image_video_audio_and_fixed_metadata_reach_loader_without_loss(
    respx_mock, synthetic_mp4, tmp_path, monkeypatch
):
    import io

    from PIL import Image

    from comfy_hub_worker import runner

    image = io.BytesIO()
    Image.new("RGB", (96, 64), "navy").save(image, format="PNG")
    assets = [
        {"key": "ref_image_0", "kind": "image", "name": "test.png", "mime": "image/png"},
        {"key": "ref_video_0", "kind": "video", "name": "test.mp4", "mime": "video/mp4"},
        {"key": "ref_audio_0", "kind": "audio", "name": "test.m4a", "mime": "audio/mp4"},
    ]
    job = {
        "id": "media-forwarding", "lease": "test-lease", "mode": "h3_r2v",
        "prompt": "a scene", "width": 640, "height": 360, "frames": 124, "fps": 24,
        "steps": 20, "seed": 7, "denoise": 1, "sound": True,
        "referenceVideoAudio": True, "refImageSize": "max", "assets": assets,
    }
    for asset in assets:
        respx_mock.get(
            f"http://cloud.test/api/mvp/worker/input/media-forwarding/{asset['key']}"
        ).respond(200, content=image.getvalue() if asset["kind"] == "image" else synthetic_mp4)
    respx_mock.post("http://cloud.test/api/mvp/worker/progress").respond(
        200, json={"status": "running"}
    )
    complete = respx_mock.post("http://cloud.test/api/mvp/worker/complete").respond(
        200, json={"status": "completed"}
    )
    original = runner.load_workflow
    forwarded = []

    def observe(directory, mode, values):
        forwarded.append(values.copy())
        return original(directory, mode, values)

    monkeypatch.setattr(runner, "load_workflow", observe)

    class LocalComfy:
        async def check(self, _graph):
            pass

        async def upload_media(self, filename, _data, _mime):
            return "hub/" + filename

        async def submit(self, _graph, _job_id):
            return "media-prompt"

        async def watch_nodes(self, *_):
            await asyncio.Event().wait()

        async def result(self, *_args, **_kwargs):
            return synthetic_mp4

    async with httpx.AsyncClient(base_url="http://cloud.test") as http:
        await execute(job, Journal(tmp_path), Cloud(http), LocalComfy(), SimpleNamespace(
            workflow_directory=Path(__file__).resolve().parents[3] / "workflows"
        ))
    values = forwarded[-1]
    assert values["workflowEngine"] == "native" and values["workflowRevision"]
    assert values["steps"] == 20 and values["referenceVideoAudio"] is True
    assert values["refImageSize"] == "max"
    assert [a["key"] for a in values["assets"]] == [a["key"] for a in assets]
    assert [a["kind"] for a in values["assets"]] == ["image", "video", "audio"]
    assert all(a["path"].startswith("hub/media-forwarding_") for a in values["assets"])
    assert values["assets"][1]["has_audio"] is True
    assert values["assets"][2]["has_audio"] is True
    assert complete.call_count == 1


async def test_video_only_worker_never_requests_mac(tmp_path):
    from comfy_hub_worker.config import Settings
    from comfy_hub_worker.runner import run

    settings = Settings(
        _env_file=None,
        cloud_api_base_url="https://cloud.test",
        worker_id="00000000-0000-4000-8000-000000000001",
        worker_api_token="x" * 32,
        workflow_directory=Path(__file__).resolve().parents[3] / "workflows",
        worker_state_directory=tmp_path,
        comfyui_base_url="https://unavailable-mac.example-tailnet.ts.net:9443",
        h3_comfyui_base_url="http://127.0.0.1:8189",
        image_generation_enabled=False,
    )
    with respx.mock(assert_all_called=False) as router:
        mac = router.get("https://unavailable-mac.example-tailnet.ts.net:9443/system_stats").respond(503)
        router.get("http://127.0.0.1:8189/system_stats").respond(200, json={"system": {}})
        heartbeat = router.post("https://cloud.test/api/mvp/worker/heartbeat").respond(
            200, json={"ok": True}
        )
        claim = router.post("https://cloud.test/api/mvp/worker/claim").respond(
            200, json={"job": None}
        )
        await run(settings, once=True)
        assert not mac.called
        import json

        assert json.loads(heartbeat.calls[0].request.content)["h3_online"] is True
        assert json.loads(claim.calls[0].request.content)["available_modes"] == [
            "h3_i2v", "h3_r2v", "h3_t2v"
        ]


async def test_multimodal_job_reaches_workflow_and_exports_requested_ratio(
    respx_mock, synthetic_mp4, tmp_path
):
    """Exercise reference download -> decode -> graph -> crop -> completion, without a GPU."""
    job = {
        "id": "test-job",
        "lease": "test-lease",
        "mode": "h3_r2v",
        "prompt": "Use <Audio 1>",
        "width": 640,
        "height": 360,
        "frames": 124,
        "fps": 24,
        "steps": 30,
        "seed": 7,
        "denoise": 1,
        "sound": False,
        "referenceVideoAudio": False,
        "assets": [
            {"key": "ref_audio_0", "kind": "audio", "name": "voice.m4a", "mime": "audio/mp4"}
        ],
    }
    respx_mock.get("http://cloud.test/api/mvp/worker/input/test-job/ref_audio_0").respond(
        200, content=synthetic_mp4
    )
    respx_mock.post("http://cloud.test/api/mvp/worker/progress").respond(
        200, json={"status": "running"}
    )
    completed = respx_mock.post("http://cloud.test/api/mvp/worker/complete").respond(
        200, json={"status": "completed"}
    )

    class FakeComfy:
        graph = None

        async def check(self, graph):
            pass

        async def upload_media(self, filename, data, mime):
            assert filename.endswith("_ref_audio_0.wav")
            assert data[:4] == b"RIFF" and mime == "audio/wav"
            return "hub/voice.wav"

        async def submit(self, graph, job_id):
            self.graph = graph
            return "prompt-test"

        async def watch_nodes(self, *_):
            await asyncio.Event().wait()

        async def result(self, *_args, **_kwargs):
            return synthetic_mp4

    comfy = FakeComfy()
    journal = Journal(tmp_path)
    journal.save(job)
    settings = SimpleNamespace(workflow_directory=Path(__file__).resolve().parents[3] / "workflows")
    async with httpx.AsyncClient(base_url="http://cloud.test") as http:
        await execute(job, journal, Cloud(http), comfy, settings)
    assert comfy.graph["136"]["inputs"]["ref_audios.ref_audio_0"] == ["hub:ref_audio_0", 0]
    assert comfy.graph["124"]["inputs"]["steps"] == 30
    assert completed.call_count == 1 and not journal.path.exists()
    from comfy_hub_worker.video import validate_video

    request = completed.calls[0].request
    mime = BytesParser(policy=default).parsebytes(
        ("Content-Type: " + request.headers["content-type"] + "\r\n\r\n").encode() + request.content
    )
    fields = {
        part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
        for part in mime.iter_parts()
    }
    assert validate_video(fields["video"], job)["height"] == 360
    assert fields["poster"][:2] == b"\xff\xd8"
