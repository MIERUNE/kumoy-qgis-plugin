"""Tests for ui/browser/cache_size.py

Verifies the locale/unit formatting of format_data_size and the
clear-cache helpers (the three branches of make_clear_cache_action,
cache_size_text, and combined_cache_size).
"""

import types

import pytest
from qgis.PyQt.QtCore import QLocale
from qgis.PyQt.QtWidgets import QMenu


@pytest.mark.usefixtures("qgis_plugin_path")
class TestFormatDataSize:
    """QLocale varies unit labels by locale too (ja_JP: KB, fr_FR: ko, ...),
    so pin a known locale (en_US) during the test and restore it afterwards."""

    @pytest.fixture(autouse=True)
    def en_locale(self):
        original = QLocale()
        QLocale.setDefault(QLocale("en_US"))
        yield
        QLocale.setDefault(original)

    def test_uses_traditional_units_not_iec(self):
        from plugin_dir.ui.browser.cache_size import format_data_size

        formatted = format_data_size(12 * 1024 * 1024)

        assert "MiB" not in formatted
        assert "MB" in formatted

    def test_kilobyte_range(self):
        from plugin_dir.ui.browser.cache_size import format_data_size

        formatted = format_data_size(2048)

        assert "KiB" not in formatted
        assert "kB" in formatted


@pytest.mark.usefixtures("qgis_plugin_path")
class TestMakeClearCacheAction:
    """Covers the three branches (no cache / cached / size lookup failure).
    Size formatting is locale-dependent, so only the label prefix is asserted."""

    @pytest.fixture
    def menu(self):
        return QMenu()

    def _make(self, menu, get_size, on_triggered=lambda: None):
        from plugin_dir.ui.browser.cache_size import make_clear_cache_action

        return make_clear_cache_action(menu, "Clear", get_size, on_triggered)

    def test_disabled_with_plain_label_when_no_cache(self, menu):
        action = self._make(menu, lambda: None)

        assert action.isEnabled() is False
        assert action.text() == "Clear"

    def test_enabled_with_size_label_when_cached(self, menu):
        action = self._make(menu, lambda: 2048)

        assert action.isEnabled() is True
        assert action.text().startswith("Clear (")

    def test_zero_byte_cache_is_still_clearable(self, menu):
        action = self._make(menu, lambda: 0)

        assert action.isEnabled() is True
        assert action.text().startswith("Clear (")

    def test_enabled_with_plain_label_on_oserror(self, menu):
        def unreadable():
            raise PermissionError("cache dir unreadable")

        action = self._make(menu, unreadable)

        # Clearing must remain possible even when the size cannot be read;
        # propagating the exception would swallow the whole context menu
        assert action.isEnabled() is True
        assert action.text() == "Clear"

    def test_trigger_invokes_callback(self, menu):
        calls = []
        action = self._make(menu, lambda: 100, on_triggered=lambda: calls.append(1))

        action.trigger()

        assert calls == [1]


@pytest.mark.usefixtures("qgis_plugin_path")
class TestCacheSizeText:
    def test_formats_known_size(self):
        from plugin_dir.ui.browser.cache_size import cache_size_text, format_data_size

        assert cache_size_text(lambda: 2048) == format_data_size(2048)

    def test_unknown_when_no_cache(self):
        from plugin_dir.ui.browser.cache_size import cache_size_text

        assert cache_size_text(lambda: None) == "size unknown"

    def test_unknown_on_oserror(self):
        from plugin_dir.ui.browser.cache_size import cache_size_text

        def unreadable():
            raise PermissionError("cache dir unreadable")

        assert cache_size_text(unreadable) == "size unknown"


@pytest.mark.usefixtures("qgis_plugin_path")
class TestCombinedCacheSize:
    def _item(self, size):
        return types.SimpleNamespace(cache_size=lambda: size)

    def test_none_when_nothing_cached(self):
        from plugin_dir.ui.browser.cache_size import combined_cache_size

        assert combined_cache_size([self._item(None), self._item(None)]) is None

    def test_sums_only_cached_items(self):
        from plugin_dir.ui.browser.cache_size import combined_cache_size

        items = [self._item(None), self._item(100), self._item(50)]

        assert combined_cache_size(items) == 150
