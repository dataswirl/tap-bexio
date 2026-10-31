"""Tests for the sync audit script."""

from __future__ import annotations

import json

from scripts import audit_sync

SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "name": {"type": ["string", "null"]},
        "tags": {"type": "array", "items": {"type": "string"}},
        "unused": {"type": ["string", "null"]},
    },
}
STDERR = (
    "2026-10-31 INFO ignored line\n"
    "2026-10-31 WARNING | tap-bexio.contacts | Properties ('secret', 'extra') were present"
    " in the 'contacts' stream but not found in catalog schema. Ignoring.\n"
)


def messages(*lines: dict) -> str:
    return "".join(json.dumps(line) + "\n" for line in lines)


def run(tmp_path, monkeypatch, capsys, out: str, err: str = "") -> str:
    out_path, err_path = tmp_path / "sync.out", tmp_path / "sync.err"
    out_path.write_text(out, encoding="utf-8")
    err_path.write_text(err, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["audit_sync.py", str(out_path), str(err_path)])
    audit_sync.main()
    return capsys.readouterr().out


def test_reports_violations_dropped_fields_and_absent_fields(tmp_path, monkeypatch, capsys):
    out = messages(
        {"type": "SCHEMA", "stream": "contacts", "schema": SCHEMA, "key_properties": ["id"]},
        {"type": "STATE", "value": {}},
        {"type": "RECORD", "stream": "contacts", "record": {"id": 1, "tags": ["a", 2]}},
        {"type": "RECORD", "stream": "contacts", "record": {"id": "2", "name": None}},
        {"type": "SCHEMA", "stream": "empty", "schema": SCHEMA, "key_properties": []},
    )
    assert run(tmp_path, monkeypatch, capsys, out, STDERR) == (
        "streams with data: 1\n"
        "\n== schema violations\n"
        "  contacts.id: ['str, expected type=integer']\n"
        "  contacts.tags[]: ['int, expected type=string']\n"
        "\n== returned by the API but not in the schema (dropped)\n"
        "  contacts: 'secret', 'extra'\n"
        "\n== in the schema but absent from every record\n"
        "  contacts (2 records): ['unused']\n"
    )


def test_checks_formats(tmp_path, monkeypatch, capsys):
    schema = {"type": "object", "properties": {"d": {"type": "string", "format": "date"}}}
    out = messages(
        {"type": "SCHEMA", "stream": "s", "schema": schema},
        {"type": "RECORD", "stream": "s", "record": {"d": "not a date"}},
    )
    assert "  s.d: ['str, expected format=date']\n" in run(tmp_path, monkeypatch, capsys, out)


def test_nested_paths_collapse_array_indexes(tmp_path, monkeypatch, capsys):
    schema = {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "items": {"type": "object", "properties": {"n": {"type": "integer"}}},
            }
        },
    }
    out = messages(
        {"type": "SCHEMA", "stream": "s", "schema": schema},
        {"type": "RECORD", "stream": "s", "record": {"rows": [{"n": 1}, {"n": "x"}, {"n": "y"}]}},
    )
    assert "  s.rows[].n: ['str, expected type=integer']\n" in run(
        tmp_path, monkeypatch, capsys, out
    )


def test_clean_sync_has_empty_sections(tmp_path, monkeypatch, capsys):
    out = messages(
        {"type": "SCHEMA", "stream": "s", "schema": {"type": "object", "properties": {}}},
        {"type": "RECORD", "stream": "s", "record": {}},
    )
    assert run(tmp_path, monkeypatch, capsys, out) == (
        "streams with data: 1\n"
        "\n== schema violations\n"
        "\n== returned by the API but not in the schema (dropped)\n"
        "\n== in the schema but absent from every record\n"
    )
