"""Authenticators: a static Bearer token, or OAuth with a refresh token."""

from __future__ import annotations

import datetime as dt

from singer_sdk.authenticators import BearerTokenAuthenticator, OAuthAuthenticator
from singer_sdk.exceptions import FatalAPIError

from tap_bexio.config import OAuthCredentials, TokenAuth

#: Refresh this many seconds before the access token expires, so no request carries a
#: token that dies in flight.
EXPIRY_MARGIN = 60
#: Lifetime assumed when the token response has no ``expires_in`` (bexio sends 3600).
DEFAULT_EXPIRATION = 3600
TOKEN_REQUEST_TIMEOUT = 60


class BexioOAuthAuthenticator(OAuthAuthenticator):
    """Exchange a refresh token for short-lived access tokens, refreshing them as needed."""

    def __init__(self, credentials: OAuthCredentials) -> None:
        """Store the credentials; the first request fetches an access token."""
        super().__init__(
            auth_endpoint=credentials.token_url,
            client_id=credentials.client_id,
            client_secret=credentials.client_secret,
        )
        self.refresh_token = credentials.refresh_token
        #: When to fetch the next access token (``EXPIRY_MARGIN`` before it expires).
        self.valid_until: dt.datetime | None = None

    @property
    def oauth_request_body(self) -> dict[str, str | None]:
        """Return the ``refresh_token`` grant."""
        return {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

    def is_token_valid(self) -> bool:
        """Return whether an access token is held and has not reached its refresh time."""
        return self.valid_until is not None and _now() < self.valid_until

    def update_access_token(self) -> None:
        """Fetch a new access token; fail the sync if bexio refuses the refresh token."""
        self.logger.info("Requesting new access token")
        requested_at = _now()
        response = self._session.post(
            self.auth_endpoint, data=self.oauth_request_payload, timeout=TOKEN_REQUEST_TIMEOUT
        )
        if not response.ok:
            msg = (
                f"bexio refused the token refresh (HTTP {response.status_code}: "
                f"{response.text[:500]}). Check client_id and client_secret, or run "
                "tap-bexio-auth to get a new refresh_token."
            )
            raise FatalAPIError(msg)
        token = response.json()
        self.access_token = token["access_token"]
        lifetime = int(token.get("expires_in") or DEFAULT_EXPIRATION)
        self.valid_until = requested_at + dt.timedelta(seconds=lifetime - EXPIRY_MARGIN)
        self._note_rotation(token.get("refresh_token"))

    def _note_rotation(self, new_refresh_token: str | None) -> None:
        """Use a rotated refresh token for the rest of the run and tell the user to store it."""
        if not new_refresh_token or new_refresh_token == self.refresh_token:
            return
        self.refresh_token = new_refresh_token
        self.logger.warning(
            "bexio issued a new refresh token. If later runs fail with an invalid refresh "
            "token, update the refresh_token setting (run tap-bexio-auth)."
        )


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def make_authenticator(
    auth: TokenAuth | OAuthCredentials,
) -> BearerTokenAuthenticator | BexioOAuthAuthenticator:
    """Return the authenticator for the configured auth mode."""
    if isinstance(auth, TokenAuth):
        return BearerTokenAuthenticator(token=auth.token)
    return BexioOAuthAuthenticator(auth)
