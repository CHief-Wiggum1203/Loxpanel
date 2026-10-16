# LoxPanel – Hinweise für die Entwicklung

Web-Touch-Visu für den Loxone Miniserver. Fork von `Lenardo1/Loxpanel`, hier
eigenständig weiterentwickelt und auf Unraid betrieben. Ausführliche Analyse in
[`docs/ARCHITEKTUR.md`](docs/ARCHITEKTUR.md), dort stehen Datenfluss, Routen,
Konfigurationsformate, Erweiterungs-Rezepte und bekannte Schwachstellen. Die
priorisierte Arbeitsliste steht in [`docs/TODO.md`](docs/TODO.md).

## Aufbau in einem Satz

`bin/webvisu.py` (aiohttp) verbindet sich per WebSocket mit dem Miniserver, rendert
alle Ansichten serverseitig als JSON und schickt sie per WebSocket an
`webfrontend/html/panel.html`, das nur noch anzeigt (Markup; Stil und Skript in
`panel/`). Konfigurator und Einstellungen
liegen seit Upstream 0.3.2 gemeinsam in `config.html` (Markup; Stil in `config.css`, Skript in
`config/*.js`, Rubriken „Ansichten",
„Vorgaben", „Geräte" und „Einstellungen"), `settings.html` leitet nur noch weiter; beide
sprechen `/api/*`. Die Wörter der Oberfläche (Ansicht, Gerät, Vorgaben,
Einstellungen) stehen in `docs/ARCHITEKTUR.md` §7.2.

## Wichtige Dateien

| Datei | Inhalt |
|---|---|
| `bin/webvisu.py` | der Kern des Servers: `App` (`__init__()` mit allen Feldern, `_spawn()`, `close()`; die Themen erbt sie als Mixins), die Routen-Handler und `main()` am Ende; rund 2.100 Zeilen, wird weiter zerlegt |
| `bin/konfig.py` | die Konfigdateien unter `config/`: Pfade, Laden und atomares Schreiben, die Leser der `loxpanel.cfg` (`_config()`, `_ms_zugang()`, `_audio_config()` …), die Optionskonstanten (`PANEL_STANDARD`, `THEME_UI_KEYS`, `KACHEL_ZIEL` …), die Wertprüfer (`_clean_*`) und die Sanitizer (`_sanitize_panels()` …, in `App` als statische Methoden erreichbar) |
| `bin/sicherung.py` | Backup als ZIP ohne Kennwörter und das Einspielen einer Sicherung (lesen, prüfen, Kennwörter einsetzen, schreiben); die Routen `/api/backup` und `/api/restore` bleiben in `webvisu.py` |
| `bin/statistik.py` | Verläufe aus den Statistik-Dateien des Miniservers: Parser, Ausdünnen, Tagesbalken und als Mixin `Statistik` (erbt `App`) Laden mit Cache, Verlaufsblöcke der Detailseite und Mini-Verläufe der Kacheln |
| `bin/haus.py`, `bin/gesten.py` | Hausübersicht (Mixin `Haus`, `_view_haus()`, `HAUS_*`) und Gesten der Visu (Mixin `Gesten`, `geste()`, `gesten_hilfe()`, `GESTEN_*_TYPEN`); `App` erbt beide |
| `bin/miniserver.py`, `geraete.py`, `audiodienst.py`, `intercomdienst.py`, `front.py`, `verteilung.py`, `medien.py`, `diagnosedaten.py`, `ansicht.py`, `seiten.py` | die übrigen Themen der `App`, je ein Mixin: Verbindung, Token, Struktur und Befehle (`Miniserver`), Geräte, Agenten, Display und `panels.json` schreiben (`Geraete`, dazu `KIOSK_APPS`, `AGENT_*`), Audioserver-Anbindung (`Audiodienst`), SIP-Zugang und Kamera der Intercom (`Intercomdienst`), Kalender und Wetter der Uhr-Seite (`Front`), Broadcaster und `push()` (`Verteilung`), Icons, Cover und Klingelbilder (`Medien`), Diagnose und `/api/types` (`Diagnosedaten`, dazu `VERSION`), wirksames Profil, Theme und Export (`Ansicht`), `render()`, Tabs, Kacheln und Detailseiten (`Seiten`) |
| `bin/bausteine/` | Kachel und Detailseite je Bausteintyp, ein Modul je Familie (licht, schalten, beschattung, klima, audio, intercom, werte, sicherheit, wecker, energie, garten, wellness, zentral); `@kachel("Typ")` und `@detail("Typ")` tragen die Funktionen in die Tabellen ein, `gemeinsam.py` hält die Typmengen, Konstanten der Strukturdoku, Adapter und reine Helfer; die Helfer der Bausteine sind Mixins (`helfer.py` `Grundhelfer`, je Familie z. B. `KlimaHelfer`), `BausteinHelfer` fasst sie zusammen, `App` erbt es |
| `bin/loxone_ws.py` | Loxone-WebSocket und Binärparser |
| `bin/audioserver.py`, `bin/audioserver_events.py`, `bin/audioserver_auth.py` | Audioserver-Backends: Gen1/MS4H, Gen2-Events (Port 7091) und die App-Anmeldung am gekoppelten Audioserver (RSA/AES, braucht `cryptography`) |
| `bin/theme_colors.py` | Leitet aus EINER Grundfarbe den ganzen Panel-Farbsatz ab (Flächen, Schrift, Icon- und Zustandsfarben) und rechnet jeden Wert gegen die Fläche nach, auf der er steht: Hauptschrift AAA, Rest AA, Grafik 3:1, dazu Deuteranopie und Protanopie. Liefert `None`, wenn eine Farbe kein tragfähiges Theme hergibt. Dazu die Kachel-Sets (`KACHEL_SETS`): jeder Wert eines Sets steht nur dort, die Visu hängt ihre Regeln an die Art (`data-kachelset-aufbau`/`-leiste`), nie an den Namen. Nur Standardbibliothek. Aufgerufen aus `_theme_vars()` |
| `bin/front_info.py` | Front (Screensaver): iCal-Abo parsen (`icalendar`+`python-dateutil`) und Wetter von Open-Meteo (kein API-Key). Eigenständig; das Mixin `Front` (`front.py`) ruft `load_front()` periodisch (`front_task`) und pusht `{t:"front"}` an die Panels |
| `bin/loxone_weather.py` | Wetter vom Loxone-Wetterserver (falls die Anlage ihn hat): rechnet die Binaertabelle des Miniservers in dieselbe Form wie `front_info.fetch_weather()` um und hat damit Vorrang vor Open-Meteo. Wetterlage-Texte und Einheiten kommen aus der Struktur des Miniservers, nicht aus einer Tabelle im Code |
| `bin/loxone_secure.py` | Verschlüsselte Befehle an den Miniserver (Command Encryption, HTTP-Variante `jdev/sys/fenc`): RSA-Schlüssel aus `getPublicKey`, AES-256-CBC, Anmeldung im Befehl (`autht`). Damit holt `App.secured_details()` (`miniserver.py`) die gesicherten Details, etwa den SIP-Zugang der Intercom. Braucht `cryptography` |
| `bin/sip_probe.py` | SIP-Prüfung der Türstation: OPTIONS über UDP mit Wiederholung nach RFC 3261, Anmeldung per Digest (MD5, SHA-256, `-sess`), Codecs aus dem SDP. Löst keinen Anruf aus. Nur Standardbibliothek; aufgerufen von `/api/sip/pruefen` |
| `bin/version_info.py` | Welcher Stand läuft: Version, Commit und Bauzeit aus `bin/version.json`, die APK-Build (`syncLoxpanelAssets`), Dockerfile und `.deb`-Bau (`packaging/deb/build.sh`) schreiben; ohne die Datei Version aus `loxberry-plugin/plugin.cfg` und Commit aus Git; ohne Commit (lokaler `docker compose`-Build) ein Prüfwert über den Code (`inhalt`), an dem offene Seiten ein Update erkennen. Konfigurator (Seitenleiste), `/api/settings`, `/api/health` |
| `bin/diagnose.py` | Diagnosepaket (`/api/diagnose`, je Gerät oder für den Server): ZIP mit `diagnose.md` (Zusammenfassung oben), `diagnose.json`, den Einstellungen und den letzten Log-Zeilen (Puffer `LOG` am Root-Logger, `LOG_ZEILEN`, `LOG_MINUTEN`). Entfernt Kennwörter und Tokens, kürzt Kalender-Abos auf den Host, streicht Zugangsdaten in Adressen und den Standort und schwärzt jeden gefundenen Wert auch im Log, auch URL-kodiert. Nur Standardbibliothek; die Angaben sammelt `App.diagnose_daten()` (`diagnosedaten.py`) |
| `webfrontend/html/*.html`, `i18n.js`, `raster.js`, `config.css`, `config/*.js`, `panel/` | Frontend, Vanilla JS, kein Build; `raster.js` ist die gemeinsame Rasterrechnung von Visu und Konfigurator (`/raster.js`); der Konfigurator lädt sein Skript in elf Teilen aus `config/` (§7.2), die Visu zwei Stylesheets und zwölf Skriptteile aus `panel/` (§7.1); Reihenfolge jeweils in der HTML-Datei, alle Funktionen global |
| `agent/loxpanel-agent.py` | Panel-Agent für Wandpanels; Kopie liegt als Heredoc in `deploy/install-agent.sh` |
| `android/` | LoxPanel-App für Android (Lenardos #61): Server per Chaquopy im Gerät, Visu in eigener WebView mit der JS-Brücke `LoxKiosk`. Ein Wächter im Server-Dienst startet die App neu, wenn `/api/health` ausfällt (Regeln in `Waechter.kt`). Der Build kopiert `bin/`, `webfrontend/`, `deploy/` und aus `config/` nur die Vorlagen aus dem Arbeitsbaum in die App (`syncLoxpanelAssets`, gewacht von `tests/test_apk_inhalt.py`); Anleitung in `android/README.md` |
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
jedem PR, jedem Push auf `main` und jedem `v*`-Tag aus. Lokal dasselbe:

```bash
.venv/bin/pip install -r requirements-dev.txt     # einmalig, dazu für Browser-Tests:
.venv/bin/python -m playwright install chromium    # einmalig
python3 -m py_compile bin/*.py bin/bausteine/*.py agent/loxpanel-agent.py
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
- Browser-Tests, die Text messen (Umbruch, Abschneiden, freie Höhe), hängen
  an der Schrift: Die Visu nimmt `Inter`, wenn es installiert ist, die CI
  (ubuntu-latest) hat es nicht und rendert mit DejaVu Sans, das breiter läuft.
  Wo eine Zeile genau umbricht, darf ein Test deshalb nicht hart vorgeben,
  sondern misst es (`test_mini_verlauf_im_neuen_aufbau`) oder vergleicht mit
  und ohne Faktor (`test_lesbarkeit_auf_standardgeraeten`).

## Konventionen und Stolperfallen

- Oberfläche und Kommentare sind deutsch. Admin-Texte laufen über `i18n.js`
  (Schlüssel = deutscher Text), Panel-Texte stehen hart im Server. Das gilt auch
  für die Front: Wochentage, „Heute"/„Morgen"/„ganztägig" und die Wetterlage baut
  `front_info.py`, das Panel zeigt sie nur an (Zahlen formatiert das Panel deutsch).
- Umlaute: Anzeige-Texte, Commit-Meldungen, PR-Titel und PR-Texte schreiben sich
  mit `ä ö ü ß`. Kommentare im Code bleiben bei der Ersatzschreibung (`ae oe ue
  ss`), wie sie Upstream durchgehend verwendet — sonst reibt sich jeder
  Upstream-Merge daran. Doku unter `docs/` ist reiner Umlaut-Text.
- Neue Panel-Optionen müssen in `_sanitize_panels()` (`bin/konfig.py`) freigeschaltet werden, sonst
  verwirft der Server sie beim Speichern. Das passiert nicht mehr still: die
  Antwort nennt sie (`verworfen`), der Konfigurator zeigt eine Warnung. Ein
  Standardwert, der bewusst nicht gespeichert wird, gehört nach
  `PANEL_STANDARD` (`konfig.py`), sonst gibt es einen Fehlalarm. Dazu muss die Option in
  `App._panel_export()` (`ansicht.py`) stehen: Der Konfigurator schickt beim Speichern zurück, was
  er von dort bekam, sonst geht sie beim nächsten Speichern still verloren.
- Neue Bausteintypen bekommen eine Kachel-Funktion `@kachel("Typ")` mit
  `(app, uuid, c, it)` und eine Detailseiten-Funktion `@detail("Typ")` mit
  `(app, uuid, c, route)` in der passenden Familie unter `bin/bausteine/`,
  nicht in `webvisu.py` und nicht in `adapters.py`; `App._control_item()` baut
  Kopf und Fuß der Kachel, `App._view_control()` hängt Verlauf und verlinkte
  Objekte an (beide in `seiten.py`). Ein Typ darf nur einmal eingetragen sein (sonst Fehler beim
  Import), `tests/test_bausteine.py` kennt die Liste. Die Helfer (`_state`,
  `_fmt_num`, `_jal_fahrt` …) sind Methoden der Mixins in `bausteine/` (ein
  neuer Helfer einer Familie in deren `…Helfer`-Klasse), aufgerufen über `app.`.
  Nennt die zweite Zeile der Kachel keinen Zustand, sondern
  beschreibt nur („Türsprechanlage“), `subInfo=True` setzen, sonst steht sie
  im neuen Kachel-Aufbau groß vorn. Schriftgrößen ohne Einstellung stehen
  einmal in `GROESSEN_STANDARD`, nicht in `load_theme()` oder der Vorlage.
- Detailseiten-Blöcke (Vokabular in `docs/ARCHITEKTUR.md` §3.7): Ändert der
  Inhalt eines Blocks seine Gestalt, gehört er in `blockSig()` der Visu, sonst
  patcht `updatePanel()` ihn nie und er friert ein. Befehle und State-Bedeutung
  eines Bausteins aus der Loxone-Strukturdoku („Structure File“), nicht
  raten; Unterseiten (Zone, Weckzeit …) sind eigene `view`-Routen in `render()`.
- `loxpanel.cfg` aus `/config` (Einstellungen → Miniserver) hat Vorrang vor
  `LOXPANEL_MS_*`-Variablen (`konfig._ms_zugang()`).
- Tests, die eine Konstante oder einen Helfer des Servers ersetzen, nehmen
  `ersetzen(monkeypatch, name, wert)` aus `tests/lox.py`: `webvisu.py` importiert
  aus den herausgelösten Modulen mit eigener Bindung je Modul, ein Patch nur
  an `W` träfe den Aufrufer dort nicht. Die herausgelösten Module (`ZERLEGT` in
  `tests/lox.py`, dazu `bausteine`) importieren `webvisu` nie
  (`tests/test_schichten.py`); App-Methoden eines Themas wandern als Mixin.
  Ein neues Modul kommt in `_ZERLEGT_MODULE` hinter die Module, aus denen es
  importiert. Die Bausteine importieren kein Themenmodul (Kreis über
  `bausteine/__init__.py`); was den Miniserver braucht, gehört in ein Thema.
- Beim Ändern des Agenten beide Stellen anfassen: `agent/loxpanel-agent.py` und
  den Heredoc in `deploy/install-agent.sh`.
- Die Brücke `LoxKiosk` der App hat zwei Seiten: `KioskBridge` in
  `android/.../KioskActivity.kt` und die Aufrufe der Visu in `panel/display.js`
  und `panel/startseite.js` (`KIOSK_APPS`, `appLeerlauf()`, `appHelligkeit()`,
  `setSaver`). Die App-Tests in
  `tests/browser/` bauen sie nach; eine neue Methode gehört auch dorthin.
- `/api/health` meldet 503, sobald eine Aufgabe aus `a["tasks"]` (`on_startup()`)
  endet. Daran hängen der Docker-Healthcheck und der Wächter der App, der sie
  dann neu startet. Dort nur Aufgaben eintragen, die nie planmäßig enden.
- Keine Authentifizierung auf den Routen. Nichts bauen, was das Netz nach außen
  öffnet, ohne das vorher zu lösen.
- Image-Name `ghcr.io/chief-wiggum1203/loxpanel` in Kleinbuchstaben. Ein Push auf
  `main` baut `:latest` neu, aber erst, wenn die Tests desselben Laufs grün sind
  (Job `veroeffentlichen` in `tests.yml`). Einen eigenen Docker-Workflow gibt es
  im Fork nicht mehr, `tests/test_workflows.py` wacht darüber.
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
