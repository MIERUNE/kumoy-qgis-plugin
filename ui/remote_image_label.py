from qgis.PyQt.QtCore import QBuffer, QByteArray, Qt, QUrl
from qgis.PyQt.QtGui import QImage, QImageReader, QPixmap
from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import QLabel

from ..imgs import PIN_ICON

# icon
placeholder_pixmap = PIN_ICON.pixmap(24, 24)


class RemoteImageLabel(QLabel):
    def __init__(self, parent=None, size=(150, 100)):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(*size)
        self._img: QImage | None = None
        self.nam = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None

    def load(self, url: str):
        self.setPixmap(placeholder_pixmap)
        self._reply = self.nam.get(QNetworkRequest(QUrl(url)))
        self._reply.finished.connect(self._on_finished)

    def _on_finished(self):
        if self._reply.error():
            self.setPixmap(placeholder_pixmap)
            self._reply.deleteLater()
            return
        data: QByteArray = self._reply.readAll()
        self._reply.deleteLater()
        buf = QBuffer()
        buf.setData(data)
        buf.open(QBuffer.ReadOnly)
        reader = QImageReader(buf)
        reader.setAutoTransform(True)
        img = reader.read()
        if img.isNull():
            self.setPixmap(placeholder_pixmap)
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
