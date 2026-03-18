"""
Roll up per-case results into summary stats and emit machine-readable JSON reports.
"""
from pathlib import Path


def aggregate_results(results: list[dict]) -> dict:
    """
    Compute totals, per-tag pass counts, per-operation last result, P95 latency, error list.

    Returns:
        Dict suitable for embedding in JSON/HTML reports.
    """
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    failed = total - passed
    by_tag = {}
    by_operation = {}
    durations = [r.get("duration", 0) for r in results if r.get("duration") is not None]
    errors = [r.get("error") for r in results if r.get("error")]

    for r in results:
        tag = r.get("tag") or "unknown"
        by_tag[tag] = by_tag.get(tag, {"total": 0, "passed": 0})
        by_tag[tag]["total"] += 1
        if r.get("passed"):
            by_tag[tag]["passed"] += 1

        op = r.get("operation_id") or "unknown"
        by_operation[op] = {"passed": r.get("passed"), "duration": r.get("duration"), "error": r.get("error")}

    p95_ms = None
    if durations:
        idx = min(int(len(durations) * 0.95), len(durations) - 1)
        if idx >= 0:
            p95_ms = round(sorted(durations)[idx] * 1000, 2)

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "by_tag": by_tag,
        "by_operation": by_operation,
        "durations_ms": [round(d * 1000, 2) for d in durations],
        "p95_ms": p95_ms,
        "errors": [e for e in errors if e],
    }


def write_json_report(summary: dict, results: list[dict], out_path: str | Path) -> None:
    """Serialize ``{"summary": ..., "results": [...]}`` to ``out_path`` (UTF-8, indented)."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"summary": summary, "results": results}
    path.write_text(__import__("json").dumps(payload, indent=2), encoding="utf-8")
