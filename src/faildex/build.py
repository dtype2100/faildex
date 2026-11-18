"""Build the committed store from the public datasets.

The store holds public data only. Each dataset is pinned to one revision in
`SOURCES`, downloaded by `make data` into `.tmp/data/<name>`, and read through
the same adapters that read a user's own logs. A Call keeps a pointer of the
form `<dataset name>/<path inside the dataset>:<line>`, never a local path.
"""

from __future__ import annotations

import shutil
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path

import relate

from faildex.adapters import claude_code, codex
from faildex.schema import BATCH, CallRecord, ingest


@dataclass(frozen=True)
class Source:
    name: str
    repo: str
    revision: str
    license: str
    agent: str
    paths: tuple[str, ...]

    @property
    def url(self) -> str:
        return f"https://huggingface.co/datasets/{self.repo}"


SOURCES = (
    Source(
        name="wisp",
        repo="crispwisp/wisp-claude-code-sessions",
        revision="c2c90b59174318ab0b163ec9c9ac82bb879288ce",
        license="MIT",
        agent="claude_code",
        paths=("transcripts",),
    ),
    Source(
        name="codex-trajectories",
        repo="israellaguan/codex-tool-use-trajectories",
        revision="69019b2c717fe7be8f4fab16b317e4b8bbcf831b",
        license="MIT",
        agent="codex",
        paths=("trajectories.train.jsonl", "trajectories.eval.jsonl"),
    ),
)

_SOURCE = """
MERGE (d:Source {name: $name})
  SET d.repo = $repo, d.revision = $revision, d.license = $license, d.url = $url
"""

_FROM = """
UNWIND $rows AS row
MATCH (s:Session {id: row.session_key}), (d:Source {name: row.source})
MERGE (s)-[:FROM]->(d)
"""

_COUNTS = {
    "Source": "MATCH (n:Source) RETURN count(n) AS n",
    "Session": "MATCH (n:Session) RETURN count(n) AS n",
    "Call": "MATCH (n:Call) RETURN count(n) AS n",
    "Command": "MATCH (n:Command) RETURN count(n) AS n",
    "ErrorSig": "MATCH (n:ErrorSig) RETURN count(n) AS n",
    "failed calls": "MATCH (n:Call) WHERE n.ok = false RETURN count(n) AS n",
    "relationships": "MATCH ()-[r]->() RETURN count(r) AS n",
}


def read_source(source: Source, data_dir: Path) -> Iterator[CallRecord]:
    """Records of one dataset, with pointers rewritten relative to the dataset."""
    root = data_dir / source.name
    paths = [root / rel for rel in source.paths]
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing; run `make data` first")
    if source.agent == "codex":
        records = codex.read_files(paths)  # one numbering across the dataset's files
    else:
        records = (record for path in paths for record in claude_code.read_dir(path))
    for record in records:
        inside = Path(record.source_path).resolve().relative_to(root.resolve())
        yield replace(record, source_path=f"{source.name}/{inside.as_posix()}")


def counts(db) -> dict[str, int]:
    return {name: next(iter(db.execute(query)))["n"] for name, query in _COUNTS.items()}


def _size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _peak_rss_mb() -> float:
    """Peak memory of this process in MB; 0.0 where `resource` is missing (Windows)."""
    try:
        import resource
    except ImportError:
        return 0.0
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024 if sys.platform == "darwin" else 1024)


def build_store(data_dir: Path, out: Path) -> dict:
    """Rebuild the store at `out` from scratch and return what was written.

    The new store is built next to `out` and swapped in only when the build
    succeeded, so a failed rebuild (missing data, a bad file) leaves the old
    store untouched.
    """
    started = time.monotonic()
    out.parent.mkdir(parents=True, exist_ok=True)
    work = out.parent / f".{out.name}.building"
    if work.exists():
        shutil.rmtree(work)
    try:
        _build_into(data_dir, work)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    old = out.parent / f".{out.name}.old"
    if old.exists():
        shutil.rmtree(old)
    if out.exists():
        out.rename(old)
    work.rename(out)
    shutil.rmtree(old, ignore_errors=True)
    from faildex.store import open_store

    db = open_store(out)
    try:
        found = counts(db)
    finally:
        db.close()
    return {
        "counts": found,
        "bytes": _size(out),
        "seconds": time.monotonic() - started,
        "peak_rss_mb": _peak_rss_mb(),
    }


def _build_into(data_dir: Path, out: Path) -> None:
    db = relate.connect(str(out))
    try:
        for source in SOURCES:
            records = list(read_source(source, data_dir))
            ingest(db, records)
            db.execute(
                "CREATE CONSTRAINT source_name IF NOT EXISTS "
                "FOR (n:Source) REQUIRE n.name IS UNIQUE"
            )
            db.execute(
                _SOURCE,
                {
                    "name": source.name,
                    "repo": source.repo,
                    "revision": source.revision,
                    "license": source.license,
                    "url": source.url,
                },
            )
            keys = sorted({r.session_key for r in records})
            rows = [{"session_key": k, "source": source.name} for k in keys]
            for i in range(0, len(rows), BATCH):
                db.execute(_FROM, {"rows": rows[i : i + BATCH]})
        db.commit()
        db.flush()
    finally:
        db.close()


def report(result: dict, out: Path) -> str:
    lines = [f"store: {out}"]
    lines += [f"  {name:<14} {value:>8,}" for name, value in result["counts"].items()]
    lines.append(f"  {'size on disk':<14} {result['bytes'] / 1e6:>8.2f} MB")
    lines.append(f"  {'build time':<14} {result['seconds']:>8.1f} s")
    lines.append(f"  {'peak memory':<14} {result['peak_rss_mb']:>8.0f} MB")
    return "\n".join(lines)
