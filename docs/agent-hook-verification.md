# Local agent hook verification — 2026-11-20

A dated record. The faildex hooks it checks before a shell command (Cursor
`beforeShellExecution`, Codex `pre-shell`) have since been removed; see
[agent hooks](agent-hooks.md) for what `faildex link` installs now.

## Cursor CLI

Cursor CLI `2026.11.19-f005e9d`, using `grok-4.7-xhigh`, was checked outside the
faildex checkout so its public demo store could not override the private store.
The installed faildex skill was available in all three checks.

| Check | Configuration and interface | Observed result |
| --- | --- | --- |
| 1 | Existing user hooks, including 17 entries from other integrations; temporary recording hooks appended; print mode | No recorder events. No injected faildex rule or warning; the agent read the faildex skill after the failed shell command. |
| 2 | Original user hooks restored; a new interactive CLI session | No injected faildex rule or warning; the agent used the faildex skill after the failure. No temporary recorder was installed for this check. |
| 3 | Temporary minimal configuration containing only recording hooks; print mode | Six recorder entries: `sessionStart`, `preToolUse`, `beforeShellExecution`, `postToolUseFailure`, `preToolUse`, `beforeReadFile`. |

The minimal configuration proves that this CLI invokes hooks. It intentionally
contained no faildex hooks, so the absence of faildex context in check 3 does not
test faildex's output handling. The recorders returned empty JSON, or
`{"permission":"allow"}` for `beforeShellExecution`, and recorded only event names,
input field names and input byte lengths. They did not store command or file contents.

The existing configuration produced no recorder events in check 1. This identifies
an unresolved interaction with that configuration; it does not establish which
entry causes it, or that every configuration with other integrations fails.
**The three-check limit was reached.** Isolating the responsible entry and verifying
faildex context delivery in a minimal configuration remain future work.

Both temporary changes were restored byte for byte in `finally` blocks. The
original and restored file's SHA-256 was
`de5983607204f25069f103504e77f9425e3e87e16b8e3bc7234bb79aca2e601b`.
No other integration's hooks were permanently changed.

### Protocol and future verification

The [official hook schema](https://cursor.com/docs/hooks) specifies `sessionStart`
with `additional_context`, and `beforeShellExecution` with `user_message` and
`agent_message`. These match faildex's current fields; a field-name correction
is not supported by the evidence. The minimal experiment directly observed the
five distinct events listed above; other CLI events were not tested.
The [official CLI guide](https://cursor.com/docs/cli/using#rules) documents
`.cursor/rules`, root `AGENTS.md` and `CLAUDE.md` as rule sources.

After approval for additional experiments:

1. Back up `~/.cursor/hooks.json` as bytes. Keep the backup outside the checkout.
2. Add a recorder that writes its event name before parsing stdin and returns
   nonblocking JSON. Use a fresh session outside the faildex repository.
3. Compare the unchanged configuration with a minimal configuration, then isolate
   other entries while preserving their original bytes for restoration.
4. Restore the original file immediately after each experiment, including errors
   and timeouts, and compare its hash. Never leave other tools disabled.
5. Separately test faildex rules and warnings: ask for the first injected rule
   before reading files, execute `find /nonexistent-dir -name x` once against a
   private store with known failures, then check the warning and skill read.

Until the interaction is resolved, keep other integrations installed and use
faildex's skill, explicit `faildex check` calls and the documented CLI rule sources.

## Fifth round: three additional bisection checks

All three checks used the same CLI version, model and original configuration
in a shared outside-repository workspace. Each fresh print-mode session executed `ls -d .`
exactly once, completed its tool call, and exited 0. The two installed faildex
hooks were retained in all three temporary configurations. Recorders were appended
to the selected entries; they stored only the event name and input key names.

| Check | Other integrations included | Recorder events | Elapsed |
| --- | --- | --- | --- |
| 1 | integration A's 8 entries, approximately half of the original 17 other entries | `sessionStart`, `preToolUse`, `beforeShellExecution`, `postToolUse`, `sessionEnd` | 20.51 s |
| 2 | 5 of the remaining 9 entries, all from integration B | None | 15.86 s |
| 3 | Same 5 integration B commands/events as check 2, temporarily omitting their `type: "command"` and empty `matcher` fields | None | 16.35 s |

The five candidate entries are:

| Integration | Cursor event |
| --- | --- |
| integration B | `beforeSubmitPrompt` |
| integration B | `postToolUse` |
| integration B | `postToolUseFailure` |
| integration B | `preToolUse` |
| integration B | `sessionStart` |

This reproduces missing recorder events with that five-entry group, while the
integration A subset and faildex hooks coexist with working recorders. It does **not** prove
that every integration B entry fails, identify a single responsible entry, or establish
which product is defective. Removing the two optional fields together did not
restore execution, so their mere presence is insufficient as an explanation.
The CLI sessions did not reach the probe driver's 90-second timeout; individual
hook failures, internal timeouts, output handling and cross-entry interactions
were not isolated.

**The new three-check limit was reached.** Further splitting of these five entries
and an unchanged full-configuration control remain unperformed. No faildex code
change or permanent change to any other integration is justified by these results.

For reproduction after approval for more checks, start from a byte backup of the
local configuration. Keep faildex's two entries, copy only the candidate group
above in its original order, and append recorders that return nonblocking JSON.
Compare with the integration A-only subset, using the same fresh workspace and one harmless
shell command. To repeat check 3, omit only `type` and `matcher` on the five selected
entries; leave their commands and event names unchanged. Restore the original
bytes in a `finally` block after each run, including failures and timeouts.

Each fifth-round run restored the original SHA-256
`de5983607204f25069f103504e77f9425e3e87e16b8e3bc7234bb79aca2e601b`.
The local results and key-only records are saved under
`/private/tmp/faildex-r5-hook-probes/` as `1-result.json` through `3-result.json`;
only check 1 produced `1-events.jsonl`. Private configuration backups are
not committed. No additional hook experiments were run for this documentation.

## Codex interactive session

A dated record (2026-11-20) of a hook that faildex no longer has: the `pre-shell`
hook below warned before a shell command and has since been removed. `faildex link`
now installs only the `SessionStart` hook for Codex and takes the `pre-shell` one out,
and `faildex hook` stays silent on it.

A fresh worker ran Codex `0.170.0` outside the repository. `/hooks` showed
both faildex commands enabled and **Trusted** in the user configuration:

- `SessionStart`: `faildex hook --agent codex --event session-start --rules-encoded …`
- `PreToolUse`, matcher `Bash`: `faildex hook --agent codex --event pre-shell`

The worker quoted its first injected rule before reading any file:

> When cat fails with (eval):<n>: ===== not found (seen in 10 sessions, 10 calls):
> no recovery on record yet; stop and check before retrying.

It then executed `find /nonexistent-dir -name x` once. The terminal displayed:

> ↳ Hook · faildex: `find` exited with code 1 and no useful output in 6 earlier
> sessions; no recovery on record.

The worker also quoted the injected pre-tool context identifying six sessions,
six calls and 4% of 155 `find` runs. The command exited 1 with the expected
missing-directory message. No manual `faildex check`, file read or retry preceded
the command. Both verification panes were closed after their evidence was captured.
