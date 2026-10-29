import dataclasses
import datetime
import os
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from renderknecht.renderers import pandoc
from renderknecht.util import yaml

_CREATOR_BLOCK = (
    f"```{{=latex}}\n\\AtBeginDocument{{\\hypersetup{{pdfcreator={{{pandoc._CREATOR}}}}}}}\n```\n"
)


@pytest.fixture(scope="session", autouse=True)
def configure_yaml() -> None:
    yaml.configure()


@pytest.fixture(scope="function", autouse=True)
def provide_env() -> Iterator[None]:
    orig_env = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(orig_env)


def test_augment_yaml_preamble_injects_pdfcreator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Creator \\hypersetup block is always appended to header-includes."""
    monkeypatch.setattr(
        pandoc, "_CREATOR", "renderknecht testhash (https://github.com/Embedded-Focus/renderknecht/)"
    )
    os.environ["PREAMBLE_YAML"] = "/dev/null"
    tmp_files: pandoc.TemporaryFiles = []
    _, metadata = pandoc.prepare_markdown("---\ntitle: test\n---\n", tmp_files)
    assert metadata is not None
    header_includes = metadata.get("header-includes", [])
    assert any("pdfcreator" in entry for entry in header_includes)
    assert any("renderknecht testhash" in entry for entry in header_includes)


def test_augment_yaml_preamble_adds_code_font_without_preamble() -> None:
    """A stripped preamble must not lose Source Code Pro or the font family."""
    os.environ["PREAMBLE_YAML"] = "/dev/null"
    tmp_files: pandoc.TemporaryFiles = []
    _, metadata = pandoc.prepare_markdown("---\ntitle: test\n---\n", tmp_files)
    assert metadata is not None
    assert metadata.get("fontfamily") == "sourcesanspro"
    assert metadata.get("fontfamilyoptions") == ["default"]
    assert any("sourcecodepro" in entry for entry in metadata.get("header-includes", []))


def test_augment_yaml_preamble_keeps_code_font_with_preamble() -> None:
    """With the bundled preamble the code font is added exactly once."""
    tmp_files: pandoc.TemporaryFiles = []
    _, metadata = pandoc.prepare_markdown("---\ntitle: test\n---\n", tmp_files)
    assert metadata is not None
    code_includes = [entry for entry in metadata.get("header-includes", []) if "sourcecodepro" in entry]
    assert len(code_includes) == 1


def test_augment_yaml_preamble_keeps_code_font_when_document_sets_header_includes() -> None:
    """Document header-includes must not replace the preamble's code font entry.

    Without the additive merge, front matter sets header-includes, the preamble
    entry is dropped, and code falls back to the default typewriter font.
    """
    tmp_files: pandoc.TemporaryFiles = []
    _, metadata = pandoc.prepare_markdown(
        '---\nheader-includes: ["```{=latex}\\n\\\\usepackage{myfont}\\n```"]\n---\n\ntext\n',
        tmp_files,
    )
    assert metadata is not None
    includes = metadata.get("header-includes", [])
    assert any("sourcecodepro" in entry for entry in includes)
    assert any("myfont" in entry for entry in includes)
    assert any("pdfcreator" in entry for entry in includes)


def test_augment_yaml_preamble_drops_duplicated_includes() -> None:
    """A front-matter include that copies the preamble must not be added twice.

    Two copies run the same \newcommand twice. LaTeX then stops with an
    "already defined" error and produces no PDF.
    """
    pdflscape = (
        "```{=latex}\n\\usepackage{pdflscape}\n"
        "\\newcommand{\\blandscape}{\\begin{landscape}}\n"
        "\\newcommand{\\elandscape}{\\end{landscape}}\n```\n"
    )
    tmp_files: pandoc.TemporaryFiles = []
    _, metadata = pandoc.prepare_markdown(
        "---\nheader-includes:\n- |\n  ```{=latex}\n  \\usepackage{pdflscape}\n"
        "  \\newcommand{\\blandscape}{\\begin{landscape}}\n"
        "  \\newcommand{\\elandscape}{\\end{landscape}}\n  ```\n---\n\ntext\n",
        tmp_files,
    )
    assert metadata is not None
    includes = metadata.get("header-includes", [])
    assert includes.count(pdflscape) == 1
    assert any("sourcecodepro" in entry for entry in includes)


def test_augment_yaml_preamble_keeps_document_landscape_block() -> None:
    """A document that carries the landscape block is answered, not doubled.

    Documents written before the driver owned the block define it in their
    own front matter. A second copy runs `\newenvironment` twice. The driver
    leaves the document's copy alone and only adds the class binding.
    """
    own_block = "```{=latex}\n\\newenvironment{landscapepage}{\\clearpage\\blandscape}{\\elandscape\\clearpage}\n```\n"
    document = (
        "---\nheader-includes:\n- |\n  ```{=latex}\n"
        "  \\newenvironment{landscapepage}{\\clearpage\\blandscape}{\\elandscape\\clearpage}\n"
        "  ```\n---\n\ntext\n"
    )
    os.environ["PREAMBLE_YAML"] = "/dev/null"
    tmp_files: pandoc.TemporaryFiles = []
    _, metadata = pandoc.prepare_markdown(document, tmp_files)
    assert metadata is not None
    includes = metadata.get("header-includes", [])
    assert pandoc.LANDSCAPE_INCLUDE not in includes
    assert sum(own_block in entry for entry in includes) == 1
    assert metadata["pandoc-latex-environment"]["landscapepage"] == ["landscapepage"]


def test_augment_yaml_preamble_defines_landscape_for_a_renewing_document() -> None:
    """A document that only renews the environment needs the driver's copy.

    `\renewenvironment` works only if the environment already exists. If no
    preamble file defines it, the driver must. This is true even when the
    document's own front matter already mentions `landscapepage`.
    """
    os.environ["PREAMBLE_YAML"] = "/dev/null"
    tmp_files: pandoc.TemporaryFiles = []
    _, metadata = pandoc.prepare_markdown(
        "---\nheader-includes:\n- |\n  ```{=latex}\n"
        "  \\renewenvironment{landscapepage}{\\clearpage\\blandscape}{\\elandscape\\clearpage}\n"
        "  ```\n---\n\ntext\n",
        tmp_files,
    )
    assert metadata is not None
    assert pandoc.LANDSCAPE_INCLUDE in metadata.get("header-includes", [])


def test_augment_yaml_preamble_keeps_box_classes_when_document_adds_a_class() -> None:
    """A front-matter environment map must not replace the preamble's map.

    With a plain ** merge, one added class drops every class the preamble
    carries. `::: info` then runs through the filter unmatched and prints as a
    plain div, without the colored box.
    """
    tmp_files: pandoc.TemporaryFiles = []
    _, metadata = pandoc.prepare_markdown(
        "---\npandoc-latex-environment:\n  hint: [hint]\n---\n\ntext\n",
        tmp_files,
    )
    assert metadata is not None
    environments = metadata.get("pandoc-latex-environment", {})
    assert environments["hint"] == ["hint"]
    assert environments["info-box"] == ["info"]
    assert environments["warning-box"] == ["warning"]
    assert environments["error-box"] == ["error"]
    assert environments["landscapepage"] == ["landscapepage"]


def test_augment_yaml_preamble_drops_duplicated_environment_classes() -> None:
    """A class named in both maps is handed to the filter once.

    A duplicate sends the content through the filter twice. This puts a box
    inside a box, or a landscape page inside a landscape page.
    """
    tmp_files: pandoc.TemporaryFiles = []
    _, metadata = pandoc.prepare_markdown(
        "---\npandoc-latex-environment:\n  info-box: [info]\n  landscapepage: [landscapepage]\n---\n\ntext\n",
        tmp_files,
    )
    assert metadata is not None
    environments = metadata.get("pandoc-latex-environment", {})
    assert environments["info-box"] == ["info"]
    assert environments["landscapepage"] == ["landscapepage"]


def test_landscapepage_needs_no_front_matter() -> None:
    """A plain document gets the landscape environment and its class binding.

    The boxes and `landscapepage` belong to the preamble, so a document marks its
    wide tables with `::: landscapepage` and names nothing in front matter.
    """
    tmp_files: pandoc.TemporaryFiles = []
    _, metadata = pandoc.prepare_markdown("---\ntitle: x\n---\n\ntext\n", tmp_files)
    assert metadata is not None
    assert any("newenvironment{landscapepage}" in entry for entry in metadata["header-includes"])
    assert metadata["pandoc-latex-environment"]["landscapepage"] == ["landscapepage"]


def test_as_include_list_handles_scalar_and_sequence() -> None:
    assert pandoc._as_include_list(None) == []
    assert pandoc._as_include_list("a") == ["a"]
    assert pandoc._as_include_list(["a", "b"]) == ["a", "b"]
    assert pandoc._as_include_list(("a", "b")) == ["a", "b"]


def test_merge_environments_combines_and_deduplicates() -> None:
    assert pandoc._merge_environments(None, None) == {}
    assert pandoc._merge_environments("keine karte", {"box": ["box"]}) == {"box": ["box"]}
    assert pandoc._merge_environments({"info-box": "info"}, {"info-box": ["info"]}) == {"info-box": ["info"]}
    assert pandoc._merge_environments({"box": ["box"]}, {"eigentoendung": ["eigentoendung"]}) == {
        "box": ["box"],
        "eigentoendung": ["eigentoendung"],
    }


def test_embed_images_skips_rewrite_when_not_mounted() -> None:
    tmp_files: pandoc.TemporaryFiles = []
    markdown, metadata = pandoc.prepare_markdown("some text", tmp_files)
    assert markdown == "some text"
    assert not metadata
    assert not tmp_files


def test_embed_images_rewrites_uploads_url(tmp_path: Path) -> None:
    with patch("renderknecht.renderers.pandoc._UPLOADS_DIR", tmp_path):
        tmp_files: pandoc.TemporaryFiles = []
        markdown, metadata = pandoc.prepare_markdown(
            "foo https://hedgedoc.example.com/uploads/image.png bar",
            tmp_files,
        )
    assert markdown == f"foo {tmp_path}/image.png bar"
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


def test_embed_diagrams_figure_label_reaches_pandoc_as_one_attribute_block() -> None:
    """Keep `#fig:x` usable, with and without the braces of the author.

    pandoc-crossref gives a number to an image whose identifier starts with `fig:`.
    Pandoc reads one level of braces. `{ {#fig:x} }` is then text and not an
    attribute, so the braces stay on the page and every `@fig:x` prints `??`. This
    happens when renderknecht adds braces that the author already wrote.
    """
    tmp_files: pandoc.TemporaryFiles = []
    written_as_block = pandoc.embed_diagrams(
        """Hello,
