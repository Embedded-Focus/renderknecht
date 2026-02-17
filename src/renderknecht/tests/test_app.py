from util.pandoc_wrapper import determine_pandoc_arguments


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
        "--listings",
        "--figure-caption-position=below",
        "--table-caption-position=below",
        "--citeproc",
        "--csl",
        "ieee.csl",
        "--filter",
        "pandoc-latex-environment",
    ]


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
        "--listings",
        "--figure-caption-position=below",
        "--table-caption-position=below",
        "--citeproc",
        "--csl",
        "ieee.csl",
        "--filter",
        "pandoc-latex-environment",
        "--number-sections",
        "--toc",
    ]
