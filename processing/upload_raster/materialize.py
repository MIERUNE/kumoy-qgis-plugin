"""QGIS 仮想ラスタ(virtualraster)を GDAL が読める GeoTIFF へ実体化する。

仮想ラスタ（ラスタ計算機の仮想出力など）はディスク上のファイルパスを持たず
``gdal.Open`` できないため、``QgsRasterInterface`` 経由で一時 GeoTIFF に描き出して
から COG 変換する。COG ドライバは ``CreateCopy`` 専用で ``QgsRasterFileWriter``
（``Create`` ベース）では直接書けないため、「GeoTIFF に実体化 → GDAL で COG 化」
の二段になる。

WMS/WCS などオンライン系や他プロバイダは対応せず、明示的に拒否する（アップロード
用途では原ピクセルを持つローカル由来のラスタだけを対象にする方針）。
"""

from typing import Callable, Optional

from qgis.core import (
    QgsCoordinateTransformContext,
    QgsRasterBlockFeedback,
    QgsRasterFileWriter,
    QgsRasterLayer,
    QgsRasterPipe,
)

from ... import i18n


class RasterMaterializeCanceled(Exception):
    """ユーザーが実体化を中断した。"""


def materialize_to_geotiff(
    layer: QgsRasterLayer,
    dst_path: str,
    progress_callback: Optional[Callable[[float], None]] = None,
    is_canceled: Optional[Callable[[], bool]] = None,
) -> None:
    """``layer`` の画素を GeoTIFF として ``dst_path`` へ書き出す。

    呼び出し規約は ``convert_to_cog`` と同じ: 進捗は 0-100、中断は ``is_canceled``
    のポーリング、``dst_path`` の用意と削除は呼び出し側の責務。

    Raises:
        RasterMaterializeCanceled: ``is_canceled`` が True を返した場合。
        Exception: 非対応プロバイダ、または QGIS が書き出しに失敗した場合。
    """
    if layer.providerType() != "virtualraster":
        raise Exception(
            i18n.tr(
                "This raster cannot be uploaded because it uses an unsupported "
                "source type ({}). Only file-based rasters and QGIS virtual "
                "rasters are supported."
            ).format(layer.providerType())
        )

    provider = layer.dataProvider()
    if provider is None or not provider.isValid():
        raise Exception(i18n.tr("The input raster layer has no readable data source."))

    if is_canceled is not None and is_canceled():
        raise RasterMaterializeCanceled()

    # provider を clone してパイプへ委譲する（writeRaster が所有権を取る）。
    clone = provider.clone()
    pipe = QgsRasterPipe()
    if not pipe.set(clone):
        raise Exception(i18n.tr("Failed to prepare the raster for rendering."))

    # writeRaster の進捗・中断はシグナル/QgsFeedback ベースなので、進捗通知の
    # たびに is_canceled をポーリングして cancel へ変換する。
    block_feedback = QgsRasterBlockFeedback()

    def _on_progress(p: float) -> None:
        if is_canceled is not None and is_canceled():
            block_feedback.cancel()
        if progress_callback is not None:
            progress_callback(p)

    block_feedback.progressChanged.connect(_on_progress)

    writer = QgsRasterFileWriter(dst_path)
    writer.setOutputFormat("GTiff")
    # 再投影しないので変換コンテキストは空で足りる（出力 CRS = 元の CRS）。
    err = writer.writeRaster(
        pipe,
        clone.xSize(),
        clone.ySize(),
        clone.extent(),
        clone.crs(),
        QgsCoordinateTransformContext(),
        block_feedback,
    )

    if block_feedback.isCanceled():
        raise RasterMaterializeCanceled()
    if err != QgsRasterFileWriter.NoError:
        raise Exception(
            i18n.tr("QGIS failed to render the raster to a file (error {}).").format(
                err
            )
        )
