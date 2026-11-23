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
WRAPPERS = frozenset(
    ["sudo", "time", "env", "nohup", "command", "timeout", "setsid", "nice", "stdbuf"]
)
# Wrapper options that take a value: the next word is a user, a directory, a signal.
WRAPPER_VALUE_FLAGS = frozenset(
    [
        "-u",
        "-g",
        "-C",
        "-n",
        "-k",
        "-s",
        "-p",
        "-h",
        "-r",
        "-t",
        "-T",
        "-i",
        "-o",
        "-e",
        "-D",
        "-U",
        "--user",
        "--group",
        "--chdir",
        "--signal",
        "--kill-after",
        "--host",
        "--role",
        "--type",
    ]
)
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

_COMMENT_LINE = re.compile(r"^[ \t]*#.*$", re.MULTILINE)
_CONTINUATION = re.compile(r"\\\r?\n")
_ANSIC_CONTINUATION = re.compile(r"\$(?:\\\r?\n)+'")
_BODY_PREFIX = re.compile(r"^(?:do|then|else|elif)(?:\s+|(?=[({])|$)")
_WRAPPER_ARG = re.compile(r"^(-.*|\d+(\.\d+)?[smhd]?)$")
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
    # Secrets first, before any other mask can split them: `api_key=...`, `token: ...`,
    # and token shapes that need no label (sk-..., ghp_..., xoxb-..., AKIA..., JWTs).
    (
        re.compile(
            r"\b((?:api|access|auth|secret|private)?[_-]?(?:key|token|secret)|password|passwd)"
            r"(\s*[=:]\s*)[^\s,;'\"`]{6,}",
            re.IGNORECASE,
        ),
        r"\1\2<secret>",
    ),
    (
        re.compile(
            r"\b(?:sk|pk|rk)[-_](?:live|test|proj|ant)?[-_]?[A-Za-z0-9_\-]{12,}"
            r"|\bgh[pousr]_[A-Za-z0-9]{20,}|\bxox[abprs]-[A-Za-z0-9\-]{10,}"
            r"|\bAKIA[0-9A-Z]{16}\b|\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+"
        ),
        "<secret>",
    ),
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
# zsh NOMATCH: `(eval):1: no matches found: README*` and `zsh:1: no matches found: *.py`
# are the same shell error; keep the glob out of the signature so they line up.
NOMATCH_SIG = "no matches found: <glob>"
_NOMATCH = re.compile(r"^(?:\(eval\)|zsh):(?:\d+:)?\s*no matches found:\s+\S+", re.IGNORECASE)
_LEGACY_NOMATCH = re.compile(
    r"^(?:\(eval\)|zsh):(?:<n>:|\d+:)?\s*no matches found:\s+\S+", re.IGNORECASE
)
# zsh `=` expansion: an unquoted word that starts with `==` (`echo =====`, `[ a == b ]`)
# makes zsh look up a command named after the rest, `(eval):1: ==== not found`. Like
# NOMATCH it happens in the shell before any program runs, whatever the program is.
EQUALS_SIG = "=<word> not found"
_EQUALS = re.compile(r"^(?:\(eval\)|zsh):(?:<n>:|\d+:)?\s*=\S* not found$", re.IGNORECASE)
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


def _in_windows_path(text: str, pos: int) -> bool:
    """True when the unquoted token up to `pos` starts with a Windows drive prefix."""
    j = pos
    while j > 0 and not text[j - 1].isspace() and text[j - 1] not in ";|&()<>\"'":
        j -= 1
    return bool(_WINDOWS_PATH.match(text[j : pos + 1]))


