import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from renderknecht.renderers import pandoc
from renderknecht.util import yaml


@pytest.fixture(scope="session", autouse=True)
def configure_yaml() -> None:
    yaml.configure()


@pytest.fixture(scope="function", autouse=True)
def provide_env() -> Iterator[None]:
    orig_env = os.environ.copy()
    os.environ["CMD_DOMAIN"] = "hostname"
    yield
    os.environ.clear()
    os.environ.update(orig_env)


def test_no_cmd_domain_env_var() -> None:
    tmp_files: pandoc.TemporaryFiles = []
    markdown, metadata = pandoc.prepare_markdown("some text", tmp_files)
    assert markdown == "some text"
    assert not metadata
    assert not tmp_files


def test_cmd_domain_env_var() -> None:
    tmp_files: pandoc.TemporaryFiles = []
    markdown, metadata = pandoc.prepare_markdown("foo https://hostname/whatever", tmp_files)
    assert markdown == "foo http://app:3000/whatever"
    assert not metadata
    assert not tmp_files


def test_embed_graphviz_empty() -> None:
    tmp_files: pandoc.TemporaryFiles = []
    markdown = pandoc.embed_diagrams("""Hello, World!""", tmp_files)
    assert markdown == "Hello, World!"
    assert not tmp_files


def test_embed_graphviz() -> None:
    tmp_files: pandoc.TemporaryFiles = []
    result = pandoc.embed_diagrams(
        """Hello,
```graphviz
digraph "the holy hand grenade" { rankdir=LR; 1 -> 2 -> 3 -> lob }
```

```graphviz
digraph G {
    main -> parse -> execute;
    main -> init;
    main -> cleanup;
    execute -> make_string;
    execute -> printf
    init -> make_string;
    main -> printf;
    execute -> compare;
}
```
o.m.g.
""",
        tmp_files,
    )
    assert (
        result
        == f"""Hello,

![]({tmp_files[0].name})


![]({tmp_files[1].name})
o.m.g.
"""
    )


def test_embed_graphviz_caption() -> None:
    tmp_files: pandoc.TemporaryFiles = []
    result = pandoc.embed_diagrams(
        """Hello,
```graphviz [asdf]
digraph "the holy hand grenade" { rankdir=LR; 1 -> 2 -> 3 -> lob }
```
""",
        tmp_files,
    )

    assert (
        result
        == f"""Hello,

![asdf]({tmp_files[0].name})
"""
    )


@patch("renderknecht.renderers.pandoc.httpx.get")
def test_embed_plantuml(get: MagicMock) -> None:
    tmp_files: pandoc.TemporaryFiles = []
    response = get.return_value
    response.text = "I am a little teapot"

    result = pandoc.embed_diagrams(
        """Hello,
```plantuml [qwer]
```
""",
        tmp_files,
    )

    assert (
        result
        == f"""Hello,

![qwer]({tmp_files[0].name})
"""
    )


@patch("renderknecht.renderers.pandoc.httpx.get")
def test_embed_plantuml_with_formatting(get: MagicMock) -> None:
    tmp_files: pandoc.TemporaryFiles = []
    response = get.return_value
    response.text = "I am a little teapot"

    result = pandoc.embed_diagrams(
        """Hello,
```plantuml [qwer|height=90%]
```
""",
        tmp_files,
    )

    assert (
        result
        == f"""Hello,

![qwer]({tmp_files[0].name}){{ height=90% }}
"""
    )


def test_extract_yaml_metadata() -> None:
    os.environ["PREAMBLE_YAML"] = "/dev/null"
    tmp_files: pandoc.TemporaryFiles = []
    markdown, metadata = pandoc.prepare_markdown(
        """---
---
# Hello, World!
""",
        tmp_files,
    )

    assert (
        markdown
        == """---
{}
---
# Hello, World!
"""
    )
    assert not metadata
    assert not tmp_files


def test_extract_yaml_metadata_multiline_string() -> None:
    os.environ["PREAMBLE_YAML"] = "/dev/null"
    tmp_files: pandoc.TemporaryFiles = []
    markdown, metadata = pandoc.prepare_markdown(
        """---
header-includes:
- |
  ```{=latex}
  \\usepackage{pdflscape}
  \\newcommand{\\blandscape}{\\begin{landscape}}
  \\newcommand{\\elandscape}{\\end{landscape}}
---
# Hello, World!
""",
        tmp_files,
    )

    assert (
        markdown
        == """---
header-includes:
- |
  ```{=latex}
  \\usepackage{pdflscape}
  \\newcommand{\\blandscape}{\\begin{landscape}}
  \\newcommand{\\elandscape}{\\end{landscape}}
---
# Hello, World!
"""
    )
    assert metadata == {
        "header-includes": [
            "```{=latex}\n\\usepackage{pdflscape}\n\\newcommand{\\blandscape}{\\begin{landscape}}\n\\newcommand{\\elandscape}{\\end{landscape}}\n"
        ]
    }
    assert not tmp_files


