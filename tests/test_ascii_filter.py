import importlib.resources
import shutil
import subprocess

import pytest

from renderknecht.util.pandoc_wrapper import determine_pandoc_arguments

_FILTER = str(importlib.resources.files("renderknecht") / "resources" / "ascii-code.lua")
_PANDOC = shutil.which("pandoc")
pandoc = pytest.mark.skipif(_PANDOC is None, reason="pandoc not installed")


def test_determine_pandoc_arguments_includes_ascii_code_filter() -> None:
    args = determine_pandoc_arguments(None)
    assert "--lua-filter" in args
    assert _FILTER in args


def test_ascii_code_filter_shipped_as_resource() -> None:
    path = importlib.resources.files("renderknecht") / "resources" / "ascii-code.lua"
    assert path.is_file()


def _run_pandoc(markdown: str, to: str, *extra: str) -> subprocess.CompletedProcess[bytes]:
    assert _PANDOC is not None
    return subprocess.run(
        [_PANDOC, "--lua-filter", _FILTER, "-f", "markdown", "-t", to, *extra],
        input=markdown.encode(),
        capture_output=True,
        check=True,
    )


@pandoc
def test_render_code_block_with_en_dash_is_ascii_and_warns() -> None:
    markdown = "# t\n\nen dash \u2013 in text\n\n```yaml\na: # 1\u201390 days\n```\n"
    result = _run_pandoc(markdown, "plain")
    stdout = result.stdout.decode()
    # The code block holds plain ASCII only.
    assert "a: # 1-90 days" in stdout
    # Normal text keeps the original character.
    assert "en dash \u2013 in text" in stdout
    # A warning tells the user about the change.
    stderr = result.stderr.decode()
    assert "WARN" in stderr
    assert "U+2013" in stderr


@pandoc
def test_render_inline_code_with_ellipsis_is_ascii() -> None:
    result = _run_pandoc("text \u2026 outside\n\n`wait \u2026 go`\n", "plain")
    stdout = result.stdout.decode()
    assert "wait ... go" in stdout
    assert "text \u2026 outside" in stdout


@pandoc
def test_render_inline_code_with_multiplication_sign_is_ascii() -> None:
    """Regression test for a crash. pdfTeX cannot read the multiplication
    sign (×) inside \\lstinline, so the run stopped and gave no PDF. The
    filter changes this sign to a plain x now, so this crash cannot happen
    again."""
    result = _run_pandoc("text × outside\n\n`A × E`\n", "plain")
    stdout = result.stdout.decode()
    assert "A x E" in stdout
    assert "text × outside" in stdout


@pandoc
def test_render_code_block_for_lstlisting_writer_stays_ascii() -> None:
    """Regression test for a crash. A code block sent bytes that pdfTeX
    cannot read, so the run stopped and gave no PDF. The filter changes every
    code block byte to plain ASCII now, so this crash cannot happen again."""
    markdown = "# t\n\n```yaml\nactions/upload-artifact@v4   # 1\u201390 \u2013 days\n```\n"
    result = _run_pandoc(markdown, "latex", "--syntax-highlighting=idiomatic")
    stdout = result.stdout.decode()
    assert "\\begin{lstlisting}" in stdout
    listing = stdout.split("\\begin{lstlisting}")[1].split("\\end{lstlisting}")[0]
    assert listing.isascii()
    assert "1-90 - days" in listing
