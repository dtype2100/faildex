"""faildex: find the failures coding agents keep repeating."""

import argparse
import base64
from pathlib import Path

from faildex import __version__
from faildex.i18n import t


def _build_store(args: argparse.Namespace) -> int:
    from faildex.build import build_store, report

    try:
        result = build_store(args.data, args.out)
    except FileNotFoundError as err:
        print(t("err.prefix", message=err))
        return 1
    print(report(result, args.out))
    return 0


def _eval(args: argparse.Namespace) -> int:
    from faildex.evaluate import report
    from faildex.store import open_store

    try:
        db = open_store(args.store)
    except FileNotFoundError as err:
        print(t("err.prefix", message=err))
        return 1
    command = "faildex report"
    if getattr(args, "store_given", False):
        command += f" --store {_shell_path(args.store)}"
    print(report(db, command))
    db.close()
    return 0


def _open(args: argparse.Namespace):
    from faildex.store import open_store

    try:
        return open_store(args.store)
    except FileNotFoundError as err:
        print(t("err.prefix", message=err))
        return None


def _display_store_path(store: Path) -> str:
    from faildex.insight import tilde_path

    return tilde_path(store)


def _shell_path(store: Path) -> str:
    """A store path the reader can paste back into a shell, `~` kept unquoted."""
    import os
    import shlex

    if os.name == "nt":
        # cmd.exe expands neither `~` nor single quotes, so keep the path and use double quotes.
        raw = str(store)
        return f'"{raw}"' if any(ch.isspace() or ch in "&|<>^()" for ch in raw) else raw
    shown = _display_store_path(store)
    if shown.startswith("~/"):
        return "~/" + shlex.quote(shown[2:])
    return shlex.quote(shown)


def _store_overview(db, store_path: Path) -> tuple[str, bool, int, int]:
    """(human label for store, is_public, session count, failed call count)."""
    import os

    from faildex.store import PRIVATE_STORE, _shipped_store

    sessions = next(iter(db.execute("MATCH (s:Session) RETURN count(s) AS n")))["n"]
    failed = next(iter(db.execute("MATCH (c:Call) WHERE c.ok = false RETURN count(c) AS n")))["n"]
    sources = next(iter(db.execute("MATCH (d:Source) RETURN count(d) AS n")))["n"]

    resolved = store_path.expanduser().resolve()
    private_resolved = PRIVATE_STORE.expanduser().resolve()
    if resolved == private_resolved:
        return t("rules.label.yours"), False, sessions, failed

    shipped = _shipped_store()
    cache_root = (
        Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser().resolve() / "faildex"
    )
    is_cached_public = resolved.parent == cache_root and resolved.name.startswith("store-")
    is_public = bool(
        sources or is_cached_public or (shipped is not None and resolved == shipped.resolve())
    )
    if is_public:
        if is_cached_public:
            where = t("rules.label.builtin")
        elif store_path == Path("store"):
            where = "./store"
        else:
            where = _display_store_path(store_path)
        return t("rules.label.public", where=where), True, sessions, failed
    return t("rules.label.store", path=_display_store_path(store_path)), False, sessions, failed


