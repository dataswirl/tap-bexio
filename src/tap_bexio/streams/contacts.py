"""Contact streams."""

from __future__ import annotations

import typing as t

from tap_bexio.client import BexioOffsetStream, BexioSearchStream, BexioStream

if t.TYPE_CHECKING:
    from singer_sdk.helpers.types import Context


class ContactsStream(BexioSearchStream):
    """Contacts, active and archived (incremental).

    ``show_archived=true`` returns *only* archived contacts, so both sets are synced as
    separate partitions, each with its own bookmark.
    """

    name = "contacts"
    path = "/2.0/contact"
    child_context_key = "contact_id"

    @property
    def partitions(self) -> list[dict[str, t.Any]]:
        """Return the active and archived partitions."""
        return [{"archived": False}, {"archived": True}]

    def get_url_params(
        self,
        context: Context | None,
        next_page_token: int | None,
    ) -> dict[str, t.Any]:
        """Select active or archived contacts."""
        params = super().get_url_params(context, next_page_token)
        if (context or {}).get("archived"):
            params["show_archived"] = "true"
        return params


class ContactRelationsStream(BexioSearchStream):
    """Relations between contacts (incremental)."""

    name = "contact_relations"
    path = "/2.0/contact_relation"


class ContactGroupsStream(BexioOffsetStream):
    """Contact groups."""

    name = "contact_groups"
    path = "/2.0/contact_group"


class ContactSectorsStream(BexioOffsetStream):
    """Contact sectors (``contact_branch`` in the API)."""

    name = "contact_sectors"
    path = "/2.0/contact_branch"


class ContactTypesStream(BexioOffsetStream):
    """Contact types (legacy endpoint, not in the current API reference)."""

    name = "contact_types"
    path = "/2.0/contact_type"


class SalutationsStream(BexioOffsetStream):
    """Salutations."""

    name = "salutations"
    path = "/2.0/salutation"


class TitlesStream(BexioOffsetStream):
    """Titles."""

    name = "titles"
    path = "/2.0/title"


class ContactAdditionalAddressesStream(BexioOffsetStream):
    """Additional addresses of a contact."""

    name = "contact_additional_addresses"
    path = "/2.0/contact/{contact_id}/additional_address"
    parent_stream_type = ContactsStream
    state_partitioning_keys = ()


STREAMS: list[type[BexioStream]] = [
    ContactsStream,
    ContactRelationsStream,
    ContactGroupsStream,
    ContactSectorsStream,
    ContactTypesStream,
    SalutationsStream,
    TitlesStream,
    ContactAdditionalAddressesStream,
]
