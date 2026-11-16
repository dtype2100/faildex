# Evaluation

Run `make eval`. It reads the committed store and prints the tables below. The
code is [`src/faildex/evaluate.py`](../src/faildex/evaluate.py); an independent
recount inside Relate WebAssembly (the browser demo, `site/graph.js`) gives the
same 83 of 121.

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
| codex-trajectories | 233 / 101 | 119 | 81 (68.1%) | 49 (60.5%) |
| wisp (Claude Code) | 61 / 27 | 2 | 2 | 0 |
| All | 294 / 128 | 121 | 83 (68.6%) | 49 (59.0%) |

With failure text only (no exit-code keys): 72 of 102 recurring (70.6%), 45 warnable.

38 distinct failure keys appear in the later period; 17 of them were seen earlier.

## Limits

- **Availability, not effect.** The numbers show that the graph already held the
  failure and often a recovery. They do not show that an agent given the warning
  would have avoided the failure. That needs a controlled run, which this
  evaluation does not include.
- **One project dominates.** The Codex dataset is one developer working on one
  Windows project, so failures recur within a project more than they would
  across unrelated work. `command timed out` alone is 31 of the 83 recurring
  failures; without it the recurrence is 52 of 90 (57.8%).
- **The Claude Code sample is small.** Its later period has two keyed failures.
  The wisp dataset contributes sessions and schema coverage more than statistics.
- **No cross-agent overlap in this data.** No failure key appears under both
  agents here: one dataset is PowerShell on Windows, the other bash on Linux.
  The graph supports the cross-agent case, and the tests cover it, but the
  public data does not demonstrate it.
- **Keys are heuristic.** 388 of 627 failed calls get a key; the rest printed nothing usable, were
  no-match exits of search tools, or came from inline scripts. Normalization masks
  paths, numbers, quoted strings, URLs and hosts; a few command templates in the
  public store are still words from inline scripts rather than programs.
- **A recovery is "the same command worked again soon".** Most recorded
  recoveries are a retry of the same command; the graph cannot tell what changed
  in the arguments, because raw commands are not stored.
