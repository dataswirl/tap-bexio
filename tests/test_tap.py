"""Offline tests for tap-bexio."""

from __future__ import annotations

from pathlib import Path

from tap_bexio.client import BexioStream
from tap_bexio.tap import TapBexio

SCHEMAS_DIR = Path(__file__).parent.parent / "src" / "tap_bexio" / "schemas"
INCREMENTAL = {"contacts", "contact_relations", "invoices", "offers", "orders"}


def test_every_stream_has_a_schema_file_and_vice_versa():
    tap = TapBexio(config={"auth_token": "dummy"})
    assert set(tap.streams) == {p.stem for p in SCHEMAS_DIR.glob("*.json")}


def test_primary_and_replication_keys_exist_in_schemas():
    tap = TapBexio(config={"auth_token": "dummy"})
    for stream in tap.streams.values():
        properties = stream.schema["properties"]
        for key in stream.primary_keys or ():
            assert key in properties, f"{stream.name}: {key}"
        if stream.replication_key:
            assert properties[stream.replication_key]["format"] == "date-time"


def test_incremental_streams():
    tap = TapBexio(config={"auth_token": "dummy"})
    assert {n for n, s in tap.streams.items() if s.replication_key} == INCREMENTAL


def test_default_api_url():
    tap = TapBexio(config={"auth_token": "dummy"})
    stream = tap.streams["countries"]
    assert isinstance(stream, BexioStream)
    assert stream.url_base == "https://api.bexio.com"
