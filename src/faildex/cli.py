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


def _open(args: argparse.Namespace):
    from faildex.store import open_store

    try:
        return open_store(args.store)
    except FileNotFoundError as err:
        print(f"error: {err}")
        return None


def _rules(args: argparse.Namespace) -> int:
    from faildex.insight import approve, proposals, render

    db = _open(args)
    if db is None:
        return 1
    items = proposals(db, args.min_sessions)[: args.top]
    db.close()
    if args.approve:
        added = approve(items, args.approve, args.to)
        print(f"added {len(added)} rule(s) to {args.to}")
        return 0
    print(render(items))
    return 0


def _link(args: argparse.Namespace) -> int:
    from faildex.link import link, render, unlink

    steps = (unlink if args.remove else link)(args.rules, dry_run=args.dry_run)
    print(render(steps))
    if not args.remove and not args.dry_run:
        where = str(args.rules.expanduser().resolve()).replace(str(Path.home()), "~", 1)
        print(f"rules file: {where}  (new sessions read it and use the skill)")
    return 0


def _check(args: argparse.Namespace) -> int:
    from faildex.insight import warnings_for_line

    db = _open(args)
    if db is None:
        return 1
    _, pairs = warnings_for_line(db, args.command_line, args.min_sessions)
    db.close()
    for _, item in pairs[: args.top]:
        print(item.rule())
    return 0


def _hook(args: argparse.Namespace) -> int:
    import sys

    from faildex.hook import respond

    out = respond(sys.stdin.read(), args.store, args.min_sessions, args.log, args.top)
    if out:
        print(out)
    return 0


def _mcp(args: argparse.Namespace) -> int:
    from faildex.mcp_server import serve

    serve(args.store)
    return 0


# Where each agent keeps its logs by default, relative to the home folder.
DEFAULT_SOURCES = (
    ("claude", ".claude/projects"),
    ("codex_sessions", ".codex/sessions"),
    ("cursor", ".cursor/chats"),
    ("antigravity", ".gemini/antigravity-cli"),
    ("antigravity", ".gemini/antigravity"),
)


def _ingest(args: argparse.Namespace) -> int:
    """Private by construction: the store stays on this machine and keeps local pointers."""
    import relate

    from faildex.adapters import antigravity, claude_code, codex, codex_local, cursor
    from faildex.build import counts
    from faildex.schema import ingest

    if not (args.claude or args.codex or args.codex_sessions or args.cursor or args.antigravity):
        # No source given: use every agent's default folder that exists on this machine.
        home = Path.home()
        found_any = False
        for attr, rel in DEFAULT_SOURCES:
            path = home / rel
            if path.is_dir():
                getattr(args, attr).append(path)
                print(f"found {path}")
                found_any = True
        if not found_any:
            print(
                "error: no agent logs in the default folders "
                f"({', '.join('~/' + rel for _, rel in DEFAULT_SOURCES)}); "
                "give --claude, --codex-sessions, --cursor or --antigravity DIR"
            )
            return 1
    missing = [
        str(p)
        for p in [*args.claude, *args.codex, *args.codex_sessions, *args.cursor, *args.antigravity]
        if not p.exists()
    ]
    if missing:
        print(f"error: not found: {', '.join(missing)}")
        return 1
    records = [r for root in args.claude for r in claude_code.read_dir(root)]
    records += [r for root in args.codex_sessions for r in codex_local.read_dir(root)]
    records += [r for root in args.cursor for r in cursor.read_dir(root)]
    records += [r for root in args.antigravity for r in antigravity.read_dir(root)]
    records += list(codex.read_files(args.codex)) if args.codex else []
    args.store.parent.mkdir(parents=True, exist_ok=True)
    db = relate.connect(str(args.store))
    try:
        written = ingest(db, records, local_paths=True)
        db.commit()
        db.flush()
        found = counts(db)
    finally:
        db.close()
    print(f"ingested {written:,} calls into {args.store}")
    print(
        f"  sessions {found['Session']:,}  calls {found['Call']:,}  "
        f"failed {found['failed calls']:,}  failure keys {found['ErrorSig']:,}"
    )
    return 0


def _export_web(args: argparse.Namespace) -> int:
    from faildex.export import write

    db = _open(args)
    if db is None:
        return 1
    size = write(db, args.out)
    db.close()
    print(f"wrote {args.out} ({size / 1e6:.2f} MB)")
    return 0


def _report(args: argparse.Namespace) -> int:
    from faildex.report import render

    db = _open(args)
    if db is None:
        return 1
    print(render(db, args.split, args.key, args.hook_log))
    db.close()
    return 0


