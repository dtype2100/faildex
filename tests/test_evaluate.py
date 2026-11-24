import relate

from faildex.evaluate import STAGES, evaluate, hook_rules, replay, report, shared_keys, split
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


def test_split_is_exact_even_when_sessions_start_together():
    sessions = [(f"s{n}", "same") for n in range(10)]
    earlier, later, cut = split(sessions)
    assert (len(earlier), len(later), cut) == (7, 3, "same")
    assert split([("only", "t")]) is None
    assert split([]) is None


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
    assert len(later_only.later_keys) == 3
    assert len(later_only.recurring_keys) == 2


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


def test_a_recovery_of_one_command_does_not_make_another_command_warnable():
    records = [
        _call("s1", 1, 0, ok=False, sig="permission denied"),
        _call("s1", 1, 1),
    ]
    records += [_call(f"s{n}", n, 0) for n in range(2, 8)]
    records += [_call("s8", 8, 0, ok=False, command="rm", sig="permission denied")]
    records += [_call("s9", 9, 0, ok=False, sig="permission denied"), _call("s10", 10, 0)]
    db = relate.connect(":memory:")
    ingest(db, records)
    db.execute("CREATE (:Source {name: 'demo'})")
    db.execute("MATCH (s:Session), (d:Source {name: 'demo'}) MERGE (s)-[:FROM]->(d)")
    demo = evaluate(db)[0]
    assert (demo.later_failures, demo.recurring, demo.warnable) == (2, 2, 1)


def _scored(records):
    db = relate.connect(":memory:")
    ingest(db, records)
    db.execute("CREATE (:Source {name: 'demo'})")
    db.execute("MATCH (s:Session), (d:Source {name: 'demo'}) MERGE (s)-[:FROM]->(d)")
    demo = evaluate(db)[0]
    return demo.later_failures, demo.recurring, demo.warnable


def test_a_success_that_arrived_before_the_failure_is_no_recovery():
    from dataclasses import replace

    failed = replace(_call("s1", 1, 0, ok=False, sig="rejected"), ts="2026-01-01T00:00:03Z")
    earlier_success = replace(_call("s1", 1, 1), ts="2026-01-01T00:00:02Z")
    records = [failed, earlier_success, *[_call(f"s{n}", n, 0) for n in range(2, 8)]]
    records += [_call("s8", 8, 0, ok=False, sig="rejected"), _call("s9", 9, 0), _call("s10", 10, 0)]
    assert _scored(records) == (1, 1, 0)


def test_a_later_compound_failure_is_recurring_but_not_warnable():
    from dataclasses import replace

    records = [_call("s1", 1, 0, ok=False, sig="timed out"), _call("s1", 1, 1)]
    records += [_call(f"s{n}", n, 0) for n in range(2, 8)]
    records += [replace(_call("s8", 8, 0, ok=False, sig="timed out"), compound=True)]
    records += [_call("s9", 9, 0, ok=False, sig="timed out"), _call("s10", 10, 0)]
    assert _scored(records) == (2, 2, 1)


def _no_sources(records):
    db = relate.connect(":memory:")
    ingest(db, records)
    return db


def test_a_private_store_without_datasets_is_scored_per_agent():
    """`faildex ingest` stores carry no Source nodes; the same split runs per agent."""
    records = [
        _call("s1", 1, 0, ok=False, sig="rejected: non-fast-forward"),
        _call("s1", 1, 1, command="git pull"),
        _call("s1", 1, 2),
        _call("s2", 2, 0, ok=False, command="npm run", sig="missing script"),
        *[_call(f"s{n}", n, 0) for n in range(3, 8)],
        _call("s8", 8, 0, ok=False, sig="rejected: non-fast-forward"),
        _call("s9", 9, 0, ok=False, command="npm run", sig="missing script"),
        _call("s10", 10, 0, ok=False, command="cargo build", sig="linker not found"),
    ]
    # A second agent with too few sessions to split is left out, not scored as empty.
    records.append(_call("c1", 1, 0, ok=False, agent="codex", sig="missing script"))
    db = _no_sources(records)
    by_agent = {r.source: r for r in evaluate(db)}
    assert set(by_agent) == {"claude_code", "all"}
    mine = by_agent["claude_code"]
    assert (mine.earlier_sessions, mine.later_sessions) == (7, 3)
    assert (mine.later_failures, mine.recurring, mine.warnable) == (3, 2, 1)
    text = report(db)
    assert text.startswith("No public dataset in this store, so sessions are grouped by agent.")
    assert "each agent's sessions" in text
    assert "\nagent " in text and "claude_code" in text


