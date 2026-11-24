"""The numbers in the documents are the numbers `make eval` prints."""

from pathlib import Path

import pytest

from faildex.evaluate import evaluate
from faildex.store import open_store

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def results():
    db = open_store(ROOT / "store")
    try:
        return evaluate(db)[-1], evaluate(db, kinds=("text",))[-1]
    finally:
        db.close()


def _row(result) -> str:
    return (
        f"| {result.later_failures} | {result.recurring} ({result.recurrence:.1%}) "
        f"| {result.warnable} ({result.warnable_share:.1%}) |"
    )


def test_readme_table_matches_the_committed_store(results):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    both, text_only = results
    assert f"| All failure keys {_row(both)}" in readme
    assert f"| Failure text only {_row(text_only)}" in readme
    assert f"{both.recurrence:.0%} of the failures" in readme
    assert f"same {both.recurring} of {both.later_failures}" in readme


def test_evaluation_doc_matches_the_committed_store(results):
    doc = (ROOT / "docs" / "evaluation.md").read_text(encoding="utf-8")
    both, _ = results
    assert f"| All | {both.earlier_sessions} / {both.later_sessions} {_row(both)}" in doc
    assert f"{len(both.later_keys)} distinct failure keys" in doc
    assert f"same {both.recurring} of {both.later_failures}" in doc


def test_relate_webassembly_reaches_the_same_numbers(results, tmp_path):
    """The browser demo recomputes the evaluation in another build of the engine."""
    import json
    import shutil
    import subprocess

    site = ROOT / "site"
    if not shutil.which("node") or not (site / "vendor" / "relate_bg.wasm").is_file():
        pytest.skip("run `make site` first (needs Node)")
    if not (site / "data.json").is_file():
        pytest.skip("run `make site` first")
    out = subprocess.run(
        ["node", str(site / "check.mjs")], capture_output=True, text=True, check=True, timeout=120
    )
    total = json.loads(out.stdout)["scores"][-1]
    both, _ = results
    assert (total["failures"], total["recurring"], total["warnable"]) == (
        both.later_failures,
        both.recurring,
        both.warnable,
    )


def test_every_test_named_in_the_evaluation_doc_exists():
    import re

    doc = (ROOT / "docs" / "evaluation.md").read_text(encoding="utf-8")
    named = re.findall(r"`(test_\w+\.py)::(test_\w+)`", doc)
    assert len(named) >= 12
    for file, function in named:
        assert f"def {function}(" in (ROOT / "tests" / file).read_text(encoding="utf-8"), (
            f"{file}::{function}"
        )
