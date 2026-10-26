#!/usr/bin/env python3
"""
Write a caDSR /edps DATATEAM-508 duplicate drift baseline JSON from live STS.

Use after intentional Neo4j cleanup to refresh the checked-in ceiling, not on
every routine test pass.

Example::

    STS_BASE_URL=https://sts-qa.cancer.gov/v2 python scripts/export_cadsr_edps_drift_baseline.py \\
        -o data/baselines/cadsr_edps_508_duplicate_baseline_2026-10-21.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts_test_framework.client import APIClient  # noqa: E402
from sts_test_framework.config import project_root, sts_base_url  # noqa: E402
from sts_test_framework.edp_edps_drift import format_508_report_key  # noqa: E402


def _term_key(term: dict, path_origin: str) -> tuple[str, str, str, str]:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=project_root()
        / "data/baselines/cadsr_edps_508_duplicate_baseline_export.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--origin",
        default="caDSR",
        help="EDP origin name (default: caDSR)",
    )
    args = parser.parse_args()

    client = APIClient()
    path = f"/edps/{quote(args.origin, safe='')}"
    res = client.get(path)
    if res.status_code != 200:
        print(f"GET {path} failed: HTTP {res.status_code}", file=sys.stderr)
        return 1
    body = res.json()
    if not isinstance(body, list):
        print("Expected JSON array", file=sys.stderr)
        return 1

    keys = [_term_key(t, args.origin) for t in body if isinstance(t, dict)]
    counts = Counter(keys)
    dups = {k: c for k, c in counts.items() if c > 1}

    groups = []
    for (origin_name, origin_id, origin_version, value), count in sorted(
        dups.items(), key=lambda kv: (-kv[1], kv[0])
    ):
        groups.append(
            {
                "origin_name": origin_name,
                "origin_id": origin_id,
                "origin_version": origin_version,
                "value": value,
                "count": count,
            }
        )

    dup_groups = len(groups)
    extra = sum(g["count"] for g in groups) - dup_groups if groups else 0
    payload = {
        "policy": "no_drift_until_graph_cleanup_then_strict_zero",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_run": "scripts/export_cadsr_edps_drift_baseline.py",
        "sts_base_url_at_capture": sts_base_url(),
        "summary": {
            "rows": len(body),
            "unique_508_keys": len(counts),
            "duplicate_groups": dup_groups,
            "extra_duplicate_rows": extra,
        },
        "groups": groups,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {args.output} ({dup_groups} duplicate groups, extra_rows={extra})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
