import pytest

from faildex.normalize import command_template, error_signature

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
]

SIGNATURES = [
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
