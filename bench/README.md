# Controlled bench for the earlier hook that warned before a command

> **A record of a removed hook.** This bench measured faildex's earlier hook, which
> warned before a command (`PreToolUse`). That hook is gone: in this checkout,
> `faildex hook` stays silent on `PreToolUse` and speaks only right after a failed
> shell call (`PostToolUseFailure`), so running the bench here measures nothing. To run
> it again, check out the commit whose hook it measured, `03313cc`, build its
> environment there, and pass that checkout's `.venv/bin/faildex` as `--hook`.

The same tasks run headless in Claude Code with the faildex hook off and on, and
the runs are compared. Results and what they show are in
[docs/evaluation.md](../docs/evaluation.md#controlled-bench).

| File | What it is |
|---|---|
| `tasks.py` | The seven tasks: prompt, folder setup, the failure keys each is about, and the check for "done" |
| `seed/` | Two synthetic Claude Code sessions with the `git diff --no-index`, `=<word> not found` and glob failures, added to the bench store |
| `run.py` | Runs the tasks and scores each run; `summarize` prints the table |
| `results/runs.jsonl` | One line per run of the published bench: condition, task, counts, the shell commands (folder paths replaced) and the failure keys |
| `results/summary.md` | The table `run.py summarize` prints from `runs.jsonl` |

## Run it

You need Claude Code signed in and a faildex checkout with its environment:

```sh
uv sync
uv run python bench/run.py run --out "$TMPDIR/faildex-bench" --hook .venv/bin/faildex --reps 10
uv run python bench/run.py summarize "$TMPDIR/faildex-bench/runs.jsonl"
```

To measure the hook of another checkout, pass its `.venv/bin/faildex` as `--hook`.
The published runs used the hook of `origin/main` 03313cc.

After a change to the scoring, `uv run python bench/run.py rescore "$TMPDIR/faildex-bench"`
scores the saved runs again without running the agent.

`--out` must be outside any git repository, because some tasks need a folder
that is not one. Everything is written under it: the bench store, one folder per
run (task files, settings, stream, hook log) and `runs.jsonl`.

## What each run gets

- No user settings: `--setting-sources project,local`, so your own hooks,
  plugins and `CLAUDE.md` are not loaded, and `--strict-mcp-config`.
- Its own `--settings` file: `{}` for "off"; for "on", one `PreToolUse` hook
  running `faildex hook --store <bench store> --log <run>/hook.jsonl`.
- The tools Bash, Read, Glob and Grep, allowed without prompts.
- `LC_ALL=en_US.UTF-8`, so git prints the English messages the store knows.
- No `GIT_*` variable from the calling shell (Claude Code gives its own shell
  `GIT_EDITOR=true`), so every run starts without the caller's git settings.
  This was added after the published runs, which inherited `GIT_EDITOR=true`;
  the agent's own shell gets that value from Claude Code anyway.
- `--include-hook-events`, so the stream shows which hooks ran.

## How a run is scored

- **Had the failure**: the failure's text appears in any shell output, whatever
  the exit code (agents often pipe into `head`, which hides it). Lines are
  normalized with faildex's own `error_signature`.
- **Came back**: `target_calls` counts the shell calls whose output shows the
  failure; more than one means it came back in a later call.
- **Failed calls**: shell calls that ended with an error, read with faildex's
  Claude Code adapter.
- **Hook spoke**: lines in the run's hook log; the hook writes one per call it
  warned before (with up to two warnings in it).
- **Done**: the task's own check in `tasks.py`.

The model and the number of runs are recorded in every line of `runs.jsonl`.
Before committing new results, check that no line holds a home directory, a
temporary directory or an e-mail address; `run.py` replaces the run folder in
the commands it records.
