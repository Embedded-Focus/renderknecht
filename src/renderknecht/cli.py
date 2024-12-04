import argparse
import logging
import subprocess
import sys

from renderers import pandoc


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Render Markdown using Pandoc.")
    parser.add_argument(
        "markdown",
        nargs="?",
        type=str,
        help="Markdown content to render. If not provided, input will be read from stdin.",
    )
    args = parser.parse_args()

    markdown_content = args.markdown if args.markdown else sys.stdin.read()

    try:
        result = pandoc.render_markdown(markdown_content, [])
        sys.stdout.buffer.write(result)
    except subprocess.CalledProcessError as e:
        logging.error(f"Subprocess error: {e}")
        sys.stderr.buffer.write(e.stderr)
        sys.exit(e.returncode)


if __name__ == "__main__":
    main()
