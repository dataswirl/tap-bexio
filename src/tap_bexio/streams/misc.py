"""Company, user, reference data and file streams."""

from __future__ import annotations

import typing as t

from tap_bexio.client import BexioOffsetStream, BexioStream, BexioUnpagedStream


class UsersStream(BexioOffsetStream):
    """Users."""

    name = "users"
    path = "/3.0/users"


class FictionalUsersStream(BexioOffsetStream):
    """Fictional users."""

    name = "fictional_users"
    path = "/3.0/fictional_users"


class CompanyProfileStream(BexioUnpagedStream):
    """Company profile."""

    name = "company_profile"
    path = "/2.0/company_profile"


class PermissionsStream(BexioUnpagedStream):
    """Activated modules and permissions of the token's user (single record)."""

    name = "permissions"
    path = "/3.0/permissions"
    records_jsonpath = "$"
    primary_keys = ()


class CountriesStream(BexioOffsetStream):
    """Countries."""

    name = "countries"
    path = "/2.0/country"


class LanguagesStream(BexioOffsetStream):
    """Languages."""

    name = "languages"
    path = "/2.0/language"


class FilesStream(BexioOffsetStream):
    """Files in the inbox and archive (metadata only)."""

    name = "files"
    path = "/3.0/files"
    send_limit = False
    extra_params: t.ClassVar[dict[str, t.Any]] = {"archived_state": "all"}


STREAMS: list[type[BexioStream]] = [
    UsersStream,
    FictionalUsersStream,
    CompanyProfileStream,
    PermissionsStream,
    CountriesStream,
    LanguagesStream,
    FilesStream,
]
