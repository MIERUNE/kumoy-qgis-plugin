import base64
from typing import Dict, List, Optional

from qgis.core import QgsFeature
from qgis.PyQt.QtCore import QVariant

from .. import constants
from .client import ApiClient


def get_features(
    vector_id: str,
    strato_ids: Optional[List[int]] = None,
    bbox: Optional[List[float]] = None,
    limit: Optional[int] = None,
    after_id: Optional[int] = None,
) -> list:
    """
    Get features from a vector layer
    """
    if strato_ids is None:
        strato_ids = []

    options = {
        "strato_ids": strato_ids,
        "bbox": bbox,
        "limit": limit,
    }
    if after_id is not None:
        options["after_id"] = after_id

    response = ApiClient.post(f"/_qgis/vector/{vector_id}/get-features", options)

    # decode base64
    for feature in response:
        feature["strato_wkb"] = base64.b64decode(feature["strato_wkb"])

    return response


def add_features(
    vector_id: str,
    features: List[QgsFeature],
):
    """
    Add features to a vector layer
    """
    _features = [
        {
            "strato_wkb": base64.b64encode(f.geometry().asWkb()).decode("utf-8"),
            "properties": dict(zip(f.fields().names(), f.attributes())),
        }
        for f in features
    ]

    # rm strato_id from properties
    for feature in _features:
        if "strato_id" in feature["properties"]:
            del feature["properties"]["strato_id"]

    for feature in _features:
        for k in feature["properties"]:
            # HACK: replace QVariant of properties with None
            # attribute of f.attributes() become QVariant when it is null (other type is automatically casted to primitive)
            if (
                isinstance(feature["properties"][k], QVariant)
                and feature["properties"][k].isNull()
            ):
                feature["properties"][k] = None

    ApiClient.post(f"/_qgis/vector/{vector_id}/add-features", {"features": _features})


def delete_features(
    vector_id: str,
    strato_ids: List[int],
):
    """
    Delete features from a vector layer
    """
    ApiClient.post(
        f"/_qgis/vector/{vector_id}/delete-features", {"strato_ids": strato_ids}
    )


def change_attribute_values(
    vector_id: str,
    attribute_items: List[Dict],
):
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
):
    """
    Change geometry values of a feature in a vector layer
    """
    geometry_items_encoded = [
        {
            "strato_id": item["strato_id"],
            "strato_wkb": base64.b64encode(item["geom"]).decode("utf-8"),
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
):
    """
    Update column types in a vector layer

    Args:
        vector_id: The ID of the vector layer
        columns: Dictionary mapping column names to data types ('integer', 'float', 'string', 'boolean')
    """
    ApiClient.post(f"/_qgis/vector/{vector_id}/update-columns", {"columns": columns})


def add_attributes(
    vector_id: str,
    attributes: dict,
):
    """
    Add new attributes to a vector layer

    Args:
        vector_id: The ID of the vector layer
        attributes: Dictionary mapping attribute names to data types ('integer', 'float', 'string', 'boolean')
    """
    ApiClient.post(
        f"/_qgis/vector/{vector_id}/add-attributes", {"attributes": attributes}
    )


def delete_attributes(
    vector_id: str,
    attribute_names: List[str],
):
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
):
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


def get_diff(vector_id: str, last_updated: str) -> List[Dict]:
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
        feature["strato_wkb"] = base64.b64decode(feature["strato_wkb"])

    return response