def _demo(args: argparse.Namespace) -> int:
    """Rules, a pre-run check and the evaluation, on the public store that ships with faildex."""
    from faildex.evaluate import report
    from faildex.hook import notice_for
    from faildex.insight import proposals, render, warnings_for
    from faildex.store import open_store, public_store

    db = open_store(public_store())
    try:
        print("== 1. Failures that came back across sessions, with the recovery on record\n")
        print(render(proposals(db)[:3]))
        print("\n== 2. Before running a command (what the Claude Code hook prints)\n")
        for command in ("git status", "ls"):
            found = warnings_for(db, command)
            print(f"$ {command}")
            print(
                f"  {notice_for(found)}"
                if found
                else "  (no notice: no recurring failure on record)"
            )
        print("\n== 3. How often later sessions repeated a failure the graph already held\n")
        print(report(db))
    finally:
        db.close()
    print("\nThis ran on public session logs. Index your own with: faildex ingest --help")
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
    evaluate.add_argument("--store", type=Path, default=None, help="store directory")
    evaluate.set_defaults(run=_eval)

    rules = commands.add_parser("rules", help="propose rules from recurring failures")
    rules.add_argument("--approve", type=int, nargs="+", metavar="N", help="write these proposals")
    rules.add_argument("--to", type=Path, default=Path("faildex-rules.md"), help="rules file")
    rules.set_defaults(run=_rules)

    linker = commands.add_parser(
        "link",
        help="install the faildex skill and your approved rules into Claude Code, Antigravity, Codex and Cursor",
    )
    linker.add_argument(
        "--rules",
        type=Path,
        default=Path("~/faildex-rules.md"),
        help="rules file to link (default ~/faildex-rules.md)",
    )
    linker.add_argument("--remove", action="store_true", help="undo the links")
    linker.add_argument("--dry-run", action="store_true", help="show what would change")
    linker.set_defaults(run=_link)

    check = commands.add_parser("check", help="what is known to go wrong with a command")
    check.add_argument("command_line", help="the command about to run, quoted")
    check.set_defaults(run=_check)

    hook = commands.add_parser("hook", help="Claude Code PreToolUse hook (JSON on stdin)")
    hook.add_argument("--log", type=Path, default=None, help="append one line per warning given")
    hook.set_defaults(run=_hook)

    report = commands.add_parser(
        "report", help="counts before and after a date, for your own store"
    )
    report.add_argument("--store", type=Path, default=None, help="store directory")
    report.add_argument("--split", metavar="YYYY-MM-DD", help="compare before and from this day")
    report.add_argument("--key", help="count failures whose key contains this text")
    report.add_argument("--hook-log", type=Path, default=None, help="the file given to hook --log")
    report.set_defaults(run=_report)

    mcp = commands.add_parser("mcp", help="serve preflight, evidence and recurring over MCP")
    mcp.add_argument("--store", type=Path, default=None, help="store directory")
    mcp.set_defaults(run=_mcp)

    for sub, top in ((rules, 10), (check, 3), (hook, 2)):
        sub.add_argument("--store", type=Path, default=None, help="store directory")
        sub.add_argument("--min-sessions", type=int, default=2, help="sessions a failure must span")
        sub.add_argument("--top", type=int, default=top, help="how many to show")

    ingest = commands.add_parser(
        "ingest", help="read your own agent logs into a private store on this machine"
    )
    ingest.add_argument(
        "--claude",
        type=Path,
        action="append",
        default=[],
        metavar="DIR",
        help="a directory of Claude Code transcripts (*.jsonl), searched recursively",
    )
    ingest.add_argument(
        "--codex",
        type=Path,
        action="append",
        default=[],
        metavar="FILE",
        help="a Codex trajectories jsonl file",
    )
    ingest.add_argument(
        "--codex-sessions",
        type=Path,
        action="append",
        default=[],
        metavar="DIR",
        help="a directory of Codex CLI session files (~/.codex/sessions)",
    )
    ingest.add_argument(
        "--cursor",
        type=Path,
        action="append",
        default=[],
        metavar="DIR",
        help="a directory of Cursor agent chats (~/.cursor/chats)",
    )
    ingest.add_argument(
        "--antigravity",
        type=Path,
        action="append",
        default=[],
        metavar="DIR",
        help="an Antigravity data folder (~/.gemini/antigravity or ~/.gemini/antigravity-cli)",
    )
    ingest.add_argument("--store", type=Path, default=None, help="store directory")
    ingest.set_defaults(run=_ingest)

    web = commands.add_parser("export-web", help="write the store as JSON for the browser demo")
    web.add_argument("--out", type=Path, default=Path("site/data.json"), help="output file")
    web.add_argument("--store", type=Path, default=None, help="store directory")
    web.set_defaults(run=_export_web)

    demo = commands.add_parser("demo", help="see faildex work on the public logs it ships with")
    demo.set_defaults(run=_demo)

    sources = commands.add_parser("sources", help="list the pinned public datasets")
    sources.set_defaults(run=_sources)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if getattr(args, "store", "set") is None:
        from faildex.store import PRIVATE_STORE, default_store

        private = PRIVATE_STORE.expanduser()
        if args.command == "ingest":
            args.store = private
        elif args.command == "report" and (private / "manifest.json").is_file():
            args.store = private  # report is about your own logs, even inside a checkout
        else:
            args.store = default_store()
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
