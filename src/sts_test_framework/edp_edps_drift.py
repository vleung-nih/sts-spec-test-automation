"""Helpers for caDSR /edps DATATEAM-508 duplicate drift vs a checked-in baseline."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def format_508_report_key(
    origin_name: str,
    origin_id: str,
    origin_version: str,
    value: str,
) -> str:
    return f"{origin_name}/{origin_id}/{origin_version}/{value}"


def baseline_groups_to_counts(
    groups: list[dict[str, Any]],
) -> dict[str, int]:
    """Map report key -> duplicate row count from baseline JSON groups."""
    out: dict[str, int] = {}
    for g in groups:
        key = format_508_report_key(
            str(g["origin_name"]),
            str(g["origin_id"]),
            str(g["origin_version"]),
            str(g.get("value", "")),
        )
        out[key] = int(g["count"])
    return out


def current_dups_to_report_keys(
    current_dups: dict[tuple[str, str, str, str], int],
) -> dict[str, int]:
    out: dict[str, int] = {}
    for (origin_name, origin_id, origin_version, value), count in current_dups.items():
        key = format_508_report_key(origin_name, origin_id, origin_version, value)
        out[key] = count
    return out


@dataclass(frozen=True)
class DriftCompareResult:
    """Outcome when live dup counts are within baseline (no regression)."""

    resolved_keys: list[str]
    current_duplicate_groups: int
    max_count: int


def load_drift_baseline(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Drift baseline not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError(f"Drift baseline must contain non-empty groups list: {path}")
    return data


def compare_dups_to_baseline(
    current_dups: dict[tuple[str, str, str, str], int],
    baseline_groups: list[dict[str, Any]],
) -> DriftCompareResult:
    """
    Fail if any new duplicate 4-tuple appears or any baseline group's count increased.

    Returns resolved baseline keys (had count > 1 in baseline, no longer duplicated live).
    """
    baseline_counts = baseline_groups_to_counts(baseline_groups)
    live_counts = current_dups_to_report_keys(current_dups)

    new_keys: dict[str, int] = {}
    for key, count in live_counts.items():
        if key not in baseline_counts:
            new_keys[key] = count

    increases: dict[str, dict[str, int]] = {}
    for key, base_count in baseline_counts.items():
        if base_count <= 1:
            continue
        live = live_counts.get(key)
        if live is not None and live > base_count:
            increases[key] = {"baseline": base_count, "actual": live}

    if new_keys or increases:
        parts = [
            "DATATEAM-508 duplicate drift vs baseline: regression detected "
            "(new duplicate 4-tuple and/or increased count).",
        ]
        if new_keys:
            parts.append(
                f"  new_duplicate_4_tuples ({len(new_keys)}): "
                f"{json.dumps(new_keys, indent=2)}"
            )
        if increases:
            parts.append(
                f"  count_increases ({len(increases)}): "
                f"{json.dumps(increases, indent=2)}"
            )
        raise AssertionError("\n".join(parts))

    resolved = sorted(
        key
        for key, base_count in baseline_counts.items()
        if base_count > 1 and key not in live_counts
    )
    max_count = max(live_counts.values(), default=0)
    return DriftCompareResult(
        resolved_keys=resolved,
        current_duplicate_groups=len(live_counts),
        max_count=max_count,
    )
