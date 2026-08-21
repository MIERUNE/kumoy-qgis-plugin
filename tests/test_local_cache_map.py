"""Tests for kumoy/local_cache/map.py

Verifies that get_cache_size sums sizes with the same matching rule as
clear(): any file whose name contains map_id.
"""

import types

import pytest


@pytest.mark.usefixtures("qgis_plugin_path")
class TestCacheSize:
    @pytest.fixture
    def cache(self, tmp_path, monkeypatch):
        from plugin_dir.kumoy.local_cache import map as map_cache

        cache_dir = tmp_path / "maps"
        cache_dir.mkdir()
        monkeypatch.setattr(map_cache, "get_cache_dir", lambda: str(cache_dir))
        return types.SimpleNamespace(mod=map_cache, cache_dir=cache_dir)

    def test_zero_when_not_cached(self, cache):
        assert cache.mod.get_cache_size("m-1") == 0

    def test_zero_when_cache_file_is_empty(self, cache):
        (cache.cache_dir / "m-1.qgs").write_bytes(b"")

        assert cache.mod.get_cache_size("m-1") == 0

    def test_sums_files_containing_map_id(self, cache):
        (cache.cache_dir / "m-1.qgs").write_bytes(b"x" * 100)
        (cache.cache_dir / "m-1_extra.dat").write_bytes(b"x" * 30)
        # Files of other maps are not counted
        (cache.cache_dir / "m-2.qgs").write_bytes(b"x" * 999)

        assert cache.mod.get_cache_size("m-1") == 130

    def test_total_zero_when_no_files(self, cache):
        assert cache.mod.get_total_cache_size() == 0

    def test_total_sums_all_files(self, cache):
        (cache.cache_dir / "m-1.qgs").write_bytes(b"x" * 100)
        (cache.cache_dir / "m-2.qgs").write_bytes(b"x" * 60)

        assert cache.mod.get_total_cache_size() == 160
