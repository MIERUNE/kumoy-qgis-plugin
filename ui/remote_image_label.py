import os

from qgis.PyQt.QtCore import QBuffer, QByteArray, Qt, QUrl, QRect
from qgis.PyQt.QtGui import QImage, QImageReader, QPixmap, QRegion
from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import QLabel

from ..imgs import PIN_ICON

# icon
placeholder_pixmap = PIN_ICON.pixmap(24, 24)


class RemoteImageLabel(QLabel):
    def __init__(self, parent=None, size=(150, 100), circular=False):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(*size)
        self._img: QImage | None = None
        self._circular = circular
        self.nam = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None

        # Apply circular style if requested
        if self._circular:
            self._setup_circular_style()

    def _setup_circular_style(self):
        """Set up style for circular avatar"""
        radius = min(self.width(), self.height()) // 2
        self.setStyleSheet(
            f"""
            RemoteImageLabel {{
                background-color: #9c27b0;
                color: white;
                border-radius: {radius}px;
                font-weight: bold;
                font-size: 14px;
                border: none;
            }}
        """
        )

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
        # Create circular mask if needed
        if self._circular:
            self._create_circular_mask()

    def _create_circular_mask(self):
        """Create circular mask for avatar"""
        # Create circular region
        size = min(self.width(), self.height())
        x = (self.width() - size) // 2
        y = (self.height() - size) // 2

        # Create elliptical mask (which will be circular for a square)
        region = QRegion(QRect(x, y, size, size), QRegion.Ellipse)
        self.setMask(region)

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
