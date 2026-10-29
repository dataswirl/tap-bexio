"""Shared fixtures for tap-bexio tests."""

from __future__ import annotations

import typing as t

import pytest
import responses

from tap_bexio.client import BexioStream
from tap_bexio.tap import TapBexio

API = "https://api.bexio.com"


@pytest.fixture(autouse=True)
def no_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(BexioStream, "backoff_max_tries", lambda _: 1)


@pytest.fixture
def make_tap() -> t.Callable[..., TapBexio]:
    def _make(state: dict | None = None, **config: t.Any) -> TapBexio:
        return TapBexio(config={"auth_token": "token", **config}, state=state)

    return _make


@pytest.fixture
def mocked() -> t.Iterator[responses.RequestsMock]:
    with responses.RequestsMock() as rsps:
        yield rsps
