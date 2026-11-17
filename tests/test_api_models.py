import pytest

from plugin_dir.kumoy.api.error import (
    ForbiddenError,
    NetworkError,
    QuotaExceededError,
    UnauthorizedError,
    error_from_response,
)
from plugin_dir.kumoy.api.models import (
    OrganizationDetail,
    VectorDetail,
    from_dict,
    list_of,
)


def test_nested_and_defaults():
    v = from_dict(
        VectorDetail,
        {
            "id": "v1",
            "name": "roads",
            "type": "LINESTRING",
            "extent": [1, 2, 3, 4],
            "columns": [{"name": "a", "type": "string"}],
            "unknown": 1,
        },
    )
    assert v.columns[0].name == "a"
    assert v.role == "MEMBER"
    org = from_dict(OrganizationDetail, {"id": "o", "name": "n", "planSettings": {}})
    assert org.planSettings.maxVectors == 0


def test_missing_required_field_fails_loudly():
    with pytest.raises(ValueError):
        list_of(VectorDetail, [{"id": "v1", "name": "x"}])


@pytest.mark.parametrize(
    "status,cls",
    [(401, UnauthorizedError), (403, ForbiddenError), (429, QuotaExceededError)],
)
def test_error_by_status(status, cls):
    e = error_from_response(status, {"message": "m", "error": "d"}, "f")
    assert type(e) is cls and e.error == "d"


def test_network_error_and_odd_bodies():
    assert isinstance(error_from_response(None, None, "offline"), NetworkError)
    # zod validation failures use {"success": false, "error": {...}}
    e = error_from_response(400, {"success": False, "error": {"issues": []}}, "bad")
    assert e.message == "bad" and e.error == ""
