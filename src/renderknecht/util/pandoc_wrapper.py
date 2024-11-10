from .yaml import YAMLMetadata


def determine_pandoc_arguments(metadata: YAMLMetadata) -> list[str]:
    pandoc_args = [
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

    if not metadata:
        return pandoc_args

    if (pandoc_options := metadata.get("pandoc-options", None)) and "toc" in pandoc_options:
        pandoc_args += [
            "--number-sections",
            "--toc",
        ]
    return pandoc_args
