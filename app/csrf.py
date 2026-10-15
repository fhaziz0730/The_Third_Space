"""Session-bound CSRF tokens and same-origin checks for browser mutations."""

import hmac
import secrets
from urllib.parse import parse_qs, urlsplit

from starlette.requests import Request
from starlette.responses import PlainTextResponse

MAX_FORM_BYTES = 256 * 1024


def csrf_token(request):
    token = request.session.get("csrf_token")
    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def origin_of(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            return None
        return (parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80))
    except ValueError:
        return None


class CSRFMiddleware:
    def __init__(self, app, app_origin=""):
        self.app = app
        self.app_origin = app_origin

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in {"GET", "HEAD", "OPTIONS"}:
            return await self.app(scope, receive, send)
        request = Request(scope)
        expected_origin = origin_of(self.app_origin or str(request.base_url))
        source = request.headers.get("origin") or request.headers.get("referer")
        if (request.headers.get("sec-fetch-site") == "cross-site"
                or (source and origin_of(source) != expected_origin)):
            return await PlainTextResponse("Cross-origin form submission rejected.", status_code=403)(scope, receive, send)
        expected = request.session.get("csrf_token", "")
        supplied = request.headers.get("x-csrf-token", "")
        body = bytearray()
        if not supplied:
            # All current HTML forms use application/x-www-form-urlencoded.
            if request.headers.get("content-type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
                return await PlainTextResponse("Missing CSRF token. Reload the page and try again.", status_code=403)(scope, receive, send)
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > MAX_FORM_BYTES:
                    return await PlainTextResponse("Form is too large.", status_code=413)(scope, receive, send)
                if not message.get("more_body", False):
                    break
            try:
                tokens = parse_qs(body.decode("utf-8"), max_num_fields=1000).get("csrf_token", [])
                supplied = tokens[0] if len(tokens) == 1 else ""
            except (UnicodeError, ValueError):
                supplied = ""
        if (not isinstance(expected, str) or not expected or not supplied
                or len(supplied) > 256 or not hmac.compare_digest(expected.encode(), supplied.encode())):
            return await PlainTextResponse("Invalid CSRF token. Reload the page and try again.", status_code=403)(scope, receive, send)
        if not request.headers.get("x-csrf-token"):
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            return await self.app(scope, replay, send)
        await self.app(scope, receive, send)