def _strip_here_strings(text: str) -> str:
    """Strip PowerShell `@'...'@` / `@"..."@` here-strings in linear time."""
    if "@'" not in text and '@"' not in text:
        return text
    out, i, n = [], 0, len(text)
    no_closer = {"'": False, '"': False}
    while i < n:
        if text[i : i + 2] in ("@'", '@"'):
            q = text[i + 1]
            if not no_closer[q]:
                closer = f"\n{q}@"
                end = text.find(closer, i + 2)
                if end >= 0:
                    i = end + len(closer)
                    continue
                no_closer[q] = True
        nxt_sq = text.find("@'", i + 1)
        nxt_dq = text.find('@"', i + 1)
        cands = [p for p in (nxt_sq, nxt_dq) if p >= 0]
        nxt = min(cands) if cands else n
        out.append(text[i:nxt])
        i = nxt
    return "".join(out)


def _bracket_glob_end(text: str, start: int) -> tuple[bool, int]:
    """(is_glob, scan_end) for `[` at `start` within its shell word."""
    j, n = start + 1, len(text)
    while j < n:
        ch = text[j]
        if ch.isspace() or ch in ";|&()<>\"'":
            return False, j
        if ch == "\\":
            j += 2
            continue
        if ch == "]":
            return True, j + 1
        j += 1
    return False, n


def _scan_shell(text: str, mode: str) -> bool:
    """Single-pass O(N) iterative scanner for multiline arith, unquoted `||`, globs or `==` words."""
    windows = bool(_WINDOWS_PATH.search(text))
    stack: list[list] = []  # frames: [kind, depth]
    arith_depth = 0
    no_more_bt = False
    no_more_sq = False
    no_rb_until = -1
    last_win_pos = -1
    last_win_j = 0
    last_win_res = False
    escaped_end = -1
    i, n = 0, len(text)

    def _push(kind: str, depth: int) -> None:
        nonlocal arith_depth
        stack.append([kind, depth])
        if kind == "arith":
            arith_depth += 1

    def _pop() -> None:
        nonlocal arith_depth
        kind, _ = stack.pop()
        if kind == "arith":
            arith_depth -= 1

    def _in_win_path_at(pos: int) -> bool:
        nonlocal last_win_pos, last_win_j, last_win_res
        limit = max(last_win_pos, 0)
        j = pos
        while j > limit and not text[j - 1].isspace() and text[j - 1] not in ";|&()<>\"'":
            j -= 1
        if j > limit or last_win_pos < 0:
            res = bool(_WINDOWS_PATH.match(text, j))
        else:
            j = last_win_j
            res = last_win_res
        last_win_pos, last_win_j, last_win_res = pos, j, res
        return res

    while i < n:
        ch = text[i]
        top = stack[-1][0] if stack else None

        if top == "arith":
            if mode == "arith" and ch == "\n":
                return True
            if text[i : i + 3] == "$((":
                _push("arith", 2)
                i += 3
                continue
            if text[i : i + 2] == "$(":
                _push("subst", 1)
                i += 2
                continue
            if ch == "(":
                stack[-1][1] += 1
            elif ch == ")":
                stack[-1][1] -= 1
                if stack[-1][1] == 0:
                    _pop()
            i += 1
            continue

        if top == "dq":
            if ch == "\\":
                i += 2
                continue
            if text[i : i + 3] == "$((":
                _push("arith", 2)
                i += 3
                continue
            if text[i : i + 2] == "${":
                _push("param", 1)
                i += 2
                continue
            if text[i : i + 2] == "$(":
                _push("subst", 1)
                i += 2
                continue
            if ch == "`":
                if not no_more_bt:
                    if text.find("`", i + 1) >= 0:
                        _push("bt", 0)
                        i += 1
                        continue
                    no_more_bt = True
                i += 1
                continue
            if ch == '"':
                _pop()
            i += 1
            continue

        if mode == "arith" and ch == "\n" and arith_depth > 0:
            return True

        if top == "bt":
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                _pop()
                i += 1
                continue

        if text[i : i + 2] == "\\\\" or text[i : i + 3] == "\\$'":
            i += 2
            continue

        if (
            ch == "\\"
            and ((not _in_win_path_at(i)) if mode in ("glob", "equals") else (not windows))
            and i + 1 < n
            and text[i + 1] != "\n"
        ):
            escaped_end = i + 2  # an escaped space joins words, it does not end one
            i += 2
            continue

        if text[i : i + 2] == "$'":
            i += 2
            while i < n:
                if text[i] == "\\":
                    i += 2
                elif text[i] == "'":
                    i += 1
                    break
                else:
                    i += 1
            continue

        if ch == "'":
            if i > 0 and text[i - 1].isalnum() and (no_more_sq or text.find("'", i + 1) < 0):
                no_more_sq = True
                i += 1
                continue
            end_sq = text.find("'", i + 1)
            i = n if end_sq < 0 else end_sq + 1
            continue

        if ch == '"':
            _push("dq", 0)
            i += 1
            continue

        if ch == "`":
            if not no_more_bt:
                if text.find("`", i + 1) >= 0:
                    _push("bt", 0)
                    i += 1
                    continue
                no_more_bt = True
            i += 1
            continue

        if ch == "#" and (i == 0 or text[i - 1].isspace()):
            end = text.find("\n", i)
            i = n if end < 0 else end + 1
            continue

        if text[i : i + 3] == "$((":
            _push("arith", 2)
            i += 3
            continue

        if text[i : i + 2] == "${":
            _push("param", 1)
            i += 2
            continue

        if text[i : i + 2] == "$(":
            _push("subst", 1)
            i += 2
            continue

        if text[i : i + 2] == "((" and (mode == "arith" or i == 0 or text[i - 1] in " \t\n;|&({"):
            _push("arith", 2)
            i += 2
            continue

        if (
            mode in ("glob", "equals")
            and text[i : i + 2] == "[["
            and (i == 0 or text[i - 1].isspace())
            and (i + 2 == n or text[i + 2].isspace())
        ):
            _push("bracket", 0)
            i += 2
            continue

        if top == "param":
            if ch == "{":
                stack[-1][1] += 1
                i += 1
                continue
            if ch == "}":
                stack[-1][1] -= 1
                if stack[-1][1] == 0:
                    _pop()
                i += 1
                continue

        if top == "subst":
            if ch == "(":
                stack[-1][1] += 1
                i += 1
                continue
            if ch == ")":
                stack[-1][1] -= 1
                if stack[-1][1] == 0:
                    _pop()
                i += 1
                continue

        if top == "bracket" and (
            text[i : i + 2] == "]]"
            and (i + 2 == n or text[i + 2].isspace() or text[i + 2] in ";&|)")
        ):
            _pop()
            i += 2
            continue

        active = top in (None, "subst", "bt")
        if active:
            if mode == "or" and text[i : i + 2] == "||":
                return True
            if (
                mode == "equals"
                and text[i : i + 2] == "=="
                and (i == 0 or text[i - 1] in " \t\n;|&(")
                and i != escaped_end
            ):
                return True
            if mode == "glob":
                if ch in "*?":
                    return True
                if ch == "[" and i >= no_rb_until:
                    matched, end_rb = _bracket_glob_end(text, i)
                    if matched:
                        return True
                    no_rb_until = end_rb

        i += 1

    return False


