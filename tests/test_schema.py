import relate

from faildex.schema import CallRecord, ingest

# Two sessions, five calls. Both sessions hit the same failure; s1 recovers.
RECORDS = [
    CallRecord("claude-code", "s1", 0, "Bash", True, command="git status"),
    CallRecord("claude-code", "s1", 1, "Bash", False, command="echo", error_sig="=== not found"),
    CallRecord(
        "claude-code", "s1", 2, "Bash", True, command="echo", source_path="a.jsonl", source_line=9
    ),
    CallRecord("codex", "s2", 0, "exec", False, command="echo", error_sig="=== not found"),
    CallRecord("codex", "s2", 1, "exec", True, command="ls"),
]


def one(db, query):
    return next(iter(db.execute(query)))


def counts(db):
    nodes = one(db, "MATCH (n) RETURN count(n) AS n")["n"]
    rels = one(db, "MATCH ()-[r]->() RETURN count(r) AS n")["n"]
    return nodes, rels


def make_db():
    db = relate.connect(":memory:")
    assert ingest(db, RECORDS) == 5
    return db


def test_node_and_relationship_counts():
    # 2 Session + 5 Call + 3 Command + 1 ErrorSig; 5 HAS_CALL + 3 NEXT + 5 RAN + 2 FAILED_WITH
    assert counts(make_db()) == (11, 15)


def test_ingesting_twice_changes_nothing():
    db = make_db()
    before = counts(db)
    ingest(db, RECORDS)
    assert counts(db) == before


def test_next_stays_inside_one_session():
    db = make_db()
    crossing = one(
        db,
        "MATCH (s1:Session)-[:HAS_CALL]->(a)-[:NEXT]->(b)<-[:HAS_CALL]-(s2:Session) "
        "WHERE s1 <> s2 RETURN count(*) AS n",
    )["n"]
    assert crossing == 0


def test_failure_shared_across_sessions_and_agents():
    db = make_db()
    row = one(
        db,
        "MATCH (e:ErrorSig)<-[:FAILED_WITH]-(c:Call)<-[:HAS_CALL]-(s:Session) "
        "RETURN e.sig AS sig, count(DISTINCT s) AS sessions, count(DISTINCT s.agent) AS agents",
    )
    assert (row["sig"], row["sessions"], row["agents"]) == ("=== not found", 2, 2)


def test_recovery_path_is_found():
    db = make_db()
    rows = list(
        db.execute(
            "MATCH (e:ErrorSig {sig: '=== not found'})<-[:FAILED_WITH]-(f:Call)-[:NEXT*1..3]->(fix:Call) "
            "WHERE fix.ok MATCH (f)-[:RAN]->(k:Command)<-[:RAN]-(fix) "
            "RETURN fix.id AS fix, fix.source_line AS line"
        )
    )
    assert [(r["fix"], r["line"]) for r in rows] == [("claude-code:s1:2", 9)]


def _failed(**fields):
    return CallRecord(agent="a", session_id="s", seq=0, tool="Bash", ok=False, **fields)


def test_failure_key_prefers_text_then_exit_code():
    assert _failed(command="npm run", error_sig="missing script", exit_code=1).failure == (
        "missing script",
        "text",
    )
    assert _failed(command="npm run", exit_code=2).failure == ("npm run exited 2", "exit")


def test_failure_key_skips_no_match_exits_and_unknown_commands():
    assert _failed(command="rg", exit_code=1).failure is None  # nothing matched
    assert _failed(command="rg", exit_code=2).failure == ("rg exited 2", "exit")
    assert _failed(command="<script>", exit_code=1).failure is None
    assert _failed(exit_code=1).failure is None
    assert CallRecord(agent="a", session_id="s", seq=0, tool="Bash", ok=True).failure is None


def _c(seq, ok=True, command="git push", sig=None, ts=None, session="s"):
    return CallRecord(
        agent="a",
        session_id=session,
        seq=seq,
        tool="Bash",
        ok=ok,
        command=command,
        error_sig=sig,
        ts=ts,
    )


def _rows(db, query):
    return [dict(r) for r in db.execute(query)]


def test_reingesting_a_changed_call_replaces_its_links():
    import relate

    from faildex.schema import ingest

    db = relate.connect(":memory:")
    ingest(db, [_c(0, ok=False, sig="first failure")])
    ingest(db, [_c(0, ok=True, command="npm run")])
    assert _rows(db, "MATCH (:Call)-[:FAILED_WITH]->(e) RETURN e.sig AS sig") == []
    assert _rows(db, "MATCH (:Call)-[:RAN]->(k) RETURN k.template AS t") == [{"t": "npm run"}]


def test_duplicate_and_partial_loads_keep_one_next_chain():
    import relate

    from faildex.schema import ingest

    db = relate.connect(":memory:")
    ingest(db, [_c(0), _c(1), _c(0), _c(1)])
    ingest(db, [_c(3)])
    ingest(db, [_c(2)])
    chain = _rows(db, "MATCH (a:Call)-[:NEXT]->(b:Call) RETURN a.seq AS a, b.seq AS b ORDER BY a")
    assert chain == [{"a": 0, "b": 1}, {"a": 1, "b": 2}, {"a": 2, "b": 3}]


def test_timestamps_are_stored_in_utc_so_text_order_is_time_order():
    import relate

    from faildex.schema import ingest, utc

    assert utc("2026-01-01T01:00:00-08:00") == "2026-01-01T09:00:00.000000Z"
    assert utc("2026-01-01T00:30:00Z") < utc("2026-01-01T01:00:00-08:00")
    assert utc("not a time") is None
    db = relate.connect(":memory:")
    ingest(db, [_c(0, ts="2026-01-01T09:00:00+09:00"), _c(1, ts="2026-01-01T00:00:01Z")])
    assert _rows(db, "MATCH (s:Session) RETURN s.started_at AS t") == [
        {"t": "2026-01-01T00:00:00.000000Z"}
    ]


def test_a_shared_store_refuses_local_paths():
    import pytest
    import relate

    from faildex.schema import ingest

    local = CallRecord(
        agent="a",
        session_id="s",
        seq=0,
        tool="Bash",
        ok=True,
        source_path="/Users/alice/private/session.jsonl",
    )
    db = relate.connect(":memory:")
    for bad in (local, CallRecord("a", "s", 1, "Bash", True, source_path="../up/x.jsonl")):
        with pytest.raises(ValueError, match="local path"):
            ingest(db, [bad])
    assert ingest(db, [local], local_paths=True) == 1
