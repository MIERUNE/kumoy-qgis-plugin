"""Kumoy ラスタ(COG)用の QgsRasterDataProvider。

実体は「ローカルにキャッシュした COG を gdal プロバイダで読む」だけだが、レイヤーが
Kumoy の URI（raster_id）で永続化される点に価値がある。プロジェクトを保存・再読込
すると同じ URI からプロバイダが作り直され、キャッシュが無ければ自動でダウンロード
し直す（絶対パス参照の gdal レイヤーと違い、キャッシュ削除や別マシンでも壊れない）。

描画パイプラインが要求する read 系メソッドは内部 gdal プロバイダへ素通しする。
ダウンロードのトリガと進捗 UI だけがこのクラス固有の責務。
"""

from typing import Optional

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsDataProvider,
    QgsMessageLog,
    QgsProviderRegistry,
    QgsRasterDataProvider,
    QgsRectangle,
)
from qgis.PyQt import sip
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.utils import iface

from ... import i18n
from ...pyqt_version import QT_APPLICATION_MODAL
from .. import constants, download, local_cache
from ..api.error import format_api_error


def parse_uri(uri: str) -> tuple[str, str, str]:
    """Kumoy ラスタ URI を (project_id, raster_id, raster_name) に分解する。"""
    metadata = QgsProviderRegistry.instance().providerMetadata(
        constants.RASTER_DATA_PROVIDER_KEY
    )
    parts = metadata.decodeUri(uri)
    project_id = parts.get("project_id", "")
    raster_id = parts.get("raster_id", "")
    raster_name = parts.get("raster_name", "")
    if raster_id == "" or project_id == "":
        raise ValueError("Invalid URI. 'project_id' and 'raster_id' are required.")
    return project_id, raster_id, raster_name


