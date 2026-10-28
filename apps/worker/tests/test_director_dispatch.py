import json
from pathlib import Path

import pytest

from comfy_hub_worker.mapping import load_workflow
from comfy_hub_worker.workflow_dispatch import prepare_submission, recovery_outputs

DIRECTORY = Path(__file__).resolve().parents[3] / "workflows"


def job(mode="h3_t2v", **overrides):
    assets = [] if mode == "h3_t2v" else [{
        "key": "first_frame" if mode == "h3_i2v" else "ref_image_0",
        "kind": "image", "path": "hub/validated.png",
    }]
    return {
        "mode": mode, "workflowEngine": "director", "workflowRevision": "director-v1.0.0",
        "workflowOutputNodeIds": ["8"], "prompt": "a boat", "width": 640, "height": 360,
        "seed": 42, "frames": 124, "fps": 24, "steps": 20, "assets": assets, **overrides,
    }


@pytest.mark.parametrize("mode", ["h3_t2v", "h3_i2v", "h3_r2v"])
def test_accepted_director_dispatch_builds_the_fixed_graph(mode):
    task = job(mode)
    prepare_submission(task, DIRECTORY, director_enabled=True)
    graph, outputs = load_workflow(DIRECTORY, mode, task)
    assert outputs == ["8"]
    assert graph["6"]["class_type"] == "MiniMaxH3Director"
    assert task["workflowRevision"] == "director-v1.0.0"


@pytest.mark.parametrize("extra", [
    {"workflowRevision": None}, {"workflowOutputNodeIds": None},
    {"workflowRevision": "director-future"}, {"workflowOutputNodeIds": ["92"]},
])
def test_missing_or_replaced_director_revision_cannot_submit(extra):
    with pytest.raises(ValueError):
        prepare_submission(job(**extra), DIRECTORY, director_enabled=True)


def test_disabled_director_can_recover_existing_prompt_without_current_package(tmp_path):
    task = job(prompt_id="already-accepted-prompt")
    assert recovery_outputs(task, tmp_path) == ["8"]
    with pytest.raises(ValueError, match="尚未启用"):
        prepare_submission(task, DIRECTORY)


def test_missing_registry_or_unaccepted_package_does_not_fall_back(tmp_path):
    with pytest.raises(ValueError):
        prepare_submission(job(), tmp_path, director_enabled=True)
    registry = json.loads((DIRECTORY / "h3_capabilities.json").read_text(encoding="utf-8"))
    registry["engines"]["director"]["modes"]["h3_t2v"]["available"] = False
    (tmp_path / "h3_capabilities.json").write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(ValueError, match="尚未验收"):
        prepare_submission(job(), tmp_path, director_enabled=True)
