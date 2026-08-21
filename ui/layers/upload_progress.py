"""Progress dialog shared by a whole batch of layer uploads.

One dialog per batch instead of one per layer (Issue #538): a 100-layer save
now shows "3 of 100" and takes a single Cancel press to abort the rest.
Lifetime belongs to the flow that opens ``upload_progress()``; upload code only
reports into the dialog it is handed.
"""

from contextlib import contextmanager

from qgis.PyQt.QtCore import QCoreApplication, pyqtSignal
from qgis.PyQt.QtGui import QFontMetrics
from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)
from qgis.utils import iface

from ... import i18n
from ...pyqt_version import QT_APPLICATION_MODAL, QT_TEXT_ELIDE_MODE

# Overall bar counts 100 steps per layer so within-layer progress shows there too
_STEPS_PER_LAYER = 100


@contextmanager
def upload_progress(total: int):
    """Open a dialog for ``total`` layers and always close it on exit."""
    dialog = UploadProgressDialog(total, iface.mainWindow())
    dialog.show()
    try:
        yield dialog
    finally:
        dialog.finish()


class UploadProgressDialog(QDialog):
    """Batch upload progress with a single cancel for the whole batch.

    Cancel only flags ``is_canceled()`` and emits ``canceled``; aborting the
    running upload and skipping the rest is the caller's decision.
    """

    canceled = pyqtSignal()

    def __init__(self, total: int, parent=None) -> None:
        super().__init__(parent)
        self._total = max(total, 1)
        self._current_index = 0
        self._canceled = False
        # resizeEvent can arrive before the widgets below exist
        self._layer_message = ""
        self._layer_label = None

        self.setWindowTitle(i18n.tr("Kumoy Upload"))
        self.setWindowModality(QT_APPLICATION_MODAL)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Overall progress is meaningless for a single layer, so it is hidden below
        self._overall_label = QLabel()
        layout.addWidget(self._overall_label)

        self._overall_bar = QProgressBar()
        self._overall_bar.setMaximum(self._total * _STEPS_PER_LAYER)
        self._overall_bar.setValue(0)
        layout.addWidget(self._overall_bar)

        if self._total == 1:
            self._overall_label.hide()
            self._overall_bar.hide()

        # Elide rather than wrap: wrapped long layer names outgrow the dialog
        # height and make it jitter per layer. Full text goes in the tooltip.
        self._layer_label = QLabel()
        self._layer_label.setWordWrap(False)
        layout.addWidget(self._layer_label)

        self._layer_bar = QProgressBar()
        self._layer_bar.setMaximum(_STEPS_PER_LAYER)
        self._layer_bar.setValue(0)
        layout.addWidget(self._layer_bar)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self._cancel_button = QPushButton(i18n.tr("Cancel"))
        self._cancel_button.clicked.connect(self.request_cancel)
        button_row.addWidget(self._cancel_button)
        layout.addLayout(button_row)

        self._update_overall_label()

    def is_canceled(self) -> bool:
        return self._canceled

    def request_cancel(self) -> None:
        # Ignore repeats so the user is not asked once per remaining layer
        if self._canceled:
            return
        self._canceled = True
        self._cancel_button.setEnabled(False)
        self._cancel_button.setText(i18n.tr("Cancelling..."))
        self._overall_label.setText(i18n.tr("Cancelling upload..."))
        self.canceled.emit()
        self._pump()

    def reject(self) -> None:
        # Esc and the window close button mean cancel, not close: closing
        # mid-upload leaves progress with nowhere to go. Only finish() closes.
        self.request_cancel()

    def begin_layer(self, name: str, index: int) -> None:
        self._current_index = index
        self._set_layer_message(i18n.tr("Uploading layer '{}'...").format(name))
        self._layer_bar.setValue(0)
        self._overall_bar.setValue(index * _STEPS_PER_LAYER)
        self._update_overall_label()

        # Issue #356: the dialog is sometimes left unpainted on Windows
        self.repaint()
        self._pump()
        self.repaint()
        self._pump()

    def set_layer_progress(self, percent: float) -> None:
        value = min(max(int(percent), 0), _STEPS_PER_LAYER)
        self._layer_bar.setValue(value)
        self._overall_bar.setValue(self._current_index * _STEPS_PER_LAYER + value)

    def finish(self) -> None:
        # accept() rather than close()/hide(): an ApplicationModal dialog holds a
        # native modal session on macOS that otherwise outlives the widget.
        self.accept()
        self.deleteLater()

    def resizeEvent(self, event) -> None:
        # A new width moves the elision point
        super().resizeEvent(event)
        self._render_layer_message()

    def _set_layer_message(self, text: str) -> None:
        self._layer_message = text
        self._layer_label.setToolTip(text)
        self._render_layer_message()

    def _render_layer_message(self) -> None:
        if self._layer_label is None:
            return
        metrics = QFontMetrics(self._layer_label.font())
        self._layer_label.setText(
            metrics.elidedText(
                self._layer_message,
                QT_TEXT_ELIDE_MODE.ElideMiddle,
                self._layer_label.width(),
            )
        )

    def _update_overall_label(self) -> None:
        if self._canceled:
            return
        self._overall_label.setText(
            i18n.tr("Uploading layer {} of {}...").format(
                min(self._current_index + 1, self._total), self._total
            )
        )

    @staticmethod
    def _pump() -> None:
        QCoreApplication.processEvents()
