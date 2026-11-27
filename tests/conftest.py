"""Every test runs with a throwaway home folder and no language setting of the person running it.

HOME and USERPROFILE point at a temporary folder, so nothing reads or writes the real
`~/.faildex` (store or config.json), and FAILDEX_LANG is removed, so the output is the
English default unless a test asks for Korean.

No test writes in the repository's `store/`: a test that reads the public demo store
opens `public_copy`, its cache copy in the run's temporary cache folder.
"""

import pytest

from faildex import i18n


@pytest.fixture(scope="session")
def _shared_cache(tmp_path_factory):
    # One copy of the public demo store for the whole run, outside the real ~/.cache.
    return tmp_path_factory.mktemp("cache")


@pytest.fixture(scope="session")
def public_copy(_shared_cache):
    """The public demo store's cache copy, made and opened once (so a read-only open
    works), in the run's temporary cache: the folder `public_store()` gives every test."""
    from faildex.store import open_store, public_store

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("XDG_CACHE_HOME", str(_shared_cache))
        path = public_store()
        open_store(path).close()
    return path


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch, _shared_cache):
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(_shared_cache))
    monkeypatch.delenv("FAILDEX_LANG", raising=False)
    i18n.use("en", "default")
    yield home
    i18n.use("en", "default")


@pytest.fixture(autouse=True)
def _no_background_index(monkeypatch):
    """A hook that finds no index starts a rebuild in the background; tests that call the
    hook through the CLI should not leave such processes behind, unless they test it."""
    from faildex import index

    monkeypatch.setattr(index, "start_rebuild", lambda store: None)
