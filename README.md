# Firefly III FinTS Companion

Bedienoberfläche, Ablaufsteuerung und Beobachtbarkeit für den FinTS-Importer
[`bnw/firefly-iii-fints-importer`](https://github.com/bnw/firefly-iii-fints-importer) —
**ohne den Importer selbst anzufassen**. Dieser Companion läuft als eigener Container
(Sidecar) neben dem Importer, teilt sich dessen Config-Verzeichnis und triggert Läufe
über die HTTP-Schnittstelle.

Image: `ghcr.io/jwtue/firefly-iii-fints-companion` (per GitHub Actions gebaut, `linux/arm64`).

Ausführliche Vorrecherche und Architekturentscheidungen: siehe [AGENTS.md](AGENTS.md).

## Warum

Der automate-Endpoint des Importers antwortet auf **alles** mit HTTP 200 und HTML —
Erfolg, fehlende Config, TAN-Anforderung, Fatal Error. Es gibt keinen maschinenlesbaren
Status. Ein Cron-Vorgänger prüfte nur auf `Fatal error` im Body und meldete deshalb zehn
Tage lang „OK" für Läufe, die nie stattfanden. Der Sidecar erkennt, speichert, zeigt und
(später) meldet Fehlläufe.

**Zentrale Designregel:** Ein nicht erkannter Response-Body ist ein **Fehlschlag**, niemals
ein Erfolg. Diese Regel ist in [`app/importer/detect.py`](app/importer/detect.py) kodiert
und durch einen Property-Test abgesichert.

## Stand

**M1–M5 sind umgesetzt:**

- **M1 Durchstich:** Configs auflisten, Lauf manuell triggern, korrekt klassifiziertes
  Ergebnis mit redigiertem Response-Body in der Historie.
- **M2 Scheduler:** Cron-Zeitplan pro Config, sequenzielle Ausführung über einen globalen
  Lock, **kein Lauf beim Container-Start**. Reconcile beim Start spiegelt nur DB→Scheduler.
- **M3 Benachrichtigungen:** ntfy + Telegram (Apprise-Syntax), Alarm bei Fehler und
  „TAN erforderlich" (eigener Wortlaut), `notified`-Flag gegen Wiederholung, Dead-Man's-Switch
  (stündlich) für Configs, die aufhören zu laufen. Jeder ausgehende Text läuft durch den Redactor.
- **M4 Config-Editor:** Anlegen/Bearbeiten/Duplizieren/Löschen per Formular, Secret-Felder
  maskiert und „unverändert lassen"-Semantik, Regex-Warnung mit Entsperren, Audit-Log,
  Persistence-Schnellformular.
- **M5 Catch-up:** Nach erkanntem Ausfall wird das Abruffenster für einen Lauf automatisch
  geweitet (≤ 89 Tage), im `finally` zurückgesetzt; Crash-Reparatur beim Start.

Offen: **M0** Upstream-PR (fertig im Nachbar-Repo, wartet aufs Mergen) und **M6** (JSON-Detektor
scharf schalten via `SIDECAR_IMPORTER_SUPPORTS_JSON=true`, sobald der PR durch ist).

## Statuserkennung

Adapterkette, erster passender Detektor gewinnt:

1. `JsonStatusDetector` — aktiv, sobald der Upstream-Status-PR (`&format=json`) deployt ist.
2. `HttpStatusDetector` — aktiv, sobald Antworten einen echten Statuscode (≠ 200) tragen.
3. `HtmlHeuristicDetector` — terminaler Fallback, parst das HTML. **Default: Fehlschlag.**

Die ersten beiden sind gegen den heutigen Importer (immer 200, immer HTML) inert und
kosten nichts — beim Merge des PRs wird nur `SIDECAR_IMPORTER_SUPPORTS_JSON=true` gesetzt.

## Sicherheit

Die Configs enthalten Bank-PIN, FinTS-Persistence-String und Firefly-Token **im Klartext**.
Der Sidecar ist damit eine Secret-Editing-Anwendung:

- **Redaction von Anfang an** ([`app/redact.py`](app/redact.py)): jeder gespeicherte
  Response-Body und jede Log-Zeile läuft durch einen zentralen Redactor. Ein Sentinel-Test
  stellt sicher, dass Secrets in keiner DB-Spalte, keinem Log und keiner gerenderten Seite
  auftauchen.
- **Fail-closed-Auth:** Der Container startet nur, wenn entweder ein Passwort-Hash
  (`SIDECAR_PASSWORD_HASH`) oder ein vertrauenswürdiges Netz (`SIDECAR_TRUSTED_NETWORKS`)
  konfiguriert ist. Kein stiller offener Zustand.
- **Netz-Bypass anhand des direkten Peers**, nie `X-Forwarded-For` — sonst wäre der Bypass
  durch einen Header spoofbar. Läuft ein Reverse Proxy davor, ist dessen Container-IP der
  Peer; diese Konsequenz bewusst berücksichtigen.
- Kein Host-Port-Mapping, `read_only`-Container, `cap_drop: ALL`, Non-Root-User.

## Konfiguration

Alle Optionen über Umgebungsvariablen mit Präfix `SIDECAR_` — siehe
[`.env.example`](.env.example). Passwort-Hash erzeugen:

```bash
python -c "from app.auth import hash_password; print(hash_password('deinPasswort'))"
```

## Betrieb

```bash
docker compose -f compose.example.yaml up -d --build
```

Der Sidecar hat kein Host-Port-Mapping — Zugriff über einen Reverse Proxy im gemeinsamen
Netz. `GET /healthz` ist unauthentifiziert (nur Liveness, keine Daten) und eignet sich als
Site-Monitor.

## Entwicklung

```bash
python -m venv .venv && ./.venv/Scripts/pip install -e ".[dev]"
./.venv/Scripts/pytest            # gesamte Test-Suite
SIDECAR_TRUSTED_NETWORKS=127.0.0.1/32 SIDECAR_BEHIND_TLS=false \
  ./.venv/Scripts/uvicorn app.asgi:app --reload
```

Tests laufen ohne echte Bank: aufgezeichnete Importer-HTML-Fixtures unter
[`tests/fixtures/importer/`](tests/fixtures/importer/) und ein In-Process-Stub
([`tests/stub/importer.py`](tests/stub/importer.py)) treiben Detektor, Runner und die
volle ASGI-App.

## Upstream-Beitrag (M0)

Vor dem produktiven Ausbau gehört ein PR gegen `bnw/firefly-iii-fints-importer`, der im
automate-Modus einen maschinenlesbaren Status liefert (Statuscode ≠ 200 bei Fehler, optional
JSON bei `&format=json`). Details im Plan; der Sidecar ist bewusst **nicht** darauf
blockiert und trägt bis dahin die Heuristik.
