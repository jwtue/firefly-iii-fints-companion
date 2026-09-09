# Firefly III FinTS Companion

A companion web UI for the FinTS importer
[`bnw/firefly-iii-fints-importer`](https://github.com/bnw/firefly-iii-fints-importer). It adds shared
bank logins, scheduling, run history and notifications on top of the importer **without modifying
it** — it runs as its own container next to the importer, shares the importer's configuration
directory, and triggers imports over the importer's HTTP interface.

Image: `ghcr.io/jwtue/firefly-iii-fints-companion`.

> Built with the assistance of Claude Code. See [`AGENTS.md`](AGENTS.md) for the design rationale.

## Why this exists

The importer is a browser wizard with no scheduler, no persistent logs, and a headless mode that
answers every outcome — success, “config not found”, “TAN required”, a fatal error — with `HTTP 200`
and an HTML body. Scraping that body for an error string reports success for runs that never
happened. This companion makes runs observable, classifies failures conservatively, and — its main
idea — models the bank access as a **shared login** instead of repeating credentials per account.

## Shared logins

In the importer, every account configuration is a self-contained JSON file that repeats the full bank
credentials and TAN setup. In practice several accounts share one bank access, so re-authenticating
(a fresh FinTS persistence string, which PSD2 forces roughly every 90 days) means editing every file.

Here the model is normalized:

- A **login** holds the bank access once: URL, code, username, PIN, TAN method and the persistence
  string.
- An **account import** inherits a login and adds only what is account-specific: the account to fetch
  (IBAN, or an account number for a credit card), the target Firefly account, the rolling date window,
  description rewriting and a schedule.
- The companion **renders the importer's flat config files from this model** on demand. A single
  re-authentication on a login therefore propagates to every account that inherits from it.

## What it does

- **Adopt an existing importer setup** — on first run it scans the importer's config files and
  reconstructs them as logins and accounts (files sharing a bank access are grouped into one login,
  the persistence string carries over), with a preview before anything is created.
- **Logins & accounts** — manage both through forms, with validation (≤ 90-day window, filename rules,
  cron syntax) and inline help for the fields that cannot be guessed.
- **Scheduling** — a cron schedule per account. A dedicated scheduler process runs due imports
  sequentially through a shared lock, so two runs never hit the same bank at once. Nothing runs at
  container start.
- **Run history** — every run is stored with its timestamp, trigger, outcome, duration and a redacted
  excerpt of the importer response.
- **Reliable outcome detection** — a chain that upgrades as the importer gains a machine-readable
  status: a JSON body, then a real HTTP status code, then an HTML heuristic that classifies as success
  **only** on a recognized “Import finished” page and treats everything else as a failure.
- **Notifications** — Telegram alerts on failed runs and on “TAN required”. Every message is redacted.
- **Dead-man's switch** — alerts when a scheduled account has *not* succeeded when it should have,
  catching silent gaps (a dead scheduler, an account that stopped running) that failure alerts miss.
- **Missed-run catch-up** — after an outage the fetch window is widened for a single run to cover the
  gap (capped at the 90-day limit); Firefly's duplicate detection absorbs the overlap.
- **Re-authentication** — a one-field form to paste the new persistence string; it propagates to all
  accounts of the login.
- **Bilingual UI** — English and German, switchable in the header (cookie > Accept-Language).

## What it does not do

- **Answer TANs.** The FinTS session lives inside the importer, so a headless run cannot complete a
  TAN challenge. The companion notifies that a TAN is due; you complete it once through the importer
  UI and paste the new persistence string into the login.
- **Credit-card retrieval.** That lives in the importer.
- **Modify the importer.** It is used as an unmodified upstream image.

## How it works

The companion and the importer share the config directory (mounted at `/data/configurations` on the
importer). A run renders the account's config, writes it there, and triggers
`GET /?automate=true&config=<name>.json`. The normalized model and the run history live in SQLite; the
flat config files are generated artifacts.

## Requirements

- A running `bnw/firefly-iii-fints-importer` container reachable over HTTP.
- The config directory shared between both containers, mounted at **`/data/configurations`** on the
  importer side (not `/app/configurations` — the importer's automate path resolves the config name
  relative to `CWD=/`, so the wrong mount fails silently).

## Running

Bring it up next to the importer with the example compose file:

```bash
docker compose -f compose.example.yaml up -d
```

The companion has no host port mapping; reach it through a reverse proxy. `GET /healthz` is
unauthenticated (liveness only). Run the scheduler as a second container from the same image with
`command: php bin/scheduler.php` (see the example compose file).

## Configuration

All options are environment variables with the `SIDECAR_` prefix — see [`.env.example`](.env.example).
The container refuses to start unless access is protected — a password (`SIDECAR_PASSWORD` or
`SIDECAR_PASSWORD_HASH`) or a trusted network (`SIDECAR_TRUSTED_NETWORKS`). The Firefly connection,
importer URL and Telegram credentials can be set either by environment variable or in the Settings
page; a value fixed by the environment is shown read-only.

## Security

The logins hold the bank PIN, the FinTS persistence string and (globally) the Firefly token, so the
companion is a secret-editing application:

- Authentication is required and enforced at startup. An optional trusted-network bypass
  (`SIDECAR_TRUSTED_NETWORKS`) is evaluated against the **direct socket peer only**, never
  `X-Forwarded-For`; behind a reverse proxy the peer is the proxy, so use it deliberately.
- Secrets are never sent to the browser; an empty password field on save keeps the stored value.
- Every stored response excerpt and every notification is passed through redaction built from the
  current secrets.
- No host port mapping — expose only via a reverse proxy on a shared network.

## Development

```bash
composer install
vendor/bin/phpunit
SIDECAR_PASSWORD=dev SIDECAR_BEHIND_TLS=false php -S localhost:8080 -t public
```

Tests run without a real bank or importer: the config renderer, the outcome detector, the validator,
the redactor and the scheduler are covered with unit tests and in-memory SQLite.

## Versioning

[Semantic Versioning](https://semver.org/). A git tag `vX.Y.Z` triggers a CI build that publishes the
image tagged `X.Y.Z`, `X.Y` and `latest`.

## License

MIT — see [`LICENSE`](LICENSE).
