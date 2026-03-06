# AGENTS.md

## Repository Overview

- Purpose: Renders Markdown files into PDFs via pandoc and the eisvogel LaTeX template.
- Core tech: Python, pandoc, Flask (web mode), GraphViz, PlantUML, uv, ruff, ty, pytest, hatchling.

Used (minimum) versions can be found in pyproject.toml.

## Layout

- `src/renderknecht/`: main Python package (src layout)
  - `renderers/`: pandoc-based Markdown → PDF renderer
  - `util/`: utilities — YAML handling (`yaml.py`), pandoc argument builder (`pandoc_wrapper.py`)
  - `resources/`: bundled defaults — `preamble.yaml`, `authors.yaml`, `ieee.csl`, logo PDFs
- `src/renderknecht/podman_wrapper.py`: podman wrapper; exposes the `renderknecht-wrapper` CLI entry point
- `tests/`: unit tests
- `Dockerfile.renderknecht`: container image build
- `compose.yaml`: full stack (HedgeDoc + PlantUML + renderknecht + Caddy reverse proxy)
- `entrypoint.sh`: auto-detects render mode (stdin pipe) vs serve mode (Flask)
- `pyproject.toml`: project configuration and dependencies

## Common Commands

Always prefix any Python-related command with `uv run`, e.g.:

- Run tests: `uv run pytest`
  - Run test "name": `uv run pytest -k name`
  - Run test in specific path: `uv run pytest tests/file.py`
- Collect tests: `uv run pytest --co`
- Lint/format: `uv run ruff check`, `uv run ruff format --check`, `uv run ty check`

## Wrapper

`renderknecht-wrapper` is the host-side CLI entry point. Install both scripts at once:

```sh
uv tool install -e .
```

This installs:
- `renderknecht` — the renderer CLI (runs inside the container, or locally if pandoc is available)
- `renderknecht-wrapper` — the podman wrapper for host-side use

Usage: `renderknecht-wrapper < input.md > output.pdf`

The wrapper (`src/renderknecht/podman_wrapper.py`) mounts
`$XDG_CONFIG_HOME/renderknecht/` (default: `~/.config/renderknecht/`) into the container as
`RESOURCES_DIR=/resources` when that directory exists, then replaces itself with
`podman run` via `os.execvp`. Override the image:

```sh
RENDERKNECHT_IMAGE=renderknecht:dev renderknecht-wrapper < input.md > output.pdf
```

## Container modes

Two operating modes, selected by the first CMD argument passed to `entrypoint.sh`:

- **Render mode** (first arg is `render`): set by the wrapper; runs the renderknecht CLI
- **Serve mode** (no arg / default): started by `compose.yaml`; runs the Flask web UI

Resource override priority (highest to lowest):

- `PREAMBLE_YAML` / `AUTHORS_YAML` env vars
- `RESOURCES_DIR/<file>`
- `$XDG_CONFIG_HOME/renderknecht/<file>` (auto-mounted by wrapper)
- Bundled defaults in `src/renderknecht/resources/`

## Testing Patterns

- Naming: test files `test_<feature>.py`, test functions `test_<action>_<expected_outcome>`.
- Isolate environment-dependent tests using the `provide_env` fixture (copies/restores `os.environ`).
- Set `os.environ["PREAMBLE_YAML"] = "/dev/null"` in tests that should not load the default preamble.
- Use `unittest.mock.patch` for external HTTP calls (e.g. PlantUML server).

## Implementation Details

- Add concise/precise docstrings to utility functions.
  - Docstrings use Python Sphinx format (e.g. `:param foo:`, `:returns:`, `:raises ValueError:`).
- Add Python type hints where possible.
- Prefer pragmatic solutions; if a shortcut is taken, call out the shortcomings explicitly.
- Bundled resources are accessed via `importlib.resources.files("renderknecht") / "resources"`;
  environment variables are checked first as overrides.
