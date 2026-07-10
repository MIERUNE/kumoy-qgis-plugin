"""任意ラスタを COG (Cloud Optimized GeoTIFF) に変換する。

再投影はしない。元データの破壊を避けるため、元の CRS とピクセル値・データ型を
そのまま保持する。CRS が未設定のラスタにだけ、呼び出し側が指定した CRS を
ヘッダへ割り当てる（``-a_srs`` 相当。ピクセルは触らない）。GeoTransform が
未設定のラスタには identity を割り当て、地理参照を欠いた COG が出力されるのを防ぐ。
"""

from typing import Callable, Optional

from osgeo import gdal


class CogConversionCanceled(Exception):
    """進捗コールバックが変換の中断を要求した。"""


def convert_to_cog(
    src_path: str,
    dst_path: str,
    assign_crs_wkt: Optional[str] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
    is_canceled: Optional[Callable[[], bool]] = None,
) -> None:
    """``src_path`` のラスタを COG として ``dst_path`` に書き出す。

    Args:
        assign_crs_wkt: 元ラスタの CRS が未設定のときに割り当てる CRS（WKT）。
            None の場合は元の CRS をそのまま保持する。
        progress_callback: 進捗(0-100)を受け取る。
        is_canceled: True を返すと変換を中断し ``CogConversionCanceled`` を送出。

    Raises:
        CogConversionCanceled: ``is_canceled`` が True を返した場合。
        Exception: GDAL が変換に失敗した場合。
    """
    gdal.UseExceptions()

    canceled = {"value": False}

    def _gdal_callback(complete: float, _message: str, _data: object) -> int:
        # 戻り値 0 で GDAL は処理を中断する。
        if is_canceled is not None and is_canceled():
            canceled["value"] = True
            return 0
        if progress_callback is not None:
            progress_callback(complete * 100.0)
        return 1

    options = gdal.TranslateOptions(
        options=["-approx_stats"],
        format="COG",
        # COG ドライバ既定のタイル化に DEFLATE 圧縮を足す。データ型は原典のまま。
        creationOptions=["COMPRESS=DEFLATE"],
        # outputSRS は -a_srs 相当（割り当てのみ、再投影しない）。
        outputSRS=assign_crs_wkt if assign_crs_wkt else None,
        callback=_gdal_callback,
    )

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
