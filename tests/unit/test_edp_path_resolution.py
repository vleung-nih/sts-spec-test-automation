"""Unit tests for EDP discovery and path-param resolution (no network)."""

from sts_test_framework.client import APIResponse
from sts_test_framework.config import bundled_spec_path
from sts_test_framework.discover import _discover_edp
from sts_test_framework.generator import (
    _is_edp_properties_path,
    _resolve_path_params,
    generate_cases,
)
from sts_test_framework.loader import load_spec


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


def test_is_edp_properties_path_matches_edps_properties_route():
    assert _is_edp_properties_path(
        "/edps/{originName}/{originId}/{originVersion}/properties"
    )
    assert _is_edp_properties_path(
        "/v2/edps/{originName}/{originId}/{originVersion}/properties"
    )


def test_is_edp_properties_path_rejects_model_and_terms_routes():
    assert not _is_edp_properties_path(
        "/model/{modelHandle}/version/{versionString}/node/{nodeHandle}/properties"
    )
    assert not _is_edp_properties_path(
        "/edp/{originName}/{originId}/{originVersion}/terms"
    )
    assert not _is_edp_properties_path("/edps/{originName}")


def test_edp_properties_skip_oob_expects_200_empty_list():
    """Huge skip on edp properties must generate 200 + [] (same shape as cde-pvs)."""
    spec_path = bundled_spec_path()
    assert spec_path.exists(), f"Bundled spec missing: {spec_path}"
    spec = load_spec(spec_path)
    test_data = {
        "edp_origin_name": "caDSR",
        "edp_origin_id": "14883058",
        "edp_origin_version": "1.00",
        "edp_available": True,
    }
    cases = generate_cases(spec, test_data, include_negative=True)
    oob = [
        c
        for c in cases
        if str(c.get("operation_id") or "").endswith("__skip_oob")
        and "/edps/" in (c.get("path") or "")
        and (c.get("path") or "").endswith("/properties")
    ]
    assert len(oob) == 1, f"Expected one edp-properties __skip_oob case, got {len(oob)}"
    case = oob[0]
    assert case["expected_status"] == 200
    assert case.get("expected_json") == []
    assert case.get("negative") is False
    assert case["params"].get("skip") == 9_999_999


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
        {"origin_id": "7572817", "origin_version": "2.0", "value": "x"},
        {"origin_id": "999", "origin_version": "1.0", "value": "y"},
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
