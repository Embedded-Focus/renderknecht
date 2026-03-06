# Renderknecht

Renders Markdown files into beautiful PDFs via [pandoc](https://pandoc.org/) and the
[eisvogel](https://github.com/Wandmalfarbe/pandoc-latex-template) LaTeX template.

## Local Installation

Requires pandoc, texlive, and graphviz to be installed on your system.

```sh
uv tool install /path/to/renderknecht
```

This adds `renderknecht` to `~/.local/bin`. Render a document:

```sh
renderknecht < input.md > output.pdf
```

### Per-user resources

Place custom resources in `~/.config/renderknecht/` (respects `$XDG_CONFIG_HOME`):

```
~/.config/renderknecht/
├── preamble.yaml   # LaTeX/pandoc front-matter defaults
├── authors.yaml    # display name → full name mapping
└── logo.pdf        # referenced from titlepage-logo in front matter
```

Any file present there takes priority over the bundled defaults.

## Container

### Build

```sh
podman build -t renderknecht:latest -f Dockerfile.renderknecht .
```

### Run

Two modes are selected automatically based on how stdin is connected:

**Render mode** (stdin is a pipe or file):

```sh
renderknecht:latest < input.md > output.pdf
```

**Serve mode** (no stdin / detached): started via `compose.yaml`; runs the HedgeDoc +
renderknecht web stack.

```sh
podman compose up
```

### Resource overrides

Pass a directory of resources via `RESOURCES_DIR`, or override individual files:

```sh
podman run --rm -i \
    -v /my/project:/resources:ro \
    -e RESOURCES_DIR=/resources \
    renderknecht:latest < input.md > output.pdf
```

Priority (highest to lowest): `PREAMBLE_YAML` / `AUTHORS_YAML` env vars →
`RESOURCES_DIR/<file>` → `~/.config/renderknecht/<file>` → bundled defaults.

## Markdown front matter

Renderknecht merges a default preamble with the document's YAML front matter. The document
always wins over the preamble defaults. Example:

```yaml
---
title: My Document
author:
  - rainer
date: 2026-03-06
titlepage-logo: /path/to/logo.pdf
---
```

Authors listed in `authors.yaml` are expanded to their full display names automatically.
