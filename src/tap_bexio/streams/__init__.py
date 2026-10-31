"""Stream classes for tap-bexio, grouped by Bexio domain."""

from __future__ import annotations

import inspect

from tap_bexio.client import BexioStream
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

_MODULES = (contacts, sales, items, purchase, accounting, banking, projects, payroll, misc)

#: Every public stream class, by module and then in definition order.
STREAM_TYPES: list[type[BexioStream]] = [
    cls
    for module in _MODULES
    for cls in vars(module).values()
    if inspect.isclass(cls)
    and issubclass(cls, BexioStream)
    and cls.__module__ == module.__name__
    and not cls.__name__.startswith("_")
]
