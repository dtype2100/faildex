import json

from faildex.cli import main
from faildex.link import link, unlink


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
