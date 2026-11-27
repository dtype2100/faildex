"""The bench tasks: situations where agents often hit a failure faildex knows.

Each prompt asks for an ordinary piece of work and carries no hint about the
failure. Every run gets a fresh folder built by `setup`; `targets` are the
failure keys (prefixes) the task is about; `success` says whether the work got done.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

NOT_A_REPO = "fatal: not a git repository"
NO_INDEX = "usage: git diff --no-index"
EQUALS = "=<word> not found"
NOMATCH = "no matches found: <glob>"

# The answer says the folder is not under git (any wording).
_NOT_GIT = re.compile(
    r"\b(not|isn't|is not|no|without)\b[^.\n]{0,60}\bgit\b"
    r"|\bgit\b[^.\n]{0,60}\b(not (?:initiali[sz]ed|a repo|available|found)|no repo)"
    r"|not (?:under|in) version control|no version control|no commits?\b",
    re.IGNORECASE,
)


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=bench", "-c", "user.email=bench@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


APP = "def main():\n    print('hello')\n\n\nif __name__ == '__main__':\n    main()\n"


def changes_setup(root: Path, repo: bool) -> None:
    _write(root, {"app.py": APP, "notes.md": "# Notes\n\n- ship v1\n"})
    if repo:
        _git(root, "init", "-q")
        _git(root, "add", ".")
        _git(root, "commit", "-q", "-m", "first")
        _write(
            root, {"app.py": APP.replace("'hello'", "'hello, bench'"), "todo.txt": "write docs\n"}
        )


def diff_setup(root: Path, repo: bool) -> None:
    _write(root, {"config.ini": "[server]\nport = 8080\nhost = localhost\n"})
    if repo:
        _git(root, "init", "-q")
        _git(root, "add", ".")
        _git(root, "commit", "-q", "-m", "first")
        _write(root, {"config.ini": "[server]\nport = 9090\nhost = localhost\n"})


TASKS = [
    {
        "id": "changes-outside",
        "prompt": "Summarize the uncommitted changes in this project.",
        "setup": lambda root: changes_setup(root, repo=False),
        "targets": [NOT_A_REPO],
        "success": lambda root, answer, outputs: bool(_NOT_GIT.search(answer)),
        "success_means": "the answer says the folder is not under git",
    },
    {
        "id": "diff-outside",
        "prompt": "Show me what changed in config.ini since the last commit.",
        "setup": lambda root: diff_setup(root, repo=False),
        "targets": [NO_INDEX, NOT_A_REPO],
        "success": lambda root, answer, outputs: bool(_NOT_GIT.search(answer)),
        "success_means": "the answer says the folder is not under git",
    },
    {
        "id": "changes-inside",
        "prompt": "Summarize the uncommitted changes in this project.",
        "setup": lambda root: changes_setup(root, repo=True),
        "targets": [NOT_A_REPO],
        "success": lambda root, answer, outputs: "app.py" in answer and "todo" in answer,
        "success_means": "the answer names app.py and todo.txt",
    },
    {
        "id": "diff-inside",
        "prompt": "Show me what changed in config.ini since the last commit.",
        "setup": lambda root: diff_setup(root, repo=True),
        "targets": [NO_INDEX, NOT_A_REPO],
        "success": lambda root, answer, outputs: "9090" in answer,
        "success_means": "the answer gives the new port 9090",
    },
    {
        "id": "banner",
        "prompt": (
            "In the terminal, print the names of the files in this folder between "
            "two ========== separator lines."
        ),
        "setup": lambda root: _write(root, {"a.txt": "a\n", "b.txt": "b\n", "c.txt": "c\n"}),
        "targets": [EQUALS],
        "success": lambda root, answer, outputs: any(
            "==========" in out and "a.txt" in out for out in outputs
        ),
        "success_means": "one successful shell output holds the separator and the names",
    },
    {
        "id": "cleanup",
        "prompt": "Delete every .log and .tmp file in this folder, then tell me which files are left.",
        "setup": lambda root: _write(root, {"a.tmp": "", "b.tmp": "", "keep.txt": "keep\n"}),
        "targets": [NOMATCH],
        "success": lambda root, answer, outputs: (
            not (root / "a.tmp").exists()
            and not (root / "b.tmp").exists()
            and (root / "keep.txt").exists()
        ),
        "success_means": "a.tmp and b.tmp are gone and keep.txt is still there",
    },
    {
        "id": "count-py",
        "prompt": "How many .py files are in this folder, including subfolders? Use the shell.",
        "setup": lambda root: _write(
            root,
            {
                "src/a.py": "",
                "src/pkg/b.py": "",
                "tests/test_c.py": "",
                "README.md": "# demo\n",
            },
        ),
        "targets": [NOMATCH],
        "success": lambda root, answer, outputs: bool(
            re.search(r"\b(3|three)\b", answer, re.IGNORECASE)
        ),
        "success_means": "the answer says 3",
    },
]
