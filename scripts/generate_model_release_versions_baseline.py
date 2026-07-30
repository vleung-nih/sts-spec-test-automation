#!/usr/bin/env python3
"""
Collect release versions for every STS model and write a baseline JSON snapshot.

Usage (from project root):
    python scripts/generate_model_release_versions_baseline.py
    STS_BASE_URL=https://sts-qa.cancer.gov/v2 \\
        python scripts/generate_model_release_versions_baseline.py

Release versions are those with no hyphen (e.g. 2.1.0; not 2.1.0-0338852).
Output: data/model_release_versions_baseline.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

_repo_root = Path(__file__).resolve().parent.parent
_src = _repo_root / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from sts_test_framework.client import APIClient
from sts_test_framework.config import project_root, sts_base_url
from sts_test_framework.discover import _is_release_version

_DEFAULT_OUTPUT = "data/model_release_versions_baseline.json"


def _version_sort_key(version: str) -> tuple:
    """Sort key for major.minor.patch-ish version strings."""
    try:
        parts = version.split(".")[:3]
        return tuple(int(x) if x.isdigit() else 0 for x in parts)
    except (ValueError, AttributeError):
        return (0, 0, 0)


def _release_versions_from_body(body: object) -> list[str]:
    """Filter a /versions JSON body to sorted unique release version strings."""
    if not isinstance(body, list):
        return []
    releases: set[str] = set()
    for item in body:
        if isinstance(item, str) and item.strip() and _is_release_version(item):
            releases.add(item.strip())
    return sorted(releases, key=_version_sort_key)


def _model_handles(body: object) -> list[str]:
    """Unique model handles from GET /models/, preserving first-seen order then sorted."""
    if not isinstance(body, list):
        return []
    seen: set[str] = set()
    handles: list[str] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        handle = item.get("handle")
        if not isinstance(handle, str) or not handle.strip():
            continue
        handle = handle.strip()
        if handle in seen:
            continue
        seen.add(handle)
        handles.append(handle)
    return sorted(handles)


def generate_baseline(*, base_url: str, output_path: Path) -> Path:
    """
    GET /models/ and /model/{handle}/versions for each handle; write release-only baseline.
    """
    client = APIClient(base_url, timeout=120)
    print(f"GET {base_url}/models/")
    models_res = client.get("/models/")
    if models_res.status_code != 200:
        raise SystemExit(
            f"GET /models/ failed: HTTP {models_res.status_code} in {models_res.duration:.3f}s"
        )
    handles = _model_handles(models_res.json())
    if not handles:
        raise SystemExit("GET /models/ returned no model handles")

    models: dict[str, list[str]] = {}
    for handle in handles:
        path = f"/model/{quote(handle, safe='')}/versions"
        print(f"GET {base_url}{path}")
        response = client.get(path, params={"skip": 0, "limit": 0})
        if response.status_code != 200:
            raise SystemExit(
                f"GET {path} failed: HTTP {response.status_code} in {response.duration:.3f}s"
            )
        releases = _release_versions_from_body(response.json())
        models[handle] = releases
        print(f"  {handle}: {len(releases)} release version(s)")

    payload = {
        "source": base_url.rstrip("/"),
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Release versions only (no hyphen). Test asserts baseline ⊆ live.",
        "models": models,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    total = sum(len(v) for v in models.values())
    print(f"Wrote {len(models)} model(s), {total} release version(s) to {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate model release-version baseline JSON from live STS "
            "for model_release_versions tests."
        )
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"STS v2 base URL (default: STS_BASE_URL or {sts_base_url()})",
    )
    parser.add_argument(
        "--output",
        default=_DEFAULT_OUTPUT,
        help=f"Output path under project root (default: {_DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    root = project_root()
    output_path = root / args.output
    generate_baseline(
        base_url=args.base_url or sts_base_url(),
        output_path=output_path,
    )


if __name__ == "__main__":
    main()
