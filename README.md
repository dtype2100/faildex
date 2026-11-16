# faildex

A failure index for coding agents. faildex reads the session logs of Claude Code,
Codex and Cursor into one embedded [Relate](https://github.com/relatedb/relate) graph,
finds the failures that keep coming back across sessions, reads the way out off
the graph, and tells the agent before it runs the same command again.

Built for the Relate by Neo4j Hackathon.

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
| `faildex hook` | A Claude Code `PreToolUse` hook. Before a command with a known recurring failure it adds what earlier sessions learned. For every other command it prints nothing. |
| `faildex mcp` | MCP tools `preflight`, `evidence` and `recurring`, so any MCP agent can ask before it acts. |
| `faildex eval` | The numbers above, recomputed from the committed store. |
| `faildex ingest` | Your own Claude Code, Codex CLI and Cursor agent logs in a private store on your machine (`~/.faildex/store`), which every command above then uses. |

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

Requirements: Python 3.10 or later and [uv](https://docs.astral.sh/uv/).
Tested on macOS and Linux in CI.

```bash
git clone https://github.com/dtype2100/faildex && cd faildex
make setup     # install
make demo      # rules, a pre-run check and the evaluation, from the committed store
make eval      # the evaluation table alone
make test      # 120+ tests
```

`make demo` needs no download and no API key. It takes a few seconds.

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
evaluation in the browser; it arrives at the same 80 of 117.

Index your own logs. They stay on your machine, in `~/.faildex/store`:

```bash
uv run faildex ingest --claude ~/.claude/projects --codex-sessions ~/.codex/sessions --cursor ~/.cursor/chats
uv run faildex rules --store ~/.faildex/store
```

Use it in Claude Code. Add this to `.claude/settings.json`:

```json
{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
  {"type": "command", "command": "uv run --project /path/to/faildex faildex hook --store /path/to/faildex/store", "timeout": 5}
]}]}}
```

Use it from any MCP client:

```json
{"mcpServers": {"faildex": {"command": "uv",
  "args": ["run", "--project", "/path/to/faildex", "faildex", "mcp", "--store", "/path/to/faildex/store"]}}}
```

An agent skill that tells the agent when to call these is in
[`skills/faildex/SKILL.md`](skills/faildex/SKILL.md); copy it into `.claude/skills/faildex/`.

## Where the data lives

- **`store/`** is the persisted Relate store: 422 sessions, 14,328 tool calls,
  627 failed calls, 38,424 relationships, 0.85 MB. `faildex.store.open_store`
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

## Judging criteria

| Criterion | Where to look |
|---|---|
| Use of Relate and connected context | Schema with shared `Command` / `ErrorSig` nodes; recovery read as a `NEXT` path; constraints; committed directory store; read-only readers beside a writer |
| Functionality | `make demo`; `faildex rules`, `check`, `hook`, `mcp`, `eval`, `ingest`, `build-store`; a browser demo on Relate WebAssembly; CI on macOS and Linux |
| Usefulness | 68% of later failures were already in the graph; the hook warns only for those and is silent otherwise |
| Documentation and reproducibility | This file, `docs/schema.md`, `docs/evaluation.md`; every number comes from `make eval` on the committed store |
| Creativity | Failures learned by one agent become rules and warnings for the next session, with the log lines as evidence |

## AI use

This project was written with AI coding agents: Claude Code (Claude) for
implementation and Codex for independent code review. The design decisions, the
data choice and the review of results are the author's.

## Licence

Apache-2.0. Dataset licences are listed above.
