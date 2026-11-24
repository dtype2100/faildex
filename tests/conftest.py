"""Every test runs with a throwaway home folder and no language setting of the person running it.

HOME and USERPROFILE point at a temporary folder, so nothing reads or writes the real
`~/.faildex` (store or config.json), and FAILDEX_LANG is removed, so the output is the
English default unless a test asks for Korean.
"""

import pytest

from faildex import i18n


@pytest.fixture(scope="session")
def _shared_cache(tmp_path_factory):
    # One copy of the public demo store for the whole run, outside the real ~/.cache.
    return tmp_path_factory.mktemp("cache")


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
