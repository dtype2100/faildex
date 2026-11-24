"""English and Korean output, `faildex help`, `faildex lang`, and the README steps."""

import json
import re
import shlex
import string
from pathlib import Path

import pytest
import relate
from test_hook import _bash
from test_insight import REJECTED, _records

from faildex import i18n
from faildex.cli import build_parser, main
from faildex.guide import EXAMPLES, STEPS
from faildex.schema import ingest

ROOT = Path(__file__).parent.parent
STORE = ROOT / "store"


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


def _store(tmp_path):
    store = tmp_path / "store"
    db = relate.connect(str(store))
    ingest(db, _records(), local_paths=True)
    db.commit()
    db.flush()
    db.close()
    return store


# The catalog


def test_both_languages_have_the_same_keys():
    assert set(i18n.EN) == set(i18n.KO)


def test_both_languages_have_the_same_placeholders():
    differ = [key for key in i18n.EN if _fields(i18n.EN[key]) != _fields(i18n.KO[key])]
    assert differ == []


def test_every_korean_message_is_translated():
    """A Korean entry left as the English text would read as a gap."""
    same = [
        key
        for key in i18n.EN
        if i18n.EN[key] == i18n.KO[key]
        and re.search(r"[A-Za-z]{4,}", re.sub(r"\{[^}]*\}", "", i18n.EN[key]))
    ]
    assert same == []


def test_width_and_pad_count_hangul_as_two_columns():
    assert i18n.width("세션") == 4
    assert i18n.pad("세션", 10, ">") == "      세션"
    assert i18n.pad("sessions", 10, ">") == f"{'sessions':>10}"
    assert i18n.wrap("   할 일: 가나 다라 마바", 12, "   ") == [
        "   할 일:",
        "   가나 다라",
        "   마바",
    ]


# Choosing the language


def test_the_default_is_english_and_the_system_locale_is_ignored(monkeypatch):
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")
    monkeypatch.setenv("LC_ALL", "ko_KR.UTF-8")
    assert i18n.resolve() == ("en", "default")


def test_option_then_env_then_config_then_default(monkeypatch, tmp_path):
    i18n.save("ko")
    assert i18n.resolve() == ("ko", "config")
    monkeypatch.setenv("FAILDEX_LANG", "en")
    assert i18n.resolve() == ("en", "env")
    assert i18n.resolve("ko") == ("ko", "option")
    monkeypatch.setenv("FAILDEX_LANG", "fr")  # not a language faildex has: ignored
    assert i18n.resolve() == ("ko", "config")


def test_faildex_lang_saves_switches_and_reports_where_it_came_from(capsys):
    home = Path.home()
    store = home / ".faildex" / "store"
    store.mkdir(parents=True)
    (store / "manifest.json").write_text("{}")

    assert main(["lang"]) == 0
    assert capsys.readouterr().out.startswith("language: en (the default")

    assert main(["lang", "ko"]) == 0
    out = capsys.readouterr().out
    assert "저장했습니다: ko" in out and "~/.faildex/config.json" in out
    assert json.loads((home / ".faildex" / "config.json").read_text()) == {"lang": "ko"}

    assert main(["lang"]) == 0
    assert capsys.readouterr().out.startswith("언어: ko (~/.faildex/config.json에 저장됨)")
    assert main(["help"]) == 0
    assert "faildex 사용 순서" in capsys.readouterr().out

    assert main(["lang", "en"]) == 0
    assert capsys.readouterr().out.startswith("saved: en")
    assert main(["help"]) == 0
    assert "how to use it, in order" in capsys.readouterr().out
    # The store folder next to the config is untouched.
    assert sorted(p.name for p in store.iterdir()) == ["manifest.json"]
    assert (store / "manifest.json").read_text() == "{}"


