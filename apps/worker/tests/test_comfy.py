import asyncio
import io

import httpx
import pytest
from PIL import Image, UnidentifiedImageError

from comfy_hub_worker.comfy import Comfy, validate_image


def png():
    data = io.BytesIO()
    Image.new("RGB", (512, 512), (100, 120, 140)).save(data, format="PNG")
    return data.getvalue()


def test_reject_bad_image():
    with pytest.raises(UnidentifiedImageError):
        validate_image(b"not-an-image")


async def test_mock_upload_submit_history_download(respx_mock):
    data = png()
    upload = respx_mock.post("http://comfy.test/upload/image").respond(
        200, json={"name": "test.png", "subfolder": "hub"}
    )
    submit = respx_mock.post("http://comfy.test/prompt").respond(200, json={"prompt_id": "p1"})
    respx_mock.get("http://comfy.test/history/p1").respond(
        200,
        json={
            "p1": {
                "status": {"completed": True, "status_str": "success"},
                "outputs": {
                    "9": {"images": [{"filename": "result.png", "subfolder": "", "type": "output"}]}
                },
            }
        },
    )
    respx_mock.get("http://comfy.test/view").respond(200, content=data)
    ticks = []

    async def tick(message):
        ticks.append(message)

    async with httpx.AsyncClient(base_url="http://comfy.test") as client:
        comfy = Comfy(client)
        assert await comfy.upload("job", data) == "hub/test.png"
        assert await comfy.submit({"9": {}}, "job") == "p1"
        result = await comfy.result("p1", ["9"], tick, asyncio.Queue())
        assert Image.open(io.BytesIO(result)).size == (512, 512)
    assert upload.call_count == submit.call_count == 1
    assert ticks


async def test_prompt_timeout_is_not_retried(respx_mock):
    submit = respx_mock.post("http://comfy.test/prompt").mock(
        side_effect=httpx.ReadTimeout("lost response")
    )
    async with httpx.AsyncClient(base_url="http://comfy.test") as client:
        with pytest.raises(httpx.ReadTimeout):
            await Comfy(client).submit({}, "job")
    assert submit.call_count == 1


async def test_recover_matches_accepted_job_from_queue(respx_mock):
    respx_mock.get("http://comfy.test/queue").respond(
        200,
        json={"queue_running": [[0, "p1", {}, {"hub_job_id": "job"}, ["9"]]], "queue_pending": []},
    )
    respx_mock.get("http://comfy.test/history").respond(200, json={})
    async with httpx.AsyncClient(base_url="http://comfy.test") as client:
        assert await Comfy(client).find_submission("job") == "p1"


async def test_generation_error_becomes_clear_failure(respx_mock):
    respx_mock.get("http://comfy.test/history/p1").respond(
        200,
        json={
            "p1": {
                "status": {
                    "status_str": "error",
                    "messages": [["execution_error", {"exception_message": "out of memory"}]],
                }
            }
        },
    )

    async def tick(message):
        pass

    async with httpx.AsyncClient(base_url="http://comfy.test") as client:
        with pytest.raises(RuntimeError, match="out of memory"):
            await Comfy(client).result("p1", ["9"], tick, asyncio.Queue())


async def test_save_video_result_uses_exported_output_node(respx_mock):
    respx_mock.get("http://comfy.test/history/video1").respond(
        200,
        json={
            "video1": {
                "status": {"completed": True, "status_str": "success"},
                "outputs": {
                    "92": {
                        "images": [
                            {
                                "filename": "clip.mp4",
                                "subfolder": "h3",
                                "type": "output",
                                "id": "asset-id",
                            }
                        ]
                    }
                },
            }
        },
    )
    view = respx_mock.get("http://comfy.test/view").respond(200, content=b"video-bytes")

    async def tick(message):
        pass

    async with httpx.AsyncClient(base_url="http://comfy.test") as client:
        result = await Comfy(client).result(
            "video1", ["92"], tick, asyncio.Queue(), media_kind="video"
        )
    assert result == b"video-bytes"
    assert view.calls[0].request.url.params["filename"] == "clip.mp4"
    assert "id" not in view.calls[0].request.url.params
