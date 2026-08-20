import pytest
from qgis.PyQt.QtCore import QByteArray
from qgis.PyQt.QtGui import QImage

from plugin_dir.pyqt_version import Q_NETWORK_REPLY_ERROR


class _FakeReply:
    """QNetworkReply の最小スタブ。error() は Qt6 と同じ enum 値を返す"""

    def __init__(self, error, data=b""):
        self._error = error
        self._data = QByteArray(data)

    def error(self):
        return self._error

    def readAll(self):
        return self._data

    def deleteLater(self):
        pass


def _png_bytes() -> bytes:
    from qgis.PyQt.QtCore import QBuffer

    from plugin_dir.pyqt_version import Q_BUFFER_OPEN_MODE

    img = QImage(4, 4, QImage.Format.Format_ARGB32)
    img.fill(0xFF00FF00)
    buf = QBuffer()
    buf.open(Q_BUFFER_OPEN_MODE.WriteOnly)
    assert img.save(buf, "PNG")
    return bytes(buf.data())


@pytest.mark.usefixtures("qgis_plugin_path")
class TestRemoteImageLabelOnFinished:
    def _label(self):
        from plugin_dir.ui.remote_image_label import RemoteImageLabel

        return RemoteImageLabel(size=(32, 32))

    def test_successful_reply_is_not_treated_as_error(self):
        # Qt6 では NoError が truthy なので、真偽値判定だと常に失敗扱いになる
        label = self._label()
        label._reply = _FakeReply(Q_NETWORK_REPLY_ERROR.NoError, _png_bytes())
        label._on_finished()
        assert label._img is not None
        assert not label._img.isNull()

    def test_failed_reply_keeps_placeholder(self):
        label = self._label()
        label._reply = _FakeReply(Q_NETWORK_REPLY_ERROR.HostNotFoundError)
        label._on_finished()
        assert label._img is None

    def test_undecodable_body_keeps_placeholder(self):
        label = self._label()
        label._reply = _FakeReply(Q_NETWORK_REPLY_ERROR.NoError, b"not an image")
        label._on_finished()
        assert label._img is None
