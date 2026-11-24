import json
from pathlib import Path

import pytest

from faildex.cli import main
from faildex.link import COPY, link, skill_source, unlink


def RULES(steps):
    return [s for s in steps if s.what == "rules"]


def _home(tmp_path, antigravity=True):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text(
        "@/somewhere/working-rules.md"
    )  # no trailing newline
    if antigravity:
        (home / ".gemini" / "antigravity-cli").mkdir(parents=True)
    return home


def test_link_wires_both_agents_and_is_idempotent(tmp_path):
    home = _home(tmp_path)
    rules = tmp_path / "rules.md"
    first = {s.agent: s.status for s in RULES(link(rules, home))}
    assert first == {"Claude Code": "linked", "Antigravity": "linked"}
    claude = (home / ".claude" / "CLAUDE.md").read_text()
    assert claude == f"@/somewhere/working-rules.md\n@{rules.resolve()}\n"
    agents = home / ".gemini/config/plugins/faildex-rules/rules/AGENTS.md"
    assert agents.is_symlink() and agents.resolve() == rules.resolve()
    assert json.loads((agents.parent.parent / "plugin.json").read_text())["name"] == "faildex-rules"
    assert rules.read_text().startswith("# Rules learned")  # created so approve can append

    second = {s.agent: s.status for s in RULES(link(rules, home))}
    assert second["Claude Code"] == second["Antigravity"] == "already"
    assert (home / ".claude" / "CLAUDE.md").read_text() == claude


def test_dry_run_changes_nothing(tmp_path):
    home = _home(tmp_path)
    rules = tmp_path / "rules.md"
    steps = {s.agent: s.status for s in RULES(link(rules, home, dry_run=True))}
    assert steps["Claude Code"] == steps["Antigravity"] == "would link"
    assert not rules.exists()
    assert not (home / ".gemini" / "config").exists()
    assert (home / ".claude" / "CLAUDE.md").read_text() == "@/somewhere/working-rules.md"


def test_unlink_removes_only_what_link_added(tmp_path):
    home = _home(tmp_path)
    rules = tmp_path / "rules.md"
    link(rules, home)
    steps = {s.agent: s.status for s in RULES(unlink(rules, home))}
    assert steps == {"Claude Code": "removed", "Antigravity": "removed"}
    assert (home / ".claude" / "CLAUDE.md").read_text() == "@/somewhere/working-rules.md\n"
    assert not (home / ".gemini/config/plugins/faildex-rules").exists()
    assert rules.exists()  # the rules themselves are kept
    assert {s.status for s in unlink(rules, home) if s.what == "rules"} == {"absent"}


def test_other_peoples_files_are_left_alone(tmp_path):
    home = _home(tmp_path)
    plugin = home / ".gemini/config/plugins/faildex-rules"
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text('{"name": "someone-else"}')
    steps = {s.agent: s.status for s in RULES(link(tmp_path / "rules.md", home))}
    assert steps["Antigravity"] == "skipped"
    assert {s.agent: s.status for s in RULES(unlink(tmp_path / "rules.md", home))}[
        "Antigravity"
    ] == "skipped"
    assert plugin.exists()


def test_antigravity_is_skipped_when_not_installed(tmp_path):
    home = _home(tmp_path, antigravity=False)
    steps = {s.agent: s.status for s in RULES(link(tmp_path / "rules.md", home))}
    assert steps["Antigravity"] == "skipped"
    assert not (home / ".gemini").exists()


