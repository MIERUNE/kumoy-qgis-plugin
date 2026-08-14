"""Cache-size display helpers for the clear-cache UI.

Formats sizes for menu labels and confirmation dialogs, and builds
clear-cache actions whose enablement reflects cache existence.
"""

from typing import Callable, Optional, Protocol

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
    get_size: Callable[[], Optional[int]],
    on_triggered: Callable[[], None],
) -> QAction:
    """Build a clear-cache QAction whose label shows the cache size.

    The size is appended as a locale-neutral " (12.3 MB)" suffix, following
    the tr("...") + suffix composition style used elsewhere in this plugin.

    get_size returns the cache size in bytes, or None when no cache exists:
    - None: disabled with the plain label, so cache absence is visible.
    - int (0 included): enabled with the size suffix. An empty (0-byte) cache
      must stay clearable, hence existence — not size — decides enablement.
    - OSError from get_size: enabled with the plain label. The cache dir may
      be unreadable, but the user must still be able to attempt clearing,
      and a raised exception here would swallow the whole context menu.
    """
    try:
        size = get_size()
        enabled = size is not None
    except OSError as e:
        QgsMessageLog.logMessage(
            f"Failed to read cache size: {e}", LOG_CATEGORY, Qgis.Warning
        )
        size, enabled = None, True
    text = label if size is None else f"{label} ({format_data_size(size)})"
    action = QAction(text, parent)
    action.setEnabled(enabled)
    action.triggered.connect(on_triggered)
    return action


def cache_size_text(get_size: Callable[[], Optional[int]]) -> str:
    """Cache size string for dialog text; never raises.

    Falls back to a translated "size unknown" when the lookup fails or the
    cache vanished between opening the menu and the dialog.
    """
    try:
        size = get_size()
    except OSError as e:
        QgsMessageLog.logMessage(
            f"Failed to read cache size: {e}", LOG_CATEGORY, Qgis.Warning
        )
        size = None
    if size is None:
        return i18n.tr("size unknown")
    return format_data_size(size)


class HasCacheSize(Protocol):
    """Structural type: RasterItem/VectorItem/StyledMapItem share no base
    class, so items usable with combined_cache_size() are typed by shape."""

    def cache_size(self) -> Optional[int]: ...


def combined_cache_size(items: list[HasCacheSize]) -> Optional[int]:
    """Combined cache size of selected browser items (None when none cached)."""
    sizes = [item.cache_size() for item in items]
    present = [s for s in sizes if s is not None]
    return sum(present) if present else None
