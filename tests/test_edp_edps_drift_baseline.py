"""Unit tests for DATATEAM-508 /edps duplicate drift baseline comparison."""
from __future__ import annotations

import pytest

from sts_test_framework.edp_edps_drift import compare_dups_to_baseline


def _key(
    origin_id: str = "1",
    origin_version: str = "1",
    value: str = "Title",
) -> tuple[str, str, str, str]:
    return ("caDSR", origin_id, origin_version, value)


def test_same_counts_passes():
    baseline = [
        {
            "origin_name": "caDSR",
            "origin_id": "1",
            "origin_version": "1",
            "value": "Title",
            "count": 3,
        }
    ]
    current = {_key(): 3}
    result = compare_dups_to_baseline(current, baseline)
    assert result.current_duplicate_groups == 1
    assert result.max_count == 3
    assert result.resolved_keys == []


def test_lower_count_passes():
    baseline = [
        {
            "origin_name": "caDSR",
            "origin_id": "1",
            "origin_version": "1",
            "value": "Title",
            "count": 5,
        }
    ]
    current = {_key(): 3}
    result = compare_dups_to_baseline(current, baseline)
    assert result.max_count == 3


def test_higher_count_fails():
    baseline = [
        {
            "origin_name": "caDSR",
            "origin_id": "1",
            "origin_version": "1",
            "value": "Title",
            "count": 3,
        }
    ]
    current = {_key(): 4}
    with pytest.raises(AssertionError, match="count_increases"):
        compare_dups_to_baseline(current, baseline)


def test_new_duplicate_4_tuple_fails():
    baseline = [
        {
            "origin_name": "caDSR",
            "origin_id": "1",
            "origin_version": "1",
            "value": "Title A",
            "count": 2,
        }
    ]
    current = {_key(value="Title B"): 2}
    with pytest.raises(AssertionError, match="new_duplicate_4_tuples"):
        compare_dups_to_baseline(current, baseline)


def test_resolved_baseline_group_passes():
    baseline = [
        {
            "origin_name": "caDSR",
            "origin_id": "1",
            "origin_version": "1",
            "value": "Title",
            "count": 2,
        },
        {
            "origin_name": "caDSR",
            "origin_id": "2",
            "origin_version": "1",
            "value": "Other",
            "count": 3,
        },
    ]
    current = {_key(origin_id="2", value="Other"): 3}
    result = compare_dups_to_baseline(current, baseline)
    assert result.resolved_keys == ["caDSR/1/1/Title"]
