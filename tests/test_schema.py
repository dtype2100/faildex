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
