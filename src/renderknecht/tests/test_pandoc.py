import os
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from renderers import pandoc
from util import yaml


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


@patch("renderers.pandoc.httpx.get")
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


@patch("renderers.pandoc.httpx.get")
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
    os.environ["PREAMBLE_YAML"] = "../preamble.yaml"

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

    assert (
        markdown
        == """---
author:
- First Name
- Second Name
- Third Name
header-includes:
- |
  ```{=latex}
  \\usepackage{pdflscape}
  ```
titlepage: true
titlepage-color: ffffff
titlepage-logo: honeytreelabs_WIP.pdf
titlepage-rule-color: e8ab23
titlepage-text-color: 395c6b
---

# Hello, World!
"""
    )

    assert metadata == {
        "author": [
            "First Name",
            "Second Name",
            "Third Name",
        ],
        "header-includes": [
            "```{=latex}\n" "\\usepackage{pdflscape}\n" "```\n",
        ],
        "titlepage": True,
        "titlepage-color": "ffffff",
        "titlepage-logo": "honeytreelabs_WIP.pdf",
        "titlepage-rule-color": "e8ab23",
        "titlepage-text-color": "395c6b",
    }
    assert not tmp_files


def test_extract_yaml_metadata_with_preamble_has_less_priority() -> None:
    os.environ["PREAMBLE_YAML"] = "../preamble.yaml"

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

    assert (
        markdown
        == """---
author:
- First Name
- Second Name
- Third Name
header-includes:
- |
  ```{=latex}
  \\usepackage{pdflscape}
  ```
titlepage: false
titlepage-color: ffffff
titlepage-logo: honeytreelabs_WIP.pdf
titlepage-rule-color: e8ab23
titlepage-text-color: 395c6b
---

# Hello, World!
"""
    )

    assert metadata == {
        "author": [
            "First Name",
            "Second Name",
            "Third Name",
        ],
        "header-includes": [
            "```{=latex}\n" "\\usepackage{pdflscape}\n" "```\n",
        ],
        "titlepage": False,
        "titlepage-color": "ffffff",
        "titlepage-logo": "honeytreelabs_WIP.pdf",
        "titlepage-rule-color": "e8ab23",
        "titlepage-text-color": "395c6b",
    }
    assert not tmp_files


def test_extract_yaml_metadata_toc() -> None:
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
