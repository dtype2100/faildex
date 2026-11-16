import relate

from faildex.evaluate import cutoff, evaluate, report, shared_keys
from faildex.schema import CallRecord, ingest


def _call(session, day, seq, ok=True, command="git push", sig=None, agent="claude_code"):
    return CallRecord(
        agent=agent,
        session_id=session,
        seq=seq,
        tool="Bash",
        ok=ok,
        ts=f"2026-01-{day:02d}T00:00:{seq:02d}Z",
        command=command,
        error_sig=sig,
    )


def _graph():
    """Ten sessions on ten days: seven earlier, three later."""
    records = []
    # s1: a failure that is fixed two calls later.
    records += [
        _call("s1", 1, 0, ok=False, sig="rejected: non-fast-forward"),
        _call("s1", 1, 1, command="git pull"),
        _call("s1", 1, 2),
    ]
    # s2: a failure that is never fixed.
    records += [_call("s2", 2, 0, ok=False, command="npm run", sig="missing script")]
    records += [_call(f"s{n}", n, 0) for n in range(3, 8)]
    # Later period: one repeat of each earlier failure, and one new failure.
    records += [_call("s8", 8, 0, ok=False, sig="rejected: non-fast-forward")]
    records += [_call("s9", 9, 0, ok=False, command="npm run", sig="missing script")]
    records += [_call("s10", 10, 0, ok=False, command="cargo build", sig="linker not found")]
    db = relate.connect(":memory:")
    ingest(db, records)
    db.execute("CREATE (:Source {name: 'demo'})")
    db.execute("MATCH (s:Session), (d:Source {name: 'demo'}) MERGE (s)-[:FROM]->(d)")
    return db


def test_cutoff_puts_the_last_thirty_percent_later():
    starts = [f"d{n:02d}" for n in range(10)]
    assert cutoff(starts) == "d07"
    assert cutoff(["only"]) is None
    assert cutoff([]) is None


def test_recurrence_and_warnable_on_a_known_graph():
    by_source = {r.source: r for r in evaluate(_graph())}
    demo = by_source["demo"]
    assert (demo.earlier_sessions, demo.later_sessions) == (7, 3)
    assert demo.later_failures == 3
    assert demo.recurring == 2  # s8 and s9 repeat; s10 is new
    assert demo.warnable == 1  # only the git push failure was fixed on record
    assert round(demo.recurrence, 3) == 0.667
    assert by_source["all"].recurring == 2


def test_a_failure_first_seen_later_is_not_recurring():
    db = _graph()
    later_only = next(r for r in evaluate(db) if r.source == "demo")
    assert later_only.later_keys == 3
    assert later_only.recurring_keys == 2


def test_shared_keys_need_two_agents():
    db = _graph()
    assert shared_keys(db) == []
    ingest(db, [_call("c1", 1, 0, ok=False, sig="missing script", agent="codex")])
    assert shared_keys(db) == ["missing script"]


def test_report_prints_both_tables():
    text = report(_graph())
    assert "recurrence" in text
    assert "Failure text only" in text
    assert "66.7%" in text


def test_what_an_earlier_session_did_after_the_cut_is_not_known_earlier():
    records = [_call(f"s{n}", n, 0) for n in range(1, 8)]
    # s1 starts first but only fails on day 9, after the later period began.
    late = _call("s1", 9, 1, ok=False, sig="disk full")
    records.append(late)
    records += [_call(f"s{n}", n, 0, ok=False, sig="disk full") for n in (8, 10)]
    records.append(_call("s9", 9, 0))
    db = relate.connect(":memory:")
    ingest(db, records)
    db.execute("CREATE (:Source {name: 'demo'})")
    db.execute("MATCH (s:Session), (d:Source {name: 'demo'}) MERGE (s)-[:FROM]->(d)")
    demo = evaluate(db)[0]
    assert demo.later_failures == 2
    assert demo.recurring == 0
