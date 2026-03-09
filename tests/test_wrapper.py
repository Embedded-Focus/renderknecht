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