def _rules(args: argparse.Namespace) -> int:
    import sys

    from faildex.insight import approve, proposals, render, safe_console_text, use_color
    from faildex.store import PRIVATE_STORE

    db = _open(args)
    if db is None:
        return 1
    try:
        all_items = proposals(db, args.min_sessions)
        items = all_items[: args.top]
        if args.approve:
            added = approve(items, args.approve, args.to)
            print(t("rules.added", count=len(added), path=args.to))
            return 0
        label, is_public, sessions, failed = _store_overview(db, args.store)
    finally:
        db.close()

    color = use_color(sys.stdout)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"

    def style(text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if color else text

    total = len(all_items)
    recurring = t("rules.summary.recurring", count=f"{total:,}") if total else ""
    summary = t(
        "rules.summary",
        label=label,
        sessions=f"{sessions:,}",
        failed=f"{failed:,}",
        recurring=recurring,
    )
    lines = [style(summary, "1")]
    if is_public:
        private = PRIVATE_STORE.expanduser()
        if (
            private / "manifest.json"
        ).is_file() and args.store.expanduser().resolve() != private.resolve():
            hint = t("rules.hint.yours")
        else:
            hint = t("rules.hint.ingest")
        lines.append(style(t("rules.demo_note", hint=hint), "33"))
    lines.append("")
    lines.append(
        render(
            items,
            show_evidence=args.evidence,
            color=color,
            encoding=encoding,
        )
    )
    if items:
        lines.append("")
        more = []
        if len(items) < total:
            more.append(t("rules.showing", shown=len(items), total=f"{total:,}", count=total))
        if not args.evidence and any(len(item.evidence) > 1 for item in items):
            more.append(t("rules.full_evidence"))
        if more:
            lines.append("; ".join(more))
        picks = "1 3" if len(items) >= 3 else " ".join(str(i) for i in range(1, len(items) + 1))
        extra = []
        if getattr(args, "store_given", False):
            extra.append(f"--store {_shell_path(args.store)}")
        if args.min_sessions != 2:
            extra.append(f"--min-sessions {args.min_sessions}")
        suffix = f" {' '.join(extra)}" if extra else ""
        command = f"faildex rules --approve {picks}{suffix} --to ~/faildex-rules.md"
        lines.append(style(t("rules.write", command=command), "1"))
    print(safe_console_text("\n".join(lines), sys.stdout))
    return 0


def _link(args: argparse.Namespace) -> int:
    from faildex.link import link, render, unlink

    steps = (unlink if args.remove else link)(args.rules, dry_run=args.dry_run)
    print(render(steps))
    if not args.remove and not args.dry_run:
        where = str(args.rules.expanduser().resolve()).replace(str(Path.home()), "~", 1)
        print(t("link.rules_file", path=where))
        print(t("link.claude_hook"))
    return 0


def _check(args: argparse.Namespace) -> int:
    from faildex.insight import warnings_for_line

    db = _open(args)
    if db is None:
        return 1
    _, pairs = warnings_for_line(db, args.command_line, args.min_sessions)
    db.close()
    from faildex.i18n import current

    for _, item in pairs[: args.top]:
        print(item.rule(lang=current()))
    return 0


def _hook(args: argparse.Namespace) -> int:
    import sys

    from faildex.hook import respond
    from faildex.i18n import use

    use("en")  # an agent reads this, whatever language the person chose

    out = respond(
        sys.stdin.read(),
        args.store,
        args.min_sessions,
        args.log,
        args.top,
        agent=args.agent,
        event=args.event,
        rules=args.encoded_rules or args.rules,
    )
    if out:
        print(out)
    return 0


def _mcp(args: argparse.Namespace) -> int:
    from faildex.i18n import use
    from faildex.mcp_server import serve

    use("en")  # an agent reads this, whatever language the person chose

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
                print(t("ingest.found", path=path))
                found_any = True
        if not found_any:
            folders = ", ".join("~/" + rel for _, rel in DEFAULT_SOURCES)
            print(t("err.prefix", message=t("err.no_logs", folders=folders)))
            return 1
    missing = [
        str(p)
        for p in [*args.claude, *args.codex, *args.codex_sessions, *args.cursor, *args.antigravity]
        if not p.exists()
    ]
    if missing:
        print(t("err.prefix", message=t("err.not_found", paths=", ".join(missing))))
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
    where = _display_store_path(args.store)
    print(t("ingest.done", count=f"{written:,}", where=where))
    print(
        t(
            "ingest.total",
            sessions=f"{found['Session']:,}",
            calls=f"{found['Call']:,}",
            failed=f"{found['failed calls']:,}",
            keys=f"{found['ErrorSig']:,}",
        )
    )
    return 0


def _export_web(args: argparse.Namespace) -> int:
    """The browser demo is meant to be published, so it never picks your own logs unasked.

    Without `--store` it ignores FAILDEX_STORE too: only an explicit option exports a store
    that may hold your own logs.
    """
    from faildex.export import write
    from faildex.store import public_store

    chosen = getattr(args, "store", None) is None
    if chosen:
        if (Path("store") / "manifest.json").is_file():
            args.store = Path("store")
        else:
            args.store = public_store()
    db = _open(args)
    if db is None:
        return 1
    try:
        local = next(
            iter(
                db.execute(
                    "MATCH (s:Session) WHERE NOT (s)-[:FROM]->(:Source) RETURN count(s) AS n"
                )
            )
        )["n"]
        if local and chosen:
            message = t("err.export_own_logs", store=args.store, count=f"{local:,}")
            print(t("err.prefix", message=message))
            return 1
        size = write(db, args.out)
    finally:
        db.close()
    print(t("web.wrote", out=args.out, size=f"{size / 1e6:.2f}", store=args.store))
    if local:
        print(t("web.note_own", count=f"{local:,}"))
    return 0


def _report(args: argparse.Namespace) -> int:
    from faildex.report import render

    if args.hook_log is not None and not args.hook_log.is_file():
        print(t("err.prefix", message=t("err.no_hook_log", path=args.hook_log)))
        return 1
    db = _open(args)
    if db is None:
        return 1
    print(render(db, args.split, args.key, args.hook_log))
    db.close()
    return 0


def _demo(args: argparse.Namespace) -> int:
    """Rules, a pre-run check and the evaluation, on the public store that ships with faildex."""
    import sys

    from faildex.evaluate import report
    from faildex.hook import notice_for
    from faildex.insight import proposals, render, safe_console_text, use_color, warnings_for
    from faildex.store import open_store, public_store

    color = use_color(sys.stdout)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    db = open_store(public_store())
    try:
        print(t("demo.rules"))
        print(
            safe_console_text(render(proposals(db)[:3], color=color, encoding=encoding), sys.stdout)
        )
        print(t("demo.check"))
        for command in ("git status", "ls"):
            found = warnings_for(db, command)
            print(f"$ {command}")
            print(f"  {notice_for(found)}" if found else t("demo.no_notice"))
        print(t("demo.eval"))
        print(report(db))
    finally:
        db.close()
    print(t("demo.end"))
    return 0


def _sources(args: argparse.Namespace) -> int:
    from faildex.build import SOURCES

    for source in SOURCES:
        print(source.name, source.repo, source.revision)
    return 0


def _positive(value: str) -> int:
    number = int(value) if value.lstrip("-").isdigit() else None
    if number is None or number < 1:
        raise argparse.ArgumentTypeError(t("err.whole_number", value=repr(value)))
    return number


def _day(value: str) -> str:
    """A YYYY-MM-DD day; the report compares it as text with the stored dates."""
    import re
    from datetime import date

    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value).isoformat()
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(t("err.day", value=repr(value)))


