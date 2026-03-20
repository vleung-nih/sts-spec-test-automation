"""
Manual tests for GET /terms/model-pvs/{model}/ (all properties with PVS for a model).

Not in bundled OpenAPI as of spec/v2.yaml (only /terms/model-pvs/{model}/{property} is listed).

Behavior verified against live STS:
- Omitting the version query uses the server's latest model version for that model.
- Use query parameter ``version`` (not ``model_version``) to pin a model version; the same
  name is used elsewhere for model-PVS (e.g. property-level routes). Product docs may refer
  to ``model_version``; the deployed API uses ``version``.

Tests are **parametrized** over ``MAJOR_MODELS`` (same handles as
``test_model_pvs_no_duplicates.py``). For each handle, ``model_pvs_pin_context`` loads
``model_version`` as ``versions[0]`` from ``GET /model/{handle}/versions`` (same default as
``discover(..., use_release_version=False)``), cached **once per model** per session — not full
``discover()`` (nodes/properties/terms).

**Console output:** This module prints which endpoints and models are under test. The project
``pyproject.toml`` sets ``pytest -s`` so stdout is shown on pass (override with ``--capture=fd``
if you want to hide it).
"""
import logging
from urllib.parse import quote, urlencode

import pytest

logger = logging.getLogger(__name__)

# Same set as test_model_pvs_no_duplicates.py — major commons / data models on STS.
MAJOR_MODELS = ["C3DC", "CCDI", "CCDI-DCC", "ICDC", "CTDC", "CDS", "PSDC"]


def _full_url(base_url: str, path: str, params: dict | None = None) -> str:
    """Build the same URL shape the client uses, for readable logs (GET only)."""
    u = base_url.rstrip("/") + (path if path.startswith("/") else "/" + path)
    if params:
        u += "?" + urlencode(params)
    return u


def _print_test_header(name: str, api_client, td: dict) -> None:
    """What is being exercised: STS env + per-model pin (first version from /versions)."""
    print("\n" + "=" * 72)
    print(f"  {name}")
    print(f"  STS_BASE_URL (effective): {api_client.base_url}")
    print(f"  model_handle: {td.get('model_handle')!r}")
    print(f"  pin model_version (GET .../versions first element): {td.get('model_version')!r}")
    print("=" * 72)


def _fetch_model_pin_context(api_client, model_handle: str) -> dict:
    """
    Minimal lookup: first version string from GET /model/{handle}/versions.

    Matches discover()'s default when use_release_version is False (versions[0]).
    """
    versions_path = f"/model/{quote(model_handle, safe='')}/versions"
    response = api_client.get(versions_path)
    if response.status_code != 200:
        pytest.skip(
            f"GET {versions_path} returned HTTP {response.status_code} for "
            f"model_handle={model_handle!r}"
        )
    versions = response.json()
    if not isinstance(versions, list) or len(versions) == 0:
        pytest.skip(
            f"Empty or invalid versions for model_handle={model_handle!r}"
        )
    v0 = versions[0]
    if not isinstance(v0, str) or not v0.strip():
        pytest.skip(
            f"First version missing or not a string for model_handle={model_handle!r}"
        )
    return {"model_handle": model_handle, "model_version": v0.strip()}


@pytest.fixture(scope="session")
def model_pvs_pin_context(api_client):
    """
    Session cache: one GET /model/{handle}/versions per MAJOR_MODELS handle (7 calls),
    reused across the three parametrized tests (21 cases).
    """
    cache: dict[str, dict] = {}

    def get_context(model_handle: str) -> dict:
        if model_handle not in cache:
            cache[model_handle] = _fetch_model_pin_context(api_client, model_handle)
        return cache[model_handle]

    return get_context


def _assert_permissible_value(pv: dict) -> None:
    """
    Assert one element inside ``permissibleValues`` matches the expected STS shape.

    Each PV is a dict with at least:
    - ``value``: the canonical string used in the model
    - ``ncit_concept_code``: NCIt code (e.g. C25379)
    - ``synonyms``: list of alternate strings from NCIt

    We only assert when the list is non-empty; empty ``permissibleValues`` is allowed for
    properties that have no enumerated values in that response slice.
    """
    assert isinstance(pv, dict), f"permissible value must be dict, got {type(pv).__name__}"
    assert "value" in pv, "permissible value missing 'value'"
    assert "ncit_concept_code" in pv, "permissible value missing 'ncit_concept_code'"
    assert "synonyms" in pv, "permissible value missing 'synonyms'"
    assert isinstance(pv["synonyms"], list), "synonyms must be a list"


