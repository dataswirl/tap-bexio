"""Banking streams."""

from __future__ import annotations

from tap_bexio.client import BexioOffsetStream, BexioPageStream, BexioStream


class BankAccountsStream(BexioOffsetStream):
    """Bank accounts."""

    name = "bank_accounts"
    path = "/3.0/banking/accounts"


class PaymentsStream(BexioPageStream):
    """Bank payments (4.0; replaces the deprecated 3.0 payments endpoint).

    The response is ``{"query", "sort-by", "pagination", "results": [...]}``, unlike the
    spec, which documents a single payment object. Pages are 1-based (``page=0`` is
    served as page 1), also contrary to the spec.
    """

    name = "payments"
    path = "/4.0/banking/payments"
    records_jsonpath = "$.results[*]"
    size_param = "per-page"


class PaymentTypesStream(BexioOffsetStream):
    """Payment types."""

    name = "payment_types"
    path = "/2.0/payment_type"


STREAMS: list[type[BexioStream]] = [
    BankAccountsStream,
    PaymentsStream,
    PaymentTypesStream,
]
