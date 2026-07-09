"""
Manual EDP / custom CDE tests (``edp_cadsr_parity`` and ``edp_custom_cde`` markers).

================================================================================
WHAT THIS IS (plain English)
================================================================================

**Generated** EDP tests only check HTTP status and coarse list shape. These **manual**
tests pin real ``origin_name`` / ``origin_id`` / ``origin_version`` triples and assert
**permissible-value label parity** on ``GET /edp/{origin}/{id}/{version}/terms``.

Two families:

1. ``edp_cadsr_parity`` — caDSR EDP PV ``value`` multiset must **equal** v2
   ``GET /terms/cde-pvs/{id}/{version}/pvs`` PV ``value`` multiset (NCIt/synonyms ignored).
2. ``edp_custom_cde`` — non-caDSR origins; PV multiset must match ``expected_pv_values``
   in JSON and/or Enum labels from a vendored YAML property (``yaml_ref``).

================================================================================
WHERE THE DATA COMES FROM
================================================================================

- ``data/edp_cadsr_parity_cases.json`` — pinned caDSR triples (exact ``origin_version``).
- ``data/edp_custom_cde_cases.json`` — pinned custom-authority triples + expected PVs.
- STS: session ``api_client`` — ``GET /edp/.../terms``, optional ``GET /edps/{origin}``,
  and ``GET /terms/cde-pvs/.../pvs`` (caDSR parity only).

================================================================================
HOW TO RUN
================================================================================

::

    pytest tests/test_manual/test_edp_custom_cdes.py -m edp_cadsr_parity -v
    pytest tests/test_manual/test_edp_custom_cdes.py -m edp_custom_cde -v
    pytest tests/test_manual/test_edp_custom_cdes.py -m "edp_cadsr_parity or edp_custom_cde" -v

Uses ``STS_BASE_URL`` (default QA). Version strings are **exact** MDB pins (e.g. ``2.0`` not
``2.00``).
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
import yaml

from sts_test_framework.client import APIClient, full_url
from sts_test_framework.config import project_root

logger = logging.getLogger(__name__)

# Pinned case lists (same pattern as caDSR manual tests under data/*.json).
_CADSR_PARITY_DATA_FILE = project_root() / "data" / "edp_cadsr_parity_cases.json"
_CUSTOM_CDE_DATA_FILE = project_root() / "data" / "edp_custom_cde_cases.json"
# Vendored model YAMLs used when a custom case supplies yaml_ref instead of expected_pv_values.
_YAML_ROOT = project_root() / "data" / "data-models-yaml"


def _load_cadsr_parity_cases() -> list[dict[str, Any]]:
    """Load caDSR EDP-vs-cde-pvs cases; skip the module if the JSON file is missing or empty."""
    if not _CADSR_PARITY_DATA_FILE.is_file():
        pytest.skip(f"Case data file not found: {_CADSR_PARITY_DATA_FILE}")
    with open(_CADSR_PARITY_DATA_FILE, encoding="utf-8") as f:
        payload = json.load(f)
    cases = payload.get("cases", [])
    if not cases:
        pytest.skip(f"No cases in {_CADSR_PARITY_DATA_FILE}")
    return cases


def _load_custom_cde_cases() -> list[dict[str, Any]]:
    """Load non-caDSR EDP cases; skip the module if the JSON file is missing or empty."""
    if not _CUSTOM_CDE_DATA_FILE.is_file():
        pytest.skip(f"Case data file not found: {_CUSTOM_CDE_DATA_FILE}")
    with open(_CUSTOM_CDE_DATA_FILE, encoding="utf-8") as f:
        payload = json.load(f)
    cases = payload.get("cases", [])
    if not cases:
        pytest.skip(f"No cases in {_CUSTOM_CDE_DATA_FILE}")
    return cases


def _case_id(case: dict[str, Any]) -> str:
    """Stable pytest id, e.g. caDSR-7572817-2.0."""
    return f"{case['origin_name']}-{case['origin_id']}-{case.get('origin_version', 'x')}"


def _edp_terms_path(origin_name: str, origin_id: str, origin_version: str) -> str:
    """Relative v2 path for PV lookup: /edp/{origin}/{id}/{version}/terms."""
    return (
        f"/edp/{quote(origin_name, safe='')}/{quote(origin_id, safe='')}/"
        f"{quote(origin_version, safe='')}/terms"
    )


def _edps_list_path(origin_name: str) -> str:
    """Relative v2 path to browse EDP defining terms by authority: /edps/{origin}."""
    return f"/edps/{quote(origin_name, safe='')}"


def _cde_pvs_path(origin_id: str, origin_version: str) -> str:
    """Relative v2 path for legacy caDSR CDE PVs (NCIt-enriched): /terms/cde-pvs/{id}/{ver}/pvs."""
    return (
        f"/terms/cde-pvs/{quote(origin_id, safe='')}/"
        f"{quote(origin_version, safe='')}/pvs"
    )


def _pv_values_from_edp_terms(body: object) -> list[str]:
    """Pull human-readable PV labels from EDP Term[] (uses each item's ``value`` field only)."""
    if not isinstance(body, list):
        return []
    out: list[str] = []
    for item in body:
        if isinstance(item, dict):
            val = item.get("value")
            if val is not None:
                out.append(str(val))
    return out


def _pv_values_from_cde_pvs(body: object) -> list[str]:
    """Pull PV labels from cde-pvs CDEPermissibleValues[] (ignores NCIt codes and synonyms)."""
    if not isinstance(body, list):
        return []
    out: list[str] = []
    for row in body:
        if not isinstance(row, dict):
            continue
        pvs = row.get("permissibleValues")
        if not isinstance(pvs, list):
            continue
        for pv in pvs:
            if isinstance(pv, dict) and pv.get("value") is not None:
                out.append(str(pv["value"]))
    return out


def _enum_values_from_yaml(yaml_file: str, prop_handle: str) -> list[str]:
    """
    Read allowed enum labels for a property from a vendored model YAML.

    Supports a top-level ``Enum:`` list or ``Type.item_type`` / ``Type.Enum`` lists.
    """
    path = _YAML_ROOT / yaml_file
    if not path.is_file():
        pytest.fail(f"yaml_ref file not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        pytest.fail(f"yaml_ref {path}: expected mapping at root")
    prop = data.get(prop_handle)
    if not isinstance(prop, dict):
        pytest.fail(f"yaml_ref {path}: property {prop_handle!r} not found")
    enum_block = prop.get("Enum")
    if enum_block is None:
        item_type = None
        type_spec = prop.get("Type")
        if isinstance(type_spec, dict):
            item_type = type_spec.get("item_type") or type_spec.get("Enum")
        enum_block = item_type
    if not isinstance(enum_block, list):
        pytest.fail(
            f"yaml_ref {path} property {prop_handle!r}: no Enum or Type.item_type list"
        )
    values: list[str] = []
    for entry in enum_block:
        if isinstance(entry, str):
            values.append(entry)
        elif isinstance(entry, dict) and entry.get("Value") is not None:
            values.append(str(entry["Value"]))
    if not values:
        pytest.fail(
            f"yaml_ref {path} property {prop_handle!r}: Enum list yielded no string values"
        )
    return values


def _resolve_expected_pv_values(case: dict[str, Any]) -> list[str]:
    """Custom CDE cases must supply expected_pv_values and/or yaml_ref; fail if neither is usable."""
    pinned = case.get("expected_pv_values")
    if isinstance(pinned, list) and pinned:
        return [str(v) for v in pinned]
    yaml_ref = case.get("yaml_ref")
    if isinstance(yaml_ref, dict):
        yf = yaml_ref.get("file")
        prop = yaml_ref.get("property")
        if yf and prop:
            return _enum_values_from_yaml(str(yf), str(prop))
    pytest.fail(
        f"edp_custom_cde case {_case_id(case)}: set non-empty expected_pv_values "
        "and/or yaml_ref with file + property"
    )


def _assert_no_duplicate_values(values: list[str], label: str) -> None:
    """STS should not return the same PV label twice within one EDP response."""
    counts = Counter(values)
    dups = [v for v, c in counts.items() if c > 1]
    assert not dups, f"{label}: duplicate permissible value strings: {sorted(dups)!r}"


def _assert_edp_listed_in_edps(
    api_client: APIClient,
    origin_name: str,
    origin_id: str,
    origin_version: str,
) -> None:
    """
    Sanity check: the defining EDP term appears in GET /edps/{originName}.

    caDSR has thousands of EDP rows, so we paginate (limit=100) until we find a
    matching origin_id + origin_version or exhaust the listing.
    """
    list_path = _edps_list_path(origin_name)
    list_url = full_url(api_client, list_path)
    page_limit = 100
    skip = 0
    matches: list[dict[str, Any]] = []
    pages = 0
    max_pages = 50
    while pages < max_pages:
        print(f"  STS edps GET: {list_url}?limit={page_limit}&skip={skip}")
        list_res = api_client.get(list_path, params={"limit": page_limit, "skip": skip})
        print(f"  STS edps HTTP: {list_res.status_code} in {list_res.duration:.3f}s (skip={skip})")
        assert list_res.status_code == 200, (
            f"STS edps GET {list_url} expected 200, got {list_res.status_code}"
        )
        listed = list_res.json()
        assert isinstance(listed, list), (
            f"STS edps: expected JSON array, got {type(listed).__name__}"
        )
        if not listed:
            break
        matches = [
            t
            for t in listed
            if isinstance(t, dict)
            and str(t.get("origin_id")) == origin_id
            and str(t.get("origin_version")) == origin_version
        ]
        if matches:
            break
        if len(listed) < page_limit:
            break
        skip += page_limit
        pages += 1
    assert matches, (
        f"STS edps/{origin_name}: no defining term with origin_id={origin_id!r} "
        f"origin_version={origin_version!r} (paginated up to skip={skip})"
    )
    print(f"  edps listing: found {len(matches)} matching defining term(s) (skip={skip})")


@pytest.mark.edp_cadsr_parity
@pytest.mark.parametrize("case", _load_cadsr_parity_cases(), ids=_case_id)
def test_edp_cadsr_parity_matches_cde_pvs(api_client: APIClient, case: dict[str, Any]):
    """
    caDSR regression: EDP and cde-pvs must return the same set of PV labels.

    Steps per JSON case:
    1. GET /edp/caDSR/{id}/{version}/terms — collect Term.value strings
    2. GET /edps/caDSR (paginated) — confirm the CDE is listed as an EDP defining term
    3. GET /terms/cde-pvs/{id}/{version}/pvs — collect permissibleValues[].value strings
    4. Assert both lists match as multisets (order ignored; duplicates counted)

    Version strings must match MDB exactly (e.g. 2.0, not 2.00).
    """
    origin_name = str(case["origin_name"])
    origin_id = str(case["origin_id"])
    origin_version = str(case["origin_version"])
    compare_cde_pvs = case.get("compare_cde_pvs", True)
    case_label = _case_id(case)

    print(f"\n--- EDP caDSR parity vs cde-pvs: {case_label} ---")
    if case.get("description"):
        print(f"  Note: {case['description']}")

    # --- Step 1: fetch PV labels from the new generic EDP endpoint ---
    edp_path = _edp_terms_path(origin_name, origin_id, origin_version)
    edp_url = full_url(api_client, edp_path)
    print(f"  STS edp GET: {edp_url}")
    edp_res = api_client.get(edp_path)
    print(f"  STS edp HTTP: {edp_res.status_code} in {edp_res.duration:.3f}s")
    assert edp_res.status_code == 200, (
        f"STS edp GET {edp_url} expected 200, got {edp_res.status_code}"
    )
    edp_body = edp_res.json()
    assert isinstance(edp_body, list), (
        f"STS edp {edp_url}: expected JSON array, got {type(edp_body).__name__}"
    )
    assert len(edp_body) > 0, f"STS edp {edp_url}: expected non-empty Term[]"

    edp_values = _pv_values_from_edp_terms(edp_body)
    print(f"  EDP permissibleValues count={len(edp_values)} (multiset)")
    _assert_no_duplicate_values(edp_values, "edp")

    # --- Step 2: confirm this CDE appears in the EDP browse/list endpoint ---
    _assert_edp_listed_in_edps(api_client, origin_name, origin_id, origin_version)

    if compare_cde_pvs:
        # --- Step 3: fetch the same PV labels from the older caDSR-specific endpoint ---
        cde_path = _cde_pvs_path(origin_id, origin_version)
        cde_url = full_url(api_client, cde_path)
        print(f"  STS cde-pvs GET: {cde_url}")
        cde_res = api_client.get(cde_path)
        print(f"  STS cde-pvs HTTP: {cde_res.status_code} in {cde_res.duration:.3f}s")
        assert cde_res.status_code == 200, (
            f"STS cde-pvs GET {cde_url} expected 200, got {cde_res.status_code}"
        )
        cde_body = cde_res.json()
        assert isinstance(cde_body, list), (
            f"STS cde-pvs {cde_url}: expected JSON array, got {type(cde_body).__name__}"
        )
        assert len(cde_body) > 0, f"STS cde-pvs {cde_url}: expected non-empty response"
        cde_values = _pv_values_from_cde_pvs(cde_body)
        print(f"  cde-pvs permissibleValues count={len(cde_values)} (multiset)")
        # --- Step 4: PV label multisets must match (NCIt/synonyms are not compared) ---
        assert Counter(edp_values) == Counter(cde_values), (
            f"EDP vs cde-pvs PV value multiset mismatch for {case_label}\n"
            f"  EDP-only: {sorted(set(edp_values) - set(cde_values))!r}\n"
            f"  cde-pvs-only: {sorted(set(cde_values) - set(edp_values))!r}"
        )
        print("  cde-pvs parity: EDP PV multiset == cde-pvs PV multiset OK")

    print(f"  PASS {case_label}\n")
    logger.info("PASS edp_cadsr_parity %s edp_rows=%s", case_label, len(edp_values))


@pytest.mark.edp_custom_cde
@pytest.mark.parametrize("case", _load_custom_cde_cases(), ids=_case_id)
def test_edp_custom_cde_matches_expected(api_client: APIClient, case: dict[str, Any]):
    """
    Custom-authority EDP: PV labels must match pinned expectations (not cde-pvs).

    Steps per JSON case:
    1. Load expected PV labels from expected_pv_values and/or yaml_ref in the case file
    2. GET /edp/{origin}/{id}/{version}/terms — collect Term.value strings
    3. GET /edps/{origin} (paginated) — confirm the custom CDE is listed
    4. Assert EDP multiset equals expected multiset

    origin_name must not be caDSR (use edp_cadsr_parity for those).
    cde-pvs is intentionally not called — it only works for NCI caDSR CDEs.
    """
    origin_name = str(case["origin_name"])
    origin_id = str(case["origin_id"])
    origin_version = str(case["origin_version"])
    case_label = _case_id(case)

    print(f"\n--- EDP custom CDE: {case_label} ---")
    if case.get("description"):
        print(f"  Note: {case['description']}")
    assert origin_name != "caDSR", (
        f"edp_custom_cde case {case_label}: use edp_cadsr_parity for caDSR origins"
    )

    # --- Step 1: load expected PV labels from the case JSON or vendored YAML ---
    expected_values = _resolve_expected_pv_values(case)
    print(f"  Expected PV count={len(expected_values)} (from JSON and/or yaml_ref)")

    # --- Step 2: fetch PV labels from the generic EDP endpoint ---
    edp_path = _edp_terms_path(origin_name, origin_id, origin_version)
    edp_url = full_url(api_client, edp_path)
    print(f"  STS edp GET: {edp_url}")
    edp_res = api_client.get(edp_path)
    print(f"  STS edp HTTP: {edp_res.status_code} in {edp_res.duration:.3f}s")
    assert edp_res.status_code == 200, (
        f"STS edp GET {edp_url} expected 200, got {edp_res.status_code}"
    )
    edp_body = edp_res.json()
    assert isinstance(edp_body, list), (
        f"STS edp {edp_url}: expected JSON array, got {type(edp_body).__name__}"
    )
    assert len(edp_body) > 0, f"STS edp {edp_url}: expected non-empty Term[]"

    edp_values = _pv_values_from_edp_terms(edp_body)
    print(f"  EDP permissibleValues count={len(edp_values)} (multiset)")
    _assert_no_duplicate_values(edp_values, "edp")

    # --- Step 3: confirm the custom CDE is listed under GET /edps/{origin} ---
    _assert_edp_listed_in_edps(api_client, origin_name, origin_id, origin_version)

    # --- Step 4: EDP labels must match the pinned/YAML expected multiset ---
    assert Counter(edp_values) == Counter(expected_values), (
        f"EDP vs expected PV value multiset mismatch for {case_label}\n"
        f"  EDP-only: {sorted(set(edp_values) - set(expected_values))!r}\n"
        f"  expected-only: {sorted(set(expected_values) - set(edp_values))!r}"
    )
    print("  custom CDE: EDP PV multiset == expected multiset OK")
    print(f"  PASS {case_label}\n")
    logger.info(
        "PASS edp_custom_cde %s edp_rows=%s expected_rows=%s",
        case_label,
        len(edp_values),
        len(expected_values),
    )
