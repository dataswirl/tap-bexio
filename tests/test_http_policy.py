"""How Bexio responses are classified and rate limits honoured."""

from __future__ import annotations

import pytest

from tap_bexio.config import ForbiddenBehavior
from tap_bexio.http_policy import Action, classify, retry_wait, throttle_wait

SKIP, FAIL = ForbiddenBehavior.SKIP, ForbiddenBehavior.FAIL


@pytest.mark.parametrize(
    ("status", "is_child", "forbidden", "expected"),
    [
        (200, False, SKIP, Action.CONTINUE),
        (401, False, SKIP, Action.FAIL_UNAUTHORIZED),
        (401, True, SKIP, Action.FAIL_UNAUTHORIZED),
        (403, False, SKIP, Action.SKIP_STREAM),
        (403, True, SKIP, Action.SKIP_STREAM),
        (403, False, FAIL, Action.FAIL_FORBIDDEN),
        (404, True, SKIP, Action.SKIP_PARTITION),
        (404, False, SKIP, Action.CONTINUE),  # left to the SDK, which fails on 4xx
        (429, False, SKIP, Action.CONTINUE),  # left to the SDK, which retries
    ],
)
def test_classify(status, is_child, forbidden, expected):
    assert classify(status, is_child=is_child, forbidden=forbidden) is expected


@pytest.mark.parametrize(
    ("status", "headers", "expected"),
    [
        (200, {"RateLimit-Remaining": "1", "RateLimit-Reset": "7"}, 8),
        (200, {"RateLimit-Remaining": "0", "RateLimit-Reset": "3"}, 4),
        (200, {"RateLimit-Remaining": "2", "RateLimit-Reset": "7"}, None),
        (200, {"RateLimit-Remaining": "1"}, None),
        (200, {"RateLimit-Remaining": "x", "RateLimit-Reset": "7"}, None),
        (200, {}, None),
        (429, {"RateLimit-Remaining": "0", "RateLimit-Reset": "7"}, None),  # retry waits
    ],
)
def test_throttle_wait(status, headers, expected):
    assert throttle_wait(status, headers) == expected


@pytest.mark.parametrize(
    ("status", "headers", "expected"),
    [
        (429, {"RateLimit-Reset": "7"}, 8),
        (429, {}, 60),
        (429, {"RateLimit-Reset": "soon"}, 60),
        (503, {"RateLimit-Reset": "7"}, 10),
        (None, {}, 10),
    ],
)
def test_retry_wait(status, headers, expected):
    assert retry_wait(status, headers) == expected
