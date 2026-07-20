# Firefly III FinTS Companion

A companion service for the FinTS importer
[`bnw/firefly-iii-fints-importer`](https://github.com/bnw/firefly-iii-fints-importer). It adds
a web UI, scheduling, run history and notifications on top of the importer **without modifying
it** — it runs as its own container next to the importer, shares the importer's configuration
directory, and triggers imports over the importer's HTTP interface.

Image: `ghcr.io/jwtue/firefly-iii-fints-companion` (`linux/arm64`).

## What it does

- **Configuration management** — create, edit, duplicate and delete the importer's per-account
  JSON configs through a form, with validation (90-day window limit, filename rules, required
  headless fields) and inline help for the fields that can't be guessed.
- **Scheduling** — a cron schedule per config. Runs execute sequentially through a global lock,
  so two runs never hit the same bank at once. Nothing runs at container start.
- **Run history** — every run is stored with its timestamp, trigger, outcome, duration and the
  (redacted) importer response body, all viewable in the UI.
- **Reliable outcome detection** — the importer answers everything with HTTP 200 and HTML, so
  outcomes are classified from the response. Anything not recognized as a success — a missing
  config, a TAN prompt, a fatal error, an unknown page — is recorded as a **failure**, never a
  silent success.
- **Notifications** — ntfy and Telegram (apprise-style URLs) on failed runs and on "TAN
  required", plus an hourly dead-man's switch that alerts when a scheduled config stops
  succeeding. Every outbound message is redacted.
- **Catch-up** — after a missed run the fetch window is temporarily widened for a single run so
  no transactions are lost, then restored (Firefly's duplicate detection absorbs the overlap).

## What it does not do

- **Answer TANs.** The FinTS session lives inside the importer process, so a headless run cannot
  complete a TAN challenge. The companion notifies that a TAN is due; the user completes it once
  through the importer UI and pastes the new persistence string back in (a dedicated one-field
  form exists for this). PSD2 requires this roughly every 90 days regardless.
- **Credit-card imports.** Out of scope.
- **Modify the importer.** It is used as an unmodified upstream image.

## How it works

The companion and the importer share the config directory (mounted at
`/data/configurations` on the importer). A run is triggered with
`GET /?automate=true&config=<name>.json`.

Outcome detection is an adapter chain, first match wins:

1. `JsonStatusDetector` — used when the importer returns a JSON status (`&format=json`).
2. `HttpStatusDetector` — used when the response carries a real HTTP status code (≠ 200).
3. `HtmlHeuristicDetector` — the fallback: it parses the HTML and **defaults to failure** for
   anything it does not positively recognize as success.

State (run history, schedules, audit log) is kept in SQLite. Configs remain the single source
of truth as JSON on the shared volume; no secrets are copied into the database.

## Known limitations

- **The importer exposes no machine-readable status.** Detection therefore relies on the HTML
  heuristic. If the importer is patched to return a status code / JSON, set
  `SIDECAR_IMPORTER_SUPPORTS_JSON=true` to use it instead.
- **90-day fetch window.** Beyond ~90 days PSD2 forces a second TAN mid-dialog that the importer
  cannot resume, so the window is capped at 90 days (catch-up widening at 89).
- **`description_regex_*` must not change after the first import.** Changing the description
  format breaks Firefly's hash-based duplicate detection and creates duplicate transactions. The
  editor renders these fields read-only behind an explicit unlock and warns about this.
- **`bank_2fa` and `bank_2fa_device` are not guessable.** They must be copied verbatim from the
  importer UI after a login (no umlauts in the device name).

## Requirements

- A running `bnw/firefly-iii-fints-importer` container reachable over HTTP.
- The config directory shared between both containers (mounted at `/data/configurations` on the
  importer side).

## Running

Pull the published image:

```bash
docker pull ghcr.io/jwtue/firefly-iii-fints-companion:latest
```

or bring it up next to the importer with the example compose file:

```bash
docker compose -f compose.example.yaml up -d
```

The companion has no host port mapping; reach it through a reverse proxy on the shared network.
`GET /healthz` is unauthenticated (liveness only, no data) and is suitable as a health check.
The UI is bilingual (English/German); the language follows `Accept-Language` and can be switched
in the header.

## Configuration

All options are environment variables with the `SIDECAR_` prefix — see
[`.env.example`](.env.example) for the full list. The container refuses to start unless either a
password (`SIDECAR_PASSWORD_HASH`) or a trusted network (`SIDECAR_TRUSTED_NETWORKS`) is
configured. Generate a password hash with:

```bash
python -c "from app.auth import hash_password; print(hash_password('yourPassword'))"
```

## Security

The configs contain the bank PIN, the FinTS persistence string and the Firefly token in
cleartext, so the companion is treated as a secret-editing application:

- Redaction runs on every stored response body, log line and notification, built from the
  current secrets.
- Authentication is required by default: a single-user password login, or a trusted-network
  bypass evaluated against the direct socket peer only (never `X-Forwarded-For`).
- No secrets are stored in the database. Password fields are masked in the UI, and an unchanged
  password field on save preserves the stored secret.
- The container ships read-only with `cap_drop: ALL` and a non-root user, and has no host port
  mapping.

## Development

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
pytest
SIDECAR_TRUSTED_NETWORKS=127.0.0.1/32 SIDECAR_BEHIND_TLS=false \
  uvicorn app.asgi:app --reload
```

Tests run without a real bank: recorded importer HTML fixtures under
[`tests/fixtures/importer/`](tests/fixtures/importer/) and an in-process importer stub drive the
detector, the runner and the full ASGI app.

## Versioning

The project follows [Semantic Versioning](https://semver.org/). A git tag `vX.Y.Z` triggers a
CI build that publishes the image tagged `X.Y.Z`, `X.Y` and `latest`. Notable changes are
recorded in [CHANGELOG.md](CHANGELOG.md).

## Built with Claude Code

This project was created and is maintained with [Claude Code](https://claude.com/claude-code).

## License

MIT — see [pyproject.toml](pyproject.toml).
