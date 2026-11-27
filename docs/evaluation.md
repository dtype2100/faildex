# Evaluation

Run `make eval`. It reads the committed store and prints the tables below. The
code is [`src/faildex/evaluate.py`](../src/faildex/evaluate.py); an independent
recount inside Relate WebAssembly (the browser demo, `site/graph.js`) gives the
same 80 of 117.

## Question

When an agent fails, had that failure already happened in an earlier session,
and did that session also record a way out?

## Method

1. Take the sessions of one dataset and order them by (start time, id).
2. The first 70% are the **earlier** period, the last 30% the **later** period.
   The cut is the start time of the first later session. An earlier session
   still running at the cut contributes only its calls before the cut.
3. A **failure key** is the normalized failure text. When a failed command
   printed nothing usable, the key is `<command> exited <code>`. Search tools
   that exit 1 for "no match" (`rg`, `grep`, `diff` and others) are not failures.
4. **Recurring**: a later-period failed call whose key was seen in the earlier period.
5. **Warnable**: a recurring failure where the earlier period also shows the
   same command failing with that key and then succeeding within five calls of
   the same session. Command lines that chain several programs are skipped on
   both sides, because the log does not say which part failed or succeeded.
   A call is dated by when its result arrived, and a success counts only if it
   arrived after the failure.
   "Warnable" means the graph held a recovery. It does not mean the hook's rule
   would fire: see [Would the hook have spoken?](#would-the-hook-have-spoken) below.

## Result

| Dataset | Sessions earlier / later | Later failures | Recurring | Warnable (of recurring) |
|---|---|---|---|---|
| codex-trajectories | 233 / 101 | 115 | 78 (67.8%) | 48 (61.5%) |
| wisp (Claude Code) | 61 / 27 | 2 | 2 | 0 |
| All | 294 / 128 | 117 | 80 (68.4%) | 48 (60.0%) |

With failure text only (no exit-code keys): 72 of 102 recurring (70.6%), 45 warnable.

36 distinct failure keys appear in the later period; 16 of them were seen earlier.

## Would the hook have spoken?

The table above asks what the graph knew. This asks what faildex's earlier hook,
which warned before a command, would have done with it. faildex no longer has that
hook: this section and the [controlled bench](#controlled-bench) are why (see
[notices right after a failure](#notices-right-after-a-failure-claude-code-posttoolusefailure)).
Knowledge is the earlier period only; the rule is that hook's own (a failure seen in 2 or more sessions and in at least 3% of that command's
runs, at most 2 warnings per call); it is replayed on every later-period shell
call. Nobody was warned in these logs, so this shows when the hook would have
spoken, not what an agent would have done next. `make eval` prints it below the
tables.

| Later-period failures with a key | 117 |
|---|---|
| made by a shell call | 116 |
| on a line with a stored command | 84 |
| whose key the earlier period held | 66 |
| held for that same command | 63 |
| in 2 or more sessions | 55 |
| and in at least 3% of that command's runs (the hook speaks) | 10 |

The hook would have spoken before 206 of the 5,070 later shell calls (4.1%).
188 of those calls succeeded, 10 failed with the failure it named, and 8 ended
another way.

| Command | Failure the warning named | Earlier period | Warned later | Came true |
|---|---|---|---|---|
| `git diff` | `usage: git diff --no-index [] [...]` | 3 of 11 runs, 3 sessions | 93 | 0 |
| `git status` | `fatal: not a git repository ...` | 25 of 71 runs, 24 sessions | 90 | 0 |
| `Format-Hex` | `format-hex : a parameter cannot be found ...` | 2 of 2 runs, 2 sessions | 13 | 8 |
| `New-Item` | `New-Item exited 1` (no usable output) | 2 of 34 runs, 2 sessions | 10 | 2 |
| `New-Item` | `command timed out after <n> milliseconds` | 3 of 34 runs, 2 sessions | (same 10) | 0 |

Read this as a description of these logs, not as a rate. `make eval` prints the
70% split above; the other cuts and the overlap with recoveries below are
recomputed from the committed store by `tests/test_docs.py`.

- Nine of the ten are in one session. Without that session the count is 1.
- With the cut at 50%, 60%, 80% or 90% instead of 70%, the count is 0, 22, 10
  or 15. The recurrence above stays between 66% and 71% over the same cuts.
- None of the 48 failures with a recovery on record would have been warned: 43
  are under 3% of their command's runs and 5 were seen in one earlier session.
  The ten that came true were all warned with "no recovery on record".
- 32 of the 116 shell failures are on lines with no stored command, mostly
  PowerShell lines such as `$x = ...` and `& { ... }`, so there is nothing to
  look up.
- The public logs hold no zsh glob or `=` failure, so the hook's two shell-level
  rules never fire here and are not measured. They are decided on the raw
  command line, which the store does not keep, so on a private store the replay
  can miss warnings the hook gave.
- Only the stored first program of each line is looked up; the hook itself also
  reads the later parts of a line.

A next step to measure, not built: warning only when the same command has just
failed in the same session.

## Controlled bench

The replay says when the earlier hook would have spoken; it cannot say what an
agent does after a warning. This bench runs the same tasks in Claude Code with
that hook, which warned before a command, off and on (the hook of `origin/main`
03313cc; faildex no longer has it). It is a small controlled
experiment on one model and seven made-up tasks, not a measure of faildex in
general. The code, the tasks and every run's record are in
[`bench/`](../bench/).

- **Tasks.** Seven, each in a fresh folder under a temporary directory: summarize
  uncommitted changes, and show what changed in `config.ini` since the last
  commit, once in a folder that is not a git repository and once in one that is;
  print file names between `==========` lines; delete `.log` and `.tmp` files
  when there are no `.log` files; count `.py` files in subfolders. The prompts
  give no hint about the failure.
- **Runs.** `claude -p` with `--output-format stream-json`, model
  `claude-haiku-5-5` (Claude Code 2.1.332), 10 runs per task and condition, 140 in
  all, the two conditions interleaved. Each run loads no user settings
  (`--setting-sources project,local`) and gets its own `--settings` file with the
  hook or none; the hook events in each stream confirm that no `PreToolUse` hook
  ran in the 70 runs without one. Tools print English messages
  (`LC_ALL=en_US.UTF-8`).
- **Store.** The hook reads a copy of the committed store plus two synthetic
  sessions in `bench/seed/` that hold the `git diff --no-index`, `=<word> not
  found` and glob failures, so that the hook knows all four failures the tasks
  are about.
- **Measures.** A run counts as having the failure when the failure's text
  appears in any shell output, whatever the exit code: the agents often ran
  `git status 2>&1 | head`, which hides it. Also counted: shell calls that ended
  with an error, calls the hook warned before (its own log), and whether the
  task got done (a check per task in `bench/tasks.py`).

Each cell: runs with the failure, failed shell calls, calls the hook warned
before, tasks done. "Failed shell calls" stays at 0 because the agents hid exit
codes behind pipes and `; echo`; the failure text is what counts.

| Task | off: runs with the failure | failed calls | hook spoke | succeeded | on: runs with the failure | failed calls | hook spoke | succeeded |
|---|---|---|---|---|---|---|---|---|
| changes-outside | 10/10 | 0 | 0 | 10/10 | 10/10 | 0 | 10 | 10/10 |
| diff-outside | 10/10 | 0 | 0 | 10/10 | 10/10 | 0 | 1 | 10/10 |
| changes-inside | 0/10 | 0 | 0 | 10/10 | 0/10 | 0 | 10 | 10/10 |
| diff-inside | 0/10 | 0 | 0 | 10/10 | 0/10 | 0 | 10 | 10/10 |
| banner | 0/10 | 0 | 0 | 10/10 | 0/10 | 0 | 0 | 10/10 |
| cleanup | 0/10 | 0 | 0 | 10/10 | 0/10 | 0 | 0 | 10/10 |
| count-py | 0/10 | 0 | 0 | 10/10 | 0/10 | 0 | 0 | 10/10 |
| all | 20/70 | 0 | 0 | 70/70 | 20/70 | 0 | 31 | 70/70 |

What the runs show:

- **A warning did not reduce failures on the first try.** 20 of 70 runs hit the
  failure with the hook off, and 20 of 70 with it on. Every run of the two tasks
  outside a repository, in both conditions, hit it with its first git call
  (`git status`, or `git rev-parse` used as a check). A warning comes right
  before a call and never blocks it, so a failure on the first try cannot be
  avoided this way; it could only change what the agent does next. In no run, in
  either condition, did the failure come back in a later call, so there was
  nothing left for the warning to prevent.
- **Inside a repository the hook warned anyway.** In the two tasks inside a
  repository it spoke 20 times, every one about a failure that cannot happen
  there. Every task was done in all 140 runs, so these warnings did not cost the
  task here.
- **The zsh tasks never failed.** The model quoted `==========` and the globs on
  its own in all 60 runs, so these runs say nothing about those two rules.
- **Cost.** 140 runs, 24 minutes of agent time, $0.17 reported by Claude Code.
  The same bench also ran a third condition, a hook that skipped the two git
  warnings inside a repository; that change was not kept, and its runs are not
  part of this record.

## What guards each rule

Each rule of the method has a test that fails if the rule is broken. The names
are test functions under `tests/`.

| Rule | Test |
|---|---|
| The split is by session and exact, even when sessions start together | `test_evaluate.py::test_split_is_exact_even_when_sessions_start_together` |
| Nothing after the cut counts as known earlier | `test_evaluate.py::test_what_an_earlier_session_did_after_the_cut_is_not_known_earlier` |
| A call is dated by when its result arrived | `test_adapter_claude.py::test_a_call_is_dated_by_when_its_result_arrived` |
| Timestamps compare as instants | `test_schema.py::test_timestamps_are_stored_in_utc_so_text_order_is_time_order` |
| A failure first seen later is not recurring | `test_evaluate.py::test_a_failure_first_seen_later_is_not_recurring` |
| Warnable needs the same command, not only the same failure | `test_evaluate.py::test_a_recovery_of_one_command_does_not_make_another_command_warnable` |
| A success that arrived before the failure is no recovery | `test_evaluate.py::test_a_success_that_arrived_before_the_failure_is_no_recovery` |
| A chained command line is neither a recovery nor warnable | `test_evaluate.py::test_a_later_compound_failure_is_recurring_but_not_warnable`, `test_insight.py::test_a_compound_success_is_not_a_recovery` |
| The same call is never counted twice | `test_adapter_claude.py::test_a_call_logged_twice_is_one_call`, `test_adapter_codex.py::test_an_event_exported_into_two_files_is_counted_once`, `test_schema.py::test_duplicate_and_partial_loads_keep_one_next_chain` |
| No-match exits of search tools are not failures | `test_schema.py::test_failure_key_skips_no_match_exits_and_unknown_commands` |
| No raw text or local path reaches the graph | `test_adapter_claude.py::test_no_raw_command_text_or_output_in_records`, `test_schema.py::test_a_shared_store_refuses_local_paths`, `test_normalize.py` |
| A private store without public datasets is split per agent; one that cannot be split says so and points to `faildex report` | `test_evaluate.py::test_a_private_store_without_datasets_is_scored_per_agent`, `test_evaluate.py::test_report_explains_an_unscorable_store_instead_of_an_empty_table` |
| The documents show what `make eval` prints | `test_docs.py::test_readme_table_matches_the_committed_store` |
| The hook replay applies the hook's own rule, to every command of the store | `test_evaluate.py::test_the_replay_uses_the_hooks_own_rule_on_every_command_of_the_store` |
| The hook replay warns what the hook would have said, in the hook's order and within its cap of 2 | `test_evaluate.py::test_the_replay_warns_what_the_hook_would_have_said_in_the_same_order` |
| A call dated after the cut is not known, even inside an earlier session | `test_evaluate.py::test_a_call_from_after_the_cut_inside_an_earlier_session_is_not_known`, `test_evaluate.py::test_a_lookup_limited_to_every_session_is_the_hooks_own_lookup` |
| Every agent's shell calls are replayed, local Codex logs included | `test_evaluate.py::test_the_replay_counts_local_codex_shell_calls` |
| The hook replay knows nothing from after the cut | `test_evaluate.py::test_the_replay_knows_nothing_from_after_the_cut` |
| The hook replay runs per agent on a private store | `test_evaluate.py::test_the_hook_replay_runs_per_agent_on_a_private_store` |
| The replay numbers in the documents are what `make eval` prints; the other cuts and the overlap with recoveries are recomputed from the committed store | `test_docs.py::test_the_hook_replay_in_the_documents_matches_the_committed_store`, `test_docs.py::test_the_replay_claims_about_cuts_and_recoveries_hold` |
| A second engine build reaches the same numbers | `test_docs.py::test_relate_webassembly_reaches_the_same_numbers` |
| The bench table and its claims are the committed runs | `test_docs.py::test_the_bench_table_in_the_documents_is_the_committed_runs` |
| The notice after a failure keys it as the store does | `test_post_failure.py::test_the_hook_keys_a_failure_as_the_store_does` |
| The notice leaves out the hook's own session and its subagents | `test_post_failure.py::test_the_own_session_and_its_subagents_are_left_out_of_the_counts` |
| The notice names no next step on a compound line | `test_post_failure.py::test_a_compound_line_gets_the_precedent_and_no_next_step` |

## Notices right after a failure (Claude Code `PostToolUseFailure`)

The Claude Code hook that `faildex link` installs runs `faildex hook` right after a
shell call fails (`PostToolUseFailure`); faildex warns no agent before a command any
more (the two sections above are why). When other sessions
had the same failure of the same command, the hook tells the agent so, with the
recovery on record. This section says how it decides, what was measured before it
was built, and what was not measured.

- **Same key as the store.** The hook reads the `error` text the way the store
  reads a tool result: the exit code, the error signature over the whole text (its
  first 2,000 characters scanned) and the same failure key
  (`adapters.claude_code.failed_call`, shared with the adapter). It looks the key
  up under the line's stored command template, its first program, and nowhere
  else: no lookup by failure key alone.
- **Other sessions only.** The session the hook runs in and its subagents
  (`<session>/agent-*`) are left out of both the session count and the call
  count, so a failure a refresh has just stored is no precedent for itself. The
  hook speaks when at least `--min-sessions` (2) other sessions remain.
- **A precedent is enough.** The 3% share of the earlier warning before a command does not apply,
  since the call has already failed, and no recovery is required. A stricter rule
  that also wanted a usable next step (a strict recovery, a shell fix, or a retry
  for a transient failure) on a line that is not compound would almost never
  speak: 0 of 52 keyed Claude Code failures in the table below. Most failures are
  on compound lines, and a compound line is used neither as a next step nor as
  evidence of a recovery.
- **The words.** The rule sentence of `faildex rules`, in English, with the
  counts above: no "retry it" for a lasting error, no next step at all on a line
  that runs several programs, no paths and no evidence pointers. The quoted error
  is marked as what earlier sessions recorded, data and not instructions, with
  control characters removed and each line capped at 1,000 characters.
- **Silence.** Not Bash; an empty or non-string `error`; an interrupted call
  (`is_interrupt`, exit 130 or 143); a payload over 1,000,000 characters; no key;
  no match; too few other sessions. A session is told again each time it repeats
  the failure: the hook keeps no state on its normal path, and a repeat is when
  the notice matters again.

Replayed on the public `store/` in time order, with only what was known before
each failure (a precedent is any agent's earlier failure of the same command and
key in another session):

| Claude Code shell calls in `store/` | 1,415 |
|---|---|
| marked failed | 65 |
| with a non-zero exit (the hook runs) | 57 |
| not interrupted (exit 130 or 143) | 55 |
| with a failure key | 52 |
| of those, on a compound line | 44 |
| with a precedent in at least 1 / 2 other sessions | 1 / 0 |
| of those, with a usable next step on a line that is not compound | 0 |

At the default of 2 sessions the hook would not have spoken on this data. The
public Claude Code sample is small and its sessions rarely share a failure; how
often the hook speaks depends on how many sessions a store holds.

- **Every agent.** Counted over Codex failures too, under the stricter rule and
  once per session and key, 50 (m = 1) or 47 (m = 2) failures would have been
  told, all of them Codex and 47 and 46 of them `command timed out after <n>
  milliseconds`, from the one Windows Codex project of the public data. Codex has
  no `PostToolUseFailure` hook, so this does not measure the Claude Code case.
- **The hook sees the store's key.** In 13 real `claude -p` runs
  (`claude-haiku-5-5`, Claude Code 2.1.332), each failing one way, the hook's
  `error` text was the transcript's `tool_result` text and gave the same key: 13
  of 13. The same texts plus 11 edge cases (an error past 2,000 characters, CRLF,
  no exit line, empty text and others) give the same key on the store's path and
  the hook's path in 24 of 24; they are a test
  (`tests/fixtures/post_failure/key_inputs.json`). grep with no match is not
  marked failed, and `echo ====` exits 0, because Claude Code's shell no longer
  expands a leading `=`.
- **The effect was not measured.** No bench and no replay asks whether a notice
  reduces repeats. In a trial of 8 made-up tasks run 4 times each without any
  notice, on the same model, the first failure never came back later in a run, so
  that measure had nothing to reduce there.
- **Hidden failures never reach it.** A failure behind a pipe, `; echo` or
  `2>/dev/null` exits 0 and fires no `PostToolUseFailure`. In 5 of those 8 tasks
  the hook ran in at most 2 of 4 runs: the model checked first, quoted, or hid
  the exit code.
- **Out of scope.** Tools other than Bash; Codex and Cursor, which get the rules
  at session start only (Cursor has `postToolUseFailure`, which faildex does not
  use; Codex has no failure event). With `--refresh-every`, the hook counts failed
  calls only.
- **One-off counts.** The table and the trial were counted by scripts that are
  not in the repository; the key contract and the hook's rules are tests.

## Limits

- **Availability, not effect.** The numbers show that the graph already held the
  failure and often a recovery. They do not show that an agent given the warning
  would have avoided the failure. The [controlled bench](#controlled-bench) is
  one small check of that, on one model and seven tasks: a warning did not reduce
  failures on the first try.
- **One project dominates.** The Codex dataset is one developer working on one
  Windows project, so failures recur within a project more than they would
  across unrelated work. `command timed out` alone is 31 of the 80 recurring
  failures; without it the recurrence is 49 of 86 (57.0%).
- **The Claude Code sample is small.** Its later period has two keyed failures.
  The wisp dataset contributes sessions and schema coverage more than statistics.
- **No cross-agent overlap in this data.** No failure key appears under both
  agents here: one dataset is PowerShell on Windows, the other bash on Linux.
  The graph supports the cross-agent case, and the tests cover it, but the
  public data does not demonstrate it.
- **Keys are heuristic.** 382 of 627 failed calls get a key; the rest printed nothing usable, were
  no-match exits of search tools, or came from inline scripts. Normalization masks
  paths, numbers, quoted strings, URLs and hosts; inline scripts whose program cannot be told apart from data share the
  template `<script>`.
- **A recovery is "the same command worked again soon".** Most recorded
  recoveries are a retry of the same command; the graph cannot tell what changed
  in the arguments, because raw commands are not stored.
