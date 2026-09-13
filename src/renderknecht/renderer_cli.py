import argparse
import logging
import subprocess
import sys

from .renderers import pandoc


def main() -> None:
    """Render Markdown with the in-container renderer."""
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Render Markdown using Pandoc.")
    parser.add_argument(
        "markdown",
        nargs="?",
        type=str,
        help="Markdown content to render. If omitted, read from stdin.",
    )
    args = parser.parse_args()

    markdown_content = args.markdown if args.markdown else sys.stdin.read()

    try:
        result = pandoc.render_markdown(markdown_content, [])
        sys.stdout.buffer.write(result)
    except subprocess.CalledProcessError as error:
        logging.error("Subprocess error: %s", error)
        if error.stderr:
            sys.stderr.buffer.write(error.stderr)
        raise SystemExit(error.returncode) from error


if __name__ == "__main__":
    main()
