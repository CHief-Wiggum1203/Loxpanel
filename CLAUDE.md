# LoxPanel – Hinweise für die Entwicklung

Web-Touch-Visu für den Loxone Miniserver. Fork von `Lenardo1/Loxpanel`, hier
eigenständig weiterentwickelt und auf Unraid betrieben. Ausführliche Analyse in
[`docs/ARCHITEKTUR.md`](docs/ARCHITEKTUR.md), dort stehen Datenfluss, Routen,
Konfigurationsformate, Erweiterungs-Rezepte und bekannte Schwachstellen. Die
priorisierte Arbeitsliste steht in [`docs/TODO.md`](docs/TODO.md).

## Aufbau in einem Satz

`bin/webvisu.py` (aiohttp) verbindet sich per WebSocket mit dem Miniserver, rendert
alle Ansichten serverseitig als JSON und schickt sie per WebSocket an
`webfrontend/html/panel.html`, das nur noch anzeigt. Konfigurator und Einstellungen
liegen seit Upstream 0.3.2 gemeinsam in `config.html` (Rubriken „Panel
Configuration", „Displays" und „Settings"), `settings.html` leitet nur noch weiter; beide
sprechen `/api/*`.

## Wichtige Dateien

| Datei | Inhalt |
|---|---|
| `bin/webvisu.py` | gesamter Server, 3.000 Zeilen, Routen in `main()` am Ende |
| `bin/loxone_ws.py` | Loxone-WebSocket und Binärparser |
| `bin/audioserver.py`, `bin/audioserver_events.py`, `bin/audioserver_auth.py` | Audioserver-Backends: Gen1/MS4H, Gen2-Events (Port 7091) und die App-Anmeldung am gekoppelten Audioserver (RSA/AES, braucht `cryptography`) |
| `bin/theme_colors.py` | Leitet aus EINER Grundfarbe den ganzen Panel-Farbsatz ab (Flächen, Schrift, Icon- und Zustandsfarben) und rechnet jeden Wert gegen die Fläche nach, auf der er steht: Hauptschrift AAA, Rest AA, Grafik 3:1, dazu Deuteranopie und Protanopie. Liefert `None`, wenn eine Farbe kein tragfähiges Theme hergibt. Nur Standardbibliothek. Aufgerufen aus `_theme_vars()` |
| `bin/front_info.py` | Front (Screensaver): iCal-Abo parsen (`icalendar`+`python-dateutil`) und Wetter von Open-Meteo (kein API-Key). Eigenständig; `webvisu.py` ruft `load_front()` periodisch (`front_task`) und pusht `{t:"front"}` an die Panels |
| `bin/loxone_weather.py` | Wetter vom Loxone-Wetterserver (falls die Anlage ihn hat): rechnet die Binaertabelle des Miniservers in dieselbe Form wie `front_info.fetch_weather()` um und hat damit Vorrang vor Open-Meteo. Wetterlage-Texte und Einheiten kommen aus der Struktur des Miniservers, nicht aus einer Tabelle im Code |
| `webfrontend/html/*.html`, `i18n.js` | Frontend, Vanilla JS, kein Build |
| `agent/loxpanel-agent.py` | Panel-Agent für Wandpanels; Kopie liegt als Heredoc in `deploy/install-agent.sh` |
| `android/` | LoxPanel-App für Android (Lenardos #61): Server per Chaquopy im Gerät, Visu in eigener WebView mit der JS-Brücke `LoxKiosk`. Der Build kopiert `bin/`, `webfrontend/`, `deploy/` und `config/` aus dem Arbeitsbaum in die App (`syncLoxpanelAssets`); Anleitung in `android/README.md` |
| `packaging/deb/` | Lenardos `.deb`-Paket für Linux-Panels (#62), im Fork nicht weiterentwickelt |
| `config/*.example` | Vorlagen; echte Dateien liegen im Volume `/app/config` |
| `unraid/loxpanel.xml`, `deploy/UNRAID.md` | Unraid-Betrieb |
| `loxberry-plugin/` | LoxBerry-Wrapper, nur für Releases relevant |

## Lokal starten

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
LOXPANEL_MS_HOST=<ip> LOXPANEL_MS_USER=<user> LOXPANEL_MS_PASS=<pass> \
  .venv/bin/python bin/webvisu.py          # http://localhost:8099
```

Ohne Miniserver-Zugang startet der Server trotzdem, wartet und zeigt jedem
Panel, wo der Konfigurator zu öffnen ist; mit Zugang versucht er es mit
wachsenden Pausen immer wieder. Den Platzhalter-Zugang aus
`loxpanel.cfg.example` nimmt er nie. `/config` und `/api/settings` sind dann
erreichbar, das reicht als Rauchtest. Docker: `docker compose up -d --build`.

## Prüfen vor einem Push

Tests liegen in `tests/` (pytest), die GitHub-Action `tests.yml` führt sie auf
jedem PR und jedem Push auf `main` aus. Lokal dasselbe:

```bash
.venv/bin/pip install -r requirements-dev.txt     # einmalig, dazu für Browser-Tests:
.venv/bin/python -m playwright install chromium    # einmalig
python3 -m py_compile bin/*.py agent/loxpanel-agent.py
.venv/bin/ruff check --select F,E9 bin agent tests
.venv/bin/pytest                  # alles; -m "not browser" ohne Chromium (~15 s)
```

- `tests/lox.py` enthält den Miniserver-Nachbau (Statistik-Dateien, V2-Binärdaten,
  Befehle, Token-Prüfung) und die Beispiel-Anlage. Neue Tests bauen darauf auf,
  statt eigene Nachbauten anzulegen.
- Browser-Tests (`tests/browser/`, Marker `browser`) fahren die echte Visu und den
  Konfigurator in Chromium; Screenshots landen im `tmp_path` bzw. in der CI als
  Artefakt „screenshots".
- Kein Test darf `config/` verändern, ein Wächter in `tests/conftest.py` prüft das.
  Wer Config-Dateien lesen und schreiben muss, nimmt die Fixture `cfg_ordner`: Sie
  leitet Schreiben (`CFG_FILE`, `PANELS_FILE`, `THEME_FILE`) und Lesen (die Leser
  werten `Path(__file__)` erst beim Aufruf aus) nach `tmp_path` um.
- Tests, die von der Uhrzeit abhängen, erzeugen Aufzeichnungen je Monat
  (`monatsdateien()`), sonst scheitern sie am Monatsanfang.

## Konventionen und Stolperfallen

- Oberfläche und Kommentare sind deutsch. Admin-Texte laufen über `i18n.js`
  (Schlüssel = deutscher Text), Panel-Texte stehen hart im Server. Das gilt auch
  für die Front: Wochentage, „Heute"/„Morgen"/„ganztägig" und die Wetterlage baut
  `front_info.py`, das Panel zeigt sie nur an (Zahlen formatiert das Panel deutsch).
- Umlaute: Anzeige-Texte, Commit-Meldungen, PR-Titel und PR-Texte schreiben sich
  mit `ä ö ü ß`. Kommentare im Code bleiben bei der Ersatzschreibung (`ae oe ue
  ss`), wie sie Upstream durchgehend verwendet — sonst reibt sich jeder
  Upstream-Merge daran. Doku unter `docs/` ist reiner Umlaut-Text.
- Neue Panel-Optionen müssen in `_sanitize_panels()` freigeschaltet werden, sonst
  verwirft der Server sie beim Speichern. Das passiert nicht mehr still: die
  Antwort nennt sie (`verworfen`), der Konfigurator zeigt eine Warnung. Ein
  Standardwert, der bewusst nicht gespeichert wird, gehört nach
  `PANEL_STANDARD`, sonst gibt es einen Fehlalarm.
- Neue Bausteintypen kommen in die beiden Ketten `_control_item()` und
  `_view_control_inner()`, nicht in `adapters.py`. Reihenfolge der Zweige ist
  relevant.
- `loxpanel.cfg` aus `/config` (Settings → Miniserver) hat Vorrang vor
  `LOXPANEL_MS_*`-Variablen.
- Beim Ändern des Agenten beide Stellen anfassen: `agent/loxpanel-agent.py` und
  den Heredoc in `deploy/install-agent.sh`.
- Die Brücke `LoxKiosk` der App hat zwei Seiten: `KioskBridge` in
  `android/.../KioskActivity.kt` und die Aufrufe in `panel.html` (`KIOSK_APPS`,
  `appLeerlauf()`, `appHelligkeit()`, `setSaver`). Die App-Tests in
  `tests/browser/` bauen sie nach; eine neue Methode gehört auch dorthin.
- Keine Authentifizierung auf den Routen. Nichts bauen, was das Netz nach außen
  öffnet, ohne das vorher zu lösen.
- Image-Name `ghcr.io/chief-wiggum1203/loxpanel` in Kleinbuchstaben. Ein Push auf
  `main` baut `:latest` neu.
- Root-`plugin.cfg`, `daemon/`, `postinstall.sh`, `apt`,
  `webfrontend/htmlauth/index.php`, `config/visu.*` sind Altlasten ohne Funktion.

## Git

Entwicklung auf Feature-Branches, PR gegen `main` dieses Forks (nicht gegen das
Original). Das Repo erlaubt nur Squash oder Rebase, keine Merge-Commits.
Upstream-Updates: `git remote add upstream https://github.com/Lenardo1/Loxpanel`,
dann `git fetch upstream && git merge upstream/main`. Upstream-Merges als echten
Merge-Commit nach `main` bringen (PR mit „Create a merge commit", nicht
squashen), sonst kennt der Fork die Upstream-Commits nicht und dieselben
Konflikte kommen beim nächsten Release wieder.

Ausführlicher Ablauf – Feature-Entwicklung als Contributor und den Fork
synchron halten: [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md).
