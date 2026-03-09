import os
import shutil
import sys
from pathlib import Path

_HELP = """\
Usage: renderknecht-wrapper < input.md > output.pdf

Render a Markdown document to PDF inside the renderknecht container image.
Reads from stdin, writes the PDF to stdout.

Environment variables:
  RENDERKNECHT_IMAGE    Image to use (default: renderknecht:latest)
  RENDERKNECHT_RUNTIME  Container runtime: 'podman' or 'docker'
                        (default: podman if available, else docker)
  XDG_CONFIG_HOME       Base for the user config dir (default: ~/.config)

Resources (preamble.yaml, authors.yaml, logo PDFs) are read from
$XDG_CONFIG_HOME/renderknecht/ when that directory exists, and mounted
read-only into the container as RESOURCES_DIR=/resources.
"""


def main() -> None:
    """Launch the renderknecht container, mounting the XDG config dir when present.

    Replaces the current process with the selected container runtime via
    os.execvp so stdin/stdout pass through without any wrapper overhead.
    Runtime is selected via RENDERKNECHT_RUNTIME; if unset, podman is
    preferred over docker when both are available on PATH.

    :raises FileNotFoundError: if no supported container runtime is found on PATH.
    """
    if {"-h", "--help"} & set(sys.argv[1:]):
        print(_HELP, end="")
        return

    runtime = os.environ.get("RENDERKNECHT_RUNTIME")
    if runtime is None:
        for candidate in ("podman", "docker"):
            if shutil.which(candidate):
                runtime = candidate
                break
        else:
            raise FileNotFoundError("No container runtime found on PATH; install podman or docker")

    image = os.environ.get("RENDERKNECHT_IMAGE", "renderknecht:latest")
    xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    resources_dir = xdg_config / "renderknecht"

    cmd = [runtime, "run", "--rm", "-i"]
    if resources_dir.is_dir():
        cmd += [
            "-v",
            f"{resources_dir.resolve()}:/resources:ro",
            "-e",
            "RESOURCES_DIR=/resources",
        ]
    cmd += [image, "render"]
    cmd += sys.argv[1:]

    os.execvp(runtime, cmd)  # noqa: S606, S607 (intentional PATH lookup, no shell needed)
