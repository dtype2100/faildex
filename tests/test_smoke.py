import relate

import faildex
from faildex.cli import main


def test_version_is_set():
    assert faildex.__version__


def test_cli_runs():
    assert main([]) == 0


def test_relate_opens_in_memory():
    db = relate.connect(":memory:")
    rows = list(db.execute("RETURN 1 + 2 AS n"))
    assert rows[0]["n"] == 3
