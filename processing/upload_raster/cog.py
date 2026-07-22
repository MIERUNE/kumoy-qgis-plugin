"""任意ラスタを COG (Cloud Optimized GeoTIFF) に変換する。

再投影はしない。元データの破壊を避けるため、ピクセル値・データ型はそのまま
保持する。呼び出し側が CRS を指定した場合はそれをヘッダへ割り当てる
（``-a_srs`` 相当。既存の CRS も上書きされるが、ピクセルは触らない）。
GeoTransform が未設定のラスタには identity を割り当て、地理参照を欠いた
COG が出力されるのを防ぐ。
"""

from typing import Callable, Optional, Union

from osgeo import gdal

from ... import i18n


class CogConversionCanceled(Exception):
    """進捗コールバックが変換の中断を要求した。"""


SOURCE_UNREADABLE: object = object()
"""``read_source_crs_wkt`` の返り値: ソースが開けず CRS を判定できなかった。"""


def read_source_crs_wkt(src_path: str) -> Union[Optional[str], object]:
    """``src_path`` のラスタファイルに埋め込まれた CRS を WKT で返す。

    CRS が無ければ None。QGIS 上で手動設定したレイヤ CRS はファイルには
    存在しないため、``layer.crs()`` ではなく GDAL が実際に読む CRS を見る。
    開けないファイルは ``SOURCE_UNREADABLE`` を返して判定を保留し、
    エラー報告は同じパスを開く ``convert_to_cog`` に任せる。
    """
    gdal.UseExceptions()
    try:
        ds = gdal.Open(src_path)
    except Exception:
        return SOURCE_UNREADABLE
    if ds is None:
        return SOURCE_UNREADABLE
    try:
        srs = ds.GetSpatialRef()
        return srs.ExportToWkt() if srs is not None else None
    finally:
        ds.Close()


def _cog_supports_band_interleave() -> bool:
    """COG ドライバが INTERLEAVE 作成オプション（=BAND 格納）に対応するか。

    GDAL のバージョン番号ではなくドライバの能力を直接見る。COG の INTERLEAVE
    作成オプションは GDAL 3.11 で追加されたが、実環境の GDAL は QGIS のバージョンと
    無関係にばらつく（同じ QGIS 3.44 でも 3.10〜3.12）ため、能力検出が唯一堅牢。
    """
    driver = gdal.GetDriverByName("COG")
    option_list = driver.GetMetadataItem("DMD_CREATIONOPTIONLIST") or ""
    return "INTERLEAVE" in option_list


def convert_to_cog(
    src_path: str,
    dst_path: str,
    assign_crs_wkt: Optional[str] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
    is_canceled: Optional[Callable[[], bool]] = None,
) -> None:
    """``src_path`` のラスタを COG として ``dst_path`` に書き出す。

    Args:
        assign_crs_wkt: 出力へ割り当てる CRS（WKT）。元ラスタに CRS があっても
            上書きする（``-a_srs`` 相当、再投影はしない）。None の場合は元の
            CRS をそのまま保持する。
        progress_callback: 進捗(0-100)を受け取る。
        is_canceled: True を返すと変換を中断し ``CogConversionCanceled`` を送出。

    Raises:
        CogConversionCanceled: ``is_canceled`` が True を返した場合。
        Exception: GDAL が変換に失敗した場合。
    """
    gdal.UseExceptions()
    gdal.SetConfigOption("GDAL_CACHEMAX", "1024MB")

    canceled = {"value": False}

    def _gdal_callback(complete: float, _message: str, _data: object) -> int:
        # 戻り値 0 で GDAL は処理を中断する。
        if is_canceled is not None and is_canceled():
            canceled["value"] = True
            return 0
        if progress_callback is not None:
            progress_callback(complete * 100.0)
        return 1

    src_ds = gdal.Open(src_path)
    if src_ds is None:
        raise Exception(f"GDAL failed to open raster: {src_path}")

    # 元データに GeoTransform が無いと COG ドライバが地理参照タグを欠いた出力を
    # 作り、下流の gdal ラッパー(kumoyraster)で扱えなくなる。位置情報が無くても
    # 変換・表示を通すため、恣意的な identity を割り当てる（画素は触らない）。
    # can_return_null=True にしないと未設定でも既定 (0,1,0,0,0,1) が返り判定できない。
    if src_ds.GetGeoTransform(can_return_null=True) is None:
        # 北上画像になるよう y 方向は -1。原点・スケールは便宜上のピクセル空間。
        src_ds.SetGeoTransform([0.0, 1.0, 0.0, 0.0, 0.0, -1.0])

    # COG ドライバ既定のタイル化に DEFLATE 圧縮を足す。データ型は原典のまま。
    # NUM_THREADS=ALL_CPUS でタイル圧縮とオーバービュー生成を全コアに並列化する。
    # BIGTIFF は付けない。4GiB を超える出力は classic TIFF に収まらず書き込みが
    # 失敗するが、それがそのままアップロード上限（4GB, MAX_RASTER_UPLOAD_BYTES）
    # の物理的な天井として働く。上限手前の超過は呼び出し側がバイト数で弾く。
    creation_options = ["COMPRESS=DEFLATE", "NUM_THREADS=ALL_CPUS"]

    # INTERLEAVE=BAND: バンドごとに連続配置し、単一バンドの読み出し（DEFLATE 展開）を
    # 局所化する。このオプションは GDAL 3.11+ の COG ドライバでしか使えない。非対応の
    # GDAL では多バンドが PIXEL 格納になり単一バンド読み出しが遅くなる。COG は immutable
    # で後から作り直せないため、多バンドはこの能力の無い GDAL では拒否する。単バンドは
    # PIXEL / BAND が同義で無害なので、古い GDAL でもそのまま通す。
    if _cog_supports_band_interleave():
        creation_options.append("INTERLEAVE=BAND")
    elif src_ds.RasterCount > 1:
        raise Exception(
            i18n.tr(
                "This raster has {} bands, but your GDAL version is too old to create "
                "a multi-band Cloud Optimized GeoTIFF for upload (GDAL 3.11 or newer is "
                "required). Please update QGIS/GDAL and try again."
            ).format(src_ds.RasterCount)
        )

    options = gdal.TranslateOptions(
        options=["-approx_stats"],
        format="COG",
        creationOptions=creation_options,
        # outputSRS は -a_srs 相当（割り当てのみ、再投影しない）。
        outputSRS=assign_crs_wkt if assign_crs_wkt else None,
        callback=_gdal_callback,
    )

    # GDAL は中断時に「例外を送出」または「None を返す」のどちらにもなり得るため、
    # canceled フラグを正にして両方の経路で CogConversionCanceled に正規化する。
    try:
        result = gdal.Translate(dst_path, src_ds, options=options)
    except Exception:
        if canceled["value"]:
            raise CogConversionCanceled()
        raise

    if canceled["value"]:
        raise CogConversionCanceled()
    if result is None:
        raise Exception("GDAL failed to convert raster to COG")
