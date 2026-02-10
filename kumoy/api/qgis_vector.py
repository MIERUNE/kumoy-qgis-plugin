import base64
from typing import Dict, List, Optional

from qgis.core import QgsFeature
from qgis.PyQt.QtCore import QCoreApplication, QDate, QDateTime, QTime, QVariant

from .. import constants
from .client import ApiClient


def tr(message: str) -> str:
    return QCoreApplication.translate("@default", message)


def get_features(
    vector_id: str,
    kumoy_ids: Optional[List[int]] = None,
    bbox: Optional[List[float]] = None,
    limit: Optional[int] = None,
    after_id: Optional[int] = None,
) -> list:
    """
    Get features from a vector layer
    """
    if kumoy_ids is None:
        kumoy_ids = []

    options = {
        "kumoy_ids": kumoy_ids,
        "bbox": bbox,
        "limit": limit,
    }
    if after_id is not None:
        options["after_id"] = after_id

    response = ApiClient.post(f"/_qgis/vector/{vector_id}/get-features", options)

    # decode base64
    for feature in response:
        feature["kumoy_wkb"] = base64.b64decode(feature["kumoy_wkb"])

    return response


class WkbTooLargeError(Exception):
    """Raised when a feature's WKB exceeds the maximum allowed length."""

    pass


def add_features(
    vector_id: str,
    features: List[QgsFeature],
) -> None:
    """
    Add features to a vector layer
    """
    _features = []
    for f in features:
        kumoy_wkb = base64.b64encode(f.geometry().asWkb()).decode("utf-8")
        if len(kumoy_wkb) > constants.MAX_WKB_LENGTH:
            raise WkbTooLargeError(
                tr("Feature geometry exceeds maximum WKB length ({} > {})").format(
                    f"{len(kumoy_wkb):,}", f"{constants.MAX_WKB_LENGTH:,}"
                )
            )
        _features.append(
            {
                "kumoy_wkb": kumoy_wkb,
                "properties": dict(zip(f.fields().names(), f.attributes())),
            }
        )

    # rm kumoy_id from properties
    for feature in _features:
        if "kumoy_id" in feature["properties"]:
            del feature["properties"]["kumoy_id"]

    for feature in _features:
        for k in feature["properties"]:
            # HACK: replace QVariant of properties with None
            # attribute of f.attributes() become QVariant when it is null (other type is automatically casted to primitive)
            if (
                isinstance(feature["properties"][k], QVariant)
                and feature["properties"][k].isNull()
            ):
                feature["properties"][k] = None

            # HACK: Replace Qt datetime objects to string
            # attribute of f.attributes() become QDateTime/QDate/QTime when the field type is written in date time format
            # input: PyQt.QtCore.QDateTime(2026, 2, 4, 10, 29, 41, 859)
            # output: '2026-02-04T10:29:41.859'
            elif isinstance(feature["properties"][k], QDateTime):
                feature["properties"][k] = feature["properties"][k].toString(
                    "yyyy-MM-ddTHH:mm:ss.zzz"
                )
            elif isinstance(feature["properties"][k], QDate):
                feature["properties"][k] = feature["properties"][k].toString(
                    "yyyy-MM-dd"
                )
            elif isinstance(feature["properties"][k], QTime):
                feature["properties"][k] = feature["properties"][k].toString(
                    "HH:mm:ss.zzz"
                )

    ApiClient.post(f"/_qgis/vector/{vector_id}/add-features", {"features": _features})


def delete_features(
    vector_id: str,
    kumoy_ids: List[int],
) -> None:
    """
    Delete features from a vector layer
    """
    ApiClient.post(
        f"/_qgis/vector/{vector_id}/delete-features", {"kumoy_ids": kumoy_ids}
    )


def change_attribute_values(
    vector_id: str,
    attribute_items: List[Dict],
) -> None:
    """
    Change attribute values of a feature in a vector layer
    """
    ApiClient.post(
        f"/_qgis/vector/{vector_id}/change-attribute-values",
        {"attribute_items": attribute_items},
    )


def change_geometry_values(
    vector_id: str,
    geometry_items: List[Dict],
) -> None:
    """
    Change geometry values of a feature in a vector layer
    """
    geometry_items_encoded = [
        {
            "kumoy_id": item["kumoy_id"],
            "kumoy_wkb": base64.b64encode(item["geom"]).decode("utf-8"),
        }
        for item in geometry_items
    ]

    ApiClient.post(
        f"/_qgis/vector/{vector_id}/change-geometry-values",
        {"geometry_items": geometry_items_encoded},
    )


def update_columns(
    vector_id: str,
    columns: dict,
) -> None:
    """
    Update column types in a vector layer

    Args:
        vector_id: The ID of the vector layer
        columns: Dictionary mapping column names to data types ('integer', 'float', 'string', 'boolean')
    """
    ApiClient.post(f"/_qgis/vector/{vector_id}/update-columns", {"columns": columns})


def add_attributes(
    vector_id: str,
    attributes: List[dict],
) -> None:
    """
    Add new attributes to a vector layer

    Args:
        vector_id: The ID of the vector layer
        attributes: List of dicts with 'name' and 'type' keys.
                    type is one of 'integer', 'float', 'string', 'boolean'
    """
    ApiClient.post(
        f"/_qgis/vector/{vector_id}/add-attributes-v2", {"attributes": attributes}
    )


def delete_attributes(
    vector_id: str,
    attribute_names: List[str],
) -> None:
    """
    Delete attributes from a vector layer

    Args:
        vector_id: The ID of the vector layer
        attribute_names: List of attribute names to delete
    """
    ApiClient.post(
        f"/_qgis/vector/{vector_id}/delete-attributes",
        {"attributeNames": attribute_names},
    )


def rename_attributes(
    vector_id: str,
    attribute_map: dict,
) -> None:
    """
    Rename attributes in a vector layer

    Args:
        vector_id: The ID of the vector layer
        attribute_map: Dictionary mapping old attribute names to new attribute names
    """
    ApiClient.post(
        f"/_qgis/vector/{vector_id}/rename-attributes",
        {"attributeMap": attribute_map},
    )


def get_diff(vector_id: str, last_updated: str) -> Dict:
    """
    Get the difference of features in a vector layer since the last updated time.

    Args:
        vector_id: The ID of the vector layer.
        last_updated_at: The last updated time in ISO format.

    Returns:
        A list of features that have changed since the last updated time.
    """
    response = ApiClient.post(
        f"/_qgis/vector/{vector_id}/get-diff",
        {"last_updated": last_updated},
    )

    for feature in response["updatedRows"]:
        feature["kumoy_wkb"] = base64.b64decode(feature["kumoy_wkb"])

    return response
