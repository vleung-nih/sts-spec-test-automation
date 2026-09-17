"""
Manual tests: **v2 root readiness** — ``GET /`` returns STS status and deployed version.

================================================================================
WHAT THIS IS (plain English)
================================================================================

The v2 base URL (``STS_BASE_URL``, e.g. ``https://sts-qa.cancer.gov/v2``) should
respond at ``GET /`` with a small JSON readiness payload:

- ``application``: ``"STS"``
- ``status``: ``"READY"``
- ``version``: the deployed package version (expected to match the bundled OpenAPI spec)

**Why it matters:** Clients and operators use this endpoint to confirm STS is up and
which version is running without calling a data endpoint.

================================================================================
WHERE THE EXPECTED VERSION COMES FROM
================================================================================

- **``spec_version`` fixture** — reads ``info.version`` from the bundled OpenAPI spec
  (``spec/v2-5-0.json`` via ``bundled_spec_path()``). When the spec file is bumped for a
  new release, the expected version updates automatically; no hardcoded version in this test.

- **Endpoint:** ``GET /`` relative to ``STS_BASE_URL`` (no query parameters).

================================================================================
TESTS IN THIS FILE (summary)
================================================================================

**``test_root_returns_ready_with_spec_version``**

- **Passes** if: status is 200, body parses as JSON, ``application`` is ``"STS"``,
  ``status`` is ``"READY"``, and ``version`` equals ``spec_version``.
- **Fails** otherwise with an assertion message naming the path and expected vs actual values.

================================================================================
HOW TO RUN
================================================================================

::

    pytest tests/test_manual/test_root.py -v

Uses ``api_client`` (``STS_BASE_URL``) and ``spec_version`` (bundled spec).
"""


def test_root_returns_ready_with_spec_version(api_client, spec_version):
    response = api_client.get("/")
    assert response.status_code == 200, (
        f"GET /: expected 200, got {response.status_code}"
    )
    data = response.json()
    assert data is not None, "GET /: response body is not JSON"
    response_version = data.get("version")
    print(f"  spec version (expected): {spec_version}")
    print(f"  response version:        {response_version!r}")
    assert data.get("application") == "STS", (
        f"GET /: expected application 'STS', got {data.get('application')!r}"
    )
    assert data.get("status") == "READY", (
        f"GET /: expected status 'READY', got {data.get('status')!r}"
    )
    assert data.get("version") == spec_version, (
        f"GET /: expected version {spec_version!r}, got {data.get('version')!r}"
    )
