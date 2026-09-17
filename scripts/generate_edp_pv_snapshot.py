#!/usr/bin/env python3
"""
Fetch EDP permissible-value labels from STS and write a sorted JSON snapshot.

Usage (from project root):
    python scripts/generate_edp_pv_snapshot.py --origin-id CRDC0001 --origin-version 1
    python scripts/generate_edp_pv_snapshot.py --origin-id CRDC0003 --origin-version 3.2
    STS_BASE_URL=https://sts-qa.cancer.gov/v2 python scripts/generate_edp_pv_snapshot.py \\
        --origin-name CRDC --origin-id CRDC0002 --origin-version 1

Output: data/edp_expected_pv/{origin_id}_{origin_version}.json (sorted string array).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote

_repo_root = Path(__file__).resolve().parent.parent
_src = _repo_root / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from sts_test_framework.client import APIClient
from sts_test_framework.config import project_root, sts_base_url

_DEFAULT_OUTPUT_DIR = "data/edp_expected_pv"


def _edp_terms_path(origin_name: str, origin_id: str, origin_version: str) -> str:
    return (
        f"/edp/{quote(origin_name, safe='')}/{quote(origin_id, safe='')}/"
        f"{quote(origin_version, safe='')}/terms"
    )


def _pv_values_from_edp_terms(body: object) -> list[str]:
    if not isinstance(body, list):
        return []
    out: list[str] = []
    for item in body:
        if isinstance(item, dict):
            val = item.get("value")
            if val is not None:
                out.append(str(val))
    return out


def _snapshot_filename(origin_id: str, origin_version: str) -> str:
    return f"{origin_id}_{origin_version}.json"


def generate_snapshot(
    *,
    origin_name: str,
    origin_id: str,
    origin_version: str,
    base_url: str,
    output_dir: Path,
) -> Path:
    """GET EDP terms (no limit) and write sorted PV labels to a JSON snapshot file."""
    client = APIClient(base_url, timeout=120)
    path = _edp_terms_path(origin_name, origin_id, origin_version)
    print(f"GET {base_url}{path}")
    response = client.get(path)
    if response.status_code != 200:
        raise SystemExit(
            f"STS EDP GET failed: HTTP {response.status_code} in {response.duration:.3f}s"
        )
    body = response.json()
    if not isinstance(body, list) or not body:
        raise SystemExit("STS EDP response: expected non-empty JSON array")

    values = sorted(_pv_values_from_edp_terms(body))
    if not values:
        raise SystemExit("No Term.value strings extracted from EDP response")

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / _snapshot_filename(origin_id, origin_version)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(values, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {len(values)} PV labels to {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate EDP PV snapshot JSON from live STS for edp_custom_cde tests."
    )
    parser.add_argument(
        "--origin-name",
        default="CRDC",
        help="EDP origin authority (default: CRDC)",
    )
    parser.add_argument("--origin-id", required=True, help="EDP origin_id, e.g. CRDC0001")
    parser.add_argument("--origin-version", required=True, help="EDP origin_version, e.g. 1 or 3.2")
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"STS v2 base URL (default: STS_BASE_URL or {sts_base_url()})",
    )
    parser.add_argument(
        "--output-dir",
        default=_DEFAULT_OUTPUT_DIR,
        help=f"Directory under project root for snapshots (default: {_DEFAULT_OUTPUT_DIR})",
    )
    args = parser.parse_args()

    root = project_root()
    output_dir = root / args.output_dir
    generate_snapshot(
        origin_name=args.origin_name,
        origin_id=args.origin_id,
        origin_version=args.origin_version,
        base_url=args.base_url or sts_base_url(),
        output_dir=output_dir,
    )


if __name__ == "__main__":
    main()
