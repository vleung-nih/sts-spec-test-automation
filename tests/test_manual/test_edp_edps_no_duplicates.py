"""
Manual EDP listing uniqueness test (``edp_edps_unique`` marker).

================================================================================
WHAT THIS IS (plain English)
================================================================================

``GET /edps/{origin}`` returns EDP defining terms for an authority (e.g. ``caDSR``
for CDEs). This test uses the same uniqueness key as DATATEAM-508 / MDB term
dedup: ``(origin_name, origin_id, origin_version, value)``.

Two listing rows that share only ``origin_id`` + ``origin_version`` but have
different ``value`` (two CDE titles) are **not** duplicates. Rows that match on
all four fields are redundant term nodes and fail.

**CRDC:** must have zero duplicate 4-tuples (strict).

**caDSR:** legacy duplicate term nodes remain on STS until Neo4j cleanup.
DATATEAM-722 / bento-mdb PR 197 prevents new same-key inserts. For caDSR we
compare live duplicate **counts** to a checked-in baseline
(``duplicate_drift_baselines`` in case JSON): fail only on **new** duplicate
4-tuples or **higher** counts than baseline. When cleanup reaches zero dupes,
remove the baseline entry and use strict zero for caDSR again.

================================================================================
WHERE THE DATA COMES FROM
================================================================================

- ``data/edp_edps_unique_cases.json`` — ``origins`` and optional
  ``duplicate_drift_baselines`` per origin.
- Baseline snapshot: ``data/baselines/cadsr_edps_508_duplicate_baseline_2026-10-21.json``.
- STS: session ``api_client`` — ``GET /edps/{origin}`` (no limit → all rows).

================================================================================
HOW TO RUN
================================================================================

::

    pytest tests/test_manual/test_edp_edps_no_duplicates.py -m edp_edps_unique -v

Uses ``STS_BASE_URL`` (default QA). caDSR drift baseline is applied for any
base URL; counts on non-QA tiers may differ from the QA snapshot.
"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

from sts_test_framework.client import APIClient, full_url
from sts_test_framework.config import project_root
from sts_test_framework.edp_edps_drift import compare_dups_to_baseline, load_drift_baseline

logger = logging.getLogger(__name__)

_EDPS_UNIQUE_DATA_FILE = project_root() / "data" / "edp_edps_unique_cases.json"

_DRIFT_POLICY_NOTE = (
    "caDSR: no-drift vs checked-in 508 duplicate baseline (DATATEAM-722 prevent "
    "merged; legacy dupes frozen until graph cleanup). Fail = new 4-tuple or count "
    "increase. CRDC: strict zero duplicates."
)

_CASES_PAYLOAD: dict[str, Any] | None = None


def _load_cases_payload() -> dict[str, Any]:
    """Load uniqueness case JSON; skip the module if missing."""
    global _CASES_PAYLOAD
    if _CASES_PAYLOAD is not None:
        return _CASES_PAYLOAD
    if not _EDPS_UNIQUE_DATA_FILE.is_file():
        pytest.skip(f"Case data file not found: {_EDPS_UNIQUE_DATA_FILE}")
    with open(_EDPS_UNIQUE_DATA_FILE, encoding="utf-8") as f:
        _CASES_PAYLOAD = json.load(f)
    return _CASES_PAYLOAD


def _load_origins() -> list[str]:
    """Load EDP origins to check; skip the module if the JSON file is missing or empty."""
    payload = _load_cases_payload()
    origins = payload.get("origins", [])
    if not origins:
        pytest.skip(f"No origins in {_EDPS_UNIQUE_DATA_FILE}")
    return [str(o) for o in origins]


def _baseline_path_for_origin(origin: str) -> Path | None:
    payload = _load_cases_payload()
    by_origin = payload.get("duplicate_drift_baselines") or {}
    rel = by_origin.get(origin)
    if not rel:
        return None
    return project_root() / str(rel)


def _edps_list_path(origin_name: str) -> str:
    """Relative v2 path to browse EDP defining terms by authority: /edps/{origin}."""
    return f"/edps/{quote(origin_name, safe='')}"


def _term_key(term: dict[str, Any], path_origin: str) -> tuple[str, str, str, str]:
    """DATATEAM-508 uniqueness key: (origin_name, origin_id, origin_version, value)."""
    origin_name = term.get("origin_name")
    if origin_name is None or str(origin_name).strip() == "":
        origin_name = path_origin
    value = term.get("value")
    if value is None:
        value = ""
    return (
        str(origin_name),
        str(term.get("origin_id")),
        str(term.get("origin_version")),
        str(value),
    )


def _dup_report(
    dups: dict[tuple[str, str, str, str], int],
    samples_by_key: dict[tuple[str, str, str, str], list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """Human-readable duplicate report keyed by the 508 4-tuple."""
    report: dict[str, dict[str, Any]] = {}
    for key, count in sorted(dups.items(), key=lambda kv: -kv[1]):
        origin_name, origin_id, origin_version, value = key
        samples = samples_by_key.get(key, [])
        report[f"{origin_name}/{origin_id}/{origin_version}/{value}"] = {
            "count": count,
            "origin_name": origin_name,
            "origin_id": origin_id,
            "origin_version": origin_version,
            "value": value,
            "handles": [s.get("handle") for s in samples[:5]],
            "nanoids": [s.get("nanoid") for s in samples[:5]],
        }
    return report


@pytest.mark.edp_edps_unique
@pytest.mark.parametrize("origin", _load_origins(), ids=lambda o: o)
def test_edps_listing_has_no_duplicate_edps(api_client: APIClient, origin: str):
    """
    GET /edps/{origin} — DATATEAM-508 duplicate check.

    CRDC: no duplicate 4-tuples. caDSR: no drift vs baseline when configured.
    """
    list_path = _edps_list_path(origin)
    list_url = full_url(api_client, list_path)
    baseline_path = _baseline_path_for_origin(origin)
    print(f"\n--- EDP listing uniqueness (DATATEAM-508): {origin} ---")
    print(f"  {_DRIFT_POLICY_NOTE}")
    if baseline_path:
        print(f"  drift baseline: {baseline_path.relative_to(project_root())}")
    print(f"  STS edps GET: {list_url}")
    logger.info("%s origin=%s baseline=%s", _DRIFT_POLICY_NOTE, origin, baseline_path)

    res = api_client.get(list_path)
    print(f"  STS edps HTTP: {res.status_code} in {res.duration:.3f}s")
    assert res.status_code == 200, (
        f"STS edps GET {list_url} expected 200, got {res.status_code}"
    )
    body = res.json()
    assert isinstance(body, list), (
        f"STS edps {list_url}: expected JSON array, got {type(body).__name__}"
    )
    assert body, f"STS edps {list_url}: expected non-empty defining-term list"

    keys = [_term_key(t, origin) for t in body if isinstance(t, dict)]
    counts = Counter(keys)
    dups = {k: c for k, c in counts.items() if c > 1}

    samples_by_key: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for term in body:
        if not isinstance(term, dict):
            continue
        key = _term_key(term, origin)
        if key in dups:
            samples_by_key[key].append(term)

    print(
        f"  rows={len(body)} unique_508_keys={len(counts)} "
        f"duplicated_keys={len(dups)}"
    )

    if baseline_path is None:
        assert not dups, (
            f"/edps/{origin}: {len(body)} rows but only {len(counts)} unique "
            f"(origin_name, origin_id, origin_version, value) keys — "
            f"{len(dups)} DATATEAM-508 duplicate group(s).\n"
            f"  duplicate 4-tuple -> {{count, handles, nanoids}}: "
            f"{json.dumps(_dup_report(dups, samples_by_key), indent=2)}"
        )
        print(f"  PASS {origin}: {len(body)} rows; DATATEAM-508 duplicates=0\n")
        logger.info(
            "PASS edp_edps_unique %s rows=%s unique=%s",
            origin,
            len(body),
            len(counts),
        )
        return

    baseline = load_drift_baseline(baseline_path)
    baseline_groups = baseline["groups"]

    if not dups and baseline_groups:
        print(
            f"  PASS {origin}: all baseline duplicate groups resolved "
            f"({len(baseline_groups)} were in baseline). "
            "Consider removing duplicate_drift_baselines and enabling strict zero.\n"
        )
        logger.info("PASS edp_edps_unique %s all baseline dups resolved", origin)
        return

    result = compare_dups_to_baseline(dups, baseline_groups)
    if result.resolved_keys:
        print(
            f"  cleanup progress: {len(result.resolved_keys)} baseline duplicate "
            f"group(s) no longer duplicated (first 5): {result.resolved_keys[:5]}"
        )
    print(
        f"  PASS {origin} (no drift): duplicate_groups={result.current_duplicate_groups} "
        f"max_count={result.max_count}\n"
    )
    logger.info(
        "PASS edp_edps_unique %s drift_ok groups=%s max_count=%s resolved=%s",
        origin,
        result.current_duplicate_groups,
        result.max_count,
        len(result.resolved_keys),
    )
