"""
Manual EDP listing uniqueness test (``edp_edps_unique`` marker).

================================================================================
WHAT THIS IS (plain English)
================================================================================

``GET /edps/{origin}`` is meant to list the extended definition property (EDP)
defining terms for an authority (e.g. ``caDSR`` for CDEs). Each EDP is identified
by its ``origin_id`` + ``origin_version``. This test asserts the listing contains
each EDP **once** — no duplicate ``(origin_id, origin_version)`` rows.

The endpoint currently emits one row per underlying ``:term`` node (one per model
property that reuses a CDE), so a single logical EDP can appear many times. As of
this writing ``caDSR`` returns ~648 rows for ~488 unique EDPs (some repeated up to
14x); ``CRDC`` is clean because each CRDC EDP has a single term node today.

So this test is expected to FAIL for caDSR until the API dedups the listing, and
PASS for CRDC. Once the API groups by ``(origin_id, origin_version)`` both pass,
and CRDC stays protected once its EDPs get reused across properties.

================================================================================
WHERE THE DATA COMES FROM
================================================================================

- ``data/edp_edps_unique_cases.json`` — ``{"origins": ["caDSR", "CRDC"]}``.
- STS: session ``api_client`` — ``GET /edps/{origin}`` (no limit → all rows).

================================================================================
HOW TO RUN
================================================================================

::

    pytest tests/test_manual/test_edp_edps_no_duplicates.py -m edp_edps_unique -v

Uses ``STS_BASE_URL`` (default QA).
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any
from urllib.parse import quote

import pytest

from sts_test_framework.client import APIClient, full_url
from sts_test_framework.config import project_root

logger = logging.getLogger(__name__)

_EDPS_UNIQUE_DATA_FILE = project_root() / "data" / "edp_edps_unique_cases.json"


def _load_origins() -> list[str]:
    """Load EDP origins to check; skip the module if the JSON file is missing or empty."""
    if not _EDPS_UNIQUE_DATA_FILE.is_file():
        pytest.skip(f"Case data file not found: {_EDPS_UNIQUE_DATA_FILE}")
    with open(_EDPS_UNIQUE_DATA_FILE, encoding="utf-8") as f:
        payload = json.load(f)
    origins = payload.get("origins", [])
    if not origins:
        pytest.skip(f"No origins in {_EDPS_UNIQUE_DATA_FILE}")
    return [str(o) for o in origins]


def _edps_list_path(origin_name: str) -> str:
    """Relative v2 path to browse EDP defining terms by authority: /edps/{origin}."""
    return f"/edps/{quote(origin_name, safe='')}"


def _triple(term: dict[str, Any]) -> tuple[str, str]:
    """EDP identity within an origin: (origin_id, origin_version)."""
    return (str(term.get("origin_id")), str(term.get("origin_version")))


@pytest.mark.edp_edps_unique
@pytest.mark.parametrize("origin", _load_origins(), ids=lambda o: o)
def test_edps_listing_has_no_duplicate_edps(api_client: APIClient, origin: str):
    """
    GET /edps/{origin} must list each EDP (origin_id, origin_version) exactly once.

    Steps:
    1. GET /edps/{origin} (no limit → all defining terms in one response)
    2. Count rows per (origin_id, origin_version) triple
    3. Assert no triple appears more than once; on failure, report the duplicates
    """
    list_path = _edps_list_path(origin)
    list_url = full_url(api_client, list_path)
    print(f"\n--- EDP listing uniqueness: {origin} ---")
    print(f"  STS edps GET: {list_url}")

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

    triples = [_triple(t) for t in body if isinstance(t, dict)]
    counts = Counter(triples)
    dups = {k: c for k, c in counts.items() if c > 1}
    print(f"  rows={len(body)} unique_edps={len(counts)} duplicated_edps={len(dups)}")

    # A human-readable value label per duplicated triple, to make the report actionable.
    values_by_triple = {
        _triple(t): t.get("value")
        for t in body
        if isinstance(t, dict) and _triple(t) in dups
    }
    dup_report = {
        f"{oid}/{ver}": {"count": c, "value": values_by_triple.get((oid, ver))}
        for (oid, ver), c in sorted(dups.items(), key=lambda kv: -kv[1])
    }

    assert not dups, (
        f"/edps/{origin}: {len(body)} rows but only {len(counts)} unique EDP "
        f"(origin_id, origin_version) triples — {len(dups)} EDP(s) duplicated.\n"
        f"  duplicate triple -> {{count, value}}: {json.dumps(dup_report, indent=2)}"
    )

    print(f"  PASS {origin}: {len(body)} rows all unique by (origin_id, origin_version)\n")
    logger.info("PASS edp_edps_unique %s rows=%s unique=%s", origin, len(body), len(counts))
