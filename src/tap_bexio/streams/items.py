"""Item and stock streams."""

from __future__ import annotations

from tap_bexio.client import BexioOffsetStream, BexioStream


class ArticlesStream(BexioOffsetStream):
    """Articles (items/products)."""

    name = "articles"
    path = "/2.0/article"


class StockLocationsStream(BexioOffsetStream):
    """Stock locations."""

    name = "stock_locations"
    path = "/2.0/stock_place"


class StockAreasStream(BexioOffsetStream):
    """Stock areas."""

    name = "stock_areas"
    path = "/2.0/stock"


class UnitsStream(BexioOffsetStream):
    """Units of measure."""

    name = "units"
    path = "/2.0/unit"


STREAMS: list[type[BexioStream]] = [
    ArticlesStream,
    StockLocationsStream,
    StockAreasStream,
    UnitsStream,
]
