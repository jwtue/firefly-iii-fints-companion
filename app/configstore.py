"""Read/write importer config JSON files on the shared volume.

The JSON files are the single source of truth (AGENTS.md §6). This module never
keeps a second cleartext copy: writes are atomic (temp file + ``os.replace``) into
the same directory, and the catch-up window mutation in ``runner.py`` restores the
file in-place rather than cloning it.

Every write rebuilds the process-wide redactor from all current secrets so a
freshly-added credential is masked from that point on.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .models import FintsConfig, validate_filename
from .redact import Redactor, set_active_redactor


@dataclass(frozen=True, slots=True)
class ConfigListEntry:
    """Lightweight listing row — name plus whether it parses/validates."""

    name: str
    valid: bool
    error: str | None = None


class ConfigStore:
    def __init__(self, config_dir: Path | str) -> None:
        self.config_dir = Path(config_dir)

    def _path(self, name: str) -> Path:
        validate_filename(name)  # refuse traversal / spaces before touching the fs
        return self.config_dir / name

    # --- Reading -------------------------------------------------------------

    def list_names(self) -> list[str]:
        if not self.config_dir.is_dir():
            return []
        return sorted(p.name for p in self.config_dir.glob("*.json") if p.is_file())

    def list(self) -> list[ConfigListEntry]:
        entries: list[ConfigListEntry] = []
        for name in self.list_names():
            try:
                self.read(name)
                entries.append(ConfigListEntry(name, True))
            except Exception as exc:  # noqa: BLE001 — surface parse errors in the UI
                entries.append(ConfigListEntry(name, False, str(exc)))
        return entries

    def read(self, name: str) -> FintsConfig:
        raw = json.loads(self._path(name).read_text(encoding="utf-8"))
        return FintsConfig.model_validate(raw)

    def read_raw(self, name: str) -> dict:
        """Parse to a dict without model validation (for repair/inspection)."""
        return json.loads(self._path(name).read_text(encoding="utf-8"))

    def exists(self, name: str) -> bool:
        try:
            return self._path(name).is_file()
        except ValueError:
            return False

    # --- Writing -------------------------------------------------------------

    def write(self, name: str, config: FintsConfig) -> None:
        """Atomically write a validated config, then refresh the redactor."""
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(config.to_importer_json(), indent=4, ensure_ascii=False)
        self._atomic_write(path, payload)
        self.refresh_redactor()

    def write_raw(self, name: str, data: dict) -> None:
        """Write an already-shaped dict (used by catch-up window mutation)."""
        path = self._path(name)
        payload = json.dumps(data, indent=4, ensure_ascii=False)
        self._atomic_write(path, payload)
        self.refresh_redactor()

    @staticmethod
    def _atomic_write(path: Path, payload: str) -> None:
        # Same-directory temp file so os.replace is atomic on the same filesystem.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def duplicate(self, source: str, dest: str) -> None:
        if self.exists(dest):
            raise ValueError(f"Target {dest} already exists.")
        self.write(dest, self.read(source))

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)
        self.refresh_redactor()

    # --- Redactor ------------------------------------------------------------

    def collect_secrets(self) -> list[str]:
        secrets: list[str] = []
        for name in self.list_names():
            try:
                secrets.extend(self.read(name).secret_values())
            except Exception:  # noqa: BLE001 — a broken config must not disable redaction
                # Fall back to raw string values so secrets are still masked.
                try:
                    raw = self.read_raw(name)
                    for key in (
                        "bank_password",
                        "firefly_access_token",
                        "bank_fints_persistence",
                        "bank_username",
                    ):
                        val = raw.get(key)
                        if isinstance(val, str) and val:
                            secrets.append(val)
                except Exception:  # noqa: BLE001
                    continue
        return secrets

    def refresh_redactor(self) -> None:
        set_active_redactor(Redactor(self.collect_secrets()))
