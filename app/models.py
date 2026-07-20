"""Pydantic models for the importer config JSON.

These mirror ``app/ConfigurationFactory.php`` in the importer. The importer is the
consumer of what we write, so field names and quirks are dictated by it, not by us:

* ``skip_transaction_review`` is the STRING ``"true"``, not a bool — the importer
  compares it as a string.
* the ``from`` window key collides with a Python keyword, hence the ``from_`` alias.
* secrets are typed ``SecretStr`` so an accidental ``repr()`` cannot leak them; use
  ``.get_secret_value()`` at the serialization boundary only.

The business constraints from AGENTS.md live in the validators: the 90-day PSD2
window ceiling and the filename rules.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    SecretStr,
    field_validator,
    model_validator,
)

# Filename: no spaces (lands unquoted in the automate URL), no path separators
# (the importer applies basename(), but we refuse traversal defensively anyway).
FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}\.json$")

# PSD2 forces a second TAN mid-dialog beyond 90 days; the importer cannot resume
# that (session serialization loses the dialog state → errors 9050/9800/9010).
MAX_WINDOW_DAYS = 90
# Above this we warn but still allow — a heads-up before the hard ceiling.
WARN_WINDOW_DAYS = 80

# Sentinel accepted by the importer for banks without a PSD2 TAN mode.
NO_PSD2_TAN_MODE = "NoPsd2TanMode"


def validate_filename(name: str) -> str:
    if not FILENAME_RE.match(name):
        raise ValueError(
            "Filename must match [A-Za-z0-9._-]{1,64}.json — no spaces (it lands "
            "unquoted in the importer URL), no path separators."
        )
    return name


# Module-level so it is not captured as a Pydantic private attribute on the model.
_TIME_EXPR_RE = re.compile(
    r"^\s*(?:now|now\s*-\s*(\d+)\s+(day|week|month)s?|(\d{4}-\d{2}-\d{2}))\s*$",
    re.IGNORECASE,
)


class TimeExpr(RootModel[str]):
    """A PHP ``DateTime``-compatible subset used by the importer's from/to window.

    Accepts ``now``, ``now - N day|week|month[s]`` and an ISO ``YYYY-MM-DD`` date.
    ``resolve(ref)`` turns it into a concrete date relative to a reference day so
    the window span can be checked.
    """

    @field_validator("root")
    @classmethod
    def _check(cls, v: str) -> str:
        if not _TIME_EXPR_RE.match(v):
            raise ValueError(
                "Time expression must be 'now', 'now - N days|weeks|months' or "
                "an ISO date YYYY-MM-DD."
            )
        return v.strip()

    def resolve(self, ref: date) -> date:
        m = _TIME_EXPR_RE.match(self.root)
        assert m is not None  # validated on construction
        if m.group(3):  # ISO date
            return date.fromisoformat(m.group(3))
        if m.group(1) is None:  # bare 'now'
            return ref
        n = int(m.group(1))
        unit = m.group(2).lower()
        days = {"day": 1, "week": 7, "month": 30}[unit] * n
        return ref - timedelta(days=days)


class ChooseAccountAutomation(BaseModel):
    """The headless-only block. All four fields are mandatory for automated runs."""

    model_config = ConfigDict(populate_by_name=True)

    bank_account_iban: str
    firefly_account_id: int
    from_: TimeExpr = Field(alias="from")
    to: TimeExpr

    @model_validator(mode="after")
    def _window_within_psd2_ceiling(self) -> "ChooseAccountAutomation":
        today = date.today()
        span = (self.to.resolve(today) - self.from_.resolve(today)).days
        if span <= 0:
            raise ValueError("'to' must be after 'from'.")
        if span > MAX_WINDOW_DAYS:
            raise ValueError(
                f"Window is {span} days. Beyond {MAX_WINDOW_DAYS} days PSD2 forces a "
                f"second TAN mid-dialog that the importer cannot resume (errors "
                f"9050/9800/9010). Keep the window ≤ {MAX_WINDOW_DAYS} days."
            )
        return self

    def window_span_days(self, ref: date | None = None) -> int:
        ref = ref or date.today()
        return (self.to.resolve(ref) - self.from_.resolve(ref)).days


class FintsConfig(BaseModel):
    """One importer configuration file.

    Populated by field name or by JSON alias. Serialize with
    :meth:`to_importer_json` so secrets and the string-typed ``skip_transaction_review``
    round-trip exactly as the importer expects.
    """

    model_config = ConfigDict(populate_by_name=True)

    bank_username: SecretStr
    bank_password: SecretStr
    bank_code: str
    bank_url: str
    bank_2fa: str
    bank_2fa_device: str = ""
    bank_fints_persistence: SecretStr | None = None

    firefly_url: str
    firefly_access_token: SecretStr

    # STRING "true", not bool — the importer string-compares this.
    skip_transaction_review: str = "true"

    description_regex_match: str | None = None
    description_regex_replace: str | None = None

    auto_submit_form_via_js: bool = False
    force_mt940: bool = False

    choose_account_automation: ChooseAccountAutomation

    @field_validator("bank_2fa_device")
    @classmethod
    def _device_no_umlauts(cls, v: str) -> str:
        # The importer's getTanMedia() strings must be copied verbatim, but umlauts
        # are known to break the match — surface that as a validation error.
        if any(ch in v for ch in "äöüÄÖÜß"):
            raise ValueError("bank_2fa_device must not contain umlauts (breaks the match).")
        return v

    @field_validator("skip_transaction_review")
    @classmethod
    def _skip_review_is_string_true(cls, v: str) -> str:
        if v != "true":
            raise ValueError('skip_transaction_review must be the string "true" for headless runs.')
        return v

    def secret_values(self) -> list[str]:
        """All secret strings in this config, for feeding the redactor."""
        out: list[str] = []
        for s in (
            self.bank_password,
            self.firefly_access_token,
            self.bank_fints_persistence,
            self.bank_username,
        ):
            if isinstance(s, SecretStr):
                out.append(s.get_secret_value())
        return out

    def to_importer_json(self) -> dict:
        """Serialize to the exact dict shape the importer reads.

        Secrets are unwrapped here — this is the only place they leave SecretStr,
        and only to be written to the shared config volume.
        """
        return {
            "bank_username": self.bank_username.get_secret_value(),
            "bank_password": self.bank_password.get_secret_value(),
            "bank_code": self.bank_code,
            "bank_url": self.bank_url,
            "bank_2fa": self.bank_2fa,
            "bank_2fa_device": self.bank_2fa_device,
            "bank_fints_persistence": (
                self.bank_fints_persistence.get_secret_value()
                if self.bank_fints_persistence
                else ""
            ),
            "firefly_url": self.firefly_url,
            "firefly_access_token": self.firefly_access_token.get_secret_value(),
            "skip_transaction_review": self.skip_transaction_review,
            "description_regex_match": self.description_regex_match or "",
            "description_regex_replace": self.description_regex_replace or "",
            "auto_submit_form_via_js": self.auto_submit_form_via_js,
            "force_mt940": self.force_mt940,
            "choose_account_automation": {
                "bank_account_iban": self.choose_account_automation.bank_account_iban,
                "firefly_account_id": self.choose_account_automation.firefly_account_id,
                "from": self.choose_account_automation.from_.root,
                "to": self.choose_account_automation.to.root,
            },
        }