def test_report_explains_an_unscorable_store_instead_of_an_empty_table():
    db = _no_sources([_call("s1", 1, 0, ok=False, sig="missing script")])
    text = report(db)
    assert (
        "Nothing to score: no agent has 2 or more sessions with a start time (1 agent found)."
        in text
    )
    assert "faildex report" in text
    assert "recurrence" not in text


def test_public_datasets_keep_the_dataset_table():
    text = report(_graph())
    assert text.startswith("Split: first 70% of each dataset's sessions")
    assert "grouped by agent" not in text
    assert "\ndataset " in text


def test_the_unscorable_hint_keeps_the_store_the_reader_chose(tmp_path, capsys):
    from faildex.cli import _shell_path, main

    store = tmp_path / "one session"
    db = relate.connect(str(store))
    ingest(db, [_call("s1", 1, 0, ok=False, sig="missing script")])
    db.commit()
    db.flush()
    db.close()
    assert main(["eval", "--store", str(store)]) == 0
    out = capsys.readouterr().out
    assert f"run: faildex report --store {_shell_path(store)}" in out


# The hook replay: the hook's own rule, earlier period known, later period scored.


def _replay_graph(sources=True):
    """Seven earlier sessions, three later; `git push` fails in 2 of 9 earlier runs."""
    records = [
        _call("s1", 1, 0, ok=False, sig="rejected"),
        _call("s2", 2, 0, ok=False, sig="rejected"),
        _call("s3", 3, 0, ok=False, command="npm run", sig="missing script"),
        *[_call(f"s{n}", n, 1) for n in range(1, 8)],
        # Later: a warned call that fails as named, a warned call that works,
        # a failure seen in one earlier session only, and a failure of another tool.
        _call("s8", 8, 0, ok=False, sig="rejected"),
        _call("s9", 9, 0),
        _call("s10", 10, 0, ok=False, command="npm run", sig="missing script"),
        CallRecord(
            agent="claude_code",
            session_id="s10",
            seq=1,
            tool="Edit",
            ok=False,
            ts="2026-01-10T00:00:01Z",
            error_sig="file has not been read yet",
        ),
    ]
    db = relate.connect(":memory:")
    ingest(db, records)
    if sources:
        db.execute("CREATE (:Source {name: 'demo'})")
        db.execute("MATCH (s:Session), (d:Source {name: 'demo'}) MERGE (s)-[:FROM]->(d)")
    return db


def test_the_hook_replay_counts_where_each_later_failure_stops():
    demo, every = replay(_replay_graph())
    assert demo.source == "demo" and every.source == "all"
    # s8 git push: warned and failed as named; s10 npm run: seen in one earlier session
    # only; s10 Edit: not a shell call.
    assert dict(zip(STAGES, demo.funnel)) == {
        "failure": 3,
        "shell": 2,
        "named": 2,
        "known": 2,
        "command": 2,
        "sessions": 1,
        "rate": 1,
        "cap": 1,
    }
    assert sorted(stage for _, stage in demo.stages) == ["cap", "command", "failure"]
    assert (demo.shell_calls, demo.warned, demo.warned_ok, demo.came_true, demo.other) == (
        3,
        2,
        1,
        1,
        0,
    )
    assert demo.came_true_sessions == (1,)
    [outcome] = demo.rules
    assert (outcome.rule.command, outcome.rule.sig) == ("git push", "rejected")
    assert (outcome.rule.calls, outcome.rule.runs, outcome.rule.sessions) == (2, 9, 2)
    assert (outcome.warned, outcome.came_true) == (2, 1)


def test_the_replay_knows_nothing_from_after_the_cut():
    """A rule learned only from later sessions must not warn in the later period."""
    db = _replay_graph()
    ingest(db, [_call("s9", 9, 1, ok=False, command="npm run", sig="missing script")])
    demo = replay(db)[0]
    assert [o.rule.command for o in demo.rules] == ["git push"]


