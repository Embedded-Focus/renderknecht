import os
import sys
from collections.abc import Iterator
from unittest.mock import patch

import pytest

from renderknecht.podman_wrapper import main


@pytest.fixture()
def provide_env() -> Iterator[None]:
    orig_env = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(orig_env)


def test_main_runtime_env_var_override(provide_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    os.environ["RENDERKNECHT_RUNTIME"] = "docker"
    monkeypatch.setattr(sys, "argv", ["renderknecht-wrapper"])
    with patch("renderknecht.podman_wrapper.os.execvp") as mock_exec:
        main()
    runtime_used = mock_exec.call_args[0][0]
    assert runtime_used == "docker"


def test_main_mounts_cwd_as_work(provide_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    os.environ["RENDERKNECHT_RUNTIME"] = "podman"
    monkeypatch.setattr(sys, "argv", ["renderknecht-wrapper"])
    with patch("renderknecht.podman_wrapper.os.execvp") as mock_exec:
        main()
    cmd = mock_exec.call_args[0][1]
    assert "/work:ro" in " ".join(cmd)
    assert "WORK_DIR=/work" in cmd
