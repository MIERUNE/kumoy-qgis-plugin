"""Edit form setup for Kumoy layers, shared by the Browser and upload paths."""

from typing import List

from qgis.core import (
    QgsEditorWidgetSetup,
    QgsProperty,
    QgsPropertyCollection,
    QgsVectorLayer,
)
from qgis.gui import QgsExternalResourceWidget, QgsFileWidget, QgsWidgetWrapper

from ...kumoy import api, external_storage, local_cache


def _attachment_widget_setup(
    vector_id: str, vector_column_id: str
) -> QgsEditorWidgetSetup:
    # StorageUrl must go through PropertyCollection: a plain config string gets
    # quoted as a literal and the expression is never evaluated.
    collection = QgsPropertyCollection()
    collection.setProperty(
        QgsWidgetWrapper.Property.StorageUrl,
        QgsProperty.fromExpression(
            external_storage.build_storage_url_expression(vector_id, vector_column_id),
            True,
        ),
    )

    return QgsEditorWidgetSetup(
        "ExternalResource",
        {
            "StorageType": external_storage.STORAGE_TYPE,
            "StorageMode": QgsFileWidget.StorageMode.GetFile,
            # DefaultRoot + RelativeDefaultPath makes doFetch receive
            # `{vectorId}/{value}`; the stored value alone has no vector_id.
            "DefaultRoot": vector_id,
            "RelativeStorage": QgsFileWidget.RelativeStorage.RelativeDefaultPath,
            "DocumentViewer": QgsExternalResourceWidget.DocumentViewerContent.Image,
            "DocumentViewerHeight": 0,
            "DocumentViewerWidth": 0,
            "UseLink": False,
            "FullUrl": False,
            "PropertyCollection": collection.toVariant(
                QgsWidgetWrapper.propertyDefinitions()
            ),
        },
    )


def _apply_attachment_widgets(
    layer: QgsVectorLayer, vector: api.vector.KumoyVectorDetail
) -> None:
    for column in vector.columns:
        if column.get("type") != "attachment":
            continue
        idx = layer.fields().indexOf(column["name"])
        if idx < 0:
            continue
        layer.setEditorWidgetSetup(
            idx, _attachment_widget_setup(vector.id, column["id"])
        )


def _staged_attachment_ids(
    layer: QgsVectorLayer, vector: api.vector.KumoyVectorDetail
) -> List[str]:
    """Collect the attachments whose file was staged but never uploaded."""
    buffer = layer.editBuffer()
    if buffer is None:
        return []

    indexes = [
        layer.fields().indexOf(column["name"])
        for column in vector.columns
        if column.get("type") == "attachment"
    ]
    values = []
    for feature in buffer.addedFeatures().values():
        values.extend(feature.attribute(idx) for idx in indexes if idx >= 0)
    for changed in buffer.changedAttributeValues().values():
        values.extend(changed.get(idx) for idx in indexes if idx >= 0)

    return [
        value for value in values if local_cache.attachment.is_staged(vector.id, value)
    ]


def configure_kumoy_layer(
    layer: QgsVectorLayer, vector: api.vector.KumoyVectorDetail
) -> None:
    config = layer.editFormConfig()

    # kumoy_id is assigned by the server, so keep it out of edit forms
    field_idx = layer.fields().indexOf("kumoy_id")
    if field_idx >= 0:
        config.setReadOnly(field_idx, True)

    layer.setEditFormConfig(config)

    _apply_attachment_widgets(layer, vector)

    def on_before_rollback() -> None:
        # Discarded edits are the only owner of their staged files, so nothing
        # will ever upload them
        current = getattr(layer.dataProvider(), "kumoy_vector", None) or vector
        for attachment_id in _staged_attachment_ids(layer, current):
            local_cache.attachment.discard_staged(current.id, attachment_id)

    layer.beforeRollBack.connect(on_before_rollback)
