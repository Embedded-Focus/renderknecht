<div align="center">

<img src="assets/renderknecht_logo.png" alt="Renderknecht" width="260">

# Renderknecht

*Render Markdown files into polished PDFs with pandoc and Eisvogel.*

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Flask](https://img.shields.io/badge/Flask-web%20UI-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Pandoc](https://img.shields.io/badge/Pandoc-renderer-2F7BBF)](https://pandoc.org/)
[![Podman](https://img.shields.io/badge/Podman-supported-892CA0?logo=podman&logoColor=white)](https://podman.io/)
[![uv](https://img.shields.io/badge/uv-supported-DE5FE9)](https://docs.astral.sh/uv/)
[![Last commit](https://img.shields.io/github/last-commit/Embedded-Focus/renderknecht?logo=github)](https://github.com/Embedded-Focus/renderknecht/commits/main)

**[Quick Start](#quick-start)** ·
**[Per-user Resources](#per-user-resources)** ·
**[Markdown Front Matter](#markdown-front-matter)** ·
**[Container Stack](#container-stack-hedgedoc--renderknecht)** ·
**[Resource Overrides](#advanced-resource-overrides)**

</div>

Renders Markdown files into beautiful PDFs via [pandoc](https://pandoc.org/) and the
[eisvogel](https://github.com/Wandmalfarbe/pandoc-latex-template) LaTeX template.

All tooling (pandoc, LaTeX, graphviz) runs inside a container — nothing to install locally
beyond podman.

## Quick start

**1. Build the image** (once):

```sh
make build              # uses podman by default
make build RUNTIME=docker  # use Docker instead
```

**2. Install** (gets both `renderknecht` and `renderknecht-wrapper`):

```sh
uv tool install -e .
```

**3. Render**:

```sh
renderknecht-wrapper < input.md > output.pdf
```

The wrapper always mounts the **current working directory** read-only into the
container (`/work`), so relative image references in the Markdown resolve
correctly as long as the images live alongside the input file:

```sh
cd /my/project
renderknecht-wrapper < report.md > report.pdf   # images in /my/project/ work
```

## Per-user resources

Place custom resources in `~/.config/renderknecht/` (respects `$XDG_CONFIG_HOME`).
The wrapper mounts that directory read-only into the container automatically.

```
~/.config/renderknecht/
├── preamble.yaml   # LaTeX/pandoc front-matter defaults
├── authors.yaml    # short name → display name mapping
└── logo.pdf        # referenced via titlepage-logo in front matter
```

Any file present there takes priority over the bundled defaults.

## Markdown front matter

Renderknecht merges the default preamble with the document's YAML front matter.
The document always wins over preamble defaults. Example:

```yaml
---
title: My Document
author:
  - rainer
date: 2026-03-06
titlepage-logo: logo.pdf
---
```

Authors listed in `authors.yaml` are expanded to their full display names automatically.

## Container stack (HedgeDoc + renderknecht)

```sh
podman compose up
```

Starts HedgeDoc, PlantUML, Caddy, and the renderknecht web service. The renderknecht
service auto-detects whether it is running in render mode (stdin pipe) or serve mode
(no stdin / detached).

The HedgeDoc uploads volume is shared with the renderknecht service, so images
uploaded to HedgeDoc are embedded in the PDF automatically — no additional
configuration required.

## Advanced: resource overrides

The wrapper exposes the same override mechanism as the container directly:

| Mechanism | Description |
|-----------|-------------|
| `~/.config/renderknecht/` | Per-user XDG config dir (auto-mounted by wrapper) |
| `RESOURCES_DIR=/path` | Mount an arbitrary directory; overrides XDG |
| `PREAMBLE_YAML=/path` | Override just the preamble (highest priority) |
| `AUTHORS_YAML=/path` | Override just the authors map (highest priority) |

```sh
podman run --rm -i \
    -v /my/project:/resources:ro \
    -e RESOURCES_DIR=/resources \
    renderknecht:latest < input.md > output.pdf
```

Override the image name used by the wrapper:

```sh
RENDERKNECHT_IMAGE=renderknecht:dev renderknecht-wrapper < input.md > output.pdf
```
