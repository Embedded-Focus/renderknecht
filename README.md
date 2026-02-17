# Renderknecht

Renders Markdown files into beautiful PDFs.

Build it:

``` shell
podman build -t renderknecht:latest -f Dockerfile.renderknecht .
```

Run it:

``` shell
podman run --rm -i \
	-e PREAMBLE_YAML=preamble.yaml \
	-e AUTHORS_YAML=authors.yaml \
	renderknecht:latest uv run cli.py < input.md > output.pdf
```
