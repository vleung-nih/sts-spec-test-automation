"""
Manual EDP listing uniqueness test (``edp_edps_unique`` marker).

================================================================================
WHAT THIS IS (plain English)
================================================================================

``GET /edps/{origin}`` is meant to list the extended definition property (EDP)
defining terms for an authority (e.g. ``caDSR`` for CDEs). Each EDP is identified
by its ``origin_id`` + ``origin_version``. This test asserts the listing contains
each EDP **once** — no unexpected duplicate ``(origin_id, origin_version)`` rows.

MDB term-node uniqueness uses ``(origin_name, origin_id, origin_version, value)``.
Some caDSR defining terms can therefore appear more than once under the listing
key ``(origin_id, origin_version)`` without being redundant under the term-dedup
rule. Those residuals are listed in
``data/edp_edps_unique_cases.json`` → ``allowed_duplicate_edps`` and are ignored
for the pass/fail assertion. Any **new** duplicate not on that allowlist fails.

``CRDC`` has no allowlisted residuals and must stay fully unique by
``(origin_id, origin_version)``.

================================================================================
WHERE THE DATA COMES FROM
================================================================================

- ``data/edp_edps_unique_cases.json`` — ``origins`` plus optional
  ``allowed_duplicate_edps`` keyed by origin.
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

# Cached payload so origins + allowlist load once per session.
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


def _allowed_triples_for_origin(origin: str) -> set[tuple[str, str]]:
    """Return allowlisted (origin_id, origin_version) pairs for an origin."""
    payload = _load_cases_payload()
    by_origin = payload.get("allowed_duplicate_edps") or {}
    entries = by_origin.get(origin) or []
    return {
        (str(e["origin_id"]), str(e["origin_version"]))
        for e in entries
        if isinstance(e, dict) and e.get("origin_id") is not None and e.get("origin_version") is not None
    }


def _edps_list_path(origin_name: str) -> str:
    """Relative v2 path to browse EDP defining terms by authority: /edps/{origin}."""
    return f"/edps/{quote(origin_name, safe='')}"


def _triple(term: dict[str, Any]) -> tuple[str, str]:
    """EDP identity within an origin: (origin_id, origin_version)."""
    return (str(term.get("origin_id")), str(term.get("origin_version")))


def _dup_report(
    dups: dict[tuple[str, str], int],
    values_by_triple: dict[tuple[str, str], Any],
) -> dict[str, dict[str, Any]]:
    """Human-readable duplicate report keyed by origin_id/version."""
    return {
        f"{oid}/{ver}": {"count": c, "value": values_by_triple.get((oid, ver))}
        for (oid, ver), c in sorted(dups.items(), key=lambda kv: -kv[1])
    }


@pytest.mark.edp_edps_unique
@pytest.mark.parametrize("origin", _load_origins(), ids=lambda o: o)
def test_edps_listing_has_no_duplicate_edps(api_client: APIClient, origin: str):
    """
    GET /edps/{origin} must list each EDP (origin_id, origin_version) once,
    except for allowlisted residuals in edp_edps_unique_cases.json.

    Steps:
    1. GET /edps/{origin} (no limit → all defining terms in one response)
    2. Count rows per (origin_id, origin_version) triple
    3. Split duplicates into allowlisted vs unexpected; fail only on unexpected
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
    allowed = _allowed_triples_for_origin(origin)
    allowed_dups = {k: c for k, c in dups.items() if k in allowed}
    unexpected_dups = {k: c for k, c in dups.items() if k not in allowed}
    stale_allowlist = sorted(allowed - set(dups.keys()))

    print(
        f"  rows={len(body)} unique_edps={len(counts)} "
        f"duplicated_edps={len(dups)} allowlisted_dups={len(allowed_dups)} "
        f"unexpected_dups={len(unexpected_dups)}"
    )

    values_by_triple = {
        _triple(t): t.get("value")
        for t in body
        if isinstance(t, dict) and _triple(t) in dups
    }
    if allowed_dups:
        print(
            "  allowlisted duplicates (known residual): "
            f"{json.dumps(_dup_report(allowed_dups, values_by_triple), indent=2)}"
        )
    if stale_allowlist:
        stale_report = [f"{oid}/{ver}" for oid, ver in stale_allowlist]
        print(
            "  WARN stale allowlist entries (no longer duplicated; safe to remove): "
            f"{stale_report}"
        )
        logger.warning(
            "edp_edps_unique %s stale allowlist entries: %s", origin, stale_report
        )

    assert not unexpected_dups, (
        f"/edps/{origin}: {len(body)} rows but only {len(counts)} unique EDP "
        f"(origin_id, origin_version) triples — {len(unexpected_dups)} unexpected "
        f"EDP(s) duplicated (allowlisted residuals excluded).\n"
        f"  unexpected duplicate triple -> {{count, value}}: "
        f"{json.dumps(_dup_report(unexpected_dups, values_by_triple), indent=2)}"
    )

    print(
        f"  PASS {origin}: {len(body)} rows; unexpected duplicates=0 "
        f"(allowlisted={len(allowed_dups)})\n"
    )
    logger.info(
        "PASS edp_edps_unique %s rows=%s unique=%s allowlisted_dups=%s",
        origin,
        len(body),
        len(counts),
        len(allowed_dups),
    )
