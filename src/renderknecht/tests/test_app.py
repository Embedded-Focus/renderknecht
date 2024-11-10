from util.pandoc_wrapper import determine_pandoc_arguments


def test_determine_pandoc_arguments_none() -> None:
    assert determine_pandoc_arguments(None) == [
        "pandoc",
        "--verbose",
        "-s",
        "-f",
        "markdown+implicit_figures+table_captions+grid_tables+citations",
        "-t",
        "pdf",
        "--template",
        "eisvogel",
        "--listings",
        "--citeproc",
        "--csl",
        "ieee.csl",
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
        "markdown+implicit_figures+table_captions+grid_tables+citations",
        "-t",
        "pdf",
        "--template",
        "eisvogel",
        "--listings",
        "--citeproc",
        "--csl",
        "ieee.csl",
        "--number-sections",
        "--toc",
    ]
