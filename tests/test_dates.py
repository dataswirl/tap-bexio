"""Which schema properties hold dates, and how their values are conformed."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from tap_bexio.dates import FormatTree, conform, date_tree

ZURICH = ZoneInfo("Europe/Zurich")


def test_date_tree_maps_nested_objects_and_arrays():
    schema = {
        "properties": {
            "id": {"type": "integer"},
            "day": {"type": "string", "format": "date"},
            "at": {"type": "string", "format": "date-time"},
            "email": {"type": "string", "format": "email"},
            "tracking": {"properties": {"start": {"format": "date-time"}, "n": {}}},
            "entries": {"items": {"properties": {"date": {"format": "date"}}}},
            "days": {"items": {"format": "date"}},
            "plain": {"properties": {"n": {"type": "integer"}}},
        }
    }
    assert date_tree(schema) == {
        "day": "date",
        "at": "date-time",
        "tracking": {"start": "date-time"},
        "entries": {"date": "date"},
        "days": "date",
    }


def test_conform_walks_the_tree_and_leaves_other_values():
    row = {
        "at": "2024-07-15 13:17:32",
        "days": ["2024-07-15", "2024-07-16 00:00:00"],
        "tracking": {"start": "2024-01-15 08:00:00", "n": 1},
        "entries": [{"date": "2024-07-14T23:30:00+00:00"}],
        "other": "2024-07-15 13:17:32",
    }
    tree: FormatTree = {
        "at": "date-time",
        "days": "date",
        "tracking": {"start": "date-time"},
        "entries": {"date": "date"},
        "missing": "date",
    }
    assert conform(row, tree, ZURICH) == {
        "at": "2024-07-15T13:17:32+02:00",
        "days": ["2024-07-15", "2024-07-16"],
        "tracking": {"start": "2024-01-15T08:00:00+01:00", "n": 1},
        "entries": [{"date": "2024-07-15"}],
        "other": "2024-07-15 13:17:32",
    }


def test_conform_ignores_shape_mismatches():
    assert conform({"at": {"x": 1}}, {"at": "date-time"}, ZURICH) == {"at": {"x": 1}}
    assert conform({"at": "2024-01-01"}, {"at": {"x": "date"}}, ZURICH) == {"at": "2024-01-01"}
    assert conform(None, {"at": "date"}, ZURICH) is None
