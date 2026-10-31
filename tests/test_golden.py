"""Golden snapshot of full syncs against canned responses.

Pins the Singer messages (SCHEMA, RECORD, STATE) a sync emits, so refactors can prove they
did not change behaviour. Regenerate with ``UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py``
and review the diff.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
from pathlib import Path

from responses import matchers

from .conftest import API

GOLDEN_DIR = Path(__file__).parent / "golden"
# The SDK caps bookmarks at the sync start time, which differs on every run.
SIGNPOST = re.compile(r'("replication_key_signpost": )"[^"]*"')


def _messages(tap, stream_name):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        tap.streams[stream_name].sync()
    messages = [json.loads(line) for line in out.getvalue().splitlines()]
    for message in messages:
        message.pop("time_extracted", None)
    return messages


def _check(name, messages):
    path = GOLDEN_DIR / f"{name}.json"
    text = json.dumps(messages, indent=1, sort_keys=True) + "\n"
    text = SIGNPOST.sub(r'\1"<now>"', text)
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN_DIR.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert text == path.read_text(encoding="utf-8")


def _offset_query(offset=0, limit=2, **extra):
    return matchers.query_param_matcher(
        {"limit": str(limit), "offset": str(offset), **{k: str(v) for k, v in extra.items()}}
    )


def test_offset_stream(make_tap, mocked):
    mocked.get(
        f"{API}/2.0/country",
        json=[{"id": 1, "name": "CH"}, {"id": 2, "name": "DE"}],
        match=[_offset_query(0)],
    )
    mocked.get(f"{API}/2.0/country", json=[{"id": 3, "name": "AT"}], match=[_offset_query(2)])
    _check("countries", _messages(make_tap(page_size=2), "countries"))


def test_page_stream(make_tap, mocked):
    for page in (1, 2):
        mocked.get(
            f"{API}/4.0/expenses",
            json={
                "data": [{"id": f"e{page}", "created_at": "2024-07-15T13:17:32+0000"}],
                "paging": {"page": page, "page_count": 2},
            },
            match=[matchers.query_param_matcher({"page": str(page), "limit": "500"})],
        )
    _check("expenses", _messages(make_tap(), "expenses"))


def test_search_stream_with_children(make_tap, mocked):
    mocked.post(
        f"{API}/2.0/kb_invoice/search",
        json=[
            {"id": 1, "updated_at": "2024-02-01 08:00:00", "is_valid_from": "2024-02-01"},
            {"id": 2, "updated_at": "2024-03-01 09:30:00", "is_valid_from": "2024-03-01"},
        ],
        match=[
            _offset_query(0, limit=500, order_by="id"),
            matchers.json_params_matcher(
                [{"field": "updated_at", "value": "2024-01-15 01:00:00", "criteria": ">="}]
            ),
        ],
    )
    for doc in (1, 2):
        mocked.get(
            f"{API}/2.0/kb_invoice/{doc}",
            json={"id": doc, "positions": [{"id": 10, "type": "KbPositionText"}]},
        )
        mocked.get(f"{API}/2.0/kb_invoice/{doc}/kb_reminder", json=[])
        mocked.get(
            f"{API}/2.0/kb_invoice/{doc}/comment",
            json=[{"id": 200 + doc, "date": "2024-03-02 10:00:00"}],
        )
    mocked.get(f"{API}/2.0/kb_invoice/1/payment", json=[{"id": 101, "date": "2024-03-02"}])
    mocked.get(f"{API}/2.0/kb_invoice/2/payment", status=404)  # deleted during sync
    tap = make_tap(start_date="2024-01-15T00:00:00Z")
    _check("invoices", _messages(tap, "invoices"))


def test_contacts_partitions_with_children(make_tap, mocked):
    mocked.get(
        f"{API}/2.0/contact",
        json=[{"id": 1, "updated_at": "2024-01-01 12:00:00"}],
        match=[_offset_query(0, limit=500, order_by="id")],
    )
    mocked.get(
        f"{API}/2.0/contact",
        json=[{"id": 2, "updated_at": "2024-06-01 12:00:00"}],
        match=[_offset_query(0, limit=500, order_by="id", show_archived="true")],
    )
    mocked.get(f"{API}/2.0/contact/1/additional_address", json=[{"id": 5}])
    mocked.get(f"{API}/2.0/contact/2/additional_address", status=403)
    _check("contacts", _messages(make_tap(), "contacts"))
