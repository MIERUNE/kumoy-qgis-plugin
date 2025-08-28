import base64
from typing import Dict, List, Optional

from qgis.core import QgsFeature
from qgis.PyQt.QtCore import QVariant

from ..provider.local_cache import MaxDiffCountExceededError
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

    if response.get("error"):
        print(f"Error fetching features for vector {vector_id}: {response['error']}")
        return []

    # decode base64
    for feature in response["content"]:
        feature["strato_wkb"] = base64.b64decode(feature["strato_wkb"])

    return response["content"]


def add_features(
    vector_id: str,
    features: List[QgsFeature],
) -> bool:
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

    # HACK: replace QVariant of properties with None
    # attribute of f.attributes() become QVariant when it is null (other type is automatically casted to primitive)
    for feature in _features:
        for k in feature["properties"]:
            if (
                isinstance(feature["properties"][k], QVariant)
                and feature["properties"][k].isNull()
            ):
                feature["properties"][k] = None

    response = ApiClient.post(
        f"/_qgis/vector/{vector_id}/add-features", {"features": _features}
    )

    if response.get("error"):
        print(f"Error adding features to vector {vector_id}: {response['error']}")
        return False

    return True


def delete_features(
    vector_id: str,
    strato_ids: List[int],
) -> bool:
    """
    Delete features from a vector layer
    """
    response = ApiClient.post(
        f"/_qgis/vector/{vector_id}/delete-features", {"strato_ids": strato_ids}
    )

    if response.get("error"):
        print(f"Error deleting features from vector {vector_id}: {response['error']}")
        return False

    return True


def change_attribute_values(
    vector_id: str,
    attribute_items: List[Dict],
) -> bool:
    """
    Change attribute values of a feature in a vector layer
    """
    response = ApiClient.post(
        f"/_qgis/vector/{vector_id}/change-attribute-values",
        {"attribute_items": attribute_items},
    )

    if response.get("error"):
        print(
            f"Error changing attribute values for features in vector {vector_id}: {response['error']}"
        )
        return False

    return True


def change_geometry_values(
    vector_id: str,
    geometry_items: List[Dict],
) -> bool:
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

    response = ApiClient.post(
        f"/_qgis/vector/{vector_id}/change-geometry-values",
        {"geometry_items": geometry_items_encoded},
    )

    if response.get("error"):
        print(
            f"Error changing geometry values for {geometry_items} in vector {vector_id}: {response['error']}"
        )
        return False

    return True


def update_columns(
    vector_id: str,
    columns: dict,
) -> bool:
    """
    Update column types in a vector layer

    Args:
        vector_id: The ID of the vector layer
        columns: Dictionary mapping column names to data types ('integer', 'float', 'string', 'boolean')
    """
    response = ApiClient.post(
        f"/_qgis/vector/{vector_id}/update-columns", {"columns": columns}
    )

    if response.get("error"):
        print(f"Error updating columns in vector {vector_id}: {response['error']}")
        return False

    return True


def add_attributes(
    vector_id: str,
    attributes: dict,
) -> bool:
    """
    Add new attributes to a vector layer

    Args:
        vector_id: The ID of the vector layer
        attributes: Dictionary mapping attribute names to data types ('integer', 'float', 'string', 'boolean')
    """
    response = ApiClient.post(
        f"/_qgis/vector/{vector_id}/add-attributes", {"attributes": attributes}
    )

    if response.get("error"):
        print(f"Error adding attributes to vector {vector_id}: {response['error']}")
        return False

    return True


def delete_attributes(
    vector_id: str,
    attribute_names: List[str],
) -> bool:
    """
    Delete attributes from a vector layer

    Args:
        vector_id: The ID of the vector layer
        attribute_names: List of attribute names to delete
    """
    response = ApiClient.post(
        f"/_qgis/vector/{vector_id}/delete-attributes",
        {"attributeNames": attribute_names},
    )

    if response.get("error"):
        print(f"Error deleting attributes from vector {vector_id}: {response['error']}")
        return False

    return True


def rename_attributes(
    vector_id: str,
    attribute_map: dict,
) -> bool:
    """
    Rename attributes in a vector layer

    Args:
        vector_id: The ID of the vector layer
        attribute_map: Dictionary mapping old attribute names to new attribute names
    """
    response = ApiClient.post(
        f"/_qgis/vector/{vector_id}/rename-attributes",
        {"attributeMap": attribute_map},
    )

    if response.get("error"):
        print(f"Error renaming attributes in vector {vector_id}: {response['error']}")
        return False

    return True


def get_diff(vector_id: str, last_updated: str) -> List[Dict]:
    """
    Get the difference of features in a vector layer since the last updated time.

    Args:
        vector_id: The ID of the vector layer.
        last_updated_at: The last updated time in ISO format.

    Raises:
        MaxDiffCountExceededError: If the diff exceeds the maximum allowed size.

    Returns:
        A list of features that have changed since the last updated time.
    """
    response = ApiClient.post(
        f"/_qgis/vector/{vector_id}/get-diff",
        {"last_updated": last_updated},
    )

    if response.get("error"):
        # 差分の最大数超過エラーを検知
        if response["error"]["error"] == "MAX_DIFF_COUNT_EXCEEDED":
            # 呼び出し元に伝搬
            raise MaxDiffCountExceededError("MAX_DIFF_COUNT_EXCEEDED")

        print(f"Error getting diff for vector {vector_id}: {response['error']}")
        return {
            "updatedRows": [],
            "deletedRows": [],
        }

    for feature in response["content"]["updatedRows"]:
        feature["strato_wkb"] = base64.b64decode(feature["strato_wkb"])

    return response["content"]
