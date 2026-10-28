import base64
import copy
import datetime
import importlib.resources
import logging
import os
import re
import shlex
import string
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
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


_UPLOADS_DIR = Path("/hedgedoc/public/uploads")

_CREATOR = (
    f"renderknecht {os.environ.get('RENDERKNECHT_GIT_HASH', 'unknown')} "
    "(https://github.com/Embedded-Focus/renderknecht/)"
)

#: Load Source Code Pro as the code (monospace) font. Eisvogel only loads this
#: package itself when no `fontfamily` is set. Our default look needs
#: `fontfamily: sourcesanspro` on Debian trixie, so Eisvogel skips it and the
#: driver loads it instead. Code in this file owns the include, so that no
#: preamble file can lose the code font.
CODE_FONT_INCLUDE = "```{=latex}\n\\usepackage{sourcecodepro}\n```\n"

#: The font family that keeps the look Eisvogel would bring with its default
#: `sourcesans` package. That package is gone from Debian trixie, so trixie's
#: equivalent `sourcesanspro` takes its place. The `default` option is needed,
#: because the package only defines the family. Without it the document keeps
#: the serif font LaTeX starts with.
DEFAULT_FONT_METADATA = {
    "fontfamily": "sourcesanspro",
    "fontfamilyoptions": ["default"],
}


def _as_include_list(value: object) -> list[str]:
    """Return a header-includes value as a list of LaTeX include strings.

    :param value: A header-includes value: None, a string, or a sequence of
        strings.
    :returns: The includes as a list of strings. None becomes an empty list.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def embed_images(markdown: str) -> str:
    """Rewrite HedgeDoc upload URLs to local filesystem paths.

    Replaces any absolute URL pointing to ``/uploads/`` with a path under
    :data:`_UPLOADS_DIR`, which must be mounted from the HedgeDoc uploads
    volume.  When the mount is absent (e.g. in wrapper/render mode), image
    URLs are left unchanged.

    :param markdown: Markdown text to process.
    :returns: Markdown with upload URLs replaced by local file paths.
    """
    if not _UPLOADS_DIR.is_dir():
        logging.debug("HedgeDoc uploads not mounted at %s. Not embedding images.", _UPLOADS_DIR)
        return markdown

    return re.sub(r"https?://[^/]+/uploads/", f"{_UPLOADS_DIR}/", markdown)


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


#: Path of the puppeteer configuration file. The image build creates this file.
#: It tells Chromium to run without its sandbox.
MERMAID_PUPPETEER_CONFIG = "/etc/renderknecht/puppeteer.json"


def render_mermaid(markup: str) -> bytes:
    """Render a Mermaid block to a PDF with the mmdc command.

    pandoc converts SVG to PDF with librsvg, which is the same SVG converter it
    uses for GraphViz and PlantUML. Mermaid SVG does not survive that step.
    librsvg drops the text inside ``<foreignObject>`` elements, which carry
    Mermaid labels by default. It drops text inside a group that holds a CSS
    ``filter`` or ``opacity`` declaration. It also drops the spaces between the
    per-word ``<tspan>`` elements that Mermaid writes. The diagram shapes stay, so
    the page looks nearly right without the text.

    mmdc renders with Chromium instead, so the PDF matches what a browser shows.
    This holds for every Mermaid diagram type.

    :param markup: Mermaid source code.
    :returns: The diagram as PDF bytes.
    :raises FileNotFoundError: if ``mmdc`` is not on PATH.
    :raises subprocess.CalledProcessError: if mmdc rejects the input, for example
        on invalid Mermaid syntax.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        source = Path(tmp_dir) / "diagram.mmd"
        target = Path(tmp_dir) / "diagram.pdf"
        source.write_text(markup, encoding="utf-8")

        command = ["mmdc", "-i", str(source), "-o", str(target), "--quiet"]
        if puppeteer_config := _puppeteer_config():
            command += ["-p", str(puppeteer_config)]
        command += shlex.split(os.environ.get("MERMAID_ARGS", ""))

        process = subprocess.run(command, capture_output=True)  # noqa: S603
        if process.returncode != 0:
            logging.error(
                "mmdc failed to render Mermaid: %s", process.stderr.decode(errors="replace").strip()
            )
            raise subprocess.CalledProcessError(process.returncode, command, process.stdout, process.stderr)
        return target.read_bytes()


