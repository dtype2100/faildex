import pytest

from faildex.normalize import command_template, command_templates, error_signature

COMMANDS = [
    ("git status", "git status"),
    ("git -C repo push origin main", "git push"),
    ("cd src && pytest -q", "pytest"),
    ("FOO=1 BAR=2 npm run build", "npm run"),
    ("sudo docker compose up -d", "docker compose"),
    ("python3 -m pytest tests", "python3 -m pytest"),
    ("uv run pytest -q", "uv run pytest"),
    ("/usr/local/bin/gh api repos/x/y", "gh api"),
    ("ls -la | head -3", "ls"),
    ("echo ====", "echo"),
    ("cd /tmp; export A=1", "cd"),
    (r"C:\tools\dotnet.exe build app.sln", "dotnet build"),
    ("Get-ChildItem -Recurse src", "Get-ChildItem"),
    (r"$p='src\app\Program.cs'; Get-Content $p", "Get-Content"),
    ("$i=0; $j", None),
    ("notes.md", None),
    ("echo 'creds in ~/x; ALL repos public' >> notes", "echo"),
    ("# check the runner; look at what it does\ngit status", "git status"),
    ('geo=$(hyprctl clients -j | jq .x) && grim -g "$geo" out.png', "grim"),
    ("BASE=$(git rev-parse origin/main); git fetch -q origin", "git fetch"),
    ("timeout 180 bin/hyprbench run --task x", "hyprbench"),
    ("sudo -u customer-secret git status", "git status"),
    ("env -C /Users/alice/private git status", "git status"),
    ("ROOT=$(pwd) git status; pytest -q", "git status"),
    ("CODE=$(cat /tmp/code | tr -d '-')\nnode run.mjs", "node"),
    ("git status # TODO (slow\npytest -q", "git status"),
    ("fill() { node cdp.mjs eval x; }\ngit status", "git status"),
    ("setsid chromium --no-first-run >/dev/null 2>&1 &", "chromium"),
    ('node -e "\nconst run = async () => {\n  also();\n};\n"', "node"),
    (
        "& {\n$roots = @(\n'M:\\b2t\\arch294_loading03',\n'M:\\b2t\\arch295_press'\n);\nforeach ($r in $roots) { Import-Csv $r }\n}",
        None,
    ),
    ("npm --prefix /Users/alice/private run build", "npm run"),
    ("npm --prefix customer-secret run build", "npm run"),
    ("git customer-secret", "git"),
    ("uv run customer-secret", "uv run"),
    ("python -m customer_secret", "python -m"),
    ("make customer-secret", "make"),
    ("git /Users/alice/private", "git"),
    ("uv run ./scripts/secret-name.py", "uv run"),
    ("python -m /Users/alice/x", "python -m"),
    ("if [ -f a ]; then\n  git status\nfi", "git status"),
    ("for f in *.x; do ls README*; done", "ls"),
    ("for d in a b; do ( ls README* ); done", "ls"),
    ("( ls README* readme* )", "ls"),
    ("cd /tmp && ( ls README* )", "ls"),
    ("f=$(ls README* readme* | head -1)", "ls"),
    ('echo "$(ls README*)"', "ls"),
    ("echo '$(ls README*)'", "echo"),
    ("git status # $(ls README*)", "git status"),
    (
        'cd ~ && for d in a b; do ( cd "$d" && { git log -1; f=$(ls README* readme* | head -1); } ); done',
        "git log",
    ),
    ("cat <<'EOF' > notes\nplain words here\nEOF\ngit add notes", "cat"),
    ("gh 2>/dev/null", "gh"),
    ("$roots = @(\n'arch294_loading03',\n'arch295_press'\n)\nGet-Item $roots", "Get-Item"),
    ("$rows = @{\n  diamond = 'a'\n}\n$rows.diamond", "<script>"),
    ("$text = @'\nimport math\nprint(1)\n'@\n$text | python -", "<script>"),
]

