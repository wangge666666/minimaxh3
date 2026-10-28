"""Rebuild editable LiteGraph JSON from the reviewed API files and /object_info.

Usage: python workflows/build_director_editable.py --object-info <saved-object-info.json>
No prompts are submitted and no ComfyUI instance is changed.
"""

import argparse
import json
from pathlib import Path

WIDGETS = {
    "STRING",
    "INT",
    "FLOAT",
    "BOOLEAN",
    "COMBO",
    "BDGROUP",
    "COMFY_DYNAMICCOMBO_V3",
}
POSITIONS = {
    "1": [40, 40],
    "2": [40, 190],
    "3": [40, 370],
    "4": [40, 490],
    "5": [440, 40],
    "6": [920, 40],
    "7": [2000, 40],
    "8": [2340, 40],
    "9": [40, 650],
    "10": [440, 650],
}


def editable(graph: dict, info: dict) -> dict:
    nodes = {}
    for index, (node_id, api) in enumerate(graph.items()):
        definition = info[api["class_type"]]
        specs = {
            **definition["input"].get("required", {}),
            **definition["input"].get("optional", {}),
        }
        node = {
            "id": int(node_id),
            "type": api["class_type"],
            "pos": POSITIONS.get(node_id, [440, 900 + index * 150]),
            "size": [1000, 1450] if node_id == "6" else [380, 260],
            "flags": {},
            "order": index,
            "mode": 0,
            "inputs": [],
            "outputs": [],
            "properties": {"Node name for S&R": api["class_type"]},
            "widgets_values": [],
            "widgets_values_named": {},
        }
        for name, spec in specs.items():
            typ, options = spec[0], spec[1] if len(spec) > 1 else {}
            value = api["inputs"].get(name, options.get("default"))
            if typ == "COMFY_AUTOGROW_V3":
                child = next(iter(options["template"]["input"]["required"].values()))[0]
                connected = [key for key in api["inputs"] if key.startswith(name + ".")]
                for key in [
                    *connected,
                    name + "." + options["template"]["prefix"] + str(len(connected)),
                ]:
                    node["inputs"].append(
                        {"name": key, "type": child, "shape": 7, "link": None}
                    )
                continue
            widget = isinstance(typ, list) or typ in WIDGETS
            widget = widget and not options.get("forceInput", False)
            linked = (
                isinstance(value, list) and len(value) == 2 and str(value[0]) in graph
            )
            if not widget or linked:
                entry = {
                    "name": name,
                    "type": "COMBO" if isinstance(typ, list) else typ,
                    "link": None,
                }
                if name in definition["input"].get("optional", {}):
                    entry["shape"] = 7
                if widget:
                    entry["widget"] = {"name": name}
                node["inputs"].append(entry)
            if widget:
                if linked:
                    value = options.get("default")
                if value is None and isinstance(typ, list):
                    value = typ[0]
                if value is None and typ in {"COMBO", "COMFY_DYNAMICCOMBO_V3"}:
                    choices = options.get("options", [])
                    value = choices[0] if choices else "auto"
                    if isinstance(value, dict):
                        value = value["key"]
                node["widgets_values"].append(value)
                node["widgets_values_named"][name] = value
                if options.get("control_after_generate"):
                    node["widgets_values"].append("fixed")
                    node["widgets_values_named"]["control_after_generate"] = "fixed"
        if api["class_type"] == "SaveVideo":
            node["widgets_values"] = [
                api["inputs"]["filename_prefix"],
                "mp4",
                "h264",
                "auto",
                "auto",
            ]
        for slot, typ in enumerate(definition["output"]):
            entry = {"name": definition["output_name"][slot], "type": typ, "links": []}
            if definition.get("output_is_list", [False] * len(definition["output"]))[
                slot
            ]:
                entry["shape"] = 6
            node["outputs"].append(entry)
        nodes[node_id] = node
    links = []
    for target_id, api in graph.items():
        for name, value in api["inputs"].items():
            if not (
                isinstance(value, list) and len(value) == 2 and str(value[0]) in nodes
            ):
                continue
            source_id, source_slot = str(value[0]), value[1]
            target_slot = next(
                i
                for i, inp in enumerate(nodes[target_id]["inputs"])
                if inp["name"] == name
            )
            link_id = len(links) + 1
            typ = nodes[source_id]["outputs"][source_slot]["type"]
            links.append(
                [link_id, int(source_id), source_slot, int(target_id), target_slot, typ]
            )
            nodes[source_id]["outputs"][source_slot]["links"].append(link_id)
            nodes[target_id]["inputs"][target_slot]["link"] = link_id
    return {
        "revision": 0,
        "last_node_id": max(map(int, nodes)),
        "last_link_id": len(links),
        "nodes": list(nodes.values()),
        "links": links,
        "groups": [],
        "config": {},
        "extra": {
            "ds": {"scale": 0.65, "offset": [70, 70]},
            "workflowRendererVersion": "LG",
            "directorRevision": "director-v1.0.0",
        },
        "version": 0.4,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--object-info", type=Path, required=True)
    args = parser.parse_args()
    info = json.loads(args.object_info.read_text(encoding="utf-8"))
    directory = Path(__file__).resolve().parent
    for mode in ("t2v", "i2v", "r2v"):
        api = json.loads(
            (directory / f"h3_director_{mode}_api.json").read_text(encoding="utf-8")
        )
        target = directory / f"h3_director_{mode}_editable.json"
        target.write_text(
            json.dumps(editable(api, info), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
