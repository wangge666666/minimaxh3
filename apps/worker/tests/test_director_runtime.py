import hashlib

import pytest

from comfy_hub_worker.director_runtime import audit_plugin, prepare_plugin


def test_isolated_plugin_copy_never_overwrites_or_accepts_unreviewed_code(tmp_path):
    source, dest = tmp_path / "source", tmp_path / "dest"
    source.mkdir()
    (source / "__init__.py").write_bytes(b"# reviewed\n")
    manifest = {"files": {"__init__.py": hashlib.sha256(b"# reviewed\n").hexdigest()}}
    assert not audit_plugin(source, manifest)
    prepare_plugin(source, dest, manifest)
    assert (dest / "__init__.py").read_bytes() == b"# reviewed\n"
    with pytest.raises(ValueError, match="already exists"):
        prepare_plugin(source, dest, manifest)
    (source / "extra.py").write_text("# unreviewed")
    assert audit_plugin(source, manifest) == ["extra.py"]
    with pytest.raises(ValueError, match="preserve and review"):
        prepare_plugin(source, tmp_path / "new", manifest)
    (source / "__init__.py").write_text("# changed")
    assert audit_plugin(source, manifest) == ["__init__.py", "extra.py"]
    (source / "extra.py").unlink()
    (source / "__init__.py").write_bytes(b"# reviewed\r\n")
    manifest["hashNormalization"] = "canonical-lf"
    assert not audit_plugin(source, manifest)
