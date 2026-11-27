"""The numbers in the documents are the numbers `make eval` prints."""

from pathlib import Path

import pytest

from faildex.evaluate import evaluate
from faildex.store import open_store

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def results(public_copy):
    db = open_store(public_copy)
    try:
        return evaluate(db)[-1], evaluate(db, kinds=("text",))[-1]
    finally:
        db.close()


def _row(result) -> str:
    return (
        f"| {result.later_failures} | {result.recurring} ({result.recurrence:.1%}) "
        f"| {result.warnable} ({result.warnable_share:.1%}) |"
    )


def test_readme_table_matches_the_committed_store(results):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    both, text_only = results
    assert f"| All failure keys {_row(both)}" in readme
    assert f"| Failure text only {_row(text_only)}" in readme
    assert f"{both.recurrence:.0%} of the failures" in readme
    assert f"same {both.recurring} of {both.later_failures}" in readme


def test_evaluation_doc_matches_the_committed_store(results):
    doc = (ROOT / "docs" / "evaluation.md").read_text(encoding="utf-8")
    both, _ = results
    assert f"| All | {both.earlier_sessions} / {both.later_sessions} {_row(both)}" in doc
    assert f"{len(both.later_keys)} distinct failure keys" in doc
    assert f"same {both.recurring} of {both.later_failures}" in doc


def test_relate_webassembly_reaches_the_same_numbers(results, tmp_path):
    """The browser demo recomputes the evaluation in another build of the engine."""
    import json
    import shutil
    import subprocess

    site = ROOT / "site"
    if not shutil.which("node") or not (site / "vendor" / "relate_bg.wasm").is_file():
        pytest.skip("run `make site` first (needs Node)")
    if not (site / "data.json").is_file():
        pytest.skip("run `make site` first")
    out = subprocess.run(
        ["node", str(site / "check.mjs")], capture_output=True, text=True, check=True, timeout=120
    )
    total = json.loads(out.stdout)["scores"][-1]
    both, _ = results
    assert (total["failures"], total["recurring"], total["warnable"]) == (
        both.later_failures,
        both.recurring,
        both.warnable,
    )


def test_every_test_named_in_the_evaluation_doc_exists():
    import re

    doc = (ROOT / "docs" / "evaluation.md").read_text(encoding="utf-8")
    named = re.findall(r"`(test_\w+\.py)::(test_\w+)`", doc)
    assert len(named) >= 12
    for file, function in named:
        assert f"def {function}(" in (ROOT / "tests" / file).read_text(encoding="utf-8"), (
            f"{file}::{function}"
        )


# The hook replay ("Would the hook have spoken?")


