"""The hook's index gives, byte for byte, what the hook gives reading the store itself.

This is the gate for the index: for every command template in the store, the zsh
pooled rules, several `--min-sessions`/`--top`, both agents' formats and both
languages of the rule text, the answer from the index equals the answer from the store.
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from faildex import hook, index
from faildex.cli import main
from faildex.insight import warnings_for_line
from faildex.store import STORE_PARTS, open_store

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
# Lines that reach the pooled zsh rules, compound lines and lines faildex never saw.
EXTRA_LINES = [
    "ls *.py",
    "for f in *.x; do ls README*; done",
    "echo ====",
    "echo ==== && ls *.md",
    "git status && ls",
    "cd /tmp && git status; git log --oneline | head",
    "a-command-no-store-has-seen --flag",
    "",
]
REAL_START_REBUILD = index.start_rebuild


def _claude_session(path: Path, session: str, calls: list[tuple[str, str | None]]) -> None:
    """A Claude Code transcript with these Bash calls; an error text marks a failure."""
    lines = []
    parent = None
    for n, (command, error) in enumerate(calls):
        use, result = f"{session}-a{n}", f"{session}-u{n}"
        stamp = f"2026-11-17T09:{n:02d}:00.000Z"
        lines.append(
            {
                "type": "assistant",
                "uuid": use,
                "parentUuid": parent,
                "sessionId": session,
                "timestamp": stamp,
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": f"toolu_{use}",
                            "name": "Bash",
                            "input": {"command": command},
                        }
                    ],
                },
            }
        )
        lines.append(
            {
                "type": "user",
                "uuid": result,
                "parentUuid": use,
                "sessionId": session,
                "timestamp": stamp,
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": f"toolu_{use}",
                            "is_error": error is not None,
                            "content": f"Exit code 1\n{error}" if error else "ok",
                        }
                    ],
                },
            }
        )
        parent = result
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


@pytest.fixture(scope="module")
def private_store(tmp_path_factory):
    """A store shaped like a private one: local pointers, several agents, both zsh pools."""
    base = tmp_path_factory.mktemp("private")
    logs = base / "logs"
    logs.mkdir()
    for session in ("sess-eq-a", "sess-eq-b", "sess-eq-c"):
        _claude_session(
            logs / f"{session}.jsonl",
            session,
            [
                ("echo ====", "(eval):1: ==== not found"),
                ("echo '===='", None),
                ("git push", "fatal: the current branch has no upstream branch"),
                ("git push -u origin main", None),
                ("git push", None),
                ("pytest -q", "error: 2 failed"),
                ("pytest -q", None),
            ],
        )
    store = base / "store"
    argv = ["ingest", "--store", str(store), "--claude", str(logs)]
    argv += ["--claude", str(FIXTURES / "claude_code"), "--claude", str(FIXTURES / "zsh_glob")]
    argv += ["--codex", str(FIXTURES / "codex" / "trajectories.sample.jsonl")]
    argv += ["--codex-sessions", str(FIXTURES / "codex_local")]
    argv += ["--antigravity", str(FIXTURES / "antigravity")]
    assert main(argv) == 0
    return store


@pytest.fixture(scope="module")
def public_store(tmp_path_factory):
    """A copy of the committed public store, prepared once, with its index beside it."""
    store = tmp_path_factory.mktemp("public") / "store"
    shutil.copytree(ROOT / "store", store)
    db = open_store(store)  # the usual first open creates the per-machine files
    try:
        body = index.build(db)
    finally:
        db.close()
    index.write(index.beside(store), index.fingerprint(store), body)
    return store


def _lines(store: Path) -> list[str]:
    db = open_store(store)
    try:
        templates = sorted(r["t"] for r in db.execute("MATCH (k:Command) RETURN k.template AS t"))
    finally:
        db.close()
    return templates + EXTRA_LINES


def _bash(line: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": line}})


class _Shared:
    """One read-only connection lent to every call, so the comparison opens a store once."""

    def __init__(self, db):
        self._db = db

    def execute(self, *args, **kwargs):
        return self._db.execute(*args, **kwargs)

    def close(self):
        pass


@pytest.fixture
def via_store(monkeypatch):
    """Run a call with the index out of the way: the hook's own store lookup, read-only."""
    opened = {}

    def run(store, call):
        if store not in opened:
            opened[store] = hook._open_read_only(store)
        with monkeypatch.context() as m:
            m.setattr(index, "load", lambda store: None)
            m.setattr(hook, "_open_read_only", lambda store: _Shared(opened[store]))
            return call()

    yield run
    for db in opened.values():
        db.close()


def _via_index(store, monkeypatch, call):
    """Run `call` from the index only: opening the store would fail the test."""

    def refuse(store):
        raise AssertionError("the hook opened the store although its index matches")

    with monkeypatch.context() as m:
        m.setattr(hook, "_open_read_only", refuse)
        return call()


@pytest.mark.parametrize("which", ["public_store", "private_store"])
def test_hook_output_from_the_index_is_byte_identical(which, request, monkeypatch, via_store):
    store = request.getfixturevalue(which)
    assert index.load(store) is not None
    lines = _lines(store)
    warned = 0
    for line in lines:
        for min_sessions in (1, 2, 3):
            for top in (1, 2, 5):
                for agent in ("claude", "cursor"):
                    raw = _bash(line) if agent == "claude" else json.dumps({"command": line})

                    def answer(raw=raw, min_sessions=min_sessions, top=top, agent=agent):
                        return hook.respond(raw, store, min_sessions, None, top, agent=agent)

                    direct = via_store(store, answer)
                    from_index = _via_index(store, monkeypatch, answer)
                    assert from_index.encode() == direct.encode(), (line, min_sessions, top, agent)
                    warned += bool(direct) and direct != json.dumps({"permission": "allow"})
    assert warned > 0  # the comparison covered real warnings, not only silence


