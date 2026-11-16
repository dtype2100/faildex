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
SUBCOMMANDS = {
    "git": "add am apply bisect blame branch checkout cherry-pick clean clone commit config "
    "describe diff fetch grep init lfs log ls-files ls-remote merge mv pull push rebase reflog "
    "remote reset restore rev-parse revert rm show stash status submodule switch tag worktree",
    "gh": "api auth gist issue pr release repo run search secret workflow",
    "uv": "add build init lock pip publish python remove run sync tool venv",
    "npm": "add audit build ci exec init install link publish remove run start test update",
    "pnpm": "add audit build exec init install link publish remove run start test update",
    "yarn": "add audit build exec init install link publish remove run start test upgrade",
    "docker": "build compose exec images logs ps pull push rm rmi run start stop",
    "cargo": "add bench build check clippy doc fmt install run test update",
    "kubectl": "apply delete describe exec get logs rollout",
    "brew": "info install list search uninstall update upgrade",
    "pip": "download freeze install list show uninstall",
    "pip3": "download freeze install list show uninstall",
    "go": "build fmt get install mod run test vet",
    "poetry": "add install lock run update",
    "conda": "activate create env install list",
    "dotnet": "add build new publish restore run test",
    "apt": "install remove update upgrade",
    "apt-get": "install remove update upgrade",
    "systemctl": "daemon-reload disable enable is-active restart start status stop",
    "hf": "auth download repo upload",
}
SUBCOMMANDS = {tool: frozenset(names.split()) for tool, names in SUBCOMMANDS.items()}
# Programs worth a second word. Only a subcommand from the list above is kept:
# any other argument could be a name or a path the user never meant to share.
SUBCOMMAND_TOOLS = frozenset(SUBCOMMANDS)
# What may follow `uv run` and `python -m` in a template, for the same reason.
RUNNERS = frozenset(
    [
        "pytest",
        "ruff",
        "python",
        "python3",
        "mypy",
        "pyright",
        "black",
        "isort",
        "pre-commit",
        "faildex",
    ]
)
MODULES = frozenset(
    ["pytest", "venv", "pip", "unittest", "http.server", "json.tool", "build", "ruff", "mypy"]
)
# Words that only set up the real command.
SKIP_PROGRAMS = frozenset(["cd", "export", "set", "source", "pushd", "popd", "true", "echo"])
# Skipped programs that still decide the exit status of the line they are on.
OUTPUT_ONLY = frozenset(["echo", "true"])
WRAPPERS = frozenset(["sudo", "time", "env", "nohup", "command"])
# Shell and script syntax that can open a line without being a program.
KEYWORDS = frozenset(
    [
        "if",
        "then",
        "else",
        "elif",
        "fi",
        "for",
        "while",
        "do",
        "done",
        "case",
        "esac",
        "function",
        "foreach",
        "try",
        "catch",
        "finally",
        "break",
        "continue",
        "return",
        "declare",
        "local",
        "read",
        "mapfile",
        "exit",
        "false",
        "import",
        "from",
        "param",
        "switch",
    ]
)
# Programs accepted inside an inline PowerShell script, where most lines are data.
SCRIPT_PROGRAMS = SUBCOMMAND_TOOLS | frozenset(
    ["rg", "python", "python3", "py", "node", "ffmpeg", "curl", "powershell", "pwsh", "cmd"]
)
SCRIPT = "<script>"
# Flags that consume the next token, so it is not mistaken for a subcommand.
VALUE_FLAGS = frozenset(
    ["-C", "-c", "-n", "-H", "--namespace", "--context", "--git-dir", "--work-tree"]
)
_WINDOWS_PATH = re.compile(r"[A-Za-z]:\\")

