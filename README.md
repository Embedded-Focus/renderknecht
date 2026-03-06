# Renderknecht

Renders Markdown files into beautiful PDFs via [pandoc](https://pandoc.org/) and the
[eisvogel](https://github.com/Wandmalfarbe/pandoc-latex-template) LaTeX template.

All tooling (pandoc, LaTeX, graphviz) runs inside a container — nothing to install locally
beyond podman.

## Quick start

**1. Build the image** (once):

```sh
podman build -t renderknecht:latest -f Dockerfile.renderknecht .
```

**2. Install** (gets both `renderknecht` and `renderknecht-wrapper`):

```sh
uv tool install -e .
```

**3. Render**:

```sh
renderknecht-wrapper < input.md > output.pdf
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