def _has_multiline_arith(command: str) -> bool:
    return "((" in command and _scan_shell(command, "arith")


def _skip_command(command: str) -> bool:
    """Return True for constructs skipped up front before command extraction."""
    return (
        "<<" in command
        or bool(_ANSIC_CONTINUATION.search(command))
        or _has_multiline_arith(command)
    )


def _has_unquoted_or(command: str) -> bool:
    if "||" not in command:
        return False
    return _scan_shell(_strip_here_strings(command), "or")


def _skip_wrapper_words(text: str) -> str:
    """Drop leading wrapper commands and their flags/assignments in linear time."""
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        j = i
        while j < n and not text[j].isspace():
            j += 1
        if _program(text[i:j]) not in WRAPPERS:
            return text[i:]
        i = j
        while i < n:
            while i < n and text[i].isspace():
                i += 1
            j = i
            while j < n and not text[j].isspace():
                j += 1
            arg = text[i:j]
            if arg.startswith("-") or _ASSIGNMENT.match(arg):
                i = j
                continue
            break
    return ""


def _match_function_header(segment: str) -> tuple[bool, bool]:
    """Return (is_function_def, is_header_only) in strict O(N) time."""
    text = _skip_wrapper_words(_CONTINUATION.sub(" ", segment).strip())
    if not text:
        return False, False
    i, n = 0, len(text)
    has_keyword = False
    if text.startswith("function") and (n == 8 or text[8].isspace()):
        has_keyword = True
        i = 8
        while i < n and text[i].isspace():
            i += 1
    name_start = i
    while i < n:
        ch = text[i]
        if text[i : i + 2] == "$'":
            i += 2
            closed = False
            while i < n:
                if text[i] == "\\":
                    i += 2
                elif text[i] == "\n":
                    return False, False
                elif text[i] == "'":
                    closed = True
                    i += 1
                    break
                else:
                    i += 1
            if not closed:
                return False, False
        elif ch in ("'", '"'):
            q = ch
            i += 1
            closed = False
            while i < n:
                if text[i] == "\n":
                    return False, False
                if text[i] == q:
                    closed = True
                    i += 1
                    break
                i += 1
            if not closed:
                return False, False
        elif ch.isspace() or ch in ";|&<>(){}#$" or text[i : i + 2] == "()":
            break
        else:
            i += 1
    if i == name_start:
        return False, False
    while i < n and text[i].isspace():
        i += 1
    has_parens = False
    if i < n and text[i] == "(":
        j = i + 1
        while j < n and text[j].isspace():
            j += 1
        if j < n and text[j] == ")":
            has_parens = True
            i = j + 1
            while i < n and text[i].isspace():
                i += 1
    if not has_keyword and not has_parens:
        return False, False
    is_head = i == n
    is_def = is_head or text[i] in "{("
    return is_def, is_head