def _help(args: argparse.Namespace) -> int:
    import sys

    from faildex.guide import command, overview
    from faildex.i18n import current
    from faildex.insight import safe_console_text

    names = list(args.commands)
    if args.topic is None:
        text = overview(names, current())
    elif args.topic in args.commands:
        text = command(args.topic, args.commands[args.topic])
    else:
        message = t("err.unknown_topic", topic=args.topic, commands=", ".join(names))
        print(t("err.prefix", message=message), file=sys.stderr)
        return 2
    print(safe_console_text(text, sys.stdout))
    return 0


def _lang(args: argparse.Namespace) -> int:
    import os

    from faildex.i18n import ENV, LANGUAGES, config_path, current, origin, resolve, save, use

    env = os.environ.get(ENV)
    env_value = env.strip().lower() if env else None
    if args.choice is None:
        where = origin()
        detail = (
            t("lang.origin.config", path=_display_store_path(config_path()))
            if where == "config"
            else t(f"lang.origin.{where}")
        )
        print(t("lang.now", language=current(), origin=detail))
        if env and env_value not in LANGUAGES:
            print(t("lang.env_ignored", value=env))
        return 0
    try:
        path = save(args.choice)
    except (OSError, ValueError) as err:
        print(t("err.prefix", message=t("err.config", message=err)))
        return 1
    # The saved language applies now unless --lang or FAILDEX_LANG still decides it.
    use(*resolve(args.lang_option))
    _fit_console()
    print(t("lang.saved", language=args.choice, path=_display_store_path(path)))
    if env_value in LANGUAGES and env_value != args.choice:
        print(t("lang.env_wins", value=env))
    elif env and env_value not in LANGUAGES:
        print(t("lang.env_ignored", value=env))
    return 0


