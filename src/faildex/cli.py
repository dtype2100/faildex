"""Command-line entry point."""

import argparse

from faildex import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="faildex", description=__doc__)
    parser.add_argument("--version", action="version", version=f"faildex {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