def _is_function_def(segment: str) -> bool:
    return _match_function_header(segment)[0]


def _is_function_head(segment: str) -> bool:
    return _match_function_header(segment)[1]


def _continues_into_function_body(
    command: str,
    start: int,
    nl: int,
    pieces: list[str] | None = None,
    piece_start: int = 0,
) -> tuple[bool, int]:
    """(should_join, skip_until) for newlines inside or after a function header in O(N)."""
    n = len(command)
    if pieces:
        head = _CONTINUATION.sub(" ", "".join(pieces) + command[piece_start:nl]).strip()
        match = _BODY_PREFIX.match(head)
        if match:
            head = head[match.end() :].lstrip()
        if _is_function_head(head):
            k = nl + 1
            while k < n and command[k].isspace():
                k += 1
            if k < n and command[k] in "{(":
                return True, max(nl, k - 1)
        return False, -1

    def _skip_hspace_cont(pos: int) -> int:
        while pos < n:
            ch = command[pos]
            if ch in " \t":
                pos += 1
            elif command[pos : pos + 2] == "\\\n":
                pos += 2
            elif command[pos : pos + 3] == "\\\r\n":
                pos += 3
            else:
                break
        return pos

    def _read_word_stop(pos: int) -> int:
        q = pos
        while q < n and not command[q].isspace():
            if command[q : q + 2] == "\\\n" or command[q : q + 3] == "\\\r\n":
                break
            q += 1
        return q

    p = _skip_hspace_cont(start)
    for kw in ("do", "then", "else", "elif"):
        if command.startswith(kw, p):
            end_kw = p + len(kw)
            if (
                end_kw == n
                or command[end_kw].isspace()
                or command[end_kw] in "({"
                or command[end_kw : end_kw + 2] == "\\\n"
                or command[end_kw : end_kw + 3] == "\\\r\n"
            ):
                p = _skip_hspace_cont(end_kw)
                break

    dead_until = -1
    while p < n:
        if command[p : p + 2] == "()":
            break
        q = _read_word_stop(p)
        word = command[p:q]
        if not word or _program(word) not in WRAPPERS:
            break
        next_p = _skip_hspace_cont(q)
        while next_p < n:
            r = _read_word_stop(next_p)
            arg = command[next_p:r]
            if arg and (arg.startswith("-") or _ASSIGNMENT.match(arg)):
                next_p = _skip_hspace_cont(r)
                continue
            break
        dead_until = max(dead_until, p)
        p = next_p

    has_keyword = False
    if command.startswith("function", p):
        after_kw = p + 8
        if (
            after_kw == n
            or command[after_kw] in " \t"
            or command[after_kw : after_kw + 2] == "\\\n"
            or command[after_kw : after_kw + 3] == "\\\r\n"
        ):
            has_keyword = True
            p = _skip_hspace_cont(after_kw)

    name_start = p
    while p < n:
        ch = command[p]
        if command[p : p + 2] == "$'":
            p += 2
            closed = False
            while p < n:
                if command[p] == "\\":
                    if command[p : p + 2] == "\\\n" or command[p : p + 3] == "\\\r\n":
                        return False, dead_until
                    p += 2
                elif command[p] == "\n":
                    return False, dead_until
                elif command[p] == "'":
                    closed = True
                    p += 1
                    break
                else:
                    p += 1
            if not closed:
                return False, dead_until
        elif ch in ("'", '"'):
            q = ch
            p += 1
            closed = False
            while p < n:
                if command[p] == "\n":
                    return False, dead_until
                if command[p] == q:
                    closed = True
                    p += 1
                    break
                p += 1
            if not closed:
                return False, dead_until
        elif (
            ch.isspace()
            or ch in ";|&<>(){}#$"
            or command[p : p + 2] == "()"
            or command[p : p + 2] == "\\\n"
            or command[p : p + 3] == "\\\r\n"
        ):
            break
        else:
            p += 1
    if p == name_start:
        return False, dead_until

    p = _skip_hspace_cont(p)
    has_parens = False
    if p < n and command[p] == "(":
        q = _skip_hspace_cont(p + 1)
        if q < n and command[q] == ")":
            has_parens = True
            p = _skip_hspace_cont(q + 1)

    if not has_keyword and not has_parens:
        return False, dead_until
    if p < nl and not (command[p] == "\r" and p + 1 == nl):
        return False, dead_until
    while p < n and command[p].isspace():
        p += 1
    if p < n and command[p] in "{(":
        return True, max(nl, p - 1)
    return False, dead_until


