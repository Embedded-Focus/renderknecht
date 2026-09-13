# Changelog

## 0.1.0

- Add the installable `renderknecht` host command with Docker and Podman detection.
- Build pinned AMD64 and ARM64 renderer images from assets carried in the Python distribution.
- Verify upstream artifacts and locked Python dependencies before each image build.
- Add image status, build, update, rebuild, removal, smoke testing, rollback, and manifest replay.
- Keep `renderknecht-wrapper` and the Git clone plus `make build` workflow compatible.
- Add trusted publishing and end-to-end verification for TestPyPI.
