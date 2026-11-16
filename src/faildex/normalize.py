"""Normalize shell commands and failure text so that recurrences line up.

`command_template` reduces a command line to the program and, for tools with
subcommands, the subcommand: "git -C repo push origin main" -> "git push".

`error_signature` reduces failure output to one masked line: paths, numbers,
quoted strings and hex ids are replaced, so the same failure in two sessions
yields the same signature.
"""

from __future__ import annotations

import re
import shlex

# Programs whose first non-flag argument is a subcommand worth keeping.
SUBCOMMAND_TOOLS = frozenset(
    [
        "git",
        "gh",
        "uv",
        "npm",
        "pnpm",
        "yarn",
        "docker",
        "cargo",
        "kubectl",
        "brew",
        "pip",
        "pip3",
        "go",
        "make",
        "npx",
        "poetry",
        "conda",
        "dotnet",
        "apt",
        "apt-get",
        "systemctl",
        "hf",
        "relate",
    ]
)
# Words that only set up the real command.
SKIP_PROGRAMS = frozenset(["cd", "export", "set", "source", "pushd", "popd", "true", "echo"])
WRAPPERS = frozenset(["sudo", "time", "env", "nohup", "command"])
# Flags that consume the next token, so it is not mistaken for a subcommand.
VALUE_FLAGS = frozenset(
    ["-C", "-c", "-n", "-H", "--namespace", "--context", "--git-dir", "--work-tree"]
)
_WINDOWS_PATH = re.compile(r"[A-Za-z]:\\")

_SEGMENTS = re.compile(r"\s*(?:&&|\|\||;|\n)\s*")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_EXIT_LINE = re.compile(r"^(<error>)?\s*exit code:? -?\d+", re.IGNORECASE)
_NOISE_LINE = re.compile(r"^(wall time:|output:|at line:\d+ char:\d+|\+ |~+$)", re.IGNORECASE)
_ERROR_WORDS = re.compile(
    r"(error|not found|no such|fatal|failed|denied|cannot|can't|invalid|exception|unknown|"
    r"refused|timed? ?out|no matches|unexpected|not recognized|is not a |usage:)",
    re.IGNORECASE,
)
_MASKS = [
    (re.compile(r"(['\"`]).{0,200}?\1"), "<s>"),
    (re.compile(r"[A-Za-z]:\\[^\s'\"<>|]+"), "<path>"),
    (re.compile(r"[a-z][a-z0-9+.\-]*://\S+", re.IGNORECASE), "<url>"),
    (re.compile(r"(?:~|\.{1,2}|[\w\-.@+]+)?/[\w\-.@+~/%]+"), "<path>"),
    (
        re.compile(
            r"\b(?:[a-z0-9\-]+\.)+(?:com|org|net|io|dev|ai|example|internal|local|co|kr)\b",
            re.IGNORECASE,
        ),
        "<host>",
    ),
    (re.compile(r"\b[0-9a-f]{7,}\b"), "<hex>"),
    (re.compile(r"\d+"), "<n>"),
]
_COMMAND_NAME = re.compile(r"^[A-Za-z_][\w.\-]*$")
_DATA_FILE = re.compile(
    r"\.(md|txt|json|ya?ml|toml|cs|cpp|c|h|js|ts|html|css|csv|log|xml)$", re.IGNORECASE
)
MAX_SIG = 90
SCAN_CHARS = 2000


def _tokens(segment: str) -> list[str]:
    # POSIX splitting eats the backslashes of Windows paths, so keep them literal there.
    windows = bool(_WINDOWS_PATH.search(segment))
    try:
        tokens = shlex.split(segment, posix=not windows)
    except ValueError:
        tokens = segment.split()
    return [t.strip("'\"") for t in tokens] if windows else tokens


def _positional(tokens: list[str]) -> list[str]:
    """Arguments that are neither flags nor the value of a value-taking flag."""
    out, skip = [], False
    for token in tokens:
        if skip:
            skip = False
        elif token in VALUE_FLAGS:
            skip = True
        elif not token.startswith("-"):
            out.append(token)
    return out


def _program(token: str) -> str:
    name = re.split(r"[\\/]", token)[-1]
    return name[:-4] if name.lower().endswith(".exe") else name


def command_template(command: str) -> str | None:
    """Return "<program>" or "<program> <subcommand>" for the first real command."""
    fallback = None
    for segment in _SEGMENTS.split(command.strip()):
        tokens = [t for t in _tokens(segment) if not _ASSIGNMENT.match(t)]
        while tokens and _program(tokens[0]) in WRAPPERS:
            tokens = tokens[1:]
        if not tokens or tokens[0].startswith(("#", "$")):
            continue  # comment, or a PowerShell variable assignment / invocation
        program = _program(tokens[0])
        if not _COMMAND_NAME.match(program) or _DATA_FILE.search(program):
            continue  # a file name or expression, not a command
        if program in SKIP_PROGRAMS:
            fallback = fallback or program
            continue
        args = _positional(tokens[1:])
        if program in ("python", "python3", "py") and "-m" in tokens:
            index = tokens.index("-m")
            module = tokens[index + 1] if index + 1 < len(tokens) else ""
            return f"{program} -m {module}".strip()
        if program == "uv" and args[:1] == ["run"] and len(args) > 1:
            return f"uv run {_program(args[1])}"
        if program in SUBCOMMAND_TOOLS and args:
            return f"{program} {args[0]}"
        return program
    return fallback


def error_signature(text: str) -> str | None:
    """Return a masked one-line signature for failure output, or None if empty."""
    lines = [line.strip() for line in text[:SCAN_CHARS].splitlines()]
    lines = [
        line
        for line in lines
        if line and not _EXIT_LINE.match(line) and not _NOISE_LINE.match(line)
    ]
    if not lines:
        return None
    if any(line.startswith("Traceback") for line in lines):
        picked = lines[-1]
    else:
        # Without an error word the line is ordinary output, which must not enter the graph.
        picked = next((line for line in lines if _ERROR_WORDS.search(line)), None)
        if picked is None:
            return None
    picked = re.sub(r"<[^>]{1,40}>", "", picked)
    for pattern, mask in _MASKS:
        picked = pattern.sub(mask, picked)
    picked = re.sub(r"\s+", " ", picked).strip().lower()
    return picked[:MAX_SIG] or None
