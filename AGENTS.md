# AGENTS.md

## Repository Overview

- Purpose: Renders Markdown files into PDFs via pandoc and the eisvogel LaTeX template.
- Core tech: Python, pandoc, Flask (web mode), GraphViz, PlantUML, Mermaid (mmdc + Chromium), uv, ruff, ty, pytest, hatchling.

Used (minimum) versions can be found in pyproject.toml.

## Layout

- `src/renderknecht/`: main Python package (src layout)
  - `renderers/`: pandoc-based Markdown → PDF renderer (`pandoc.py` lists the diagram tools in `TOOLS`)
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

## Supply chain

The image build pins every part of the toolchain. See the `Pinned versions` section
in README.md and the `ARG` block at the top of `Dockerfile.renderknecht`.

- The base image is `debian:trixie-slim` at an image digest.
- apt packages come from one Debian snapshot, not from `unstable`. A mixed apt pool
  is what made texlive configuration fail during the build.
- Each download is checked against a SHA-256 checksum before it is installed.
- `uv sync --locked` fails the build when `uv.lock` is stale.
- The build renders one small PDF at the end through `render_markdown`. That test covers
  preamble.yaml, the pandoc filters and the template. If that render fails, the build
  fails.

When you bump a version, change one version at a time. Then run a few renders and
compare the PDFs. pandoc-crossref is built for one pandoc version, so its version
changes together with pandoc.

The npm parts carry no checksum in the Dockerfile. npm makes sure that each package it
downloads is intact, and the two `ARG` values set the versions we name. npm still picks
the newest build of each package that mermaid-cli needs, so you cannot fix the whole npm
tree with those two values. Chrome comes from the puppeteer version inside mermaid-cli,
so nothing pins the Chrome version of its own.

Mermaid runs through the Chrome headless shell, not the full browser. `fontconfig` and
`fonts-liberation` are in the image, because Chrome draws no text when it finds no
font on the system.

## Diagram rendering

`embed_diagrams()` in `renderers/pandoc.py` renders diagram blocks before pandoc
runs. It rewrites each block into an image reference that points at a temporary
file. `TOOLS` in the same file lists the tools and their fence languages:

| Fence | Renderer | Output | Works in render mode? |
|-------|----------|--------|-----------------------|
| `graphviz` | `dot`, through the `graphviz` package | `.svg` | yes |
| `plantuml` | the `plantuml:8080` service | `.svg` | no |
| `mermaid` | the `mmdc` command | `.pdf` | yes |

The `plantuml` service exists only inside the compose network, so render mode
cannot reach it.

Adding a tool means one `render_<name>()` function and one `TOOLS` entry. The
fence regex comes from `TOOLS`, so you change nothing else.

Mermaid output is a PDF from Chromium, not an SVG from librsvg. Pandoc converts SVG with
librsvg, and Mermaid SVG does not survive that step. librsvg drops the text inside
`<foreignObject>` elements, which carry Mermaid labels by default. librsvg drops text
inside a group that holds a CSS `filter:` or `opacity:` declaration.

librsvg also drops the spaces between the per-word `<tspan>` elements that Mermaid
writes. The PDF from `mmdc -o out.pdf` matches what a browser shows for every diagram
type.

- `MERMAID_ARGS` passes extra arguments to `mmdc`. The image ships
  `/etc/renderknecht/puppeteer.json`, which sets `--no-sandbox`, because Chromium
  runs as root inside the container.
- mermaid-cli 12.0.0 is the newest CLI release. It asks for `mermaid ^12.0.0`, so the
  image installs mermaid 12.2.0 next to it. A test makes sure that `mmdc` loads that
  copy. If npm puts another copy in a nested folder, the build stops. `mmdc` loads
  that copy instead of the pinned one.
- The image build renders one diagram with `mmdc`. If `mmdc` cannot render it, the build
  stops. A broken browser otherwise fails on the first real document.

## Testing Patterns

- Naming: test files `test_<feature>.py`, test functions `test_<action>_<expected_outcome>`.
- Isolate environment-dependent tests using the `provide_env` fixture (copies/restores `os.environ`).
- Set `os.environ["PREAMBLE_YAML"] = "/dev/null"` in tests that should not load the default preamble.
- Use `unittest.mock.patch` for external HTTP calls (e.g. PlantUML server).
- Patch `subprocess.run` for the Mermaid renderer. The fake writes a file to the
  path after `-o` (see `_fake_mmdc`). For each tool in `TOOLS`, keep one test that
  shows that the fence matches and that the tool uses its own file suffix.

## Implementation Details

- Eisvogel 3.5 loads the LaTeX package `sourcesans` when the document sets no font
  family. Debian trixie has the older name `sourcesanspro` only, so the renderer
  defaults `fontfamily: sourcesanspro` with `fontfamilyoptions: [default]`. The option
  is needed, because the package only defines the font. Without the option, the
  document keeps the serif font that LaTeX starts with. Eisvogel only loads
  `sourcecodepro` (the code font) when no font family is set, so the renderer adds
  that include itself: `CODE_FONT_INCLUDE` in `renderers/pandoc.py`. It also keeps
  document front-matter `header-includes` from replacing the preamble entries.
  A wrong font does not fail the build, so look at a rendered PDF after you change
  the template or the Debian snapshot.
- The default preamble needs `tcolorbox`, so the image needs `texlive-latex-extra`. That
  package arrives through Recommends, not by name. If you turn Recommends off, add
  `texlive-latex-extra` to the package list. The render in the image build finds this
  kind of fault.

- Add concise/precise docstrings to utility functions.
  - Docstrings use Python Sphinx format (e.g. `:param foo:`, `:returns:`, `:raises ValueError:`).
- Add Python type hints where possible.
- Prefer pragmatic solutions; if a shortcut is taken, call out the shortcomings explicitly.
- Bundled resources are accessed via `importlib.resources.files("renderknecht") / "resources"`;
  environment variables are checked first as overrides.