def test_the_replay_uses_the_hooks_own_rule_on_every_command_of_the_store():
    """With every session known, the replay's rules are what the hook would say today."""
    from pathlib import Path

    from faildex.insight import warnings_for
    from faildex.normalize import shell_sig
    from faildex.store import open_store

    db = open_store(Path(__file__).parent.parent / "store")
    try:
        everyone = [row["id"] for row in db.execute("MATCH (s:Session) RETURN s.id AS id")]
        replayed = hook_rules(db, everyone, None)
        commands = [row["t"] for row in db.execute("MATCH (k:Command) RETURN k.template AS t")]
        assert len(commands) > 100 and len(replayed) >= 5  # not vacuous: rules exist
        for command in commands:
            hook = [f.sig for f in warnings_for(db, command) if shell_sig(f.sig) is None]
            assert [r.sig for r in replayed.get(command, [])] == hook, command  # same order
    finally:
        db.close()


def test_the_hook_replay_runs_per_agent_on_a_private_store():
    db = _replay_graph(sources=False)
    by_agent = {r.source: r for r in replay(db)}
    assert set(by_agent) == {"claude_code", "all"}
    assert (by_agent["claude_code"].warned, by_agent["claude_code"].came_true) == (2, 1)
    text = report(db)
    assert "Would the hook have spoken?" in text
    assert "The hook would have spoken before 2 of 3 later shell calls (66.7%)" in " ".join(
        text.split()
    )


def test_the_report_shows_the_replay_in_both_languages():
    from faildex import i18n

    text = report(_replay_graph())
    for line in (
        "later failures with a failure key",
        "in at least 3% of its runs (the hook speaks)",
        "1 succeeded, 1 failed with the failure it named, 0 ended another way.",
        "git push      rejected",
        "2 of 9 runs, 2 sessions",
        "Limits: only the stored first program of each line is looked up",
    ):
        assert line in text or line in " ".join(text.split()), line
    i18n.use("ko", "option")
    try:
        text = report(_replay_graph())
    finally:
        i18n.use("en", "default")
    assert "훅이 말했을까?" in text and "실패 2회 / 실행 9회, 2세션" in text and "한계:" in text


def _ordering_records():
    """Earlier: A and B fail `make` in 4 sessions, never fixed; Z fails in 3 and is fixed
    by a retry each time, so the hook ranks Z first (score 3 x 2) and then A (4 x 1)."""
    earlier = []
    for n in range(1, 5):
        earlier += [
            _call(f"e{n}", n, 0, command="make"),
            _call(f"e{n}", n, 1, ok=False, command="make", sig="a-fail"),
            _call(f"e{n}", n, 2, ok=False, command="make", sig="b-fail"),
        ]
    for n in range(5, 8):
        earlier += [
            _call(f"e{n}", n, 0, ok=False, command="make", sig="z-fail"),
            _call(f"e{n}", n, 1, command="make"),
        ]
    later = [
        _call("l1", 8, 0, ok=False, command="make", sig="z-fail"),
        _call("l2", 9, 0, ok=False, command="make", sig="b-fail"),
        _call("l3", 10, 0, command="make"),
    ]
    return earlier, later


CUT = "2026-01-08T00:00:00Z"  # the start of the first later session in these graphs


def _hook_said(earlier_records, command):
    """What the real hook says before `command`, run on a store of the earlier period only:
    the calls of earlier sessions made before the cut, linked the way ingest links them."""
    import json

    from faildex.hook import _lookup
    from faildex.schema import utc

    only_earlier = relate.connect(":memory:")
    ingest(only_earlier, [r for r in earlier_records if utc(r.ts) < CUT])
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    _, items = _lookup(only_earlier, json.loads(json.dumps(payload)), 2)
    return [item.sig for item in items]


