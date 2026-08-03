"""Vector-specific half of the local-to-Kumoy conversion driven by ``convert.py``.

Runs ``kumoy:uploadvector`` synchronously on the main thread; the raster side
needs a worker thread instead (see ``_upload_raster._run_upload``).
"""

from typing import Optional

from qgis.core import (
    Qgis,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.utils import iface

import processing

from ... import i18n
from ...kumoy import api, constants
from .configure import configure_kumoy_layer
from .upload_progress import UploadProgressDialog


def upload(
    layer: QgsVectorLayer,
    project_index: int,
    vector_name: str,
    progress: UploadProgressDialog,
) -> Optional[QgsVectorLayer]:
    """Upload ``layer`` and return the matching Kumoy layer, or None on cancel."""
    feedback = QgsProcessingFeedback()

    # processing.run blocks the main thread, so pump events on every update to let
    # the dialog repaint and the cancel button be clicked
    def update_progress(value: float) -> None:
        progress.set_layer_progress(value)
        QCoreApplication.processEvents()

    feedback.progressChanged.connect(update_progress)
    progress.canceled.connect(feedback.cancel)
    if progress.is_canceled():
        # Cancel pressed while a previous layer was running must not be lost
        feedback.cancel()

    try:
        result = processing.run(
            "kumoy:uploadvector",
            {
                "INPUT": layer,
                "PROJECT": project_index,
                "VECTOR_NAME": vector_name,
                "SELECTED_FIELDS": [],
            },
            context=QgsProcessingContext(),
            feedback=feedback,
        )

        if feedback.isCanceled():
            iface.messageBar().pushMessage(
                constants.PLUGIN_NAME,
                i18n.tr("Upload cancelled"),
                level=Qgis.Warning,
                duration=3,
            )
            return None

        if not result or "VECTOR_ID" not in result:
            raise Exception(i18n.tr("Upload failed - unable to get vector id"))
    finally:
        # Drop only this feedback's connection: the dialog outlives it
        progress.canceled.disconnect(feedback.cancel)

    return _build_kumoy_layer(result["VECTOR_ID"])


def _build_kumoy_layer(vector_id: str) -> QgsVectorLayer:
    vector = api.vector.get_vector(vector_id)
    vector_uri = (
        f"project_id={vector.projectId};"
        f"vector_id={vector.id};"
        f"vector_name={vector.name};"
        f"vector_type={vector.type};"
    )

    kumoy_layer = QgsVectorLayer(vector_uri, vector.name, constants.DATA_PROVIDER_KEY)
    if not kumoy_layer.isValid():
        error_msg = (
            kumoy_layer.error().message() if kumoy_layer.error() else "Unknown error"
        )
        raise Exception(i18n.tr("Failed to create Kumoy layer: {}").format(error_msg))

    configure_kumoy_layer(kumoy_layer, vector)

    return kumoy_layer
