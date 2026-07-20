"""Minimal bilingual (de/en) i18n — no external dependencies.

Language resolution per request: an explicit ``lang`` cookie (set by the switcher)
wins; otherwise the ``Accept-Language`` header is consulted; otherwise English.

Translations are keyed by short semantic ids. English is the canonical fallback:
a missing key falls back to English, then to the key itself, so a typo is visible
rather than silently blank. ``t(...)`` supports ``str.format`` keyword arguments.
"""

from __future__ import annotations

from starlette.requests import Request

SUPPORTED = ("en", "de")
DEFAULT = "en"

# --- catalog -----------------------------------------------------------------
# Keep keys grouped by area. English first as the canonical source.

_EN: dict[str, str] = {
    # brand / nav / chrome
    "brand": "FinTS Companion",
    "nav.overview": "Overview",
    "nav.configs": "Configs",
    "nav.schedules": "Schedules",
    "nav.runs": "Runs",
    "session.bypass": "Trusted network",
    "session.bypass_title": "Access from a trusted network",
    "session.logout": "Log out",
    "footer.tagline": "Firefly III FinTS Companion — observability for the FinTS importer.",
    "lang.label": "Language",
    # generic actions
    "action.run_now": "Run now",
    "action.edit": "Edit",
    "action.delete": "Delete",
    "action.duplicate": "Duplicate",
    "action.cancel": "Cancel",
    "action.persistence": "Persistence",
    "common.none_dash": "–",
    # dashboard
    "dashboard.title": "Overview",
    "dashboard.empty": "No configs found in the config directory. Create one or mount the "
                       "config volume at {path}.",
    "dashboard.th.config": "Config",
    "dashboard.th.last_status": "Last status",
    "dashboard.th.transactions": "Transactions",
    "dashboard.th.time": "When",
    "dashboard.th.next_run": "Next run",
    "dashboard.no_run_yet": "no run yet",
    "config.invalid": "invalid",
    # config list
    "configs.title": "Configs",
    "configs.new": "+ New config",
    "configs.empty": "No configs yet. Create one or mount the config volume at {path}.",
    "configs.th.file": "File",
    "configs.th.state": "State",
    "configs.th.actions": "Actions",
    "state.valid": "valid",
    "state.invalid": "invalid",
    "configs.dup_prompt": "New filename (.json):",
    # config form
    "form.new_title": "New config",
    "form.edit_title": "Edit config",
    "form.back_to_configs": "← Back to configs",
    "form.filename": "Filename (no spaces, ends in .json)",
    "form.filename_help": "",
    "form.fs.bank_access": "Bank access",
    "form.username": "Login name",
    "form.password": "PIN / password",
    "form.ph.required": "required",
    "form.ph.unchanged": "leave unchanged",
    "form.bank_code": "Bank code (bank_code)",
    "form.bank_url": "FinTS URL",
    "form.fs.tan": "TAN method",
    "form.tan_help": "These values are <strong>not guessable</strong> — they are shown in the "
                     "importer UI after login and must be copied verbatim. Special value "
                     "<code>NoPsd2TanMode</code> for banks without a PSD2 TAN.",
    "form.bank_2fa": "TAN method code (bank_2fa)",
    "form.bank_2fa_device": "TAN medium (bank_2fa_device, no umlauts; only needed for headless)",
    "form.persist_state": "Persistence string (TAN-free follow-up logins):",
    "form.persist_set": "set",
    "form.persist_unset": "not set",
    "form.persist_link": "enter separately",
    "form.fs.firefly": "Firefly III",
    "form.firefly_url": "Firefly URL (stack-internal, e.g. http://firefly:8080)",
    "form.firefly_token": "Personal Access Token",
    "form.fs.account": "Account & window (headless)",
    "form.iban": "Bank IBAN",
    "form.firefly_account_id": "Firefly account id",
    "form.from": "From (from)",
    "form.to": "To (to)",
    "form.window_help": "The window must stay ≤ 90 days (PSD2 otherwise forces a second TAN).",
    "form.fs.reformat": "Description reformatting",
    "form.badge.care": "handle with care",
    "form.regex_warn": "Do <strong>not change after the first import</strong> — a format change "
                       "breaks Firefly's hash-based duplicate detection and creates duplicates.",
    "form.regex_unlock": "Unlock fields for editing",
    "form.fs.options": "Options",
    "form.force_mt940": "force_mt940 (force MT940 instead of CAMT)",
    "form.auto_submit": "auto_submit_form_via_js",
    "form.skip_review_note": "skip_transaction_review is fixed to <code>\"true\"</code> for headless.",
    "form.create": "Create",
    "form.save": "Save",
    # delete
    "delete.title": "Delete config",
    "delete.warning": "The config {name} and its schedule will be permanently removed. The JSON "
                      "file is deleted.",
    "delete.confirm": "Delete permanently",
    # persistence form
    "persist.title": "FinTS persistence string",
    "persist.help": "After a manual TAN run in the importer UI a new persistence string (base64) "
                    "is shown. Enter it here — it enables TAN-free follow-up logins until PSD2 "
                    "requires a TAN again in about 90 days. Only this one field is changed.",
    "persist.field": "Persistence string",
    "persist.save": "Save",
    "persist.enter_prompt": "Please paste the persistence string.",
    # login
    "login.title": "Log in",
    "login.password": "Password",
    "login.submit": "Log in",
    "login.disabled": "Password authentication is disabled. Access is only possible from a "
                      "trusted network (<code>SIDECAR_TRUSTED_NETWORKS</code>).",
    "login.invalid": "Invalid password.",
    "login.pw_auth_disabled": "Password authentication is disabled.",
    # runs
    "runs.title": "Run history",
    "runs.empty": "No runs yet.",
    "runs.th.num": "#",
    "runs.th.config": "Config",
    "runs.th.trigger": "Trigger",
    "runs.th.status": "Status",
    "runs.th.transactions": "Transactions",
    "runs.th.duration": "Duration",
    "runs.th.start": "Start",
    "run.back": "← Back to history",
    "run.title": "Run #{id} · {config}",
    "run.detail.status": "Status",
    "run.detail.detection": "Detection",
    "run.detail.trigger": "Trigger",
    "run.detail.transactions": "Transactions sent",
    "run.detail.start": "Start",
    "run.detail.end": "End",
    "run.detail.duration": "Duration",
    "run.detail.window": "Time window",
    "run.response.title": "Importer response",
    "run.response.note": "(redacted{orig})",
    "run.response.orig_bytes": ", original {n} bytes",
    "run.response.none": "No response body stored (e.g. timeout or connection error).",
    # schedules
    "schedules.title": "Schedules",
    "schedules.hint": "One cron schedule per config. Without a schedule a config runs only "
                      "manually. Runs execute sequentially — never two at once against the same bank.",
    "schedules.test_notify": "Send test notification",
    "schedules.th.config": "Config",
    "schedules.th.schedule": "Schedule",
    "schedules.th.cron": "Cron",
    "schedules.th.catchup": "Catch-up",
    "schedules.th.next_run": "Next run",
    "schedule.active": "active",
    "schedule.inactive": "inactive",
    "schedule.none": "none",
    "schedule.catchup_days": "≤ {n} d",
    "schedule.catchup_off": "off",
    "schedule.form_title": "Schedule",
    "schedule.back": "← Back to schedules",
    "schedule.enabled": "Schedule active",
    "schedule.cron": "Cron expression (5 fields: min hour day month weekday)",
    "schedule.cron_help": "Example: <code>0 1 * * *</code> = daily at 01:00.",
    "schedule.timezone": "Timezone",
    "schedule.fs.catchup": "Catch-up after an outage",
    "schedule.catchup_help": "After a detected outage the fetch window is widened automatically "
                             "for one run so no transactions are lost (Firefly's duplicate "
                             "detection absorbs the overlap).",
    "schedule.catchup_enabled": "Catch-up active",
    "schedule.catchup_max": "Maximum widening (days, ≤ 89 due to PSD2)",
    "schedule.save": "Save",
    # status badges
    "status.running": "running",
    "status.ok": "OK",
    "status.ok_no_transactions": "OK · 0 transactions",
    "status.tan_required": "TAN required",
    "status.tan_device_ambiguous": "TAN medium unclear",
    "status.config_not_found": "config not found",
    "status.verification_failed": "verification failed",
    "status.importer_error": "importer error",
    "status.stalled": "stalled / unknown",
    "status.timeout": "timeout",
    "status.unreachable": "unreachable",
    "status.internal_error": "internal error",
    # route/form validation messages
    "err.filename_invalid": "Filename must match [A-Za-z0-9._-]{{1,64}}.json — no spaces, no "
                            "path separators.",
    "err.filename_exists": "A config with this name already exists.",
    "err.required": "Required.",
}

