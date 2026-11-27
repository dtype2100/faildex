"""`faildex link` puts faildex's Claude Code hook (PostToolUseFailure) into
~/.claude/settings.json, and `faildex link --remove` takes it out again.

Every test works in a temporary home; none touches the real one.
"""

import json
from pathlib import Path

import pytest

from faildex.agent_hooks import _faildex_hook_command, configure_claude
from faildex.cli import main
from faildex.link import link, unlink

OURS = {"type": "command", "command": "faildex hook --agent claude", "timeout": 5}
INSTALLED = {"hooks": {"PostToolUseFailure": [{"matcher": "Bash", "hooks": [OURS]}]}}
OTHER = {"type": "command", "command": "herdr hook", "timeout": 3}


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def _settings(home: Path) -> Path:
    return home / ".claude" / "settings.json"


def _write(home: Path, data) -> Path:
    path = _settings(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=4) + "\n")
    return path


def _backups(home: Path) -> list[Path]:
    return sorted(_settings(home).parent.glob("settings.json.faildex-backup-*"))


def _step(steps):
    (step,) = [s for s in steps if s.agent == "Claude Code" and s.what == "hooks"]
    return step


def _link(home, tmp_path, **kwargs):
    return _step(link(tmp_path / "rules.md", home, **kwargs))


def _unlink(home, tmp_path, **kwargs):
    return _step(unlink(tmp_path / "rules.md", home, **kwargs))


def test_no_settings_file_gets_one_with_only_our_hook(home, tmp_path):
    step = _link(home, tmp_path)
    assert step.status == "installed" and "/hooks" in step.note
    assert json.loads(_settings(home).read_text()) == INSTALLED
    assert _backups(home) == []


def test_other_keys_and_hooks_are_kept_in_order_and_a_backup_is_made(home, tmp_path):
    original = {
        "model": "opus",
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [OTHER]}],
            "PostToolUseFailure": [{"matcher": "Edit", "hooks": [OTHER]}],
            "Stop": [{"hooks": [OTHER]}],
        },
        "permissions": {"allow": ["Bash(ls:*)"]},
    }
    path = _write(home, original)
    before = path.read_bytes()
    assert _link(home, tmp_path).status == "installed"
    data = json.loads(path.read_text())
    assert list(data) == ["model", "hooks", "permissions"]
    assert list(data["hooks"]) == ["PreToolUse", "PostToolUseFailure", "Stop"]
    assert data["hooks"]["PostToolUseFailure"] == [
        {"matcher": "Edit", "hooks": [OTHER]},
        {"matcher": "Bash", "hooks": [OURS]},
    ]
    assert {k: v for k, v in data.items() if k != "hooks"} == {
        k: v for k, v in original.items() if k != "hooks"
    }
    assert data["hooks"]["PreToolUse"] == original["hooks"]["PreToolUse"]
    assert data["hooks"]["Stop"] == original["hooks"]["Stop"]
    (backup,) = _backups(home)
    assert backup.read_bytes() == before


def test_a_second_run_changes_nothing(home, tmp_path):
    _write(home, {"model": "opus"})
    _link(home, tmp_path)
    after = _settings(home).read_bytes()
    backups = _backups(home)
    assert _link(home, tmp_path).status == "already"
    assert _settings(home).read_bytes() == after and _backups(home) == backups


def test_a_pre_tool_use_faildex_hook_moves_with_its_command(home, tmp_path):
    mine = {
        "type": "command",
        "command": "/opt/faildex/.venv/bin/faildex hook --store /data/store --log /data/hook.jsonl",
        "timeout": 7,
    }
    _write(home, {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [OTHER, mine]}]}})
    step = _link(home, tmp_path)
    assert step.status == "moved"
    data = json.loads(_settings(home).read_text())
    assert data["hooks"]["PreToolUse"] == [{"matcher": "Bash", "hooks": [OTHER]}]
    assert data["hooks"]["PostToolUseFailure"] == [{"matcher": "Bash", "hooks": [mine]}]
    assert len(_backups(home)) == 1


def test_a_lone_pre_tool_use_faildex_hook_leaves_no_empty_event(home, tmp_path):
    _write(home, {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [dict(OURS)]}]}})
    assert _link(home, tmp_path).status == "moved"
    assert json.loads(_settings(home).read_text()) == INSTALLED


def test_faildex_under_both_events_loses_only_the_pre_tool_use_one(home, tmp_path):
    post = [{"matcher": "Bash", "hooks": [{"command": "faildex hook --log /l"}]}]
    both = {
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [OTHER, {"command": "faildex hook"}]}],
            "PostToolUseFailure": post,
        }
    }
    _write(home, both)
    assert _link(home, tmp_path).status == "updated"
    assert json.loads(_settings(home).read_text()) == {
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [OTHER]}],
            "PostToolUseFailure": post,
        }
    }
    assert len(_backups(home)) == 1
    assert _link(home, tmp_path).status == "already"


def test_only_post_tool_use_failure_is_already(home, tmp_path):
    path = _write(
        home, {"hooks": {"PostToolUseFailure": [{"hooks": [{"command": "faildex hook"}]}]}}
    )
    before = path.read_bytes()
    assert _link(home, tmp_path).status == "already"
    assert path.read_bytes() == before and _backups(home) == []


