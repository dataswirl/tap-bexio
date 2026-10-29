"""Stream classes for tap-bexio, grouped by Bexio domain."""

from __future__ import annotations

from tap_bexio.streams import (
    accounting,
    banking,
    contacts,
    items,
    misc,
    payroll,
    projects,
    purchase,
    sales,
)

STREAM_TYPES = [
    *contacts.STREAMS,
    *sales.STREAMS,
    *items.STREAMS,
    *purchase.STREAMS,
    *accounting.STREAMS,
    *banking.STREAMS,
    *projects.STREAMS,
    *payroll.STREAMS,
    *misc.STREAMS,
]