def test_faildex_lang_keeps_other_settings_and_refuses_a_broken_file(capsys):
    config = Path.home() / ".faildex" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"other": 1}')
    assert main(["lang", "ko"]) == 0
    assert json.loads(config.read_text()) == {"other": 1, "lang": "ko"}
    config.write_text("{not json")
    capsys.readouterr()
    assert main(["lang", "en"]) == 1
    assert "error:" in capsys.readouterr().out
    assert config.read_text() == "{not json"


def test_faildex_lang_says_when_the_environment_still_wins(monkeypatch, capsys):
    monkeypatch.setenv("FAILDEX_LANG", "en")
    assert main(["lang", "ko"]) == 0
    out = capsys.readouterr().out
    assert "FAILDEX_LANG=en" in out
    assert main(["lang"]) == 0
    assert "FAILDEX_LANG" in capsys.readouterr().out


def test_lang_works_before_and_after_the_command(capsys):
    assert main(["--lang", "ko", "eval", "--store", str(STORE)]) == 0
    before = capsys.readouterr().out
    assert main(["eval", "--lang", "ko", "--store", str(STORE)]) == 0
    assert capsys.readouterr().out == before
    assert "반복률" in before


# Korean output keeps every number


def test_korean_eval_matches_english_numbers(capsys):
    main(["eval", "--store", str(STORE)])
    english = capsys.readouterr().out
    main(["--lang", "ko", "eval", "--store", str(STORE)])
    korean = capsys.readouterr().out
    assert re.findall(r"\d+(?:\.\d+)?%?", english) == re.findall(r"\d+(?:\.\d+)?%?", korean)
    assert "117" in korean and "68.4%" in korean and "전체" in korean
    # Columns still line up: every table row is as wide as its header, in terminal columns.
    rows = [line for line in korean.splitlines() if line.startswith(("데이터셋", "codex", "wisp"))]
    assert len({i18n.width(row) for row in rows}) == 1


def test_korean_rules_demo_and_report(capsys):
    assert main(["--lang", "ko", "rules", "--top", "3", "--store", str(STORE)]) == 0
    out = capsys.readouterr().out
    assert "세션 422개, 실패 호출 627개, 반복 실패 25개" in out
    assert "할 일:" in out and "근거 (3):" in out
    assert "fatal: not a git repository" in out  # the failure key is log text, never translated
    assert all(i18n.width(line) <= 80 for line in out.splitlines() if line.startswith("   "))

    assert main(["--lang", "ko", "demo"]) == 0
    out = capsys.readouterr().out
    assert "== 1. 여러 세션에서 다시 나온 실패" in out
    # What the hook prints is shown as the hook prints it: English.
    assert "faildex: `git status` failed with" in out

    assert main(["--lang", "ko", "report", "--store", str(STORE)]) == 0
    assert "에이전트" in capsys.readouterr().out


def test_check_speaks_korean_but_approve_writes_english(tmp_path, capsys):
    store = _store(tmp_path)
    assert main(["--lang", "ko", "check", "git push", "--store", str(store)]) == 0
    out = capsys.readouterr().out
    assert "오류로 실패할 때" in out and REJECTED in out

    rules = tmp_path / "rules.md"
    argv = ["--lang", "ko", "rules", "--approve", "1", "--to", str(rules), "--store", str(store)]
    assert main(argv) == 0
    assert "규칙 1개를" in capsys.readouterr().out
    assert f"- When `git push` fails with `{REJECTED}`" in rules.read_text()
    # A second approval in English sees the same rule and skips it.
    assert main(["rules", "--approve", "1", "--to", str(rules), "--store", str(store)]) == 0
    assert capsys.readouterr().out.startswith("added 0 rule(s)")


def test_hook_and_mcp_stay_english(tmp_path, monkeypatch, capsys):
    from faildex import mcp_server

    store = _store(tmp_path)
    monkeypatch.setenv("FAILDEX_LANG", "ko")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(_bash("git push origin main")))
    assert main(["hook", "--store", str(store)]) == 0
    out = capsys.readouterr().out
    assert "earlier sessions" in out and not re.search("[가-힣]", out)

    i18n.use("ko")
    found = mcp_server.preflight(store, "git push origin main")["known_failures"][0]
    assert found["rule"].startswith("When `git push` fails with")


