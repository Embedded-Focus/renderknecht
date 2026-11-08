import importlib.resources

import pytest

from renderknecht.util.pandoc_wrapper import determine_pandoc_arguments, pdf_engine

_CSL_PATH = str(importlib.resources.files("renderknecht") / "resources" / "ieee.csl")
_ASCII_FILTER = str(importlib.resources.files("renderknecht") / "resources" / "ascii-code.lua")


def test_pdf_engine_defaults_to_xetex(monkeypatch: pytest.MonkeyPatch) -> None:
    """XeTeX is the default engine, because it reads every Unicode character."""
    monkeypatch.delenv("PDF_ENGINE", raising=False)
    assert pdf_engine() == "xelatex"


def test_pdf_engine_env_var_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """A document that must go through pdfLaTeX can opt back in."""
    monkeypatch.setenv("PDF_ENGINE", "pdflatex")
    assert pdf_engine() == "pdflatex"
    assert "--pdf-engine" in determine_pandoc_arguments(None)
    assert "pdflatex" in determine_pandoc_arguments(None)


def test_determine_pandoc_arguments_none() -> None:
    assert determine_pandoc_arguments(None) == [
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
        "xelatex",
        "--lua-filter",
        _ASCII_FILTER,
        "--citeproc",
        "--csl",
        _CSL_PATH,
        "--filter",
        "pandoc-latex-environment",
    ]


def test_determine_pandoc_arguments_work_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORK_DIR", "/work")
    args = determine_pandoc_arguments(None)
    assert "--resource-path" in args
    assert "/work" in args


def test_determine_pandoc_arguments_toc() -> None:
    assert determine_pandoc_arguments(
        {
            "pandoc-options": ["toc"],
            "toc-own-page": True,
        }
    ) == [
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
        "xelatex",
        "--lua-filter",
        _ASCII_FILTER,
        "--citeproc",
        "--csl",
        _CSL_PATH,
        "--filter",
        "pandoc-latex-environment",
        "--number-sections",
        "--toc",
    ]


def test_determine_pandoc_arguments_crossref() -> None:
    args = determine_pandoc_arguments({"pandoc-options": ["crossref"]})
    crossref_idx = args.index("pandoc-crossref")
    citeproc_idx = args.index("--citeproc")
    assert crossref_idx < citeproc_idx, "pandoc-crossref filter must precede --citeproc"
    # eisvogel only loads \usepackage{listings} when this variable is set
    listings_idx = args.index("listings=true")
    assert args[listings_idx - 1] == "-M"
