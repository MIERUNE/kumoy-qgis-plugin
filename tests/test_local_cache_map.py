"""Tests for kumoy/local_cache/map.py: map files left by older plugin versions."""

import os

import pytest


@pytest.fixture
def cache(qgis_plugin_path, tmp_path, monkeypatch):
    from plugin_dir.kumoy.local_cache import map as map_cache

    cache_dir = tmp_path / "maps"
    cache_dir.mkdir()
    monkeypatch.setattr(map_cache, "get_cache_dir", lambda: str(cache_dir))
    # The tests reach the directory through the module they test
    monkeypatch.setattr(map_cache, "dir", cache_dir, raising=False)
    return map_cache


class TestCacheSize:
    def test_zero_when_not_cached(self, cache):
        assert cache.get_cache_size("m-1") == 0

    def test_zero_without_cache_dir(self, cache, monkeypatch, tmp_path):
        monkeypatch.setattr(cache, "get_cache_dir", lambda: str(tmp_path / "none"))

        assert cache.get_cache_size("m-1") == 0
        assert cache.get_total_cache_size() == 0
        assert cache.clear("m-1") is True
        assert cache.clear_all() is True

    def test_sums_files_containing_map_id(self, cache):
        (cache.dir / "m-1.qgs").write_bytes(b"x" * 100)
        (cache.dir / "m-1_extra.dat").write_bytes(b"x" * 30)
        # Files of other maps are not counted
        (cache.dir / "m-2.qgs").write_bytes(b"x" * 999)

        assert cache.get_cache_size("m-1") == 130

    def test_total_sums_all_files(self, cache):
        (cache.dir / "m-1.qgs").write_bytes(b"x" * 100)
        (cache.dir / "m-2.qgs").write_bytes(b"x" * 60)

        assert cache.get_total_cache_size() == 160


class TestClear:
    def test_clear_removes_only_that_map(self, cache):
        (cache.dir / "m-1.qgs").write_bytes(b"x")
        (cache.dir / "m-2.qgs").write_bytes(b"x")

        assert cache.clear("m-1") is True
        assert [p.name for p in cache.dir.iterdir()] == ["m-2.qgs"]

    def test_clear_all_removes_files_and_subdirs(self, cache):
        (cache.dir / "m-1.qgs").write_bytes(b"x" * 100)
        sub = cache.dir / "sub"
        sub.mkdir()
        (sub / "nested.qgs").write_bytes(b"x" * 60)

        assert cache.clear_all() is True
        assert list(cache.dir.iterdir()) == []


class TestLegacyMapId:
    def test_map_file_in_cache(self, cache):
        assert cache.legacy_map_id(str(cache.dir / "abc-123.qgs")) == "abc-123"

    def test_relative_spelling_of_the_cache_dir(self, cache):
        path = os.path.join(str(cache.dir), "..", "maps", "abc.qgs")

        assert cache.legacy_map_id(path) == "abc"

    @pytest.mark.parametrize("name", ["abc.qgz", "abc.gpkg"])
    def test_other_files_in_cache(self, cache, name):
        assert cache.legacy_map_id(str(cache.dir / name)) is None

    def test_file_elsewhere(self, cache, tmp_path):
        assert cache.legacy_map_id(str(tmp_path / "abc.qgs")) is None

    @pytest.mark.parametrize("path", ["", "kumoy:abc"])
    def test_not_a_file(self, cache, path):
        assert cache.legacy_map_id(path) is None