```graphviz [A figure|{#fig:x}]
digraph "the holy hand grenade" { rankdir=LR; 1 -> 2 }
```
""",
        tmp_files,
    )
    written_as_pairs = pandoc.embed_diagrams(
        """Hello,
```graphviz [A figure|#fig:x]
digraph "the holy hand grenade" { rankdir=LR; 1 -> 2 }
```
""",
        tmp_files,
    )

    assert (
        written_as_block
        == f"""Hello,

![A figure]({tmp_files[0].name}){{#fig:x}}
"""
    )
    assert (
        written_as_pairs
        == f"""Hello,

![A figure]({tmp_files[1].name}){{ #fig:x }}
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


def _fake_mmdc(run: MagicMock) -> None:
    """Act like mmdc and write a PDF to the path after `-o`."""

    def write_pdf(command: list[str], **kwargs: object) -> MagicMock:
        Path(command[command.index("-o") + 1]).write_bytes(b"%PDF-1.7 fake diagram")
        return MagicMock(returncode=0, stdout=b"", stderr=b"")

    run.side_effect = write_pdf


@patch("renderknecht.renderers.pandoc.subprocess.run")
def test_embed_mermaid(run: MagicMock) -> None:
    tmp_files: pandoc.TemporaryFiles = []
    _fake_mmdc(run)

    result = pandoc.embed_diagrams(
        """Hello,
```mermaid
graph TD
  A[Start] --> B{Is it good?}
```
""",
        tmp_files,
    )

    assert (
        result
        == f"""Hello,

![]({tmp_files[0].name})
"""
    )
    assert tmp_files[0].name.endswith(".pdf")


@patch("renderknecht.renderers.pandoc.subprocess.run")
def test_embed_mermaid_caption_and_formatting(run: MagicMock) -> None:
    tmp_files: pandoc.TemporaryFiles = []
    _fake_mmdc(run)

    result = pandoc.embed_diagrams(
        """Hello,
```mermaid [qwer|height=90%]
graph TD
  A-->B
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


@patch("renderknecht.renderers.pandoc.subprocess.run")
def test_render_mermaid_passes_puppeteer_config(run: MagicMock) -> None:
    """renderknecht passes the no-sandbox puppeteer configuration from the image to mmdc."""
    config = Path(tempfile.gettempdir()) / "renderknecht-test-puppeteer.json"
    config.write_text("{}")
    os.environ["MERMAID_PUPPETEER_CONFIG"] = str(config)
    _fake_mmdc(run)

    assert pandoc.render_mermaid("graph TD\n  A-->B\n").startswith(b"%PDF-")

    command = run.call_args.args[0]
    assert command[command.index("-p") + 1] == str(config)


@patch("renderknecht.renderers.pandoc.subprocess.run")
def test_render_mermaid_without_puppeteer_config(run: MagicMock) -> None:
    """Outside the container, renderknecht runs mmdc with mmdc's own sandbox defaults."""
    os.environ["MERMAID_PUPPETEER_CONFIG"] = "/does/not/exist.json"
    _fake_mmdc(run)

    assert pandoc.render_mermaid("graph TD\n  A-->B\n").startswith(b"%PDF-")
    assert "-p" not in run.call_args.args[0]


@patch("renderknecht.renderers.pandoc.subprocess.run")
def test_render_mermaid_raises_on_invalid_syntax(run: MagicMock) -> None:
    run.return_value = MagicMock(returncode=1, stdout=b"", stderr=b"Parse error on line 2")

    with pytest.raises(subprocess.CalledProcessError):
        pandoc.render_mermaid("graph TD\n  A--\n")


@pytest.mark.parametrize("tool", sorted(pandoc.TOOLS))
def test_embed_diagrams_handles_every_registered_tool(tool: str) -> None:
    """The fence regex matches every registered tool, and each tool uses its own suffix."""
    suffix = pandoc.TOOLS[tool].suffix
    rendered: MagicMock = MagicMock(return_value=b"rendered")
    tmp_files: pandoc.TemporaryFiles = []

    with patch.dict(pandoc.TOOLS, {tool: dataclasses.replace(pandoc.TOOLS[tool], render=rendered)}):
        markdown = pandoc.embed_diagrams(f"Hello,\n```{tool}\nmarkup\n```\n", tmp_files)

    assert "markup" not in markdown
    assert f"![]({tmp_files[0].name})" in markdown
    assert tmp_files[0].name.endswith(suffix)
    rendered.assert_called_once_with("markup\n")


def test_embed_diagrams_leaves_unknown_language_alone() -> None:
    """A fence language that TOOLS does not name stays in the document."""
    tmp_files: pandoc.TemporaryFiles = []
    markdown = "```kangaroos\nnot a diagram\n```\n"

    assert pandoc.embed_diagrams(markdown, tmp_files) == markdown
    assert not tmp_files


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

    assert "# Hello, World!" in markdown
    assert "pdfcreator" in markdown
    # PREAMBLE_YAML is /dev/null here, so no preamble file contributes. The
    # landscape feature still has to be there, because the driver owns it.
    assert metadata == {
        "fontfamily": "sourcesanspro",
        "fontfamilyoptions": ["default"],
        "header-includes": [
            pandoc.CODE_FONT_INCLUDE,
            pandoc.LANDSCAPE_INCLUDE,
            _CREATOR_BLOCK,
        ],
        "pandoc-latex-environment": {"landscapepage": ["landscapepage"]},
    }
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

    assert "usepackage{pdflscape}" in markdown
    assert "pdfcreator" in markdown
    assert "# Hello, World!" in markdown
    assert metadata == {
        "fontfamily": "sourcesanspro",
        "fontfamilyoptions": ["default"],
        "header-includes": [
            "```{=latex}\n\\usepackage{pdflscape}\n\\newcommand{\\blandscape}{\\begin{landscape}}\n\\newcommand{\\elandscape}{\\end{landscape}}\n",
            pandoc.CODE_FONT_INCLUDE,
            pandoc.LANDSCAPE_INCLUDE,
            _CREATOR_BLOCK,
        ],
        "pandoc-latex-environment": {"landscapepage": ["landscapepage"]},
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

    assert {k: v for k, v in metadata.items() if k not in ("titlepage-logo", "date")} == {
        "author": [
            "First Name",
            "Second Name",
            "Third Name",
        ],
        "header-includes": [
            "```{=latex}\n\\usepackage{pdflscape}\n\\newcommand{\\blandscape}{\\begin{landscape}}\n\\newcommand{\\elandscape}{\\end{landscape}}\n```\n",
            "```{=latex}\n\\usepackage{tcolorbox}\n\\newtcolorbox{info-box}{colback=cyan!5!white,arc=0pt,outer arc=0pt,colframe=cyan!60!black}\n\\newtcolorbox{warning-box}{colback=orange!5!white,arc=0pt,outer arc=0pt,colframe=orange!80!black}\n\\newtcolorbox{error-box}{colback=red!5!white,arc=0pt,outer arc=0pt,colframe=red!75!black}\n```\n",
            "```{=latex}\n\\usepackage{tikz}\n\\makeatletter\n\\@ifundefined{landscapepage}{%\n\\newcommand{\\landscapepage@head}{%\n\\begin{tikzpicture}[remember picture,overlay]\n\\node[rotate=90,anchor=south west,inner sep=0pt] at ([xshift=2.5cm,yshift=2.5cm]current page.south west)\n{\\hbox to \\dimexpr\\paperheight-5cm\\relax{\\normalfont\\upshape\\small \\@title\\hfil \\@date}};\n\\node[rotate=90,anchor=south west,inner sep=0pt] at ([xshift=2.6cm,yshift=2.5cm]current page.south west)\n{\\hbox to \\dimexpr\\paperheight-5cm\\relax{\\leaders\\hrule height 0.4pt\\hfil}};\n\\end{tikzpicture}%\n}%\n\\newcommand{\\landscapepage@foot}{%\n\\begin{tikzpicture}[remember picture,overlay]\n\\node[rotate=90,anchor=north west,inner sep=0pt] at ([xshift=\\dimexpr\\paperwidth-2.6cm\\relax,yshift=2.5cm]current page.south west)\n{\\hbox to \\dimexpr\\paperheight-5cm\\relax{\\leaders\\hrule height 0.4pt\\hfil}};\n\\node[rotate=90,anchor=north west,inner sep=0pt] at ([xshift=\\dimexpr\\paperwidth-2.5cm\\relax,yshift=2.5cm]current page.south west)\n{\\hbox to \\dimexpr\\paperheight-5cm\\relax{\\normalfont\\upshape\\small \\@author\\hfil \\thepage}};\n\\end{tikzpicture}%\n}%\n\\newenvironment{landscapepage}{%\n\\clearpage\n\\pagestyle{empty}%\n\\blandscape\n\\addtolength{\\oddsidemargin}{2cm}%\n\\addtolength{\\textheight}{-4cm}%\n\\@colht=\\textheight\\relax\n\\@colroom=\\textheight\\relax\n\\vsize=\\textheight\\relax\n\\addtolength{\\textheight}{-2cm}%\n\\def\\@oddhead{\\landscapepage@head}%\n\\def\\@oddfoot{\\landscapepage@foot}%\n}{%\n\\elandscape\n\\clearpage\n\\@ifundefined{ps@eisvogel-header-footer}{}{\\pagestyle{eisvogel-header-footer}}%\n}\n}{}\n\\makeatother\n```\n",
            "```{=latex}\n\\usepackage{sourcecodepro}\n```\n",
            _CREATOR_BLOCK,
        ],
        "pandoc-latex-environment": {
            "tcolorbox": ["box"],
            "info-box": ["info"],
            "warning-box": ["warning"],
            "error-box": ["error"],
            "landscapepage": ["landscapepage"],
        },
        "colorlinks": True,
        "fontfamily": "sourcesanspro",
        "fontfamilyoptions": ["default"],
        "toccolor": "black",
        "titlepage": True,
        "titlepage-color": "ffffff",
        "titlepage-rule-color": "f25c05",
        "titlepage-text-color": "010326",
    }
    assert metadata["date"] == datetime.date.today().isoformat()
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

    assert {k: v for k, v in metadata.items() if k not in ("titlepage-logo", "date")} == {
        "author": [
            "First Name",
            "Second Name",
            "Third Name",
        ],
        "header-includes": [
            "```{=latex}\n\\usepackage{pdflscape}\n\\newcommand{\\blandscape}{\\begin{landscape}}\n\\newcommand{\\elandscape}{\\end{landscape}}\n```\n",
            "```{=latex}\n\\usepackage{tcolorbox}\n\\newtcolorbox{info-box}{colback=cyan!5!white,arc=0pt,outer arc=0pt,colframe=cyan!60!black}\n\\newtcolorbox{warning-box}{colback=orange!5!white,arc=0pt,outer arc=0pt,colframe=orange!80!black}\n\\newtcolorbox{error-box}{colback=red!5!white,arc=0pt,outer arc=0pt,colframe=red!75!black}\n```\n",
            "```{=latex}\n\\usepackage{tikz}\n\\makeatletter\n\\@ifundefined{landscapepage}{%\n\\newcommand{\\landscapepage@head}{%\n\\begin{tikzpicture}[remember picture,overlay]\n\\node[rotate=90,anchor=south west,inner sep=0pt] at ([xshift=2.5cm,yshift=2.5cm]current page.south west)\n{\\hbox to \\dimexpr\\paperheight-5cm\\relax{\\normalfont\\upshape\\small \\@title\\hfil \\@date}};\n\\node[rotate=90,anchor=south west,inner sep=0pt] at ([xshift=2.6cm,yshift=2.5cm]current page.south west)\n{\\hbox to \\dimexpr\\paperheight-5cm\\relax{\\leaders\\hrule height 0.4pt\\hfil}};\n\\end{tikzpicture}%\n}%\n\\newcommand{\\landscapepage@foot}{%\n\\begin{tikzpicture}[remember picture,overlay]\n\\node[rotate=90,anchor=north west,inner sep=0pt] at ([xshift=\\dimexpr\\paperwidth-2.6cm\\relax,yshift=2.5cm]current page.south west)\n{\\hbox to \\dimexpr\\paperheight-5cm\\relax{\\leaders\\hrule height 0.4pt\\hfil}};\n\\node[rotate=90,anchor=north west,inner sep=0pt] at ([xshift=\\dimexpr\\paperwidth-2.5cm\\relax,yshift=2.5cm]current page.south west)\n{\\hbox to \\dimexpr\\paperheight-5cm\\relax{\\normalfont\\upshape\\small \\@author\\hfil \\thepage}};\n\\end{tikzpicture}%\n}%\n\\newenvironment{landscapepage}{%\n\\clearpage\n\\pagestyle{empty}%\n\\blandscape\n\\addtolength{\\oddsidemargin}{2cm}%\n\\addtolength{\\textheight}{-4cm}%\n\\@colht=\\textheight\\relax\n\\@colroom=\\textheight\\relax\n\\vsize=\\textheight\\relax\n\\addtolength{\\textheight}{-2cm}%\n\\def\\@oddhead{\\landscapepage@head}%\n\\def\\@oddfoot{\\landscapepage@foot}%\n}{%\n\\elandscape\n\\clearpage\n\\@ifundefined{ps@eisvogel-header-footer}{}{\\pagestyle{eisvogel-header-footer}}%\n}\n}{}\n\\makeatother\n```\n",
            "```{=latex}\n\\usepackage{sourcecodepro}\n```\n",
            _CREATOR_BLOCK,
        ],
        "pandoc-latex-environment": {
            "tcolorbox": ["box"],
            "info-box": ["info"],
            "warning-box": ["warning"],
            "error-box": ["error"],
            "landscapepage": ["landscapepage"],
        },
        "colorlinks": True,
        "fontfamily": "sourcesanspro",
        "fontfamilyoptions": ["default"],
        "toccolor": "black",
        "titlepage": False,
        "titlepage-color": "ffffff",
        "titlepage-rule-color": "f25c05",
        "titlepage-text-color": "010326",
    }
    assert metadata["date"] == datetime.date.today().isoformat()
    assert not tmp_files


def test_date_today_sentinel_replaced() -> None:
    """'today' in the date field is replaced with the current ISO date."""
    os.environ["PREAMBLE_YAML"] = "/dev/null"
    tmp_files: pandoc.TemporaryFiles = []
    _, metadata = pandoc.prepare_markdown(
        """---
date: today
---
# Hello
""",
        tmp_files,
    )
    assert metadata is not None
    assert metadata["date"] == datetime.date.today().isoformat()


def test_date_today_sentinel_case_insensitive() -> None:
    """'TODAY' and 'Today' are also replaced."""
    os.environ["PREAMBLE_YAML"] = "/dev/null"
    for value in ("TODAY", "Today", "toDay"):
        tmp_files: pandoc.TemporaryFiles = []
        _, metadata = pandoc.prepare_markdown(
            f"---\ndate: {value}\n---\n",
            tmp_files,
        )
        assert metadata is not None
        assert metadata["date"] == datetime.date.today().isoformat(), f"failed for date: {value}"


def test_date_literal_not_replaced() -> None:
    """A literal date string is passed through unchanged."""
    os.environ["PREAMBLE_YAML"] = "/dev/null"
    tmp_files: pandoc.TemporaryFiles = []
    _, metadata = pandoc.prepare_markdown(
        """---
date: "2025-01-15"
---
# Hello
""",
        tmp_files,
    )
    assert metadata is not None
    assert metadata["date"] == "2025-01-15"


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
        "fontfamily": "sourcesanspro",
        "fontfamilyoptions": ["default"],
        "header-includes": [
            pandoc.CODE_FONT_INCLUDE,
            pandoc.LANDSCAPE_INCLUDE,
            _CREATOR_BLOCK,
        ],
        "pandoc-latex-environment": {"landscapepage": ["landscapepage"]},
    }
    assert not tmp_files
