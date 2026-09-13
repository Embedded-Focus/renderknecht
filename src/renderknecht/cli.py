import argparse
import sys

from . import image_manager


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="renderknecht",
        usage="renderknecht [--version] [<renderer arguments>] | renderknecht image <command>",
        description="Render Markdown to PDF in a locally managed container image.",
        epilog="Without an image command, Markdown is read from stdin and the PDF is written to stdout.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {image_manager.package_version()}")
    subparsers = parser.add_subparsers(dest="command")
    image_parser = subparsers.add_parser("image", help="Manage the local renderer image")
    image_subparsers = image_parser.add_subparsers(dest="image_command", required=True)

    image_subparsers.add_parser("status", help="Show the active and tested image")
    build_parser = image_subparsers.add_parser("build", help="Build the bundled, tested image")
    build_parser.add_argument("--manifest", type=str, help="Rebuild a previously resolved JSON manifest")
    image_subparsers.add_parser("update", help="Resolve and build compatible upstream updates")
    rebuild_parser = image_subparsers.add_parser(
        "rebuild", help="Rebuild the bundled image even if it exists"
    )
    rebuild_parser.add_argument("--manifest", type=str, help="Rebuild a previously resolved JSON manifest")
    image_subparsers.add_parser("remove", help="Remove Renderknecht-managed local images")
    return parser


def main() -> None:
    """Run image management commands or render stdin with the active image."""
    parser = _parser()
    try:
        arguments = sys.argv[1:]
        if not arguments or arguments[0] != "image":
            if {"-h", "--help", "--version"} & set(arguments):
                parser.parse_args(arguments)
                return
            image_manager.render(arguments)
            return

        args = parser.parse_args(arguments)
        if args.image_command == "status":
            image_manager.print_status()
        elif args.image_command == "build":
            manifest = image_manager.load_resolved_manifest(args.manifest) if args.manifest else None
            image_manager.build(manifest=manifest)
        elif args.image_command == "update":
            image_manager.update()
        elif args.image_command == "rebuild":
            manifest = image_manager.load_resolved_manifest(args.manifest) if args.manifest else None
            image_manager.build(force=True, manifest=manifest)
        elif args.image_command == "remove":
            image_manager.remove()
    except image_manager.ImageError as error:
        print(f"renderknecht: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except KeyboardInterrupt:
        print("renderknecht: interrupted", file=sys.stderr)
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
