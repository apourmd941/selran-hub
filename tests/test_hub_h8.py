"""H8 tests — remote transport (Streamable HTTP / SSE) + bearer-token auth gate.

The security-critical units are tested directly: the loopback check, the
"non-loopback requires a token" rule, and the ASGI bearer-token middleware
(reject without / with a wrong token; pass with the right one). A live smoke
(below, run manually) boots the bridge in streamable-http mode and checks the
401/refusal behavior over real HTTP.
"""

import asyncio
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from selran_hub import mcp_bridge as br  # noqa: E402


# ----------------------------------------------------------- bind policy

def test_is_loopback():
    assert all(br._is_loopback(h) for h in ("127.0.0.1", "localhost", "::1", "LocalHost"))
    assert not any(br._is_loopback(h) for h in ("0.0.0.0", "1.2.3.4", "", "example.com"))


def test_loopback_needs_no_token():
    assert br.resolve_http_security("127.0.0.1", "") is False   # allowed, auth off
    assert br.resolve_http_security("127.0.0.1", "tok") is True  # auth on if token set


def test_non_loopback_requires_token():
    assert br.resolve_http_security("0.0.0.0", "tok") is True
    with pytest.raises(ValueError):
        br.resolve_http_security("0.0.0.0", "")          # refuse: network bind, no auth
    with pytest.raises(ValueError):
        br.resolve_http_security("192.168.1.5", "")


# ----------------------------------------------------------- auth middleware

def _drive(headers, scope_type="http"):
    """Run one ASGI request of `scope_type` through the middleware. Returns
    (sent_messages, inner_reached)."""
    reached = {"v": False}

    async def inner(scope, receive, send):
        reached["v"] = True
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

    mw = br.BearerAuthMiddleware(inner, "s3cret-token")
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(m):
        sent.append(m)

    scope = {"type": scope_type, "method": "POST", "path": "/mcp", "headers": headers or []}
    asyncio.run(mw(scope, receive, send))
    return sent, reached["v"]


def _status(sent):
    return next((m["status"] for m in sent if m["type"] == "http.response.start"), None)


def test_middleware_rejects_without_token():
    sent, reached = _drive([])
    assert _status(sent) == 401 and reached is False


def test_middleware_rejects_wrong_token():
    sent, reached = _drive([(b"authorization", b"Bearer wrong")])
    assert _status(sent) == 401 and reached is False


def test_middleware_rejects_non_bearer_scheme():
    sent, reached = _drive([(b"authorization", b"Basic s3cret-token")])
    assert _status(sent) == 401 and reached is False


def test_middleware_allows_correct_token():
    sent, reached = _drive([(b"authorization", b"Bearer s3cret-token")])
    assert _status(sent) == 200 and reached is True


def test_non_ascii_token_yields_401_not_crash():
    # Hostile input: a non-ASCII byte must 401, not raise (bytes compare).
    sent, reached = _drive([(b"authorization", b"Bearer \xff\xfe\x80")])
    assert _status(sent) == 401 and reached is False


def test_lifespan_scope_passes_through_unauthenticated():
    # Server lifecycle must reach the app (else the session manager never starts).
    sent, reached = _drive(None, scope_type="lifespan")
    assert reached is True


def test_websocket_scope_is_rejected():
    # Deny-by-default: a non-http connection scope never reaches the app.
    sent, reached = _drive([], scope_type="websocket")
    assert reached is False
    assert any(m["type"] == "websocket.close" for m in sent)
