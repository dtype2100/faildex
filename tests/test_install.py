import zipfile
from pathlib import Path

from faildex.cli import main
from faildex.store import STORE_PARTS, default_store, open_store, public_store

ROOT = Path(__file__).parent.parent


def test_public_store_is_a_cached_copy_that_opens(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    store = public_store()
    assert store.is_relative_to(tmp_path)
    assert {p.name for p in store.iterdir()} >= {"manifest.json", "nodes", "relationships"}
    db = open_store(store)
    assert next(iter(db.execute("MATCH (n:Session) RETURN count(n) AS n")))["n"] > 0
    db.close()
    assert public_store() == store  # copied once


def test_default_store_falls_back_to_the_public_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))  # Windows
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("FAILDEX_STORE", raising=False)
    assert default_store().is_relative_to(tmp_path / "cache")


def test_demo_runs_anywhere(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "faildex: `git status` failed with" in out
    assert "(no notice" in out
    assert "recurrence" in out


def test_wheel_settings_ship_only_the_committed_store_files():
    text = (ROOT / "pyproject.toml").read_text()
    for part in STORE_PARTS:
        assert f'"store/{part}" = "faildex/_store/{part}"' in text
    assert "wal" not in text.split("force-include]", 1)[1].split("[", 1)[0]


def test_install_script_is_plain_sh_and_overridable():
    script = (ROOT / "install.sh").read_text()
    assert script.startswith("#!/bin/sh")
    assert "FAILDEX_SOURCE:-git+https://github.com/dtype2100/faildex" in script
    assert "uv tool install --force" in script


def test_built_wheel_contains_the_store(tmp_path):
    import shutil
    import subprocess

    if not shutil.which("uv"):
        return
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path), str(ROOT)],
        check=True,
        capture_output=True,
    )
    (wheel,) = tmp_path.glob("*.whl")
    names = zipfile.ZipFile(wheel).namelist()
    assert "faildex/_store/manifest.json" in names
    assert any(n.startswith("faildex/_store/nodes/") for n in names)
    assert not any("/wal/" in n or n.endswith((".lock", ".writer")) for n in names)
    assert "faildex/_skills/faildex/SKILL.md" in names  # faildex link installs it
