"""Shared constants, fixtures, and helpers for ``tests/test_manual/``."""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from sts_test_framework.client import APIClient, APIResponse

MAJOR_MODELS = ["C3DC", "CCDI", "CCDI-DCC", "ICDC", "CTDC", "CDS", "PSDC"]

# Transient caDSR API failures (504 gateway timeout, connection errors, etc.)
_CADSR_RETRYABLE_STATUS = frozenset({0, 429, 500, 502, 503, 504})


def get_cadsr_data_element_with_retry(
    client: APIClient,
    path: str,
    *,
    log: Callable[[str], None] | None = print,
) -> APIResponse:
    """
    GET ``path`` (typically ``/DataElement/{cde_id}``) with retries on flaky responses.

    Retries when status is 0 (connection/URL error from ``APIClient``), 429, or 5xx
    gateway/server codes commonly seen on caDSR. Does not retry other 4xx.

    Environment (optional):

    - ``CADSR_GET_MAX_ATTEMPTS`` — default ``4`` (first try + up to 3 retries).
    - ``CADSR_GET_RETRY_DELAY_SEC`` — default ``2.0`` seconds between attempts.
    """
    max_attempts = int(os.getenv("CADSR_GET_MAX_ATTEMPTS", "4"))
    delay_sec = float(os.getenv("CADSR_GET_RETRY_DELAY_SEC", "2.0"))
    if max_attempts < 1:
        max_attempts = 1

    last: APIResponse | None = None
    for attempt in range(1, max_attempts + 1):
        last = client.get(path)
        if last.status_code == 200:
            return last
        if last.status_code not in _CADSR_RETRYABLE_STATUS or attempt >= max_attempts:
            return last
        if log is not None:
            log(
                f"  caDSR GET {path!r} attempt {attempt}/{max_attempts} "
                f"got HTTP {last.status_code}, retrying in {delay_sec}s..."
            )
        time.sleep(delay_sec)
    assert last is not None
    return last
