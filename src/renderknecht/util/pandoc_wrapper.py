import importlib.resources
import os

from .yaml import YAMLMetadata

_RESOURCES = importlib.resources.files("renderknecht") / "resources"

#: The LaTeX engine that pandoc drives for PDF output. XeTeX is Unicode-aware:
#: it reads every character in the document without per-character mapping
#: tables, so characters such as ``e⁻`` render instead of stopping the build
#: with "not set up for use with LaTeX". The `PDF_ENGINE` environment variable
#: overrides the engine, for a document that must go through pdfLaTeX.
DEFAULT_PDF_ENGINE = "xelatex"


def pdf_engine() -> str:
    """Return the LaTeX engine that pandoc drives for PDF output.

    :returns: The engine name, `PDF_ENGINE` from the environment when set, or
        :data:`DEFAULT_PDF_ENGINE`.
    """
    return os.environ.get("PDF_ENGINE", DEFAULT_PDF_ENGINE)


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
        "--pdf-engine",
        pdf_engine(),
    ]

    if "crossref" in pandoc_options:
        # pandoc-crossref emits lstlisting; -M listings=true makes eisvogel load \usepackage{listings}
        pandoc_args += ["--filter", "pandoc-crossref", "-M", "listings=true"]

    pandoc_args += [
        "--lua-filter",
        str(_RESOURCES / "ascii-code.lua"),
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
