"""Controlled bench for the pre-run hook: the same tasks with the hook off and on.

The same tasks run headless in Claude Code under two conditions:

    off      no faildex hook (user settings are not loaded at all)
    on       the `PreToolUse` hook of a faildex checkout

Each run gets a fresh folder, a settings file of its own and a hook log of its
own. The hook reads a bench store: the public store that ships in `store/`
plus the two synthetic sessions in `bench/seed/`, copied into the output folder.
Nothing outside the output folder is written.

    uv run python bench/run.py run --out DIR --hook PATH [--reps 5]
    uv run python bench/run.py summarize DIR/runs.jsonl
    uv run python bench/run.py rescore DIR      # score saved runs again after a change

PATH is the `faildex` executable of the checkout whose hook is measured.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from tasks import TASKS

CONDITIONS = ("off", "on")
TOOLS = "Bash,Read,Glob,Grep"
# Variables of the calling Claude Code session; a bench run must not inherit them.
# `GIT_*` too (Claude Code gives its own shell `GIT_EDITOR=true`): the hook asks git
# in its own environment, so every run starts without the caller's git settings.
_PARENT_ENV = re.compile(
    r"^(CLAUDECODE|CLAUDE_CODE_.*|CLAUDE_PID|CLAUDE_EFFORT|AI_AGENT|GIT_.*)$", re.IGNORECASE
)


def prepare_store(out: Path) -> Path:
    import relate

    from faildex.adapters.claude_code import read_dir
    from faildex.schema import ingest

    store = out / "store"
    if store.exists():
        shutil.rmtree(store)
    shutil.copytree(HERE.parent / "store", store)
    db = relate.connect(str(store))
    ingest(db, read_dir(HERE / "seed"), local_paths=True)
    db.commit()
    db.flush()
    db.close()
    return store


def settings(condition: str, faildex: dict[str, str], store: Path, log: Path) -> dict:
    if condition == "off":
        return {}
    # The hook runs through a shell: quote every part, so a path with a space stays one.
    command = shlex.join([faildex[condition], "hook", "--store", str(store), "--log", str(log)])
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": command, "timeout": 5}],
                }
            ]
        }
    }


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not _PARENT_ENV.match(k)}
    env["LANG"] = env["LC_ALL"] = "en_US.UTF-8"  # tools print their English messages
    return env


def run_one(job: dict) -> dict:
    task = next(t for t in TASKS if t["id"] == job["task"])
    home = Path(job["dir"])
    if home.exists():
        shutil.rmtree(home)
    work = home / "work"
    work.mkdir(parents=True)
    task["setup"](work)
    log = home / "hook.jsonl"
    config = home / "settings.json"
    config.write_text(json.dumps(settings(job["condition"], job["faildex"], job["store"], log)))
    stream = home / "stream.jsonl"
    command = [
        "claude", "-p", task["prompt"],
        "--model", job["model"],
        "--output-format", "stream-json", "--verbose", "--include-hook-events",
        "--setting-sources", "project,local",
        "--strict-mcp-config",
        "--settings", str(config),
        "--no-session-persistence",
        "--tools", TOOLS, "--allowed-tools", TOOLS,
    ]  # fmt: skip
    started = time.monotonic()
    with stream.open("w") as out, (home / "stderr.txt").open("w") as err:
        try:
            code = subprocess.run(
                command, cwd=work, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                env=_env(), timeout=job["timeout"], check=False,
            ).returncode  # fmt: skip
        except subprocess.TimeoutExpired:
            code = "timeout"
    seconds = round(time.monotonic() - started, 1)
    return {**score(task, work, stream, log, home), "exit": code, "seconds": seconds,
            "condition": job["condition"], "task": job["task"], "rep": job["rep"],
            "model": job["model"]}  # fmt: skip


def _scrub(text: str, home: Path) -> str:
    text = text.replace(str(home / "work"), ".").replace(str(home), "<run>")
    text = re.sub(r"/(?:Users|home)/[^/\s'\"]+", "~", text)
    return re.sub(r"/private/tmp/[^\s'\"]*|/tmp/[^\s'\"]*", "<tmp>", text)


def score(task: dict, work: Path, stream: Path, log: Path, home: Path) -> dict:
    """What one run did, read from its stream with faildex's own Claude Code adapter."""
    from faildex.adapters.claude_code import read_session
    from faildex.normalize import error_signature, shell_sig

    records = [r for r in read_session(stream) if r.tool == "Bash"]
    uses, outputs, texts, answer, pre_hooks, cost, turns = {}, [], [], "", 0, None, None
    for line in stream.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("type")
        content = (event.get("message") or {}).get("content")
        if kind == "assistant" and isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_use" and block.get("name") == "Bash":
                    uses[block.get("id")] = str((block.get("input") or {}).get("command"))
        elif kind == "user" and isinstance(content, list):
            for block in content:
                if block.get("type") != "tool_result" or block.get("tool_use_id") not in uses:
                    continue
                body = block.get("content")
                if isinstance(body, list):
                    body = "\n".join(str(b.get("text", "")) for b in body if isinstance(b, dict))
                texts.append(str(body))
                if not block.get("is_error"):
                    outputs.append(str(body))
        elif kind == "system" and event.get("subtype") == "hook_started":
            pre_hooks += event.get("hook_event") == "PreToolUse"
        elif kind == "result":
            answer = str(event.get("result") or "")
            cost, turns = event.get("total_cost_usd"), event.get("num_turns")
    sigs = [r.error_sig or "" for r in records if not r.ok]

    def named(text: str) -> int:
        """How many times the output shows the task's failure, whether or not the exit
        code did: agents often pipe into `head` or append `2>&1; echo`, which hides it,
        and one call can run several commands that each fail."""
        found = 0
        for raw in text.splitlines():
            sig = error_signature(raw) or ""
            sig = shell_sig(sig) or sig
            found += any(sig.startswith(t) for t in task["targets"])
        return found

    hits = sum(named(text) for text in texts)
    calls_hit = sum(bool(named(text)) for text in texts)
    spoke = len(log.read_text().splitlines()) if log.exists() else 0
    return {
        "bash_calls": len(records),
        "failed_calls": len(sigs),
        "target_failures": hits,
        "target_calls": calls_hit,  # more than 1: the failure came back in a later call
        "target_hit": bool(hits),
        "spoke": spoke,
        "pre_tool_hooks": pre_hooks,
        "success": bool(task["success"](work, answer, outputs)),
        "cost_usd": cost,
        "turns": turns,
        "failures": sigs,
        "commands": [_scrub(c, home) for c in uses.values()],
    }