def _puppeteer_config() -> Path | None:
    """Return the puppeteer configuration file to pass to mmdc, or None.

    The image ships a configuration file that turns off the Chromium sandbox.
    Chromium needs this, because it runs as root inside the container. That path
    usually does not exist outside the container. A developer who runs the CLI on
    their own machine is one example. mmdc then uses its own sandboxed defaults.

    :returns: Path to a puppeteer configuration file, or None to let mmdc use its
        own defaults.
    """
    candidate = Path(os.environ.get("MERMAID_PUPPETEER_CONFIG", MERMAID_PUPPETEER_CONFIG))
    return candidate if candidate.is_file() else None


Renderer = Callable[[str], str | bytes]


@dataclass(frozen=True)
class Tool:
    """A diagram tool together with the file extension of its output."""

    render: Renderer
    suffix: str


TOOLS: dict[str, Tool] = {
    "graphviz": Tool(render_graphviz, ".svg"),
    "mermaid": Tool(render_mermaid, ".pdf"),
    "plantuml": Tool(render_plantuml, ".svg"),
}

TemporaryFiles = list[FileIO]


def embed_diagrams(markdown: str, tmp_files: TemporaryFiles) -> str:
    """Replace diagram code blocks with references to the rendered diagrams.

    renderknecht renders each block that :data:`TOOLS` names into a temporary
    file, then replaces the block with a Markdown image. Pandoc embeds the
    diagram instead of printing the markup. The fence languages come from
    :data:`TOOLS`, so you add a tool in one place.

    :param markdown: Markdown to process.
    :param tmp_files: List that collects the temporary files for later cleanup.
    :returns: Markdown with diagram blocks replaced by image references.
    """
    fence = "|".join(sorted(TOOLS))

    def replace(match: re.Match) -> str:
        tool = TOOLS[match.group(1)]
        block_content = match.group(6)
        caption = match.group(3) if match.group(3) else ""
        formatting = f"{{ {match.group(5)} }}" if match.group(5) else ""
        with tempfile.NamedTemporaryFile(delete=False, suffix=tool.suffix) as tmp_file:
            tmp_files.append(tmp_file)  # type: ignore
            rendered = tool.render(block_content)
            tmp_file.write(rendered if isinstance(rendered, bytes) else rendered.encode())
            return f"""
![{caption}]({tmp_file.name}){formatting}"""

    return re.sub(
        rf"```\s*({fence})(\s+\[(.*?)(\|(.*?))?\])?\n(.*?)```",
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
        preamble_includes = _as_include_list(augmented_metadata.get("header-includes"))
        if yaml_metadata is not None:
            augmented_metadata = {**augmented_metadata, **yaml_metadata}
            # A header-includes entry in the document front matter would replace
            # the preamble entries in a plain ** merge. That silently drops the
            # code font and every other include. Keep both lists. Documents often
            # copy a preamble block verbatim, so drop exact duplicates. Two copies
            # would run \newcommand or \newtcolorbox twice and LaTeX stops with an
            # "already defined" error.
            if "header-includes" in yaml_metadata:
                combined = preamble_includes + _as_include_list(yaml_metadata["header-includes"])
                augmented_metadata["header-includes"] = list(dict.fromkeys(combined))

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

        # The fonts belong to the driver, not to one preamble file. A config that
        # overrides fontfamily or header-includes must not lose Source Code Pro,
        # or code snippets fall back to Latin Modern Typewriter.
        augmented_metadata = {**DEFAULT_FONT_METADATA, **augmented_metadata}
        code_font_includes = _as_include_list(augmented_metadata.get("header-includes"))
        if not any("sourcecodepro" in include for include in code_font_includes):
            code_font_includes.append(CODE_FONT_INCLUDE)
        augmented_metadata["header-includes"] = code_font_includes

        creator_block = (
            f"```{{=latex}}\n\\AtBeginDocument{{\\hypersetup{{pdfcreator={{{_CREATOR}}}}}}}\n```\n"
        )
        augmented_metadata.setdefault("header-includes", []).append(creator_block)

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
