# Local agent hook verification — 2026-11-20

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

## Codex interactive session

A fresh Herdr worker ran Codex `0.170.0` outside the repository. `/hooks` showed
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
