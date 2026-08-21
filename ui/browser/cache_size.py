"""Cache-size display helpers for the clear-cache UI.

Formats sizes for menu labels and confirmation dialogs, and builds
clear-cache actions whose enablement reflects cache existence.
"""

from typing import Callable, Protocol

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QLocale
from qgis.PyQt.QtWidgets import QAction, QWidget

from ... import i18n
from ...kumoy.constants import LOG_CATEGORY
from ...pyqt_version import Q_LOCALE_DATA_SIZE_TRADITIONAL


def format_data_size(size_bytes: int) -> str:
    """Locale-aware human-readable file size (e.g. '12.3 MB').

    Single entry point so every cache-size label formats identically.
    Traditional units (kB/MB, 1024 divisor) instead of Qt's default IEC
    (KiB/MiB), which most users find unfamiliar.
    """
    return QLocale().formattedDataSize(size_bytes, 2, Q_LOCALE_DATA_SIZE_TRADITIONAL)


def make_clear_cache_action(
    parent: QWidget,
    label: str,
    get_size: Callable[[], int],
    on_triggered: Callable[[], None],
) -> QAction:
    """Build a clear-cache QAction whose label shows the cache size.

    The size is appended as a locale-neutral " (12.3 MB)" suffix, following
    the tr("...") + suffix composition style used elsewhere in this plugin.

    get_size returns the cache size in bytes (0 when nothing is cached):
    - 0: disabled with the plain label, so cache absence is visible.
    - > 0: enabled with the size suffix.
    - OSError from get_size: enabled with a "size unknown" suffix. The cache
      dir may be unreadable, but the user must still be able to attempt
      clearing, and a raised exception here would swallow the whole context
      menu.
    """
    try:
        size = get_size()
        enabled = size > 0
        suffix = format_data_size(size) if size > 0 else None
    except OSError as e:
        QgsMessageLog.logMessage(
            f"Failed to read cache size: {e}", LOG_CATEGORY, Qgis.Warning
        )
        suffix, enabled = i18n.tr("size unknown"), True
    text = label if suffix is None else f"{label} ({suffix})"
    action = QAction(text, parent)
    action.setEnabled(enabled)
    action.triggered.connect(on_triggered)
    return action


def cache_size_text(get_size: Callable[[], int]) -> str:
    """Cache size string for dialog text; never raises.

    Falls back to a translated "size unknown" when the lookup fails.
    """
    try:
        return format_data_size(get_size())
    except OSError as e:
        QgsMessageLog.logMessage(
            f"Failed to read cache size: {e}", LOG_CATEGORY, Qgis.Warning
        )
        return i18n.tr("size unknown")


class HasCacheSize(Protocol):
    """Structural type: RasterItem/VectorItem/StyledMapItem share no base
    class, so items usable with combined_cache_size() are typed by shape."""

    def cache_size(self) -> int: ...


def combined_cache_size(items: list[HasCacheSize]) -> int:
    """Combined cache size in bytes of the selected browser items."""
    return sum(item.cache_size() for item in items)
