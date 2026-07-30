"""レイヤーアップロードの進捗表示ダイアログ。

Map保存フローは選択されたレイヤーを1つずつアップロードする。以前はレイヤーごとに
``QProgressDialog`` を開いていたため、100レイヤーあると「今何個目か」が分からず、
中断したいときに100回キャンセルを押す必要があった（Issue #538）。

ここでは全体進捗（何個目 / 全体）と現在のレイヤーの進捗を1つのダイアログにまとめ、
キャンセル1回で残り全部を止められるようにする。単体アップロード（レイヤーパネルの
コンテキストメニュー）でも同じダイアログを total=1 で使う。
"""

from qgis.PyQt.QtCore import QCoreApplication, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ... import i18n
from ...pyqt_version import QT_APPLICATION_MODAL

# 全体進捗バーはレイヤーごとに 100 刻みで進める（レイヤー内の進捗も反映するため）
_STEPS_PER_LAYER = 100


class UploadProgressDialog(QDialog):
    """連続アップロードの全体進捗を見せ、1回のキャンセルで全体を止めるダイアログ。

    キャンセルは即座にウィンドウを閉じるのではなく ``canceled`` シグナルを出して
    ``is_canceled()`` を True にするだけ。実行中のアップロードの中断（feedback.cancel）
    と、残りレイヤーのスキップは呼び出し側が判断する。
    """

    canceled = pyqtSignal()

    def __init__(self, total: int, parent=None) -> None:
        super().__init__(parent)
        self._total = max(total, 1)
        self._current_index = 0
        self._canceled = False

        self.setWindowTitle(i18n.tr("Kumoy Upload"))
        self.setWindowModality(QT_APPLICATION_MODAL)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 全体進捗（複数レイヤーのときだけ意味があるので単体では隠す）
        self._overall_label = QLabel()
        layout.addWidget(self._overall_label)

        self._overall_bar = QProgressBar()
        self._overall_bar.setMaximum(self._total * _STEPS_PER_LAYER)
        self._overall_bar.setValue(0)
        layout.addWidget(self._overall_bar)

        if self._total == 1:
            self._overall_label.hide()
            self._overall_bar.hide()

        # 現在アップロード中のレイヤー
        self._layer_label = QLabel()
        self._layer_label.setWordWrap(True)
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
        """キャンセルを受け付ける。2回目以降は無視する。"""
        if self._canceled:
            return
        self._canceled = True
        self._cancel_button.setEnabled(False)
        self._cancel_button.setText(i18n.tr("Cancelling..."))
        self._overall_label.setText(i18n.tr("Cancelling upload..."))
        self.canceled.emit()
        self._pump()

    def reject(self) -> None:
        """Esc・タイトルバーの×をキャンセル要求として扱い、ダイアログは閉じない。

        アップロード中に閉じてしまうと進捗の行き先が無くなるので、実際に閉じるのは
        呼び出し側が ``finish()`` を呼んだときだけ。
        """
        self.request_cancel()

    def begin_layer(self, name: str, index: int) -> None:
        """``index`` 番目（0起点）のレイヤー ``name`` のアップロード開始を表示する。"""
        self._current_index = index
        self._layer_label.setText(i18n.tr("Uploading layer '{}'...").format(name))
        self._layer_bar.setValue(0)
        self._overall_bar.setValue(index * _STEPS_PER_LAYER)
        self._update_overall_label()

        # Issue #356: Windowsでダイアログが描画されないことがあるため明示的に描かせる
        self.repaint()
        self._pump()
        self.repaint()
        self._pump()

    def set_layer_progress(self, percent: float) -> None:
        """現在のレイヤーの進捗（0-100）を反映し、全体進捗も合わせて進める。"""
        value = min(max(int(percent), 0), _STEPS_PER_LAYER)
        self._layer_bar.setValue(value)
        self._overall_bar.setValue(self._current_index * _STEPS_PER_LAYER + value)

    def finish(self) -> None:
        """ダイアログを閉じて破棄する。

        macOS の ApplicationModal はネイティブのモーダルセッションを張るため、
        close()/hide() だとセッションが残って閉じないことがある。accept() で終わらせる。
        """
        self.accept()
        self.deleteLater()

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