def test_the_replay_warns_what_the_hook_would_have_said_in_the_same_order():
    """The hook run on a store of the earlier period alone gives the replay's warnings."""
    from faildex.insight import warnings_for

    earlier, later = _ordering_records()
    only_earlier = relate.connect(":memory:")
    ingest(only_earlier, earlier)
    hook = [f.sig for f in warnings_for(only_earlier, "make")]
    assert hook == ["z-fail", "a-fail", "b-fail"]
    assert _hook_said(earlier, "make") == ["z-fail", "a-fail"]  # the hook's cap of 2

    db = _no_sources(earlier + later)
    mine = replay(db)[0]
    by_sig = {o.rule.sig: o for o in mine.rules}
    assert [o.rule.sig for o in mine.rules] == hook
    assert [o.rule.sig for o in mine.rules if o.warned] == _hook_said(earlier, "make")
    # At most two warnings: Z and A. The later Z failure came true; B was past the cap.
    assert (by_sig["z-fail"].warned, by_sig["z-fail"].came_true) == (3, 1)
    assert (by_sig["b-fail"].warned, by_sig["b-fail"].runs) == (0, 3)
    assert dict(zip(STAGES, mine.funnel))["rate"] == 2
    assert dict(zip(STAGES, mine.funnel))["cap"] == 1
    text = " ".join(report(db).split())
    assert "Rules whose command came up but which stayed past the first 2 warnings: 1" in text


def test_the_replay_counts_local_codex_shell_calls():
    """Local Codex logs record every shell command as the tool `exec`."""
    from faildex.adapters import codex_local

    def exec_call(session, day, ok=True, sig=None):
        return CallRecord(
            agent="codex",
            session_id=session,
            seq=0,
            tool=codex_local.TOOL,
            ok=ok,
            ts=f"2026-01-{day:02d}T00:00:00Z",
            command="cargo test",
            error_sig=sig,
        )

    records = [
        exec_call("c1", 1, ok=False, sig="linker"),
        exec_call("c2", 2, ok=False, sig="linker"),
    ]
    records += [exec_call(f"c{n}", n) for n in range(3, 8)]
    records += [
        exec_call("c8", 8, ok=False, sig="linker"),
        exec_call("c9", 9),
        exec_call("c10", 10),
    ]
    codex = replay(_no_sources(records))[0]
    assert codex.source == "codex"
    assert (codex.shell_calls, codex.warned, codex.came_true) == (3, 3, 1)


def test_a_private_store_is_not_said_to_hold_no_warnings():
    text = " ".join(report(_replay_graph(sources=False)).split())
    assert "Nobody was warned in these logs" not in text
    assert "a warning the hook really gave is not in the store" in text
    assert "Nobody was warned in these logs" in " ".join(report(_replay_graph()).split())


def test_a_call_from_after_the_cut_inside_an_earlier_session_is_not_known():
    """Results arrive out of order in parallel calls: a call logged between a failure and
    its retry can be dated after the cut. The hook, knowing only what came before the cut,
    sees the retry right after the failure; so must the replay."""
    earlier, later = _ordering_records()
    stray = []
    for n in range(5, 8):  # Z's sessions: failure, a stray call after the cut, the retry
        stray += [
            _call(f"e{n}", n, 0, ok=False, command="make", sig="z-fail"),
            _call(f"e{n}", 9, 1, command=f"fix{n}"),
            _call(f"e{n}", n, 2, command="make"),
        ]
    earlier = [r for r in earlier if r.session_id not in {"e5", "e6", "e7"}] + stray
    said = _hook_said(earlier, "make")
    assert said == ["z-fail", "a-fail"]
    mine = replay(_no_sources(earlier + later))[0]
    assert [o.rule.sig for o in mine.rules if o.warned] == said
    assert {o.rule.sig: o.came_true for o in mine.rules}["z-fail"] == 1


def test_a_lookup_limited_to_every_session_is_the_hooks_own_lookup():
    """With every session and no cut, the replay's lookup (recoveries counted on rebuilt
    chains) gives the very failures, counts and recoveries the hook reads from Cypher."""
    from pathlib import Path

    from faildex.insight import failures
    from faildex.store import open_store

    def fields(found):
        return {
            sig: (f.kind, f.calls, sorted(f.sessions), f.commands, f.tools, f.fixes, f.recovered)
            for sig, f in found.items()
        }

    db = open_store(Path(__file__).parent.parent / "store")
    try:
        everyone = [row["id"] for row in db.execute("MATCH (s:Session) RETURN s.id AS id")]
        commands = [row["t"] for row in db.execute("MATCH (k:Command) RETURN k.template AS t")]
        recovered = 0
        for command in commands:
            hook = failures(db, command)
            assert fields(failures(db, command, everyone, None)) == fields(hook), command
            recovered += sum(f.recovered for f in hook.values())
        assert recovered > 50  # not vacuous: recoveries are compared
    finally:
        db.close()