_DE: dict[str, str] = {
    "brand": "FinTS Companion",
    "nav.overview": "Übersicht",
    "nav.configs": "Configs",
    "nav.schedules": "Zeitpläne",
    "nav.runs": "Läufe",
    "session.bypass": "Netz-Bypass",
    "session.bypass_title": "Zugriff aus vertrauenswürdigem Netz",
    "session.logout": "Abmelden",
    "footer.tagline": "Firefly III FinTS Companion — Beobachtbarkeit für den FinTS-Importer.",
    "lang.label": "Sprache",
    "action.run_now": "Jetzt ausführen",
    "action.edit": "Bearbeiten",
    "action.delete": "Löschen",
    "action.duplicate": "Duplizieren",
    "action.cancel": "Abbrechen",
    "action.persistence": "Persistence",
    "common.none_dash": "–",
    "dashboard.title": "Übersicht",
    "dashboard.empty": "Keine Configs im Config-Verzeichnis gefunden. Lege eine an oder mounte "
                       "das Config-Volume auf {path}.",
    "dashboard.th.config": "Config",
    "dashboard.th.last_status": "Letzter Status",
    "dashboard.th.transactions": "Umsätze",
    "dashboard.th.time": "Zeitpunkt",
    "dashboard.th.next_run": "Nächster Lauf",
    "dashboard.no_run_yet": "noch kein Lauf",
    "config.invalid": "ungültig",
    "configs.title": "Configs",
    "configs.new": "+ Neue Config",
    "configs.empty": "Keine Configs vorhanden. Lege eine an oder mounte das Config-Volume auf {path}.",
    "configs.th.file": "Datei",
    "configs.th.state": "Zustand",
    "configs.th.actions": "Aktionen",
    "state.valid": "gültig",
    "state.invalid": "ungültig",
    "configs.dup_prompt": "Neuer Dateiname (.json):",
    "form.new_title": "Neue Config",
    "form.edit_title": "Config bearbeiten",
    "form.back_to_configs": "← Zu den Configs",
    "form.filename": "Dateiname (ohne Leerzeichen, endet auf .json)",
    "form.filename_help": "",
    "form.fs.bank_access": "Bank-Zugang",
    "form.username": "Anmeldename",
    "form.password": "PIN / Passwort",
    "form.ph.required": "erforderlich",
    "form.ph.unchanged": "unverändert lassen",
    "form.bank_code": "BLZ (bank_code)",
    "form.bank_url": "FinTS-URL",
    "form.fs.tan": "TAN-Verfahren",
    "form.tan_help": "Diese Werte sind <strong>nicht ratbar</strong> — sie stehen in der "
                     "Importer-UI nach dem Login und müssen wörtlich übernommen werden. "
                     "Sonderwert <code>NoPsd2TanMode</code> für Banken ohne PSD2-TAN.",
    "form.bank_2fa": "TAN-Verfahren-Code (bank_2fa)",
    "form.bank_2fa_device": "TAN-Medium (bank_2fa_device, keine Umlaute; nur für headless nötig)",
    "form.persist_state": "Persistence-String (TAN-freie Folge-Logins):",
    "form.persist_set": "gesetzt",
    "form.persist_unset": "nicht gesetzt",
    "form.persist_link": "separat eintragen",
    "form.fs.firefly": "Firefly III",
    "form.firefly_url": "Firefly-URL (stack-intern, z.B. http://firefly:8080)",
    "form.firefly_token": "Personal Access Token",
    "form.fs.account": "Konto & Zeitfenster (headless)",
    "form.iban": "Bank-IBAN",
    "form.firefly_account_id": "Firefly-Konto-ID",
    "form.from": "Von (from)",
    "form.to": "Bis (to)",
    "form.window_help": "Fenster muss ≤ 90 Tage bleiben (PSD2 erzwingt sonst eine zweite TAN).",
    "form.fs.reformat": "Buchungstext-Umformung",
    "form.badge.care": "mit Vorsicht",
    "form.regex_warn": "Nach dem Erst-Import <strong>nicht mehr ändern</strong> — eine "
                       "Formatänderung bricht Fireflys hashbasierte Duplikaterkennung und "
                       "erzeugt Doubletten.",
    "form.regex_unlock": "Felder zum Bearbeiten entsperren",
    "form.fs.options": "Optionen",
    "form.force_mt940": "force_mt940 (MT940 statt CAMT erzwingen)",
    "form.auto_submit": "auto_submit_form_via_js",
    "form.skip_review_note": "skip_transaction_review ist für headless fest auf "
                             "<code>\"true\"</code>.",
    "form.create": "Anlegen",
    "form.save": "Speichern",
    "delete.title": "Config löschen",
    "delete.warning": "Die Config {name} und ihr Zeitplan werden dauerhaft entfernt. Die "
                      "JSON-Datei wird gelöscht.",
    "delete.confirm": "Endgültig löschen",
    "persist.title": "FinTS-Persistence-String",
    "persist.help": "Nach einem manuellen TAN-Durchlauf in der Importer-UI wird ein neuer "
                    "Persistence-String angezeigt (Base64). Hier eintragen — das ermöglicht "
                    "TAN-freie Folge-Logins, bis PSD2 in ca. 90 Tagen erneut eine TAN verlangt. "
                    "Es wird nur dieses eine Feld geändert.",
    "persist.field": "Persistence-String",
    "persist.save": "Speichern",
    "persist.enter_prompt": "Bitte den Persistence-String einfügen.",
    "login.title": "Anmelden",
    "login.password": "Passwort",
    "login.submit": "Anmelden",
    "login.disabled": "Passwort-Authentifizierung ist deaktiviert. Zugriff ist nur aus einem "
                      "vertrauenswürdigen Netz möglich (<code>SIDECAR_TRUSTED_NETWORKS</code>).",
    "login.invalid": "Ungültiges Passwort.",
    "login.pw_auth_disabled": "Passwort-Authentifizierung ist deaktiviert.",
    "runs.title": "Lauf-Historie",
    "runs.empty": "Noch keine Läufe.",
    "runs.th.num": "#",
    "runs.th.config": "Config",
    "runs.th.trigger": "Auslöser",
    "runs.th.status": "Status",
    "runs.th.transactions": "Umsätze",
    "runs.th.duration": "Dauer",
    "runs.th.start": "Start",
    "run.back": "← Zur Historie",
    "run.title": "Lauf #{id} · {config}",
    "run.detail.status": "Status",
    "run.detail.detection": "Erkennung",
    "run.detail.trigger": "Auslöser",
    "run.detail.transactions": "Umsätze übertragen",
    "run.detail.start": "Start",
    "run.detail.end": "Ende",
    "run.detail.duration": "Dauer",
    "run.detail.window": "Zeitfenster",
    "run.response.title": "Antwort des Importers",
    "run.response.note": "(redigiert{orig})",
    "run.response.orig_bytes": ", Original {n} Bytes",
    "run.response.none": "Kein Antwort-Body gespeichert (z. B. Timeout oder Verbindungsfehler).",
    "schedules.title": "Zeitpläne",
    "schedules.hint": "Ein Cron-Zeitplan pro Config. Ohne Zeitplan läuft eine Config nur "
                      "manuell. Läufe werden sequenziell ausgeführt — nie zwei gleichzeitig "
                      "gegen dieselbe Bank.",
    "schedules.test_notify": "Test-Benachrichtigung senden",
    "schedules.th.config": "Config",
    "schedules.th.schedule": "Zeitplan",
    "schedules.th.cron": "Cron",
    "schedules.th.catchup": "Catch-up",
    "schedules.th.next_run": "Nächster Lauf",
    "schedule.active": "aktiv",
    "schedule.inactive": "inaktiv",
    "schedule.none": "keiner",
    "schedule.catchup_days": "≤ {n} T",
    "schedule.catchup_off": "aus",
    "schedule.form_title": "Zeitplan",
    "schedule.back": "← Zu den Zeitplänen",
    "schedule.enabled": "Zeitplan aktiv",
    "schedule.cron": "Cron-Ausdruck (5 Felder: min std tag monat wochentag)",
    "schedule.cron_help": "Beispiel: <code>0 1 * * *</code> = täglich 01:00.",
    "schedule.timezone": "Zeitzone",
    "schedule.fs.catchup": "Catch-up nach Ausfall",
    "schedule.catchup_help": "Nach einem erkannten Ausfall wird das Abruffenster für einen Lauf "
                             "automatisch geweitet, damit keine Umsätze verloren gehen (Fireflys "
                             "Duplikaterkennung fängt die Überlappung ab).",
    "schedule.catchup_enabled": "Catch-up aktiv",
    "schedule.catchup_max": "Maximale Weitung (Tage, ≤ 89 wegen PSD2)",
    "schedule.save": "Speichern",
    "status.running": "läuft",
    "status.ok": "OK",
    "status.ok_no_transactions": "OK · 0 Umsätze",
    "status.tan_required": "TAN erforderlich",
    "status.tan_device_ambiguous": "TAN-Medium unklar",
    "status.config_not_found": "Config nicht gefunden",
    "status.verification_failed": "Verifikation fehlgeschlagen",
    "status.importer_error": "Importer-Fehler",
    "status.stalled": "Abgebrochen / unbekannt",
    "status.timeout": "Timeout",
    "status.unreachable": "Nicht erreichbar",
    "status.internal_error": "Interner Fehler",
    "err.filename_invalid": "Dateiname muss zu [A-Za-z0-9._-]{{1,64}}.json passen — keine "
                            "Leerzeichen, keine Pfadtrenner.",
    "err.filename_exists": "Eine Config mit diesem Namen existiert bereits.",
    "err.required": "Pflichtfeld.",
}

