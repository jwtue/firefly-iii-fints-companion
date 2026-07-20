# AGENTS.md — Briefing: FinTS-Importer-Sidecar

Dieses Repo ist **leer**. Es soll ein Begleit-Container für den FinTS-Importer
`bnw/firefly-iii-fints-importer` entstehen, der dessen fehlende Bedienoberfläche,
Ablaufsteuerung und Beobachtbarkeit nachrüstet — **ohne den Importer selbst anzufassen**.

Dieses Dokument ist die vollständige Vorrecherche. Lies es ganz, bevor du Code schreibst.
Die Analyse wurde am 19.07.2026 gegen den damaligen `master` durchgeführt.

---

## 1. Ausgangslage

Der Nutzer betreibt ein Homelab mit Firefly III (self-hosted Finanzverwaltung) auf einem
Raspberry Pi. Umsätze deutscher Bankkonten kommen per FinTS/HBCI über
[`bnw/firefly-iii-fints-importer`](https://github.com/bnw/firefly-iii-fints-importer) hinein.

**Warum FinTS und nicht die offiziellen Wege:** Der offizielle Firefly-Data-Importer bindet
Banken nur über externe Aggregatoren an (GoCardless, Salt Edge) — beides Cloud-Dienste, durch
die die Bankdaten laufen. GoCardless hat sein kostenloses Bank-Account-Data-Produkt eingestellt,
Neuregistrierungen sind geschlossen. FinTS ist der einzige Weg, der vollständig self-hosted
bleibt: Bank ↔ eigener Container ↔ Firefly, kein Dritter dazwischen. Das ist eine bewusste,
nicht verhandelbare Grundentscheidung.

**Der Importer ist ~1.400 LOC PHP** (12 Klassen, 11 Twig-Templates, ein Test-File). Klein genug,
um ihn ganz zu lesen — tu das, bevor du gegen ihn integrierst.

### Was am Importer nicht gut ist (Motivation für dieses Projekt)

- **Er ist ein Browser-Wizard, kein Dienst.** Ablaufzustand lebt in der PHP-Session und stirbt
  mit dem Tab. Headless-Betrieb existiert nur als angeflanschter `?automate=true`-Pfad.
- **Kein Scheduler.** Der Container startet `php -S` und wartet. Er zieht von sich aus nie etwas.
  Wer automatisieren will, baut sich außen einen Cron, der die automate-URL aufruft.
- **Kein Logging, das diesen Namen verdient.** `app/Logger.php` ist eine statische Klasse mit
  `error_log()` als einzigem Sink. Kein PSR-3, nicht mockbar, unstrukturiert, keine Redaction
  (`Logger::trace()` über FinTS-Verkehr trägt PIN/TAN-Material ins Log).
- **Silent Fail.** Siehe Abschnitt 3 — der wichtigste Punkt des ganzen Dokuments.
- **Konfiguration ist roh.** JSON-Dateien mit Bank-PIN im Klartext, von Hand editiert. Mehrere
  Felder (`bank_2fa`, `bank_2fa_device`, `bank_fints_persistence`) kann man nicht wissen, sondern
  muss sie aus der UI eines vorherigen Laufs abschreiben.
- **Keinerlei Authentifizierung.** Kein Basic-Auth, kein CSRF-Token. Wer den Port erreicht, sieht
  die Config-Auswahl und kann Importe starten.
- **`php -S` als Produktionsserver**, `display_errors=1` und `error_reporting(E_ALL)` in
  `app/index.php` — jede uncaught Exception wirft einen Stacktrace in den Browser, und im Stack
  liegen Bank-Zugangsdaten.

Der Nutzer hat das mit dem Rest seines Homelab-Stacks verglichen und findet es zu Recht
unterdurchschnittlich bedienbar.

---

## 2. Architekturentscheidung — und die verworfenen Alternativen

**Gewählt: eigenständiger Sidecar-Container.** Er teilt sich das Config-Verzeichnis per Volume
mit dem Importer und triggert Läufe über dessen HTTP-Schnittstelle. Der Importer bleibt
unverändertes Upstream-Image.

Verworfen wurde:

- **Den Importer forken und dort eine WebUI einbauen.** Das ist kein Ausbau, sondern eine
  andere Anwendung: Es gibt keine Persistenz, kein Job-Modell, keinen Scheduler, keine
  User-Verwaltung. Wochenlange Arbeit plus dauerhafte Divergenz zu einem Upstream, das seit
  Dezember 2025 wieder aktiv ist (25 Commits allein in dem Monat).
- **Alles neu schreiben.** Der Wert des Importers steckt nicht in den 1.400 LOC, sondern in den
  einsedimentierten Bank-Eigenheiten: MT940-vs-CAMT-Fallback, `force_mt940`, TAN-Medium-Auswahl,
  `NoPsd2TanMode` für Banken mit kaputter PSD2-Implementierung. Die offenen Issues sind ein
  Wissensspeicher über fehlerhafte Bankenimplementierungen. Das erleidet man beim Rewrite neu,
  mit einer einzigen Bank als Testfall.

**Vorteil des Sidecars:** stabile Schnittstellen (Config-Verzeichnis + eine URL), freie
Technologiewahl, unabhängiger Lebenszyklus, kein Rebase-Schmerz.

Es gibt parallel ein **davon unabhängiges** Vorhaben, dem Importer Kreditkarten-Unterstützung
beizubringen (`phpFinTS`-PR für DKKKU-Segmente, danach Importer-seitiger PR). **Das ist nicht
Aufgabe dieses Repos.** Nicht vermischen.

---

## 3. Die Schnittstelle — und ihre Schwachstelle

### Trigger

```
GET http://firefly-fints-importer:8080/?automate=true&config=<dateiname>.json
```

`<dateiname>` ist der reine Basename, keine Pfadangabe, **keine Leerzeichen** (landet unquoted
in der URL). Voraussetzung in der Config: `choose_account_automation` gefüllt und
`skip_transaction_review: "true"`.

### ⚠ Der Importer antwortet auf ALLES mit HTTP 200 und HTML

Erfolg, Config nicht gefunden, TAN erforderlich, Bank-Timeout, PHP-Fatal-Error — immer 200,
immer HTML. **Es gibt keinen maschinenlesbaren Status.**

Das ist keine Theorie. Genau daran ist der bisherige Betrieb gescheitert: Ein Cron-Sidecar rief
täglich die automate-URL auf und prüfte den Body auf `Fatal error`. Weil das Config-Volume auf
`/app/configurations` statt `/data/configurations` gemountet war, brach jeder Lauf mit
`error.twig` und der Meldung „Could not find the configuration" ab — HTTP 200, kein
`Fatal error` im Body. Der Sidecar meldete **zehn Tage lang täglich `OK` für Läufe, die nie
stattgefunden haben.** Der Nutzer merkte es erst, weil in Firefly keine Daten ankamen.

Merke: Der Mount-Pfad ist inzwischen korrigiert, aber die Klasse des Fehlers bleibt. Body-Grep
ist eine Heuristik, keine Schnittstelle.

### Daraus folgt die erste Aufgabe

**Bevor du den Sidecar baust, mach einen Upstream-PR gegen `bnw/firefly-iii-fints-importer`,
der im automate-Modus einen maschinenlesbaren Status liefert** — HTTP-Statuscode ≠ 200 bei
Fehler, oder eine JSON-Antwort wenn `automate=true` gesetzt ist. Das sind geschätzt 20–30 LOC,
nützt jedem Automatisierer und hat gute Merge-Chancen bei einem aktiven Maintainer.

Der Sidecar wird dadurch von „scrapt HTML" zu „liest Status". Ohne diesen PR baust du deine
Fehlererkennung auf demselben Sand, auf dem das Vorgängersystem eingebrochen ist.

Solange der PR nicht durch ist: Body-Prüfung defensiv auslegen — nicht nur auf `Fatal error`,
sondern auch auf `error_header` bzw. den `error.twig`-Titel, und positiv verifizieren
(hat der Lauf tatsächlich Transaktionen gemeldet?) statt nur negativ auf Fehlerstrings zu prüfen.

### Der Mount-Pfad (nicht wiederholen)

Das Config-Volume gehört auf **`/data/configurations`**, nicht `/app/configurations` — obwohl
das Upstream-`docker-compose.yml` letzteres vorschlägt. Grund: Die Dateiauswahl der UI scannt
beide Verzeichnisse, der automate-Pfad in `app/Setup.php` löst aber nur relativ
`data/configurations/<name>` auf, und das Image setzt kein `WORKDIR` (CWD = `/`).

---

## 4. Das Config-Format

Eine JSON-Datei pro Bankkonto. Vorlage im Homelab-Repo unter
`env-examples/firefly-fints-config.json.example`. Geparst wird sie von
`app/ConfigurationFactory.php` — dort steht verbindlich, welche Felder Pflicht sind.

| Feld | Bedeutung / Fallstricke |
|---|---|
| `bank_username` / `bank_password` | Anmeldename + PIN. **Klartext-Secret.** |
| `bank_code` | BLZ |
| `bank_url` | FinTS-Endpoint der Bank |
| `bank_2fa` | Code des TAN-Verfahrens. Bankspezifisch, **nicht ratbar** — die Importer-UI listet die Verfahren nach dem Login samt Code. Sonderwert `NoPsd2TanMode` für Banken ohne PSD2-TAN. |
| `bank_2fa_device` | Name des TAN-Mediums, nur für headless nötig. **Nicht raten** — exakt den String aus `getTanMedia()` übernehmen, den die UI zeigt. Keine Umlaute. |
| `bank_fints_persistence` | Ermöglicht TAN-freie Folge-Logins. Wird nach erfolgreichem Import in der UI angezeigt. **Secret** — erlaubt Kontozugriff ohne TAN. Base64-kodiert abgelegt. |
| `firefly_url` | stack-intern, z.B. `http://firefly:8080` |
| `firefly_access_token` | Firefly Personal Access Token. **Secret.** |
| `skip_transaction_review` | `"true"` (String!) — Pflicht für headless |
| `description_regex_match` / `_replace` | Umformatierung der Buchungstexte. **Nach dem Erst-Import nicht mehr ändern** — Format-Änderungen brechen Fireflys Hash-basierte Duplikaterkennung und erzeugen Doubletten. Wenn deine UI diese Felder editierbar macht, warne davor. |
| `auto_submit_form_via_js` | halbautomatischer Browser-Modus |
| `force_mt940` | erzwingt MT940 statt CAMT, falls CAMT-Parsing bei der Bank klemmt |
| `choose_account_automation` | Pflicht für headless: `bank_account_iban`, `firefly_account_id`, `from`/`to` |

**Zum Zeitfenster (`from`/`to`):** rollierend, typisch `"now - 7 days"` → `"now"`.
**Muss ≤ 90 Tage bleiben** — ältere Umsätze verlangen PSD2-bedingt eine zweite TAN mitten im
Dialog, an deren Fortsetzung der Importer scheitert (Session-Serialisierung verliert den
Dialog-Zustand → Fehler 9050/9800/9010). Wenn deine UI das Fenster editierbar macht, validiere
diese Grenze.

Beachte auch: Ein rollierendes 7-Tage-Fenster verzeiht keinen längeren Ausfall. Fällt der
Import 10 Tage aus, sind drei Tage dauerhaft verloren, bis jemand das Fenster einmalig weitet.
**Das ist ein starkes Argument dafür, dass dein Sidecar Ausfälle laut meldet** — und ein
Feature-Kandidat: nach erkanntem Ausfall das Fenster für einen Lauf automatisch weiten
(Fireflys Duplikaterkennung fängt die Überlappung ab).

---

## 5. Aufgabenumfang

### In Scope

1. **Config-Verwaltung** — Anlegen, Bearbeiten, Duplizieren, Löschen der JSON-Dateien über eine
   Weboberfläche. Formular statt Texteditor, mit Erklärungen zu den nicht-ratbaren Feldern und
   Validierung (Zeitfenster ≤ 90 Tage, Dateiname ohne Leerzeichen, Pflichtfelder für headless).
2. **Ablaufsteuerung** — Zeitplan pro Config, Trigger der automate-URL, sequenziell (nicht
   parallel gegen dieselbe Bank). Der Sidecar **ersetzt** den bisherigen Cron-Container, statt
   ihn zu verwalten — Scheduler, Trigger, Log-Speicher und Benachrichtigung an einer Stelle.
3. **Lauf-Historie und Logs** — pro Lauf Zeitstempel, Config, Ergebnis, Dauer, Response-Body.
   Einsehbar in der UI. Das ist der Kern des Nutzens: Der Nutzer hatte im Fehlerfall *überhaupt
   keine* Logs.
4. **Benachrichtigungen** — Telegram und/oder E-Mail bei fehlgeschlagenem Lauf und insbesondere
   bei „TAN erforderlich". Statt Stille.

### Explizit NICHT in Scope

- **Kreditkarten-Unterstützung** — separates Vorhaben, siehe Abschnitt 2.
- **TAN-Resume.** Der Sidecar kann *benachrichtigen*, dass eine TAN fällig ist, sie aber nicht
  entgegennehmen: Die FinTS-Session lebt im Importer-Prozess. Versuch das nicht. Der Nutzer
  klickt sich dann einmal durch die Importer-UI und trägt den neuen
  `bank_fints_persistence`-String ein — **das ist der erwartete Ablauf.** PSD2 erzwingt ihn
  ohnehin ca. alle 90 Tage.
  Ein realistischer Komfortgewinn wäre stattdessen: Nach dem manuellen Durchlauf den neuen
  Persistence-String bequem in der Sidecar-UI eintragen können, statt JSON von Hand zu editieren.
- **Den Importer patchen.** Änderungen am Importer gehen als Upstream-PR, nicht in dieses Repo.

---

## 6. Sicherheit

Der Sidecar wird zur **Secret-Editing-Anwendung**: Die Configs enthalten Bank-PIN,
FinTS-Persistence-String und Firefly-Token im Klartext. Anders als beim Importer selbst reicht
„hängt hinter einem Reverse Proxy" hier nicht.

- Echte Authentifizierung ist Pflicht, nicht optional.
- Passwortfelder in der UI maskieren; PIN nie in Lauf-Logs, Fehlermeldungen oder Stacktraces
  ausgeben. **Redaction von Anfang an einbauen**, nicht nachrüsten.
- Response-Bodies des Importers vor dem Speichern filtern — bei `display_errors=1` können dort
  Stacktraces mit Zugangsdaten stehen.
- Kein Host-Port-Mapping; Zugriff nur über den Reverse Proxy.
- Config-Verzeichnis liegt im FTP-Backup — keine zusätzlichen Klartext-Kopien anlegen.

---

## 7. Homelab-Konventionen

Das Zielsystem ist `jwtue/homelab`. **Lies dort vor dem Deployment `docs/configuration.md`,
`docs/networking.md`, `docs/volumes-and-backup.md` und `docs/firefly.md`** — die Konventionen
sind dokumentiert, nicht erraten. Kurzfassung:

- **Volumes:** Pi unter `/home/admin/docker-volumes/<stack>/...`. Keine Docker-managed Volumes.
- **Netze:** stack-internes `default` plus externes `nginx-net` für den Reverse Proxy.
  Container-Hostnamen funktionieren stackübergreifend.
- **Kein Host-Port-Mapping**, Zugriff über NPM.
- **DNS:** `.app.<ort>` für Anwendungen, `.home` für standortunabhängige Links.
- **Homepage-Dashboard:** Der Container bekommt `homepage.*`-Labels (Gruppe, Name, Icon, `href`
  auf die `.home`-Domain, Beschreibung, `siteMonitor`) — analog zu den bestehenden Diensten im
  Firefly-Stack.
- **Deployment:** Der Sidecar gehört in `docker-compose/pi/firefly.yaml`, wo Importer und
  Cron-Container heute schon stehen. Der bestehende `firefly-fints-cron` entfällt dabei.
- **Dokumentation mitziehen:** Bei Änderungen am Homelab-Repo sofort `README`/`docs` anpassen,
  erledigte Checklisten-Punkte abhaken. Ausführliche Konzepte nach `docs/*.md`, nicht in die
  `AGENTS.md` des Homelab-Repos.
- **Git:** Branch heißt `main`, nie `master`.

---

## 8. Technologiewahl

Bewusst offen gelassen — der Sidecar ist ein eigenständiger Dienst und **nicht an PHP gebunden**.
Anforderungen: klein, ein Container, ARM-tauglich (Raspberry Pi), leichtgewichtige Persistenz
(SQLite genügt für Lauf-Historie und Zeitplan), serverseitig gerendertes HTML reicht völlig.
Ein SPA-Frontend wäre für den Umfang überzogen.

Vor der Entscheidung: kurz prüfen, ob
[`Gared/firefly-iii-fints-console-importer`](https://github.com/Gared/firefly-iii-fints-console-importer)
inzwischen brauchbare Teile liefert — das Repo ging die CLI-Richtung an und war 07/2026 sehr aktiv.

---

## 9. Empfohlene Reihenfolge

1. **Importer-Quelltext lesen** — `app/Setup.php`, `app/ConfigurationFactory.php`,
   `app/index.php`, `app/Logger.php`. Das sind wenige hundert Zeilen und klärt die
   Schnittstelle verbindlich.
2. **Upstream-PR für maschinenlesbaren Status** (Abschnitt 3). Fundament für alles Weitere.
3. **Minimaler Durchstich:** Configs auflisten, einen Lauf triggern, Ergebnis speichern und
   anzeigen. Damit ist der Kernnutzen — Sichtbarkeit — schon erreicht.
4. **Zeitplanung**, dann den alten `firefly-fints-cron` ablösen.
5. **Benachrichtigungen.**
6. **Config-Editor** zuletzt: der größte Sicherheitsaufwand bei geringstem Alltagsnutzen
   (Configs ändern sich selten — außer beim Persistence-String, siehe Abschnitt 5).

---

## 10. Offene Fragen für den Nutzer

Vor Implementierungsbeginn klären, nicht raten:

- Bevorzugte Sprache/Framework für den Sidecar?
- Telegram, E-Mail oder beides? Existiert im Homelab schon ein Benachrichtigungsweg, an den
  sich anschließen lässt?
- Soll der Sidecar den `firefly-fints-cron` sofort ablösen oder zunächst parallel laufen?
- Reicht Single-User-Auth (ein Passwort), oder soll er sich an bestehende Homelab-Auth anbinden?

---

*Erstellt am 19.07.2026 im Rahmen der Vorrecherche. Alle Aussagen zum Importer beziehen sich auf
den damaligen `master`-Stand — bei Abweichungen gilt der Quelltext, nicht dieses Dokument.*
