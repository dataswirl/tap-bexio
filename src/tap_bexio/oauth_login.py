"""``tap-bexio-auth``: log in to bexio once in the browser and print a refresh token.

The bexio app's redirect URL must point at this machine (``http://localhost:<port>/...``);
the helper listens there for the single redirect that carries the authorization code.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import secrets
import sys
import typing as t
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import requests

from tap_bexio.config import DEFAULT_OAUTH_TOKEN_URL, OIDC_BASE_URL

if t.TYPE_CHECKING:
    from collections.abc import Sequence

AUTHORIZE_URL = f"{OIDC_BASE_URL}/auth"
DEFAULT_REDIRECT_URI = "http://localhost:8080/callback"
#: ``offline_access`` makes the refresh token non-expiring; the rest are the read scopes
#: the tap's streams use. bexio grants only those enabled for the app.
DEFAULT_SCOPES = (
    "openid offline_access accounting company_profile contact_show article_show "
    "kb_invoice_show kb_offer_show kb_order_show kb_delivery_show kb_bill_show "
    "kb_expense_show bank_account_show bank_payment_show project_show task_show "
    "note_show file payroll_employee_show payroll_absence_show"
)
TIMEOUT = 60


@dataclasses.dataclass(frozen=True)
class RedirectUri:
    """The app's registered redirect URL, split into where to listen."""

    url: str
    host: str
    port: int
    path: str

    @classmethod
    def parse(cls, url: str) -> RedirectUri:
        """Return the parts of ``url``; it must name a host and an explicit port."""
        parts = urlsplit(url)
        if not parts.hostname or not parts.port:
            msg = f"{url!r} needs a host and port, e.g. {DEFAULT_REDIRECT_URI}"
            raise argparse.ArgumentTypeError(msg)
        return cls(url, parts.hostname, parts.port, parts.path or "/")


class CallbackError(Exception):
    """The redirect did not carry a usable authorization code."""


def authorize_url(client_id: str, redirect_uri: str, scopes: str, state: str) -> str:
    """Return the URL that starts the browser login."""
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scopes,
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def code_from_callback(path: str, expected_state: str) -> str:
    """Return the authorization code from the redirect's path and query."""
    query = {key: values[0] for key, values in parse_qs(urlsplit(path).query).items()}
    if "error" in query:
        msg = f"bexio returned {query['error']}: {query.get('error_description', '')}"
        raise CallbackError(msg)
    if query.get("state") != expected_state:
        msg = "State mismatch; the redirect did not come from this login."
        raise CallbackError(msg)
    if not query.get("code"):
        msg = "The redirect carries no authorization code."
        raise CallbackError(msg)
    return query["code"]


def exchange_body(code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    """Return the form body that trades the authorization code for tokens."""
    return {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }


def wait_for_redirect(redirect: RedirectUri) -> str:
    """Serve requests on the redirect's host and port until it is hit; return its path."""
    received: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if urlsplit(self.path).path != redirect.path:
                self.send_error(404)
                return
            received.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Done. You can close this tab and return to the terminal.")

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass  # keep the terminal quiet

    with HTTPServer((redirect.host, redirect.port), Handler) as server:
        while not received:
            server.handle_request()
    return received[0]


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Return the command-line options."""
    parser = argparse.ArgumentParser(prog="tap-bexio-auth", description=__doc__)
    parser.add_argument("--client-id", default=os.environ.get("TAP_BEXIO_CLIENT_ID"))
    parser.add_argument("--client-secret", default=os.environ.get("TAP_BEXIO_CLIENT_SECRET"))
    parser.add_argument(
        "--redirect-uri",
        type=RedirectUri.parse,
        default=DEFAULT_REDIRECT_URI,
        help="Must match the redirect URL registered on the bexio app.",
    )
    parser.add_argument("--scopes", default=DEFAULT_SCOPES, help="Space-separated scopes.")
    parser.add_argument("--token-url", default=DEFAULT_OAUTH_TOKEN_URL)
    parser.add_argument("--json", action="store_true", help="Print the whole token response.")
    args = parser.parse_args(argv)
    if not args.client_id or not args.client_secret:
        parser.error(
            "--client-id and --client-secret (or TAP_BEXIO_CLIENT_ID / "
            "TAP_BEXIO_CLIENT_SECRET) are required."
        )
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """Run the browser login and print the refresh token."""
    args = parse_args(argv)
    state = secrets.token_urlsafe(16)
    redirect: RedirectUri = args.redirect_uri
    url = authorize_url(args.client_id, redirect.url, args.scopes, state)
    print(f"Opening the bexio login in your browser. If it does not open, visit:\n{url}\n")  # noqa: T201
    webbrowser.open(url)
    try:
        code = code_from_callback(wait_for_redirect(redirect), state)
    except CallbackError as exc:
        print(f"Login failed: {exc}", file=sys.stderr)  # noqa: T201
        return 1
    response = requests.post(
        args.token_url,
        data=exchange_body(code, args.client_id, args.client_secret, redirect.url),
        timeout=TIMEOUT,
    )
    if not response.ok:
        print(f"Token exchange failed ({response.status_code}): {response.text}", file=sys.stderr)  # noqa: T201
        return 1
    token = response.json()
    if args.json:
        print(json.dumps(token, indent=2))  # noqa: T201
        return 0
    print(f"Granted scopes: {token.get('scope', '')}\n")  # noqa: T201
    print("Store the refresh token with:\n")  # noqa: T201
    print(f"  meltano config tap-bexio set refresh_token '{token['refresh_token']}'")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