def _flat(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture(scope="module")
def replayed(public_copy):
    from faildex.evaluate import replay

    db = open_store(public_copy)
    try:
        return replay(db)[-1]
    finally:
        db.close()


def test_the_hook_replay_in_the_documents_matches_the_committed_store(replayed):
    from faildex.evaluate import STAGES

    r = replayed
    funnel = dict(zip(STAGES, r.funnel))
    doc = _flat((ROOT / "docs" / "evaluation.md").read_text(encoding="utf-8"))
    for row in (
        f"| Later-period failures with a key | {funnel['failure']} |",
        f"| made by a shell call | {funnel['shell']} |",
        f"| on a line with a stored command | {funnel['named']} |",
        f"| whose key the earlier period held | {funnel['known']} |",
        f"| held for that same command | {funnel['command']} |",
        f"| in 2 or more sessions | {funnel['sessions']} |",
        f"(the hook speaks) | {funnel['rate']} |",
        (
            f"before {r.warned} of the {r.shell_calls:,} later shell calls "
            f"({r.warned / r.shell_calls:.1%})"
        ),
        (
            f"{r.warned_ok} of those calls succeeded, {r.came_true} failed with the failure it "
            f"named, and {r.other} ended another way"
        ),
        f"{funnel['shell'] - funnel['named']} of the {funnel['shell']} shell failures",
    ):
        assert row in doc, row
    assert funnel["cap"] == funnel["rate"]  # the 2-warning cap loses nothing here
    spoke = [o for o in r.rules if o.warned]
    lines = (ROOT / "docs" / "evaluation.md").read_text(encoding="utf-8").splitlines()
    table = [line for line in lines if line.startswith("| `") and " runs, " in line]
    assert len(table) == len(spoke)
    for o in spoke:
        earlier = f"| {o.rule.calls} of {o.rule.runs} runs, {o.rule.sessions} sessions |"
        [row] = [x for x in table if x.startswith(f"| `{o.rule.command}` |") and earlier in x]
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        named, warned, came_true = cells[1], cells[-2], cells[-1]
        assert came_true == str(o.came_true), row
        assert warned in (str(o.warned), f"(same {o.warned})"), row
        shown = named.split("`")[1].removesuffix(" ...").removesuffix("...")
        assert o.rule.sig.startswith(shown) and len(shown) >= 15, row
    readme = _flat((ROOT / "README.md").read_text(encoding="utf-8"))
    assert (
        f"before {r.warned} of the {r.shell_calls:,} later shell calls "
        f"({r.warned / r.shell_calls:.1%}), and {r.came_true} of those calls" in readme
    )
    assert f"{r.came_true} of the {funnel['failure']}." in readme
    ko = _flat((ROOT / "README.ko.md").read_text(encoding="utf-8"))
    assert f"셸 호출 {r.shell_calls:,}개 중 {r.warned}개({r.warned / r.shell_calls:.1%})" in ko
    assert f"실패 {funnel['failure']}개 중 {r.came_true}개" in ko


def test_the_replay_claims_about_cuts_and_recoveries_hold(replayed, monkeypatch, public_copy):
    from faildex import evaluate as ev
    from faildex.normalize import shell_sig

    r = replayed
    doc = _flat((ROOT / "docs" / "evaluation.md").read_text(encoding="utf-8"))
    readme = _flat((ROOT / "README.md").read_text(encoding="utf-8"))
    ko = _flat((ROOT / "README.ko.md").read_text(encoding="utf-8"))
    # "Nine of the ten are in one session. Without that session the count is 1."
    assert (r.came_true, len(r.came_true_sessions), r.came_true_sessions[0]) == (10, 2, 9)
    assert "Nine of the ten are in one session. Without that session the count is 1." in doc
    assert "Nine of the ten are in one session" in readme and "10개 중 9개가 한 세션" in ko

    db = open_store(public_copy)
    try:
        counts, recurrence = {}, []
        for share in (0.5, 0.6, 0.7, 0.8, 0.9):
            monkeypatch.setattr(ev, "EARLIER_SHARE", share)
            counts[share] = ev.replay(db)[-1].came_true
            recurrence.append(ev.evaluate(db)[-1].recurrence)
        monkeypatch.setattr(ev, "EARLIER_SHARE", 0.7)
        quoted = ", ".join(str(counts[s]) for s in (0.5, 0.6, 0.8))
        assert f"the count is {quoted} or {counts[0.9]}." in doc
        assert 0.66 <= min(recurrence) and max(recurrence) < 0.71
        assert "stays between 66% and 71%" in doc
        low, high = min(counts.values()), max(counts.values())
        assert f"between {low} and {high}" in readme and f"{low}~{high}개" in ko

        # None of the 48 with a recovery on record was warned: 43 under 3%, 5 in one session.
        stages = dict(ev.replay(db)[-1].stages)
        warnable, untold = [], set()
        for name in [row["name"] for row in db.execute(ev._SOURCES)]:
            rows = db.execute(ev._SESSIONS, {"source": name})
            earlier, later, cut = ev.split([(row["id"], row["started"]) for row in rows])
            params = {"earlier": earlier, "cut": cut}
            known = {row["sig"] for row in db.execute(ev._EARLIER_KEYS, params)}
            recovered = {(row["sig"], row["command"]) for row in db.execute(ev._RECOVERED, params)}
            warnable += [
                row["call"]
                for row in db.execute(ev._LATER, {"later": later})
                if row["kind"] in ("text", "exit")
                and row["sig"] in known
                and not row["compound"]
                and (row["sig"], row["command"]) in recovered
            ]
            for found in ev.hook_rules(db, earlier, cut).values():
                untold |= {(x.sig, x.command) for x in found if (x.sig, x.command) not in recovered}
        where = [stages[call] for call in warnable]
        assert (len(where), where.count("sessions"), where.count("command")) == (48, 43, 5)
        assert "None of the 48 failures with a recovery on record would have been warned: 43" in doc
        assert "None of the 48 failures with a recovery on record would have been warned" in readme
        assert "복구 기록이 있는 48개 중 훅이 경고했을 것은 없습니다" in ko
        # The rules that came true had no recovery on record in the earlier period.
        assert all((o.rule.sig, o.rule.command) in untold for o in r.rules if o.came_true)
        # No zsh glob or `=` failure in the public logs.
        sigs = [row["sig"] for row in db.execute("MATCH (e:ErrorSig) RETURN e.sig AS sig")]
        assert not any(shell_sig(sig) for sig in sigs)
    finally:
        db.close()


# The controlled bench ("Controlled bench")


def test_the_bench_table_in_the_documents_is_the_committed_runs():
    import importlib.util
    import json

    spec = importlib.util.spec_from_file_location("bench_run", ROOT / "bench" / "run.py")
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    runs = ROOT / "bench" / "results" / "runs.jsonl"
    rows = [json.loads(line) for line in runs.read_text(encoding="utf-8").splitlines()]
    table = bench.summarize_rows(rows)
    assert (ROOT / "bench" / "results" / "summary.md").read_text(encoding="utf-8").strip() == (
        table.strip()
    )
    doc = (ROOT / "docs" / "evaluation.md").read_text(encoding="utf-8")
    assert table.split("\n\n")[0] in doc

    def runs_with(condition, tasks=None):
        return [
            r for r in rows if r["condition"] == condition and (not tasks or r["task"] in tasks)
        ]

    # Each task and condition at least 5 times; one model; the hook absent where it should be.
    cells = {(r["task"], r["condition"]) for r in rows}
    assert all(sum(1 for r in rows if (r["task"], r["condition"]) == c) >= 5 for c in cells)
    assert len({r["model"] for r in rows}) == 1
    assert sum(r["pre_tool_hooks"] for r in runs_with("off")) == 0
    flat = _flat(doc)
    off, on = (runs_with(c) for c in ("off", "on"))
    assert {r["condition"] for r in rows} == {"off", "on"}
    hit = [sum(r["target_hit"] for r in group) for group in (off, on)]
    assert f"{hit[0]} of {len(off)} runs hit the failure with the hook off" in flat
    assert f"and {hit[1]} of {len(on)} with it on" in flat
    readme = _flat((ROOT / "README.md").read_text(encoding="utf-8"))
    ko = _flat((ROOT / "README.ko.md").read_text(encoding="utf-8"))
    assert hit[0] == hit[1] and f"{hit[0]} of {len(off)} runs either way" in readme
    assert f"어느 쪽이든 {len(off)}회 중 {hit[0]}회" in ko
    inside = {"changes-inside", "diff-inside"}
    spoke = sum(r["spoke"] for r in runs_with("on", inside))
    assert f"In the two tasks inside a repository it spoke {spoke} times" in flat
    assert f"warned before {spoke} calls" in readme and f"호출 {spoke}번 앞에서" in ko
    assert all(r["success"] for r in rows) and f"Every task was done in all {len(rows)}" in flat
    # The failure never came back in a later call; outside a repository it came every time.
    assert not any(r["target_calls"] > 1 for r in rows)
    assert "did the failure come back in a later call" in flat
    outside = [r for r in rows if r["task"] in ("changes-outside", "diff-outside")]
    assert all(r["target_hit"] for r in outside)
    zsh = [r for r in rows if r["task"] in ("banner", "cleanup", "count-py")]
    assert not any(r["target_hit"] for r in zsh)
    assert f"globs on its own in all {len(zsh)} runs" in flat
    assert f"{len(rows)} runs, {sum(r['seconds'] for r in rows) / 60:.0f} minutes" in flat
    # The published records name no home directory, temporary folder or e-mail address.
    text = runs.read_text(encoding="utf-8")
    assert not any(mark in text for mark in ("/Users/", "/home/", "/tmp/", "/var/folders", "@"))


def test_the_bench_quotes_the_hook_command(tmp_path):
    import importlib.util
    import shlex

    spec = importlib.util.spec_from_file_location("bench_run", ROOT / "bench" / "run.py")
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    exe = str(tmp_path / "faildex copy" / ".venv" / "bin" / "faildex")
    store, log = tmp_path / "bench run" / "store", tmp_path / "bench run" / "hook.jsonl"
    config = bench.settings("on", {"on": exe}, store, log)
    [entry] = config["hooks"]["PreToolUse"][0]["hooks"]
    assert shlex.split(entry["command"]) == [exe, "hook", "--store", str(store), "--log", str(log)]
    assert bench.settings("off", {"on": exe}, store, log) == {}
