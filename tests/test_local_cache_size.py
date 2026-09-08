"""Tests for kumoy/local_cache/size.py

Verifies that dir_total_size counts files in nested directories and that
OSError propagates (callers show a "size unknown" label on failure).
"""

import pytest


@pytest.mark.usefixtures("qgis_plugin_path")
class TestDirTotalSize:
    @pytest.fixture
    def size(self):
        from plugin_dir.kumoy.local_cache import size

        return size

    def test_zero_when_empty(self, size, tmp_path):
        assert size.dir_total_size(str(tmp_path)) == 0

    def test_sums_files_directly_under_dir(self, size, tmp_path):
        (tmp_path / "a.tif").write_bytes(b"x" * 100)
        (tmp_path / "b.tif").write_bytes(b"x" * 60)

        assert size.dir_total_size(str(tmp_path)) == 160

    def test_sums_files_in_nested_dirs(self, size, tmp_path):
        (tmp_path / "a.tif").write_bytes(b"x" * 100)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.tif").write_bytes(b"x" * 60)
        subsub = sub / "subsub"
        subsub.mkdir()
        (subsub / "c.tif").write_bytes(b"x" * 15)

        assert size.dir_total_size(str(tmp_path)) == 175

    def test_empty_subdir_adds_nothing(self, size, tmp_path):
        (tmp_path / "a.tif").write_bytes(b"x" * 100)
        (tmp_path / "empty").mkdir()

        assert size.dir_total_size(str(tmp_path)) == 100

    def test_oserror_propagates_when_dir_missing(self, size, tmp_path):
        with pytest.raises(OSError):
            size.dir_total_size(str(tmp_path / "missing"))
