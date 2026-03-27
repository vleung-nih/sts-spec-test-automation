"""
CLI for CCDI Federation (DCC) OpenAPI-driven functional tests.

Environment: ``DCC_BASE_URL`` (default includes ``/api/v1``), optional ``DCC_REPORT_DIR``.
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


def main_dcc() -> None:
    import argparse

    from .config import DEFAULT_DCC_BASE_URL, bundled_dcc_spec_path, dcc_base_url

    parser = argparse.ArgumentParser(description="CCDI Federation (DCC) API test framework")
    parser.add_argument("--spec", default=None, help="Path to DCC OpenAPI JSON (default: bundled spec/dcc/openapi.json)")
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"DCC base URL ending in /api/v1 (default: DCC_BASE_URL or {DEFAULT_DCC_BASE_URL})",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Report directory (default: DCC_REPORT_DIR or reports/dcc)",
    )
    parser.add_argument("--tags", default=None, help="Comma-separated OpenAPI tags to run (default: all)")
    parser.add_argument("--no-negative", action="store_true", help="Skip negative test cases")
    parser.add_argument("--quiet", action="store_true", help="Minimal console output")
    args = parser.parse_args()

    base_url = args.base_url or dcc_base_url()
    report_dir = args.report or os.getenv("DCC_REPORT_DIR", "reports/dcc")
    spec_path = Path(args.spec) if args.spec else bundled_dcc_spec_path()
    if not spec_path.exists():
        print(f"Spec not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    tag_filter = [t.strip() for t in args.tags.split(",")] if args.tags else None
    quiet = args.quiet

    def log(msg: str) -> None:
        if not quiet:
            print(msg, flush=True)

    from .loader import get_paths, load_spec
    from .client import APIClient
    from .dcc_discover import discover_dcc
    from .dcc_generator import generate_cases_dcc
    from .runners.functional import run_functional_tests_dcc
    from .reporters.report import aggregate_results, write_json_report
    from .reporters.html_report import write_html_report_dcc

    log(f"Loading spec from {spec_path}...")
    spec = load_spec(spec_path)
    log(f"Spec loaded: {len(get_paths(spec))} paths.")

    log(f"Client: base_url={base_url}")
    client = APIClient(base_url)

    log("Running discovery...")
    test_data = discover_dcc(client)
    discovery_info: dict | None = None
    if test_data:
        discovery_info = {}
        parts = []
        for key in sorted(test_data.keys()):
            v = test_data[key]
            if isinstance(v, str) and len(v) > 20:
                disp = v[:17] + "..."
            else:
                disp = v
            parts.append(f"{key}={disp!r}")
            discovery_info[key] = v
        log(f"Discovery: {', '.join(parts)}")
    else:
        log("Discovery: no data (API unreachable or empty subject list).")

    cases = generate_cases_dcc(spec, test_data, include_negative=not args.no_negative, tag_filter=tag_filter)
    if not cases:
        print("No test cases generated (check discovery and tag filter)", file=sys.stderr)
        sys.exit(0)

    n_positive = sum(1 for c in cases if not c.get("negative"))
    n_negative = len(cases) - n_positive
    log(f"Generated {len(cases)} cases ({n_positive} positive, {n_negative} negative).")
    if not quiet:
        by_tag = Counter(c.get("tag") or "unknown" for c in cases)
        log(f"By tag: {', '.join(f'{t}={n}' for t, n in sorted(by_tag.items()))}.")

    def on_case_done(result: dict) -> None:
        status = "Pass" if result.get("passed") else "Fail"
        path = result.get("path_display") or result.get("path", "")
        duration = result.get("duration")
        duration_ms = f"{duration * 1000:.0f} ms" if duration is not None else "?"
        note = result.get("pagination_pair_display_note")
        suffix = f" — {note}" if note else ""
        if result.get("passed"):
            log(f"  [Pass] GET {path} ({duration_ms}){suffix}")
        else:
            err = (result.get("error") or "")[:80]
            log(f"  [Fail] GET {path} ({duration_ms}) - {err}")

    if quiet:
        print(f"Running {len(cases)} test cases...", flush=True)
    else:
        log(f"Running {len(cases)} test cases...")
    results = run_functional_tests_dcc(client, cases, on_case_done=on_case_done if not quiet else None)
    summary = aggregate_results(results)

    run_id = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    Path(report_dir).mkdir(parents=True, exist_ok=True)
    json_path = Path(report_dir) / f"dcc_report_{run_id}.json"
    html_path = Path(report_dir) / f"dcc_report_{run_id}.html"
    write_json_report(summary, results, json_path)
    write_html_report_dcc(
        summary,
        results,
        html_path,
        base_url=base_url,
        discovery_info=discovery_info,
        cases_generated={"total": len(cases), "positive": n_positive, "negative": n_negative},
    )
    if quiet:
        print(f"Report written: {json_path}, {html_path}", flush=True)
    else:
        log(f"Report written: {json_path}, {html_path}")

    passed = summary.get("passed", 0)
    total = summary.get("total", 0)
    print(f"Result: {passed}/{total} passed", flush=True)
    if summary.get("failed", 0) > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main_dcc()