def _assert_item_shape(item: dict) -> None:
    """
    Assert one top-level array element matches the contract for this endpoint.

    Each row describes one property on the model at a given model version:
    - ``model``, ``property``, ``version``: strings identifying model, property handle, and
      resolved model version for that row
    - ``permissibleValues``: list of PV dicts; may be empty if that property has no PVS
      in this view

    For every *non-empty* PV entry we delegate to ``_assert_permissible_value`` so nested
    structure is validated only where the API actually returns PV rows.
    """
    assert isinstance(item, dict), f"item must be dict, got {type(item).__name__}"
    for key in ("model", "property", "version"):
        assert key in item, f"item missing {key!r}"
        assert isinstance(item[key], str), f"{key} must be str"
    assert "permissibleValues" in item, "item missing 'permissibleValues'"
    pvs = item["permissibleValues"]
    assert isinstance(pvs, list), "permissibleValues must be a list"
    for pv in pvs:
        _assert_permissible_value(pv)


@pytest.mark.parametrize("model_handle", MAJOR_MODELS)
def test_model_pvs_by_model_latest(api_client, model_handle, model_pvs_pin_context):
    """
    Happy path with **no** ``version`` query param.

    Requirement: omitting ``version`` should return the **latest** model snapshot. We verify
    that by calling ``GET /model/{handle}/latest-version`` first and asserting every row’s
    ``version`` matches that response’s ``version`` field (in addition to shape checks).
    """
    td = model_pvs_pin_context(model_handle)
    model_handle = td["model_handle"]

    _print_test_header("test_model_pvs_by_model_latest", api_client, td)

    # Ground truth for “latest” from the dedicated model endpoint (same as e.g. get_latest_version
    # fallback in test_model_pvs_no_duplicates.py).
    latest_path = f"/model/{quote(model_handle, safe='')}/latest-version"
    print(f"  GET (latest ground truth): {_full_url(api_client.base_url, latest_path)}")
    logger.info(
        "model-pvs-by-model latest: GET %s",
        _full_url(api_client.base_url, latest_path),
    )
    latest_res = api_client.get(latest_path)
    assert latest_res.status_code == 200, (
        f"GET {latest_path}: expected 200, got {latest_res.status_code}: "
        f"{latest_res.body[:500]!r}"
    )
    lv_data = latest_res.json()
    assert isinstance(lv_data, dict), "latest-version response must be a JSON object"
    lv_ver = lv_data.get("version")
    assert isinstance(lv_ver, str) and lv_ver.strip(), (
        "latest-version must include a non-empty string 'version'"
    )
    expected_latest = lv_ver.strip()
    print(f"  latest-version -> version: {expected_latest!r}")

    path = f"/terms/model-pvs/{quote(model_handle, safe='')}/"
    print(f"  GET (no version query): {_full_url(api_client.base_url, path)}")
    logger.info(
        "model-pvs-by-model latest: GET %s (expect rows version == %s)",
        _full_url(api_client.base_url, path),
        expected_latest,
    )
    response = api_client.get(path)
    # Endpoint must succeed for a real model from MAJOR_MODELS.
    assert response.status_code == 200, (
        f"GET {path}: expected 200, got {response.status_code}: {response.body[:500]!r}"
    )
    data = response.json()
    # Contract: body is a JSON array (not a single object wrapper).
    assert isinstance(data, list), "response must be a JSON array"
    # There should be at least one property row; an empty array would be useless for QA.
    assert len(data) > 0, "expected at least one property row"

    versions_seen = set()
    found_non_empty_pvs = False
    for item in data:
        # Full structural check for every row (expensive but catches drift early).
        _assert_item_shape(item)
        # Rows must refer to the model we asked for (path param echoed in body).
        assert item["model"] == model_handle, (
            f"item.model {item['model']!r} != expected model_handle {model_handle!r}"
        )
        versions_seen.add(item["version"])
        pvs = item.get("permissibleValues") or []
        if len(pvs) > 0:
            found_non_empty_pvs = True

    props_with_pvs = sum(
        1 for item in data if len(item.get("permissibleValues") or []) > 0
    )
    print(
        f"  model-pvs response: {len(data)} property row(s), "
        f"{props_with_pvs} with non-empty permissibleValues, "
        f"version(s) in body: {versions_seen!r}"
    )
    logger.info(
        "model-pvs-by-model latest: rows=%s props_with_pvs=%s versions_seen=%s",
        len(data),
        props_with_pvs,
        versions_seen,
    )

    # Unversioned model-pvs must match the version declared by /model/{handle}/latest-version.
    assert versions_seen == {expected_latest}, (
        "without version query, every row's version should equal latest-version's 'version'; "
        f"expected {expected_latest!r}, got {versions_seen!r}"
    )
    # We need at least one non-empty permissibleValues so _assert_permissible_value ran on
    # real nested objects (not only empty lists).
    assert found_non_empty_pvs, (
        "expected at least one property with non-empty permissibleValues "
        "to validate nested shape"
    )
    print("  PASS: unversioned model-pvs version matches GET .../latest-version")
    logger.info("test_model_pvs_by_model_latest: assertions passed")


