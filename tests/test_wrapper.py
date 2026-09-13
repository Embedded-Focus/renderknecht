import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from renderknecht import image_manager


@pytest.fixture()
def provide_env() -> Iterator[None]:
    original = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(original)


def test_detect_runtime_honors_env_override(provide_env: None) -> None:
    os.environ["RENDERKNECHT_RUNTIME"] = "docker"
    with patch("renderknecht.image_manager.shutil.which", return_value="/usr/bin/docker"):
        assert image_manager.detect_runtime() == "docker"


def test_detect_runtime_prefers_podman(provide_env: None) -> None:
    with patch("renderknecht.image_manager.shutil.which", return_value="/usr/bin/runtime") as which:
        assert image_manager.detect_runtime() == "podman"
    which.assert_called_once_with("podman")


def test_render_command_mounts_cwd_as_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    command = image_manager._render_command("podman", "renderknecht:test", [])
    assert f"{tmp_path}:/work:ro" in command
    assert "WORK_DIR=/work" in command
    assert command[-2:] == ["renderknecht:test", "render"]


def test_render_command_mounts_resource_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    resources = tmp_path / "resources"
    resources.mkdir()
    preamble = tmp_path / "custom" / "preamble.yaml"
    preamble.parent.mkdir()
    preamble.write_text("title: Test\n", encoding="utf-8")
    monkeypatch.setenv("RESOURCES_DIR", str(resources))
    monkeypatch.setenv("PREAMBLE_YAML", str(preamble))
    command = image_manager._render_command("docker", "renderknecht:test", [])
    joined = " ".join(command)
    assert f"{resources}:/resources:ro" in joined
    assert f"{preamble.parent}:/renderknecht-overrides/preamble:ro" in joined
    assert "PREAMBLE_YAML=/renderknecht-overrides/preamble/preamble.yaml" in command


def test_bundled_manifest_resolves_both_architectures() -> None:
    manifest = image_manager.load_bundled_manifest()
    for architecture in ("amd64", "arm64"):
        resolved = image_manager._selected_manifest(manifest, architecture)
        assert resolved["architecture"] == architecture
        assert set(resolved["artifacts"]) == {"pandoc", "pandoc_crossref", "eisvogel"}
        assert all(len(artifact["sha256"]) == 64 for artifact in resolved["artifacts"].values())


def test_saved_manifest_can_be_loaded_for_rebuild(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(image_manager, "package_version", lambda: "1.2.3")
    manifest = image_manager._selected_manifest(image_manager.load_bundled_manifest(), "amd64")
    manifest["resolved_at"] = "2026-01-01T00:00:00+00:00"
    path = tmp_path / "manifest.json"
    image_manager._write_json(path, manifest)
    loaded = image_manager.load_resolved_manifest(path)
    assert loaded["renderknecht"] == "1.2.3"
    assert "resolved_at" not in loaded


def test_build_context_copy_excludes_local_hidden_directories(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "module.py").write_text("value = 1\n", encoding="utf-8")
    hidden = source / ".venv"
    hidden.mkdir()
    (hidden / "secret").write_text("not part of the package\n", encoding="utf-8")
    destination = tmp_path / "context"
    image_manager._copy_tree(source, destination)
    assert (destination / "module.py").is_file()
    assert not (destination / ".venv").exists()


def test_failed_smoke_test_does_not_replace_active_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    active_path = image_manager.state_dir() / "active.json"
    image_manager._write_json(active_path, {"image": "renderknecht:previous"})
    monkeypatch.setattr(image_manager, "detect_runtime", lambda: "podman")
    monkeypatch.setattr(image_manager, "architecture", lambda: "amd64")
    monkeypatch.setattr(image_manager, "_image_exists", lambda runtime, tag: True)

    def fail_smoke(runtime: str, tag: str) -> None:
        raise image_manager.ImageError("smoke test failed")

    monkeypatch.setattr(image_manager, "_smoke_test", fail_smoke)
    with pytest.raises(image_manager.ImageError, match="smoke test failed"):
        image_manager.build()
    assert image_manager._active_state() == {"image": "renderknecht:previous"}
