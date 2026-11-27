"""Hook payloads for tests: what Claude Code hands `faildex hook` after a failed Bash call."""

import json

# The failure the public demo store holds for `git status` in many sessions.
NOT_A_REPO = "fatal: not a git repository (or any of the parent directories): .git"


def failed(command: str, error: str = NOT_A_REPO, code: int = 1, session: str = "s-test") -> str:
    """A PostToolUseFailure payload for `command` failing with `error` (after `Exit code N`)."""
    return json.dumps(
        {
            "session_id": session,
            "hook_event_name": "PostToolUseFailure",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "tool_use_id": "toolu_test",
            "error": f"Exit code {code}\n{error}",
            "is_interrupt": False,
        }
    )


def git_status(command: str = "git status") -> str:
    """`git status` (or a line with it first) failing outside a repository."""
    return failed(command, NOT_A_REPO, 128)