def test_extract_yaml_metadata_with_preamble() -> None:
    tmp_files: pandoc.TemporaryFiles = []
    markdown, metadata = pandoc.prepare_markdown(
        """---
author:
  - First Name
  - Second Name
  - Third Name
---

# Hello, World!
""",
        tmp_files,
    )

    assert "titlepage-logo: " in markdown
    assert metadata is not None
    assert metadata["titlepage-logo"].endswith("logo.pdf")

    assert {k: v for k, v in metadata.items() if k != "titlepage-logo"} == {
        "author": [
            "First Name",
            "Second Name",
            "Third Name",
        ],
        "header-includes": [
            "```{=latex}\n\\usepackage{pdflscape}\n\\newcommand{\\blandscape}{\\begin{landscape}}\n\\newcommand{\\elandscape}{\\end{landscape}}\n```\n",
            "```{=latex}\n\\usepackage{tcolorbox}\n\\newtcolorbox{info-box}{colback=cyan!5!white,arc=0pt,outer arc=0pt,colframe=cyan!60!black}\n\\newtcolorbox{warning-box}{colback=orange!5!white,arc=0pt,outer arc=0pt,colframe=orange!80!black}\n\\newtcolorbox{error-box}{colback=red!5!white,arc=0pt,outer arc=0pt,colframe=red!75!black}\n```\n",
        ],
        "pandoc-latex-environment": {
            "tcolorbox": ["box"],
            "info-box": ["info"],
            "warning-box": ["warning"],
            "error-box": ["error"],
        },
        "titlepage": True,
        "titlepage-color": "ffffff",
        "titlepage-rule-color": "f25c05",
        "titlepage-text-color": "010326",
    }
    assert not tmp_files


def test_extract_yaml_metadata_with_preamble_has_less_priority() -> None:
    tmp_files: pandoc.TemporaryFiles = []
    markdown, metadata = pandoc.prepare_markdown(
        """---
titlepage: false
author:
  - First Name
  - Second Name
  - Third Name
---

# Hello, World!
""",
        tmp_files,
    )

    assert "titlepage-logo: " in markdown
    assert metadata is not None
    assert metadata["titlepage-logo"].endswith("logo.pdf")

    assert {k: v for k, v in metadata.items() if k != "titlepage-logo"} == {
        "author": [
            "First Name",
            "Second Name",
            "Third Name",
        ],
        "header-includes": [
            "```{=latex}\n\\usepackage{pdflscape}\n\\newcommand{\\blandscape}{\\begin{landscape}}\n\\newcommand{\\elandscape}{\\end{landscape}}\n```\n",
            "```{=latex}\n\\usepackage{tcolorbox}\n\\newtcolorbox{info-box}{colback=cyan!5!white,arc=0pt,outer arc=0pt,colframe=cyan!60!black}\n\\newtcolorbox{warning-box}{colback=orange!5!white,arc=0pt,outer arc=0pt,colframe=orange!80!black}\n\\newtcolorbox{error-box}{colback=red!5!white,arc=0pt,outer arc=0pt,colframe=red!75!black}\n```\n",
        ],
        "pandoc-latex-environment": {
            "tcolorbox": ["box"],
            "info-box": ["info"],
            "warning-box": ["warning"],
            "error-box": ["error"],
        },
        "titlepage": False,
        "titlepage-color": "ffffff",
        "titlepage-rule-color": "f25c05",
        "titlepage-text-color": "010326",
    }
    assert not tmp_files


def test_titlepage_logo_resolved_from_resources_dir(tmp_path: Path) -> None:
    """Logo referenced in document front matter is resolved via RESOURCES_DIR."""
    logo_file = tmp_path / "mycompany-logo.pdf"
    logo_file.write_bytes(b"%PDF")
    os.environ["RESOURCES_DIR"] = str(tmp_path)
    os.environ["PREAMBLE_YAML"] = "/dev/null"

    tmp_files: pandoc.TemporaryFiles = []
    _, metadata = pandoc.prepare_markdown(
        """---
titlepage-logo: mycompany-logo.pdf
---
# Hello
""",
        tmp_files,
    )

    assert metadata is not None
    assert metadata["titlepage-logo"] == str(logo_file)


def test_extract_yaml_metadata_toc() -> None:
    os.environ["PREAMBLE_YAML"] = "/dev/null"
    tmp_files: pandoc.TemporaryFiles = []
    _, metadata = pandoc.prepare_markdown(
        """---
pandoc-options:
    - something
    - else
    - toc
toc-own-page: true
---
# Hello, World!
""",
        tmp_files,
    )
    assert metadata == {
        "pandoc-options": ["something", "else", "toc"],
        "toc-own-page": True,
    }
    assert not tmp_files
