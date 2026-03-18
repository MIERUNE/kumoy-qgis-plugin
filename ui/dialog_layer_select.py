from typing import List

from qgis.core import QgsVectorLayer
from qgis.PyQt.QtCore import QCoreApplication
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

from ..pyqt_version import QT_DIALOG_BUTTON_CANCEL, QT_DIALOG_BUTTON_OK

_UPGRADE_HINT = (
    "To upload more, delete existing vectors from the cloud or upgrade your plan."
)


def _get_usage_color(percentage: float) -> str:
    """Get color based on usage percentage."""
    if percentage >= 100:
        return "#f44336"
    elif percentage >= 75:
        return "#ffa726"
    return "#8bc34a"


class LayerSelectDialog(QDialog):
    """Dialog for selecting which local layers to convert to Kumoy layers."""

    def __init__(
        self,
        layers: List[QgsVectorLayer],
        max_vectors: int,
        current_vectors: int,
        parent=None,
    ):
        super().__init__(parent)
        self._layers = layers
        self._max_vectors = max_vectors
        self._current_vectors = current_vectors
        self._max_layers = max(max_vectors - current_vectors, 0)
        self._checkboxes: List[QCheckBox] = []
        self._setup_ui()

    def tr(self, message: str) -> str:
        return QCoreApplication.translate("LayerSelectDialog", message)

    @property
    def selected_layers(self) -> List[QgsVectorLayer]:
        return [
            layer for layer, cb in zip(self._layers, self._checkboxes) if cb.isChecked()
        ]

    def _setup_ui(self) -> None:
        self.setWindowTitle(self.tr("Select Layers to Convert"))
        self.setMinimumWidth(400)
        self.setMinimumHeight(300)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        if self._max_layers == 0:
            limit_label = QLabel(
                self.tr(
                    "Vector limit ({}) has been reached. No more vectors can be added.\n"
                    "{}"
                ).format(self._max_vectors, self.tr(_UPGRADE_HINT))
            )
            limit_label.setWordWrap(True)
            layout.addWidget(limit_label)
            layout.addStretch()

            close_button_box = QDialogButtonBox(QT_DIALOG_BUTTON_CANCEL)
            close_button_box.rejected.connect(self.reject)
            layout.addWidget(close_button_box)
            return

        # Scrollable checkbox list
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_widget = QWidget()
        self._list_layout = QVBoxLayout(scroll_widget)
        self._list_layout.setSpacing(4)

        for i, layer in enumerate(self._layers):
            cb = QCheckBox(layer.name())
            cb.setChecked(False)
            if layer.isModified():
                cb.setEnabled(False)
                cb.setText(self.tr("{} (unsaved edits)").format(layer.name()))
            else:
                cb.toggled.connect(self._on_checkbox_toggled)
            self._checkboxes.append(cb)
            self._list_layout.addWidget(cb)

        self._list_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

        # Usage bar
        usage_row = QHBoxLayout()
        usage_row.setSpacing(10)
        self._count_label = QLabel()
        self._count_label.setFixedWidth(140)
        usage_row.addWidget(self._count_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setMinimumHeight(6)
        self._progress_bar.setMaximumHeight(6)
        self._progress_bar.setMaximum(max(self._max_layers, 1))
        usage_row.addWidget(self._progress_bar, 1)
        layout.addLayout(usage_row)

        # Bottom row: Select all / Deselect all (left) + OK / Cancel (right)
        bottom_row = QHBoxLayout()

        self._select_all_btn = QPushButton(self.tr("Select all"))
        self._select_all_btn.clicked.connect(self._select_all)
        bottom_row.addWidget(self._select_all_btn)

        self._deselect_all_btn = QPushButton(self.tr("Deselect all"))
        self._deselect_all_btn.clicked.connect(self._deselect_all)
        bottom_row.addWidget(self._deselect_all_btn)

        bottom_row.addStretch()

        button_box = QDialogButtonBox(QT_DIALOG_BUTTON_OK | QT_DIALOG_BUTTON_CANCEL)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        self._ok_button = button_box.button(QT_DIALOG_BUTTON_OK)
        bottom_row.addWidget(button_box)

        layout.addLayout(bottom_row)

        self._update_state()

    def _get_checked_count(self) -> int:
        return sum(1 for cb in self._checkboxes if cb.isChecked())

    def _on_checkbox_toggled(self) -> None:
        self._update_state()

    def _update_state(self) -> None:
        checked_count = self._get_checked_count()
        at_limit = checked_count >= self._max_layers

        for layer, cb in zip(self._layers, self._checkboxes):
            if layer.isModified():
                continue
            if not cb.isChecked():
                cb.setEnabled(not at_limit)

        self._count_label.setText(
            self.tr("{} / {} selected").format(checked_count, self._max_layers)
        )

        percentage = checked_count / self._max_layers * 100
        self._progress_bar.setValue(min(checked_count, self._max_layers))

        self._progress_bar.setStyleSheet(
            f"""
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
        )
        self._ok_button.setEnabled(True)
        self._select_all_btn.setEnabled(not at_limit)

    def _select_all(self) -> None:
        for cb in self._checkboxes:
            cb.blockSignals(True)
        count = 0
        for layer, cb in zip(self._layers, self._checkboxes):
            if layer.isModified():
                continue
            if count < self._max_layers:
                cb.setChecked(True)
                count += 1
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