SIGNATURES = [
    ('error: "customer-secret-' + "x" * 210 + '"', "error: <s>"),
    ('error: cannot open "customer-secret-never-closed', "error: cannot open <s>"),
    (
        "the user doesn't want this; it can't proceed: error",
        "the user doesn't want this; it can't proceed: error",
    ),
    ("Traceback (most recent call last):\nKeyError: 1\nMY_PRIVATE_DATA", "keyerror: <n>"),
    ("Traceback (most recent call last):\n  File x\nplain words", None),
    (
        'Traceback (most recent call last):\n  File "/src/error.py", line 1\nException: boom\nordinary',
        "exception: boom",
    ),
    ('Traceback (most recent call last):\n  File "/src/error.py", line 1\nordinary output', None),
    (
        r"rg: src\app\Frame*.cs: The system cannot find the file",
        "rg: <path>: the system cannot find the file",
    ),
    (
        "src/a.c:10:5: error: unknown type name 'foo'",
        "<path>:<n>:<n>: error: unknown type name <s>",
    ),
    ("src/app.cs:12: throw new InvalidOperationException(x);", None),
    ('12: Console.Error.WriteLine("usage error: needs [start]', None),
    ("(eval):1: no matches found: README*", "no matches found: <glob>"),
    ("(eval):3: no matches found: --include=*.py", "no matches found: <glob>"),
    ("zsh:1: no matches found: .aider*", "no matches found: <glob>"),
    ("zsh:12: no matches found: src/*.yaml", "no matches found: <glob>"),
    ("Exit code 1\n(eval):1: ==== not found", "(eval):<n>: ==== not found"),
    ("(eval):3: ===== not found", "(eval):<n>: ===== not found"),
    (
        "Traceback (most recent call last):\n  File \"/a/b.py\", line 3\nKeyError: 'name'",
        "keyerror: <s>",
    ),
    (
        "fatal: not a git repository (or any of the parent directories): .git",
        "fatal: not a git repository (or any of the parent directories): .git",
    ),
    (
        (
            "Exit code: 1\nWall time: 0.6 seconds\nOutput:\n\nAt line:1 char:5\n"
            "The term 'foo' is not recognized as the name of a cmdlet"
        ),
        "the term <s> is not recognized as the name of a cmdlet",
    ),
    ("cat: /Users/me/x/y.txt: No such file or directory", "cat: <path>: no such file or directory"),
    (
        r"Cannot find path 'C:\Users\me\x' because it does not exist.",
        "cannot find path <s> because it does not exist.",
    ),
    ("command timed out after 120000 milliseconds", "command timed out after <n> milliseconds"),
    ("ModuleNotFoundError: No module named 'relate'", "modulenotfounderror: no module named <s>"),
    (
        "ERROR: file or directory not found: tests/test_billing.py",
        "error: file or directory not found: <path>",
    ),
    (
        "fatal: Could not resolve host: git.acme-internal.example",
        "fatal: could not resolve host: <host>",
    ),
    (
        "fatal: unable to access 'https://github.com/a/b.git/': timeout",
        "fatal: unable to access <s>: timeout",
    ),
]


@pytest.mark.parametrize(("command", "expected"), COMMANDS)
def test_command_template(command, expected):
    assert command_template(command) == expected


@pytest.mark.parametrize(("text", "expected"), SIGNATURES)
def test_error_signature(text, expected):
    assert error_signature(text) == expected


def test_same_failure_in_two_sessions_gets_one_signature():
    first = error_signature("cat: /Users/alice/repo/a.txt: No such file or directory")
    second = error_signature("cat: /home/bob/other/b.txt: No such file or directory")
    assert first == second


def test_empty_output_has_no_signature():
    assert error_signature("Exit code 1\n\n") is None
    assert command_template("   ") is None


def test_plain_output_is_not_a_signature():
    assert error_signature("sites/findings.md:12: - it is a mere backend selector") is None


