import asyncio
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from types import SimpleNamespace

import httpx
import respx

from comfy_hub_worker.runner import Cloud, Journal, execute


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
