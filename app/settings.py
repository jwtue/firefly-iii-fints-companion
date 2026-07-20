"""Application settings — fail-closed by construction.

Auth model (per the approved plan): real session auth is the default; a config flag
suspends it for trusted local networks. The container must refuse to start in an
ambiguous state, so :meth:`Settings.validate_auth` raises unless the app is either
password-protected or explicitly opened to named networks.

All settings are read from the environment with the ``SIDECAR_`` prefix, e.g.
``SIDECAR_PASSWORD_HASH``, ``SIDECAR_TRUSTED_NETWORKS``.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SIDECAR_",
        env_file=".env",
        extra="ignore",
    )

    # --- Paths ---------------------------------------------------------------
    # The shared config volume. MUST be mounted at /data/configurations against
    # the importer (see AGENTS.md §3 — /app/configurations silently fails).
    config_dir: Path = Path("/data/configurations")
    # Sidecar-owned state (SQLite). Separate from the config volume.
    state_dir: Path = Path("/data/state")

    # --- Importer ------------------------------------------------------------
    importer_base_url: str = "http://firefly-fints-importer:8080"
    importer_timeout_seconds: float = 600.0
    # Flip on once the upstream status PR (M0) is deployed to append &format=json
    # and trust the machine-readable status.
    importer_supports_json: bool = False

    # --- Auth ----------------------------------------------------------------
    # argon2 hash of the single-user password. Empty => password auth disabled.
    password_hash: str = ""
    # CIDRs whose *direct peer* bypasses login. Empty => no bypass.
    # NOTE: evaluated against the direct socket peer only, never X-Forwarded-For.
    # NoDecode: take the raw env string and split it ourselves (see validator),
    # rather than letting pydantic-settings JSON-decode it.
    trusted_networks: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Signing key for session + CSRF tokens. Required whenever password auth is on.
    secret_key: str = ""
    session_max_age_seconds: int = 8 * 3600

    # --- Notifications -------------------------------------------------------
    # Apprise-style URLs, comma-separated. Supported schemes: ntfy(s), tgram(s).
    # Example: "ntfy://ntfy.example/firefly,tgram://<bottoken>/<chatid>"
    notify_urls: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Server --------------------------------------------------------------
    bind_host: str = "0.0.0.0"
    bind_port: int = 8080
    # Set true only when TLS terminates upstream and the app is never reached
    # over plain HTTP; controls the Secure flag on the session cookie.
    behind_tls: bool = True

    @field_validator("trusted_networks", "notify_urls", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [part.strip() for part in v.split(",") if part.strip()]
        return v

    @field_validator("trusted_networks")
    @classmethod
    def _validate_cidrs(cls, v: list[str]) -> list[str]:
        for cidr in v:
            ipaddress.ip_network(cidr, strict=False)  # raises on malformed input
        return v

    @property
    def trusted_nets(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        return [ipaddress.ip_network(c, strict=False) for c in self.trusted_networks]

    @property
    def password_auth_enabled(self) -> bool:
        return bool(self.password_hash)

    def validate_auth(self) -> None:
        """Fail-closed gate. Called at startup; raises to abort the container.

        Valid states:
          * password auth on  → needs a secret_key too.
          * password auth off → allowed ONLY if trusted_networks is non-empty,
            i.e. the operator deliberately opened the app to named networks.
        A fully-open, passwordless, network-unrestricted config is refused.
        """
        if self.password_auth_enabled:
            if not self.secret_key or len(self.secret_key) < 16:
                raise RuntimeError(
                    "SIDECAR_SECRET_KEY (≥16 chars) is required when password auth is enabled."
                )
            return
        if not self.trusted_networks:
            raise RuntimeError(
                "Refusing to start unauthenticated: set SIDECAR_PASSWORD_HASH to require "
                "login, or SIDECAR_TRUSTED_NETWORKS to explicitly bypass auth for named "
                "networks. This app edits bank credentials in cleartext — it will not run "
                "wide open."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
