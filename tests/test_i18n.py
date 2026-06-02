"""i18n パッケージ（load / tr）のテスト。

QGIS 非依存。辞書ルックアップと原文フォールバック、ロケール JSON のロードを検証する。
"""

import pytest

from plugin_dir import i18n


@pytest.fixture(autouse=True)
def _restore_translations():
    """各テストが _translations を汚さないよう退避・復元する。"""
    saved = i18n._translations
    yield
    i18n._translations = saved


def test_tr_returns_translation_when_present():
    i18n._translations = {"Save Map": "マップを保存"}
    assert i18n.tr("Save Map") == "マップを保存"


def test_tr_falls_back_to_source_when_missing():
    i18n._translations = {"Save Map": "マップを保存"}
    assert i18n.tr("Unknown String") == "Unknown String"


def test_tr_placeholder_is_left_for_caller_format():
    i18n._translations = {"count: {}": "件数: {}"}
    assert i18n.tr("count: {}").format(3) == "件数: 3"


def test_load_reads_locale_json():
    i18n.load("ja")
    assert i18n._translations, "ja.json should load a non-empty dict"
    # 既知のキーが訳されること（原文フォールバックでないこと）
    assert i18n.tr("Error") != "Error"


def test_load_missing_locale_falls_back_to_source():
    i18n.load("__nonexistent_locale__")
    assert i18n._translations == {}
    assert i18n.tr("Error") == "Error"