def run(args: argparse.Namespace) -> int:
    out = args.out.resolve()
    if any((d / ".git").exists() for d in (out, *out.parents)):
        sys.exit(f"{out} is inside a git repository; the tasks need a folder outside one")
    out.mkdir(parents=True, exist_ok=True)
    store = prepare_store(out)
    # The hook runs in each task's folder, so a relative path would not find it.
    faildex = {"on": str(args.hook.resolve())}
    for path in faildex.values():
        if not Path(path).is_file():
            sys.exit(f"{path} is not a faildex executable")
    tasks = [t["id"] for t in TASKS if not args.tasks or t["id"] in args.tasks]
    conditions = args.conditions.split(",")
    # Conditions are interleaved so that time of day and service load fall on both.
    jobs = [
        {"condition": c, "task": t, "rep": r, "model": args.model, "faildex": faildex,
         "store": store, "timeout": args.timeout, "dir": str(out / "runs" / c / t / str(r))}
        for r in range(args.reps) for t in tasks for c in conditions
    ]  # fmt: skip
    results = out / "runs.jsonl"
    with ThreadPoolExecutor(args.jobs) as pool, results.open("a") as sink:
        for n, row in enumerate(pool.map(run_one, jobs), start=1):
            sink.write(json.dumps(row) + "\n")
            sink.flush()
            print(f"{n}/{len(jobs)} {row['condition']:6} {row['task']:16} rep {row['rep']} "
                  f"hit={row['target_hit']} spoke={row['spoke']} ok={row['success']} "
                  f"{row['seconds']}s", flush=True)  # fmt: skip
    print(summarize_rows([json.loads(x) for x in results.read_text().splitlines()]))
    return 0


def rescore(out: Path) -> int:
    """Score the saved runs of an earlier `run` again, keeping their times and exits."""
    results = out / "runs.jsonl"
    rows = [json.loads(line) for line in results.read_text().splitlines()]
    again = []
    for row in rows:
        task = next(t for t in TASKS if t["id"] == row["task"])
        home = out / "runs" / row["condition"] / row["task"] / str(row["rep"])
        scored = score(task, home / "work", home / "stream.jsonl", home / "hook.jsonl", home)
        again.append({**row, **scored})
    results.write_text("".join(json.dumps(row) + "\n" for row in again))
    print(summarize_rows(again))
    return 0


def summarize_rows(rows: list[dict]) -> str:
    cells: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        cells[(row["task"], row["condition"])].append(row)
    conditions = [c for c in CONDITIONS if any(k[1] == c for k in cells)]
    tasks = list(dict.fromkeys(row["task"] for row in rows))

    def cell(group: list[dict]) -> str:
        n = len(group)
        hit = sum(r["target_hit"] for r in group)
        return (
            f"{hit}/{n} | {sum(r['failed_calls'] for r in group)} | "
            f"{sum(r['spoke'] for r in group)} | {sum(r['success'] for r in group)}/{n}"
        )

    head = "| Task | " + " | ".join(
        f"{c}: runs with the failure | failed calls | hook spoke | succeeded" for c in conditions
    )
    lines = [head + " |", "|---" * (1 + 4 * len(conditions)) + "|"]
    for task in tasks:
        lines.append(f"| {task} | " + " | ".join(cell(cells[(task, c)]) for c in conditions) + " |")
    every = {c: [r for r in rows if r["condition"] == c] for c in conditions}
    lines.append("| all | " + " | ".join(cell(every[c]) for c in conditions) + " |")
    cost = sum(r["cost_usd"] or 0 for r in rows)
    seconds = sum(r["seconds"] for r in rows)
    models = sorted({r["model"] for r in rows})
    hooks_off = sum(r["pre_tool_hooks"] for r in rows if r["condition"] == "off")
    lines += [
        "",
        (
            f"runs: {len(rows)}, model: {', '.join(models)}, agent time: {seconds / 60:.0f} min, "
            f"reported cost: ${cost:.2f}, PreToolUse hook runs in 'off' runs: {hooks_off}"
        ),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    go = sub.add_parser("run")
    go.add_argument("--out", type=Path, required=True)
    go.add_argument("--hook", type=Path, required=True, help="faildex executable of the hook")
    go.add_argument("--reps", type=int, default=5)
    go.add_argument("--model", default="claude-haiku-5-5")
    go.add_argument("--jobs", type=int, default=6)
    go.add_argument("--timeout", type=int, default=300)
    go.add_argument("--conditions", default=",".join(CONDITIONS))
    go.add_argument("--tasks", nargs="*")
    report = sub.add_parser("summarize")
    report.add_argument("runs", type=Path)
    again = sub.add_parser("rescore", help="score the saved runs of an output folder again")
    again.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    if args.cmd == "run":
        return run(args)
    if args.cmd == "rescore":
        return rescore(args.out)
    print(summarize_rows([json.loads(x) for x in args.runs.read_text().splitlines()]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
