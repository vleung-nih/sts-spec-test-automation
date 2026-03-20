"""Unit tests for ``_pagination_pair_check`` (two-request pagination slice)."""

from sts_test_framework.client import APIResponse
from sts_test_framework.runners.functional import _pagination_pair_check


class _MockClient:
    """Returns queued ``APIResponse`` from ``.get(path, params)`` in order."""

    def __init__(self, responses: list[APIResponse]):
        self._responses = responses
        self._i = 0
        self.calls: list[tuple[str, dict]] = []

    def get(self, path: str, params: dict | None) -> APIResponse:
        self.calls.append((path, dict(params or {})))
        r = self._responses[self._i]
        self._i += 1
        return r


def _case():
    return {
        "path": "/models/",
        "pagination_pair_params_a": {"skip": 0, "limit": 0},
        "pagination_pair_params_b": {"skip": 1, "limit": 1},
    }


def test_pair_skips_when_a_has_fewer_than_two_items():
    a = APIResponse(200, "[]", [], 0.01)
    client = _MockClient([a])
    out = _pagination_pair_check(client, _case())
    assert out.ok and out.error is None
    assert out.actual_status == 200
    assert out.b_executed is False
    assert len(client.calls) == 1


def test_pair_passes_when_b0_equals_a1():
    a_data = [{"id": "x"}, {"id": "y"}, {"id": "z"}]
    b_data = [{"id": "y"}]
    a = APIResponse(200, "...", a_data, 0.01)
    b = APIResponse(200, "...", b_data, 0.02)
    client = _MockClient([a, b])
    out = _pagination_pair_check(client, _case())
    assert out.ok and out.error is None
    assert out.actual_status == 200
    assert out.duration_total == 0.01 + 0.02
    assert out.b_executed is True
    assert out.duration_a == 0.01 and out.duration_b == 0.02
    assert len(client.calls) == 2


def test_pair_fails_when_b0_not_equal_a1():
    a_data = [{"id": "a"}, {"id": "b"}]
    b_data = [{"id": "wrong"}]
    client = _MockClient(
        [
            APIResponse(200, "...", a_data, 0.01),
            APIResponse(200, "...", b_data, 0.02),
        ]
    )
    out = _pagination_pair_check(client, _case())
    assert out.ok is False
    assert out.error is not None
    assert "B[0]" in out.error or "!=" in out.error


def test_pair_fails_when_a_not_200():
    client = _MockClient([APIResponse(500, "err", None, 0.01)])
    out = _pagination_pair_check(client, _case())
    assert out.ok is False
    assert "pagination_pair A" in (out.error or "")
    assert out.actual_status == 500


_TERMS_404_BODY = '{"detail":"Property exists, but does not use an acceptable value set."}'
_TERMS_404_JSON = {"detail": "Property exists, but does not use an acceptable value set."}


def _terms_case():
    return {
        "path": "/model/M/version/1.0.0/node/n/property/p/terms",
        "pagination_pair_params_a": {"skip": 0, "limit": 0},
        "pagination_pair_params_b": {"skip": 1, "limit": 1},
    }


def test_pair_passes_when_a_returns_acceptable_terms_404():
    a = APIResponse(404, _TERMS_404_BODY, _TERMS_404_JSON, 0.01)
    client = _MockClient([a])
    out = _pagination_pair_check(client, _terms_case())
    assert out.ok is True
    assert out.error and out.error.startswith("Special expected 404")
    assert out.actual_status == 404
    assert out.b_executed is False
    assert len(client.calls) == 1


def test_pair_passes_when_b_returns_acceptable_terms_404():
    a_data = [{"id": "x"}, {"id": "y"}]
    a = APIResponse(200, "...", a_data, 0.01)
    b = APIResponse(404, _TERMS_404_BODY, _TERMS_404_JSON, 0.02)
    client = _MockClient([a, b])
    out = _pagination_pair_check(client, _terms_case())
    assert out.ok is True
    assert out.error and out.error.startswith("Special expected 404")
    assert out.actual_status == 404
    assert out.b_executed is True
    assert len(client.calls) == 2
