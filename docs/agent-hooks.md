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

## Keeping the store current

The store learns from new sessions only when `faildex ingest` runs. Add
`--refresh-every N` to a `faildex hook` command, `N = 200` recommended, and the hook
keeps it current. In `~/.claude/settings.json`:

    {"type": "command", "command": "faildex hook --refresh-every 200", "timeout": 5}

Each call counts itself, and the call that finds the store due starts
`faildex ingest --store <the hook's store>` as a detached background process and
returns at once, so the warning is not delayed. The store is due when either holds:

- `N` hook calls have gathered since the last refresh started;
- the store has not been written for 24 hours (a manual `faildex ingest` counts).

No refresh starts within 30 minutes of the previous start, and only the call that
takes the lock starts one, so concurrent sessions do not start two. Both times are
constants in `faildex/refresh.py`, not options. The refresh reads the same default
log folders as `faildex ingest` without options.

The refreshed store is the one named with `--store` or `FAILDEX_STORE`; with
neither, it is the private `~/.faildex/store` that `faildex ingest` writes, and the
first refresh creates it. A `./store` the hook found in the current folder (a
checkout's committed `store/`) is never refreshed.

Next to the store, `<store>-refresh/` holds the counter (`count`, one byte per call,
appended without a lock and never erased, so it grows by about 1 MB per million hook
calls), `lock` (pid and time; broken when its process is gone or it is over an hour
old) and `started` (when the last refresh started, and the counter's size then; the
calls since are the size now minus that). `<store>-refresh.log` gets one line when a
refresh starts (pid, calls, reason) and one when it ends (exit code, sessions and
calls in the store, seconds), with the ingest's own output between them. If the
counter or lock cannot be written, or the ingest cannot be started, the hook still
prints its warning and says nothing about the refresh.

`faildex ingest` writes on a copy of the store and swaps the copy in when it is
done, as `faildex build-store` does, so the store a reader sees is never half
written. Two ingests take turns under the store's write lock (`.<store>.write-lock`
next to it), from copying to swapping to publishing the hook's index, so a manual
run and a refresh never drop each other's data. The first open of a fresh copy of a
store, which writes Relate's per-machine files, takes the same lock.

faildex deletes only folders it can prove are its own. A writer names its copy
`.<store>.writing-<token>` and the store it moves aside `.<store>.old-<token>`, with a
random token, and puts a mark inside each (process, the store's path, the token). It
deletes its own set-aside store only after its new store is in place with a valid
manifest. A writer that is killed leaves these folders behind: the next writer puts
a set-aside store back if the store itself is missing (removing an empty folder left
in its place, only if it is truly empty), and deletes nothing else. If it cannot put
the store back, the ingest stops with an error instead of writing a new, empty store. Folder
names are compared as text, so a store called `s[12]` is never read as a pattern.
Windows refuses to rename a folder while a
reader holds it open; after three tries, ingest keeps the old store, prints why and
exits 1, and the next refresh tries again. Ingest refuses a `--store` that is a file,
or a folder holding other files and no store, since swapping would delete them.

## The hook's index

Opening a Relate store takes most of a hook call, and a hook that opens the store
can meet an ingest replacing it. So after writing the store, `faildex ingest` writes
`<store>-index.json` next to it: for each command template that has failed, its run
count and every one of its failures (sessions, calls, recoveries, fixes, evidence),
and the failures pooled across commands for the shell rules. It holds data, not
sentences; the hook builds the same text as before from it, so any `--min-sessions`
or `--top` gives what the store would. The file is written to a temporary file in
the same folder, flushed to disk and renamed over the old one, so a reader sees the
old index or the new one.

The index names the SHA-256 of the store's `manifest.json`, which changes on every
write, and the ingest publishes it while it still holds the write lock, so the
fingerprint and the data come from the same store. The hook uses the index when the
fingerprint matches, and also while an ingest is between the two renames of a swap:
the manifest is then missing for an instant, and both marked folders,
`.<store>.old-<token>` and `.<store>.writing-<token>`, show it. Then only an index whose
fingerprint is the manifest of the store just moved aside is used, and a moved-aside
folder without a readable manifest is no evidence. A store that is missing without
that evidence was deleted: its index is not used, and without `--store` the hook goes
on from `./store` or the private store to the next one, down to the public demo
store. On the index path the hook does not load Relate at all. When the fingerprint differs, or anything in the
index cannot be read (no index yet, a store from an older faildex, a damaged file or
entry, another format version), the hook reads the store itself, read-only, and says
nothing if a read-only open fails; it never opens a store for writing. It also starts
a background rebuild of the index, at most once per 10 minutes, into the cache folder
(`~/.cache/faildex/index/`), never next to a store it did not write. The rebuilt index
is keyed to the store as the hook named it, so the next call finds it, even for the
public demo store, whose data the rebuild reads from its cache copy when the shipped
files cannot be opened as they are. The rebuild lock follows the refresh lock's rules
(checked, broken and taken under a guard) and holds a random token that the hook hands
to the rebuild; only that rebuild removes it.

The hook never fails and never writes a store. Whatever goes wrong, it prints what
it prints when it has nothing to say and exits 0. It does not read the saved language
or adjust the console either, so nothing reaches stderr. Without `--store`, it looks for a
store as other commands do, except that `~/.faildex/store` counts as present when
only its index is (mid-swap), and the public demo store is not copied into the cache:
the hook reads the cache copy if there is one, else the shipped store, through an
index when one exists.

Why count calls rather than time: the store falls behind only while agents run
commands. A timer would refresh through idle days for nothing and lag on busy
ones, while hook calls follow the flow of new sessions, and the hook is already
running, so no scheduler or daemon is needed. Why 30 minutes: an ingest re-reads
every log, which takes a while on a long history, while sessions are working;
30 minutes keeps a busy stretch from running one after another and still allows
several refreshes in a working day. Why 24 hours: sessions where the hook is not
called (another agent, the hook turned off, a quiet week) still reach the store
by the next day.

`faildex link` does not add the option to the Codex and Cursor hooks it installs;
add `--refresh-every 200` to their `faildex hook` command yourself if you want it.
