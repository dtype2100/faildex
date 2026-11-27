"""Regression tests for the final review of PR #49 (Claude Fable 5.2, 2026-11-28).

P1-1 A child the hook starts (refresh ingest, index rebuild) imported Python files from
     the agent's project folder: `-c` puts the current folder first on sys.path, and
     the child ran there. A project's `argparse.py` ran in the background.
P3-d A swap copy marked its folder only after the copy, so a copy that failed half way
     left an unmarked `.writing-<token>` folder.
P3-e A refresh wrote its end line before the ingest's own buffered output.
P3-f `faildex hook` with arguments it cannot read exited 2, which an agent may take as an
     order to block the command.
"""

import io
import json
import shutil
import sys
import time
from pathlib import Path

import pytest

from faildex import index, refresh, store
from faildex.cli import main
from faildex.hook import quiet

FIXTURES = Path(__file__).parent / "fixtures"
REAL_START_REBUILD = index.start_rebuild  # before conftest stubs it for each test


def _trap(folder: Path) -> Path:
    """A project folder whose `argparse.py` and `json.py` leave a mark when imported."""
    folder.mkdir(parents=True, exist_ok=True)
    mark = folder / "RAN"
    for name in ("argparse", "json"):
        (folder / f"{name}.py").write_text(
            f"open({str(mark)!r}, 'a').write('{name}\\n')\n", encoding="utf-8"
        )
    return mark


def _wait_for(check, seconds: float = 60) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.2)
    return False


# P1-1 ----------------------------------------------------------------------------------


def test_p1_1_a_spawned_faildex_imports_nothing_from_the_project_folder(tmp_path, monkeypatch):
    project = tmp_path / "project"
    mark = _trap(project)
    monkeypatch.chdir(project)
    log = tmp_path / "logs" / "child.log"
    log.parent.mkdir()
    refresh.spawn([*refresh.faildex_command(), "--version"], log)
    assert _wait_for(lambda: log.is_file() and "faildex" in log.read_text(encoding="utf-8"))
    text = log.read_text(encoding="utf-8")
    assert "Traceback" not in text and "Error" not in text
    assert not mark.exists()


@pytest.mark.parametrize("cache", ["absolute", "relative"])
def test_p1_1_the_index_rebuild_imports_nothing_from_the_project_folder(
    tmp_path, monkeypatch, cache
):
    """The real background rebuild, started from a project folder with a trap in it.
    With a relative XDG_CACHE_HOME the child keeps the index where the hook looks."""
    made = tmp_path / "s"
    assert main(["ingest", "--claude", str(FIXTURES / "claude_code"), "--store", str(made)]) == 0
    index.beside(made).unlink()  # no index: the hook would start a rebuild
    project = tmp_path / "project"
    mark = _trap(project)
    monkeypatch.chdir(project)
    monkeypatch.setenv("XDG_CACHE_HOME", "cache" if cache == "relative" else str(project / "cache"))
    REAL_START_REBUILD(made)
    target = index.cached(made)
    assert _wait_for(target.is_file)
    assert _wait_for(lambda: not target.with_suffix(".lock").exists())
    assert index.candidates(made)  # where this process looks for it
    log = target.with_suffix(".log")
    assert "Traceback" not in (log.read_text(encoding="utf-8") if log.is_file() else "")
    assert not mark.exists()


def test_p1_1_the_entry_drops_the_current_folder_before_any_import():
    entry = refresh.faildex_command()[-1]
    assert entry.startswith("import sys; sys.path[:] = ")
    assert entry.index("sys.path") < entry.index("from faildex")


# P3-d ----------------------------------------------------------------------------------


def test_p3_d_a_copy_that_fails_half_way_leaves_no_unmarked_folder(tmp_path, monkeypatch):
    made = tmp_path / "s"
    assert main(["ingest", "--claude", str(FIXTURES / "claude_code"), "--store", str(made)]) == 0
    before = sorted(p.name for p in tmp_path.iterdir())
    real = shutil.copytree

    def half(src, dst, **kwargs):
        dst = Path(dst)
        (dst / "manifest.json").write_bytes((Path(src) / "manifest.json").read_bytes())
        raise OSError("disk full")

    seen = []

    def watch(src, dst, **kwargs):
        seen.append(sorted(p.name for p in Path(dst).iterdir()))  # what is there already
        return half(src, dst, **kwargs)

    monkeypatch.setattr(store.shutil, "copytree", watch)
    with pytest.raises(OSError):
        store.write_store(made, lambda db: None)
    monkeypatch.setattr(store.shutil, "copytree", real)
    assert seen == [[store.SWAP_MARK]]  # marked before a single file was copied
    assert sorted(p.name for p in tmp_path.iterdir()) == before  # and cleaned up
    assert store.looks_like_store(made)


# P3-e ----------------------------------------------------------------------------------


def test_p3_e_the_end_line_comes_after_the_ingests_own_output(tmp_path):
    made = tmp_path / "s"
    assert main(["ingest", "--claude", str(FIXTURES / "claude_code"), "--store", str(made)]) == 0
    _, log = refresh.paths(made)
    code = (
        "import sys; from pathlib import Path; from faildex import refresh\n"
        f"refresh.run_logged(Path({str(made)!r}), lambda: print('ingested 4 calls') or 0)\n"
    )
    refresh.spawn([sys.executable, "-c", code], log)
    assert _wait_for(lambda: log.is_file() and " end exit=" in log.read_text(encoding="utf-8"))
    assert _wait_for(lambda: "ingested 4 calls" in log.read_text(encoding="utf-8"), 10)
    lines = log.read_text(encoding="utf-8").splitlines()
    ingested = next(i for i, line in enumerate(lines) if "ingested 4 calls" in line)
    end = next(i for i, line in enumerate(lines) if " end exit=" in line)
    assert ingested < end


# P3-f ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["hook", "--refresh-every", "0"],
        ["hook", "--refresh-every", "x"],
        ["hook", "--no-such-option"],
        ["hook", "--agent", "cursor", "--refresh-every", "0"],
        ["hook", "--agent", "cursor", "--event", "session-start", "--bogus"],
    ],
)
def test_p3_f_hook_arguments_it_cannot_read_give_the_quiet_answer(argv, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Bash"})))
    assert main(argv) == 0
    out = capsys.readouterr()
    agent = argv[argv.index("--agent") + 1] if "--agent" in argv else "claude"
    event = "session-start" if "session-start" in argv else "pre-shell"
    expected = quiet(agent, event)
    assert out.out == (expected + "\n" if expected else "")
    assert out.err.count("\n") == 1 and out.err.startswith("faildex hook: ")


def test_p3_f_other_commands_still_stop_on_bad_arguments(capsys):
    with pytest.raises(SystemExit) as done:
        main(["rules", "--top", "0"])
    assert done.value.code == 2


def test_p3_f_hook_help_still_prints(capsys):
    with pytest.raises(SystemExit) as done:
        main(["hook", "--help"])
    assert done.value.code == 0 and "--refresh-every" in capsys.readouterr().out