def _lang_option(argv: list[str]) -> str | None:
    """The value of --lang, read before the parser exists so its help text is translated."""
    found = None
    for i, word in enumerate(argv):
        if word == "--":
            break
        if word == "--lang" and i + 1 < len(argv):
            found = argv[i + 1]
        elif word.startswith("--lang="):
            found = word.split("=", 1)[1]
    return found


def _fit_console() -> None:
    """Korean on a console whose encoding cannot show it (cp1252, say): English, not a crash."""
    import sys

    from faildex.i18n import current, t, use

    if current() == "en":
        return
    broken = None
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None) or "utf-8"
        try:
            "한글".encode(encoding)
        except (UnicodeEncodeError, LookupError):
            broken = broken or encoding
    if broken is None:
        return
    use("en", "console")
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="replace")  # any other glyph it cannot show becomes "?"
            except (ValueError, OSError):
                pass
    print(t("note.console", encoding=broken), file=sys.stderr)


class _Formatter(argparse.HelpFormatter):
    """argparse's formatter with the `usage:` prefix in the chosen language."""

    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, t("argparse.usage") if prefix is None else prefix)


def _translate(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser._positionals.title = t("argparse.positional")
    parser._optionals.title = t("argparse.options")
    return parser


def build_parser() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    """The faildex parser in the current language, and each command's own parser."""
    from faildex.i18n import LANGUAGES

    parser = _translate(
        argparse.ArgumentParser(
            prog="faildex",
            description=t("cli.description"),
            epilog=t("cli.epilog"),
            formatter_class=_Formatter,
            add_help=False,
        )
    )
    parser.add_argument("-h", "--help", action="help", help=t("opt.help"))
    parser.add_argument(
        "--version", action="version", version=f"faildex {__version__}", help=t("opt.version")
    )
    parser.add_argument("--lang", choices=LANGUAGES, default=None, help=t("opt.lang"))
    commands = parser.add_subparsers(dest="command")
    found: dict[str, argparse.ArgumentParser] = {}

    def add(name: str) -> argparse.ArgumentParser:
        sub = _translate(
            commands.add_parser(
                name,
                help=t(f"cmd.{name}"),
                formatter_class=_Formatter,
                add_help=False,
            )
        )
        sub.add_argument("-h", "--help", action="help", help=t("opt.help"))
        sub.add_argument("--lang", choices=LANGUAGES, default=argparse.SUPPRESS, help=t("opt.lang"))
        found[name] = sub
        return sub

    build = add("build-store")
    build.add_argument("--data", type=Path, default=Path(".tmp/data"), help=t("opt.build.data"))
    build.add_argument("--out", type=Path, default=Path("store"), help=t("opt.build.out"))
    build.set_defaults(run=_build_store)

    evaluate = add("eval")
    evaluate.add_argument("--store", type=Path, default=None, help=t("opt.store"))
    evaluate.set_defaults(run=_eval)

    rules = add("rules")
    rules.add_argument("--approve", type=int, nargs="+", metavar="N", help=t("opt.rules.approve"))
    rules.add_argument("--to", type=Path, default=Path("faildex-rules.md"), help=t("opt.rules.to"))
    rules.add_argument("--evidence", action="store_true", help=t("opt.rules.evidence"))
    rules.set_defaults(run=_rules)

    linker = add("link")
    linker.add_argument(
        "--rules", type=Path, default=Path("~/faildex-rules.md"), help=t("opt.link.rules")
    )
    linker.add_argument("--remove", action="store_true", help=t("opt.link.remove"))
    linker.add_argument("--dry-run", action="store_true", help=t("opt.link.dry_run"))
    linker.set_defaults(run=_link)

    check = add("check")
    check.add_argument("command_line", help=t("opt.check.command_line"))
    check.set_defaults(run=_check)

    hook = add("hook")
    hook.add_argument(
        "--agent",
        choices=("claude", "codex", "cursor"),
        default="claude",
        help=t("opt.hook.agent"),
    )
    hook.add_argument(
        "--event",
        choices=("session-start", "pre-shell"),
        default="pre-shell",
        help=t("opt.hook.event"),
    )
    hook.add_argument(
        "--rules", type=Path, default=Path("~/faildex-rules.md"), help=t("opt.hook.rules")
    )
    hook.add_argument(
        "--rules-encoded",
        dest="encoded_rules",
        help=argparse.SUPPRESS,
        type=lambda value: Path(base64.urlsafe_b64decode(value).decode("utf-8")),
    )
    hook.add_argument("--log", type=Path, default=None, help=t("opt.hook.log"))
    hook.set_defaults(run=_hook)

    report = add("report")
    report.add_argument("--store", type=Path, default=None, help=t("opt.store"))
    report.add_argument("--split", metavar="YYYY-MM-DD", type=_day, help=t("opt.report.split"))
    report.add_argument("--key", help=t("opt.report.key"))
    report.add_argument("--hook-log", type=Path, default=None, help=t("opt.report.hook_log"))
    report.set_defaults(run=_report)

    mcp = add("mcp")
    mcp.add_argument("--store", type=Path, default=None, help=t("opt.store"))
    mcp.set_defaults(run=_mcp)

    for sub, top in ((rules, 10), (check, 3), (hook, 2)):
        sub.add_argument("--store", type=Path, default=None, help=t("opt.store"))
        sub.add_argument("--min-sessions", type=_positive, default=2, help=t("opt.min_sessions"))
        sub.add_argument("--top", type=_positive, default=top, help=t("opt.top"))

    ingest = add("ingest")
    for flag, metavar in (
        ("--claude", "DIR"),
        ("--codex", "FILE"),
        ("--codex-sessions", "DIR"),
        ("--cursor", "DIR"),
        ("--antigravity", "DIR"),
    ):
        ingest.add_argument(
            flag,
            type=Path,
            action="append",
            default=[],
            metavar=metavar,
            help=t(f"opt.ingest.{flag[2:].replace('-', '_')}"),
        )
    ingest.add_argument("--store", type=Path, default=None, help=t("opt.store"))
    ingest.set_defaults(run=_ingest)

    web = add("export-web")
    web.add_argument("--out", type=Path, default=Path("site/data.json"), help=t("opt.web.out"))
    web.add_argument("--store", type=Path, default=argparse.SUPPRESS, help=t("opt.web.store"))
    web.set_defaults(run=_export_web)

    add("demo").set_defaults(run=_demo)
    add("sources").set_defaults(run=_sources)

    guide = add("help")
    guide.add_argument("topic", nargs="?", metavar="COMMAND", help=t("opt.help.topic"))
    guide.set_defaults(run=_help, commands=found)

    language = add("lang")
    language.add_argument(
        "choice", nargs="?", choices=LANGUAGES, metavar="{en,ko}", help=t("opt.lang.choice")
    )
    language.set_defaults(run=_lang)
    return parser, found


def main(argv: list[str] | None = None) -> int:
    import sys

    from faildex.i18n import resolve, use

    argv = sys.argv[1:] if argv is None else list(argv)
    option = _lang_option(argv)
    use(*resolve(option))
    _fit_console()
    parser, _ = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    args.lang_option = option
    args.store_given = getattr(args, "store", None) is not None
    if getattr(args, "store", "set") is None:
        import os

        from faildex.store import PRIVATE_STORE, default_store

        private = PRIVATE_STORE.expanduser()
        if args.command == "ingest":
            args.store = private
        elif (
            args.command == "report"
            and not os.environ.get("FAILDEX_STORE")
            and (private / "manifest.json").is_file()
        ):
            args.store = private  # report is about your own logs, even inside a checkout
        else:
            args.store = default_store()
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
