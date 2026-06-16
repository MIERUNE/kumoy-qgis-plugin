"""kumoy/local_cache/raster.py のテスト

COG は immutable なので「在れば即返す / 無ければダウンロード」だけを検証する。
ダウンロード本体（download.download_to_file）と URL 取得（api）はモックする。
"""

import os
import types

import pytest


@pytest.mark.usefixtures("qgis_plugin_path")
class TestSyncLocalCache:
    @pytest.fixture
    def setup(self, tmp_path, monkeypatch):
        from plugin_dir.kumoy.local_cache import raster as raster_cache

        cache_dir = tmp_path / "rasters"
        cache_dir.mkdir()
        monkeypatch.setattr(raster_cache, "_get_cache_dir", lambda: str(cache_dir))

        calls = {"get_url": 0, "download": 0}

        def fake_download(url, dest_path, progress_callback=None, is_canceled=None):
            calls["download"] += 1
            # ダウンロード成功を、.part への書き込みで模す
            with open(dest_path, "wb") as f:
                f.write(b"COG-BYTES")

        fake_api = types.SimpleNamespace(
            raster=types.SimpleNamespace(
                get_download_url=lambda rid: (
                    calls.__setitem__("get_url", calls["get_url"] + 1)
                    or f"https://s3/{rid}?sig=x"
                )
            )
        )
        monkeypatch.setattr(raster_cache, "api", fake_api)
        monkeypatch.setattr(raster_cache.download, "download_to_file", fake_download)

        yield types.SimpleNamespace(
            mod=raster_cache, cache_dir=str(cache_dir), calls=calls
        )

    def test_downloads_when_missing(self, setup):
        s = setup
        path = s.mod.sync_local_cache("r-1")

        assert path == os.path.join(s.cache_dir, "r-1.tif")
        assert os.path.exists(path)
        assert s.calls["download"] == 1
        assert s.calls["get_url"] == 1
        # 完成ファイルだけが残り、.part は消えている
        assert not os.path.exists(path + ".part")

    def test_returns_cached_without_network(self, setup):
        s = setup
        cached = os.path.join(s.cache_dir, "r-2.tif")
        with open(cached, "wb") as f:
            f.write(b"already-here")

        path = s.mod.sync_local_cache("r-2")

        assert path == cached
        assert s.calls["download"] == 0
        assert s.calls["get_url"] == 0

    def test_cancel_leaves_no_file(self, setup, monkeypatch):
        from plugin_dir.kumoy import download

        s = setup

        def cancel_download(url, dest_path, progress_callback=None, is_canceled=None):
            raise download.DownloadCanceled()

        monkeypatch.setattr(s.mod.download, "download_to_file", cancel_download)

        with pytest.raises(download.DownloadCanceled):
            s.mod.sync_local_cache("r-3")

        assert not os.path.exists(os.path.join(s.cache_dir, "r-3.tif"))

    def test_clear_removes_file(self, setup):
        s = setup
        path = s.mod.sync_local_cache("r-4")
        assert os.path.exists(path)

        assert s.mod.clear("r-4") is True
        assert not os.path.exists(path)

    def test_is_cached(self, setup):
        s = setup
        assert s.mod.is_cached("r-5") is False
        s.mod.sync_local_cache("r-5")
        assert s.mod.is_cached("r-5") is True
