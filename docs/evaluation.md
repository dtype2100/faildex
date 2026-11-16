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

## Result

| Dataset | Sessions earlier / later | Later failures | Recurring | Warnable (of recurring) |
|---|---|---|---|---|
| codex-trajectories | 233 / 101 | 115 | 78 (67.8%) | 48 (61.5%) |
| wisp (Claude Code) | 61 / 27 | 2 | 2 | 0 |
| All | 294 / 128 | 117 | 80 (68.4%) | 48 (60.0%) |

With failure text only (no exit-code keys): 72 of 102 recurring (70.6%), 45 warnable.

36 distinct failure keys appear in the later period; 16 of them were seen earlier.

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
| The documents show what `make eval` prints | `test_docs.py::test_readme_table_matches_the_committed_store` |
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
