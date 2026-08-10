import base64
from typing import Callable, Dict, List, Optional

from qgis.core import QgsFeature

from .. import constants
from ... import i18n
from .client import ApiClient
from .flatgeobuf import _normalized_properties


def get_features(
    vector_id: str,
    after_id: Optional[int] = None,
) -> list:
    """
    Get features from a vector layer
    """
    options = {}
    if after_id is not None:
        options["after_id"] = after_id

    response = ApiClient.post(f"/_qgis/vector/{vector_id}/get-features-v2", options)

    # decode base64
    for feature in response:
        feature["kumoy_wkb"] = base64.b64decode(feature["kumoy_wkb"])

    return response


def get_features_v3(
    vector_id: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> str:
    """Download all vector features as one FlatGeobuf temporary file."""
    return ApiClient.post_binary_to_file(
        f"/_qgis/vector/{vector_id}/get-features-v3",
        {},
        progress_callback=progress_callback,
        suffix=".fgb",
    )


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
                i18n.tr("Feature geometry exceeds maximum WKB length ({} > {})").format(
                    f"{len(kumoy_wkb):,}", f"{constants.MAX_WKB_LENGTH:,}"
                )
            )
        _features.append(
            {
                "kumoy_wkb": kumoy_wkb,
                "properties": _normalized_properties(f),
            }
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