def is_nomatch_sig(sig: str) -> bool:
    """True for the pooled NOMATCH key or an older unpooled zsh NOMATCH signature."""
    return sig == NOMATCH_SIG or bool(_LEGACY_NOMATCH.match(sig))


def is_equals_sig(sig: str) -> bool:
    """True for the pooled zsh `=` expansion key or an older unpooled one."""
    return sig == EQUALS_SIG or bool(_EQUALS.match(sig))


def shell_sig(sig: str) -> str | None:
    """The pooled key of a shell-level zsh failure (NOMATCH or `=` expansion), else None."""
    if is_nomatch_sig(sig):
        return NOMATCH_SIG
    if is_equals_sig(sig):
        return EQUALS_SIG
    return None


def _peel_simple_group(segment: str) -> str:
    """Iteratively unwrap outer `( ... )` / `{ ... }` when no split chars exist inside."""
    lo, hi = 0, len(segment)
    while hi - lo >= 2 and not segment.startswith("((", lo):
        first, last = segment[lo], segment[hi - 1]
        if (first, last) not in (("(", ")"), ("{", "}")):
            break
        if any(sep in segment[lo + 1 : hi - 1] for sep in (";", "\n", "&&", "||")):
            break
        lo += 1
        hi -= 1
        while lo < hi and segment[lo].isspace():
            lo += 1
        while hi > lo and segment[hi - 1].isspace():
            hi -= 1
    return segment[lo:hi]


