import base64
import copy
import datetime
import importlib.resources
import logging
import os
import re
import string
import subprocess
import tempfile
from collections.abc import Callable
from io import FileIO
from pathlib import Path
from zlib import compress

import httpx
import yaml
from graphviz import Source
from yaml import SafeLoader

from ..util import yaml as util_yaml
from ..util.pandoc_wrapper import determine_pandoc_arguments

_RESOURCES = importlib.resources.files("renderknecht") / "resources"


def _resource_path(name: str) -> Path:
    return Path(str(_RESOURCES / name))


def _resolve_resource(specific_env_var: str, filename: str) -> Path | None:
    """Return the path to a resource file, or None to use the bundled default.

    Priority: specific env var > RESOURCES_DIR/<filename>
              > XDG_CONFIG_HOME/renderknecht/<filename> > bundled default.
    """
    if specific_env_var in os.environ:
        return Path(os.environ[specific_env_var])
    if "RESOURCES_DIR" in os.environ:
        candidate = Path(os.environ["RESOURCES_DIR"]) / filename
        if candidate.exists():
            return candidate
    xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    candidate = xdg_config / "renderknecht" / filename
    if candidate.exists():
        return candidate
    return None


def augment_authors(yaml_metadata: dict, authors: dict) -> dict:
    if yaml_metadata and "author" in yaml_metadata:
        result = copy.copy(yaml_metadata)
        result["author"] = [authors.get(author, author) for author in yaml_metadata["author"]]
        return result
    return yaml_metadata


def embed_images(markdown: str) -> str:
    if "CMD_DOMAIN" not in os.environ:
        logging.debug("CMD_DOMAIN variable has not been defined. Not embedding images.")
        return markdown

    app_hostname = os.environ["CMD_DOMAIN"]

    # embed images
    return markdown.replace(f"https://{app_hostname}", "http://app:3000")


def render_graphviz(markup: str) -> str:
    return Source(markup).pipe(format="svg").decode("utf-8")


PLANTUML_ALPHABET = string.digits + string.ascii_uppercase + string.ascii_lowercase + "-_"
BASE64_ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits + "+/"
BASE64_TO_PLANTUML = bytes.maketrans(BASE64_ALPHABET.encode("utf-8"), PLANTUML_ALPHABET.encode("utf-8"))


def render_plantuml(markup: str) -> str:
    # see: https://github.com/dougn/python-plantuml/blob/master/plantuml.py
    zlibbed_str = compress(markup.encode("utf-8"))
    compressed_string = zlibbed_str[2:-4]
    encoded = base64.b64encode(compressed_string).translate(BASE64_TO_PLANTUML).decode("utf-8")
    response = httpx.get(f"http://plantuml:8080/svg/{encoded}")
    response.raise_for_status()
    return response.text


Renderer = Callable[[str], str]
TOOLS: dict[str, Renderer] = {
    "graphviz": render_graphviz,
    "plantuml": render_plantuml,
}

TemporaryFiles = list[FileIO]


def embed_diagrams(markdown: str, tmp_files: TemporaryFiles) -> str:
    def replace(match: re.Match) -> str:
        tool = match.group(1)
        block_content = match.group(6)
        caption = match.group(3) if match.group(3) else ""
        formatting = f"{{ {match.group(5)} }}" if match.group(5) else ""
        with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".svg") as tmp_file:
            tmp_files.append(tmp_file)  # type: ignore
            tmp_file.write(TOOLS[tool](block_content))
            return f"""
![{caption}]({tmp_file.name}){formatting}"""

    return re.sub(
        r"```\s*(graphviz|plantuml)(\s+\[(.*?)(\|(.*?))?\])?\n(.*?)```",
        replace,
        markdown,
        flags=re.DOTALL,
    )


def augment_yaml_preamble(hedgedoc_markdown: str) -> tuple[str, util_yaml.YAMLMetadata]:
    augmented_metadata = {}

    def replace(match: re.Match) -> str:
        nonlocal augmented_metadata
        preamble_path = _resolve_resource("PREAMBLE_YAML", "preamble.yaml")
        if preamble_path:
            with preamble_path.open(mode="r") as fh:
                preamble_data: util_yaml.YAMLMetadata = yaml.load(fh, Loader=SafeLoader)
            if preamble_data and "titlepage-logo" in preamble_data:
                logo = preamble_data["titlepage-logo"]
                if not Path(logo).is_absolute():
                    preamble_data["titlepage-logo"] = str(preamble_path.parent / logo)
        else:
            preamble_data = yaml.safe_load((_RESOURCES / "preamble.yaml").read_text())
            if preamble_data and "titlepage-logo" in preamble_data:
                preamble_data["titlepage-logo"] = str(_resource_path(preamble_data["titlepage-logo"]))
        if preamble_data is not None:
            augmented_metadata = preamble_data

        authors_path = _resolve_resource("AUTHORS_YAML", "authors.yaml")
        if authors_path:
            with authors_path.open(mode="r") as fh:
                authors = yaml.load(fh, Loader=SafeLoader) or {}
        else:
            authors = yaml.safe_load((_RESOURCES / "authors.yaml").read_text()) or {}

        yaml_metadata: util_yaml.YAMLMetadata = yaml.load(
            f"---\n{match.group(1)}",
            Loader=SafeLoader,
        )
        if yaml_metadata is not None:
            augmented_metadata = {**augmented_metadata, **yaml_metadata}

        augmented_metadata = {
            **augmented_metadata,
            **augment_authors(augmented_metadata, authors),
        }

        if augmented_metadata and "titlepage-logo" in augmented_metadata:
            logo = augmented_metadata["titlepage-logo"]
            if not Path(logo).is_absolute() and not Path(logo).exists():
                resolved = _resolve_resource("", logo)
                if resolved:
                    augmented_metadata["titlepage-logo"] = str(resolved)

        if isinstance(augmented_metadata.get("date"), str) and augmented_metadata["date"].lower() == "today":
            augmented_metadata["date"] = datetime.date.today().isoformat()

        return f"---\n{yaml.dump(augmented_metadata, default_flow_style=False, indent=2)}---"

    return re.sub(
        r"^---\s*(.*?)---",
        replace,
        hedgedoc_markdown,
        flags=re.DOTALL,
    ), augmented_metadata


def append_references(markdown: str, yaml_metadata: util_yaml.YAMLMetadata) -> str:
    if yaml_metadata and "references" in yaml_metadata:
        return markdown + "\n\n# References\n"
    return markdown


def prepare_markdown(hedgedoc_markdown: str, tmp_files: list[FileIO]) -> tuple[str, util_yaml.YAMLMetadata]:
    enriched_markdown, yaml_metadata = augment_yaml_preamble(hedgedoc_markdown)
    enriched_markdown = embed_diagrams(enriched_markdown, tmp_files)
    enriched_markdown = embed_images(enriched_markdown)
    enriched_markdown = append_references(enriched_markdown, yaml_metadata)

    return (
        enriched_markdown,
        yaml_metadata,
    )


def render_markdown(markdown: str, tmp_files: list[FileIO]) -> bytes:
    markdown, metadata = prepare_markdown(markdown, tmp_files)

    command = determine_pandoc_arguments(metadata)
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate(input=markdown.encode())
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, " ".join(command), stdout, stderr)
    return stdout
