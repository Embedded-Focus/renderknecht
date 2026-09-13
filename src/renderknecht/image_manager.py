from __future__ import annotations

import datetime as dt
import hashlib
import importlib.metadata
import importlib.resources
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

_ASSETS = importlib.resources.files("renderknecht.image_assets")
_PACKAGE = importlib.resources.files("renderknecht")
_RUNTIMES = ("podman", "docker")
_ARCHITECTURES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
_GITHUB_API = "https://api.github.com/repos"


class ImageError(RuntimeError):
    """Report a local image-management failure."""


def package_version() -> str:
    """Return the installed Renderknecht distribution version."""
    try:
        return importlib.metadata.version("renderknecht")
    except importlib.metadata.PackageNotFoundError:
        return "0+unknown"


def detect_runtime() -> str:
    """Find the requested container runtime, preferring Podman.

    :returns: Executable name for the selected runtime.
    :raises ImageError: if the override is invalid or no runtime is installed.
    """
    override = os.environ.get("RENDERKNECHT_RUNTIME")
    if override:
        if override not in _RUNTIMES:
            raise ImageError("RENDERKNECHT_RUNTIME must be 'podman' or 'docker'")
        if not shutil.which(override):
            raise ImageError(f"requested container runtime '{override}' was not found on PATH")
        return override
    for runtime in _RUNTIMES:
        if shutil.which(runtime):
            return runtime
    raise ImageError("no container runtime found on PATH; install Podman or Docker")


def architecture() -> str:
    """Map the host machine to an architecture supported by the manifest."""
    machine = platform.machine().lower()
    try:
        return _ARCHITECTURES[machine]
    except KeyError as error:
        supported = ", ".join(sorted(set(_ARCHITECTURES.values())))
        raise ImageError(f"unsupported architecture '{machine}'; supported: {supported}") from error


def state_dir() -> Path:
    """Return the XDG directory containing image state and resolved manifests."""
    root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return root / "renderknecht"


def load_bundled_manifest() -> dict[str, Any]:
    """Load the tested dependency manifest included in the distribution."""
    return tomllib.loads((_ASSETS / "manifest.toml").read_text(encoding="utf-8"))


