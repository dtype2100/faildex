"""Counts over time, for a before/after comparison on your own store.

`faildex report --split 2026-11-17 --key "not found"` shows, before and after
a date, how many calls ran, how many failed, and how many failed with a key
containing the given text. With `--hook-log` it also counts the warnings the
hook gave. It is an observation of one person's logs, not a controlled test:
the two periods differ in more than the rule that was added.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_CALLS = """
MATCH (s:Session)-[:HAS_CALL]->(c:Call)
WHERE c.ts IS NOT NULL
OPTIONAL MATCH (c)-[:FAILED_WITH]->(e:ErrorSig)
RETURN s.agent AS agent, s.id AS session, substring(c.ts, 0, 10) AS day, c.ok AS ok, e.sig AS sig
"""

_UNDATED = "MATCH (c:Call) WHERE c.ts IS NULL RETURN count(c) AS n"

_SHARED = """
MATCH (a:Session)-[:HAS_CALL]->(:Call)-[:FAILED_WITH]->(e:ErrorSig)
WITH e, collect(DISTINCT a.agent) AS agents
WHERE size(agents) > 1
RETURN count(e) AS n
"""


@dataclass
class Period:
    name: str
    days: set
    sessions: set
    calls: int = 0
    failed: int = 0
    matched: int = 0
    warnings: int = 0

    def rate(self, count: int) -> str:
        return f"{1000 * count / self.calls:.1f}" if self.calls else "n/a"


def hook_warnings(path: Path | None) -> Counter:
    """Warnings per day from the hook's log; lines that do not parse are skipped."""
    days: Counter = Counter()
    if path is None or not path.is_file():
        return days
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        ts = entry.get("ts") if isinstance(entry, dict) else None
        if isinstance(ts, str):
            days[ts[:10]] += 1
    return days


def periods(db, split: str | None, key: str | None, hook_log: Path | None = None) -> list[Period]:
    """One period for everything, or two around `split` (a YYYY-MM-DD day)."""
    names = ["all"] if not split else [f"before {split}", f"from {split}"]
    found = [Period(name, set(), set()) for name in names]
    needle = key.lower() if key else None

    def pick(day: str) -> Period:
        return found[0] if not split or day < split else found[1]

    for row in db.execute(_CALLS):
        period = pick(row["day"])
        period.days.add(row["day"])
        period.sessions.add(row["session"])
        period.calls += 1
        if not row["ok"]:
            period.failed += 1
            if needle and row["sig"] and needle in row["sig"]:
                period.matched += 1
    for day, count in hook_warnings(hook_log).items():
        pick(day).warnings += count
    return found


def agents(db) -> dict[str, tuple[int, int, int]]:
    """Per agent: sessions, calls, failed calls."""
    sessions: dict[str, set] = {}
    calls: Counter = Counter()
    failed: Counter = Counter()
    for row in db.execute(_CALLS):
        sessions.setdefault(row["agent"], set()).add(row["session"])
        calls[row["agent"]] += 1
        failed[row["agent"]] += 0 if row["ok"] else 1
    return {a: (len(sessions[a]), calls[a], failed[a]) for a in sorted(sessions)}


def _period_name(name: str) -> str:
    from faildex.i18n import t

    if name == "all":
        return t("report.period.all")
    when, _, day = name.partition(" ")
    return t(f"report.period.{when}", day=day)


def render(db, split: str | None, key: str | None, hook_log: Path | None = None) -> str:
    from faildex.i18n import pad, t

    lines = [
        pad(t("report.col.agent"), 14)
        + pad(t("report.col.sessions"), 10, ">")
        + pad(t("report.col.calls"), 10, ">")
        + pad(t("report.col.failed"), 10, ">")
    ]
    for agent, (sessions, calls, failed) in agents(db).items():
        lines.append(f"{agent:<14}{sessions:>10,}{calls:>10,}{failed:>10,}")
    shared = next(iter(db.execute(_SHARED)))["n"]
    lines += [t("report.shared", count=shared), ""]

    per_1000 = t("report.col.per_1000")
    head = (
        pad(t("report.col.period"), 20)
        + pad(t("report.col.days"), 6, ">")
        + pad(t("report.col.sessions"), 10, ">")
        + pad(t("report.col.calls"), 9, ">")
        + pad(t("report.col.failed"), 8, ">")
        + pad(per_1000, 10, ">")
    )
    if key:  # the matched column means nothing without --key
        head += "  " + pad(t("report.col.matched", key=key), 30, ">") + pad(per_1000, 10, ">")
    with_log = hook_log is not None
    lines.append(head + (pad(t("report.col.hook"), 15, ">") if with_log else ""))
    for p in periods(db, split, key, hook_log):
        row = (
            f"{pad(_period_name(p.name), 20)}{len(p.days):>6}{len(p.sessions):>10,}"
            f"{p.calls:>9,}{p.failed:>8,}{p.rate(p.failed):>10}"
        )
        if key:
            row += f"  {p.matched:>30,}{p.rate(p.matched):>10}"
        lines.append(row + (f"{p.warnings:>15,}" if with_log else ""))
    lines.append(t("report.legend"))
    undated = next(iter(db.execute(_UNDATED)))["n"]
    if undated:
        lines.append(t("report.undated", count=f"{undated:,}"))
    if split:
        lines.append(t("report.both_sides"))
    return "\n".join(lines)