CATALOG: dict[str, dict[str, str]] = {"en": _EN, "de": _DE}


def translate(lang: str, key: str, **kwargs) -> str:
    table = CATALOG.get(lang, _EN)
    text = table.get(key)
    if text is None:
        text = _EN.get(key, key)  # fall back to English, then to the key itself
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def _parse_accept_language(header: str) -> str | None:
    """Return the preferred supported language from an Accept-Language header."""
    best_lang, best_q = None, -1.0
    for part in header.split(","):
        part = part.strip()
        if not part:
            continue
        tok, _, params = part.partition(";")
        code = tok.strip().lower()[:2]
        if code not in SUPPORTED:
            continue
        q = 1.0
        if params.strip().startswith("q="):
            try:
                q = float(params.strip()[2:])
            except ValueError:
                q = 1.0
        if q > best_q:
            best_lang, best_q = code, q
    return best_lang


def resolve_lang(cookie: str | None, accept_language: str | None) -> str:
    if cookie in SUPPORTED:
        return cookie  # type: ignore[return-value]
    if accept_language:
        picked = _parse_accept_language(accept_language)
        if picked:
            return picked
    return DEFAULT


def lang_of(request: Request) -> str:
    """Resolve (and cache on request.state) the language for this request."""
    cached = getattr(request.state, "lang", None)
    if cached in SUPPORTED:
        return cached
    lang = resolve_lang(request.cookies.get("lang"), request.headers.get("accept-language"))
    request.state.lang = lang
    return lang


def t(request: Request, key: str, **kwargs) -> str:
    """Convenience for route handlers: translate in the request's language."""
    return translate(lang_of(request), key, **kwargs)
