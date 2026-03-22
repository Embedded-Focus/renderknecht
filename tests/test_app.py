import importlib.resources

import pytest

from renderknecht.util.pandoc_wrapper import determine_pandoc_arguments

_CSL_PATH = str(importlib.resources.files("renderknecht") / "resources" / "ieee.csl")


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
        "--citeproc",
        "--csl",
        _CSL_PATH,
        "--filter",
        "pandoc-latex-environment",
        "--number-sections",
        "--toc",
    ]