def load_resolved_manifest(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load a saved resolved manifest for a reproducible rebuild.

    :param path: JSON manifest path previously reported by ``image status``.
    :returns: Validated manifest data without its informational timestamp.
    :raises ImageError: if the file is invalid or belongs to another package version.
    """
    manifest_path = Path(path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.pop("resolved_at", None)
        for key in ("schema", "renderknecht", "architecture", "base", "container", "artifacts"):
            if key not in manifest:
                raise KeyError(key)
    except (OSError, json.JSONDecodeError, KeyError, AttributeError) as error:
        raise ImageError(f"invalid resolved manifest at {manifest_path}: {error}") from error
    if manifest["renderknecht"] != package_version():
        raise ImageError(
            f"manifest requires renderknecht {manifest['renderknecht']}, installed version is {package_version()}"
        )
    return manifest


def _selected_manifest(manifest: Mapping[str, Any], arch: str) -> dict[str, Any]:
    selected = {
        "schema": manifest["schema"],
        "renderknecht": package_version(),
        "architecture": arch,
        "base": manifest["base"],
        "renderer": manifest["renderer"],
        "container": manifest["container"],
        "artifacts": {
            **manifest["artifacts"][arch],
            **manifest["artifacts"]["common"],
        },
    }
    return json.loads(json.dumps(selected))


def _fingerprint(manifest: Mapping[str, Any]) -> str:
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _tag(manifest: Mapping[str, Any]) -> str:
    return f"renderknecht:{manifest['renderknecht']}-local-{_fingerprint(manifest)[:12]}"


def _active_state() -> dict[str, Any] | None:
    path = state_dir() / "active.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ImageError(f"could not read image state at {path}: {error}") from error


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _run(
    command: Sequence[str],
    *,
    input: bytes | None = None,
    stdout: int | None = None,
    stderr: int | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(  # noqa: S603
            command,
            check=True,
            input=input,
            stdout=stdout,
            stderr=stderr,
        )
    except FileNotFoundError as error:
        raise ImageError(f"could not run {command[0]}: {error}") from error
    except subprocess.CalledProcessError as error:
        message = f"command failed with exit status {error.returncode}: {' '.join(command)}"
        if error.stderr:
            details = error.stderr.decode(errors="replace").strip()
            if details:
                message = f"{message}\n{details}"
        raise ImageError(message) from error


def _image_exists(runtime: str, tag: str) -> bool:
    result = subprocess.run(  # noqa: S603
        [runtime, "image", "inspect", tag],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _copy_tree(source: Traversable, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        if child.name.startswith(".") or child.name == "__pycache__" or child.name.endswith((".pyc", ".pyo")):
            continue
        target = destination / child.name
        if child.is_dir():
            _copy_tree(child, target)
        else:
            target.write_bytes(child.read_bytes())


def _download(url: str, destination: Path, expected_sha256: str) -> None:
    print(f"Downloading {url}", file=sys.stderr)
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(url, timeout=120) as response, destination.open("wb") as output:  # noqa: S310
            while block := response.read(1024 * 1024):
                output.write(block)
                digest.update(block)
    except (OSError, urllib.error.URLError) as error:
        raise ImageError(f"could not download {url}: {error}") from error
    actual = digest.hexdigest()
    if actual != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ImageError(f"checksum mismatch for {url}: expected {expected_sha256}, got {actual}")


def _prepare_context(context: Path, manifest: Mapping[str, Any]) -> None:
    for name in ("Containerfile", "entrypoint.sh", "container-requirements.txt"):
        (context / name).write_bytes((_ASSETS / name).read_bytes())
    _copy_tree(_PACKAGE, context / "package")
    artifacts_dir = context / "artifacts"
    artifacts_dir.mkdir()
    for artifact in manifest["artifacts"].values():
        _download(artifact["url"], artifacts_dir / artifact["filename"], artifact["sha256"])


def _smoke_test(runtime: str, tag: str) -> None:
    markdown = (_ASSETS / "smoke.md").read_bytes()
    print(f"Smoke-testing {tag}", file=sys.stderr)
    result = _run(
        [runtime, "run", "--rm", "-i", tag, "render"],
        input=markdown,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if not result.stdout.startswith(b"%PDF-"):
        details = result.stderr.decode(errors="replace").strip()
        raise ImageError(f"image smoke test did not produce a PDF{': ' + details if details else ''}")


def build(*, force: bool = False, manifest: Mapping[str, Any] | None = None) -> str:
    """Build, smoke-test, and activate an image from a resolved manifest.

    :param force: Rebuild even when the image is already present.
    :param manifest: Optional resolved manifest; the bundled manifest is used by default.
    :returns: Tag of the activated image.
    """
    runtime = detect_runtime()
    resolved = dict(manifest or _selected_manifest(load_bundled_manifest(), architecture()))
    tag = _tag(resolved)
    if force or not _image_exists(runtime, tag):
        print(f"Building {tag} with {runtime}", file=sys.stderr)
        with tempfile.TemporaryDirectory(prefix="renderknecht-build-") as directory:
            context = Path(directory)
            _prepare_context(context, resolved)
            _run(
                [
                    runtime,
                    "build",
                    "--file",
                    str(context / "Containerfile"),
                    "--tag",
                    tag,
                    "--build-arg",
                    f"BASE_IMAGE={resolved['base']['image']}",
                    "--build-arg",
                    f"RENDERKNECHT_VERSION={package_version()}",
                    "--build-arg",
                    f"MANIFEST_FINGERPRINT={_fingerprint(resolved)}",
                    "--build-arg",
                    f"SYSTEM_PACKAGES={' '.join(resolved['container']['system_packages'])}",
                    str(context),
                ]
            )
    _smoke_test(runtime, tag)

    fingerprint = _fingerprint(resolved)
    manifest_path = state_dir() / "manifests" / f"{fingerprint}.json"
    stored_manifest = {**resolved, "resolved_at": dt.datetime.now(dt.UTC).isoformat()}
    _write_json(manifest_path, stored_manifest)
    _write_json(
        state_dir() / "active.json",
        {"fingerprint": fingerprint, "image": tag, "manifest": str(manifest_path), "runtime": runtime},
    )
    print(f"Activated {tag}", file=sys.stderr)
    return tag


def _github_release(repository: str, release: str = "latest") -> dict[str, Any]:
    url = f"{_GITHUB_API}/{repository}/releases/{release}"
    request = urllib.request.Request(  # noqa: S310
        url, headers={"Accept": "application/vnd.github+json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise ImageError(f"could not resolve upstream release {repository}: {error}") from error


def _asset(release: Mapping[str, Any], name: str) -> dict[str, str]:
    for item in release.get("assets", []):
        if item.get("name") == name and str(item.get("digest", "")).startswith("sha256:"):
            return {
                "filename": name,
                "url": item["browser_download_url"],
                "sha256": item["digest"].removeprefix("sha256:"),
            }
    raise ImageError(f"release {release.get('tag_name', '<unknown>')} has no checksummed asset {name}")


def resolve_updates() -> dict[str, Any]:
    """Resolve a Pandoc-compatible set from current upstream release metadata."""
    crossref = _github_release("lierdakil/pandoc-crossref")
    body = crossref.get("body", "")
    match = re.search(r"built with Pandoc v(\d+\.\d+(?:\.\d+)?)", body)
    if not match:
        raise ImageError("pandoc-crossref release does not declare its Pandoc build version")
    pandoc_version = match.group(1)
    pandoc = _github_release("jgm/pandoc", f"tags/{pandoc_version}")
    eisvogel = _github_release("Wandmalfarbe/pandoc-latex-template")
    crossref_version = str(crossref["tag_name"]).removeprefix("v")
    eisvogel_version = str(eisvogel["tag_name"]).removeprefix("v")

    base = load_bundled_manifest()
    artifacts: dict[str, dict[str, dict[str, str]]] = {}
    for arch, pandoc_arch, crossref_arch in (
        ("amd64", "amd64", "X64"),
        ("arm64", "arm64", "ARM64"),
    ):
        artifacts[arch] = {
            "pandoc": _asset(pandoc, f"pandoc-{pandoc_version}-linux-{pandoc_arch}.tar.gz"),
            "pandoc_crossref": _asset(crossref, f"pandoc-crossref-Linux-{crossref_arch}.tar.xz"),
        }
        artifacts[arch]["pandoc"]["filename"] = "pandoc.tar.gz"
        artifacts[arch]["pandoc_crossref"]["filename"] = "pandoc-crossref.tar.xz"
    eisvogel_asset = _asset(eisvogel, f"Eisvogel-{eisvogel_version}.tar.gz")
    eisvogel_asset["filename"] = "eisvogel.tar.gz"
    base["renderer"] = {
        "pandoc": pandoc_version,
        "pandoc_crossref": crossref_version,
        "eisvogel": eisvogel_version,
    }
    base["artifacts"] = {**artifacts, "common": {"eisvogel": eisvogel_asset}}
    return _selected_manifest(base, architecture())


def update() -> str:
    """Resolve, display, build, test, and activate compatible upstream releases."""
    current = _selected_manifest(load_bundled_manifest(), architecture())
    proposed = resolve_updates()
    print("Proposed renderer versions:", file=sys.stderr)
    for name, version in proposed["renderer"].items():
        old = current["renderer"].get(name)
        print(f"  {name}: {old} -> {version}", file=sys.stderr)
    fingerprint = _fingerprint(proposed)
    _write_json(
        state_dir() / "manifests" / f"{fingerprint}.json",
        {**proposed, "resolved_at": dt.datetime.now(dt.UTC).isoformat()},
    )
    return build(manifest=proposed)


def print_status() -> None:
    """Print the selected runtime and active image state."""
    runtime = detect_runtime()
    active = _active_state()
    print(f"Runtime: {runtime}")
    if not active:
        print("Active image: none")
        return
    available = _image_exists(runtime, active["image"])
    print(f"Active image: {active['image']}")
    print(f"Available: {'yes' if available else 'no'}")
    print(f"Manifest: {active['manifest']}")


def remove() -> None:
    """Remove locally managed images and clear active state."""
    runtime = detect_runtime()
    active = _active_state()
    tags: set[str] = set()
    if active and _image_exists(runtime, active["image"]):
        tags.add(active["image"])
    result = subprocess.run(  # noqa: S603
        [runtime, "images", "--format", "{{.Repository}}:{{.Tag}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ImageError(
            f"could not list {runtime} images: {result.stderr.strip() or 'unknown runtime error'}"
        )
    tags.update(
        line for line in result.stdout.splitlines() if line.startswith("renderknecht:") and "-local-" in line
    )
    if tags:
        _run([runtime, "image", "rm", *sorted(tags)])
    (state_dir() / "active.json").unlink(missing_ok=True)
    print(f"Removed {len(tags)} managed image(s)", file=sys.stderr)


def _render_command(runtime: str, image: str, renderer_args: Sequence[str]) -> list[str]:
    work_dir = Path.cwd().resolve()
    command = [runtime, "run", "--rm", "-i", "-v", f"{work_dir}:/work:ro", "-e", "WORK_DIR=/work"]
    configured_resources = os.environ.get("RESOURCES_DIR")
    config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    resources = Path(configured_resources) if configured_resources else config_root / "renderknecht"
    if resources.is_dir():
        command += ["-v", f"{resources.resolve()}:/resources:ro", "-e", "RESOURCES_DIR=/resources"]
    elif configured_resources:
        raise ImageError(f"RESOURCES_DIR is not a directory: {resources}")
    for variable, mount_name in (
        ("PREAMBLE_YAML", "preamble"),
        ("AUTHORS_YAML", "authors"),
    ):
        configured_file = os.environ.get(variable)
        if not configured_file:
            continue
        path = Path(configured_file)
        if not path.is_file():
            raise ImageError(f"{variable} is not a file: {path}")
        container_dir = f"/renderknecht-overrides/{mount_name}"
        command += [
            "-v",
            f"{path.resolve().parent}:{container_dir}:ro",
            "-e",
            f"{variable}={container_dir}/{path.name}",
        ]
    return [*command, image, "render", *renderer_args]


def render(renderer_args: Sequence[str]) -> None:
    """Replace this process with a containerized render invocation."""
    runtime = detect_runtime()
    custom_image = os.environ.get("RENDERKNECHT_IMAGE")
    if custom_image:
        image = custom_image
    else:
        active = _active_state()
        image = build() if not active or not _image_exists(runtime, active["image"]) else active["image"]
    command = _render_command(runtime, image, renderer_args)
    os.execvp(runtime, command)  # noqa: S606, S607
