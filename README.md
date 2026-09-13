<div align="center">

<img src="assets/renderknecht_logo.png" alt="Renderknecht" width="260">

# Renderknecht

*Render Markdown files into polished PDFs with pandoc and Eisvogel.*

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/Embedded-Focus/renderknecht/actions/workflows/ci.yml/badge.svg)](https://github.com/Embedded-Focus/renderknecht/actions/workflows/ci.yml)
[![Security](https://github.com/Embedded-Focus/renderknecht/actions/workflows/security.yml/badge.svg)](https://github.com/Embedded-Focus/renderknecht/actions/workflows/security.yml)
[![Dependabot](https://img.shields.io/badge/dependabot-enabled-025e8c?logo=dependabot)](https://github.com/Embedded-Focus/renderknecht/security/dependabot)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Flask](https://img.shields.io/badge/Flask-web%20UI-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Pandoc](https://img.shields.io/badge/Pandoc-renderer-2F7BBF)](https://pandoc.org/)
[![Podman](https://img.shields.io/badge/Podman-supported-892CA0?logo=podman&logoColor=white)](https://podman.io/)
[![uv](https://img.shields.io/badge/uv-supported-DE5FE9)](https://docs.astral.sh/uv/)
[![Last commit](https://img.shields.io/github/last-commit/Embedded-Focus/renderknecht?logo=github)](https://github.com/Embedded-Focus/renderknecht/commits/main)

**[Requirements](#requirements)** ·
**[Quick Start](#quick-start)** ·
**[Per-user Resources](#per-user-resources)** ·
**[Markdown Front Matter](#markdown-front-matter)** ·
**[Container Stack](#container-stack-hedgedoc--renderknecht)** ·
**[Resource Overrides](#advanced-resource-overrides)** ·
**[Releasing](https://github.com/Embedded-Focus/renderknecht/blob/main/RELEASING.md)**

</div>

Renders Markdown files into beautiful PDFs via [pandoc](https://pandoc.org/) and the
[eisvogel](https://github.com/Wandmalfarbe/pandoc-latex-template) LaTeX template.

Install Renderknecht from a Python package index and use Podman or Docker locally.

## Requirements

To install and use Renderknecht, the host needs:

- Linux on x86-64 or ARM64
- Podman or Docker, configured to build and run containers
- Either `uv`, or Python 3.12 or newer with a Python package installer such as `pip` or `pipx`
- Network access during installation and the first local image build

Pandoc, LaTeX, Graphviz, and Eisvogel do not need to be installed on the host.

## Quick start

**1. Install the host command**:

```sh
uv tool install renderknecht
```

For a release published only to TestPyPI:

```sh
uv tool install --index https://test.pypi.org/simple/ renderknecht
```

**2. Build the tested local image**:

```sh
renderknecht image build
```

The first render also builds the image automatically when no active image exists.

**3. Render**:

```sh
renderknecht < input.md > output.pdf
```

The host command always mounts the **current working directory** read-only into the
container (`/work`), so relative image references in the Markdown resolve
correctly as long as the images live alongside the input file:

```sh
cd /my/project
renderknecht < report.md > report.pdf   # images in /my/project/ work
```

`renderknecht-wrapper` remains available as a compatibility alias.

## Image management

The package carries a pinned manifest and a Containerfile. Downloads are SHA-256 verified,
the build uses a private temporary context, and a new image becomes active only after it
renders a smoke-test PDF successfully.

```sh
renderknecht image status   # show the runtime and active image
renderknecht image build    # build the bundled, tested dependency set
renderknecht image update   # resolve compatible upstream releases and test them
renderknecht image rebuild  # force a clean rebuild of the bundled image
renderknecht image remove   # remove locally managed images
```

Image manifests and active state are stored below
`${XDG_STATE_HOME:-~/.local/state}/renderknecht/`.
Rebuild any saved manifest exactly with
`renderknecht image build --manifest /path/to/manifest.json`.

## Build from a Git clone

The original repository workflow remains supported:

```sh
git clone https://github.com/Embedded-Focus/renderknecht.git
cd renderknecht
make build                    # Podman by default
make build RUNTIME=docker     # or Docker
uv tool install -e .
RENDERKNECHT_IMAGE=renderknecht:latest renderknecht < input.md > output.pdf
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

Override the image name used by the host command:

```sh
RENDERKNECHT_IMAGE=renderknecht:dev renderknecht < input.md > output.pdf
```
