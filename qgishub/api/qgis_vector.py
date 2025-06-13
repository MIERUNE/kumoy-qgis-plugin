import base64
from typing import Dict, List, Optional

from PyQt5.QtCore import QVariant
from qgis.core import QgsFeature

from .client import ApiClient


def get_features(
    vector_id: str,
    qgishub_ids: Optional[List[int]] = None,
    bbox: Optional[List[float]] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    use_blocking: bool = False,
) -> list:
    """
    Get features from a vector layer
    
    Args:
        vector_id: The ID of the vector layer
        qgishub_ids: Optional list of specific feature IDs to fetch
        bbox: Optional bounding box filter
        limit: Optional limit on number of features
        offset: Optional offset for pagination
        use_blocking: If True, use blocking API client (for use in feature iterators)
    """
    if qgishub_ids is None:
        qgishub_ids = []

    try:
        # Use ApiClient (now uses blocking requests)
        client = ApiClient
        
        response = client.post(
            f"/_qgis/vector/{vector_id}/get-features",
            {
                "qgishub_ids": qgishub_ids,
                "bbox": bbox,
                "limit": limit,
                "offset": offset,
            },
        )

        # decode base64
        for feature in response:
            feature["qgishub_wkb"] = base64.b64decode(feature["qgishub_wkb"])

        return response
    except Exception as e:
        print(f"Error fetching features for vector {vector_id}: {str(e)}")
        return []


def add_features(
    vector_id: str,
    features: List[QgsFeature],
) -> bool:
    """
    Add features to a vector layer
    """
    try:
        _features = [
            {
                "qgishub_wkb": base64.b64encode(f.geometry().asWkb()).decode("utf-8"),
                "properties": dict(zip(f.fields().names(), f.attributes())),
            }
            for f in features
        ]

        # HACK: replace QVariant of properties with None
        # attribute of f.attributes() become QVariant when it is null (other type is automatically casted to primitive)
        for feature in _features:
            for k in feature["properties"]:
                if (
                    isinstance(feature["properties"][k], QVariant)
                    and feature["properties"][k].isNull()
                ):
                    feature["properties"][k] = None

        ApiClient.post(
            f"/_qgis/vector/{vector_id}/add-features", {"features": _features}
        )

        return True
    except Exception as e:
        print(f"Error adding features to vector {vector_id}: {str(e)}")
        return False


def delete_features(
    vector_id: str,
    qgishub_ids: List[int],
) -> bool:
    """
    Delete features from a vector layer
    """
    try:
        ApiClient.post(
            f"/_qgis/vector/{vector_id}/delete-features", {"qgishub_ids": qgishub_ids}
        )

        return True
    except Exception as e:
        print(f"Error deleting features from vector {vector_id}: {str(e)}")
        return False


def change_attribute_values(
    vector_id: str,
    attribute_items: List[Dict],
) -> bool:
    """
    Change attribute values of a feature in a vector layer
    """
    try:
        ApiClient.post(
            f"/_qgis/vector/{vector_id}/change-attribute-values",
            {"attribute_items": attribute_items},
        )
        return True
    except Exception as e:
        print(
            f"Error changing attribute values for features in vector {vector_id}: {str(e)}"
        )
        return False


def change_geometry_values(
    vector_id: str,
    geometry_items: List[Dict],
) -> bool:
    """
    Change geometry values of a feature in a vector layer
    """
    try:
        geometry_items_encoded = [
            {
                "qgishub_id": item["qgishub_id"],
                "qgishub_wkb": base64.b64encode(item["geom"]).decode("utf-8"),
            }
            for item in geometry_items
        ]

        ApiClient.post(
            f"/_qgis/vector/{vector_id}/change-geometry-values",
            {"geometry_items": geometry_items_encoded},
        )
        return True
    except Exception as e:
        print(
            f"Error changing geometry values for {geometry_items} in vector {vector_id}: {str(e)}"
        )
        return False


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
    try:
        ApiClient.post(
            f"/_qgis/vector/{vector_id}/update-columns", {"columns": columns}
        )
        return True
    except Exception as e:
        print(f"Error updating columns in vector {vector_id}: {str(e)}")
        return False


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
    try:
        ApiClient.post(
            f"/_qgis/vector/{vector_id}/add-attributes", {"attributes": attributes}
        )
        return True
    except Exception as e:
        print(f"Error adding attributes to vector {vector_id}: {str(e)}")
        return False


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
    try:
        ApiClient.post(
            f"/_qgis/vector/{vector_id}/delete-attributes",
            {"attributeNames": attribute_names},
        )
        return True
    except Exception as e:
        print(f"Error deleting attributes from vector {vector_id}: {str(e)}")
        return False


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
    try:
        ApiClient.post(
            f"/_qgis/vector/{vector_id}/rename-attributes",
            {"attributeMap": attribute_map},
        )
        return True
    except Exception as e:
        print(f"Error renaming attributes in vector {vector_id}: {str(e)}")
        return False
