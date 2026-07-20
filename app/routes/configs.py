"""Config list, manual run, and the full editor (M4).

Secret handling on edit: password-type fields render empty with a "leave unchanged"
placeholder. An empty submission keeps the stored secret; a non-empty one replaces
it. So secrets are never rendered back into HTML, and an unchanged form round-trips
without wiping them.

The description_regex_* fields are rendered read-only behind an "unlock" toggle,
because changing them after the first import breaks Firefly's hash-based duplicate
detection and creates doubles. Any actual change is written to the audit log.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from starlette.responses import RedirectResponse

from ..models import FILENAME_RE, FintsConfig, validate_filename
from .deps import ctx, render

router = APIRouter()

# Secret fields: empty on submit => keep the stored value (edit only).
SECRET_FIELDS = ("bank_password", "firefly_access_token", "bank_fints_persistence")


@router.get("/configs")
async def list_configs(request: Request):
    return render(request, "config_list.html", entries=ctx(request).store.list())


@router.get("/configs/new")
async def new_config_form(request: Request):
    return render(request, "config_form.html", mode="new", name="", data=_blank_form(),
                  errors={}, is_new=True)


@router.post("/configs")
async def create_config(request: Request):
    app_ctx = ctx(request)
    form = dict(await request.form())
    name = (form.get("filename") or "").strip()

    errors: dict[str, str] = {}
    if not FILENAME_RE.match(name):
        errors["filename"] = ("Dateiname muss zu [A-Za-z0-9._-]{1,64}.json passen — "
                              "keine Leerzeichen, keine Pfadtrenner.")
    elif app_ctx.store.exists(name):
        errors["filename"] = "Eine Config mit diesem Namen existiert bereits."

    # On create, secrets are required.
    for field in SECRET_FIELDS[:2]:  # persistence may be empty initially
        if not (form.get(field) or "").strip():
            errors[field] = "Pflichtfeld."

    config, model_errors = _build_config(form, existing=None)
    errors.update(model_errors)
    if errors:
        return render(request, "config_form.html", mode="new", name=name,
                      data=form, errors=errors, is_new=True)

    app_ctx.store.write(name, config)
    _audit(app_ctx, request, "config.create", name, "")
    return RedirectResponse("/configs", status_code=303)


@router.get("/configs/{name}/edit")
async def edit_config_form(request: Request, name: str):
    app_ctx = ctx(request)
    _require_config(app_ctx, name)
    try:
        cfg = app_ctx.store.read(name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Config is invalid: {exc}") from exc
    return render(request, "config_form.html", mode="edit", name=name,
                  data=_config_to_form(cfg), errors={}, is_new=False)


@router.post("/configs/{name}")
async def update_config(request: Request, name: str):
    app_ctx = ctx(request)
    _require_config(app_ctx, name)
    try:
        existing = app_ctx.store.read(name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Config is invalid: {exc}") from exc

    form = dict(await request.form())
    config, errors = _build_config(form, existing=existing)
    if errors:
        return render(request, "config_form.html", mode="edit", name=name,
                      data=form, errors=errors, is_new=False)

    # Audit a regex change specifically (it can create duplicates in Firefly).
    if (config.description_regex_match != existing.description_regex_match
            or config.description_regex_replace != existing.description_regex_replace):
        _audit(app_ctx, request, "config.regex_change", name,
               "description_regex_* changed")

    app_ctx.store.write(name, config)
    _audit(app_ctx, request, "config.update", name, "")
    return RedirectResponse("/configs", status_code=303)


@router.post("/configs/{name}/duplicate")
async def duplicate_config(request: Request, name: str):
    app_ctx = ctx(request)
    _require_config(app_ctx, name)
    form = dict(await request.form())
    dest = (form.get("dest") or "").strip()
    if not FILENAME_RE.match(dest) or app_ctx.store.exists(dest):
        raise HTTPException(status_code=400, detail="Invalid or existing destination name")
    app_ctx.store.duplicate(name, dest)
    _audit(app_ctx, request, "config.duplicate", name, f"-> {dest}")
    return RedirectResponse("/configs", status_code=303)


@router.get("/configs/{name}/delete")
async def confirm_delete(request: Request, name: str):
    app_ctx = ctx(request)
    _require_config(app_ctx, name)
    return render(request, "config_confirm_delete.html", name=name)


@router.post("/configs/{name}/delete")
async def delete_config(request: Request, name: str):
    app_ctx = ctx(request)
    _require_config(app_ctx, name)
    app_ctx.store.delete(name)
    from .. import schedules

    schedules.delete(app_ctx.conn, name)
    if app_ctx.scheduler is not None:
        app_ctx.scheduler.reconcile(app_ctx.conn)
    _audit(app_ctx, request, "config.delete", name, "")
    return RedirectResponse("/configs", status_code=303)


@router.get("/configs/{name}/persistence")
async def persistence_form(request: Request, name: str):
    app_ctx = ctx(request)
    _require_config(app_ctx, name)
    return render(request, "persistence_form.html", name=name, error=None)


@router.post("/configs/{name}/persistence")
async def save_persistence(request: Request, name: str):
    """Single-field update for the FinTS persistence string — the comfort win.
    Touches nothing else in the config, so there's no risk of clobbering it."""
    app_ctx = ctx(request)
    _require_config(app_ctx, name)
    form = dict(await request.form())
    value = (form.get("bank_fints_persistence") or "").strip()
    if not value:
        return render(request, "persistence_form.html", name=name,
                      error="Bitte den Persistence-String einfügen.")
    raw = app_ctx.store.read_raw(name)
    raw["bank_fints_persistence"] = value
    app_ctx.store.write_raw(name, raw)
    _audit(app_ctx, request, "config.persistence", name, "")
    return RedirectResponse("/configs", status_code=303)


