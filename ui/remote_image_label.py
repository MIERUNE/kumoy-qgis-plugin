import os

from PyQt5.QtCore import QBuffer, QByteArray, Qt, QUrl
from PyQt5.QtGui import QImageReader, QPixmap
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt5.QtWidgets import QLabel


class RemoteImageLabel(QLabel):
    def __init__(self, parent=None, size=(150, 100)):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(*size)
        self._img = None
        self.nam = QNetworkAccessManager(self)

    def load(self, url: str):
        self.setText("Loading…")
        r = self.nam.get(QNetworkRequest(QUrl(url)))
        r.finished.connect(lambda: self._on_finished(r))

    def _on_finished(self, r: QNetworkReply):
        if r.error():
            self.setText(f"Error: {r.errorString()}")
            r.deleteLater()
            return
        data: QByteArray = r.readAll()
        r.deleteLater()
        buf = QBuffer()
        buf.setData(data)
        buf.open(QBuffer.ReadOnly)
        reader = QImageReader(buf)
        reader.setAutoTransform(True)
        img = reader.read()
        if img.isNull():
            self.setText("Decode failed")
            return
        self._img = img
        self._apply_cover()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._img is not None:
            self._apply_cover()

    def _apply_cover(self):
        dpr = self.devicePixelRatioF()
        target_w = max(1, int(self.width() * dpr))
        target_h = max(1, int(self.height() * dpr))
        # KeepAspectRatioByExpanding で「全面を埋める」サイズへ拡大
        scaled = self._img.scaled(
            target_w, target_h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        px = QPixmap.fromImage(scaled)
        px.setDevicePixelRatio(dpr)
        # setScaledContents(False) のまま、中央アライメントでラベルが余分を切り落とす
        self.setPixmap(px)
