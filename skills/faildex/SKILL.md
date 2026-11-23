---
name: faildex
description: When a command fails, read this skill before retrying it. Use when a shell command has just failed, when about to retry a command that failed earlier, or when the user asks which mistakes keep recurring across agent sessions or wants rules written from them.
---

# faildex

faildex keeps a graph of past agent sessions: which commands failed, with what
failure, and what the session did next that worked.

## Before retrying a failed command

Run `faildex check "<the command>"`. Each line it prints is a failure this
command has hit in at least two earlier sessions, with the recovery on record.
It stays silent for failures that are under 3% of the command's recorded runs,
so no output means nothing frequent is known, not that the command never failed;
proceed normally. `faildex rules` lists every recurring failure.

If the MCP server is connected, call `preflight` with the command instead, and
`evidence` with a failure key to see the sessions and log lines behind it.

## When asked what keeps going wrong

Run `faildex rules`. It lists proposals, best first, each with evidence pointers.
Show them to the user. Write a rule only after the user picks it:
`faildex rules --approve <numbers> --to ~/faildex-rules.md`. That file is what
`faildex link` wires into the agents' instructions, so new sessions follow it.

## When the user's own logs are not indexed yet

`faildex check` then answers from the public demo store. Suggest
`faildex ingest` (it finds the default log folders of Claude Code, Codex,
Cursor and Antigravity; the store stays on this machine).

## Limits to state when reporting

- A recovery means the same command succeeded within five calls after it failed.
  The graph does not store raw commands, so it cannot say what was changed.
- Counts are per failure key; keys are normalized text and can merge distinct causes.
