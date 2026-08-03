"""Edit form setup for Kumoy layers, shared by the Browser and upload paths."""

from qgis.core import (
    QgsEditorWidgetSetup,
    QgsProperty,
    QgsPropertyCollection,
    QgsVectorLayer,
)
from qgis.gui import QgsExternalResourceWidget, QgsFileWidget, QgsWidgetWrapper

from ...kumoy import api, external_storage


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
            # `{vectorId}/{value}`; the value alone has no vector_id.
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


def configure_kumoy_layer(
    layer: QgsVectorLayer, vector: api.vector.KumoyVectorDetail
) -> None:
    config = layer.editFormConfig()

    # kumoy_id is assigned by the server, so keep it out of edit forms
    field_idx = layer.fields().indexOf("kumoy_id")
    if field_idx >= 0:
        config.setReadOnly(field_idx, True)

    layer.setEditFormConfig(config)

    for column in vector.columns:
        if column.get("type") != "attachment":
            continue
        idx = layer.fields().indexOf(column["name"])
        if idx < 0:
            continue
        layer.setEditorWidgetSetup(
            idx, _attachment_widget_setup(vector.id, column["id"])
        )