@pytest.mark.parametrize("model_handle", MAJOR_MODELS)
def test_model_pvs_by_model_specific_version(api_client, model_handle, model_pvs_pin_context):
    """
    **With** ``version=<discovered model_version>`` query param.

    Requirement: when the client passes an explicit version, every row in the response
    should be for **that** model version (the ``version`` field on each object should match
    the requested query value). This is stronger than the “latest” test: it ties the
    query parameter to the payload.
    """
    td = model_pvs_pin_context(model_handle)
    model_handle = td["model_handle"]
    model_version = td["model_version"]

    _print_test_header("test_model_pvs_by_model_specific_version", api_client, td)

    path = f"/terms/model-pvs/{quote(model_handle, safe='')}/"
    # Note: OpenAPI / STS use the query name ``version``, not ``model_version``.
    params = {"version": model_version}
    print(
        f"  GET (pinned version): {_full_url(api_client.base_url, path, params=params)}"
    )
    print(
        "  Note: query param is ``version``; ``model_version`` is not used by STS for this route."
    )
    logger.info(
        "model-pvs-by-model specific: GET %s",
        _full_url(api_client.base_url, path, params=params),
    )
    response = api_client.get(path, params=params)
    assert response.status_code == 200, (
        f"GET {path}?version=...: expected 200, got {response.status_code}: "
        f"{response.body[:500]!r}"
    )
    data = response.json()
    assert isinstance(data, list), "response must be a JSON array"
    assert len(data) > 0, "expected at least one property row"

    for item in data:
        _assert_item_shape(item)
        assert item["model"] == model_handle
        # Core assertion for “version query pins the snapshot”: body.version == query version.
        assert item["version"] == model_version, (
            f"with version={model_version!r}, item.version was {item['version']!r}"
        )

    print(f"  PASS: {len(data)} row(s), all item.version == query version {model_version!r}")
    logger.info(
        "test_model_pvs_by_model_specific_version: rows=%s version=%s",
        len(data),
        model_version,
    )


@pytest.mark.parametrize("model_handle", MAJOR_MODELS)
def test_model_pvs_by_model_unversioned_matches_explicit_latest_version(
    api_client, model_handle, model_pvs_pin_context
):
    """
    Equivalence: **omit** version vs **pass** ``version=<whatever the unversioned call used>``.

    Steps:
    1. Call without ``version``; read ``version`` from the first row (all rows share it
       per ``test_model_pvs_by_model_latest``).
    2. Call again with ``version`` set to that string.
    3. Responses should be identical (same rows and content), proving “no query param” really
       means “same as passing the latest version explicitly”.

    Rows are sorted by ``property`` before compare so harmless ordering differences between
    two HTTP responses do not fail the test.
    """
    td = model_pvs_pin_context(model_handle)
    model_handle = td["model_handle"]

    _print_test_header(
        "test_model_pvs_by_model_unversioned_matches_explicit_latest_version",
        api_client,
        td,
    )

    path = f"/terms/model-pvs/{quote(model_handle, safe='')}/"
    print(f"  GET (1) unversioned: {_full_url(api_client.base_url, path)}")
    r1 = api_client.get(path)
    assert r1.status_code == 200
    unversioned = r1.json()
    assert isinstance(unversioned, list) and len(unversioned) > 0
    # Infer “latest” from row0 (same string as GET /model/{handle}/latest-version per test_model_pvs_by_model_latest).
    latest_ver = unversioned[0]["version"]
    print(f"  inferred version from row0: {latest_ver!r} ({len(unversioned)} rows)")

    r2 = api_client.get(path, params={"version": latest_ver})
    print(
        f"  GET (2) explicit same version: "
        f"{_full_url(api_client.base_url, path, params={'version': latest_ver})}"
    )
    logger.info(
        "model-pvs-by-model equivalence: compare unversioned vs version=%s",
        latest_ver,
    )
    assert r2.status_code == 200
    explicit = r2.json()
    assert isinstance(explicit, list), "versioned response must be a list"
    # Same number of property rows: omitting vs explicit latest should not drop/add rows.
    assert len(explicit) == len(unversioned), (
        "omitting version vs version=<inferred latest> should return same row count"
    )
    # Sort by property so order differences between calls do not fail the test.
    key = lambda row: (row.get("property") or "", row.get("version") or "")
    su = sorted(unversioned, key=key)
    se = sorted(explicit, key=key)
    for a, b in zip(su, se):
        # Deep equality: each property’s model, version, and permissibleValues match.
        assert a == b, "unversioned payload should match explicit version=<latest from row0>"
    print("  PASS: sorted payloads identical (omit version == version=<latest from row0>)")
    logger.info(
        "test_model_pvs_by_model_unversioned_matches_explicit_latest_version: rows=%s",
        len(unversioned),
    )