def test_errors_are_translated(tmp_path, capsys):
    assert main(["--lang", "ko", "check", "--store", str(tmp_path / "none"), "git status"]) == 1
    assert "오류:" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--lang", "ko", "rules", "--top", "0"])
    assert "1 이상의 정수" in capsys.readouterr().err


# faildex help and --help


def test_faildex_help_lists_the_steps_and_points_at_per_command_help(capsys):
    for lang, more in (
        ("en", "Details for one command: faildex help <command>"),
        ("ko", "명령별 자세한 설명: faildex help <명령>"),
    ):
        assert main(["--lang", lang, "help"]) == 0
        out = capsys.readouterr().out
        for _, commands in STEPS:
            for command in commands:
                assert command in out
        assert more in out


def test_faildex_help_explains_every_command_in_both_languages(capsys):
    _, commands = build_parser()
    assert set(EXAMPLES) == set(commands)
    for lang in ("en", "ko"):
        for name in commands:
            assert main(["--lang", lang, "help", name]) == 0
            out = capsys.readouterr().out
            assert out.startswith(f"faildex {name}: ")
            for example in EXAMPLES[name]:
                assert example in out


def test_faildex_help_with_an_unknown_command_fails_with_the_list(capsys):
    assert main(["help", "nope"]) == 2
    err = capsys.readouterr().err
    assert "nope" in err and "rules" in err and "ingest" in err


def test_every_example_and_step_command_parses():
    parser, _ = build_parser()
    commands = [c for _, cs in STEPS for c in cs if c.startswith("faildex ")]
    commands += [c for examples in EXAMPLES.values() for c in examples]
    for command in commands:
        parser.parse_args(shlex.split(command)[1:])


def test_dash_dash_help_still_works_and_ends_with_the_pointer(capsys):
    for lang, tail in (("en", "New here? Run: faildex help"), ("ko", "처음이면: faildex help")):
        with pytest.raises(SystemExit) as done:
            main(["--lang", lang, "--help"])
        assert done.value.code == 0
        assert capsys.readouterr().out.rstrip().endswith(tail)
        with pytest.raises(SystemExit):
            main(["--lang", lang, "rules", "--help"])
        assert "--approve" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--lang", "ko", "rules", "--help"])
    out = capsys.readouterr().out
    assert out.startswith("사용법: faildex rules") and "규칙 파일" in out


# The README steps are the help steps


def _readme_steps(path: Path, heading: str) -> list[tuple[int, tuple[str, ...]]]:
    text = path.read_text(encoding="utf-8")
    section = text.split(f"\n{heading}\n", 1)[1].split("\n## ", 1)[0]
    steps = []
    for number, rest in re.findall(r"^(\d+)\. \*\*[^*]+\*\*: (.+)$", section, re.MULTILINE):
        steps.append((int(number), tuple(re.findall(r"`([^`]+)`", rest))))
    return steps


@pytest.mark.parametrize(
    ("readme", "heading"),
    [("README.md", "## How to use, in order"), ("README.ko.md", "## 사용 순서")],
)
def test_readme_steps_match_faildex_help(readme, heading):
    assert _readme_steps(ROOT / readme, heading) == list(STEPS)


@pytest.mark.parametrize(
    ("readme", "heading", "before"),
    [
        ("README.md", "## How to use, in order", "## Setup and run"),
        ("README.ko.md", "## 사용 순서", "## 설치와 실행"),
    ],
)
def test_readme_steps_come_before_setup(readme, heading, before):
    text = (ROOT / readme).read_text(encoding="utf-8")
    assert text.index(heading) < text.index(before)