_SEGMENTS = re.compile(r"\s*(?:&&|\|\||;|\n)\s*")
# A here-document or PowerShell here-string body is data, not commands.
_HEREDOC = re.compile(r"(<<-?\s*['\"]?(\w+)['\"]?[^\n]*)\n.*?\n\s*\2\b", re.DOTALL)
_HERE_STRING = re.compile(r"@(['\"]).*?\n\1@", re.DOTALL)
_PS_SCRIPT = re.compile(r"^\s*(\$[\w:]+\s*=|@['\"({]|\[)")
_EXCEPTION = re.compile(r"^(?:[A-Za-z_][\w.]*)?(Error|Exception|Exit|Interrupt|Warning)\s*(:|$)")
_CMDLET = re.compile(r"^[A-Z][a-z]+-[A-Za-z]+$")
_REDIRECT = re.compile(r"[<>|]")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_EXIT_LINE = re.compile(r"^(<error>)?\s*exit code:? -?\d+", re.IGNORECASE)
_NOISE_LINE = re.compile(
    r"^(wall time:|output:|at line:\d+ char:\d+|\+ |~+$|file \".*\", line \d+)", re.IGNORECASE
)
_ERROR_WORDS = re.compile(
    r"(error|not found|no such|fatal|failed|denied|cannot|can't|invalid|exception|unknown|"
    r"refused|refusing|rejected|couldn't|timed? ?out|no matches|unexpected|not recognized|is not a |usage:)",
    re.IGNORECASE,
)
_MASKS = [
    # A quoted string of any length, then one that never closes (the scan may
    # have cut it). A quote right after a letter is an apostrophe, not a string.
    (re.compile(r"(?<![A-Za-z0-9])(['\"`]).*?\1"), "<s>"),
    (re.compile(r"(?<![A-Za-z0-9])['\"`].*$"), "<s>"),
    (re.compile(r"[A-Za-z]:\\[^\s'\"<>|]+"), "<path>"),
    (re.compile(r"[a-z][a-z0-9+.\-]*://\S+", re.IGNORECASE), "<url>"),
    (re.compile(r"(?:\.{0,2}\\)?[\w\-.@+*]+(?:\\[\w\-.@+*]+)+\\?|\.{0,2}\\[\w\-.@+*]+"), "<path>"),
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
_COMMAND_NAME = re.compile(r"^[A-Za-z_](?:[\w.\-]*[A-Za-z0-9_])?$")
# "<file>:<line>:" opens a compiler message or a line of search output; only the
# first is a failure, and it says so right after the position.
_LOCATED = re.compile(r"^(?:\S+?\.\w{1,6}[:\-])?\d+[:\-](?:\d+[:\-])?\s*(.*)$")
_DIAGNOSTIC = re.compile(r"^(fatal |syntax )?(error|[A-Z]{1,4}\d{2,5})\b", re.IGNORECASE)
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
        elif not token.startswith("-") and not _REDIRECT.search(token):
            out.append(token)
    return out


def _program(token: str) -> str:
    name = re.split(r"[\\/]", token)[-1]
    return name[:-4] if name.lower().endswith(".exe") else name


def command_template(command: str) -> str | None:
    """Return "<program>" or "<program> <subcommand>" for the first real command."""
    found, fallback = _templates(command)
    return found[0] if found else fallback


def is_compound(command: str) -> bool:
    """True when the command line runs more than one program in sequence.

    The log then says only how the whole line ended, not which part failed or
    succeeded. `a || b` and `a; echo done` can even end well while `a` failed.
    """
    found, fallback = _templates(command)
    return len(found) > 1 or "||" in command or (bool(found) and fallback in OUTPUT_ONLY)


def _subcommand(program: str, args: list[str]) -> str | None:
    """The first argument that is a known subcommand of the program."""
    known = SUBCOMMANDS.get(program, frozenset())
    return next((a for a in args if a in known), None)


def _templates(command: str) -> tuple[list[str], str | None]:
    found: list[str] = []
    fallback = None
    script = bool(_PS_SCRIPT.match(command))
    if script and "\n" in command.strip():
        fallback = SCRIPT
    command = _HERE_STRING.sub("", _HEREDOC.sub(r"\1", command))
    for segment in _SEGMENTS.split(command.strip()):
        tokens = [t for t in _tokens(segment) if not _ASSIGNMENT.match(t)]
        while tokens and _program(tokens[0]) in WRAPPERS:
            tokens = tokens[1:]
        if not tokens or tokens[0].startswith(("#", "$")):
            continue  # comment, or a PowerShell variable assignment / invocation
        program = _program(tokens[0])
        if not _COMMAND_NAME.match(program) or _DATA_FILE.search(program):
            continue  # a file name or expression, not a command
        if program in KEYWORDS:
            continue
        if script and not (_CMDLET.match(program) or program in SCRIPT_PROGRAMS):
            continue  # inside a script most lines are data
        if program in SKIP_PROGRAMS:
            # An output-only program outranks pure setup, so is_compound can see it.
            if fallback is None or (program in OUTPUT_ONLY and fallback not in OUTPUT_ONLY):
                fallback = program if fallback != SCRIPT else fallback
            continue
        args = _positional(tokens[1:])
        if program in ("python", "python3", "py") and "-m" in tokens:
            index = tokens.index("-m")
            module = tokens[index + 1] if index + 1 < len(tokens) else ""
            module = module if module in MODULES else ""
            found.append(f"{program} -m {module}".strip())
        elif program == "uv" and args[:1] == ["run"] and len(args) > 1:
            inner = _program(args[1])
            found.append(f"uv run {inner}" if inner in RUNNERS else "uv run")
        elif _subcommand(program, args):
            found.append(f"{program} {_subcommand(program, args)}")
        else:
            found.append(program)
    return found, fallback


def _is_failure_line(line: str) -> bool:
    if not _ERROR_WORDS.search(line):
        return False
    located = _LOCATED.match(line)
    return not located or bool(_DIAGNOSTIC.match(located.group(1)))


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
    picked = None
    if any(line.startswith("Traceback") for line in lines):
        # The exception line, not whatever the program printed after it.
        picked = next((line for line in reversed(lines) if _EXCEPTION.match(line)), None)
        if picked is None:
            return None  # a stack with no exception line identifies nothing
    if picked is None:
        # Without an error word the line is ordinary output, which must not enter the graph.
        picked = next((line for line in lines if _is_failure_line(line)), None)
    if picked is None:
        return None
    picked = re.sub(r"<[^>]{1,40}>", "", picked)
    for pattern, mask in _MASKS:
        picked = pattern.sub(mask, picked)
    picked = re.sub(r"\s+", " ", picked).strip().lower()
    return picked[:MAX_SIG] or None
