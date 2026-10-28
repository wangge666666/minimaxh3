"""Audit a pinned Director plugin and prepare a NEW isolated plugin folder.

This never installs packages, starts ComfyUI, or modifies an existing plugin.
"""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def audit_plugin(source: Path, manifest: dict) -> list[str]:
    errors = []
    expected = manifest["files"]
    for name, digest in expected.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid plugin manifest path")
        path = source / relative
        content = path.read_bytes() if path.is_file() else b""
        if manifest.get("hashNormalization") == "canonical-lf":
            content = content.replace(b"\r\n", b"\n")
        if not path.is_file() or hashlib.sha256(content).hexdigest() != digest:
            errors.append(name)
    errors.extend(
        str(path.relative_to(source)).replace("\\", "/")
        for path in source.rglob("*.py")
        if path.relative_to(source).as_posix() not in expected
    )
    return sorted(set(errors))


def prepare_plugin(source: Path, destination: Path, manifest: dict) -> None:
    if audit_plugin(source, manifest):
        raise ValueError(
            "Plugin differs from the reviewed manifest; preserve and review local changes"
        )
    if destination.exists():
        raise ValueError("Destination already exists; refusing to overwrite a plugin")
    destination.mkdir(parents=True)
    for name in manifest["files"]:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    errors = audit_plugin(args.source, manifest)
    if errors:
        raise SystemExit("Unreviewed plugin differences: " + ", ".join(errors))
    if args.destination:
        prepare_plugin(args.source, args.destination, manifest)
    print(f"Director plugin verified: {len(manifest['files'])} files")


if __name__ == "__main__":
    main()
