"""プラグインのエントリポイントを import できることのスモークテスト。

ユニットテストはドメイン層 (kumoy/) 中心で UI 層を import しないため、
リファクタやマージで import が切れても検出できない。plugin.py は UI・
Processing を含むほぼ全モジュールを連鎖的に import するので、これ一つで
QGIS 起動時の ImportError（classFactory 失敗）を再現・検出できる。
"""


class TestPluginImport:
    def test_plugin_module_imports(self, qgis_app, qgis_plugin_path):
        from plugin_dir.plugin import KumoyPlugin

        assert KumoyPlugin is not None
