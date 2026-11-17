"""Convert any GDAL-readable raster to a COG (Cloud Optimized GeoTIFF).

No reprojection and no change of pixel values or data type: the upload must
not alter the user's data. A CRS given by the caller is only assigned
(`-a_srs`).

GDAL's exception mode is process-global and other plugins flip it, so this
code works in both modes instead of calling gdal.UseExceptions().
"""

from typing import Callable, Optional, Union

from osgeo import gdal

from .... import i18n
from ....kumoy.tasks import Canceled


class CogConversionCanceled(Canceled):
    """The `is_canceled` callback asked to stop."""


SOURCE_UNREADABLE: object = object()
"""read_source_crs_wkt(): the file could not be opened, so the CRS is unknown."""


def _open(path: str):
    try:
        return gdal.Open(path)
    except RuntimeError:
        return None


def read_source_crs_wkt(src_path: str) -> Union[Optional[str], object]:
    """The CRS embedded in the file as WKT; None when it has none.

    A CRS set on the layer in QGIS is not in the file, which is why callers
    compare the two. Unopenable files return SOURCE_UNREADABLE and leave the
    error report to convert_to_cog(), which opens the same path.
    """
    ds = _open(src_path)
    if ds is None:
        return SOURCE_UNREADABLE
    srs = ds.GetSpatialRef()
    return srs.ExportToWkt() if srs is not None else None


def _cog_supports_band_interleave() -> bool:
    """Whether the COG driver has the INTERLEAVE creation option (GDAL 3.11+).

    Checked as a capability: the GDAL bundled with one QGIS version varies
    (3.10 to 3.12 for QGIS 3.44).
    """
    options = gdal.GetDriverByName("COG").GetMetadataItem("DMD_CREATIONOPTIONLIST")
    return "INTERLEAVE" in (options or "")


def convert_to_cog(
    src_path: str,
    dst_path: str,
    assign_crs_wkt: Optional[str] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
    is_canceled: Optional[Callable[[], bool]] = None,
) -> None:
    """Write `src_path` as a COG to `dst_path` (any thread).

    `assign_crs_wkt` replaces the CRS without reprojecting; None keeps the
    source's. Raises CogConversionCanceled, or Exception when GDAL fails.
    `dst_path` is the caller's to delete on failure.
    """
    src_ds = _open(src_path)
    if src_ds is None:
        raise Exception(f"GDAL failed to open raster: {src_path}")

    creation_options = ["COMPRESS=DEFLATE", "NUM_THREADS=ALL_CPUS"]
    # No BIGTIFF: a COG over 4 GiB fails to write, which doubles as the 4 GB
    # upload limit; the caller checks the size below that by bytes.

    # BAND interleave keeps one band's tiles together so reading a single band
    # decompresses only that band. COGs are immutable, so rather than upload a
    # slow PIXEL-interleaved multi-band COG, refuse on GDAL without the option.
    # Single-band COGs are the same either way.
    if _cog_supports_band_interleave():
        creation_options.append("INTERLEAVE=BAND")
    elif src_ds.RasterCount > 1:
        band_count, src_ds = src_ds.RasterCount, None  # close (see below)
        raise Exception(
            i18n.tr(
                "This raster has {} bands, but your GDAL version is too old to create "
                "a multi-band Cloud Optimized GeoTIFF for upload (GDAL 3.11 or newer is "
                "required). Please update QGIS/GDAL and try again."
            ).format(band_count)
        )

    # Without a geotransform the COG lacks georeferencing tags and the gdal
    # provider cannot place it. Assign a pixel-space one (north up) to the
    # output; setting it on the source would write a .aux.xml next to the
    # user's file.
    output_bounds = None
    if src_ds.GetGeoTransform(can_return_null=True) is None:
        output_bounds = [0, 0, src_ds.RasterXSize, -src_ds.RasterYSize]

    canceled = []

    def on_progress(complete: float, _message, _data) -> int:
        if is_canceled is not None and is_canceled():
            canceled.append(True)
            return 0  # tells GDAL to stop
        if progress_callback is not None:
            progress_callback(complete * 100.0)
        return 1

    options = gdal.TranslateOptions(
        options=["-approx_stats"],
        format="COG",
        creationOptions=creation_options,
        outputSRS=assign_crs_wkt or None,
        outputBounds=output_bounds,
        callback=on_progress,
    )
    try:
        written = gdal.Translate(dst_path, src_ds, options=options) is not None
        error = gdal.GetLastErrorMsg()
    except RuntimeError as e:
        written, error = False, str(e)
    # Close both files before raising: a traceback kept alive (Processing,
    # tests) would hold them open, and Windows cannot delete open temp files
    src_ds = None
    if canceled:
        raise CogConversionCanceled()
    if not written:
        raise Exception(f"GDAL failed to convert raster to COG: {error}")
