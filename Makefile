.PHONY: build
build:
	podman build -t renderknecht:latest -f Dockerfile.renderknecht .
