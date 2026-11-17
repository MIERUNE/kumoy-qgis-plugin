"""Feature endpoints used only by the plugin (/api/_qgis/vector/...).

Rows are {"kumoy_id": int, "kumoy_wkb": bytes, "properties": dict}; WKB is
base64 on the wire and bytes here.
"""

import base64
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import client

# Fixed page size of get-features-v2: a shorter page is the last one
FEATURES_PAGE_SIZE = 5000
# add/change/delete accept at most this many items per request
MAX_ITEMS_PER_REQUEST = 1000
# Limit of one base64-encoded geometry
MAX_WKB_BASE64_LENGTH = 10_000_000
# get-diff answers 400 with this when more than 1000 rows changed
MAX_DIFF_COUNT_EXCEEDED = "MAX_DIFF_COUNT_EXCEEDED"


def _decode_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for row in rows:
        row["kumoy_wkb"] = base64.b64decode(row["kumoy_wkb"])
    return rows


def encode_wkb(wkb: bytes) -> str:
    return base64.b64encode(bytes(wkb)).decode("ascii")


def get_features(vector_id: str, after_id: Optional[int] = None) -> List[Dict]:
    """One page of features ordered by kumoy_id, starting after `after_id`."""
    payload = {} if after_id is None else {"after_id": after_id}
    rows = client.post(f"/_qgis/vector/{vector_id}/get-features-v2", payload)
    return _decode_rows(rows or [])


@dataclass
class Diff:
    updated_rows: List[Dict]
    deleted_ids: List[int]


def get_diff(vector_id: str, last_updated: str) -> Diff:
    """Rows changed after `last_updated` (ISO 8601, server clock).

    Raises AppError with error == MAX_DIFF_COUNT_EXCEEDED when the diff is too
    large; reload everything then.
    """
    data = client.post(
        f"/_qgis/vector/{vector_id}/get-diff", {"last_updated": last_updated}
    )
    # The OpenAPI schema says [{kumoy_id}] but the server sends plain ids
    deleted = [d["kumoy_id"] if isinstance(d, dict) else d for d in data["deletedRows"]]
    return Diff(_decode_rows(data["updatedRows"]), deleted)


def add_features(vector_id: str, features: List[Dict]) -> List[int]:
    """features: [{"kumoy_wkb": base64 str, "properties": {...}}]. Returns new ids."""
    data = client.post(
        f"/_qgis/vector/{vector_id}/add-features", {"features": features}
    )
    return list(data or [])


def change_attribute_values(vector_id: str, items: List[Dict]) -> None:
    """items: [{"kumoy_id": int, "properties": {...}}]"""
    client.post(
        f"/_qgis/vector/{vector_id}/change-attribute-values",
        {"attribute_items": items},
    )


def change_geometry_values(vector_id: str, items: List[Dict]) -> None:
    """items: [{"kumoy_id": int, "kumoy_wkb": base64 str}]"""
    client.post(
        f"/_qgis/vector/{vector_id}/change-geometry-values",
        {"geometry_items": items},
    )


def delete_features(vector_id: str, kumoy_ids: List[int]) -> None:
    client.post(f"/_qgis/vector/{vector_id}/delete-features", {"kumoy_ids": kumoy_ids})


def add_attributes(vector_id: str, attributes: List[Dict[str, str]]) -> None:
    """attributes: [{"name": str, "type": integer|float|string|boolean}]"""
    client.post(
        f"/_qgis/vector/{vector_id}/add-attributes-v2", {"attributes": attributes}
    )


def delete_attributes(vector_id: str, names: List[str]) -> None:
    client.post(
        f"/_qgis/vector/{vector_id}/delete-attributes", {"attributeNames": names}
    )
