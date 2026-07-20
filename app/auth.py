"""Authentication — session login by default, trusted-network bypass by config.

Real auth is the normal case; a config flag (``SIDECAR_TRUSTED_NETWORKS``) suspends
it for named local networks. The bypass decision uses the DIRECT socket peer only
(``request.client.host``) and never ``X-Forwarded-For`` — otherwise a single header
would spoof the bypass. If a reverse proxy sits in front, its container IP is the
peer; the operator must decide whether to trust that network.

CSRF: a signed double-submit token. The token is stored in the session and echoed
in a hidden form field; both must match on every POST.
"""

from __future__ import annotations

import ipaddress
import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from .settings import Settings

_ph = PasswordHasher()

SESSION_COOKIE = "sidecar_session"
CSRF_FIELD = "csrf_token"

# Paths reachable without auth. Everything else requires a session or a bypass.
PUBLIC_PATHS = frozenset({"/healthz", "/login", "/static"})


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(hash_: str, password: str) -> bool:
    try:
        return _ph.verify(hash_, password)
    except VerifyMismatchError:
        return False
    except Exception:  # noqa: BLE001 — malformed hash etc. => deny
        return False


@dataclass(frozen=True, slots=True)
class SessionData:
    authenticated: bool
    csrf: str


class AuthManager:
    """Owns token signing and the peer-trust decision."""

    def __init__(self, settings: Settings):
        self.settings = settings
        # A signing key is required whenever password auth is on; for a
        # bypass-only deployment we still need one for CSRF, so synthesize a
        # per-process key if none was configured.
        key = settings.secret_key or secrets.token_urlsafe(32)
        self._serializer = URLSafeTimedSerializer(key, salt="sidecar-session")

    # --- peer trust ----------------------------------------------------------

    def peer_is_trusted(self, request: Request) -> bool:
        if not self.settings.trusted_networks:
            return False
        client = request.client
        if client is None:
            return False
        try:
            peer = ipaddress.ip_address(client.host)
        except ValueError:
            return False
        return any(peer in net for net in self.settings.trusted_nets)

    # --- session tokens ------------------------------------------------------

    def issue_session(self) -> tuple[str, str]:
        """Return (cookie_value, csrf_token) for a freshly authenticated user."""
        csrf = secrets.token_urlsafe(24)
        cookie = self._serializer.dumps({"auth": True, "csrf": csrf})
        return cookie, csrf

    def load_session(self, request: Request) -> SessionData | None:
        raw = request.cookies.get(SESSION_COOKIE)
        if not raw:
            return None
        try:
            data = self._serializer.loads(raw, max_age=self.settings.session_max_age_seconds)
        except (BadSignature, Exception):  # noqa: BLE001
            return None
        return SessionData(authenticated=bool(data.get("auth")), csrf=str(data.get("csrf", "")))

    def set_session_cookie(self, response: Response, cookie_value: str) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            cookie_value,
            max_age=self.settings.session_max_age_seconds,
            httponly=True,
            samesite="strict",
            secure=self.settings.behind_tls,
            path="/",
        )

    def clear_session_cookie(self, response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE, path="/")


class AuthMiddleware(BaseHTTPMiddleware):
    """Gate every request: allow public paths, trusted peers, or valid sessions.

    Also enforces CSRF on state-changing methods. ``request.state`` is populated
    with ``authenticated``, ``bypassed`` and ``csrf`` for downstream handlers.
    """

    def __init__(self, app, auth: AuthManager):
        super().__init__(app)
        self.auth = auth

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        is_public = path == "/healthz" or path == "/login" or path.startswith("/static")

        bypassed = self.auth.peer_is_trusted(request)
        session = self.auth.load_session(request)
        authenticated = bypassed or (session is not None and session.authenticated)

        request.state.authenticated = authenticated
        request.state.bypassed = bypassed
        # CSRF token: from the session, or a transient one for bypassed peers.
        request.state.csrf = session.csrf if session else ""

        if not is_public and not authenticated:
            return RedirectResponse("/login", status_code=302)

        # CSRF check on mutating requests when not on a bypassed network. /login
        # is exempt: it is the bootstrap POST, before any session/CSRF exists.
        if (
            request.method in ("POST", "PUT", "PATCH", "DELETE")
            and not bypassed
            and path != "/login"
        ):
            if not await self._csrf_ok(request, session):
                return Response("CSRF token missing or invalid", status_code=403)

        return await call_next(request)

    async def _csrf_ok(self, request: Request, session: SessionData | None) -> bool:
        if session is None or not session.csrf:
            return False
        # Read the token without consuming the body for the handler: Starlette
        # caches the parsed form, so a later request.form() in the handler still works.
        form = await request.form()
        submitted = form.get(CSRF_FIELD)
        header = request.headers.get("x-csrf-token")
        candidate = submitted or header or ""
        return secrets.compare_digest(str(candidate), session.csrf)
