# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Images are published to `ghcr.io/jwtue/firefly-iii-fints-companion`. A git tag `vX.Y.Z`
triggers a build tagged `X.Y.Z`, `X.Y` and `latest`.

## [Unreleased]

### Changed
- **Reimplemented in PHP (Slim 4, Twig, SQLite, served by FrankenPHP)**, replacing the initial
  Python implementation, to stay close to the importer's platform for a possible future merge.

### Added
- **Adopt an existing importer setup:** on first run, scan the importer's config files and reconstruct
  them as logins and accounts (shared bank access grouped into one login), with a preview.
- **Shared bank logins.** Credentials and the TAN setup are modeled once as a *login*; each account
  import *inherits* a login and adds only account-specific fields. Re-authentication updates the
  persistence string on the login and propagates to every inheriting account. The importer's flat
  per-account config files are rendered from this normalized model.
- Account selection by IBAN or by credit-card account number.
- Telegram notifications on failed runs and on “TAN required”.
- A dedicated scheduler process (replaces an external cron); nothing runs at container start.
- Dead-man's switch: alerts when a scheduled account has not succeeded when it should have.
- Missed-run catch-up: widens the fetch window for one run after an outage (capped at 90 days).
- Optional trusted-network auth bypass, evaluated against the direct socket peer only.
- Bilingual UI (English/German), switchable in the header (cookie > Accept-Language).

### Removed
- The ntfy notification channel from the Python version (Telegram is supported) — may return later.

## [0.1.0] - 2026-07-20

First tagged release.

### Added
- Configuration management UI: create, edit, duplicate and delete the importer's
  per-account JSON configs, with validation and secret-preserving forms.
- Scheduling: a cron schedule per config, executed sequentially through a global lock;
  no run at container start.
- Run history: every run stored with timestamp, trigger, outcome, duration and a
  redacted response body, viewable in the UI.
- Outcome detection: a detector chain (JSON / HTTP status / HTML heuristic) that treats
  any unrecognized importer response as a failure, never a silent success.
- Notifications: ntfy and Telegram (apprise URL syntax), alerts on failure and on
  "TAN required", plus an hourly dead-man's switch. All outbound text is redacted.
- Catch-up: after a missed run the fetch window is widened in-place for a single run
  (≤ 89 days) and restored afterwards; stuck runs are repaired at startup.
- Bilingual UI (English/German) with per-request language resolution (cookie >
  `Accept-Language` > English) and an in-app switcher.
- Security: fail-closed auth (password login or trusted-network bypass on the direct
  peer only), a redaction chokepoint, and no secrets stored in the database.
- CI on GitHub-hosted runners: tests, then a `linux/arm64` image published to GHCR.

[Unreleased]: https://github.com/jwtue/firefly-iii-fints-companion/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jwtue/firefly-iii-fints-companion/releases/tag/v0.1.0