def test_remove_takes_ours_out_of_both_events_and_drops_empty_ones(home, tmp_path):
    _write(
        home,
        {
            "model": "opus",
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [OTHER, {"command": "faildex hook --log x"}]}
                ],
                "PostToolUseFailure": [{"matcher": "Bash", "hooks": [dict(OURS)]}],
                "Stop": [{"hooks": [OTHER]}],
            },
        },
    )
    assert _unlink(home, tmp_path).status == "removed"
    assert json.loads(_settings(home).read_text()) == {
        "model": "opus",
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [OTHER]}],
            "Stop": [{"hooks": [OTHER]}],
        },
    }
    assert _unlink(home, tmp_path).status == "absent"


def test_a_settings_file_link_created_goes_with_remove(home, tmp_path):
    _link(home, tmp_path)
    assert _settings(home).exists()
    assert _unlink(home, tmp_path).status == "removed"
    assert not _settings(home).exists() and _backups(home) == []


def test_a_settings_file_link_created_stays_when_someone_added_to_it(home, tmp_path):
    _link(home, tmp_path)
    data = json.loads(_settings(home).read_text())
    _settings(home).write_text(json.dumps({**data, "model": "opus"}))
    _unlink(home, tmp_path)
    assert json.loads(_settings(home).read_text()) == {"model": "opus", "hooks": {}}


@pytest.mark.parametrize(
    ("start", "status"),
    [
        (None, "would install"),
        ({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [dict(OURS)]}]}}, "would move"),
    ],
)
def test_dry_run_writes_nothing(home, tmp_path, start, status):
    if start is not None:
        _write(home, start)
    before = _settings(home).read_bytes() if start is not None else None
    assert _link(home, tmp_path, dry_run=True).status == status
    after = _settings(home).read_bytes() if _settings(home).exists() else None
    assert after == before and _backups(home) == []


def test_dry_run_remove_writes_nothing(home, tmp_path):
    path = _write(home, INSTALLED)
    before = path.read_bytes()
    assert _unlink(home, tmp_path, dry_run=True).status == "would remove"
    assert path.read_bytes() == before and _backups(home) == []


@pytest.mark.parametrize(
    ("text", "note"),
    [
        ("{not json", "settings.json is not a valid JSON object; left alone"),
        ("[1, 2]", "settings.json is not a valid JSON object; left alone"),
        ('{"hooks": []}', "settings.json: hooks is not an object; left alone"),
        (
            '{"hooks": {"PreToolUse": {"matcher": "Bash"}}}',
            "settings.json: a hook event is not a list of objects; left alone",
        ),
        (
            '{"hooks": {"PostToolUseFailure": ["faildex hook"]}}',
            "settings.json: a hook event is not a list of objects; left alone",
        ),
        (
            '{"hooks": {"PostToolUseFailure": [{"hooks": "faildex hook"}]}}',
            "settings.json: a hook event is not a list of objects; left alone",
        ),
    ],
)
@pytest.mark.parametrize("remove", [False, True])
def test_an_unexpected_file_is_left_alone_with_the_reason(home, tmp_path, text, note, remove):
    path = _write(home, text)
    step = (_unlink if remove else _link)(home, tmp_path)
    assert (step.status, step.note) == ("skipped", note)
    assert path.read_text() == text and _backups(home) == []


def test_a_symlinked_settings_file_is_left_alone(home, tmp_path):
    real = tmp_path / "elsewhere.json"
    real.write_text('{"model": "opus"}\n')
    _settings(home).parent.mkdir(parents=True)
    try:
        _settings(home).symlink_to(real)
    except OSError:
        pytest.skip("symlinks unavailable")
    for step in (_link(home, tmp_path), _unlink(home, tmp_path)):
        assert step.status == "skipped" and "symlink" in step.note
    assert real.read_text() == '{"model": "opus"}\n' and _backups(home) == []


def test_a_bom_is_read(home, tmp_path):
    path = _settings(home)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xef\xbb\xbf" + b'{"model": "opus"}\n')
    assert _link(home, tmp_path).status == "installed"
    assert json.loads(path.read_text())["model"] == "opus"


def test_configure_claude_alone(tmp_path):
    path = tmp_path / "settings.json"
    assert configure_claude(path, False, False)[0] == "installed"
    assert configure_claude(path, False, False) == ("already", "")
    assert configure_claude(path, True, False) == ("removed", "")
    assert json.loads(path.read_text()) == {"hooks": {}}  # not created by link: kept


@pytest.mark.parametrize(
    ("command", "ours"),
    [
        ("faildex hook", True),
        ("faildex hook --agent claude", True),
        ("/home/me/.venv/bin/faildex hook --store /s --log /l", True),
        ("C:\\Users\\me\\.local\\bin\\faildex.exe hook --store C:\\s", True),
        ('"C:\\Program Files\\faildex\\faildex.exe" hook', True),
        ("FAILDEX.EXE hook", True),
        ("faildex rules", False),
        ("faildex", False),
        ("faildex-old hook", False),
        ("echo faildex hook", False),
        ("python -m faildex hook", False),
        (None, False),
        ('faildex hook "unclosed', False),
    ],
)
def test_which_commands_are_faildex_hooks(command, ours):
    assert _faildex_hook_command(command) is ours


def test_the_cli_shows_the_step_and_what_to_do_next(home, capsys):
    assert main(["link"]) == 0
    out = capsys.readouterr().out
    line = next(x for x in out.splitlines() if "settings.json" in x)
    assert "Claude Code" in line and "installed" in line and "/hooks" in line
    assert json.loads(_settings(home).read_text()) == INSTALLED
    assert main(["--lang", "ko", "link", "--remove"]) == 0
    out = capsys.readouterr().out
    line = next(x for x in out.splitlines() if "settings.json" in x)
    assert "제거함" in line
    assert not _settings(home).exists()
