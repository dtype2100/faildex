#!/bin/sh
# Installs faildex: curl -fsSL https://raw.githubusercontent.com/dtype2100/faildex/main/install.sh | sh
#
# What it does, and nothing else:
#   1. installs uv (Astral's Python package manager) if it is missing;
#   2. installs the faildex command with `uv tool install` (uv fetches Python if needed);
#   3. tells you how to try it.
# Read it first: curl -fsSL https://raw.githubusercontent.com/dtype2100/faildex/main/install.sh
set -eu

SOURCE="${FAILDEX_SOURCE:-git+https://github.com/dtype2100/faildex}"

say() { printf '%s\n' "$*"; }

if ! command -v uv >/dev/null 2>&1; then
  say "faildex: installing uv first (https://docs.astral.sh/uv/)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # uv's installer puts it here; make it usable in this shell.
  PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  export PATH
fi

say "faildex: installing from $SOURCE"
uv tool install --force "$SOURCE"

BIN_DIR="$(uv tool dir --bin 2>/dev/null || printf '%s' "$HOME/.local/bin")"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "faildex: add $BIN_DIR to your PATH (or run: uv tool update-shell), then open a new terminal" ;;
esac

say ""
say "Installed. Try it:"
say "  faildex demo                      # rules, a pre-run warning and the numbers, on public logs"
say "  faildex check \"git status\"        # what is known to go wrong with a command"
say "  faildex ingest --claude ~/.claude/projects   # index your own Claude Code logs (stays on your machine)"
