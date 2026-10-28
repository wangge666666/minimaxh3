import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from comfy_hub_worker.runner import Journal, execute, resume_or_execute, run
from comfy_hub_worker.workflow_dispatch import (
    native_metadata,
    prepare_submission,
    recovery_outputs,
)

DIRECTORY = Path(__file__).resolve().parents[3] / "workflows"


def task(**overrides):
    return {
        "id": "application-test", "lease": "isolated-lease", "mode": "h3_t2v",
        "prompt": "a house", "width": 640, "height": 360, "seed": 1, "denoise": 1,
        **overrides,
    }


def test_legacy_native_is_pinned_and_default_settings_forwarded():
    from comfy_hub_worker.runner import workflow_values

    job = task()
    prepare_submission(job, DIRECTORY)
    values = workflow_values(job)
    assert values["workflowEngine"] == "native"
    assert values["workflowRevision"] == native_metadata(DIRECTORY, "h3_t2v")[0]
    assert values["steps"] == 20 and values["frames"] == 124 and values["fps"] == 24


@pytest.mark.parametrize("extra,reason", [
    ({"workflowEngine": "director"}, "尚未启用"),
    ({"workflowEngine": "turbo"}, "未知工作流"),
    ({"workflowEngine": None}, "未知工作流"),
    ({"workflowRevision": "native-sha256:" + "0" * 64}, "版本不可用"),
    ({"workflowOutputNodeIds": ["another-output"]}, "输出与工作流版本不匹配"),
])
async def test_invalid_submission_never_checks_uploads_or_submits(tmp_path, extra, reason):
    cloud = SimpleNamespace(progress=AsyncMock())
    comfy = SimpleNamespace(check=AsyncMock(), submit=AsyncMock(), upload_media=AsyncMock())
    with pytest.raises(ValueError, match=reason):
        await execute(task(**extra), Journal(tmp_path), cloud, comfy,
                      SimpleNamespace(workflow_directory=DIRECTORY))
    cloud.progress.assert_not_called()
    comfy.check.assert_not_called()
    comfy.upload_media.assert_not_called()
    comfy.submit.assert_not_called()


@pytest.mark.parametrize("assets", [
    [{"key": "ref_video_0", "kind": "image"}],
    [{"key": "ref_audio_1", "kind": "audio"}],
    [{"key": "ref_video_0", "kind": "video"}] * 2,
    [{"key": "ignored_audio", "kind": "audio"}],
])
def test_reference_descriptors_cannot_be_dropped(assets):
    with pytest.raises(ValueError, match="参考素材|素材编号"):
        prepare_submission(task(mode="h3_r2v", assets=assets), DIRECTORY)


def test_all_nine_images_three_videos_three_audios_preserved():
    assets = [{"key": f"ref_{kind}_{i}", "kind": kind}
              for kind, count in (("image", 9), ("video", 3), ("audio", 3))
              for i in range(count)]
    job = task(mode="h3_r2v", assets=assets, referenceVideoAudio=True, refImageSize="max")
    prepare_submission(job, DIRECTORY)
    assert job["assets"] == assets and len(job["assets"]) == 15
    assert job["referenceVideoAudio"] is True and job["refImageSize"] == "max"


def test_revision_is_portable_and_source_changes_detected(tmp_path):
    for suffix in ("api", "mapping"):
        name = f"h3_t2v_{suffix}.json"
        source = (DIRECTORY / name).read_bytes()
        (tmp_path / name).write_bytes(source.replace(b"\n", b"\r\n"))
    assert native_metadata(tmp_path, "h3_t2v") == native_metadata(DIRECTORY, "h3_t2v")
    job = task()
    prepare_submission(job, tmp_path)
    with (tmp_path / "h3_t2v_api.json").open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="版本不可用"):
        prepare_submission(job, tmp_path)


async def restored_job(job, tmp_path, monkeypatch, uploading=False):
    """No installed templates, capability registry or GPU is needed for recovery."""
    from comfy_hub_worker import runner

    build = AsyncMock(side_effect=AssertionError("must not build a new graph"))
    monkeypatch.setattr(runner, "load_workflow", build)
    monkeypatch.setattr(runner, "export_with_lease", AsyncMock(return_value=b"video"))
    job.setdefault("workflowOutputNodeIds", ["original-output"])
    journal = Journal(tmp_path)
    journal.save(job)
    cloud = SimpleNamespace(
        progress=AsyncMock(return_value={"status": "running"}), complete=AsyncMock(),
    )
    comfy = SimpleNamespace(
        submit=AsyncMock(), check=AsyncMock(),
        find_submission=AsyncMock(return_value="original-prompt"),
        watch_nodes=AsyncMock(), result=AsyncMock(return_value=b"video"),
    )
    settings = SimpleNamespace(workflow_directory=tmp_path / "not-installed")
    if uploading:
        current = {"id": job["id"], "status": "uploading", "prompt_id": "original-prompt"}
        cloud.http = SimpleNamespace(get=AsyncMock(return_value=httpx.Response(
            200, json={"jobs": [current]}, request=httpx.Request("GET", "https://test/state")
        )))
        await resume_or_execute(job, journal, cloud, comfy, settings)
    else:
        await execute(job, journal, cloud, comfy, settings)
    comfy.submit.assert_not_called()
    comfy.check.assert_not_called()
    build.assert_not_called()
    comfy.result.assert_awaited_once()
    assert comfy.result.call_args.args[:2] == ("original-prompt", ["original-output"])
    cloud.complete.assert_awaited_once()
    assert not journal.path.exists()
    return comfy


