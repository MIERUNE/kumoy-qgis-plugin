"""QGIS の External Storage として Kumoy の添付を扱う。

QGIS 標準の Attachment（External Resource）ウィジェットは「属性値 = 外部ストレージ
上の URL」を前提にしており、その解決を ``QgsExternalStorage`` に委ねる。ここに
"kumoy" ストレージを実装して登録することで、ウィジェット標準の UI のまま

- ファイル選択 → ``doStore`` で API 経由アップロード → 戻り値が属性値になる
- 属性値の表示 → ``doFetch`` でローカルキャッシュへ解決 → 標準の画像プレビュー

が動く。「変な再発明」を避けつつ S3 を QGIS へ直接公開しないための要（かなめ）。

``doStore`` に渡される URL は、ウィジェット設定の ``StorageUrl`` 式が地物ごとに
評価された結果。``kumoy://{vectorId}/{vectorColumnId}/{kumoyId}`` の形にしておく
ことで、どの地物のどのカラムへの添付かをここで復元できる。

UI は持たない（``kumoy/`` 配下のドメイン層）。失敗は ``reportError`` でウィジェット
側へ伝え、ウィジェットがユーザーへ表示する。
"""

import re
from typing import Optional, Tuple

from qgis.core import (
    Qgis,
    QgsExternalStorage,
    QgsExternalStorageFetchedContent,
    QgsExternalStorageStoredContent,
)

from . import attachment as attachment_domain
from . import local_cache

STORAGE_TYPE = "kumoy"

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_STORAGE_URL_PATTERN = re.compile(rf"^kumoy://({_UUID})/({_UUID})/(\d+)$")


def build_storage_url_expression(vector_id: str, vector_column_id: str) -> str:
    """ウィジェット設定の ``StorageUrl`` に入れる QGIS 式を組み立てる。

    ``StorageUrl`` は地物のコンテキストで評価される式なので、kumoy_id は式のまま
    残して評価時に埋めさせる。これで ``doStore`` が対象地物を特定できる。
    """
    return f"'kumoy://{vector_id}/{vector_column_id}/' || \"kumoy_id\""


def parse_storage_url(url: str) -> Optional[Tuple[str, str, int]]:
    """``kumoy://{vectorId}/{vectorColumnId}/{kumoyId}`` を分解する。"""
    match = _STORAGE_URL_PATTERN.match(url or "")
    if match is None:
        return None
    return match.group(1), match.group(2), int(match.group(3))


def parse_fetch_url(url: str) -> Optional[Tuple[str, str]]:
    """``doFetch`` に渡される URL を ``(vector_id, 属性値)`` に分解する。

    属性値だけでは vector_id が分からないため、ウィジェット設定で
    ``DefaultRoot = vector_id`` かつ ``RelativeStorage = RelativeDefaultPath`` に
    しておき、``{vectorId}/{属性値}`` の形で渡ってくることを前提にする。
    """
    parts = (url or "").split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


class _StoredContent(QgsExternalStorageStoredContent):
    """1 ファイル分のアップロード。``store()`` で実行し ``url()`` に属性値を返す。"""

    def __init__(self, file_path: str, storage_url: str):
        super().__init__()
        self._file_path = file_path
        self._storage_url = storage_url
        self._value = ""
        self._canceled = False

    def store(self) -> None:
        target = parse_storage_url(self._storage_url)
        if target is None:
            # 新規地物では kumoy_id が未採番なので式が解決できない。
            # 添付は「地物を作ってから付ける」フローに限定されている（サーバ側も同様）。
            self.reportError(
                "Cannot attach a file before the feature is saved. "
                "Save the feature first, then attach."
            )
            self.setStatus(Qgis.ContentStatus.Failed)
            self.errorOccurred.emit(self.errorString())
            return

        vector_id, vector_column_id, kumoy_id = target
        self.setStatus(Qgis.ContentStatus.Running)
        try:
            self._value = attachment_domain.upload(
                vector_id=vector_id,
                kumoy_id=kumoy_id,
                vector_column_id=vector_column_id,
                file_path=self._file_path,
                progress_callback=lambda percent: self.progressChanged.emit(percent),
                is_canceled=lambda: self._canceled,
            )
        except attachment_domain.UnsupportedAttachmentError as e:
            self._fail(f"Unsupported file type: .{e}")
            return
        except attachment_domain.AttachmentTooLargeError:
            self._fail(
                "The file exceeds the maximum attachment size "
                f"({attachment_domain.MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB)"
            )
            return
        except Exception as e:
            self._fail(str(e))
            return

        self.setStatus(Qgis.ContentStatus.Finished)
        self.stored.emit()

    def _fail(self, message: str) -> None:
        self.reportError(message)
        self.setStatus(Qgis.ContentStatus.Failed)
        self.errorOccurred.emit(self.errorString())

    def cancel(self) -> None:
        self._canceled = True
        self.setStatus(Qgis.ContentStatus.Canceled)
        self.canceled.emit()

    def url(self) -> str:
        return self._value


