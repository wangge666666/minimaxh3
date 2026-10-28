import json
from pathlib import Path

import pytest

DIRECTORY = Path(__file__).resolve().parents[3] / "workflows"


@pytest.mark.parametrize("mode", ["t2v", "i2v", "r2v"])
def test_editable_graph_keeps_reviewed_api_connections_and_settings(mode):
    api = json.loads((DIRECTORY / f"h3_director_{mode}_api.json").read_text(encoding="utf-8"))
    ui = json.loads((DIRECTORY / f"h3_director_{mode}_editable.json").read_text(encoding="utf-8"))
    nodes = {str(n["id"]): n for n in ui["nodes"]}
    assert set(nodes) == set(api)
    links = {link[0]: link for link in ui["links"]}
    for node_id, node in api.items():
        assert nodes[node_id]["type"] == node["class_type"]
        for name, value in node["inputs"].items():
            if isinstance(value, list):
                port = next(p for p in nodes[node_id]["inputs"] if p["name"] == name)
                link = links[port["link"]]
                assert [str(link[1]), link[2]] == value
                assert str(link[3]) == node_id
            elif name in nodes[node_id]["widgets_values_named"]:
                assert nodes[node_id]["widgets_values_named"][name] == value
    director = nodes["6"]["widgets_values_named"]
    assert director["steps"] == 20
    assert director["control_after_generate"] == "fixed"
    assert director["total_frames"] == 124
    assert nodes["8"]["widgets_values"][1:3] == ["mp4", "h264"]
    assert ui["version"] == 0.4


def test_registry_and_mappings_use_fixed_names_and_output_ids():
    registry = json.loads((DIRECTORY / "h3_capabilities.json").read_text(encoding="utf-8"))
    assert registry["schemaVersion"] == 1
    assert registry["defaultEngine"] == "native"
    assert registry["parameters"]["steps"] == [12, 20, 30]
    assert registry["assets"]["h3_r2v"]["image"] == 9
    assert registry["assets"]["h3_r2v"]["video"] == 3
    assert registry["assets"]["h3_r2v"]["audio"] == 3
    for mode, spec in registry["engines"]["director"]["modes"].items():
        assert spec["mapping"] == mode.replace("h3_", "h3_director_") + "_mapping.json"
        assert spec["outputNodeIds"] == ["8"]


def test_available_director_modes_reference_completed_gpu_evidence():
    registry = json.loads((DIRECTORY / "h3_capabilities.json").read_text(encoding="utf-8"))
    for mode, spec in registry["engines"]["director"]["modes"].items():
        if not spec["available"]:
            continue
        assert spec["validation"]["level"] == "gpu-smoke"
        evidence = json.loads(
            (DIRECTORY / spec["validation"]["evidence"]).read_text(encoding="utf-8")
        )
        cases = {case["caseId"]: case for case in evidence["releaseAcceptanceCases"]}
        assert spec["validation"]["profiles"]
        for profile in spec["validation"]["profiles"]:
            case = cases[profile["caseId"]]
            assert case["passed"] and case["mode"] == mode
            assert case["frameCountVerified"] == 124
            assert case["checks"]["completeAudioVideoDecode"]
