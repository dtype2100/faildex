# faildex

**English** · [한국어](README.ko.md)

A failure index for coding agents. faildex reads the session logs of Claude Code,
Codex, Cursor and Antigravity into one embedded [Relate](https://github.com/relatedb/relate) graph,
finds the failures that keep coming back across sessions, reads the way out off
the graph, and, right after an agent's shell command fails a way other sessions
already saw, tells it what they learned.

Built for the Relate by Neo4j Hackathon.

```bash
curl -fsSL https://raw.githubusercontent.com/dtype2100/faildex/main/install.sh | sh   # macOS, Linux
faildex demo
```

On Windows, see [Install](#install) for the PowerShell line.

![The faildex browser demo: 68.4% of later failures had already happened in an earlier session, and a map of the failures that came back, sized by sessions and coloured by whether a recovery is on record](docs/images/overview.jpg)

*The browser demo rebuilds the graph from 422 public sessions inside Relate
WebAssembly and recomputes every number on the page. Open it at
<https://dtype2100.github.io/faildex/>, or run it locally with `make site && make serve`.*

## How to use, in order

Three parts: set faildex up once, in order; repeat two steps as new sessions pile
up; then see the effect. `faildex help` prints the same steps in the terminal, and
the end of `faildex --help` lists the first part. Each step below has the command to
copy and what it changes. More on each command is under [Setup and run](#setup-and-run).

### First install (once, in this order)

**1. Install**

```bash
curl -fsSL https://raw.githubusercontent.com/dtype2100/faildex/main/install.sh | sh
```

If the installer says to add a folder to your PATH, run `uv tool update-shell` first. Then open a
new terminal so `faildex` is on your PATH, and check it:

```bash
faildex --version
```

What changes: adds the `faildex` command, and uv if it is missing; nothing else.
`faildex --version` prints the installed version. On Windows, use the PowerShell line in [Install](#install).

**2. Try it on public data**

```bash
faildex demo
```

What changes: nothing is written. It shows rules, the notice after a failed command and the numbers on the public logs that ship with faildex.

**3. Index your own logs**

```bash
faildex ingest
```

What changes: writes your private store at `~/.faildex/store` from the agent log folders it finds; it never leaves this machine. Later commands read it, unless `FAILDEX_STORE` is set or you run them inside a faildex checkout, which has its own `./store`.

**4. See the proposed rules, then approve the ones you want**

```bash
faildex rules
faildex rules --approve 1 3 --to ~/faildex-rules.md
```

What changes: `faildex rules` writes nothing and numbers the failures that recurred across sessions; `--approve` appends the ones you pick (here 1 and 3) to `~/faildex-rules.md`.

**5. Connect your agents**

```bash
faildex link
```

What changes: for each agent on this machine, Claude Code gets an `@` import line for the rules file in `~/.claude/CLAUDE.md`, the skill in `~/.claude/skills/faildex/` and the hook of step 6 in `~/.claude/settings.json`; Antigravity gets a `faildex-rules` plugin with the rules and the skill; Codex and Cursor get the skill and a session-start hook in their `hooks.json` that loads the rules (a faildex hook before shell commands from an earlier version is taken out). It creates `~/faildex-rules.md` if it is missing, so it can run before you approve anything, and records what it added in `~/.faildex-link.json`. In Codex, review and trust the new hooks with `/hooks` before opening a new session.

**6. Failure notices in Claude Code**

`faildex link` (step 5) has added this hook to `~/.claude/settings.json` (as `faildex hook --agent claude`), and took any `faildex hook` out of `PreToolUse`, keeping its command here if there was none yet. To use it in one project only instead, add it to that project's `.claude/settings.json` (into its `PostToolUseFailure` list if it has `hooks`):

```json
{"hooks": {"PostToolUseFailure": [{"matcher": "Bash", "hooks": [
  {"type": "command", "command": "faildex hook", "timeout": 5}
]}]}}
```

What changes: in Claude Code sessions started afterwards (in a session already running, review the new hook with `/hooks`), right after a shell command fails, Claude is told when other sessions had the same failure of the same command, with the recovery on record, and you see a one-line notice. It speaks when at least two other conversations had it (`--min-sessions`; a session and its subagents count as one); the session itself and its subagents do not count.

Scope: only failed shell calls that end with a non-zero exit code, including those run by skills, plugins and subagents. A failure hidden behind a pipe or `; echo` exits 0 and never reaches the hook; MCP tools and file tools get nothing. Approve those failures in `faildex rules` and they reach the agent as rules when a session starts. Codex and Cursor get the rules at session start only: `faildex link` installs no hook before a shell command for any agent, and takes out the ones earlier versions installed. A notice right after a failure is out of scope for them (Cursor has `postToolUseFailure`, which faildex does not use; Codex has no failure event).

**7. Check that it works**

```bash
faildex check "git status"
```

What changes: nothing is written. It prints up to three recurring failures of that command that are frequent enough to warn about, each with the recovery on record; nothing when there are none.

### Day to day (repeat as new sessions pile up)

**1. Index the new sessions**

```bash
faildex ingest
```

What changes: it reads every log again. Calls already in the store are replaced by what the log says now, new ones are added, and nothing is deleted, even when a log file is gone.

**2. Approve new rules**

```bash
faildex rules
faildex rules --approve 1 3 --to ~/faildex-rules.md
```

What changes: list first, since the numbers change after an ingest. Approved rules reach every linked agent from its next session without running `faildex link` again; on Windows, where Antigravity got a copy instead of a link, run it again.

### See the effect

**1. Score recurrence on your own logs**

```bash
faildex eval --store ~/.faildex/store
```

What changes: nothing is written. It splits your sessions by start time, per agent, and shows how many later failures had already happened earlier.

**2. Compare before and from a day**

```bash
faildex report --split 2026-11-17
```

What changes: nothing is written. It counts calls and failures in your store before that day and from that day on.

### Undo

```bash
faildex link --remove
```

- That command takes out the import line, skills, plugin and hooks that `faildex link` installs; `~/faildex-rules.md` stays.
- It also takes the `faildex hook` entries out of `PostToolUseFailure` and `PreToolUse` in `~/.claude/settings.json`, keeping every other hook and setting; a `faildex hook` you added to a project's `.claude/settings.json` stays.
- Deleting `~/.faildex` removes your private store and the saved language; commands without `--store` then use the public demo store, unless `FAILDEX_STORE` or `./store` applies.

### Output language

Output is in English by default. `faildex lang ko` switches it to Korean and `faildex lang en`
back (saved in `~/.faildex/config.json`; `--lang` or `FAILDEX_LANG` wins for one run or one
shell). Hook and MCP replies, the rule text `--approve` writes, JSON and failure keys stay in
English, because agents read them and rules files are deduplicated on that text.
`faildex help <command>` explains one command with examples.

## Use case

Coding agents do not remember. A session hits `fatal: not a git repository`,
works out why, and the next session hits it again. Each agent keeps its own log
format, so nothing carries over between sessions or between agents.

On the public session logs committed with this repository, **68% of the failures
in the later sessions had already happened in an earlier session**, and for 60%
of those an earlier session also shows the same command succeeding a few calls
later. That is knowledge the agent had on disk and could not reach.

faildex turns it into three things:

| You run | You get |
|---|---|
| `faildex rules` | Rule proposals for failures that recurred across sessions, each with the recovery on record and pointers to the log lines. Only the ones you approve are written to a rules file. |
| `faildex hook` | A Claude Code `PostToolUseFailure` hook. Right after a shell command fails, when other sessions had the same failure of the same command, it shows a one-line notice in the session and gives Claude what they learned; otherwise it prints nothing. For Codex and Cursor it loads the approved rules when a session starts. |
| `faildex mcp` | MCP tools `preflight`, `evidence` and `recurring`, so any MCP agent can ask before it acts. |
| `faildex eval` | The numbers above, recomputed from the committed store. On your own store (`--store ~/.faildex/store`), which has no public datasets, the same split runs per agent. |
| `faildex ingest` | Your own Claude Code, Codex CLI, Cursor and Antigravity logs in a private store on your machine (`~/.faildex/store`), which every command above then uses. |
| `faildex report` | Counts before and after a date on your own store: calls, failures, one failure of your choice, and notices the hook gave. |

### One failure, followed through the graph

Select a failure in the browser demo to see when it happened, its neighbourhood
in the graph (the sessions and commands that hit it), how sessions got past it,
and the log lines behind it:

<img src="docs/images/failure-detail.jpg" width="640" alt="Detail of the failure 'rg: regex parse error': 8 sessions, 12 failed calls, a timeline of when it happened, its neighbourhood in the graph, and recovery paths such as rg failing and then succeeding on the next call (8 times)">

## How it uses Relate

The log of one session is a list. The question "has this failed before, and what
got past it?" is a path across many lists, which is why the data lives in a graph.

```
(Source)<-[:FROM]-(Session)-[:HAS_CALL]->(Call)-[:NEXT]->(Call)
                                          |  \
                                       [:RAN] [:FAILED_WITH]
                                          v        v
                                      (Command) (ErrorSig)
```

`Command` and `ErrorSig` nodes are shared by every session and every agent. A
failure seen once is one hop from every other session that hit it and a short
`NEXT` path from how that session recovered:

```cypher
MATCH (k:Command {template: $command})<-[:RAN]-(f:Call)-[:FAILED_WITH]->(e:ErrorSig)
MATCH p = (f)-[:NEXT*1..5]->(g:Call {ok: true}), (g)-[:RAN]->(k)
RETURN e.sig, min(length(p)) AS calls_until_it_worked
```

What Relate is used for:

- **Embedded directory store.** `store/` is a Relate database committed to this
  repository. There is no server to start; `relate.connect("store", read_only=True)` is the whole setup.
- **Cypher with variable-length paths** for recoveries, and `MERGE` on keyed nodes
  so that loading the same log twice changes nothing.
- **Uniqueness constraints** on every key. They also index the keys: loading
  4,000 calls takes 0.6 s with them and 60 s without.
- **One writer, many readers.** The hook and the MCP server open the store
  read-only while an ingest is writing.
- **One query layer for every surface.** `faildex rules`, the hook and the MCP
  tools call the same functions in [`insight.py`](src/faildex/insight.py), so
  they cannot disagree.

The schema is in [docs/schema.md](docs/schema.md). The graph never stores a raw
command or raw output: commands become templates (`git push`), failures become
masked signatures, and each call keeps a pointer to its log line.

## Setup and run

### Install

| | One line | Needs |
|---|---|---|
| macOS | `curl -fsSL https://raw.githubusercontent.com/dtype2100/faildex/main/install.sh \| sh` | Terminal; git (Xcode command line tools) |
| Linux | `curl -fsSL https://raw.githubusercontent.com/dtype2100/faildex/main/install.sh \| sh` | any shell with curl and git |
| Windows | `powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/dtype2100/faildex/main/install.ps1 \| iex"` | PowerShell; no git needed |

Each script installs [uv](https://docs.astral.sh/uv/) if you do not have it, then
the `faildex` command, and changes nothing else. Read them first if you prefer:
[install.sh](install.sh) and [install.ps1](install.ps1), about thirty lines each.
With uv already installed, the same thing by hand:

```bash
uv tool install git+https://github.com/dtype2100/faildex      # macOS, Linux
uv tool install https://github.com/dtype2100/faildex/archive/refs/heads/main.zip   # Windows, without git
```

Open a new terminal afterwards so `faildex` is on your PATH (if the installer says to add a folder
to your PATH, run `uv tool update-shell` first). Then, from any folder
(the whole order is in [How to use, in order](#how-to-use-in-order)):

```bash
faildex demo                  # rules, a notice after a failure and the numbers, on public logs
faildex check "git status"    # what is known to go wrong with a command
```

CI installs and runs faildex on macOS, Linux and Windows. On Windows, `faildex link`
copies the rules file into Antigravity's plugin when symlinks are not allowed;
run it again after approving new rules.

`faildex demo` needs no download, no API key and no setup: the public store ships
inside the package. It takes a few seconds.

#### Windows (PowerShell)

Use PowerShell 5.1 or 7 with internet access. The one-line installer above installs
uv if needed; uv manages Python (faildex needs Python 3.10 or later). Git is not
needed for the ZIP method. If git is installed, the `git+https://...` command above
works on Windows too. Add `--force` after `uv tool install` when reinstalling or
switching between methods.

In a new PowerShell window, check the installation:

```powershell
Get-Command faildex
faildex --help
faildex demo
faildex sources
faildex ingest
```

`ingest` finds agent logs under your Windows user profile and writes the private
store to `~/.faildex/store`. If no default log folders exist, it prints
`no agent logs in the default folders` and exits with code 1; pass an existing
folder with `--claude`, `--codex-sessions`, `--cursor` or `--antigravity`.

If a new window still cannot find `faildex`, run `uv tool update-shell` and reopen
PowerShell. For the current window, use `$env:Path = "$(uv tool dir --bin);$env:Path"`.
PowerShell 5.1's `>` writes UTF-16; use `| Set-Content -Encoding UTF8` when saving
UTF-8 output (with a BOM on PowerShell 5.1).
Check `$LASTEXITCODE` immediately after a native command;
`| Select-Object -First N` can cut its output and produce a nonzero exit code.

Tested on Windows 10 22H2 with PowerShell 5.1, uv 0.9.10 and Python 3.13.5
(uv, Python and git were already installed):
all three installation methods, CLI checks, default ingest and isolated
`link`/`link --remove` passed. See [commands, results and limits](docs/windows-install-verification.md).

### From a checkout

Requirements: Python 3.10 or later and uv. Tested on macOS, Linux and Windows in CI.

```bash
git clone https://github.com/dtype2100/faildex && cd faildex
make setup     # dependencies and the secret-scan hook
make demo      # the same demo, from the committed store
make eval      # the evaluation table alone
make test      # 160+ tests
make install   # put this checkout on your PATH as `faildex`
```

Rebuild the store from the public datasets (about 120 MB of downloads):

```bash
make data          # downloads the two datasets at pinned revisions
make build-store   # writes store/ and prints node counts, size and memory
```

Run the browser demo locally (needs Node for one `npm pack`):

```bash
make site      # exports the store to site/data.json and fetches Relate WebAssembly
make serve     # http://localhost:8765
```

The page rebuilds the graph inside Relate WebAssembly and recomputes the
evaluation in the browser; it arrives at the same 80 of 117. Every panel has a
"Show Cypher" button with the queries behind it, and a console runs your own. The page is in English
and Korean: pick one from the globe menu in the top bar, or open it with `?lang=ko`.

Index your own logs. They stay on your machine, in `~/.faildex/store`. These are steps 3 to 5
of [First install](#first-install-once-in-this-order), which says what each one changes:

```bash
faildex ingest    # reads every default folder it finds; or pass --claude, --codex-sessions, --cursor, --antigravity DIR
faildex rules
cd ~ && faildex rules --approve 1 3   # write the ones you want to ~/faildex-rules.md
faildex link      # install the skill and rules, the Claude Code hook after a failure and Codex/Cursor session-start hooks; --remove undoes it
```

Example `faildex rules --top 2` output (on the public store):

```text
Public demo logs (./store): 422 sessions, 627 failed calls, 25 recurring
Note: this is demo data. Index your own logs with: faildex ingest

1. `Get-ChildItem` +4 more commands — command timed out after <n> milliseconds
   52 sessions, 81 failed calls · 38 of 81 recovered within 5 calls
   Action: retry the same command; a later try worked in 21 of 38 recoveries.
   evidence (3): codex-trajectories/trajectories.train.jsonl:18, +2 more

2. `git status` — fatal: not a git repository (or any of the parent…
   24 sessions, 25 failed calls · 0 of 25 recovered within 5 calls
   Action: stop and check before retrying; no recovery on record yet.
   evidence (3): codex-trajectories/trajectories.train.jsonl:18, +2 more

Showing 2 of 25 recurring (--top 25 for all); full evidence paths: --evidence
Write a rule: faildex rules --approve 1 2 --to ~/faildex-rules.md
```

Counts are per failure, across every command that hit it (`+4 more commands`).
"Recovered within 5 calls" counts failed calls after which the same command succeeded
within the next 5 calls; "21 of 38 recoveries" says how many of those took the step in
the Action line. The Action says "retry" only for failures that pass on their own
(timeouts, refused or reset connections, rate limits and server errors, locks); for any
other failure it says to fix the cause before running the command again. A zsh glob or
`=` failure gets its fixed cure: quote the word.
`--evidence` prints the evidence pointers (up to 3 sessions) in full.

Without `--store`, commands read the store named by the `FAILDEX_STORE`
environment variable when it is set, then `./store` (inside a checkout), then
`~/.faildex/store`, then the public demo store. `report` tries `~/.faildex/store`
before `./store`; `ingest` always writes `~/.faildex/store`; `export-web` reads
`./store` or the public demo store, stops without writing when that store holds your
own logs, and exports any other store only when you pass it with `--store`.

With no options, `faildex ingest` reads `~/.claude/projects`, `~/.codex/sessions`,
`~/.cursor/chats`, `~/.gemini/antigravity-cli` and `~/.gemini/antigravity`, whichever exist.

Use it in Claude Code. `faildex link` adds this to `~/.claude/settings.json` for every
session (step 6 of [First install](#first-install-once-in-this-order)); to use it in one
project only, add it to that project's `.claude/settings.json` yourself. It reads your
own store once you have run `faildex ingest`, and the public one until then:

```json
{"hooks": {"PostToolUseFailure": [{"matcher": "Bash", "hooks": [
  {"type": "command", "command": "faildex hook", "timeout": 5}
]}]}}
```

Codex and Cursor get the rules at session start only (`faildex link` sets that up); a
notice right after a failure is out of scope for them.

To keep your store current without running `faildex ingest` by hand, add
`--refresh-every 10` to that command (`"command": "faildex hook --refresh-every 10"`).
The hook runs only after a failed shell call, so it counts failed calls only: every 10 of
them, and at least once a day (checked when a failure comes), it starts `faildex ingest`
in the background and returns at once; no refresh starts within 30 minutes of the
previous one. 10 keeps about the pace of the earlier 200 calls: in the public Claude Code
logs, 65 of 1,415 shell calls failed.
It refreshes the store named with `--store` or `FAILDEX_STORE`, else `~/.faildex/store`, never a `./store`.
See [keeping the store current](docs/agent-hooks.md#keeping-the-store-current).

Use it from any MCP client:

```json
{"mcpServers": {"faildex": {"command": "faildex", "args": ["mcp"]}}}
```

An agent skill that tells the agent when to call these is in
[`skills/faildex/SKILL.md`](skills/faildex/SKILL.md). `faildex link` installs it for Claude Code
(`~/.claude/skills/faildex/`), Antigravity (inside its `faildex-rules` plugin,
retargeting faildex-owned rules symlinks when `--rules` changes and leaving user
files alone), Codex (`~/.codex/skills/faildex/`) and Cursor
(`~/.cursor/skills/faildex/`); `faildex link --remove` takes only faildex-owned
entries out again.

Codex and Cursor also receive one hook in their user `hooks.json`: session start
loads approved rules without evidence lines. No hook runs before a shell command, and
a faildex one an earlier version installed there is taken out. Existing hooks are preserved and backed up before changes;
removal deletes only faildex hook entries. In Codex, review and trust the new
commands with `/hooks` before opening a new session. See [hook setup](docs/agent-hooks.md).

Cursor CLI supports hooks, but in our check of `2026.11.19-f005e9d`, no hooks ran
with the existing configuration containing other integrations. A minimal probe
configuration did run hooks; the conflicting entry remains unidentified. Keep
other integrations intact and use the installed skill and [CLI rules](https://cursor.com/docs/cli/using#rules)
while investigating. See [results and verification steps](docs/agent-hook-verification.md).

## Where the data lives

- **`store/`** is the persisted Relate store: 422 sessions, 14,328 tool calls,
  627 failed calls, 38,338 relationships, 0.85 MB. `faildex.store.open_store`
  opens it, including the first time after a fresh clone.
- It is built from two public datasets only, both MIT licensed, pinned by revision
  in [`build.py`](src/faildex/build.py):
  [`crispwisp/wisp-claude-code-sessions`](https://huggingface.co/datasets/crispwisp/wisp-claude-code-sessions)
  (Claude Code) and
  [`israellaguan/codex-tool-use-trajectories`](https://huggingface.co/datasets/israellaguan/codex-tool-use-trajectories)
  (Codex). Each `Session` links to a `Source` node with the dataset, revision and licence.
- No private logs are in this repository. A shared store refuses local paths at
  the write boundary, and a secret scan runs before every commit.

## Evaluation

`make eval` splits each dataset's sessions by start time (first 70% earlier, last
30% later) and asks how much of what went wrong later was already in the graph.

| | later failures | already seen earlier | of those, recovery on record |
|---|---|---|---|
| All failure keys | 117 | 80 (68.4%) | 48 (60.0%) |
| Failure text only | 102 | 72 (70.6%) | 45 (62.5%) |

What these numbers do and do not show is in [docs/evaluation.md](docs/evaluation.md).
In short: they show that the knowledge was available, not that an agent given
the warning would have acted on it. The Codex dataset is one developer on a
Windows project, and one failure (`command timed out`) is 31 of the 80; without
it the recurrence is 57%.

A different question is whether faildex's earlier hook, which warned before a command
(it is gone; see below), would have spoken. Replaying that hook's own rule on the later period, it would have spoken before 206 of the 5,070
later shell calls (4.1%), and 10 of those calls then failed with the failure it
named, 10 of the 117. Nine of the ten are in one session, and moving the cut
between 50% and 90% moves the count between 0 and 22 (recomputed by a test from the
committed store), so this describes these logs and is not a rate. None of the 48 failures with a recovery on record would
have been warned. Details in [docs/evaluation.md](docs/evaluation.md#would-the-hook-have-spoken).

A small controlled bench runs seven tasks in Claude Code with that earlier hook off
and on, 10 times each: a warning did not reduce failures on the first try (20 of 70
runs either way), because the failure comes on the first call and a warning
never blocks it. Inside a git repository the hook still warned before 20 calls
about git failures that cannot happen there
([bench](docs/evaluation.md#controlled-bench)). These results are why faildex now
warns before no command and speaks only right after a failure.

## Across agents, on real logs

The public datasets cannot show the cross-agent case: one is PowerShell on
Windows, the other bash on Linux, and no failure appears under both. The
author's own logs can. These are counts from `faildex report` on a private
store built with `faildex ingest` on 2026-11-17. The logs are not in this
repository, so you cannot recompute these numbers; run the same two commands on
your own logs to get yours.

| Agent | Sessions | Tool calls | Failed |
|---|---|---|---|
| Claude Code | 190 | 19,443 | 364 |
| Codex | 39 | 1,786 | 101 |
| Cursor | 59 | 2,538 | 94 |

- **12 failure keys were hit by more than one agent.** What one agent ran into,
  another had already run into.
- 57 failure keys recurred across two or more sessions; 13 of them have a
  recovery on record.
- The earlier warning before a command was selective: of 197 command templates, 7 would have got one.

## Judging criteria

| Criterion | Where to look |
|---|---|
| Use of Relate and connected context | Schema with shared `Command` / `ErrorSig` nodes; recovery read as a `NEXT` path; constraints; committed directory store; read-only readers beside a writer; the same graph and queries running in Relate WebAssembly in the browser demo, with each failure's neighbourhood drawn |
| Functionality | one-line install and `faildex demo`; `faildex rules`, `check`, `hook`, `mcp`, `eval`, `ingest`, `report`, `build-store`; a browser demo on Relate WebAssembly; CI on macOS, Linux and Windows |
| Usefulness | 68% of later failures were already in the graph; in one real Claude Code run (`claude -p`, Haiku) on a synthetic seeded store, Claude received the hook's notice right after a failed command and quoted it word for word: delivery, not an effect (whether it reduces repeats [was not measured](docs/evaluation.md#notices-right-after-a-failure-claude-code-posttoolusefailure)); it speaks only when other sessions had the same failure and is silent otherwise; 12 failure keys shared across three agents in the author's own logs |
| Documentation and reproducibility | This file, `docs/schema.md`, `docs/evaluation.md` (each rule of the method mapped to the test that guards it); every number comes from `make eval` on the committed store, a test fails if a document disagrees, and the WebAssembly build reaches the same numbers |
| Creativity | Failures learned by one agent become rules and notices for the next session, with the log lines as evidence |

## AI use

This project was written with AI coding agents: Claude Code (Claude) for
implementation and Codex for independent code review. The design decisions, the
data choice and the review of results are the author's.

## Licence

Apache-2.0. Dataset licences are listed above.
