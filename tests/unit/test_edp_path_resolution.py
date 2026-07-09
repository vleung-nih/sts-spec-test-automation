"""Unit tests for EDP discovery and path-param resolution (no network)."""

from sts_test_framework.client import APIResponse
from sts_test_framework.discover import _discover_edp
from sts_test_framework.generator import _resolve_path_params


class _FakeClient:
    """Minimal stand-in for APIClient used by _discover_edp."""

    def __init__(self, response: APIResponse):
        self._response = response
        self.last_path = None
        self.last_params = None

    def get(self, path, params=None):
        self.last_path = path
        self.last_params = params
        return self._response


def _edps_path_params():
    return [{"name": "originName", "in": "path", "required": True, "schema": {"type": "string"}}]


def _edp_terms_path_params():
    return [
        {"name": "originName", "in": "path", "required": True, "schema": {"type": "string"}},
        {"name": "originId", "in": "path", "required": True, "schema": {"type": "string"}},
        {"name": "originVersion", "in": "path", "required": True, "schema": {"type": "string"}},
    ]


def test_resolve_edps_origin_name_only():
    test_data = {
        "edp_origin_name": "caDSR",
        "edp_origin_id": "7572817",
        "edp_origin_version": "2.0",
    }
    result = _resolve_path_params("/edps/{originName}", _edps_path_params(), test_data)
    assert result == {"originName": "caDSR"}


def test_resolve_edp_terms_all_three_params():
    test_data = {
        "edp_origin_name": "caDSR",
        "edp_origin_id": "7572817",
        "edp_origin_version": "2.0",
    }
    result = _resolve_path_params(
        "/edp/{originName}/{originId}/{originVersion}/terms",
        _edp_terms_path_params(),
        test_data,
    )
    assert result == {
        "originName": "caDSR",
        "originId": "7572817",
        "originVersion": "2.0",
    }


def test_resolve_returns_none_when_edp_origin_name_missing():
    test_data = {"edp_origin_id": "7572817", "edp_origin_version": "2.0"}
    assert _resolve_path_params("/edps/{originName}", _edps_path_params(), test_data) is None


def test_resolve_returns_none_when_edp_id_or_version_missing():
    test_data = {"edp_origin_name": "caDSR", "edp_origin_id": "7572817"}
    assert (
        _resolve_path_params(
            "/edp/{originName}/{originId}/{originVersion}/terms",
            _edp_terms_path_params(),
            test_data,
        )
        is None
    )


def test_discover_edp_extracts_first_complete_term():
    body = [
        {"type": "Term", "value": "Incomplete", "origin_name": "caDSR"},
        {
            "type": "Term",
            "value": "Person Sex at Birth Category",
            "origin_name": "caDSR",
            "origin_id": "7572817",
            "origin_version": "2.0",
        },
    ]
    client = _FakeClient(APIResponse(200, "...", body, 0.1))
    result = _discover_edp(client, "caDSR")
    assert result == {
        "edp_origin_name": "caDSR",
        "edp_origin_id": "7572817",
        "edp_origin_version": "2.0",
        "edp_available": True,
    }
    assert client.last_path == "/edps/caDSR"
    assert client.last_params == {"limit": 10}


def test_discover_edp_empty_when_no_usable_terms():
    client = _FakeClient(APIResponse(200, "...", [], 0.1))
    assert _discover_edp(client, "caDSR") == {}


def test_discover_edp_empty_on_non_200():
    client = _FakeClient(APIResponse(404, "...", {"detail": "Not found."}, 0.1))
    assert _discover_edp(client, "caDSR") == {}


def test_discover_edp_skips_blank_id_or_version():
    body = [
        {"origin_id": "  ", "origin_version": "2.0"},
        {"origin_id": "7572817", "origin_version": ""},
    ]
    client = _FakeClient(APIResponse(200, "...", body, 0.1))
    assert _discover_edp(client, "caDSR") == {}
