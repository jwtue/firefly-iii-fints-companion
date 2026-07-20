# AGENTS.md — Briefing: FinTS Importer Companion

This repo was **empty** at the outset. The goal is a companion container for the FinTS
importer `bnw/firefly-iii-fints-importer` that retrofits its missing user interface,
scheduling and observability — **without touching the importer itself**.

This document is the complete preliminary research. Read all of it before writing code.
The analysis was done on 2026-07-19 against the `master` branch as it stood then.

---

## 1. Starting point

The user runs a homelab with Firefly III (self-hosted personal finance) on a Raspberry Pi.
Transactions from German bank accounts arrive via FinTS/HBCI through
[`bnw/firefly-iii-fints-importer`](https://github.com/bnw/firefly-iii-fints-importer).

**Why FinTS and not the official routes:** The official Firefly Data Importer only connects
banks through external aggregators (GoCardless, Salt Edge) — both cloud services that the
bank data flows through. GoCardless has discontinued its free Bank Account Data product and
closed new registrations. FinTS is the only path that stays fully self-hosted: bank ↔ your
own container ↔ Firefly, with no third party in between. This is a deliberate, non-negotiable
foundational decision.

**The importer is ~1,400 LOC of PHP** (12 classes, 11 Twig templates, one test file). Small
enough to read in full — do that before integrating against it.

### What isn't good about the importer (motivation for this project)

- **It's a browser wizard, not a service.** The flow state lives in the PHP session and dies
  with the tab. Headless operation exists only as a bolted-on `?automate=true` path.
- **No scheduler.** The container starts `php -S` and waits. It never pulls anything on its
  own. Anyone who wants automation builds an external cron that calls the automate URL.
- **No logging worthy of the name.** `app/Logger.php` is a static class with `error_log()` as
  its only sink. No PSR-3, not mockable, unstructured, no redaction (`Logger::trace()` over
  FinTS traffic writes PIN/TAN material into the log).
- **Silent failure.** See section 3 — the single most important point in this document.
- **Configuration is raw.** JSON files with the bank PIN in cleartext, edited by hand. Several
  fields (`bank_2fa`, `bank_2fa_device`, `bank_fints_persistence`) can't be guessed; you have
  to copy them from the UI of a previous run.
- **No authentication whatsoever.** No basic auth, no CSRF token. Whoever reaches the port sees
  the config picker and can start imports.
- **`php -S` as a production server**, `display_errors=1` and `error_reporting(E_ALL)` in
  `app/index.php` — every uncaught exception throws a stack trace into the browser, and the
  stack holds bank credentials.

The user compared this to the rest of their homelab stack and rightly finds it below par in
usability.

---

## 2. Architecture decision — and the rejected alternatives

**Chosen: a standalone companion container.** It shares the config directory with the importer
via a volume and triggers runs over the importer's HTTP interface. The importer stays an
unchanged upstream image.

Rejected:

- **Forking the importer and building a web UI into it.** That isn't an extension but a
  different application: there's no persistence, no job model, no scheduler, no user
  management. Weeks of work plus permanent divergence from an upstream that has been active
  again since December 2025 (25 commits in that month alone).
- **Rewriting everything.** The importer's value isn't in the 1,400 LOC but in the
  sedimented bank quirks: MT940-vs-CAMT fallback, `force_mt940`, TAN-medium selection,
  `NoPsd2TanMode` for banks with a broken PSD2 implementation. The open issues are a knowledge
  store about faulty bank implementations. You'd re-suffer all of that in a rewrite, with a
  single bank as your only test case.

**Advantage of the companion:** stable interfaces (config directory + one URL), free choice of
technology, independent lifecycle, no rebase pain.

There is a **separate and independent** effort to teach the importer credit-card support (a
`phpFinTS` PR for DKKKU segments, then an importer-side PR). **That is not this repo's job.**
Don't mix them.

---

## 3. The interface — and its weak spot

### Trigger

```
GET http://firefly-fints-importer:8080/?automate=true&config=<filename>.json
```

`<filename>` is the plain basename, no path, **no spaces** (it lands unquoted in the URL).
Prerequisites in the config: `choose_account_automation` filled and
`skip_transaction_review: "true"`.

### ⚠ The importer answers EVERYTHING with HTTP 200 and HTML

Success, config not found, TAN required, bank timeout, PHP fatal error — always 200, always
HTML. **There is no machine-readable status.**

This isn't theory. It's exactly what the previous operation ran aground on: a cron companion
called the automate URL daily and checked the body for `Fatal error`. Because the config
volume was mounted at `/app/configurations` instead of `/data/configurations`, every run
aborted with `error.twig` and the message "Could not find the configuration" — HTTP 200, no
`Fatal error` in the body. The companion reported **`OK` daily for ten days for runs that
never happened.** The user only noticed because no data was arriving in Firefly.

Note: the mount path has since been corrected, but the class of bug remains. Body grepping is a
heuristic, not an interface.

### From this follows the first task

**Before you build the companion, make an upstream PR against
`bnw/firefly-iii-fints-importer` that returns a machine-readable status in automate mode** —
an HTTP status code ≠ 200 on failure, or a JSON response when `automate=true` is set. That's an
estimated 20–30 LOC, useful to every automator, and has good merge chances with an active
maintainer.

That turns the companion from "scrapes HTML" into "reads status". Without this PR you build your
error detection on the same sand the predecessor system collapsed on.

Until the PR lands: interpret the body check defensively — not only for `Fatal error` but also
for `error_header` / the `error.twig` title, and verify positively (did the run actually report
transactions?) instead of only checking negatively for error strings.

### The mount path (do not repeat)

The config volume belongs at **`/data/configurations`**, not `/app/configurations` — even
though the upstream `docker-compose.yml` suggests the latter. Reason: the UI's file picker
scans both directories, but the automate path in `app/Setup.php` only resolves
`data/configurations/<name>` relatively, and the image sets no `WORKDIR` (CWD = `/`).

---

## 4. The config format

One JSON file per bank account. Template in the homelab repo at
`env-examples/firefly-fints-config.json.example`. It's parsed by
`app/ConfigurationFactory.php` — that's the authoritative source for which fields are required.

| Field | Meaning / pitfalls |
|---|---|
| `bank_username` / `bank_password` | Login name + PIN. **Cleartext secret.** |
| `bank_code` | Bank sort code (BLZ) |
| `bank_url` | The bank's FinTS endpoint |
| `bank_2fa` | Code of the TAN method. Bank-specific, **not guessable** — the importer UI lists the methods with their codes after login. Special value `NoPsd2TanMode` for banks without a PSD2 TAN. |
| `bank_2fa_device` | Name of the TAN medium, only needed for headless. **Don't guess** — copy the exact string from `getTanMedia()` that the UI shows. No umlauts. |
| `bank_fints_persistence` | Enables TAN-free follow-up logins. Shown in the UI after a successful import. **Secret** — allows account access without a TAN. Stored base64-encoded. |
| `firefly_url` | Stack-internal, e.g. `http://firefly:8080` |
| `firefly_access_token` | Firefly Personal Access Token. **Secret.** |
| `skip_transaction_review` | `"true"` (a string!) — required for headless |
| `description_regex_match` / `_replace` | Reformatting of the transaction descriptions. **Don't change after the first import** — format changes break Firefly's hash-based duplicate detection and create doubles. If your UI makes these fields editable, warn about it. |
| `auto_submit_form_via_js` | Semi-automatic browser mode |
| `force_mt940` | Forces MT940 instead of CAMT, in case CAMT parsing is broken at the bank |
| `choose_account_automation` | Required for headless: `bank_account_iban`, `firefly_account_id`, `from`/`to` |

**On the time window (`from`/`to`):** rolling, typically `"now - 7 days"` → `"now"`.
**Must stay ≤ 90 days** — older transactions require, for PSD2 reasons, a second TAN in the
middle of the dialog, which the importer fails to continue (session serialization loses the
dialog state → errors 9050/9800/9010). If your UI makes the window editable, validate this
limit.

Also note: a rolling 7-day window forgives no longer outage. If the import is down for 10 days,
three days are permanently lost until someone widens the window once.
**That is a strong argument for your companion to report outages loudly** — and a feature
candidate: after a detected outage, widen the window automatically for one run (Firefly's
duplicate detection catches the overlap).

---

## 5. Scope

### In scope

1. **Config management** — create, edit, duplicate, delete the JSON files through a web
   interface. A form instead of a text editor, with explanations for the non-guessable fields
   and validation (window ≤ 90 days, filename without spaces, required fields for headless).
2. **Scheduling** — a schedule per config, triggering the automate URL, sequentially (not in
   parallel against the same bank). The companion **replaces** the previous cron container
   rather than managing it — scheduler, trigger, log storage and notification in one place.
3. **Run history and logs** — per run: timestamp, config, result, duration, response body.
   Viewable in the UI. This is the core of the value: in a failure the user had *no* logs at
   all.
4. **Notifications** — Telegram and/or email on a failed run and especially on "TAN required".
   Instead of silence.

### Explicitly NOT in scope

- **Credit-card support** — a separate effort, see section 2.
- **TAN resume.** The companion can *notify* that a TAN is due, but not accept it: the FinTS
  session lives in the importer process. Don't attempt it. The user then clicks through the
  importer UI once and enters the new `bank_fints_persistence` string — **that is the expected
  workflow.** PSD2 forces it anyway roughly every 90 days.
  A realistic comfort gain instead: after the manual run, conveniently enter the new
  persistence string in the companion UI rather than editing JSON by hand.
- **Patching the importer.** Changes to the importer go as an upstream PR, not into this repo.

---

## 6. Security

The companion becomes a **secret-editing application**: the configs contain the bank PIN, the
FinTS persistence string and the Firefly token in cleartext. Unlike with the importer itself,
"sits behind a reverse proxy" is not enough here.

- Real authentication is mandatory, not optional.
- Mask password fields in the UI; never print the PIN in run logs, error messages or stack
  traces. **Build in redaction from the start**, don't retrofit it.
- Filter the importer's response bodies before storing them — with `display_errors=1` they can
  contain stack traces with credentials.
- No host port mapping; access only through the reverse proxy.
- The config directory is in the FTP backup — don't create additional cleartext copies.

---

## 7. Homelab conventions

The target system is `jwtue/homelab`. **Before deployment, read `docs/configuration.md`,
`docs/networking.md`, `docs/volumes-and-backup.md` and `docs/firefly.md` there** — the
conventions are documented, not guessed. In short:

- **Volumes:** on the Pi under `/home/admin/docker-volumes/<stack>/...`. No Docker-managed
  volumes.
- **Networks:** the stack-internal `default` plus the external `nginx-net` for the reverse
  proxy. Container hostnames work across stacks.
- **No host port mapping**, access via NPM.
- **DNS:** `.app.<location>` for applications, `.home` for location-independent links.
- **Homepage dashboard:** the container gets `homepage.*` labels (group, name, icon, `href` to
  the `.home` domain, description, `siteMonitor`) — analogous to the existing services in the
  Firefly stack.
- **Deployment:** the companion belongs in `docker-compose/pi/firefly.yaml`, where the importer
  and cron container already live today. The existing `firefly-fints-cron` is retired in the
  process.
- **Keep docs in sync:** when changing the homelab repo, update `README`/`docs` immediately and
  check off completed checklist items. Put extensive concepts in `docs/*.md`, not in the
  homelab repo's `AGENTS.md`.
- **Git:** the branch is called `main`, never `master`.

> Note: this project ended up as a **standalone, public repository**, independent of the
> homelab repo. The homelab conventions above describe the intended eventual deployment target,
> not a constraint on this repo's structure.

---

## 8. Technology choice

Deliberately left open — the companion is a standalone service and **not tied to PHP**.
Requirements: small, one container, ARM-capable (Raspberry Pi), lightweight persistence (SQLite
suffices for run history and schedule), server-rendered HTML is entirely enough. An SPA
frontend would be overkill for the scope.

Before deciding: briefly check whether
[`Gared/firefly-iii-fints-console-importer`](https://github.com/Gared/firefly-iii-fints-console-importer)
now provides usable parts — that repo went the CLI route and was very active in 07/2026.

---

## 9. Recommended order

1. **Read the importer source** — `app/Setup.php`, `app/ConfigurationFactory.php`,
   `app/index.php`, `app/Logger.php`. That's a few hundred lines and settles the interface
   authoritatively.
2. **Upstream PR for a machine-readable status** (section 3). The foundation for everything
   else.
3. **Minimal end-to-end slice:** list configs, trigger a run, store and display the result.
   That already achieves the core value — visibility.
4. **Scheduling**, then retire the old `firefly-fints-cron`.
5. **Notifications.**
6. **Config editor last:** the largest security effort for the least everyday value (configs
   rarely change — except for the persistence string, see section 5).

---

## 10. Open questions for the user

Clarify before implementation, don't guess:

- Preferred language/framework for the companion?
- Telegram, email or both? Is there already a notification path in the homelab to hook into?
- Should the companion replace `firefly-fints-cron` immediately, or run alongside it at first?
- Is single-user auth (one password) enough, or should it tie into existing homelab auth?

---

*Created on 2026-07-19 as part of the preliminary research. All statements about the importer
refer to the `master` state at that time — where they diverge, the source code, not this
document, is authoritative.*
