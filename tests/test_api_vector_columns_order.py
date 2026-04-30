"""kumoy.api.vector.get_vector が columns を name 昇順に正規化することを検証する."""

from unittest.mock import patch


def test_get_vector_sorts_columns_by_name():
    from plugin_dir.kumoy.api import vector as api_vector

    response = {
        "id": "v1",
        "name": "test",
        "type": "POINT",
        "projectId": "p1",
        "project": {},
        "attribution": "",
        "storageUnits": 0,
        "createdAt": "",
        "updatedAt": "",
        "extent": [],
        "count": 0,
        "role": "MEMBER",
        "columns": [
            {"name": "z_col", "type": "string"},
            {"name": "a_col", "type": "integer"},
            {"name": "m_col", "type": "float"},
        ],
    }

    with patch.object(api_vector.ApiClient, "get", return_value=response):
        result = api_vector.get_vector("v1")

    assert [c["name"] for c in result.columns] == ["a_col", "m_col", "z_col"]


def test_get_vector_handles_missing_columns():
    from plugin_dir.kumoy.api import vector as api_vector

    response = {
        "id": "v1",
        "name": "test",
        "type": "POINT",
        "projectId": "p1",
        "project": {},
        "attribution": "",
        "storageUnits": 0,
        "createdAt": "",
        "updatedAt": "",
        "extent": [],
        "count": 0,
        "role": "MEMBER",
    }

    with patch.object(api_vector.ApiClient, "get", return_value=response):
        result = api_vector.get_vector("v1")

    assert result.columns == []
