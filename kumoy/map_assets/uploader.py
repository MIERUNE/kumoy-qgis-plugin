"""Presigned URLへのmultipartアップロード"""

from qgis.PyQt.QtCore import QByteArray, QEventLoop, QUrl
from qgis.PyQt.QtNetwork import (
    QHttpMultiPart,
    QHttpPart,
    QNetworkAccessManager,
    QNetworkRequest,
)

from ...pyqt_version import Q_NETWORK_REQUEST_HEADER, exec_event_loop


def upload_to_presigned_url(
    server_url: str,
    fields: dict[str, str],
    filename: str,
    file_data: bytes,
    content_type: str,
) -> None:
    """Presigned URLにファイルをアップロードする。

    S3 presigned POSTの形式でmultipart/form-dataリクエストを送信する。

    Args:
        server_url: サーバーのベースURL
        fields: presigned URLのフォームフィールド
        filename: S3キー（ファイル名）
        file_data: アップロードするファイルデータ
        content_type: Content-Type

    Raises:
        Exception: アップロード失敗時
    """
    multipart = QHttpMultiPart(QHttpMultiPart.FormDataType)

    # key フィールド
    key_part = QHttpPart()
    key_part.setHeader(
        Q_NETWORK_REQUEST_HEADER.ContentDispositionHeader,
        'form-data; name="key"',
    )
    key_part.setBody(QByteArray(filename.encode("utf-8")))
    multipart.append(key_part)

    # presigned フィールド
    for field_name, field_value in fields.items():
        part = QHttpPart()
        part.setHeader(
            Q_NETWORK_REQUEST_HEADER.ContentDispositionHeader,
            f'form-data; name="{field_name}"',
        )
        part.setBody(QByteArray(field_value.encode("utf-8")))
        multipart.append(part)

    # ファイルパート（最後に追加）
    file_part = QHttpPart()
    file_part.setHeader(
        Q_NETWORK_REQUEST_HEADER.ContentDispositionHeader,
        'form-data; name="file"; filename="upload"',
    )
    file_part.setHeader(
        Q_NETWORK_REQUEST_HEADER.ContentTypeHeader,
        content_type,
    )
    file_part.setBody(QByteArray(file_data))
    multipart.append(file_part)

    # リクエスト送信
    url = f"{server_url}/user-content"
    request = QNetworkRequest(QUrl(url))

    nam = QNetworkAccessManager()
    reply = nam.post(request, multipart)
    multipart.setParent(reply)  # prevent GC

    # ブロッキング待機
    loop = QEventLoop()
    reply.finished.connect(loop.quit)
    exec_event_loop(loop)

    status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
    if status_code not in (200, 201, 204):
        error_body = bytes(reply.readAll().data()).decode("utf-8", errors="replace")
        reply.deleteLater()
        raise Exception(f"Upload failed (HTTP {status_code}): {error_body}")

    reply.deleteLater()
