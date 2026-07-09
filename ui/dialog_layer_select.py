from dataclasses import dataclass
from typing import Callable, List, Optional

from qgis.core import QgsApplication, QgsMapLayer, QgsVectorLayer
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import i18n
from ..pyqt_version import QT_DIALOG_BUTTON_CANCEL, QT_DIALOG_BUTTON_OK


def _get_usage_color(percentage: float) -> str:
    """Get color based on usage percentage."""
    if percentage >= 100:
        return "#f44336"
    elif percentage >= 75:
        return "#ffa726"
    return "#8bc34a"


def _usage_bar_style(percentage: float) -> str:
    return f"""
        QProgressBar {{
            border: none;
            border-radius: 3px;
            background-color: #e0e0e0;
        }}
        QProgressBar::chunk {{
            background-color: {_get_usage_color(percentage)};
            border-radius: 3px;
        }}
    """


@dataclass(frozen=True)
class LayerQuota:
    """Plan-based count quota for one layer type (vectors or rasters)."""

    max_layers: int  # plan cap for the organization
    current: int  # layers the organization already has

    @property
    def remaining(self) -> int:
        return max(self.max_layers - self.current, 0)


class _QuotaGroup:
    """Selection state for one layer type under a count quota.

    Owns the quota, the checkboxes of that type, and the usage row widgets;
    the dialog just asks it to re-apply the cap after any toggle.
    """

    def __init__(
        self,
        quota: LayerQuota,
        count_label_text: str,
        limit_reached_text: str,
    ) -> None:
        self.quota = quota
        self._count_label_text = count_label_text
        self._limit_reached_text = limit_reached_text
        self.entries: List[tuple[QgsMapLayer, QCheckBox]] = []
        self._count_label: Optional[QLabel] = None
        self._progress_bar: Optional[QProgressBar] = None

    def add_usage_row(self, layout: QVBoxLayout) -> None:
        if self.quota.remaining == 0:
            limit_label = QLabel(self._limit_reached_text.format(self.quota.max_layers))
            limit_label.setWordWrap(True)
            layout.addWidget(limit_label)
            return

        row = QHBoxLayout()
        row.setSpacing(10)
        self._count_label = QLabel()
        self._count_label.setFixedWidth(180)
        row.addWidget(self._count_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setMinimumHeight(6)
        self._progress_bar.setMaximumHeight(6)
        self._progress_bar.setMaximum(self.quota.remaining)
        row.addWidget(self._progress_bar, 1)
        layout.addLayout(row)

    def checked_count(self) -> int:
        return sum(1 for _, cb in self.entries if cb.isChecked())

    def at_limit(self) -> bool:
        return self.checked_count() >= self.quota.remaining

    def update(self, is_locked: Callable[[QgsMapLayer], bool]) -> None:
        checked_count = self.checked_count()
        at_limit = self.at_limit()

        for layer, cb in self.entries:
            if is_locked(layer):
                continue
            if not cb.isChecked():
                cb.setEnabled(not at_limit)

        if self._count_label is None or self._progress_bar is None:
            return

        self._count_label.setText(
            self._count_label_text.format(checked_count, self.quota.remaining)
        )
        percentage = checked_count / self.quota.remaining * 100
        self._progress_bar.setValue(min(checked_count, self.quota.remaining))
        self._progress_bar.setStyleSheet(_usage_bar_style(percentage))


class LayerSelectDialog(QDialog):
    """Dialog for selecting which local layers to convert to Kumoy layers.

    Accepts a mixed list of vector and raster layers. Each layer type has its
    own plan-based count quota (``vector_quota``/``raster_quota``): a usage
    bar is shown per type and selection of that type is capped at the
    remaining slots. Omit a quota and selection of that type is unlimited
    with no bar.
    """

    def __init__(
        self,
        layers: List[QgsMapLayer],
        vector_quota: Optional[LayerQuota] = None,
        raster_quota: Optional[LayerQuota] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._layers = layers
        self._checkboxes: List[QCheckBox] = []

        self._vector_group = (
            _QuotaGroup(
                vector_quota,
                i18n.tr("{} vectors selected ({} max)"),
                i18n.tr(
                    "Vector limit ({}) has been reached. No more vectors can be added."
                ),
            )
            if vector_quota is not None
            else None
        )
        self._raster_group = (
            _QuotaGroup(
                raster_quota,
                i18n.tr("{} rasters selected ({} max)"),
                i18n.tr(
                    "Raster limit ({}) has been reached. No more rasters can be added."
                ),
            )
            if raster_quota is not None
            else None
        )
        self._setup_ui()

    @property
    def selected_layers(self) -> List[QgsMapLayer]:
        return [
            layer for layer, cb in zip(self._layers, self._checkboxes) if cb.isChecked()
        ]

    def _group_for(self, layer: QgsMapLayer) -> Optional[_QuotaGroup]:
        if isinstance(layer, QgsVectorLayer):
            return self._vector_group
        return self._raster_group

    def _setup_ui(self) -> None:
        self.setWindowTitle(i18n.tr("Select Layers to Convert"))
        self.setMinimumWidth(400)
        self.setMinimumHeight(300)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Scrollable checkbox list
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_widget = QWidget()
        self._list_layout = QVBoxLayout(scroll_widget)
        self._list_layout.setSpacing(4)

        for layer in self._layers:
            cb = QCheckBox(layer.name())
            # レイヤーパネルと同じQGISテーマアイコンでVector/Rasterを区別する
            cb.setIcon(
                QgsApplication.getThemeIcon(
                    "/mIconVector.svg"
                    if isinstance(layer, QgsVectorLayer)
                    else "/mIconRaster.svg"
                )
            )
            cb.setChecked(False)
            locked_reason = self._locked_reason(layer)
            if locked_reason is not None:
                cb.setEnabled(False)
                cb.setText(locked_reason.format(layer.name()))
            else:
                cb.toggled.connect(self._on_checkbox_toggled)
            self._checkboxes.append(cb)
            self._list_layout.addWidget(cb)

            group = self._group_for(layer)
            if group is not None:
                group.entries.append((layer, cb))

        self._list_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

        # One usage row per quota-capped layer type present in the list.
        for group in (self._vector_group, self._raster_group):
            if group is not None and group.entries:
                group.add_usage_row(layout)

        # Bottom row: Select all / Deselect all (left) + OK / Cancel (right)
        bottom_row = QHBoxLayout()

        self._select_all_btn = QPushButton(i18n.tr("Select all"))
        self._select_all_btn.clicked.connect(self._select_all)
        bottom_row.addWidget(self._select_all_btn)

        self._deselect_all_btn = QPushButton(i18n.tr("Deselect all"))
        self._deselect_all_btn.clicked.connect(self._deselect_all)
        bottom_row.addWidget(self._deselect_all_btn)

        bottom_row.addStretch()

        button_box = QDialogButtonBox(QT_DIALOG_BUTTON_OK | QT_DIALOG_BUTTON_CANCEL)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        bottom_row.addWidget(button_box)

        layout.addLayout(bottom_row)

        self._update_state()

    @staticmethod
    def _locked_reason(layer: QgsMapLayer) -> Optional[str]:
        """Label format string ("{}" = layer name) if the layer cannot be
        selected, else None. Vectors with unsaved edits would upload a stale
        snapshot; rasters without a CRS cannot be placed on the map."""
        if isinstance(layer, QgsVectorLayer):
            if layer.isModified():
                return i18n.tr("{} (unsaved edits)")
            return None
        if not layer.crs().isValid():
            return i18n.tr("{} (CRS not set)")
        return None

    @classmethod
    def _is_locked(cls, layer: QgsMapLayer) -> bool:
        return cls._locked_reason(layer) is not None

    def _on_checkbox_toggled(self) -> None:
        self._update_state()

    def _update_state(self) -> None:
        for group in (self._vector_group, self._raster_group):
            if group is not None:
                group.update(self._is_locked)

    def _select_all(self) -> None:
        for cb in self._checkboxes:
            cb.blockSignals(True)
        counts = {self._vector_group: 0, self._raster_group: 0}
        for layer, cb in zip(self._layers, self._checkboxes):
            if self._is_locked(layer):
                continue
            group = self._group_for(layer)
            if group is None or counts[group] < group.quota.remaining:
                cb.setChecked(True)
                counts[group] = counts.get(group, 0) + 1
            else:
                cb.setChecked(False)
        for cb in self._checkboxes:
            cb.blockSignals(False)
        self._update_state()

    def _deselect_all(self) -> None:
        for cb in self._checkboxes:
            cb.blockSignals(True)
        for cb in self._checkboxes:
            cb.setChecked(False)
        for cb in self._checkboxes:
            cb.blockSignals(False)
        self._update_state()
