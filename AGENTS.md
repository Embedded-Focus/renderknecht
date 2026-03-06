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

## Local Installation

Install renderknecht as a user tool (requires pandoc, texlive, and graphviz on PATH):

```sh
uv tool install /path/to/renderknecht   # from local checkout
```

This adds `renderknecht` to `~/.local/bin`. Usage:

```sh
renderknecht < input.md > output.pdf
```

Per-user resources are read from `$XDG_CONFIG_HOME/renderknecht/` (default: `~/.config/renderknecht/`).
Place any of `preamble.yaml`, `authors.yaml`, or logo PDFs there; they take priority over the
bundled defaults.

## Container Usage

Two operating modes, selected automatically by `entrypoint.sh`:

- **Render mode** (stdin is a pipe/file): `podman run --rm -i renderknecht:latest < input.md > output.pdf`
- **Serve mode** (no stdin / TTY): started by `compose.yaml`; runs the Flask web UI

Resource overrides (optional, all modes):

- `~/.config/renderknecht/<file>` — per-user XDG config dir (local tool installs).
- `RESOURCES_DIR=/path/to/dir` — directory containing `preamble.yaml`, `authors.yaml`, and/or logo PDFs; takes priority over XDG and bundled defaults.
- `PREAMBLE_YAML=/path/to/preamble.yaml` — override just the preamble (highest priority).
- `AUTHORS_YAML=/path/to/authors.yaml` — override just the authors map (highest priority).

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
