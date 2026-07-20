# Firefly III FinTS Companion

UI, scheduling and observability for the FinTS importer
[`bnw/firefly-iii-fints-importer`](https://github.com/bnw/firefly-iii-fints-importer) —
**without ever modifying the importer**. This companion runs as its own container
(a sidecar) next to the importer, shares its configuration directory, and triggers
runs over the importer's HTTP interface.

Image: `ghcr.io/jwtue/firefly-iii-fints-companion` (built by GitHub Actions, `linux/arm64`).

Full background research and architecture decisions: see [AGENTS.md](AGENTS.md).

## Why

The importer's automate endpoint answers **everything** with HTTP 200 and HTML —
success, a missing config, a TAN prompt, a fatal error. There is no machine-readable
status. A cron-based predecessor only grepped the body for `Fatal error` and therefore
reported "OK" for ten days of runs that never happened. This companion detects, stores,
displays and (via notifications) reports failed runs.

**Central design rule:** an unrecognized response body is a **failure**, never a
success. That rule is encoded in [`app/importer/detect.py`](app/importer/detect.py)
and guarded by a property test.

## Status

**M1–M5 are implemented:**

- **M1 walking skeleton:** list configs, trigger a run manually, view the correctly
  classified result with a redacted response body in the history.
- **M2 scheduler:** a cron schedule per config, sequential execution via a global
  lock, **no run at container start**. Reconcile on startup only mirrors DB → scheduler.
- **M3 notifications:** ntfy + Telegram (apprise URL syntax), alerts on failure and
  on "TAN required" (dedicated wording), a `notified` flag against repeats, and an
  hourly dead-man's switch for configs that stop succeeding. Every outbound message
  passes through the redactor.
- **M4 config editor:** create/edit/duplicate/delete via a form, secret fields masked
  with "leave unchanged" semantics, a regex-change warning behind an unlock toggle,
  an audit log, and a persistence quick form.
- **M5 catch-up:** after a detected outage the fetch window is widened in-place for a
  single run (≤ 89 days) and restored in a `finally`; stuck runs are repaired at startup.

Open: **M0** upstream PR (done in a sibling repo, awaiting merge) and **M6** (activate
the JSON detector via `SIDECAR_IMPORTER_SUPPORTS_JSON=true` once the PR lands).

## Status detection

An adapter chain, first matching detector wins:

1. `JsonStatusDetector` — active once the upstream status PR (`&format=json`) is deployed.
2. `HttpStatusDetector` — active once responses carry a real status code (≠ 200).
3. `HtmlHeuristicDetector` — terminal fallback, parses the HTML. **Default: failure.**

The first two are inert against today's importer (always 200, always HTML) and cost
nothing — when the PR merges, only `SIDECAR_IMPORTER_SUPPORTS_JSON=true` needs to be set.

## Security

The configs hold the bank PIN, the FinTS persistence string and the Firefly token **in
cleartext**, which makes this a secret-editing application:

- **Redaction from the start** ([`app/redact.py`](app/redact.py)): every stored response
  body and every log line passes through a central redactor. A sentinel test verifies that
  secrets never appear in any DB column, any log record, or any rendered page.
- **Fail-closed auth:** the container only starts when either a password hash
  (`SIDECAR_PASSWORD_HASH`) or a trusted network (`SIDECAR_TRUSTED_NETWORKS`) is
  configured. There is no silent open state.
- **Network bypass keyed on the direct peer**, never `X-Forwarded-For` — otherwise the
  bypass would be spoofable via a header. If a reverse proxy sits in front, its container
  IP is the peer; account for that deliberately.
- No host port mapping, `read_only` container, `cap_drop: ALL`, non-root user.

## Configuration

All options are environment variables with the `SIDECAR_` prefix — see
[`.env.example`](.env.example). Generate a password hash:

```bash
python -c "from app.auth import hash_password; print(hash_password('yourPassword'))"
```

## Running it

```bash
docker compose -f compose.example.yaml up -d
```

The companion has no host port mapping — reach it through a reverse proxy on the shared
network. `GET /healthz` is unauthenticated (liveness only, no data) and is suitable as a
site monitor.

## Development

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
pytest                              # full test suite
SIDECAR_TRUSTED_NETWORKS=127.0.0.1/32 SIDECAR_BEHIND_TLS=false \
  uvicorn app.asgi:app --reload
```

Tests run without a real bank: recorded importer HTML fixtures under
[`tests/fixtures/importer/`](tests/fixtures/importer/) and an in-process stub
([`tests/stub/importer.py`](tests/stub/importer.py)) drive the detector, the runner and
the full ASGI app.

## Upstream contribution (M0)

Before hardening for production, a PR belongs upstream against
`bnw/firefly-iii-fints-importer` that returns a machine-readable status in automate mode
(a status code ≠ 200 on failure, optional JSON with `&format=json`). The companion is
deliberately **not** blocked on it and carries the heuristic until it lands.

## License

MIT — see [pyproject.toml](pyproject.toml).
