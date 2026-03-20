"""
Session-scoped pytest fixtures: loaded OpenAPI spec, HTTP client, discovery dict, generated cases.
"""
import os
import pytest
from pathlib import Path


def pytest_report_header(config):
    """Add STS environment (base URL) to the pytest run header."""
    base_url = os.getenv("STS_BASE_URL", "https://sts-qa.cancer.gov/v2")
    return f"STS environment: {base_url}"


def _spec_path():
    """Absolute path to bundled ``spec/v2.yaml`` under the package root."""
    root = Path(__file__).resolve().parent.parent
    return root / "spec" / "v2.yaml"


@pytest.fixture(scope="session")
def spec_path():
    """Path object to OpenAPI spec file."""
    return _spec_path()


@pytest.fixture(scope="session")
def spec(spec_path):
    """Parsed OpenAPI document (skipped if spec file missing)."""
    from sts_test_framework.loader import load_spec
    if not spec_path.exists():
        pytest.skip(f"Spec not found: {spec_path}")
    return load_spec(spec_path)


@pytest.fixture(scope="session")
def base_url():
    """STS API root including ``/v2`` (overridable via ``STS_BASE_URL``)."""
    return os.getenv("STS_BASE_URL", "https://sts-qa.cancer.gov/v2")


@pytest.fixture(scope="session")
def api_client(base_url):
    """Shared ``APIClient`` for discovery and tests."""
    from sts_test_framework.client import APIClient
    return APIClient(base_url)


@pytest.fixture(scope="session")
def test_data(api_client):
    """Discovery output used to parametrize positive paths."""
    from sts_test_framework.discover import discover
    return discover(api_client)


@pytest.fixture(scope="session")
def generated_cases(spec, test_data):
    """Full case list (positive + negatives) from ``generate_cases``."""
    from sts_test_framework.generator import generate_cases
    return generate_cases(spec, test_data, include_negative=True)