def _has_unquoted(command: str, mode: str) -> bool:
    """True when an executable part of `command` matches the scanner `mode` unquoted."""
    if _skip_command(command):
        return False
    cleaned = _COMMENT_LINE.sub("", _strip_here_strings(command))
    pending = [cleaned]
    while pending:
        chunk = pending.pop()
        for segment in _segments(chunk):
            match = _BODY_PREFIX.match(segment)
            if match:
                segment = segment[match.end() :].lstrip()
            if not segment or _is_function_def(segment):
                continue
            segment = _peel_simple_group(segment)
            if not segment or _is_function_def(segment):
                continue
            if (segment[:1], segment[-1:]) in (("(", ")"), ("{", "}")) and not segment.startswith(
                "(("
            ):
                pending.append(segment[1:-1])
                continue
            if _scan_shell(segment, mode):
                return True
    return False


def has_unquoted_glob(command: str) -> bool:
    """True when an executable part of `command` contains an unquoted shell glob."""
    return _has_unquoted(command, "glob")


def has_unquoted_equals(command: str) -> bool:
    """True when an executable part of `command` has an unquoted word starting with `==`.

    zsh expands such a word (`=====`, the `==` of `[ a == b ]`) to the path of a
    command named after the rest, and fails with `<rest> not found` when there is none.
    """
    return "==" in command and _has_unquoted(command, "equals")


def command_template(command: str) -> str | None:
    """Return "<program>" or "<program> <subcommand>" for the first real command."""
    if _skip_command(command):
        return None
    found, fallback = _templates(command)
    return found[0] if found else fallback


def command_templates(command: str) -> list[str]:
    """Every distinct program template a command line runs, in order.

    `ls && git status` gives ["ls", "git status"], so a pre-run check can look
    up each part, not only the first.
    """
    if _skip_command(command):
        return []
    found, fallback = _templates(command)
    unique = list(dict.fromkeys(found))
    return unique or ([fallback] if fallback else [])


def is_compound(command: str) -> bool:
    """True when the command line runs more than one program in sequence.

    The log then says only how the whole line ended, not which part failed or
    succeeded. `a || b` and `a; echo done` can even end well while `a` failed.
    """
    if _skip_command(command):
        return False
    found, fallback = _templates(command)
    return len(found) > 1 or _has_unquoted_or(command) or (bool(found) and fallback in OUTPUT_ONLY)


def _subcommand(program: str, args: list[str]) -> str | None:
    """The first argument that is a known subcommand of the program."""
    known = SUBCOMMANDS.get(program, frozenset())
    return next((a for a in args if a in known), None)


def _segments(command: str) -> list[str]:
    """Split a command line at `;`, `&&`, `||` and newlines that are really separators.

    A separator inside quotes, a `$( )` substitution, parentheses or braces
    belongs to an argument or a block, not to the sequence of commands: text
    in an `echo '...; ...'` or the rows of a PowerShell array are not programs.
    """
    windows = bool(_WINDOWS_PATH.search(command))
    parts: list[str] = []
    pieces: list[str] = []
    start = piece_start = depth = 0
    checked_cont_until = -1
    join_until = -1
    quote: str | None = None
    ansi = False
    i, n = 0, len(command)
    while i < n:
        char = command[i]
        if quote:
            if char == "\\" and (quote == '"' or ansi):
                i += 1
            elif char == quote:
                quote, ansi = None, False
        elif (
            command[i : i + 2] == "\\\\"
            or command[i : i + 3] == "\\$'"
            or (char == "\\" and not windows and i + 1 < n and command[i + 1] != "\n")
        ):
            i += 1
        elif command[i : i + 2] == "$'":
            quote, ansi = "'", True
            i += 1
        elif char in "'\"`":
            # A quote right after a letter is an apostrophe in prose, not a string.
            if not (char == "'" and i and command[i - 1].isalnum()):
                quote, ansi = char, False
        elif char == "#" and (i == 0 or command[i - 1].isspace()):
            # A comment runs to the end of its line; omit its text without copying the whole string.
            pieces.append(command[piece_start:i])
            end = command.find("\n", i)
            if end < 0:
                piece_start = n
                i = n
                break
            pieces.append(" ")
            piece_start = end
            i = end
            continue
        elif char in "({":
            depth += 1
        elif char in ")}":
            depth = max(0, depth - 1)
        elif depth == 0:
            width = 2 if command[i : i + 2] in ("&&", "||") else 1 if char in ";\n" else 0
            if width and char == "\n":
                if i <= join_until:
                    i += 1
                    continue
                if i > checked_cont_until:
                    joined, skip_until = _continues_into_function_body(
                        command, start, i, pieces, piece_start
                    )
                    if joined:
                        join_until = skip_until
                        i += 1
                        continue
                    checked_cont_until = max(checked_cont_until, skip_until)
            if width:
                pieces.append(command[piece_start:i])
                parts.append("".join(pieces))
                pieces.clear()
                start = piece_start = i + width
                i += width
                continue
        i += 1
    pieces.append(command[piece_start:])
    parts.append("".join(pieces))
    return [part.strip() for part in parts if part.strip()]


