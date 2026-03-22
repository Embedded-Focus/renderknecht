RUNTIME ?= podman
GIT_HASH ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)

.PHONY: build
build:
	$(RUNTIME) build \
		--build-arg GIT_HASH=$(GIT_HASH) \
		-t renderknecht:latest \
		-f Dockerfile.renderknecht .