@router.post("/configs/{name}/run")
async def run_now(request: Request, name: str):
    app_ctx = ctx(request)
    _require_config(app_ctx, name)
    result = await app_ctx.runner.execute(name, "manual")
    return RedirectResponse(f"/runs/{result.run_id}", status_code=303)


# --- helpers -----------------------------------------------------------------

def _require_config(app_ctx, name: str) -> None:
    try:
        validate_filename(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not app_ctx.store.exists(name):
        raise HTTPException(status_code=404, detail="Config not found")


def _blank_form() -> dict:
    return {
        "skip_transaction_review": "true",
        "from": "now - 7 days",
        "to": "now",
    }


def _config_to_form(cfg: FintsConfig) -> dict:
    ca = cfg.choose_account_automation
    return {
        "bank_username": cfg.bank_username.get_secret_value(),
        "bank_code": cfg.bank_code,
        "bank_url": cfg.bank_url,
        "bank_2fa": cfg.bank_2fa,
        "bank_2fa_device": cfg.bank_2fa_device,
        "firefly_url": cfg.firefly_url,
        "skip_transaction_review": cfg.skip_transaction_review,
        "description_regex_match": cfg.description_regex_match or "",
        "description_regex_replace": cfg.description_regex_replace or "",
        "auto_submit_form_via_js": cfg.auto_submit_form_via_js,
        "force_mt940": cfg.force_mt940,
        "bank_account_iban": ca.bank_account_iban,
        "firefly_account_id": ca.firefly_account_id,
        "from": ca.from_.root,
        "to": ca.to.root,
        # persistence present-flag only; never render the value
        "has_persistence": cfg.bank_fints_persistence is not None,
    }


def _build_config(form: dict, *, existing: FintsConfig | None) -> tuple[FintsConfig | None, dict]:
    """Build a FintsConfig from form data, preserving unchanged secrets on edit."""
    def secret(field: str) -> str:
        submitted = (form.get(field) or "").strip()
        if submitted:
            return submitted
        if existing is not None:
            current = getattr(existing, field)
            return current.get_secret_value() if current is not None else ""
        return ""

    payload = {
        "bank_username": (form.get("bank_username") or "").strip(),
        "bank_password": secret("bank_password"),
        "bank_code": (form.get("bank_code") or "").strip(),
        "bank_url": (form.get("bank_url") or "").strip(),
        "bank_2fa": (form.get("bank_2fa") or "").strip(),
        "bank_2fa_device": (form.get("bank_2fa_device") or "").strip(),
        "bank_fints_persistence": secret("bank_fints_persistence") or None,
        "firefly_url": (form.get("firefly_url") or "").strip(),
        "firefly_access_token": secret("firefly_access_token"),
        "skip_transaction_review": (form.get("skip_transaction_review") or "true").strip(),
        "description_regex_match": (form.get("description_regex_match") or "").strip() or None,
        "description_regex_replace": (form.get("description_regex_replace") or "").strip() or None,
        "auto_submit_form_via_js": _checkbox(form, "auto_submit_form_via_js"),
        "force_mt940": _checkbox(form, "force_mt940"),
        "choose_account_automation": {
            "bank_account_iban": (form.get("bank_account_iban") or "").strip(),
            "firefly_account_id": (form.get("firefly_account_id") or "").strip(),
            "from": (form.get("from") or "").strip(),
            "to": (form.get("to") or "").strip(),
        },
    }
    try:
        return FintsConfig.model_validate(payload), {}
    except ValidationError as exc:
        return None, _flatten_errors(exc)


def _checkbox(form: dict, name: str) -> bool:
    return (form.get(name) or "").strip() not in ("", "0", "false", "off")


def _flatten_errors(exc: ValidationError) -> dict:
    errors: dict[str, str] = {}
    for err in exc.errors():
        loc = err["loc"]
        # Map nested choose_account_automation fields onto their form names.
        field = str(loc[-1]) if loc else "form"
        if field == "from_":
            field = "from"
        errors[field] = err["msg"]
    return errors


def _audit(app_ctx, request: Request, action: str, target: str, detail: str) -> None:
    actor = "trusted-net" if getattr(request.state, "bypassed", False) else "user"
    app_ctx.conn.execute(
        "INSERT INTO audit (at, actor, action, target, detail) VALUES (?, ?, ?, ?, ?)",
        (datetime.now(UTC).isoformat(), actor, action, target, detail),
    )
