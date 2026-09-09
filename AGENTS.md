# AGENTS.md — design notes

A companion for the FinTS importer [`bnw/firefly-iii-fints-importer`](https://github.com/bnw/firefly-iii-fints-importer)
that adds a management UI, scheduling, run history and notifications **without modifying the
importer**. This document explains the design so a future contributor can extend it safely. It
describes the shipped implementation, not a plan.

## Architecture

A standalone container. It shares the importer's configuration directory over a volume and triggers
imports over the importer's HTTP interface. The importer stays an unchanged upstream image.

Kept close to the importer's platform (PHP) on purpose, so the UI could later be folded into the
importer itself if the projects ever merge.

- **Web** (`public/index.php`, FrankenPHP): Slim 4 + Twig, the UI.
- **Scheduler** (`bin/scheduler.php`): a second process from the same image that runs due imports.
- **State**: SQLite. The normalized model (logins, accounts) and the run history live here; the flat
  importer configs are rendered from it.

## The shared-login model (the core idea)

The importer's config is one self-contained JSON file per account, repeating the full bank
credentials and TAN setup. In practice several accounts share one bank access, so re-authenticating
means editing every file.

Normalized here:

- `logins` — the bank access shared by several accounts (URL, code, username, PIN, TAN method,
  persistence string). Re-authentication updates the persistence string once, on the login.
- `accounts` — inherit a login; hold only account-specific fields (IBAN or credit-card account
  number, Firefly target account, rolling window, description rewriting, schedule).
- `ConfigRenderer` composes a login + account + the global Firefly settings into the importer's flat
  JSON. `ConfigWriter` writes it to the shared directory. The runner re-renders before every run, so
  a re-authentication propagates to all inheriting accounts automatically.

## The interface, and its weak spot

Trigger: `GET <importer>/?automate=true&format=json&config=<name>.json`.

The importer historically answers **everything** with HTTP 200 and HTML — success, config not found,
TAN required, fatal error. Scraping the body for an error string reports success for runs that never
happened. `OutcomeDetector` is therefore a chain that upgrades as the importer improves:

1. **JSON body** — a patched importer that returns `{status, transactions, ...}` (bnw PR #239).
2. **HTTP status code** — the same patch sets 409/404/422/500.
3. **HTML heuristic** — the fallback: success **only** on a recognized “Import finished” page;
   anything else (TAN prompt, error page, fatal error, unrecognized) is a failure by construction.

`format=json` is always sent; an unpatched importer ignores it and returns HTML, which the heuristic
handles. Never report success unless it is positively recognized.

## What is out of scope

- **Answering TANs.** The FinTS session lives in the importer; a headless run cannot complete a TAN.
  The companion only *notifies*; the user completes the TAN once through the importer UI and pastes
  the new persistence string into the login. PSD2 forces this roughly every 90 days.
- **Credit-card retrieval** — lives in the importer.
- **Patching the importer** — changes go upstream, not here.

## Constraints worth knowing

- **90-day window.** Beyond ~90 days PSD2 forces a second TAN mid-dialog that the importer cannot
  resume, so `Validator` caps the fetch window at 90 days.
- **`description_regex_*` must not change after the first import** — it alters Firefly's duplicate
  hash and creates duplicates. The account form warns about this.
- **`bank_2fa` / `bank_2fa_device` are not guessable** — they must be copied from the importer UI
  after a login (no umlauts in the device name).
- **Filenames** have no spaces (they land unquoted in the trigger URL); the slug enforces this.

## Security

The companion is a secret-editing application (bank PIN, persistence string, Firefly token):

- Authentication is mandatory and enforced at startup (single-user password). An optional
  trusted-network bypass is matched against the direct socket peer only, never `X-Forwarded-For`.
- Secrets are never sent to the browser; an empty field on save keeps the stored value.
- Redaction (`Redactor`) runs on every stored response excerpt and every notification, built from the
  current secrets — the importer can echo credentials in a stack trace with `display_errors` on.
- No host port mapping; access only through a reverse proxy.

## Testing

`vendor/bin/phpunit`. The pure logic — config rendering, outcome detection, validation, redaction and
the scheduler's due-decision — is covered with unit tests and in-memory SQLite, with no real bank or
importer required.

## Layout

```
public/index.php     web entrypoint (FrankenPHP)
bin/scheduler.php    scheduler process
src/Config/          renderer, writer, validator, sync, importer (adopt existing configs)
src/Importer/        transport, client, outcome detector
src/Model/           login/account/run repositories
src/Runner/          the run orchestration + missed-run catch-up
src/Scheduler/       cron due-decision + dead-man's switch
src/Notify/          Telegram + null notifier
src/Http/            controllers + middleware (auth, CSRF, locale)
src/Auth/, src/Support/
templates/           Twig views
lang/                en.php / de.php message catalogs (bilingual UI)
tests/
```

Reliability & UX built on the above: a **dead-man's switch** (`DeadMansSwitch`) alerts on the absence
of success, not just on failure; **catch-up** (`CatchUp`) widens the window for one run after an
outage; the UI is **bilingual** (English/German) via a small `Translator` and per-request locale
resolution, with flash and validation messages carried as keys and translated at render time.