@pytest.mark.parametrize("engine", ["native", "director"])
async def test_existing_prompt_ignores_missing_registry_or_changed_revision(
    tmp_path, monkeypatch, engine
):
    await restored_job(task(prompt_id="original-prompt", workflowEngine=engine,
                            workflowRevision="old-version"), tmp_path, monkeypatch)


async def test_response_lost_before_journal_prompt_id_recovers_original(tmp_path, monkeypatch):
    comfy = await restored_job(task(submission_pending=True), tmp_path, monkeypatch)
    comfy.find_submission.assert_awaited_once_with("application-test")


async def test_uploading_recovers_cloud_prompt_id_without_workflow_files(tmp_path, monkeypatch):
    await restored_job(task(), tmp_path, monkeypatch, uploading=True)


async def test_unknown_submission_is_never_resubmitted(tmp_path):
    comfy = SimpleNamespace(find_submission=AsyncMock(return_value=None), submit=AsyncMock())
    with pytest.raises(RuntimeError, match="禁止直接重试"):
        await execute(task(submission_pending=True), Journal(tmp_path), None, comfy,
                      SimpleNamespace(workflow_directory=tmp_path))
    comfy.submit.assert_not_called()


async def test_lost_submit_response_is_recovered_without_a_second_submit(tmp_path, monkeypatch):
    from comfy_hub_worker import runner

    monkeypatch.setattr(runner, "export_with_lease", AsyncMock(return_value=b"video"))
    journal = Journal(tmp_path)

    async def lost_response(*_):
        saved = journal.read()
        assert saved["submission_pending"] is True
        assert saved["workflowRevision"] and saved["workflowOutputNodeIds"]
        raise httpx.ReadTimeout("response lost after Comfy accepted")

    comfy = SimpleNamespace(
        check=AsyncMock(), submit=AsyncMock(side_effect=lost_response),
        find_submission=AsyncMock(return_value="accepted-prompt"),
        watch_nodes=AsyncMock(), result=AsyncMock(return_value=b"video"),
    )
    cloud = SimpleNamespace(progress=AsyncMock(return_value={"status": "running"}),
                            complete=AsyncMock())
    await execute(task(), journal, cloud, comfy, SimpleNamespace(workflow_directory=DIRECTORY))
    comfy.submit.assert_awaited_once()
    assert comfy.result.call_args.args[0] == "accepted-prompt"
    assert not journal.path.exists()


def test_old_journal_output_recovery_uses_mapping_only(tmp_path):
    name = "h3_t2v_mapping.json"
    (tmp_path / name).write_bytes((DIRECTORY / name).read_bytes())
    assert recovery_outputs(task(prompt_id="old-prompt"), tmp_path) == json.loads(
        (DIRECTORY / name).read_text()
    )["outputs"]


async def test_restart_prioritizes_journal_even_if_templates_missing(tmp_path, monkeypatch):
    from comfy_hub_worker import runner
    from comfy_hub_worker.config import Settings

    directory = tmp_path / "empty-workflows"
    directory.mkdir()
    journal = Journal(tmp_path / "state")
    journal.save(task(prompt_id="original-prompt"))
    settings = Settings(
        _env_file=None, cloud_api_base_url="http://127.0.0.1:3100",
        worker_id="00000000-0000-4000-8000-000000000001", worker_api_token="x" * 32,
        workflow_directory=directory, worker_state_directory=tmp_path / "state",
        image_generation_enabled=False, h3_comfyui_base_url="http://127.0.0.1:18189",
    )

    async def request(_client, request, **_kwargs):
        if request.url.path == "/system_stats":
            return httpx.Response(200, json={"system": {}}, request=request)
        if request.url.path == "/api/mvp/state":
            return httpx.Response(200, request=request, json={
                "jobs": [{"id": "application-test", "status": "running"}],
            })
        if request.url.path == "/api/mvp/worker/heartbeat":
            return httpx.Response(200, json={"ok": True}, request=request)
        raise AssertionError(f"unexpected request: {request.url.path}")

    monkeypatch.setattr(httpx.AsyncClient, "send", request)
    resumed = AsyncMock()
    monkeypatch.setattr(runner, "resume_or_execute", resumed)
    await run(settings, once=True)
    resumed.assert_awaited_once()


def test_single_instance_state_directory_is_locked(tmp_path):
    from comfy_hub_worker.runner import single_process

    with single_process(tmp_path):
        with pytest.raises(RuntimeError, match="已有 Worker"):
            with single_process(tmp_path):
                pass
