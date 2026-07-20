"""Validation tests for the config models and the config store."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.configstore import ConfigStore
from app.models import FintsConfig, validate_filename


def base_config(**overrides) -> dict:
    data = {
        "bank_username": "user1",
        "bank_password": "secret-pin-1234",
        "bank_code": "60050101",
        "bank_url": "https://bank.example/fints30",
        "bank_2fa": "pushTAN",
        "bank_2fa_device": "",
        "bank_fints_persistence": "cGVyc2lzdGVuY2VibG9i",
        "firefly_url": "http://firefly:8080",
        "firefly_access_token": "tok-abc",
        "skip_transaction_review": "true",
        "auto_submit_form_via_js": False,
        "force_mt940": False,
        "choose_account_automation": {
            "bank_account_iban": "DE00600501010000000000",
            "firefly_account_id": 3,
            "from": "now - 7 days",
            "to": "now",
        },
    }
    ca = overrides.pop("choose_account_automation", None)
    data.update(overrides)
    if ca:
        data["choose_account_automation"].update(ca)
    return data


def test_valid_config_parses():
    cfg = FintsConfig.model_validate(base_config())
    assert cfg.skip_transaction_review == "true"


def test_window_over_90_days_rejected():
    with pytest.raises(ValidationError, match="90 days"):
        FintsConfig.model_validate(
            base_config(choose_account_automation={"from": "now - 91 days", "to": "now"})
        )


def test_window_exactly_90_days_accepted():
    cfg = FintsConfig.model_validate(
        base_config(choose_account_automation={"from": "now - 90 days", "to": "now"})
    )
    assert cfg.choose_account_automation.window_span_days() == 90


def test_window_to_before_from_rejected():
    with pytest.raises(ValidationError, match="after"):
        FintsConfig.model_validate(
            base_config(choose_account_automation={"from": "now", "to": "now - 5 days"})
        )


def test_skip_review_must_be_string_true():
    with pytest.raises(ValidationError):
        FintsConfig.model_validate(base_config(skip_transaction_review="false"))


def test_skip_review_serializes_as_string_not_bool():
    """Assert on the JSON bytes: the importer string-compares this field."""
    cfg = FintsConfig.model_validate(base_config())
    raw = json.dumps(cfg.to_importer_json())
    assert '"skip_transaction_review": "true"' in raw
    assert '"skip_transaction_review": true' not in raw


def test_device_with_umlaut_rejected():
    with pytest.raises(ValidationError, match="umlaut"):
        FintsConfig.model_validate(base_config(bank_2fa_device="Mobiltelefon-Büro"))


def test_secrets_do_not_leak_in_repr():
    cfg = FintsConfig.model_validate(base_config())
    assert "secret-pin-1234" not in repr(cfg)
    assert "secret-pin-1234" not in str(cfg)


@pytest.mark.parametrize("bad", ["has space.json", "../escape.json", "no-ext", "sub/dir.json"])
def test_bad_filenames_rejected(bad):
    with pytest.raises(ValueError):
        validate_filename(bad)


@pytest.mark.parametrize("good", ["giro.json", "tages_geld.json", "acct-1.json"])
def test_good_filenames_accepted(good):
    assert validate_filename(good) == good


def test_store_roundtrip_preserves_string_true(tmp_path):
    store = ConfigStore(tmp_path)
    cfg = FintsConfig.model_validate(base_config())
    store.write("giro.json", cfg)
    on_disk = json.loads((tmp_path / "giro.json").read_text(encoding="utf-8"))
    assert on_disk["skip_transaction_review"] == "true"
    assert on_disk["bank_password"] == "secret-pin-1234"  # written cleartext for the importer
    reloaded = store.read("giro.json")
    assert reloaded.bank_password.get_secret_value() == "secret-pin-1234"


def test_store_lists_and_flags_invalid(tmp_path):
    store = ConfigStore(tmp_path)
    store.write("ok.json", FintsConfig.model_validate(base_config()))
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    entries = {e.name: e for e in store.list()}
    assert entries["ok.json"].valid
    assert not entries["broken.json"].valid


def test_store_refresh_redactor_masks_new_secret(tmp_path):
    from app.redact import get_active_redactor

    store = ConfigStore(tmp_path)
    store.write("giro.json", FintsConfig.model_validate(base_config(bank_password="MEGA-SECRET-PIN-42")))
    r = get_active_redactor()
    assert "MEGA-SECRET-PIN-42" not in (r("leak MEGA-SECRET-PIN-42") or "")
