"""faildex: find the failures coding agents keep repeating."""

import argparse
from pathlib import Path

from faildex import __version__


def _build_store(args: argparse.Namespace) -> int:
    from faildex.build import build_store, report

    try:
        result = build_store(args.data, args.out)
    except FileNotFoundError as err:
        print(f"error: {err}")
        return 1
    print(report(result, args.out))
    return 0


def _eval(args: argparse.Namespace) -> int:
    from faildex.evaluate import report
    from faildex.store import open_store

    try:
        db = open_store(args.store)
    except FileNotFoundError as err:
        print(f"error: {err}")
        return 1
    print(report(db))
    db.close()
    return 0


def _sources(args: argparse.Namespace) -> int:
    from faildex.build import SOURCES

    for source in SOURCES:
        print(source.name, source.repo, source.revision)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="faildex", description=__doc__)
    parser.add_argument("--version", action="version", version=f"faildex {__version__}")
    commands = parser.add_subparsers(dest="command")

    build = commands.add_parser("build-store", help="rebuild the store from the public datasets")
    build.add_argument("--data", type=Path, default=Path(".tmp/data"), help="downloaded datasets")
    build.add_argument("--out", type=Path, default=Path("store"), help="store directory")
    build.set_defaults(run=_build_store)

    evaluate = commands.add_parser("eval", help="recurrence of failures in the store")
    evaluate.add_argument("--store", type=Path, default=Path("store"), help="store directory")
    evaluate.set_defaults(run=_eval)

    sources = commands.add_parser("sources", help="list the pinned public datasets")
    sources.set_defaults(run=_sources)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