class _FetchedContent(QgsExternalStorageFetchedContent):
    """1 ファイル分の解決。``fetch()`` でキャッシュへ落とし ``filePath()`` を返す。"""

    def __init__(self, url: str):
        super().__init__()
        self._url = url
        self._path = ""
        self._canceled = False

    def fetch(self) -> None:
        parsed = parse_fetch_url(self._url)
        if parsed is None:
            self._fail(f"Invalid attachment reference: {self._url}")
            return
        vector_id, value = parsed

        # キャッシュ済みならネットワークに触らず即完了させる（フォーム表示のたびに
        # 呼ばれるため、ここが安いことが重要）。
        if local_cache.attachment.is_cached(vector_id, value):
            self._path = local_cache.attachment.get_cache_path(vector_id, value)
            self.setStatus(Qgis.ContentStatus.Finished)
            self.fetched.emit()
            return

        self.setStatus(Qgis.ContentStatus.Running)
        try:
            self._path = local_cache.attachment.sync_local_cache(
                vector_id,
                value,
                progress_callback=lambda percent: self.progressChanged.emit(percent),
                is_canceled=lambda: self._canceled,
            )
        except Exception as e:
            self._fail(str(e))
            return

        self.setStatus(Qgis.ContentStatus.Finished)
        self.fetched.emit()

    def _fail(self, message: str) -> None:
        self.reportError(message)
        self.setStatus(Qgis.ContentStatus.Failed)
        self.errorOccurred.emit(self.errorString())

    def cancel(self) -> None:
        self._canceled = True
        self.setStatus(Qgis.ContentStatus.Canceled)
        self.canceled.emit()

    def filePath(self) -> str:
        return self._path


class KumoyExternalStorage(QgsExternalStorage):
    def type(self) -> str:
        return STORAGE_TYPE

    def displayName(self) -> str:
        return "Kumoy"

    def doStore(
        self, filePath: str, url: str, authCfg: str = ""
    ) -> QgsExternalStorageStoredContent:
        return _StoredContent(filePath, url)

    def doFetch(self, url: str, authCfg: str = "") -> QgsExternalStorageFetchedContent:
        return _FetchedContent(url)


# QGIS 側（C++）はレジストリに登録したストレージの所有権を取るが、Python 側で
# 参照を失うと GC 対象になり得るのでモジュールに保持する。
_storage: Optional[KumoyExternalStorage] = None


def register() -> None:
    """ "kumoy" ストレージを登録する（多重登録はしない）。"""
    from qgis.core import QgsApplication

    global _storage
    registry = QgsApplication.externalStorageRegistry()
    if registry.externalStorageFromType(STORAGE_TYPE) is not None:
        return
    _storage = KumoyExternalStorage()
    registry.registerExternalStorage(_storage)


def unregister() -> None:
    """ "kumoy" ストレージの登録を解除する。"""
    from qgis.core import QgsApplication

    global _storage
    if _storage is None:
        return
    QgsApplication.externalStorageRegistry().unregisterExternalStorage(_storage)
    _storage = None
