"""
Manual caDSR vs STS tests (two families in this module).

================================================================================
1) ``cadsr_alt_pvs`` — Alternate **Designations** must **not** appear in **cde-pvs** / **model-pvs**
================================================================================

For pinned CDE + model + property rows (see ``data/cadsr_alternate_values_cases.json``), we:

1. Load **caDSR** ``GET .../DataElement/{cde_id}`` and collect ``Designations[].name`` (all types
   by default — same idea as the pre-change test). Optionally limit which ``Designations[].type``
   rows are included via ``CADSR_ALTERNATE_DESIGNATION_TYPES`` (comma-separated; unset or ``*`` =
   all types). Then **subtract** every official ``PermissibleValues[].value`` string so names that
   match a canonical PV are not treated as “extra” alternates.
2. Load STS **cde-pvs**, ``GET /terms/cde-pvs/{cde_id}/{cde_version}/pvs``.
3. Load STS **model-pvs**, ``GET /terms/model-pvs/{model}/{property}`` with
   ``version={model_version}``.

For **each** endpoint’s ``permissibleValues`` list we assert:

- No duplicate ``value`` strings (case-sensitive).
- Every caDSR ``PermissibleValues[].value`` (multiset) appears as some row’s ``value`` on STS
  (**all** rows — includes null ``ncit_concept_code`` enumerations, unlike ``cadsr_draft_new``).
- **Jira / DH behavior:** caDSR ``Designations[].name`` strings that are **not** themselves an
  official ``PermissibleValues[].value`` must **not** appear as a top-level ``permissibleValues.value``
  (those used to be extra null-NCIt rows; they are removed from API responses). Names are taken
  only from the caDSR designation tree (optional ``CADSR_ALTERNATE_DESIGNATION_TYPES`` limits
  which ``Designations[].type`` rows are included before subtracting official values).

We **do not** assert on ``synonyms``: STS merges NCIt synonym strings with caDSR text; the same
designation string can legitimately appear under ``synonyms`` while still being forbidden as its
own PV ``value`` row after the change.

::

    pytest tests/test_manual/test_cadsr_alternatevalues_draftnew_cdes.py -m cadsr_alt_pvs -v

================================================================================
2) ``cadsr_draft_new`` — DRAFT NEW CDEs: **cde-pvs** (+ optional **model-pvs** PV subset)
================================================================================

For pinned public IDs (see ``data/cadsr_draft_new_cases.json``), we:

1. Load **caDSR** ``GET .../DataElement/{cde_id}`` (JSON).
2. Assert ``workflowStatus`` is ``DRAFT NEW``.
3. Read ``version`` from the same DataElement and call STS
   ``GET /terms/cde-pvs/{cde_id}/{version}/pvs`` so the check tracks **live** caDSR version
   (``\"1\"`` / ``1`` are normalized to ``\"1.00\"`` so STS returns the same CDE row as the UI).
4. Assert ``longName`` **equals** the first block’s ``CDEFullName`` (exact string match).
5. **Permissible values (cde-pvs):** Only ``PermissibleValues[].value`` from caDSR is used (never
   ``Designations`` — use marker ``cadsr_alt_pvs`` for those). We require **every** caDSR
   ``value`` (with multiplicity) to appear in STS **cde-pvs** on rows where ``ncit_concept_code``
   is **non-null**. Extra STS rows with null ``ncit_concept_code`` are **ignored**.

6. **Optional model-pvs:** If a case includes **all three** of ``model``, ``model_version``, and
   ``property`` (same names as ``cadsr_alternate_values_cases.json``), after cde-pvs we call
   ``GET /terms/model-pvs/{model}/{property}?version={model_version}`` and assert the **same**
   NCIt-row PV multiset subset. Model-pvs responses do **not** include ``CDEFullName``; we do
   **not** assert any title/name match for that endpoint.

::

    pytest tests/test_manual/test_cadsr_alternatevalues_draftnew_cdes.py -m cadsr_draft_new -v

================================================================================
3) ``cadsr_released_cde_pvs`` — RELEASED CDEs: **cde-pvs** PV parity with caDSR
================================================================================

For pinned CDE id + version rows (see ``data/cadsr_released_cde_pv_cases.json``), we:

1. Load **caDSR** ``GET .../DataElement/{cde_id}?version={cde_version}``.
2. Assert ``workflowStatus`` is ``RELEASED``.
3. Assert ``longName`` **equals** STS ``CDEFullName``.
4. Assert caDSR ``PermissibleValues[].value`` multiset **equals** STS **cde-pvs**
   ``permissibleValues[].value`` multiset (**all** rows, not NCIt-only).

Unlike ``cadsr_draft_new`` (subset on NCIt rows), this catches stale STS PVs that caDSR
no longer has — the RELEASED removed-PV regression case.

::

    pytest tests/test_manual/test_cadsr_alternatevalues_draftnew_cdes.py -m cadsr_released_cde_pvs -v

================================================================================
ENVIRONMENT (all caDSR families)
================================================================================

- ``STS_BASE_URL`` — v2 STS root (default QA).
- ``CADSR_BASE_URL`` — caDSR API root (default ``https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api``).
   Paths used: ``/DataElement/{cde_id}``.
- ``CADSR_ALTERNATE_DESIGNATION_TYPES`` — (**``cadsr_alt_pvs`` only**) optional comma-separated
  ``Designations[].type`` filter before subtracting official PV values; unset or ``*`` = include
  **all** designation types (default).
- ``STS_SSL_VERIFY`` — applies to both STS and caDSR clients (same ``APIClient`` behavior).

Console output uses ``print`` (visible with pytest ``-s``; this project sets ``addopts = -v -s``).
Use ``--log-cli-level=INFO`` for duplicate ``logger`` lines.
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from typing import Any, FrozenSet

# Max designation names to print per case (avoid huge stdout).
_DESIGNATION_PREVIEW = 12
from urllib.parse import quote

import pytest

from sts_test_framework.client import APIClient, full_url
from tests.test_manual.conftest import get_cadsr_data_element_with_retry
from sts_test_framework.config import cadsr_base_url, project_root

logger = logging.getLogger(__name__)

_DATA_FILE = project_root() / "data" / "cadsr_alternate_values_cases.json"
_DRAFT_NEW_DATA_FILE = project_root() / "data" / "cadsr_draft_new_cases.json"
_RELEASED_CDE_PV_DATA_FILE = project_root() / "data" / "cadsr_released_cde_pv_cases.json"


def _load_cases() -> list[dict[str, Any]]:
    if not _DATA_FILE.is_file():
        pytest.skip(f"Case data file not found: {_DATA_FILE}")
    with open(_DATA_FILE, encoding="utf-8") as f:
        payload = json.load(f)
    cases = payload.get("cases", [])
    if not cases:
        pytest.skip(f"No cases in {_DATA_FILE}")
    return cases


def _load_draft_new_cases() -> list[dict[str, Any]]:
    if not _DRAFT_NEW_DATA_FILE.is_file():
        pytest.skip(f"Case data file not found: {_DRAFT_NEW_DATA_FILE}")
    with open(_DRAFT_NEW_DATA_FILE, encoding="utf-8") as f:
        payload = json.load(f)
    cases = payload.get("cases", [])
    if not cases:
        pytest.skip(f"No cases in {_DRAFT_NEW_DATA_FILE}")
    return cases


def _load_released_cde_pv_cases() -> list[dict[str, Any]]:
    if not _RELEASED_CDE_PV_DATA_FILE.is_file():
        pytest.skip(f"Case data file not found: {_RELEASED_CDE_PV_DATA_FILE}")
    with open(_RELEASED_CDE_PV_DATA_FILE, encoding="utf-8") as f:
        payload = json.load(f)
    cases = payload.get("cases", [])
    if not cases:
        pytest.skip(f"No cases in {_RELEASED_CDE_PV_DATA_FILE}")
    return cases


def _draft_new_nonempty(case: dict[str, Any], key: str) -> bool:
    v = case.get(key)
    return v is not None and str(v).strip() != ""


def _draft_new_model_pvs_triple(case: dict[str, Any]) -> tuple[str, str, str] | None:
    """
    If ``model``, ``model_version``, and ``property`` are all non-empty, return them as strings.

    If none are set, return ``None``. If only some are set, fail (invalid JSON contract).
    """
    keys = ("model", "model_version", "property")
    flags = [_draft_new_nonempty(case, k) for k in keys]
    if not any(flags):
        return None
    if not all(flags):
        present = [k for k, ok in zip(keys, flags) if ok]
        pytest.fail(
            f"cadsr_draft_new case cde_id={case.get('cde_id')!r}: if any of "
            f"model, model_version, property is set, all three must be non-empty. "
            f"Fields present: {present!r}"
        )
    return (
        str(case["model"]).strip(),
        str(case["model_version"]).strip(),
        str(case["property"]).strip(),
    )


def _permissible_values_from_data_element(de_item: dict[str, Any]) -> list[Any]:
    """PermissibleValues list from DataElement (direct or under ValueDomain)."""
    pvs = de_item.get("PermissibleValues")
    if isinstance(pvs, list):
        return pvs
    vd = de_item.get("ValueDomain")
    if isinstance(vd, dict):
        pvs = vd.get("PermissibleValues")
        if isinstance(pvs, list):
            return pvs
    return []


def _data_element_dict(cadsr_data: dict[str, Any]) -> dict[str, Any] | None:
    """Single DataElement object from caDSR JSON (dict or one-element list)."""
    de = cadsr_data.get("DataElement")
    if isinstance(de, list) and len(de) > 0:
        first = de[0]
        return first if isinstance(first, dict) else None
    if isinstance(de, dict):
        return de
    return None


def _cde_version_for_sts(de_item: dict[str, Any]) -> str:
    """
    Version string for ``/terms/cde-pvs/{id}/{version}/pvs``.

    caDSR often returns ``\"1\"`` or integer ``1``; STS stores CDE versions as **major.minor**
    strings (e.g. ``\"1.00\"``). Calling STS with ``.../1/pvs`` can return **200** with an
    **empty** list or rows **without** ``CDEFullName``; normalizing to ``\"1.00\"`` matches
    the pinned cases in ``data/cadsr_sts_pvs_cases.json`` (``2.00``, ``3.00``, etc.).
    """
    v = de_item.get("version")
    if v is None:
        pytest.fail(
            "caDSR DataElement missing 'version' (required for STS /terms/cde-pvs/.../pvs)"
        )
    if isinstance(v, bool):
        pytest.fail(f"Unexpected boolean 'version' on caDSR DataElement: {v!r}")
    if isinstance(v, (int, float)):
        return f"{float(v):.2f}"
    s = str(v).strip()
    if not s:
        pytest.fail("caDSR DataElement 'version' is empty")
    # Normalize plain integer or simple decimal strings to two fractional digits.
    if re.fullmatch(r"\d+", s):
        return f"{float(s):.2f}"
    if re.fullmatch(r"\d+\.\d{1,2}", s):
        return f"{float(s):.2f}"
    return s


def _cadsr_pv_value_strings(de_item: dict[str, Any]) -> list[str]:
    """``value`` string from each PermissibleValues row (multiset; order not significant)."""
    out: list[str] = []
    for pv in _permissible_values_from_data_element(de_item):
        if not isinstance(pv, dict):
            continue
        val = pv.get("value")
        if val is not None:
            out.append(str(val))
    return out


def _sts_cde_full_name(body: Any) -> str | None:
    """First list element’s ``CDEFullName`` (v2 cde-pvs)."""
    if not isinstance(body, list) or len(body) == 0:
        return None
    first = body[0]
    if not isinstance(first, dict):
        return None
    v = first.get("CDEFullName")
    return str(v) if v is not None else None


def _format_cde_pvs_response_hint(body: Any, max_len: int = 800) -> str:
    """Short debug string when STS cde-pvs body is empty or missing ``CDEFullName``."""
    if not isinstance(body, list):
        return f"body type={type(body).__name__!r} (expected JSON array)"
    if len(body) == 0:
        return "body is [] (empty array — wrong CDE id/version for STS?)"
    first = body[0]
    if not isinstance(first, dict):
        return f"body[0] type={type(first).__name__!r} (expected object)"
    keys = sorted(first.keys())
    raw = json.dumps(body, ensure_ascii=False, default=str)
    if len(raw) > max_len:
        raw = raw[:max_len] + " …"
    return f"body[0] keys={keys!r}; preview={raw}"


def _optional_alternate_designation_types() -> FrozenSet[str] | None:
    """
    Optional comma-separated ``Designations[].type`` filter for ``cadsr_alt_pvs``.

    ``None`` = include names from **all** designation types (unset, empty, or ``*``).
    """
    raw = os.getenv("CADSR_ALTERNATE_DESIGNATION_TYPES", "").strip()
    if not raw or raw == "*":
        return None
    types = frozenset(x.strip() for x in raw.split(",") if x.strip())
    return types if types else None


def _designation_names_from_pv(
    pv: dict[str, Any],
    allowed_types: FrozenSet[str] | None,
) -> list[str]:
    """Designation ``name`` strings from one PV row (root or under ValueMeaning)."""
    names: list[str] = []
    for block in (pv, pv.get("ValueMeaning") if isinstance(pv.get("ValueMeaning"), dict) else None):
        if not isinstance(block, dict):
            continue
        des = block.get("Designations")
        if not isinstance(des, list):
            continue
        for des_item in des:
            if not isinstance(des_item, dict) or des_item.get("name") is None:
                continue
            if allowed_types is not None:
                t = des_item.get("type")
                if t not in allowed_types:
                    continue
            names.append(str(des_item["name"]))
    return names


def _designation_name_type_pairs_unfiltered(cadsr_data: dict[str, Any]) -> list[tuple[str, str | None]]:
    """All ``(name, type)`` from Designations (for logging / type histogram)."""
    pairs: list[tuple[str, str | None]] = []
    if not isinstance(cadsr_data, dict):
        return pairs
    de = cadsr_data.get("DataElement")
    if isinstance(de, list) and len(de) > 0:
        de_item = de[0]
    elif isinstance(de, dict):
        de_item = de
    else:
        return pairs
    if not isinstance(de_item, dict):
        return pairs
    pvs = _permissible_values_from_data_element(de_item)
    for pv in pvs:
        if not isinstance(pv, dict):
            continue
        for block in (
            pv,
            pv.get("ValueMeaning") if isinstance(pv.get("ValueMeaning"), dict) else None,
        ):
            if not isinstance(block, dict):
                continue
            des = block.get("Designations")
            if not isinstance(des, list):
                continue
            for des_item in des:
                if not isinstance(des_item, dict) or des_item.get("name") is None:
                    continue
                t = des_item.get("type")
                t_str = str(t) if t is not None else None
                pairs.append((str(des_item["name"]), t_str))
    return pairs


def _extract_cadsr_designation_names(
    cadsr_data: dict[str, Any],
    allowed_types: FrozenSet[str] | None,
) -> list[str]:
    """
    All ``Designations[].name`` for the DataElement.

    Handles:

    - ``DataElement`` as dict or one-element list (caDSR JSON).
    - ``PermissibleValues`` on the element or under ``ValueDomain`` (REST JSON).
    - ``Designations`` on each PV or under ``PV.ValueMeaning`` (common in JSON API).
    """
    designations: list[str] = []
    if not isinstance(cadsr_data, dict):
        return designations
    de = cadsr_data.get("DataElement")
    if isinstance(de, list) and len(de) > 0:
        de_item = de[0]
    elif isinstance(de, dict):
        de_item = de
    else:
        return designations
    if not isinstance(de_item, dict):
        return designations

    pvs = _permissible_values_from_data_element(de_item)
    for pv in pvs:
        if not isinstance(pv, dict):
            continue
        designations.extend(_designation_names_from_pv(pv, allowed_types))
    return designations


def _sts_permissible_values_from_list_body(body: Any) -> list[dict[str, Any]]:
    """First list element’s ``permissibleValues`` (cde-pvs / model-pvs shape)."""
    if not isinstance(body, list) or len(body) == 0:
        return []
    first = body[0]
    if not isinstance(first, dict):
        return []
    pvs = first.get("permissibleValues", [])
    return pvs if isinstance(pvs, list) else []


def _pv_values_list(pvs: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for pv in pvs:
        if not isinstance(pv, dict):
            continue
        v = pv.get("value")
        if v is not None:
            out.append(str(v))
    return out


def _ncit_concept_code_non_null(pv: dict[str, Any]) -> bool:
    """True if STS row has a usable NCIt code (non-null; non-empty string)."""
    n = pv.get("ncit_concept_code")
    if n is None:
        return False
    if isinstance(n, str) and not n.strip():
        return False
    return True


def _pv_values_list_ncit_rows_only(pvs: list[dict[str, Any]]) -> list[str]:
    """
    ``value`` from ``permissibleValues`` rows whose ``ncit_concept_code`` is set.

    Rows with null/empty ``ncit_concept_code`` are excluded so alternate/legacy value strings
    do not affect the DRAFT NEW / official-PV subset checks.
    """
    out: list[str] = []
    for pv in pvs:
        if not isinstance(pv, dict):
            continue
        if not _ncit_concept_code_non_null(pv):
            continue
        v = pv.get("value")
        if v is not None:
            out.append(str(v))
    return out


def _assert_cadsr_subset_sts_all_pv_values(
    c_c: Counter,
    s_all: Counter,
    case_label: str,
    sts_endpoint_label: str = "cde-pvs",
) -> None:
    """
    Multiset subset: every caDSR ``PermissibleValues[].value`` must appear on STS as some row’s
    ``value`` (all rows, including null ``ncit_concept_code``).
    """
    if c_c <= s_all:
        return
    deficit = c_c - s_all
    print(
        f"  PV subset fail ({case_label}, {sts_endpoint_label}): caDSR values not matched on "
        f"STS permissibleValues rows — missing (with counts): {dict(deficit)!r}"
    )
    print(f"  STS {sts_endpoint_label} (all `value` rows) Counter={dict(s_all)!r}")
    assert False, (
        f"{case_label}: each caDSR PermissibleValues.value must appear on STS {sts_endpoint_label} "
        f"as some permissibleValues.value; missing multiset: {dict(deficit)!r}"
    )


def _normalize_pinned_cde_version(version: Any) -> str:
    """Normalize pinned ``cde_version`` from case JSON for STS/caDSR URLs."""
    if version is None:
        pytest.fail("RELEASED case missing required 'cde_version'")
    if isinstance(version, bool):
        pytest.fail(f"Unexpected boolean cde_version: {version!r}")
    if isinstance(version, (int, float)):
        return f"{float(version):.2f}"
    s = str(version).strip()
    if not s:
        pytest.fail("RELEASED case 'cde_version' is empty")
    if re.fullmatch(r"\d+", s):
        return f"{float(s):.2f}"
    if re.fullmatch(r"\d+\.\d{1,2}", s):
        return f"{float(s):.2f}"
    return s


def _assert_cadsr_sts_pv_parity(
    c_c: Counter,
    s_all: Counter,
    case_label: str,
    sts_endpoint_label: str = "cde-pvs",
) -> None:
    """
    Multiset equality: caDSR official PV values must match STS all-row PV values.

    Catches stale STS values absent from caDSR (removed-PV regression) as well as
    missing STS values.
    """
    if c_c == s_all:
        return
    only_cadsr = c_c - s_all
    only_sts = s_all - c_c
    print(
        f"  PV parity fail ({case_label}, {sts_endpoint_label}): "
        f"only in caDSR={dict(only_cadsr)!r}; only in STS={dict(only_sts)!r}"
    )
    print(f"  caDSR Counter={dict(c_c)!r}")
    print(f"  STS {sts_endpoint_label} (all rows) Counter={dict(s_all)!r}")
    assert False, (
        f"{case_label}: caDSR PermissibleValues.value multiset must equal STS "
        f"{sts_endpoint_label} permissibleValues.value multiset; "
        f"only in caDSR={dict(only_cadsr)!r}; only in STS={dict(only_sts)!r}"
    )


def _assert_cadsr_subset_sts_ncit(
    c_c: Counter,
    s_ncit: Counter,
    case_label: str,
    sts_endpoint_label: str = "cde-pvs",
) -> None:
    """
    Multiset subset: every caDSR ``value`` count must be covered by STS **NCIt-coded** rows.

    ``Counter`` supports ``<=`` for multiset inclusion (Python 3).
    """
    if c_c <= s_ncit:
        return
    deficit = c_c - s_ncit
    print(
        f"  PV subset fail ({case_label}, {sts_endpoint_label}): caDSR values not matched on "
        f"STS rows with non-null ncit_concept_code — missing (with counts): {dict(deficit)!r}"
    )
    print(f"  STS {sts_endpoint_label} (NCIt rows only) Counter={dict(s_ncit)!r}")
    assert False, (
        f"{case_label}: each caDSR PermissibleValues.value must appear on STS {sts_endpoint_label} "
        f"rows with non-null ncit_concept_code; missing multiset: {dict(deficit)!r}"
    )


def _draft_new_log_sts_pv_rows_and_ncit_counter(
    pvs_rows: list[dict[str, Any]],
    sts_endpoint_label: str,
) -> tuple[int, Counter]:
    """
    Print STS PV multisets (all rows vs NCIt-only) for draft-new checks.

    Returns ``(count of rows with non-null ncit_concept_code, Counter of values on those rows)``.
    """
    sts_pv_vals_all = _pv_values_list(pvs_rows)
    sts_pv_vals_ncit = _pv_values_list_ncit_rows_only(pvs_rows)
    n_ncit_rows = sum(
        1
        for row in pvs_rows
        if isinstance(row, dict) and _ncit_concept_code_non_null(row)
    )
    print(
        f"  STS [{sts_endpoint_label}] permissibleValues rows: total={len(pvs_rows)}, "
        f"with non-null ncit_concept_code={n_ncit_rows}"
    )
    print(
        f"  STS [{sts_endpoint_label}] `value` multiset (all rows): count={len(sts_pv_vals_all)} "
        f"Counter={dict(Counter(sts_pv_vals_all))}"
    )
    print(
        f"  STS [{sts_endpoint_label}] `value` multiset (NCIt-coded rows only): "
        f"count={len(sts_pv_vals_ncit)} Counter={dict(Counter(sts_pv_vals_ncit))}"
    )
    return n_ncit_rows, Counter(sts_pv_vals_ncit)


def _assert_no_duplicate_values(pvs: list[dict[str, Any]], endpoint_label: str) -> None:
    values = _pv_values_list(pvs)
    counts = Counter(values)
    dups = {k: c for k, c in counts.items() if c > 1}
    assert not dups, (
        f"{endpoint_label}: duplicate permissibleValues.value (case-sensitive): {dups!r}"
    )


def _assert_alternate_designations_absent_as_pv_values(
    forbidden_names: set[str],
    sts_values: set[str],
    endpoint_label: str,
) -> None:
    """
    caDSR-only designation strings (not an official ``PermissibleValues[].value``) must not
    appear as their own ``permissibleValues.value`` row (post-Jira: no duplicate null-NCIt clutter).
    """
    if not forbidden_names:
        return
    bad_v = forbidden_names & sts_values
    if bad_v:
        print(
            f"  {endpoint_label}: designation-derived name(s) must not appear as PV value: "
            f"{sorted(bad_v)!r}"
        )
        logger.warning(
            "%s: designation strings leaked as permissibleValues.value: %r",
            endpoint_label,
            sorted(bad_v),
        )
    assert not bad_v, (
        f"{endpoint_label}: caDSR designation name(s) (non-official PV strings) must not appear "
        f"as permissibleValues.value: {sorted(bad_v)!r}"
    )


@pytest.fixture(scope="session")
def cadsr_api_client():
    """HTTP client against ``CADSR_BASE_URL`` (``/DataElement/...``)."""
    return APIClient(cadsr_base_url())


def _case_id(case: dict[str, Any]) -> str:
    return f"{case['cde_id']}-{case.get('property', 'x')}"


def _draft_case_id(case: dict[str, Any]) -> str:
    return str(case["cde_id"])


def _released_cde_pv_case_id(case: dict[str, Any]) -> str:
    return f"{case['cde_id']}-{case.get('cde_version', 'x')}"


@pytest.mark.cadsr_alt_pvs
@pytest.mark.parametrize("case", _load_cases(), ids=_case_id)
def test_cadsr_alternate_designations_absent_from_sts_pvs(
    api_client: APIClient,
    cadsr_api_client: APIClient,
    case: dict[str, Any],
):
    designation_type_filter = _optional_alternate_designation_types()
    cde_id = str(case["cde_id"])
    cde_version = str(case["cde_version"])
    model = str(case["model"])
    model_version = str(case["model_version"])
    prop = str(case["property"])
    case_label = _case_id(case)

    print(f"\n--- caDSR alternate Designations absent from STS PVS: {case_label} ---")
    print(
        f"  Pinned case: CDE {cde_id} @ {cde_version} | "
        f"model {model} @ {model_version} | property {prop!r}"
    )
    if designation_type_filter is None:
        print("  Designation type filter: all types (CADSR_ALTERNATE_DESIGNATION_TYPES unset or *)")
    else:
        print(
            f"  Designation type filter (CADSR_ALTERNATE_DESIGNATION_TYPES): "
            f"{sorted(designation_type_filter)!r}"
        )
    if case.get("description"):
        print(f"  Note: {case['description']}")

    cadsr_path = f"/DataElement/{quote(cde_id, safe='')}"
    cadsr_url = full_url(cadsr_api_client, cadsr_path)
    print(f"  caDSR GET: {cadsr_url}")
    cadsr_res = get_cadsr_data_element_with_retry(cadsr_api_client, cadsr_path)
    print(
        f"  caDSR HTTP: {cadsr_res.status_code} in {cadsr_res.duration:.3f}s"
    )
    assert cadsr_res.status_code == 200, (
        f"caDSR GET {cadsr_url} expected 200, got {cadsr_res.status_code}"
    )
    cadsr_json = cadsr_res.json()
    assert isinstance(cadsr_json, dict), (
        f"caDSR {cadsr_url}: expected JSON object, got {type(cadsr_json).__name__}. "
        "HTML responses are not supported for Designations extraction."
    )

    de_item = _data_element_dict(cadsr_json)
    assert de_item is not None, (
        f"caDSR {cadsr_url}: expected DataElement object or one-element list"
    )
    c_c = Counter(_cadsr_pv_value_strings(de_item))

    all_pairs = _designation_name_type_pairs_unfiltered(cadsr_json)
    type_hist = Counter(t for _, t in all_pairs)
    print(
        f"  caDSR (unfiltered): {len(all_pairs)} designation row(s); "
        f"by type: {dict(type_hist)}"
    )

    designation_names = _extract_cadsr_designation_names(
        cadsr_json, designation_type_filter
    )
    official_value_strings = set(_cadsr_pv_value_strings(de_item))
    forbidden_names = set(designation_names) - official_value_strings
    print(
        f"  Designation names (after type filter): {len(designation_names)} occurrence(s), "
        f"{len(set(designation_names))} unique; official PV value strings: "
        f"{len(official_value_strings)}; non-official (must not appear in STS): "
        f"{len(forbidden_names)}"
    )
    if forbidden_names:
        preview = sorted(forbidden_names)[:_DESIGNATION_PREVIEW]
        more = len(forbidden_names) - len(preview)
        extra = f" … (+{more} more)" if more > 0 else ""
        print(f"  Non-official designation names (sample): {preview!r}{extra}")
    logger.info(
        "Case %s: designation_type_filter=%s occurrences=%s forbidden_unique=%s",
        case_label,
        None if designation_type_filter is None else sorted(designation_type_filter),
        len(designation_names),
        len(forbidden_names),
    )

    # --- cde-pvs ---
    cde_path = (
        f"/terms/cde-pvs/{quote(cde_id, safe='')}/{quote(cde_version, safe='')}/pvs"
    )
    cde_url = full_url(api_client, cde_path)
    print(f"  STS cde-pvs GET: {cde_url}")
    cde_res = api_client.get(cde_path)
    print(
        f"  STS cde-pvs HTTP: {cde_res.status_code} in {cde_res.duration:.3f}s"
    )
    assert cde_res.status_code == 200, (
        f"STS cde-pvs GET {cde_url} expected 200, got {cde_res.status_code}"
    )
    cde_body = cde_res.json()
    cde_pvs = _sts_permissible_values_from_list_body(cde_body)
    alt_note = (
        f"non-official designation names absent as PV value ({len(forbidden_names)} name(s))"
        if forbidden_names
        else "no non-official designation names (absence check skipped)"
    )
    print(
        f"  Verify cde-pvs: {len(cde_pvs)} permissibleValues row(s); "
        f"no duplicate value (case-sensitive); official PV multiset ⊆ all STS values; {alt_note}"
    )
    _assert_no_duplicate_values(cde_pvs, "cde-pvs")
    print("  cde-pvs: duplicate-value check OK")
    _draft_new_log_sts_pv_rows_and_ncit_counter(cde_pvs, "cde-pvs")
    s_all_cde = Counter(_pv_values_list(cde_pvs))
    _assert_cadsr_subset_sts_all_pv_values(c_c, s_all_cde, case_label, "cde-pvs")
    print("  cde-pvs: official PermissibleValues multiset ⊆ STS all value rows OK")
    cde_value_set = set(_pv_values_list(cde_pvs))
    if forbidden_names:
        _assert_alternate_designations_absent_as_pv_values(
            forbidden_names, cde_value_set, "cde-pvs"
        )
        print("  cde-pvs: non-official designation names not as PV value OK")

    # --- model-pvs ---
    mp_path = (
        f"/terms/model-pvs/{quote(model, safe='')}/{quote(prop, safe='')}"
    )
    mp_url = full_url(api_client, mp_path, {"version": model_version})
    print(f"  STS model-pvs GET: {mp_url}")
    mp_res = api_client.get(mp_path, params={"version": model_version})
    print(
        f"  STS model-pvs HTTP: {mp_res.status_code} in {mp_res.duration:.3f}s"
    )
    assert mp_res.status_code == 200, (
        f"STS model-pvs GET {mp_url} expected 200, got {mp_res.status_code}"
    )
    mp_body = mp_res.json()
    mp_pvs = _sts_permissible_values_from_list_body(mp_body)
    print(
        f"  Verify model-pvs: {len(mp_pvs)} permissibleValues row(s); "
        f"no duplicate value (case-sensitive); official PV multiset ⊆ all STS values; {alt_note}"
    )
    _assert_no_duplicate_values(mp_pvs, "model-pvs")
    print("  model-pvs: duplicate-value check OK")
    _draft_new_log_sts_pv_rows_and_ncit_counter(mp_pvs, "model-pvs")
    s_all_mp = Counter(_pv_values_list(mp_pvs))
    _assert_cadsr_subset_sts_all_pv_values(c_c, s_all_mp, case_label, "model-pvs")
    print("  model-pvs: official PermissibleValues multiset ⊆ STS all value rows OK")
    mp_value_set = set(_pv_values_list(mp_pvs))
    if forbidden_names:
        _assert_alternate_designations_absent_as_pv_values(
            forbidden_names, mp_value_set, "model-pvs"
        )
        print("  model-pvs: non-official designation names not as PV value OK")

    print(
        f"  PASS {case_label}: "
        f"non-official designation names checked={len(forbidden_names)} | "
        f"cde-pvs rows={len(cde_pvs)} | model-pvs rows={len(mp_pvs)}\n"
    )
    logger.info(
        "PASS %s: forbidden_names=%s cde_pvs_rows=%s model_pvs_rows=%s",
        case_label,
        len(forbidden_names),
        len(cde_pvs),
        len(mp_pvs),
    )


@pytest.mark.cadsr_draft_new
@pytest.mark.parametrize("case", _load_draft_new_cases(), ids=_draft_case_id)
def test_cadsr_draft_new_matches_sts_cde_pvs(
    api_client: APIClient,
    cadsr_api_client: APIClient,
    case: dict[str, Any],
):
    cde_id = str(case["cde_id"])
    case_label = _draft_case_id(case)

    print(f"\n--- caDSR DRAFT NEW vs STS cde-pvs: {case_label} ---")
    if case.get("description"):
        print(f"  Note: {case['description']}")

    model_pvs_binding = _draft_new_model_pvs_triple(case)
    if model_pvs_binding is not None:
        _m, _mv, _p = model_pvs_binding
        print(
            f"  Optional model-pvs: model={_m!r} version={_mv!r} property={_p!r} "
            "(PV subset on NCIt rows only, after cde-pvs)"
        )

    cadsr_path = f"/DataElement/{quote(cde_id, safe='')}"
    cadsr_url = full_url(cadsr_api_client, cadsr_path)
    print(f"  caDSR GET: {cadsr_url}")
    cadsr_res = get_cadsr_data_element_with_retry(cadsr_api_client, cadsr_path)
    print(
        f"  caDSR HTTP: {cadsr_res.status_code} in {cadsr_res.duration:.3f}s"
    )
    assert cadsr_res.status_code == 200, (
        f"caDSR GET {cadsr_url} expected 200, got {cadsr_res.status_code}"
    )
    cadsr_json = cadsr_res.json()
    assert isinstance(cadsr_json, dict), (
        f"caDSR {cadsr_url}: expected JSON object, got {type(cadsr_json).__name__}."
    )

    de_item = _data_element_dict(cadsr_json)
    assert de_item is not None, (
        f"caDSR {cadsr_url}: expected DataElement object or one-element list"
    )

    wf = de_item.get("workflowStatus")
    wf_str = str(wf).strip() if wf is not None else None
    print(f"  caDSR workflowStatus: {wf_str!r}")
    assert wf_str == "DRAFT NEW", (
        f"caDSR CDE {cde_id}: expected workflowStatus 'DRAFT NEW', got {wf!r} "
        "(remove from data/cadsr_draft_new_cases.json if this CDE is no longer DRAFT NEW)"
    )

    cde_version = _cde_version_for_sts(de_item)
    print(f"  caDSR version (for STS URL): {cde_version!r}")

    long_name = de_item.get("longName")
    assert long_name is not None, f"caDSR CDE {cde_id}: DataElement missing longName"
    cadsr_long = str(long_name)
    print(f"  caDSR longName: {cadsr_long!r}")

    cadsr_pv_vals = _cadsr_pv_value_strings(de_item)
    print(
        f"  caDSR PermissibleValues `value` count={len(cadsr_pv_vals)} "
        f"(multiset; Counter={dict(Counter(cadsr_pv_vals))})"
    )

    cde_path = (
        f"/terms/cde-pvs/{quote(cde_id, safe='')}/{quote(cde_version, safe='')}/pvs"
    )
    cde_url = full_url(api_client, cde_path)
    print(f"  STS cde-pvs GET: {cde_url}")
    cde_res = api_client.get(cde_path)
    print(
        f"  STS cde-pvs HTTP: {cde_res.status_code} in {cde_res.duration:.3f}s"
    )
    assert cde_res.status_code == 200, (
        f"STS cde-pvs GET {cde_url} expected 200, got {cde_res.status_code}"
    )
    cde_body = cde_res.json()
    sts_full = _sts_cde_full_name(cde_body)
    if sts_full is None:
        print(f"  DEBUG STS cde-pvs (no CDEFullName on first row): {_format_cde_pvs_response_hint(cde_body)}")
    assert sts_full is not None, (
        "STS cde-pvs: expected non-empty array with first object containing non-null CDEFullName. "
        f"{_format_cde_pvs_response_hint(cde_body)}"
    )
    print(f"  STS CDEFullName: {sts_full!r}")

    assert sts_full == cadsr_long, (
        f"CDEFullName mismatch: STS {sts_full!r} != caDSR longName {cadsr_long!r}"
    )

    cde_pvs = _sts_permissible_values_from_list_body(cde_body)
    c_c = Counter(cadsr_pv_vals)
    n_ncit_cde, s_ncit_cde = _draft_new_log_sts_pv_rows_and_ncit_counter(
        cde_pvs, "cde-pvs"
    )
    _assert_cadsr_subset_sts_ncit(c_c, s_ncit_cde, case_label, "cde-pvs")

    n_ncit_mp: int | None = None
    mp_rows = 0
    if model_pvs_binding is not None:
        model, model_version, prop = model_pvs_binding
        mp_path = (
            f"/terms/model-pvs/{quote(model, safe='')}/{quote(prop, safe='')}"
        )
        mp_url = full_url(api_client, mp_path, {"version": model_version})
        print(f"  STS model-pvs GET: {mp_url}")
        mp_res = api_client.get(mp_path, params={"version": model_version})
        print(
            f"  STS model-pvs HTTP: {mp_res.status_code} in {mp_res.duration:.3f}s"
        )
        assert mp_res.status_code == 200, (
            f"STS model-pvs GET {mp_url} expected 200, got {mp_res.status_code}"
        )
        mp_body = mp_res.json()
        mp_pvs = _sts_permissible_values_from_list_body(mp_body)
        mp_rows = len(mp_pvs)
        n_ncit_mp, s_ncit_mp = _draft_new_log_sts_pv_rows_and_ncit_counter(
            mp_pvs, "model-pvs"
        )
        _assert_cadsr_subset_sts_ncit(c_c, s_ncit_mp, case_label, "model-pvs")

    if model_pvs_binding is not None:
        print(
            f"  PASS {case_label}: longName/CDEFullName OK; caDSR PV ⊆ STS cde-pvs "
            f"and model-pvs (NCIt rows); cde-pvs rows={len(cde_pvs)}, "
            f"model-pvs rows={mp_rows}\n"
        )
        logger.info(
            "PASS draft_new %s: cde_pvs_rows=%s cde_ncit_rows=%s "
            "model_pvs_rows=%s model_pvs_ncit_rows=%s",
            case_label,
            len(cde_pvs),
            n_ncit_cde,
            mp_rows,
            n_ncit_mp,
        )
    else:
        print(
            f"  PASS {case_label}: longName/CDEFullName OK; caDSR PV values ⊆ STS "
            f"(NCIt-coded rows); cde-pvs rows={len(cde_pvs)}\n"
        )
        logger.info(
            "PASS draft_new %s: cde_pvs_rows=%s ncit_rows=%s",
            case_label,
            len(cde_pvs),
            n_ncit_cde,
        )


@pytest.mark.cadsr_released_cde_pvs
@pytest.mark.parametrize("case", _load_released_cde_pv_cases(), ids=_released_cde_pv_case_id)
def test_cadsr_released_cde_pvs_matches_sts(
    api_client: APIClient,
    cadsr_api_client: APIClient,
    case: dict[str, Any],
):
    cde_id = str(case["cde_id"])
    cde_version = _normalize_pinned_cde_version(case.get("cde_version"))
    case_label = _released_cde_pv_case_id(case)

    print(f"\n--- caDSR RELEASED vs STS cde-pvs parity: {case_label} ---")
    if case.get("description"):
        print(f"  Note: {case['description']}")
    print(f"  Pinned CDE {cde_id} @ {cde_version}")

    cadsr_path = (
        f"/DataElement/{quote(cde_id, safe='')}?version={quote(cde_version, safe='')}"
    )
    cadsr_url = full_url(cadsr_api_client, cadsr_path)
    print(f"  caDSR GET: {cadsr_url}")
    cadsr_res = get_cadsr_data_element_with_retry(cadsr_api_client, cadsr_path)
    print(
        f"  caDSR HTTP: {cadsr_res.status_code} in {cadsr_res.duration:.3f}s"
    )
    assert cadsr_res.status_code == 200, (
        f"caDSR GET {cadsr_url} expected 200, got {cadsr_res.status_code}"
    )
    cadsr_json = cadsr_res.json()
    assert isinstance(cadsr_json, dict), (
        f"caDSR {cadsr_url}: expected JSON object, got {type(cadsr_json).__name__}."
    )

    de_item = _data_element_dict(cadsr_json)
    assert de_item is not None, (
        f"caDSR {cadsr_url}: expected DataElement object or one-element list"
    )

    wf = de_item.get("workflowStatus")
    wf_str = str(wf).strip() if wf is not None else None
    print(f"  caDSR workflowStatus: {wf_str!r}")
    assert wf_str == "RELEASED", (
        f"caDSR CDE {cde_id}: expected workflowStatus 'RELEASED', got {wf!r} "
        "(remove from data/cadsr_released_cde_pv_cases.json if status changed)"
    )

    long_name = de_item.get("longName")
    assert long_name is not None, f"caDSR CDE {cde_id}: DataElement missing longName"
    cadsr_long = str(long_name)
    print(f"  caDSR longName: {cadsr_long!r}")

    cadsr_pv_vals = _cadsr_pv_value_strings(de_item)
    print(
        f"  caDSR PermissibleValues `value` count={len(cadsr_pv_vals)} "
        f"(multiset; Counter={dict(Counter(cadsr_pv_vals))})"
    )

    cde_path = (
        f"/terms/cde-pvs/{quote(cde_id, safe='')}/{quote(cde_version, safe='')}/pvs"
    )
    cde_url = full_url(api_client, cde_path)
    print(f"  STS cde-pvs GET: {cde_url}")
    cde_res = api_client.get(cde_path)
    print(
        f"  STS cde-pvs HTTP: {cde_res.status_code} in {cde_res.duration:.3f}s"
    )
    assert cde_res.status_code == 200, (
        f"STS cde-pvs GET {cde_url} expected 200, got {cde_res.status_code}"
    )
    cde_body = cde_res.json()
    sts_full = _sts_cde_full_name(cde_body)
    if sts_full is None:
        print(
            f"  DEBUG STS cde-pvs (no CDEFullName on first row): "
            f"{_format_cde_pvs_response_hint(cde_body)}"
        )
    assert sts_full is not None, (
        "STS cde-pvs: expected non-empty array with first object containing non-null "
        f"CDEFullName. {_format_cde_pvs_response_hint(cde_body)}"
    )
    print(f"  STS CDEFullName: {sts_full!r}")
    assert sts_full == cadsr_long, (
        f"CDEFullName mismatch: STS {sts_full!r} != caDSR longName {cadsr_long!r}"
    )

    cde_pvs = _sts_permissible_values_from_list_body(cde_body)
    c_c = Counter(cadsr_pv_vals)
    s_all = Counter(_pv_values_list(cde_pvs))
    print(
        f"  STS cde-pvs permissibleValues rows={len(cde_pvs)}; "
        f"all-row Counter={dict(s_all)}"
    )
    _assert_no_duplicate_values(cde_pvs, "cde-pvs")
    _assert_cadsr_sts_pv_parity(c_c, s_all, case_label, "cde-pvs")

    print(
        f"  PASS {case_label}: RELEASED status OK; longName/CDEFullName OK; "
        f"caDSR PV multiset == STS cde-pvs (all rows); rows={len(cde_pvs)}\n"
    )
    logger.info(
        "PASS released_cde_pvs %s: cde_pvs_rows=%s cadsr_pv_count=%s",
        case_label,
        len(cde_pvs),
        len(cadsr_pv_vals),
    )
