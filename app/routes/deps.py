"""Small helpers shared by route modules."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import HTMLResponse

from .. import __version__
from ..i18n import SUPPORTED, lang_of, translate


def ctx(request: Request):
    return request.app.state.ctx


def render(request: Request, template: str, **context) -> HTMLResponse:
    """Render a template with the common context (csrf token, auth flags, i18n)."""
    app_ctx = ctx(request)
    lang = lang_of(request)
    base = {
        "csrf_token": getattr(request.state, "csrf", ""),
        "authenticated": getattr(request.state, "authenticated", False),
        "bypassed": getattr(request.state, "bypassed", False),
        "password_auth_enabled": app_ctx.settings.password_auth_enabled,
        # i18n: `t('key', **kwargs)` in templates, plus the current/available langs.
        "t": lambda key, **kw: translate(lang, key, **kw),
        "lang": lang,
        "languages": SUPPORTED,
        "current_path": request.url.path,
        "version": __version__,
    }
    base.update(context)
    # Modern Starlette signature: request first, then template name, then context.
    return app_ctx.templates.TemplateResponse(request, template, base)
