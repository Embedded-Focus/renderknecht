from .yaml import YAMLMetadata


def determine_pandoc_arguments(metadata: YAMLMetadata) -> list[str]:
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
        # "-V",
        # "lang=de",
        "--listings",
        "--figure-caption-position=below",
        "--table-caption-position=below",
        "--citeproc",
        "--csl",
        "ieee.csl",
        "--filter",
        "pandoc-latex-environment",
    ]

    if not metadata:
        return pandoc_args

    if (pandoc_options := metadata.get("pandoc-options", None)) and "toc" in pandoc_options:
        pandoc_args += [
            "--number-sections",
            "--toc",
        ]
    return pandoc_args