COMPOUND_GLOBS = [
    (
        "for f in *.x; do ls README*; done",
        ["ls"],
    ),
    (
        "for d in a b; do ( ls README* ); done",
        ["ls"],
    ),
    (
        "( ls README* readme* )",
        ["ls"],
    ),
    (
        "cd /tmp && ( ls README* )",
        ["ls"],
    ),
    (
        "f=$(ls README* readme* | head -1)",
        ["ls"],
    ),
    (
        'echo "$(ls README*)"',
        ["ls"],
    ),
    (
        "echo '$(ls README*)'",
        ["echo"],
    ),
    (
        "git status # $(ls README*)",
        ["git status"],
    ),
    (
        'cd ~ && for d in a b; do ( cd "$d" && { git log -1; f=$(ls README* readme* | head -1); } ); done',
        ["git log", "ls"],
    ),
]


@pytest.mark.parametrize(("command", "expected"), COMPOUND_GLOBS)
def test_command_templates_open_for_subshell_and_substitution(command, expected):
    """A glob inside a loop, a `( … )` group, or `$(…)` is still a command to look up."""
    assert command_templates(command) == expected


def test_zsh_glob_failures_share_one_signature():
    """Literal globs must not split the same zsh NOMATCH error across keys."""
    eval_sig = error_signature("(eval):1: no matches found: README*")
    zsh_sig = error_signature("zsh:1: no matches found: --include=*.py")
    assert eval_sig == zsh_sig == "no matches found: <glob>"


def test_compound_means_several_different_programs():
    from faildex.normalize import is_compound

    assert is_compound("git status && python -c 'raise ValueError()'")
    assert not is_compound("cd repo && git status")
    assert not is_compound("git status | head -3")
    assert is_compound("python pass.py; python fail.py")
    assert is_compound("git push || echo ignored")
    assert is_compound("ROOT=$(pwd) git status; pytest -q")
    assert is_compound("git status && (pytest -q; ruff check .)")
    assert is_compound("git status # TODO (slow\npytest -q")
    assert is_compound("geo=$(hyprctl clients -j | jq .x)\ngrim out.png")
    assert is_compound("git push; echo done")
    assert not is_compound("echo hello")


@pytest.mark.parametrize(
    "command, expected",
    [
        ("cat <<'EOF'\n$(private_customer_command)\nEOF", ["cat"]),
        ("cat <<EOF\n$(private_customer_command)\nEOF\ngit status", ["cat", "git status"]),
        ("private_function() { value=$(private_customer_command); }", []),
        (
            "function private_function { value=$(private_customer_command); }\ngit status",
            ["git status"],
        ),
        (
            "( private_function() { value=$(private_customer_command); }; git status )",
            ["git status"],
        ),
    ],
)
def test_data_and_function_substitutions_never_become_commands(command, expected):
    assert command_templates(command) == expected
    assert command_template(command) == (expected[0] if expected else None)


@pytest.mark.parametrize(
    "command",
    [
        "cat <<'END-DATA'\n$(private_customer_command)\nEND-DATA",
        "private_function()\n{ value=$(private_customer_command); }",
        "function private_function\n{ value=$(private_customer_command); }",
        "f=$(private_function() { value=$(private_customer_command); })",
    ],
)
def test_nested_and_multiline_data_never_become_commands(command):
    expected = ["cat"] if command.startswith("cat ") else []
    assert command_templates(command) == expected


def test_assignment_substitution_pipeline_does_not_prove_recovery():
    from faildex.normalize import is_compound

    assert is_compound("f=$(ls README* | head -1)")
    assert is_compound("f=$(ls README*); git status")
    assert not is_compound("f=$(ls README*)")


@pytest.mark.parametrize("prefix", ["zsh:", "zsh:12:", "(eval):", "(eval):3:"])
def test_nomatch_without_line_number_masks_the_entire_glob(prefix):
    assert (
        error_signature(f"{prefix} no matches found: private-customer-*")
        == "no matches found: <glob>"
    )


@pytest.mark.parametrize(
    "command",
    [
        "cat <<A <<B\nfirst\nA\n$(private_customer_command)\nB",
        "cat <<\\EOF\n$(private_customer_command)\nEOF",
        "cat <<'END DATA'\n$(private_customer_command)\nEND DATA",
        "cat <<EOF\n$(private_customer_command)",
    ],
)
def test_unrecognized_heredocs_fail_closed(command):
    assert command_templates(command) == []
    assert command_template(command) is None
