"""The hook's index gives, byte for byte, what the hook gives reading the store itself.

This is the gate for the index: for every failure in the store, from inside a session
that had it and from a new one, on simple and compound lines, at several
`--min-sessions`, and in both languages of the rule text, the notice from the index
equals the notice from the store.
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from payloads import NOT_A_REPO

from faildex import hook, index
from faildex.cli import main
from faildex.store import STORE_PARTS, open_store

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
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


# The failure each test store holds for a command (git status: the public demo store's).
FAILURES = {"git push": "fatal: the current branch has no upstream branch"}


def _bash(line: str) -> str:
    """The hook's payload after `line` failed the way the test stores hold for its command."""
    from payloads import failed

    return failed(line, FAILURES.get(line.split(" &&")[0], NOT_A_REPO), 1)


class _Shared:
    """One read-only connection lent to every call, so the comparison opens a store once."""

    def __init__(self, db):
        self._db = db
        self.used = 0

    def execute(self, *args, **kwargs):
        self.used += 1
        return self._db.execute(*args, **kwargs)

    def close(self):
        pass


@pytest.fixture
def via_store(monkeypatch):
    """Run a call with the index out of the way: the hook's own store lookup, read-only."""
    opened, reads = {}, []

    def run(store, call):
        if store not in opened:
            opened[store] = hook._open_read_only(store)
        shared = _Shared(opened[store])
        with monkeypatch.context() as m:
            # The hook asks `candidates`, not `load`: with no index, it reads the store.
            m.setattr(index, "candidates", lambda store: [])
            m.setattr(index, "load", lambda store: None)
            m.setattr(hook, "_open_read_only", lambda store: shared)
            answer = call()
        reads.append(shared.used)
        return answer

    run.reads = lambda: sum(reads)  # how often the store side really read the store
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


def _keys(store: Path) -> list[tuple[str, str, str, str]]:
    """Every (command template, stored failure key, its kind, a session that had it)."""
    db = open_store(store)
    try:
        rows = db.execute(
            "MATCH (s:Session)-[:HAS_CALL]->(c:Call)-[:RAN]->(k:Command), "
            "(c)-[:FAILED_WITH]->(e:ErrorSig) "
            "RETURN DISTINCT k.template AS t, e.sig AS sig, e.kind AS kind, s.session_id AS sid"
        )
        return sorted((r["t"], r["sig"], r["kind"] or "text", r["sid"] or "") for r in rows)
    finally:
        db.close()


def _record(template: str, sig: str, kind: str, session: str, compound: bool):
    """What `hook._failed_call` gives the hook for a failure of `template` with key `sig`."""
    from types import SimpleNamespace

    return SimpleNamespace(
        command=template,
        failure=(sig, kind),
        compound=compound,
        session_id=session,
        session_key=f"claude-code:{session}",
    )


@pytest.mark.parametrize("which", ["public_store", "private_store"])
def test_the_notice_from_the_index_is_byte_identical(which, request, monkeypatch, via_store):
    """For every stored failure, from inside a session that had it and from a new one, on
    a simple line and a compound one, at several --min-sessions: the same words."""
    store = request.getfixturevalue(which)
    assert index.load(store) is not None
    said = 0
    for template, sig, kind, session in _keys(store):
        for sid in (session, "new-session"):
            for compound in (False, True):
                for min_sessions in (1, 2, 3):
                    record = _record(template, sig, kind, sid, compound)

                    def answer(record=record, min_sessions=min_sessions):
                        return hook._found(
                            store,
                            {"tool_name": "Bash", "tool_input": {"command": record.command}},
                            False,
                            lambda source: hook._post_warning(source, record, min_sessions),
                        )

                    direct = via_store(store, answer)
                    from_index = _via_index(store, monkeypatch, answer)
                    assert from_index == direct, (template, sig, sid, compound, min_sessions)
                    said += direct is not None
    assert said > 0  # the comparison covered real notices, not only silence
    assert via_store.reads() > 0  # and the store side read the store, not an index


@pytest.mark.parametrize("which", ["public_store", "private_store"])
def test_rule_text_in_both_languages_is_identical(which, request):
    from faildex.insight import failures

    store = request.getfixturevalue(which)
    found = index.load(store)
    db = open_store(store)
    try:
        for template in sorted({t for t, _, _, _ in _keys(store)}):
            from_db = failures(db, template).values()
            _, from_index = found.command_failures(template)

            def text(items):
                return sorted(
                    (
                        i.sig,
                        i.rule("en"),
                        i.rule("ko"),
                        i.rule("en", step=False),
                        i.notice(),
                        i.notice(step=False),
                        i.score,
                        i.evidence,
                        dict(i.session_calls),
                        {s: dict(f) for s, f in i.session_fixes.items()},
                    )
                    for i in items
                )

            assert text(from_index) == text(from_db), template
    finally:
        db.close()


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


def test_without_an_index_a_never_opened_store_is_prepared_where_it_is(tmp_path):
    """A fresh copy refuses a read-only open; since the 5th fix the hook prepares it, as
    `main` did (the per-machine files only), and warns. A missing store stays silent."""
    store = tmp_path / "store"
    store.mkdir()
    for part in STORE_PARTS:  # only the committed files, as in a fresh clone
        src = ROOT / "store" / part
        if src.is_dir():
            shutil.copytree(src, store / part)
        elif src.is_file():
            shutil.copy2(src, store / part)
    committed = {p: p.read_bytes() for p in store.rglob("*") if p.is_file()}
    assert "git status" in hook.respond(_bash("git status"), store)
    assert (store / "wal").is_dir()
    assert {p: p.read_bytes() for p in committed} == committed  # committed files untouched
    assert hook.respond(_bash("git status"), tmp_path / "missing") == ""
    assert not (tmp_path / "missing").exists()


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


def test_the_background_rebuild_prepares_a_never_opened_store_as_the_hook_does(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    for part in STORE_PARTS:
        src = ROOT / "store" / part
        if src.is_dir():
            shutil.copytree(src, store / part)
        elif src.is_file():
            shutil.copy2(src, store / part)
    manifest = (store / "manifest.json").read_bytes()
    assert index.rebuild(store) == 0
    assert (store / "manifest.json").read_bytes() == manifest  # same fingerprint
    assert index.load(store) is not None  # keyed to the store as the hook names it