def test_cli_link(tmp_path, monkeypatch, capsys):
    home = _home(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows
    rules = tmp_path / "rules.md"
    assert main(["link", "--rules", str(rules)]) == 0
    out = capsys.readouterr().out
    status = {}
    for line in out.splitlines():
        for agent in ("Claude Code", "Antigravity"):
            if line.startswith(agent) and line[len(agent) :].split()[0] == "rules":
                status[agent] = line[len(agent) :].split()[1]
    assert status == {"Claude Code": "linked", "Antigravity": "linked"}
    assert main(["link", "--rules", str(rules), "--remove"]) == 0
    assert "removed" in capsys.readouterr().out


def test_without_symlinks_a_marked_copy_is_written_and_refreshed(tmp_path, monkeypatch):
    from pathlib import Path

    def refuse(self, target):
        raise OSError("symlinks need Developer Mode")

    monkeypatch.setattr(Path, "symlink_to", refuse)
    home = _home(tmp_path)
    rules = tmp_path / "rules.md"
    assert {s.agent: s.status for s in RULES(link(rules, home))}["Antigravity"] == "copied"
    agents = home / ".gemini/config/plugins/faildex-rules/rules/AGENTS.md"
    rules.write_text(rules.read_text() + "- a new rule\n")
    assert {s.agent: s.status for s in RULES(link(rules, home))}["Antigravity"] == "copied"
    assert agents.read_text().endswith("- a new rule\n")


def test_link_installs_the_skill_for_every_agent_and_remove_takes_it_out(tmp_path):
    from faildex.link import skill_source

    home = _home(tmp_path)
    (home / ".codex").mkdir()
    (home / ".cursor").mkdir()
    rules = tmp_path / "rules.md"
    skills = {s.agent: s.status for s in link(rules, home) if s.what == "skill"}
    assert skills == {
        "Claude Code": "installed",
        "Antigravity": "installed",
        "Codex": "installed",
        "Cursor": "installed",
    }
    text = skill_source().read_text()
    for path in (
        home / ".claude/skills/faildex/SKILL.md",
        home / ".gemini/config/plugins/faildex-rules/skills/faildex/SKILL.md",
        home / ".codex/skills/faildex/SKILL.md",
        home / ".cursor/skills/faildex/SKILL.md",
    ):
        assert path.read_text() == text
    assert {s.status for s in link(rules, home) if s.what == "skill"} == {"already"}
    unlink(rules, home)
    assert not (home / ".claude/skills/faildex").exists()
    assert not (home / ".codex/skills/faildex").exists()
    assert not (home / ".cursor/skills/faildex").exists()
    assert not (home / ".gemini/config/plugins/faildex-rules").exists()


def test_someone_elses_skill_named_like_ours_is_left_alone(tmp_path):
    home = _home(tmp_path)
    other = home / ".claude/skills/faildex"
    other.mkdir(parents=True)
    (other / "SKILL.md").write_text("---\nname: something-else\n---\nmine\n")
    step = next(
        s
        for s in link(tmp_path / "rules.md", home)
        if s.what == "skill" and s.agent == "Claude Code"
    )
    assert step.status == "skipped"
    assert (other / "SKILL.md").read_text().endswith("mine\n")
    assert (
        next(
            s
            for s in unlink(tmp_path / "rules.md", home)
            if s.what == "skill" and s.agent == "Claude Code"
        ).status
        == "skipped"
    )


def test_an_old_faildex_skill_is_updated(tmp_path):
    home = _home(tmp_path)
    old = home / ".claude/skills/faildex"
    old.mkdir(parents=True)
    (old / "SKILL.md").write_text("---\nname: faildex\ndescription: old\n---\nold text\n")
    step = next(
        s
        for s in link(tmp_path / "rules.md", home)
        if s.what == "skill" and s.agent == "Claude Code"
    )
    assert step.status == "updated"


# Per-editor round trips (issue #24). Each case uses a throwaway home under tmp_path
# and never Path.home(), so a bug cannot write into the real ~/.claude or ~/.cursor.

_REAL_HOME = Path.home().resolve()
_EDITORS = (
    pytest.param("Claude Code", id="claude-code"),
    pytest.param("Antigravity", id="antigravity"),
    pytest.param("Cursor", id="cursor"),
)
_BUSY = {"linked", "installed", "updated", "copied"}


def _no_real_home():
    """Sentinel so a missing `home=` argument fails the test instead of touching ~."""
    raise AssertionError("link/unlink must use the fake home, not Path.home()")


def _snapshot(root: Path) -> dict[str, tuple[str, str]]:
    """Walk `root` without following directory symlinks: relpath -> (kind, payload)."""
    found: dict[str, tuple[str, str]] = {}

    def walk(folder: Path) -> None:
        for child in sorted(folder.iterdir(), key=lambda p: p.name):
            rel = child.relative_to(root).as_posix()
            # Hook configs and retained backups have separate coverage in test_agent_hooks.py.
            if child.parent.name in {".codex", ".cursor"} and (
                child.name == "hooks.json" or child.name.startswith("hooks.json.faildex-backup-")
            ):
                continue
            if child.is_symlink():
                found[rel] = ("symlink", str(child.readlink()))
            elif child.is_dir():
                found[rel] = ("dir", "")
                walk(child)
            elif child.is_file():
                found[rel] = ("file", child.read_text())

    if root.exists():
        walk(root)
    return found


def _editor_home(tmp_path: Path, editor: str) -> Path:
    """A fake home that already has that editor's user files, and only that editor."""
    home = tmp_path / "home"
    home.mkdir()
    if editor == "Claude Code":
        claude = home / ".claude"
        claude.mkdir()
        (claude / "CLAUDE.md").write_text("# my instructions\n")
        (claude / "settings.json").write_text('{"hooks": {}}\n')
        other = claude / "skills" / "my-skill"
        other.mkdir(parents=True)
        (other / "SKILL.md").write_text("---\nname: my-skill\n---\nkeep me\n")
    elif editor == "Antigravity":
        cli = home / ".gemini" / "antigravity-cli"
        cli.mkdir(parents=True)
        (cli / "user.txt").write_text("session-log\n")
        other = home / ".gemini" / "config" / "plugins" / "other-plugin"
        (other / "rules").mkdir(parents=True)
        (other / "plugin.json").write_text('{"name": "other-plugin"}\n')
        (other / "rules" / "AGENTS.md").write_text("other rules\n")
    elif editor == "Cursor":
        cursor = home / ".cursor"
        cursor.mkdir()
        (cursor / "argv.json").write_text('{"version": 1}\n')
        (cursor / "mcp.json").write_text('{"mcpServers": {}}\n')
        other = cursor / "skills" / "my-skill"
        other.mkdir(parents=True)
        (other / "SKILL.md").write_text("---\nname: my-skill\n---\nkeep me\n")
    else:
        raise ValueError(f"unknown editor: {editor}")
    return home


def _absolute(path: Path) -> Path:
    """Absolute path without following a final symlink (rules links point outside home)."""
    return path if path.is_absolute() else Path.cwd() / path


def _assert_confined(steps, home: Path) -> None:
    """Every reported path must sit inside the fake home, never the real one."""
    home = _absolute(home)
    assert home != _REAL_HOME
    for step in steps:
        where = _absolute(Path(step.where))
        assert where == home or home in where.parents, (step.agent, step.where)
        if where == _REAL_HOME or _REAL_HOME in where.parents:
            assert home == _REAL_HOME or _REAL_HOME in home.parents


def _assert_user_files_preserved(
    home: Path,
    original: dict[str, tuple[str, str]],
    extra_ok: frozenset[str] = frozenset(),
) -> None:
    """Pre-existing paths remain. Contents match, except files we are allowed to append to."""
    for rel, (kind, payload) in original.items():
        path = home / rel
        assert path.exists(), rel
        if kind == "symlink":
            assert path.is_symlink() and str(path.readlink()) == payload
        elif kind == "file":
            assert path.is_file() and not path.is_symlink()
            now = path.read_text()
            if rel in extra_ok:
                for line in payload.splitlines():
                    assert line in now.splitlines()
            else:
                assert now == payload
        else:
            assert path.is_dir()


def _editor_artifacts(editor: str, home: Path) -> list[Path]:
    """Files `faildex link` should write for this editor (rules and/or skill)."""
    if editor == "Claude Code":
        return [
            home / ".claude" / "CLAUDE.md",
            home / ".claude" / "skills" / "faildex" / "SKILL.md",
        ]
    if editor == "Antigravity":
        plugin = home / ".gemini" / "config" / "plugins" / "faildex-rules"
        return [
            plugin / "rules" / "AGENTS.md",
            plugin / "skills" / "faildex" / "SKILL.md",
        ]
    return [home / ".cursor" / "skills" / "faildex" / "SKILL.md"]


def _assert_editor_linked(editor: str, home: Path, rules: Path) -> None:
    """The editor-specific install landed: skill text, and rules where this editor has them."""
    text = skill_source().read_text()
    skill = next(p for p in _editor_artifacts(editor, home) if p.name == "SKILL.md")
    assert skill.is_file() and skill.read_text() == text
    if editor == "Claude Code":
        assert f"@{rules.resolve()}" in (home / ".claude" / "CLAUDE.md").read_text().splitlines()
    elif editor == "Antigravity":
        agents = home / ".gemini" / "config" / "plugins" / "faildex-rules" / "rules" / "AGENTS.md"
        if agents.is_symlink():
            assert agents.resolve() == rules.resolve()
        else:
            assert agents.read_text().startswith(COPY.format(rules.resolve()))


@pytest.fixture
def no_real_home(monkeypatch):
    """Fail the test if link/unlink fall back to Path.home()."""
    monkeypatch.setattr(Path, "home", staticmethod(_no_real_home))


@pytest.mark.parametrize("editor", _EDITORS)
def test_link_then_unlink_returns_to_the_original_state(tmp_path, editor, no_real_home):
    home = _editor_home(tmp_path, editor)
    original = _snapshot(home)
    rules = tmp_path / "rules.md"
    first = link(rules, home)
    _assert_confined(first, home)
    _assert_user_files_preserved(home, original, extra_ok=frozenset({".claude/CLAUDE.md"}))
    _assert_editor_linked(editor, home, rules)
    removed = unlink(rules, home)
    _assert_confined(removed, home)
    assert _snapshot(home) == original
    _assert_user_files_preserved(home, original)


@pytest.mark.parametrize("editor", _EDITORS)
def test_preexisting_user_files_survive_link_and_unlink(tmp_path, editor, no_real_home):
    home = _editor_home(tmp_path, editor)
    original = _snapshot(home)
    rules = tmp_path / "rules.md"
    link(rules, home)
    _assert_user_files_preserved(home, original, extra_ok=frozenset({".claude/CLAUDE.md"}))
    unlink(rules, home)
    assert _snapshot(home) == original


@pytest.mark.parametrize("editor", _EDITORS)
def test_copy_install_is_removed_by_unlink(tmp_path, editor, monkeypatch, no_real_home):
    def refuse(self, target):
        raise OSError("symlinks need Developer Mode")

    monkeypatch.setattr(Path, "symlink_to", refuse)
    home = _editor_home(tmp_path, editor)
    original = _snapshot(home)
    rules = tmp_path / "rules.md"
    first = link(rules, home)
    _assert_confined(first, home)
    _assert_user_files_preserved(home, original, extra_ok=frozenset({".claude/CLAUDE.md"}))
    _assert_editor_linked(editor, home, rules)
    for path in _editor_artifacts(editor, home):
        assert path.exists() and not path.is_symlink()
    if editor == "Antigravity":
        rules_step = next(s for s in first if s.agent == editor and s.what == "rules")
        assert rules_step.status == "copied"
    after_first = _snapshot(home)
    second = link(rules, home)
    _assert_confined(second, home)
    assert _snapshot(home) == after_first
    unlink(rules, home)
    assert _snapshot(home) == original
    for path in _editor_artifacts(editor, home):
        if path not in {home / rel for rel in original}:
            assert not path.exists()


@pytest.mark.parametrize("editor", _EDITORS)
def test_link_twice_is_safe(tmp_path, editor, no_real_home):
    home = _editor_home(tmp_path, editor)
    original = _snapshot(home)
    rules = tmp_path / "rules.md"
    first = link(rules, home)
    _assert_confined(first, home)
    _assert_editor_linked(editor, home, rules)
    after_first = _snapshot(home)
    second = [s for s in link(rules, home) if s.agent == editor]
    _assert_confined(second, home)
    assert not any(s.status in _BUSY for s in second)
    assert _snapshot(home) == after_first
    unlink(rules, home)
    assert _snapshot(home) == original


@pytest.mark.parametrize(
    "existing",
    [
        ".claude/skills",
        ".codex/skills",
        ".cursor/skills",
        ".gemini/config/plugins",
        ".gemini/config/plugins/faildex-rules/rules",
        ".claude/CLAUDE.md",
    ],
)
def test_roundtrip_preserves_preexisting_empty_paths(tmp_path, existing, no_real_home):
    home = _editor_home(tmp_path, "Antigravity")
    path = home / existing
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".md":
        path.touch()
    else:
        path.mkdir(exist_ok=True)
    if "faildex-rules" in existing:
        (home / ".gemini/config/plugins/faildex-rules/plugin.json").write_text(
            '{"name": "faildex-rules"}\n'
        )
    original = _snapshot(home)
    rules = tmp_path / "rules.md"
    link(rules, home)
    unlink(rules, home)
    assert _snapshot(home) == original


@pytest.mark.parametrize(
    "folder",
    [
        ".claude/skills/faildex",
        ".codex/skills/faildex",
        ".cursor/skills/faildex",
        ".gemini/config/plugins/faildex-rules",
        ".gemini/config/plugins/faildex-rules/skills/faildex",
    ],
)
def test_unlink_preserves_files_added_after_link(tmp_path, folder, no_real_home):
    home = _editor_home(tmp_path, "Antigravity")
    (home / ".codex").mkdir()
    (home / ".cursor").mkdir()
    rules = tmp_path / "rules.md"
    link(rules, home)
    user_file = home / folder / "user.txt"
    user_file.write_text("keep me\n")
    before = _snapshot(home)
    unlink(rules, home, dry_run=True)
    assert _snapshot(home) == before
    unlink(rules, home)
    assert user_file.read_text() == "keep me\n"
    after = _snapshot(home)
    unlink(rules, home)
    assert _snapshot(home) == after


def test_legacy_unlink_keeps_directories_and_empty_claude_file(tmp_path, no_real_home):
    home = _home(tmp_path)
    rules = tmp_path / "rules.md"
    (home / ".claude/CLAUDE.md").write_text(f"@{rules.resolve()}\n")
    skill = home / ".claude/skills/faildex/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(skill_source().read_text())
    unlink(rules, home)
    assert (home / ".claude/CLAUDE.md").read_text() == ""
    assert skill.parent.is_dir()


def test_link_does_not_replace_external_skill_or_rules_symlinks(tmp_path, no_real_home):
    home = _home(tmp_path)
    external = tmp_path / "external.md"
    external.write_text(skill_source().read_text())
    skill = home / ".claude/skills/faildex/SKILL.md"
    skill.parent.mkdir(parents=True)
    target = home / ".gemini/config/plugins/faildex-rules/rules/AGENTS.md"
    target.parent.mkdir(parents=True)
    (target.parent.parent / "plugin.json").write_text('{"name": "faildex-rules"}\n')
    try:
        skill.symlink_to(external)
        target.symlink_to(external)
    except OSError:
        pytest.skip("symlinks unavailable")
    before = external.read_text()
    rules = tmp_path / "rules.md"
    link(rules, home)
    unlink(rules, home)
    assert skill.is_symlink() and skill.resolve() == external
    assert target.is_symlink() and target.resolve() == external
    assert external.read_text() == before


def test_repeated_unlink_preserves_preexisting_faildex_files(tmp_path, no_real_home):
    home = _editor_home(tmp_path, "Antigravity")
    rules = tmp_path / "rules.md"
    rules.write_text("# existing rules\n")
    skill = home / ".claude/skills/faildex/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(skill_source().read_text())
    plugin = home / ".gemini/config/plugins/faildex-rules"
    (plugin / "rules").mkdir(parents=True)
    (plugin / "plugin.json").write_text('{"name": "faildex-rules"}\n')
    (plugin / "rules/AGENTS.md").write_text(COPY.format(rules.resolve()) + rules.read_text())
    original = _snapshot(home)
    link(rules, home)
    unlink(rules, home)
    unlink(rules, home)
    assert _snapshot(home) == original


@pytest.mark.parametrize("relative", [".claude", ".cursor/skills", ".gemini/config"])
def test_link_and_unlink_do_not_write_through_symlinked_folders(tmp_path, relative, no_real_home):
    home = tmp_path / "home"
    home.mkdir()
    folder = home / relative
    folder.parent.mkdir(parents=True, exist_ok=True)
    external = tmp_path / "external"
    external.mkdir()
    (external / "user.txt").write_text("keep me\n")
    try:
        folder.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    original = _snapshot(home)
    outside = _snapshot(external)
    rules = tmp_path / "rules.md"
    link(rules, home)
    unlink(rules, home)
    assert _snapshot(home) == original
    assert _snapshot(external) == outside


@pytest.mark.parametrize("payload", ['{"files": ["../outside"], "dirs": []}', '{"files": []}'])
def test_invalid_ownership_is_rejected_before_changes(tmp_path, payload, no_real_home):
    home = _editor_home(tmp_path, "Antigravity")
    (home / ".faildex-link.json").write_text(payload)
    original = _snapshot(home)
    rules = tmp_path / "rules.md"
    with pytest.raises(ValueError):
        link(rules, home)
    with pytest.raises(ValueError):
        unlink(rules, home)
    assert _snapshot(home) == original
    assert not rules.exists()


def test_relinking_with_new_rules_retargets_tracked_antigravity_symlink(tmp_path, no_real_home):
    home = _editor_home(tmp_path, "Antigravity")
    old_rules = tmp_path / "old-rules.md"
    new_rules = tmp_path / "new-rules.md"
    agents = home / ".gemini/config/plugins/faildex-rules/rules/AGENTS.md"
    if not hasattr(agents, "symlink_to"):
        pytest.skip("symlinks unavailable")
    first = {s.agent: s.status for s in RULES(link(old_rules, home))}
    if first["Antigravity"] == "copied":
        pytest.skip("symlinks unavailable")
    assert first["Antigravity"] == "linked"
    assert agents.is_symlink() and agents.resolve() == old_rules.resolve()

    dry = {s.agent: s.status for s in RULES(link(new_rules, home, dry_run=True))}
    assert dry["Antigravity"] == "would update"
    assert agents.resolve() == old_rules.resolve()
    assert not new_rules.exists()

    relinked = {s.agent: s.status for s in RULES(link(new_rules, home))}
    assert relinked["Antigravity"] == "updated"
    assert agents.is_symlink() and agents.resolve() == new_rules.resolve()

    again = {s.agent: s.status for s in RULES(link(new_rules, home))}
    assert again["Antigravity"] == "already"

    unlink(new_rules, home)
    assert not (home / ".gemini/config/plugins/faildex-rules").exists()


def test_relinking_retargets_broken_tracked_antigravity_symlink(tmp_path, no_real_home):
    home = _editor_home(tmp_path, "Antigravity")
    old_rules = tmp_path / "old-rules.md"
    new_rules = tmp_path / "new-rules.md"
    agents = home / ".gemini/config/plugins/faildex-rules/rules/AGENTS.md"
    first = {s.agent: s.status for s in RULES(link(old_rules, home))}
    if first["Antigravity"] == "copied":
        pytest.skip("symlinks unavailable")
    old_rules.unlink()
    assert agents.is_symlink() and not agents.exists()

    relinked = {s.agent: s.status for s in RULES(link(new_rules, home))}
    assert relinked["Antigravity"] == "updated"
    assert agents.is_symlink() and agents.resolve() == new_rules.resolve()


def test_user_antigravity_symlink_is_skipped_on_relink_and_preserved_by_unlink(
    tmp_path, no_real_home
):
    home = _home(tmp_path)
    old_rules = tmp_path / "old-rules.md"
    new_rules = tmp_path / "new-rules.md"
    old_rules.write_text("# user rules\n")
    target = home / ".gemini/config/plugins/faildex-rules/rules/AGENTS.md"
    target.parent.mkdir(parents=True)
    (target.parent.parent / "plugin.json").write_text('{"name": "faildex-rules"}\n')
    try:
        target.symlink_to(old_rules)
    except OSError:
        pytest.skip("symlinks unavailable")

    already = {s.agent: s.status for s in RULES(link(old_rules, home))}
    assert already["Antigravity"] == "already"

    skipped = {s.agent: s.status for s in RULES(link(new_rules, home))}
    assert skipped["Antigravity"] == "skipped"
    assert target.is_symlink() and target.resolve() == old_rules.resolve()

    unlink(old_rules, home)
    assert target.is_symlink() and target.resolve() == old_rules.resolve()


def test_relink_regular_file_and_copy_fallback_behavior(tmp_path, monkeypatch, no_real_home):
    home = _editor_home(tmp_path, "Antigravity")
    old_rules = tmp_path / "old-rules.md"
    new_rules = tmp_path / "new-rules.md"
    target = home / ".gemini/config/plugins/faildex-rules/rules/AGENTS.md"

    first = {s.agent: s.status for s in RULES(link(old_rules, home))}
    if first["Antigravity"] == "linked":

        def refuse(self, dest):
            raise OSError("symlinks disabled")

        monkeypatch.setattr(Path, "symlink_to", refuse)
        fallback = {s.agent: s.status for s in RULES(link(new_rules, home))}
        assert fallback["Antigravity"] == "copied"
        assert not target.is_symlink() and target.read_text().startswith(
            COPY.format(new_rules.resolve())
        )
        unlink(new_rules, home)
        assert not target.exists()

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("my manual rules\n")
    skipped = {s.agent: s.status for s in RULES(link(new_rules, home))}
    assert skipped["Antigravity"] == "skipped"
    assert target.read_text() == "my manual rules\n"
    unlink(new_rules, home)
    assert target.read_text() == "my manual rules\n"


def test_windows_copy_with_different_rules_path_keeps_existing_copy_skipped(
    tmp_path, monkeypatch, no_real_home
):
    def refuse(self, dest):
        raise OSError("symlinks need Developer Mode")

    monkeypatch.setattr(Path, "symlink_to", refuse)
    home = _home(tmp_path)
    old_rules = tmp_path / "old-rules.md"
    new_rules = tmp_path / "new-rules.md"
    assert {s.agent: s.status for s in RULES(link(old_rules, home))}["Antigravity"] == "copied"
    target = home / ".gemini/config/plugins/faildex-rules/rules/AGENTS.md"
    before = target.read_text()

    second = {s.agent: s.status for s in RULES(link(new_rules, home))}
    assert second["Antigravity"] == "skipped"
    assert target.read_text() == before


def test_unlink_with_other_rules_removes_tracked_antigravity_symlink(tmp_path, no_real_home):
    home = _editor_home(tmp_path, "Antigravity")
    old_rules = tmp_path / "old-rules.md"
    other_rules = tmp_path / "other-rules.md"
    agents = home / ".gemini/config/plugins/faildex-rules/rules/AGENTS.md"
    first = {s.agent: s.status for s in RULES(link(old_rules, home))}
    if first["Antigravity"] == "copied":
        pytest.skip("symlinks unavailable")
    assert agents.is_symlink()

    unlink(other_rules, home)
    assert not agents.exists() and not agents.is_symlink()
    assert not (home / ".faildex-link.json").exists()


# Agent files are UTF-8 whatever the machine's locale says. On Windows the locale
# encoding is a legacy code page (cp949 in Korea, cp1252 on the CI runner), and
# "원" is UTF-8 EC 9B 90: 0x90 is not a cp1252 character, so both pages reject it.
KOREAN = "# 원칙 → 한글 규칙\n"


def test_link_and_unlink_keep_a_utf8_claude_md(tmp_path):
    home = _home(tmp_path)
    claude = home / ".claude" / "CLAUDE.md"
    claude.write_text(KOREAN, encoding="utf-8")
    rules = tmp_path / "rules.md"
    assert {s.agent: s.status for s in RULES(link(rules, home))}["Claude Code"] == "linked"
    assert claude.read_text(encoding="utf-8") == f"{KOREAN}@{rules.resolve()}\n"
    assert {s.agent: s.status for s in RULES(link(rules, home))}["Claude Code"] == "already"
    assert {s.agent: s.status for s in RULES(unlink(rules, home))}["Claude Code"] == "removed"
    assert claude.read_text(encoding="utf-8") == KOREAN


def test_link_writes_a_non_ascii_rules_path_and_rules_as_utf8(tmp_path):
    home = _home(tmp_path)
    rules = tmp_path / "원본 규칙" / "rules.md"
    rules.parent.mkdir()
    rules.write_text(KOREAN, encoding="utf-8")
    first = {s.agent: s.status for s in RULES(link(rules, home))}
    assert first == {"Claude Code": "linked", "Antigravity": "linked"}
    claude = home / ".claude" / "CLAUDE.md"
    assert f"@{rules.resolve()}" in claude.read_text(encoding="utf-8").splitlines()
    # A symlink, or a copy where symlinks are not allowed: either way the rules read as UTF-8.
    agents = home / ".gemini/config/plugins/faildex-rules/rules/AGENTS.md"
    assert agents.read_text(encoding="utf-8").endswith(KOREAN)
    second = {s.agent: s.status for s in RULES(link(rules, home))}
    assert second["Claude Code"] == second["Antigravity"] == "already"
    steps = {s.agent: s.status for s in RULES(unlink(rules, home))}
    assert steps == {"Claude Code": "removed", "Antigravity": "removed"}
    assert rules.read_text(encoding="utf-8") == KOREAN
