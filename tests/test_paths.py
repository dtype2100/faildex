"""Path options take `~` as the home folder, even when the shell passes it through.

PowerShell 5.1 and cmd.exe hand `~/x` to a program unchanged, so faildex expands it
itself. conftest.py points HOME and USERPROFILE at a temporary folder, which is where
these tests expect every `~` path to land.
"""

import base64
import shutil
from pathlib import Path

from faildex.cli import build_parser, main
from faildex.store import STORE_PARTS

ROOT = Path(__file__).parent.parent
STORE = ROOT / "store"
FIXTURES = Path(__file__).parent / "fixtures"


def _copy_store(to: Path) -> None:
    to.mkdir(parents=True)
    for part in STORE_PARTS:
        source = STORE / part
        if source.is_dir():
            shutil.copytree(source, to / part)
        elif source.is_file():
            shutil.copy2(source, to / part)


def test_rules_approve_writes_a_tilde_path_into_the_home_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["rules", "--store", str(STORE), "--approve", "1", "--to", "~/x.md"]) == 0
    written = Path.home() / "x.md"
    assert written.is_file() and "When `" in written.read_text(encoding="utf-8")
    assert not (tmp_path / "~").exists()


def test_eval_reads_a_store_named_with_a_tilde(tmp_path, monkeypatch, capsys):
    _copy_store(Path.home() / ".faildex" / "store")
    monkeypatch.chdir(tmp_path)
    assert main(["eval", "--store", "~/.faildex/store"]) == 0
    out = capsys.readouterr().out
    assert "117" in out and "68.4%" in out


def test_a_missing_tilde_store_is_reported_at_the_expanded_path(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["eval", "--store", "~/nowhere"]) == 1
    out = capsys.readouterr().out
    assert f"no store at {Path.home() / 'nowhere'}" in out


def test_ingest_reads_and_writes_tilde_paths(tmp_path, monkeypatch, capsys):
    shutil.copytree(FIXTURES / "claude_code", Path.home() / "logs" / "p1")
    monkeypatch.chdir(tmp_path)
    assert main(["ingest", "--claude", "~/logs", "--store", "~/mine"]) == 0
    assert (Path.home() / "mine" / "manifest.json").is_file()
    assert "sessions 2" in capsys.readouterr().out
    assert not (tmp_path / "~").exists()


# Every path option, per command; a lost or new one fails here.
PATH_OPTIONS = {
    "build-store": {"data", "out"},
    "eval": {"store"},
    "rules": {"store", "to"},
    "link": {"rules"},
    "check": {"store"},
    "hook": {"rules", "encoded_rules", "log", "store"},
    "report": {"store", "hook_log"},
    "mcp": {"store"},
    "ingest": {"claude", "codex", "codex_sessions", "cursor", "antigravity", "store"},
    "export-web": {"out", "store"},
}


def test_every_path_option_expands_the_home_folder():
    from faildex.cli import _path

    _, commands = build_parser()
    found = {}
    for name, sub in commands.items():
        for action in sub._actions:
            assert action.type is not Path, (name, action.option_strings)
            if action.type is _path:
                found.setdefault(name, set()).add(action.dest)
            elif action.dest == "encoded_rules":  # base64 of a path, decoded then expanded
                encoded = base64.urlsafe_b64encode(b"~/r.md").decode()
                assert action.type(encoded) == Path.home() / "r.md"
                found.setdefault(name, set()).add(action.dest)
    assert found == PATH_OPTIONS


def test_only_the_home_folder_is_expanded():
    from faildex.cli import _path

    assert _path("~") == Path.home()
    assert _path("~/a") == Path.home() / "a"
    assert _path("~old") == Path("~old")  # a folder name, not a user's home
    assert _path("~nosuchuser/x") == Path("~nosuchuser/x")
    assert _path("a/~/b") == Path("a/~/b")


def test_a_folder_whose_name_starts_with_a_tilde_still_works(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    shutil.copytree(FIXTURES / "claude_code", tmp_path / "~old" / "p1")
    assert main(["ingest", "--claude", "~old", "--store", "~/mine"]) == 0
    assert "sessions 2" in capsys.readouterr().out