def _strip_assignments(segment: str) -> str:
    """Drop leading `NAME=value` words, where a value may be quoted or a `$( )`."""
    pos, n = 0, len(segment)
    while pos < n:
        match = _ASSIGNMENT.match(segment, pos)
        if not match:
            break
        i, depth, quote = match.end(), 0, None
        while i < n:
            char = segment[i]
            if quote:
                quote = None if char == quote else quote
            elif char in "'\"`":
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif char.isspace() and depth == 0:
                break
            i += 1
        while i < n and segment[i].isspace():
            i += 1
        pos = i
    return segment[pos:]


def _commands(command: str) -> list[str]:
    """The command lines of a script, with `( ... )` and `{ ...; }` groups opened up."""
    out: list[str] = []
    stack: list[tuple[bool, str]] = [(True, command)]
    while stack:
        is_chunk, item = stack.pop()
        if not is_chunk:
            out.append(item)
            continue
        children: list[tuple[bool, str]] = []
        for segment in _segments(item):
            segment = _peel_simple_group(_strip_assignments(segment))
            if not segment:
                continue
            grouped = (segment[:1], segment[-1:]) in (
                ("(", ")"),
                ("{", "}"),
            ) and not segment.startswith("((")
            children.append((True, segment[1:-1]) if grouped else (False, segment))
        stack.extend(reversed(children))
    return out


def _templates(command: str) -> tuple[list[str], str | None]:
    found: list[str] = []
    fallback = None
    script = bool(_PS_SCRIPT.match(command))
    if script and "\n" in command.strip():
        fallback = SCRIPT
    command = _COMMENT_LINE.sub("", _strip_here_strings(command))
    for segment in _commands(command):
        if _is_function_def(segment):
            continue  # `name() {...}` defines a function; it runs nothing
        tokens = [t for t in _tokens(segment) if not _ASSIGNMENT.match(t)]
        while tokens and _program(tokens[0]) in WRAPPERS:
            tokens = tokens[1:]
            # Options of the wrapper, with their values, are not the program.
            while tokens:
                if tokens[0] in WRAPPER_VALUE_FLAGS:
                    tokens = tokens[2:]
                elif _WRAPPER_ARG.match(tokens[0]) or _ASSIGNMENT.match(tokens[0]):
                    tokens = tokens[1:]
                else:
                    break
        if (
            not tokens
            or tokens[0].startswith(("#", "$"))
            or tokens[1:2] == ["()"]
            or tokens[1:3] == ["(", ")"]
            or tokens[0] == "function"
        ):
            continue  # comment, function definition, or PowerShell variable assignment / invocation
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
    if _NOMATCH.match(picked):
        picked = NOMATCH_SIG
    elif _EQUALS.match(picked):
        picked = EQUALS_SIG
    else:
        picked = re.sub(r"<[^>]{1,40}>", "", picked)
        for pattern, mask in _MASKS:
            picked = pattern.sub(mask, picked)
    picked = re.sub(r"\s+", " ", picked).strip().lower()
    return picked[:MAX_SIG] or None
