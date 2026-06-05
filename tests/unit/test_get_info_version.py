"""Unit tests for ``get_info_version``."""

import pytest

from sts_test_framework.loader import get_info_version


def test_get_info_version_returns_version_string():
    spec = {"info": {"version": "2.5.0"}}
    assert get_info_version(spec) == "2.5.0"


def test_get_info_version_coerces_non_string():
    spec = {"info": {"version": 2.5}}
    assert get_info_version(spec) == "2.5"


def test_get_info_version_raises_when_missing():
    with pytest.raises(ValueError, match="missing info.version"):
        get_info_version({})

    with pytest.raises(ValueError, match="missing info.version"):
        get_info_version({"info": {}})
