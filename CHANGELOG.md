# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Images are published to `ghcr.io/jwtue/firefly-iii-fints-companion`. A git tag `vX.Y.Z`
triggers a build tagged `X.Y.Z`, `X.Y` and `latest`.

## [Unreleased]

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
