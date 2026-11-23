# Codex and Cursor hooks

Run `faildex link` after installing faildex. It installs two user hooks for each
detected agent, preserving other integrations and making a timestamped
`hooks.json.faildex-backup-*` before changing an existing file. Invalid JSON and
symlinked hook configurations are skipped with a message. Repeating the command
does not add duplicate entries. `faildex link --remove` removes faildex entries
while preserving other hooks and the backups.

| Agent | File | Session rules | Shell warning |
| --- | --- | --- | --- |
| Codex | `~/.codex/hooks.json` | `SessionStart` → `hookSpecificOutput.additionalContext` | `PreToolUse` with `Bash` → `additionalContext` and `systemMessage` |
| Cursor | `~/.cursor/hooks.json` | `sessionStart` → `additional_context` | `beforeShellExecution` → `agent_message` and `user_message`, with permission `allow` |

The rules default to `~/faildex-rules.md`; `faildex link --rules PATH` selects
another file. Re-running `faildex link --rules PATH` retargets an existing
faildex-owned Antigravity rules symlink to the new file (leaving untracked
symlinks and regular files alone); `faildex link --remove` deletes only
faildex-owned links and files. Evidence lines are omitted from session context. The generated
command encodes the path as one shell-safe token, so Windows shell differences
and spaces or special characters in home directories do not change its meaning.
This encoding is not encryption. Warnings use the same store selection and
thresholds as `faildex check`: per-command warnings fire when a failure spans
at least `min_sessions` (default `2`) and accounts for at least `MIN_RATE`
(`0.03`, 3%) of that command's recorded runs. Shell-level `zsh` glob failures
(`(eval):<n>: no matches found: <glob>` and `zsh:<n>: no matches found: <glob>`)
are pooled across commands under `no matches found: <glob>` and warn before any
command line containing an unquoted glob once seen in at least `min_sessions`
sessions; `MIN_RATE` is not applied to that shell-level count because there is no
`zsh` command node in the graph and unquoted-glob detection gates when it fires.
zsh `=` expansion failures (`(eval):<n>: ==== not found`, from an unquoted word
starting with `==` such as `echo =====` or `[ a == b ]`) are pooled the same way
under `=<word> not found` and warn before a command line with such a word.
Lookup errors do not block shell execution.

Codex requires new or changed hooks to be reviewed and trusted in `/hooks`.
Trust the two faildex commands, then start a new session. A session started before
installation does not acquire session-start context retroactively.

Verify in fresh interactive Codex and Cursor sessions: ask for the loaded
faildex rule about quoting globs, then request `git -C /private/tmp status` on a
machine whose failure index knows that command. Confirm that the warning appears
before the shell result. Cursor should read the faildex skill after a failed
command and before retrying. Hooks need the installed `faildex` on the agent's PATH.

Cursor CLI hook execution can depend on the other entries in the configuration.
On `2026.11.19-f005e9d`, our existing configuration produced no probe events,
whereas a minimal probe configuration invoked session, shell, failure and file-read
hooks. This is an unresolved interaction, not evidence that CLI hooks are unsupported.
See [the three checks, restored configuration and remaining work](agent-hook-verification.md).

Official protocol references, checked 2026-11-19:

- [Codex hooks](https://learn.chatgpt.com/docs/hooks): configuration, trust, input and output.
- [Cursor hooks](https://cursor.com/docs/hooks): session and shell event schemas.

Cursor Cloud does not load user-home hooks or support `sessionStart`; this setup
targets local sessions.