@pytest.mark.parametrize("which", ["public_store", "private_store"])
def test_rule_text_in_both_languages_is_identical(which, request):
    store = request.getfixturevalue(which)
    found = index.load(store)
    db = open_store(store)
    try:
        for line in _lines(store):
            for min_sessions in (1, 2):
                _, from_db = warnings_for_line(db, line, min_sessions)
                _, from_index = found.warnings_for_line(line, min_sessions)

                def text(pairs):
                    return [
                        (t, i.rule("en"), i.rule("ko"), i.notice(), i.score, i.evidence)
                        for t, i in pairs
                    ]

                assert text(from_index) == text(from_db), (line, min_sessions)
    finally:
        db.close()


def test_the_private_store_reaches_both_pooled_zsh_rules(private_store):
    found = index.load(private_store)
    for line, sig in (("echo ====", "=<word> not found"), ("ls *.py", "no matches found: <glob>")):
        _, pairs = found.warnings_for_line(line, 2)
        assert ("zsh", sig) in [(t, i.sig) for t, i in pairs]


def test_ingest_writes_the_index_after_the_store(private_store):
    data = json.loads(index.beside(private_store).read_text(encoding="utf-8"))
    assert data["version"] == index.INDEX_VERSION
    assert data["manifest_sha256"] == index.fingerprint(private_store)
    assert data["faildex"] and data["created"]
    assert not list(private_store.parent.glob(".store-index.json.*"))  # no temporary left


@pytest.mark.parametrize(
    "spoil",
    [
        lambda path: path.write_text("{not json"),
        lambda path: path.write_text(json.dumps({"version": 999})),
        lambda path: path.write_text(
            json.dumps({**json.loads(path.read_text()), "version": index.INDEX_VERSION + 1})
        ),
        lambda path: path.write_text(
            json.dumps({**json.loads(path.read_text()), "manifest_sha256": "0" * 64})
        ),
        lambda path: path.write_text(json.dumps({**json.loads(path.read_text()), "commands": []})),
        lambda path: (path.unlink(), path.mkdir()),  # unreadable as a file
        lambda path: path.unlink(),
    ],
)
def test_a_bad_index_falls_back_to_the_store(tmp_path, spoil, monkeypatch):
    store = tmp_path / "store"
    shutil.copytree(ROOT / "store", store)
    open_store(store).close()
    index_file = index.beside(store)
    db = open_store(store)
    try:
        index.write(index_file, index.fingerprint(store), index.build(db))
    finally:
        db.close()
    payload = _bash("git status")
    expected = hook.respond(payload, store)
    assert expected
    spoil(index_file)
    assert index.load(store) is None
    assert hook.respond(payload, store) == expected


def test_without_an_index_a_store_that_cannot_be_read_gives_silence_and_stays_unwritten(tmp_path):
    """A fresh copy refuses a read-only open; the hook must not do the writable first open."""
    store = tmp_path / "store"
    store.mkdir()
    for part in STORE_PARTS:  # only the committed files, as in a fresh clone
        src = ROOT / "store" / part
        if src.is_dir():
            shutil.copytree(src, store / part)
        elif src.is_file():
            shutil.copy2(src, store / part)
    before = sorted(str(p.relative_to(store)) for p in store.rglob("*"))
    assert hook.respond(_bash("git status"), store) == ""
    assert sorted(str(p.relative_to(store)) for p in store.rglob("*")) == before
    assert hook.respond(_bash("git status"), tmp_path / "missing") == ""


def test_the_index_path_does_not_load_relate(public_store):
    code = (
        "import sys, io; from faildex.cli import main\n"
        "sys.stdin = io.StringIO(sys.argv[2])\n"
        "main(['hook', '--store', sys.argv[1]])\n"
        "print('RELATE' if 'relate' in sys.modules else 'NO-RELATE')\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code, str(public_store), _bash("git status")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "systemMessage" in out and out.rstrip().endswith("NO-RELATE")


def test_a_hook_without_an_index_has_one_built_once(tmp_path, monkeypatch):
    monkeypatch.setattr(index, "start_rebuild", REAL_START_REBUILD)
    store = tmp_path / "store"
    shutil.copytree(ROOT / "store", store)
    open_store(store).close()
    payload = _bash("git status")
    expected = hook.respond(payload, store)
    assert hook.respond(payload, store, rebuild=True) == expected
    lock = index.cached(store).with_suffix(".lock")
    deadline = time.monotonic() + 60
    while index.load(store) is None and time.monotonic() < deadline:
        time.sleep(0.2)
    assert index.load(store) is not None
    assert not index.beside(store).exists()  # the cache, not next to someone's store
    while lock.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    index.cached(store).unlink()
    hook.respond(payload, store, rebuild=True)  # within the pause: nothing started
    time.sleep(1)
    assert not index.cached(store).exists() and not lock.exists()


def test_the_background_rebuild_never_opens_a_store_for_writing(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    for part in STORE_PARTS:
        src = ROOT / "store" / part
        if src.is_dir():
            shutil.copytree(src, store / part)
        elif src.is_file():
            shutil.copy2(src, store / part)
    before = sorted(str(p.relative_to(store)) for p in store.rglob("*"))
    with pytest.raises(Exception):  # noqa: B017 - Relate refuses the read-only open
        index.rebuild(store)
    assert sorted(str(p.relative_to(store)) for p in store.rglob("*")) == before
    assert not index.cached(store).exists()
