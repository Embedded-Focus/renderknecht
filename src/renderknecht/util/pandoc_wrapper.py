import importlib.resources
import os

from .yaml import YAMLMetadata

_RESOURCES = importlib.resources.files("renderknecht") / "resources"


def determine_pandoc_arguments(metadata: YAMLMetadata) -> list[str]:
    pandoc_options: list = (metadata or {}).get("pandoc-options", [])

    pandoc_args = [
        "pandoc",
        "--verbose",
        "-s",
        "-f",
        "markdown+citations+grid_tables+implicit_figures+table_captions+tex_math_dollars",
        "-t",
        "pdf",
        "-s",
        "--template",
        "eisvogel",
        "--syntax-highlighting=idiomatic",
        "--figure-caption-position=below",
        "--table-caption-position=below",
    ]

    if "crossref" in pandoc_options:
        # pandoc-crossref emits lstlisting; -M listings=true makes eisvogel load \usepackage{listings}
        pandoc_args += ["--filter", "pandoc-crossref", "-M", "listings=true"]

    pandoc_args += [
        "--citeproc",
        "--csl",
        str(_RESOURCES / "ieee.csl"),
        "--filter",
        "pandoc-latex-environment",
    ]

    if work_dir := os.environ.get("WORK_DIR"):
        pandoc_args += ["--resource-path", work_dir]

    if "toc" in pandoc_options:
        pandoc_args += [
            "--number-sections",
            "--toc",
        ]

    return pandoc_args
