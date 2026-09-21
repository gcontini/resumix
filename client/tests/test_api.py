"""HttpApi's own plumbing: the health check and the version compatibility it
now carries. ``version_compat`` is pure, so most of this needs no transport;
the two behavioural tests fake ``/healthz`` with an ``httpx.MockTransport``
rather than a real server, per AGENTS.md — fake at the boundary, not above it.
"""

from __future__ import annotations

import httpx
import pytest

from resumix_client import __version__
from resumix_client.api import HttpApi, ResumixError, version_compat


@pytest.mark.parametrize("client_version, server_version, expected", [
    ("1.2.3", "1.2.9", "ok"),
    ("1.2.3", "1.2.3", "ok"),
    ("1.2.3", "1.3.0", "warn"),
    ("1.2.3", "1.1.0", "warn"),
    ("1.2.3", "2.0.0", "stop"),
    ("2.0.0", "1.9.9", "stop"),
    ("1.2.3", "unknown", "ok"),
    ("unknown", "1.2.3", "ok"),
    ("1.2.3", "1", "ok"),
])
def test_version_compat(client_version, server_version, expected):
    assert version_compat(client_version, server_version) == expected


def _client_reporting(version: str) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "request_id": "r1", "ok": True,
            "data": {"status": "ok", "version": version, "pdflatex": True,
                     "models": {}, "auth_required": False},
        })

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://server.invalid")


def _bump(part: int, by: int = 1) -> str:
    pieces = __version__.split(".")
    pieces[part] = str(int(pieces[part]) + by)
    return ".".join(pieces)


def test_a_minor_mismatch_warns_and_continues(capsys):
    api = HttpApi("http://server.invalid", client=_client_reporting(_bump(1)))

    api._ensure_healthy()  # does not raise

    assert "minor versions differ" in capsys.readouterr().err


def test_a_major_mismatch_stops_before_the_first_call():
    api = HttpApi("http://server.invalid", client=_client_reporting(_bump(0)))

    with pytest.raises(ResumixError, match="major versions differ"):
        api._ensure_healthy()


def test_a_matching_version_is_quiet(capsys):
    api = HttpApi("http://server.invalid", client=_client_reporting(__version__))

    api._ensure_healthy()

    assert capsys.readouterr().err == ""