class KumoyRasterDataProvider(QgsRasterDataProvider):
    def __init__(
        self,
        uri="",
        providerOptions=QgsDataProvider.ProviderOptions(),
        flags=QgsDataProvider.ReadFlags(),
    ):
        super().__init__(uri)
        self._uri = uri
        self._provider_options = providerOptions
        self._flags = flags
        self._gdal: Optional[QgsRasterDataProvider] = None
        self._is_valid = False

        self.project_id, self.raster_id, self.raster_name = parse_uri(uri)

        cache_path = self._ensure_cached()
        if cache_path is None:
            return

        # ローカルの COG を gdal プロバイダで開き、以降の read はこれへ委譲する。
        self._gdal = QgsProviderRegistry.instance().createProvider(
            "gdal", cache_path, providerOptions, flags
        )
        self._is_valid = self._gdal is not None and self._gdal.isValid()

    def _ensure_cached(self) -> Optional[str]:
        """COG をローカルに用意し、そのパスを返す。失敗・中断時は None。

        キャッシュ済みならネットワークも UI も発生させない（プロバイダ clone 時に
        描画スレッドから呼ばれても安全なように）。未キャッシュ時のみ、メインスレッド
        で進捗ダイアログを出しつつダウンロードする。
        """
        if local_cache.raster.is_cached(self.raster_id):
            return local_cache.raster.get_cache_path(self.raster_id)

        progress = QProgressDialog(
            i18n.tr("Downloading: {}").format(self.raster_name),
            i18n.tr("Cancel"),
            0,
            100,
            iface.mainWindow(),
        )
        progress.setWindowTitle(i18n.tr("Raster Download"))
        progress.setWindowModality(QT_APPLICATION_MODAL)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        # 自動表示タイマー（setMinimumDuration 経由）に頼らず明示的に表示する。
        # タイマー任せだと、完了後にタイマーが発火して 100% のダイアログが
        # 再表示され、閉じられなくなることがある。
        progress.setMinimumDuration(0)
        progress.show()

        try:
            return local_cache.raster.sync_local_cache(
                self.raster_id,
                progress_callback=lambda pct: progress.setValue(int(pct)),
                is_canceled=progress.wasCanceled,
            )
        except download.DownloadCanceled:
            return None
        except Exception as e:
            error_text = format_api_error(e)
            QgsMessageLog.logMessage(
                f"Raster download failed for {self.raster_id}: {error_text}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            QMessageBox.warning(
                None,
                i18n.tr("Raster Download"),
                i18n.tr("Failed to download raster '{}': {}").format(
                    self.raster_name, error_text
                ),
            )
            return None
        finally:
            # accept() でダイアログを終了させる。macOS の ApplicationModal は
            # ネイティブのモーダルセッションを張るため、close()/hide() では
            # セッションが残ってダイアログが閉じないことがある。done() 系
            # （accept）で明示的に終了させる必要がある（vector の同期ダイアログと
            # 同じ後始末）。
            progress.accept()
            progress.deleteLater()

    @classmethod
    def providerKey(cls) -> str:
        return constants.RASTER_DATA_PROVIDER_KEY

    @classmethod
    def description(cls) -> str:
        return constants.RASTER_DATA_PROVIDER_DESCRIPTION

    @classmethod
    def createProvider(cls, uri, providerOptions, flags=QgsDataProvider.ReadFlags()):
        return KumoyRasterDataProvider(uri, providerOptions, flags)

    def name(self) -> str:
        return self.providerKey()

    def isValid(self) -> bool:
        return self._is_valid

    def clone(self):
        """描画パイプライン（QgsRasterPipe）が複製時に呼ぶ。

        ここで自分自身（Python サブクラス）を返すと、C++ がクローンを所有・破棄
        する一方で Python ラッパー（=read系のオーバーライド）が GC で失われ、
        以降の block() が C++ 基底実装（空ブロック）にフォールバックして「何も
        描画されない」、あるいは pure virtual 呼び出しで crash する。

        クローンに必要なのは「同じローカル COG を読むプロバイダ」だけなので、
        内部 gdal プロバイダ自身の clone（純 C++、所有権・仮想ディスパッチとも
        sip が正しく扱う）を返す。ダウンロード・URI 永続化はレイヤー本体が持つ
        オリジナル（このインスタンス）が担うので、クローンが gdal でも支障ない。
        """
        if self._gdal is not None:
            return self._gdal.clone()
        # 無効プロバイダ（DL 失敗/中断）。描画されないが pipe コピー時に呼ばれうる。
        cloned = KumoyRasterDataProvider(self._uri, self._provider_options, self._flags)
        sip.transferto(cloned, None)
        return cloned

    # --- 以降は内部 gdal プロバイダへの委譲（描画・identify が要求する read 系） ---

    def extent(self) -> QgsRectangle:
        if self._gdal is None:
            return QgsRectangle()
        return self._gdal.extent()

    def crs(self) -> QgsCoordinateReferenceSystem:
        if self._gdal is None:
            return QgsCoordinateReferenceSystem()
        return self._gdal.crs()

    def bandCount(self) -> int:
        return self._gdal.bandCount() if self._gdal else 1

    def dataType(self, bandNo):
        if self._gdal is None:
            return Qgis.DataType.UnknownDataType
        return self._gdal.dataType(bandNo)

    def sourceDataType(self, bandNo):
        if self._gdal is None:
            return Qgis.DataType.UnknownDataType
        return self._gdal.sourceDataType(bandNo)

    def xSize(self) -> int:
        return self._gdal.xSize() if self._gdal else 0

    def ySize(self) -> int:
        return self._gdal.ySize() if self._gdal else 0

    def block(self, bandNo, boundingBox, width, height, feedback=None):
        return self._gdal.block(bandNo, boundingBox, width, height, feedback)

    def capabilities(self):
        return (
            self._gdal.capabilities()
            if self._gdal
            else QgsRasterDataProvider.NoProviderCapabilities
        )

    def colorInterpretation(self, bandNo):
        return self._gdal.colorInterpretation(bandNo)

    def colorTable(self, bandNo):
        # パレット付きラスタの描画に必要。委譲しないと基底の空テーブルが返り、
        # PaletteIndex なバンドが正しく色付けされない。
        return self._gdal.colorTable(bandNo)

    def generateBandName(self, bandNo):
        return self._gdal.generateBandName(bandNo)

    def sourceNoDataValue(self, bandNo):
        return self._gdal.sourceNoDataValue(bandNo)

    def sourceHasNoDataValue(self, bandNo):
        return self._gdal.sourceHasNoDataValue(bandNo)

    def useSourceNoDataValue(self, bandNo):
        return self._gdal.useSourceNoDataValue(bandNo)

    def setUseSourceNoDataValue(self, bandNo, use):
        return self._gdal.setUseSourceNoDataValue(bandNo, use)

    def userNoDataValues(self, bandNo):
        return self._gdal.userNoDataValues(bandNo)

    def setUserNoDataValue(self, bandNo, noData):
        return self._gdal.setUserNoDataValue(bandNo, noData)

    def userNoDataValuesContains(self, bandNo, value):
        return self._gdal.userNoDataValuesContains(bandNo, value)

    def enableProviderResampling(self, enable):
        return self._gdal.enableProviderResampling(enable)

    def setZoomedInResamplingMethod(self, method):
        return self._gdal.setZoomedInResamplingMethod(method)

    def zoomedInResamplingMethod(self):
        return self._gdal.zoomedInResamplingMethod()

    def setZoomedOutResamplingMethod(self, method):
        return self._gdal.setZoomedOutResamplingMethod(method)

    def zoomedOutResamplingMethod(self):
        return self._gdal.zoomedOutResamplingMethod()

    def setMaxOversampling(self, factor):
        return self._gdal.setMaxOversampling(factor)

    def maxOversampling(self):
        return self._gdal.maxOversampling()

    def identify(
        self, point, format, boundingBox=QgsRectangle(), width=0, height=0, dpi=96
    ):
        return self._gdal.identify(point, format, boundingBox, width, height, dpi)

    def htmlMetadata(self) -> str:
        return self._gdal.htmlMetadata() if self._gdal else ""
