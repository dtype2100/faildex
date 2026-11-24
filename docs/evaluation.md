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

The table above asks what the graph knew. This asks what the pre-run hook would
have done with it. Knowledge is the earlier period only; the rule is the hook's
own (a failure seen in 2 or more sessions and in at least 3% of that command's
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

## Limits

- **Availability, not effect.** The numbers show that the graph already held the
  failure and often a recovery. They do not show that an agent given the warning
  would have avoided the failure. That needs a controlled run, which this
  evaluation does not include.
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
