"""What to do with a Bexio response: continue, skip, fail or wait."""

from __future__ import annotations

import enum
import typing as t
from http import HTTPStatus

from tap_bexio.config import ForbiddenBehavior

if t.TYPE_CHECKING:
    from collections.abc import Mapping

#: Seconds to wait on 429 when ``RateLimit-Reset`` is missing.
DEFAULT_RATE_LIMIT_WAIT = 60
#: Seconds to wait before retrying any other retriable error.
DEFAULT_RETRY_WAIT = 10
#: Pause before the next request once the remaining quota drops to this many requests.
RATE_LIMIT_MIN_REMAINING = 1


class Action(enum.Enum):
    """Outcome of a response status, before the SDK's own checks."""

    CONTINUE = enum.auto()
    FAIL_UNAUTHORIZED = enum.auto()
    FAIL_FORBIDDEN = enum.auto()
    #: End the stream and its remaining partitions without failing the sync.
    SKIP_STREAM = enum.auto()
    #: End only the current partition (one parent record) without failing the sync.
    SKIP_PARTITION = enum.auto()


def classify(status: int, *, is_child: bool, forbidden: ForbiddenBehavior) -> Action:
    """Return what to do with a response of ``status``."""
    if status == HTTPStatus.UNAUTHORIZED:
        return Action.FAIL_UNAUTHORIZED
    if status == HTTPStatus.FORBIDDEN:
        skip = forbidden is ForbiddenBehavior.SKIP
        return Action.SKIP_STREAM if skip else Action.FAIL_FORBIDDEN
    if status == HTTPStatus.NOT_FOUND and is_child:
        return Action.SKIP_PARTITION
    return Action.CONTINUE


def throttle_wait(status: int, headers: Mapping[str, str]) -> int | None:
    """Return seconds to pause when the remaining quota is nearly used up, else None.

    A 429 is left to the retry, which already waits for ``RateLimit-Reset``.
    """
    if status == HTTPStatus.TOO_MANY_REQUESTS:
        return None
    remaining = headers.get("RateLimit-Remaining", "")
    reset = headers.get("RateLimit-Reset", "")
    if remaining.isdigit() and reset.isdigit() and int(remaining) <= RATE_LIMIT_MIN_REMAINING:
        return int(reset) + 1
    return None


def retry_wait(status: int | None, headers: Mapping[str, str]) -> float:
    """Return seconds to wait before retrying: ``RateLimit-Reset`` on 429, else a short pause."""
    if status != HTTPStatus.TOO_MANY_REQUESTS:
        return DEFAULT_RETRY_WAIT
    reset = headers.get("RateLimit-Reset", "")
    return int(reset) + 1 if reset.isdigit() else DEFAULT_RATE_LIMIT_WAIT
