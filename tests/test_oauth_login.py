"""The one-time browser login helper."""

from __future__ import annotations

import json
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from tap_bexio import oauth_login
from tap_bexio.oauth_login import (
    AUTHORIZE_URL,
    CallbackError,
    RedirectUri,
    authorize_url,
    code_from_callback,
    exchange_body,
)

REDIRECT = "http://localhost:8080/callback"


def test_authorize_url():
    url = authorize_url("id", REDIRECT, "openid offline_access", "s1")
    assert url.startswith(f"{AUTHORIZE_URL}?")
    assert parse_qs(urlsplit(url).query) == {
        "client_id": ["id"],
        "redirect_uri": [REDIRECT],
        "response_type": ["code"],
        "scope": ["openid offline_access"],
        "state": ["s1"],
    }


def test_default_scopes_include_offline_access():
    assert "offline_access" in oauth_login.DEFAULT_SCOPES.split()


def test_code_from_callback():
    assert code_from_callback("/callback?state=s1&code=abc&session_state=x", "s1") == "abc"


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("/callback?state=other&code=abc", "State mismatch"),
        ("/callback?state=s1", "no authorization code"),
        ("/callback?error=access_denied&error_description=nope&state=s1", "access_denied: nope"),
    ],
)
def test_bad_callback_is_rejected(path, message):
    with pytest.raises(CallbackError, match=message):
        code_from_callback(path, "s1")


def test_exchange_body():
    assert exchange_body("abc", "id", "secret", REDIRECT) == {
        "grant_type": "authorization_code",
        "code": "abc",
        "redirect_uri": REDIRECT,
        "client_id": "id",
        "client_secret": "secret",
    }


@pytest.mark.parametrize("argv", [[], ["--client-id", "id"], ["--client-secret", "secret"]])
def test_client_credentials_are_required(monkeypatch, argv):
    monkeypatch.delenv("TAP_BEXIO_CLIENT_ID", raising=False)
    monkeypatch.delenv("TAP_BEXIO_CLIENT_SECRET", raising=False)
    with pytest.raises(SystemExit):
        oauth_login.parse_args(argv)


def test_client_credentials_fall_back_to_env(monkeypatch):
    monkeypatch.setenv("TAP_BEXIO_CLIENT_ID", "id")
    monkeypatch.setenv("TAP_BEXIO_CLIENT_SECRET", "secret")
    args = oauth_login.parse_args([])
    assert (args.client_id, args.client_secret) == ("id", "secret")
    assert args.redirect_uri == RedirectUri(REDIRECT, "localhost", 8080, "/callback")


@pytest.mark.parametrize("url", ["http://localhost/callback", "/callback"])
def test_redirect_uri_needs_host_and_port(url):
    with pytest.raises(SystemExit):
        oauth_login.parse_args(["--client-id", "i", "--client-secret", "s", "--redirect-uri", url])


def test_redirect_uri_without_path_listens_on_root():
    assert RedirectUri.parse("http://127.0.0.1:9000").path == "/"


@pytest.fixture
def login(monkeypatch):
    """Run ``main`` with the browser replaced by a redirect to ``callback``."""

    def _run(callback: str, *extra: str) -> int:
        monkeypatch.setattr(oauth_login.webbrowser, "open", lambda _: True)
        monkeypatch.setattr(oauth_login.secrets, "token_urlsafe", lambda _: "s1")
        monkeypatch.setattr(oauth_login, "wait_for_redirect", lambda _: callback)
        return oauth_login.main(["--client-id", "id", "--client-secret", "secret", *extra])

    return _run


def test_main_prints_meltano_command(login, mocked, capsys):
    mocked.post(
        oauth_login.DEFAULT_OAUTH_TOKEN_URL,
        json={"access_token": "a", "refresh_token": "r1", "scope": "openid offline_access"},
    )
    assert login("/callback?state=s1&code=c") == 0
    assert "meltano config tap-bexio set refresh_token 'r1'" in capsys.readouterr().out
    assert parse_qs(mocked.calls[0].request.body)["code"] == ["c"]


def test_main_json_prints_the_token_response(login, mocked, capsys):
    mocked.post(oauth_login.DEFAULT_OAUTH_TOKEN_URL, json={"refresh_token": "r1"})
    assert login("/callback?state=s1&code=c", "--json") == 0
    assert json.loads(capsys.readouterr().out.split("\n\n", 1)[1]) == {"refresh_token": "r1"}


def test_main_fails_on_refused_exchange(login, mocked, capsys):
    mocked.post(oauth_login.DEFAULT_OAUTH_TOKEN_URL, status=400, json={"error": "invalid_grant"})
    assert login("/callback?state=s1&code=c") == 1
    assert "invalid_grant" in capsys.readouterr().err


def test_main_fails_on_bad_callback(login, capsys):
    assert login("/callback?state=forged&code=c") == 1
    assert "State mismatch" in capsys.readouterr().err


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("localhost", 0))
        return sock.getsockname()[1]


def browse(*urls: str) -> tuple[threading.Thread, list[requests.Response]]:
    """Request ``urls`` in order from a background thread, once the server is listening."""
    replies: list[requests.Response] = []

    def run() -> None:
        for url in urls:
            for _ in range(250):
                try:
                    replies.append(requests.get(url, timeout=2))
                    break
                except requests.ConnectionError:
                    time.sleep(0.02)

    browser = threading.Thread(target=run, daemon=True)
    browser.start()
    return browser, replies


def test_wait_for_redirect_returns_the_callback_and_ignores_other_paths():
    base = f"http://localhost:{free_port()}"
    browser, replies = browse(f"{base}/favicon.ico", f"{base}/callback?state=s1&code=c")
    redirect = RedirectUri.parse(f"{base}/callback")
    assert oauth_login.wait_for_redirect(redirect) == "/callback?state=s1&code=c"
    browser.join(5)
    assert [r.status_code for r in replies] == [404, 200]
    assert "close this tab" in replies[1].text
