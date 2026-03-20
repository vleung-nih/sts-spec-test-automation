"""
Manual tests for GET /id/{id}: verify 200 OK and response type matches expected entity type.
Uses fixed nanoids that map to Model, Node, Property, Term, Tag, Concept, Relationship, Value_set.
"""
import pytest

# (expected_type, nanoid) for each entity type
ID_BY_TYPE = [
    ("Model", "BXqzSM"),
    ("Node", "VTUKex"),
    ("Property", "dWCGhx"),
    ("Term", "sEzEfS"),
    ("Tag", "5kc0G6"),
    ("Concept", "hXZyty"),
    ("Relationship", "ueqz5Y"),
    ("ValueSet", "QGBE31"),
]


@pytest.mark.parametrize("expected_type, nanoid", ID_BY_TYPE)
def test_id_endpoint_returns_200_and_type(api_client, expected_type, nanoid):
    """GET /id/{nanoid} returns 200 and response type matches expected entity type."""
    path = f"/id/{nanoid}"
    response = api_client.get(path)
    assert response.status_code == 200, (
        f"GET {path}: expected 200, got {response.status_code}"
    )
    data = response.json()
    assert data is not None, f"GET {path}: response body is not JSON"
    assert data.get("type") == expected_type, (
        f"GET {path}: expected type {expected_type!r}, got {data.get('type')!r}"
    )
