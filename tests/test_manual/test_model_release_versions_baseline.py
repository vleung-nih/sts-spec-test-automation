"""
Manual regression: model release versions must not disappear (``model_release_versions`` marker).

================================================================================
WHAT THIS IS (plain English)
================================================================================

STS ``GET /model/{handle}/versions`` returns every published version string for a data
model. Clients and tooling rely on historical **release** versions remaining available
forever. This test guards against accidental removal of older releases.

**Business rule:** For every model handle recorded in the committed baseline, every
**release** version in that baseline must still appear in the live ``/versions``
response. New versions (and new models) are allowed and do not fail the test.

A **release** version is one with no hyphen (e.g. ``2.1.0``). Pre-releases like
``2.1.0-0338852`` are ignored — they may come and go.

================================================================================
WHERE THE DATA COMES FROM
================================================================================

1. **Baseline** — ``data/model_release_versions_baseline.json`` (``models`` map of
   handle → sorted release version strings). Regenerate with::

       python scripts/generate_model_release_versions_baseline.py

2. **Live models list** — ``GET /models/`` (used to detect whole-model disappearance).

3. **Live versions** — ``GET /model/{handle}/versions`` (``skip=0``, ``limit=0``).

================================================================================
TESTS IN THIS FILE (summary)
================================================================================

**``test_model_release_versions_baseline_subset``** (single test)

- Walks every baseline model handle.
- **Passes** if each handle still appears in ``GET /models/`` and
  ``set(baseline) ⊆ set(live_release_versions)`` for each.
- Accumulates all failures and asserts once (so one pytest item covers all models).
- Logs newly added release versions (extras) as info only.

================================================================================
HOW TO RUN
================================================================================

Uses ``api_client`` (``STS_BASE_URL``, default QA)::

    pytest tests/test_manual/test_model_release_versions_baseline.py -m model_release_versions -v

Baseline is environment-sensitive: regenerate when targeting stage/prod.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote

import pytest

from sts_test_framework.client import full_url
from sts_test_framework.config import project_root
from sts_test_framework.discover import _is_release_version

logger = logging.getLogger(__name__)

_BASELINE_FILE = project_root() / "data" / "model_release_versions_baseline.json"


def _load_baseline() -> dict[str, list[str]]:
    """Load handle → release versions from the committed baseline JSON."""
    if not _BASELINE_FILE.is_file():
        pytest.skip(f"Baseline file not found: {_BASELINE_FILE}")
    with open(_BASELINE_FILE, encoding="utf-8") as f:
        payload = json.load(f)
    models = payload.get("models", {})
    if not isinstance(models, dict) or not models:
        pytest.skip(f"No models in {_BASELINE_FILE}")
    out: dict[str, list[str]] = {}
    for handle, versions in models.items():
        if not isinstance(handle, str) or not handle.strip():
            continue
        if not isinstance(versions, list):
            continue
        cleaned = [str(v).strip() for v in versions if isinstance(v, str) and v.strip()]
        out[handle.strip()] = cleaned
    if not out:
        pytest.skip(f"No usable model entries in {_BASELINE_FILE}")
    return out


def _release_versions_from_body(body: object) -> list[str]:
    """Filter a /versions JSON body to release version strings (no hyphen)."""
    if not isinstance(body, list):
        return []
    out: list[str] = []
    for item in body:
        if isinstance(item, str) and item.strip() and _is_release_version(item):
            out.append(item.strip())
    return out


def _handles_from_models(body: object) -> set[str]:
    """Unique model handles from GET /models/."""
    if not isinstance(body, list):
        return set()
    handles: set[str] = set()
    for item in body:
        if isinstance(item, dict):
            handle = item.get("handle")
            if isinstance(handle, str) and handle.strip():
                handles.add(handle.strip())
    return handles


@pytest.mark.model_release_versions
def test_model_release_versions_baseline_subset(api_client):
    """
    Every baseline model and its release versions must still be present live.

    Walks all baseline handles in one pytest item; accumulates failures and asserts once.
    New release versions are logged but do not fail.
    """
    baseline = _load_baseline()

    models_res = api_client.get("/models/")
    assert models_res.status_code == 200, (
        f"GET /models/ failed: HTTP {models_res.status_code} "
        f"({full_url(api_client, '/models/')})"
    )
    live_handles = _handles_from_models(models_res.json())
    assert live_handles, "GET /models/ returned no model handles"

    failures: list[str] = []
    for model_handle, expected in sorted(baseline.items()):
        if model_handle not in live_handles:
            failures.append(
                f"[{model_handle}] missing from GET /models/ "
                f"(live handles: {sorted(live_handles)})"
            )
            continue

        path = f"/model/{quote(model_handle, safe='')}/versions"
        params = {"skip": 0, "limit": 0}
        url = full_url(api_client, path, params)
        print(f"  [{model_handle}] GET {url}")
        response = api_client.get(path, params=params)
        if response.status_code != 200:
            failures.append(f"[{model_handle}] GET {path} failed: HTTP {response.status_code} ({url})")
            continue

        body: Any = response.json()
        if not isinstance(body, list):
            failures.append(f"[{model_handle}] GET {path} must return a JSON array, got {type(body)}")
            continue

        live_releases = _release_versions_from_body(body)
        live_set = set(live_releases)
        expected_set = set(expected)
        baseline_sorted = sorted(expected_set)
        live_sorted = sorted(live_set)
        missing = sorted(expected_set - live_set)
        extras = sorted(live_set - expected_set)

        print(f"  [{model_handle}] baseline: {baseline_sorted}")
        print(f"  [{model_handle}] live:     {live_sorted}")

        if extras:
            msg = f"[{model_handle}] new release version(s) since baseline: {extras}"
            print(f"  {msg}")
            logger.info(msg)

        if missing:
            failures.append(
                f"[{model_handle}] release version(s) missing from live /versions "
                f"(baseline ⊆ live violated): {missing}. "
                f"baseline={baseline_sorted} live_releases={live_sorted}"
            )
            continue

        print(
            f"  [{model_handle}] OK  "
            f"baseline={len(expected_set)} live_releases={len(live_set)} extras={len(extras)}"
        )

    print(
        f"\n--- model_release_versions summary: "
        f"{len(baseline)} model(s), {len(failures)} failed ---"
    )
    assert not failures, (
        f"{len(failures)} of {len(baseline)} baseline model(s) failed "
        f"(release versions must not be removed):\n"
        + "\n".join(f"  - {msg}" for msg in failures)
    )
