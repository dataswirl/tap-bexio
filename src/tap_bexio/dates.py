"""Conforming Bexio dates and timestamps to ISO 8601."""

from __future__ import annotations

import datetime as dt
import typing as t

if t.TYPE_CHECKING:
    from zoneinfo import ZoneInfo

DATE_FORMATS = ("date", "date-time")

#: Each property's date format, or a subtree for objects (arrays take their items' entry).
type FormatTree = dict[str, str | FormatTree]


def date_tree(schema: dict[str, t.Any]) -> FormatTree:
    """Map each ``date``/``date-time`` property of ``schema`` to its format."""
    tree: FormatTree = {}
    for name, prop in schema.get("properties", {}).items():
        node = prop
        while "items" in node:
            node = node["items"]
        if node.get("format") in DATE_FORMATS:
            tree[name] = node["format"]
        elif subtree := date_tree(node):
            tree[name] = subtree
    return tree


def conform(value: t.Any, formats: str | FormatTree, tz: ZoneInfo) -> t.Any:  # noqa: ANN401
    """Conform the dates in ``value`` to ``formats``, recursing into objects and arrays.

    Objects are updated in place.
    """
    if isinstance(value, list):
        return [conform(item, formats, tz) for item in value]
    if isinstance(value, dict) and isinstance(formats, dict):
        for key, sub in formats.items():
            if key in value:
                value[key] = conform(value[key], sub, tz)
        return value
    if isinstance(value, str) and isinstance(formats, str):
        return conform_date(value, formats, tz)
    return value


def conform_date(value: str, fmt: str, tz: ZoneInfo) -> str:
    """Return ``value`` as an ISO date, or an ISO date-time in ``tz``.

    Bexio returns local time without an offset (2.0), local time with an offset (3.0) and
    UTC without a colon in the offset (4.0, "2026-10-28T14:25:39+0000"). Values that do
    not parse are left as they are.
    """
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return value
    parsed = parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz)
    return parsed.date().isoformat() if fmt == "date" else parsed.isoformat()
