"""kumoy.local_cache.raster: file operations of the COG cache."""

import os

import pytest


@pytest.fixture
def cache(qgis_app, tmp_path, monkeypatch):
    from plugin_dir.kumoy.local_cache import raster

    cache_dir = tmp_path / "rasters"
    cache_dir.mkdir()
    monkeypatch.setattr(raster, "_get_cache_dir", lambda: str(cache_dir))
    raster.dir = str(cache_dir)
    return raster


def _write(path, size):
    with open(path, "wb") as f:
        f.write(b"x" * size)


def test_commit_turns_part_into_cache_entry(cache):
    part = cache.new_part_path("r-1")
    _write(part, 10)
    assert not cache.is_cached("r-1")

    path = cache.commit("r-1", part)

    assert path == os.path.join(cache.dir, "r-1.tif")
    assert cache.is_cached("r-1")
    assert os.listdir(cache.dir) == ["r-1.tif"]


def test_part_paths_are_unique(cache):
    # Two downloads of one raster must never share a partial file
    assert cache.new_part_path("r-1") != cache.new_part_path("r-1")


def test_commit_keeps_existing_entry(cache):
    _write(cache.get_cache_path("r-1"), 5)
    part = cache.new_part_path("r-1")
    _write(part, 10)

    cache.commit("r-1", part)

    assert os.path.getsize(cache.get_cache_path("r-1")) == 5
    assert not os.path.exists(part)


def test_store_moves_file_into_cache(cache, tmp_path):
    src = tmp_path / "uploaded.tif"
    src.write_bytes(b"COG")

    path = cache.store("r-6", str(src))

    assert open(path, "rb").read() == b"COG"
    assert not src.exists()
    assert os.listdir(cache.dir) == ["r-6.tif"]


def test_sizes_count_partial_downloads(cache):
    assert cache.get_cache_size("r-7") == 0
    _write(cache.get_cache_path("r-7"), 100)
    _write(cache.new_part_path("r-7"), 40)
    _write(cache.get_cache_path("r-8"), 60)

    assert cache.get_cache_size("r-7") == 140
    assert cache.get_total_cache_size() == 200


def test_clear_removes_entry_and_parts_only(cache):
    _write(cache.get_cache_path("r-1"), 1)
    _write(cache.new_part_path("r-1"), 1)
    _write(cache.get_cache_path("r-10"), 1)  # same prefix, other raster

    assert cache.clear("r-1") is True

    assert os.listdir(cache.dir) == ["r-10.tif"]


def test_clear_all_removes_files_and_subdirs(cache):
    _write(cache.get_cache_path("r-1"), 1)
    os.makedirs(os.path.join(cache.dir, "sub"))
    _write(os.path.join(cache.dir, "sub", "x"), 1)

    assert cache.clear_all() is True
    assert os.listdir(cache.dir) == []
