import os
from typing import Callable, Optional

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
)


def import_flatgeobuf_to_geopackage(
    flatgeobuf_path: str,
    geopackage_path: str,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> None:
    """Convert a FlatGeobuf transfer file into the editable GPKG cache format."""
    source = QgsVectorLayer(flatgeobuf_path, "flatgeobuf-transfer", "ogr")
    if not source.isValid():
        raise ValueError(f"Invalid FlatGeobuf file: {flatgeobuf_path}")
    if source.fields().indexOf("kumoy_id") < 0:
        raise ValueError("FlatGeobuf is missing the kumoy_id field")

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.layerOptions = ["FID=kumoy_id"]
    options.driverName = "GPKG"
    options.fileEncoding = "UTF-8"

    writer = QgsVectorFileWriter.create(
        geopackage_path,
        source.fields(),
        source.wkbType(),
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance().transformContext(),
        options,
    )
    if writer.hasError() != QgsVectorFileWriter.NoError:
        message = writer.errorMessage()
        del writer
        del source
        raise RuntimeError(f"Failed to create GPKG cache: {message}")

    processed = 0
    try:
        for source_feature in source.getFeatures():
            feature = QgsFeature(source.fields())
            feature.setAttributes(source_feature.attributes())
            feature.setId(int(source_feature["kumoy_id"]))
            if source_feature.hasGeometry():
                feature.setGeometry(source_feature.geometry())
            feature.setValid(True)

            if not writer.addFeature(feature):
                raise RuntimeError(
                    f"Failed to write GPKG cache feature: {writer.errorMessage()}"
                )

            processed += 1
            if progress_callback is not None:
                progress_callback(processed)
    except Exception:
        del writer
        del source
        if os.path.exists(geopackage_path):
            os.unlink(geopackage_path)
        raise

    del writer
    del source
