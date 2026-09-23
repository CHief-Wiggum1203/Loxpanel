# LoxPanel – ToDo

Priorisierte Liste der Änderungen für den eigenen Betrieb auf Unraid. Nummern in
Klammern verweisen auf die Befunde in [`ARCHITEKTUR.md`](ARCHITEKTUR.md)
(F = Fehler, S = Sicherheit, P = Performance, W = Wartbarkeit). Aufwand:
**S** = unter einer Stunde, **M** = ein halber Tag, **L** = mehrere Tage.

Stand 16.09.2026: Die Liste wurde vollständig gegen den Code geprüft (jeder
Eintrag einzeln, Haken ignoriert). Sieben Punkte waren längst erledigt und sind
jetzt abgehakt; die dabei gefundenen echten Defekte stehen als neue Punkte
drin.

Sicherheit ist bewusst ganz unten eingeordnet: Der Server läuft nur im Heimnetz
und ist nicht von außen erreichbar. Sollte sich das ändern, rückt Block 10 nach
oben.

---

## 0. Umbau: Android-Panels ohne Agent

Ziel: Jedes Android-Gerät mit Kiosk-App ist gleichwertig zum Linux-Panel mit
Agent. Der Agent bleibt für Linux erhalten. Hintergrund und Bewertung in
[`ARCHITEKTUR.md`](ARCHITEKTUR.md), Abschnitt 8.

- [x] **Schritt 1, Visu übernimmt die Display-Steuerung.** Server schickt
      `dpmsOff`, `reloadHours` und `agent` mit der `theme`-Nachricht. Ohne Agent
      schaltet die Seite nach `dpmsOff` Sekunden das Display über die
      JavaScript-Schnittstelle von Fully Kiosk Browser aus und bei Klingel,
      Wecker, Notify und Goto wieder ein; Auto-Neustart per `location.reload`.
      Der Agent hängt seine Gerätekennung an die Kiosk-URL, damit der Server
      Agent-Panels am WebSocket erkennt. Doku in `deploy/ANDROID.md`. **S**
- [x] **Schritt 2, Geräteverwaltung an der Gerätekennung.** `GET /api/devices`
      führt Agenten, verbundene Browser und konfigurierte Geräte zusammen;
      *Einstellungen → Panels* zeigt eine Liste mit Typ (Agent / Fully Kiosk /
      Browser), Online-Status, Ansicht und Aktionen (Ansicht wechseln, Neu
      laden, Display aus/an). Browser ohne Kennung werden nach IP gelistet und
      per „Namen vergeben" benannt (Visu merkt sich den Namen, `setdevice`).
      Neu `/api/display` zum Schalten des Displays, auch aus Loxone. **M**
- [x] **Schritt 3, serverseitige Display-Treiber.** Je Gerät unter
      *Einstellungen → Panels* ein Treiber: Fully Kiosk Remote Admin (Port
      2323, Passwort) oder WallPanel HTTP (Port 2971), gespeichert in
      `panels.json` unter `devices[name].display`. Der Server schaltet damit
      bei `/api/display`, Klingel, Wecker, Notify, Goto und nach der
      Leerlauf-Meldung der Visu (`idle`). **M**
- [x] **Schritt 4, Einstellungen und Doku.** *Neues Panel* hat zwei Karten:
      Start-URL-Generator für Android (Gerätename, Ansicht, kopieren) und der
      SSH-Weg für Linux. `deploy/ANDROID.md` beschreibt Fully Kiosk (JS und
      Remote Admin) und WallPanel. **S**
- [ ] **Offen nach dem Umbau:** Test auf echter Hardware (Fully Kiosk und
      WallPanel), danach ggf. Feinschliff an den Bezeichnungen der
      App-Einstellungen in der Anleitung. **S**

## 0b. Upstream-Abgleich

Zuletzt eingepflegt am **19.09.2026** (`upstream/main` @ `f5bdb01`,
**Release 0.5.0**), als echter Merge-Commit. Neu damit im Fork: **Zurück-Button
der Tab-Leiste exakt mittig** (links `ceil(N/2)`, rechts `floor(N/2)`, fehlende
Zelle als Abstandhalter), **`--accent` folgt der OK-Farbe auch ohne gesetzte
Panel-Grundfarbe**, und der YC-SM55P steht im Gerätekatalog bei den
2-Pane-Geräten. Der Fork trägt seitdem ebenfalls `VERSION=0.5.0` — bewusst im
Gleichschritt mit Upstream, weil die Versionszeile sonst bei jedem Release von
Hand aufzulösen wäre; `ARCHIVEURL` zeigt weiterhin auf die Releases **dieses**
Forks.

Davor, am 18.09.2026 (`a76ed83`): **Kamera als Split-Pane** (Intercom-Livebild
mit Tür-Buttons), **gerahmte Split-Panes** mit Seiten-Snap, **zweispaltiger
Screensaver** im Querformat, **konfigurierbarer Kachelrahmen** für helle
Displays, vereinheitlichte Lautstärkeleiste, **Anlagenschema (SystemScheme)**,
Rubrik „unterstützte Geräte" und der GHCR-Login-Fallback. Dazu `LICENSE.md`:
Upstream steht seit `cade27a` unter der PolyForm Noncommercial License 1.0.0.

Neue Upstream-Releases per `git fetch upstream && git merge upstream/main`
holen, Konflikte lösen, als **Merge-Commit** nach `main` — nicht squashen,
sonst kennt der Fork die Upstream-Commits nicht und dieselben Konflikte kommen
beim nächsten Mal wieder.

- [ ] **Neu Eingepflegtes an der Anlage prüfen:** Kamera-Pane (Intercom-Bild +
      Tür-Buttons), gerahmte Split-Panes, zweispaltiger Screensaver im
      Querformat, Kachelrahmen-Einstellung, Lautstärkeleiste in beiden
      Player-Ansichten, Anlagenschema. **S**
- [x] **Allgemein nützliche Fork-Teile Upstream anbieten:** die sieben
      Bausteintypen und `/api/types` sind in Upstream angekommen. Das
      Unraid-Template bleibt bewusst fork-eigen (siehe
      [`CONTRIBUTING.md`](CONTRIBUTING.md), Spalte „Nur in den Fork"), damit
      ist der Punkt abgeschlossen. **M**

### Upstream-Beiträge

Stand 23.09.2026. **Zwölf Beiträge sind in `upstream/main` gemergt, sieben
sind eingereicht und noch offen:**

| PR | Inhalt |
|---|---|
| [#13](https://github.com/Lenardo1/loxpanel/pull/13) | Struktur-Änderungen live übernehmen |
| [#15](https://github.com/Lenardo1/loxpanel/pull/15) | Kalender-Zeitzone + eingefrorene Statuszeilen |
| [#19](https://github.com/Lenardo1/loxpanel/pull/19) | Nachtmodus (Dimmen + freier Auslöser) |
| [#20](https://github.com/Lenardo1/loxpanel/pull/20) | Panel-Theme aus einer Grundfarbe |
| [#21](https://github.com/Lenardo1/loxpanel/pull/21) | Nur senden, was sich geändert hat |
| [#23](https://github.com/Lenardo1/loxpanel/pull/23) | Positionsring auf der Kachel |
| [#24](https://github.com/Lenardo1/loxpanel/pull/24) | Wetter vom Loxone-Wetterserver |
| [#25](https://github.com/Lenardo1/loxpanel/pull/25) | Split-Pane: schlanke Scrollleiste |
| [#27](https://github.com/Lenardo1/loxpanel/pull/27) | Raum als Startseite (Raum-Direkt-Tab) + Tab-Reihenfolge |
| [#30](https://github.com/Lenardo1/loxpanel/pull/30) | Positionsring: Strichstärke regelbar, gleitend, Fahrt auf der Kachel |
| [#31](https://github.com/Lenardo1/loxpanel/pull/31) | Kalender: ein Aussetzer der Quelle löscht die Termine nicht mehr |
| [#32](https://github.com/Lenardo1/loxpanel/pull/32) | Beschattung: Fahrtrichtung als Verb |

**NOCH OFFEN — diese sieben Zweige nicht löschen:**

| PR | Zweig | Inhalt |
|---|---|---|
| [#34](https://github.com/Lenardo1/loxpanel/pull/34) | `up/kleinigkeiten` | `ValueError` bei leerer `LOXPANEL_MS_PORT`; veralteter `/settings`-Hinweis |
| [#35](https://github.com/Lenardo1/loxpanel/pull/35) | `up/raumtab-leiste` | Raum-Tab in einer mehrteiligen Leiste sperrt die übrigen Seiten aus |
| [#36](https://github.com/Lenardo1/loxpanel/pull/36) | `up/eigene-auswahl` | Freie Bausteinauswahl, ganzes Feature (enthält #35 mit) |
| [#37](https://github.com/Lenardo1/loxpanel/pull/37) | `up/raumzeile-kontrast` | Raumzeile tritt zurück und schafft wieder AA (Fork #63) |
| [#38](https://github.com/Lenardo1/loxpanel/pull/38) | `up/kalender-abos` | Kalender: mehrere Abos, mehrtägige Termine, vier Parser-Fehler (Fork #66, #67, #74) |
| [#39](https://github.com/Lenardo1/loxpanel/pull/39) | `up/uhrseite-spalte` | Uhr-Seite: rechte Spalte wählbar (Fork #68–#70), setzt auf #38 auf |
| [#40](https://github.com/Lenardo1/loxpanel/pull/40) | `up/anzeige-skalierung` | Anzeigegröße und Skalierung (Fork #71, #72), setzt auf #39 auf |

Jeder dieser Zweige trägt den Kopf seines Pull Requests. Wird ein Zweig
gelöscht, schließt GitHub den zugehörigen PR. Erst entfernen, wenn Lenardo
den PR gemergt oder geschlossen hat — und zwar einzeln, nicht in einem Rutsch.

Zu #35 und #36: Der Fehler in #35 steckt in Lenardos Code und ist an seinem
unveränderten `panel.html` im Browser nachgestellt — `renderTabs()` ersetzt
die ganze untere Leiste, sobald eine Ansicht nicht-leere `catTabs` mitbringt,
ohne zu prüfen, ob das Panel nur diese eine Seite hat. #36 enthält dieselbe
Bedingung, weil die freie Auswahl ohne sie in dieselbe Falle liefe — aber mit
anderem Wortlaut und auf die freie Auswahl verallgemeinert. Deshalb kollidieren
die beiden: Nacheinander angewendet gibt es in `renderTabs()` einen Konflikt,
per Cherry-Pick wie per Rebase nachgeprüft (22.09.2026). Vorschlag an Lenardo:
#34 und #36 mergen, #35 schließen. Wird #35 doch zuerst gemergt, gilt beim
Konflikt die Fassung aus #36.

Zu #37 bis #40 (eingereicht am 23.09.2026): #37 steht für sich. #38, #39 und
#40 sind gestapelt, weil sie dieselben Stellen im Screensaver ändern: #39
enthält den Commit aus #38, #40 die aus #38 und #39; neu ist jeweils nur der
letzte. Sie müssen in dieser Reihenfolge gemergt werden. **Nach jedem Merge den
nächsten Zweig auf das neue `upstream/main` rebasen und mit
`--force-with-lease` pushen** — sonst zeigt der PR den schon gemergten Commit
weiter mit. Alle vier sind auf `upstream/main` gebaut und dort geprüft
(Parser-Fälle, Abruf, Kalender Ende zu Ende, alle Spalten-Modi,
Skalierungskette, Messwerte), und sie gehen auch nach #33, #34 und #36 sauber
durch. Die README bleibt außen vor, Lenardos README beschreibt den Kalender
nicht.

Überschneidung mit Lenardos eigenem #33 (englische Übersetzungen): #38 bringt
zehn Katalog-Einträge mit, die #33 auch hat, neun wortgleich, einer anders
formuliert („Standort vom Miniserver wird verwendet."); #40 dazu
„Automatisch", gleich übersetzt. Doppelte Schlüssel sind kein Fehler, der
spätere gewinnt. Mergt Lenardo #33 zuerst, die Doppel aus #38 und #40
herausnehmen; angekündigt ist das im Text von #38.

Die Zweige der zwölf gemergten Beiträge sind gelöscht. Für den nächsten
Beitrag wieder genauso vorgehen: EIN Commit direkt auf `upstream/main`
aufsetzen, damit GitHub Titel und Beschreibung selbst füllt, und über diesen
Link einreichen:
`https://github.com/Lenardo1/loxpanel/compare/main...CHief-Wiggum1203:Loxpanel:<zweig>?expand=1`

Der Fork ist mit `upstream/main` gleichgezogen (siehe oben).

## 1. Konfiguration vor Datenverlust schützen

- [x] **Atomares Schreiben** von `loxpanel.cfg`, `panels.json`, `theme.json`:
      in `<datei>.tmp` schreiben, `fsync`, `os.replace`. Stellen: `_write_cfg`,
      `_persist_panels_file`, `_write_theme` in `bin/webvisu.py`. (F5) **S**
- [x] **Fehlerbehandlung beim Schreiben**: `OSError` in `_write_cfg` und den
      beiden Settings-Handlern fangen und als `{"ok": false, "error": ...}`
      zurückgeben statt 500. (F6) **S**
- [x] **Sicherung vor dem Überschreiben**: vor jedem Schreiben von `panels.json`
      eine Kopie `panels.json.bak` behalten, eine Generation reicht. **S**
- [x] **Unvollständige `loxpanel.cfg` abfangen**: `reconnect()` mit `.get()` statt
      `ms["user"]`, verständliche Fehlermeldung in `/config` (Settings). (F7) **S**

## 2. Server-Stabilität

- [x] **Befehle nach ein bis zwei Tagen wirkungslos (Token läuft ab)**: Das
      Miniserver-Token wurde nur erneuert, wenn der WebSocket abriss. Blieb er
      stabil, lief es ab — die Anzeige lief weiter, aber jeder Befehl (auch
      Icons und Verläufe) scheiterte still mit 401. Jetzt laufen alle
      HTTP-Anfragen über `_ms_http()`, das sich bei 401 einmal neu anmeldet und
      wiederholt; gescheiterte Befehle zeigt das Panel als Hinweis an. (F15,
      `ARCHITEKTUR.md` §3.4) **S**
- [x] **Broadcaster absichern**: Upstream 0.3.2 fängt Render-Fehler je
      Verbindung im `broadcaster()` und bei `nav` ab. `_push()`, `switch_mode()`
      und `api_testtone` fingen schon jeden Fehler, hatten aber kein Zeitlimit;
      sie senden jetzt über `_send_or_drop()` (5 s, trennt hängende
      Verbindungen). (F3) **S**
- [x] **`op_modes` in `App.__init__` initialisieren**, `getattr`-Workaround
      entfernt. Ohne Miniserver warf `/api/types` vorher einen
      `AttributeError`. (F2) **S**
- [x] **Timeout für Icon- und Cover-Abrufe**: `fetch_icon` hatte schon 6 s,
      `fetch_cover` hat jetzt `COVER_TIMEOUT` und fängt `asyncio.TimeoutError`.
      (F8) **S**
- [x] **`icon_cache` begrenzen**: `ICON_CACHE_MAX` = 500, der am längsten
      unbenutzte Eintrag fliegt zuerst. (F4) **S**
- [x] **HTTP-Handler für die vier HTML-Dateien**: `_web_file()` liefert bei
      fehlender Datei einen 404 mit Dateinamen statt eines Stacktrace. **S**
- [x] **`JSON.parse` im WebSocket-Handler** der Visu in `try/catch`. (F9) **S**
- [x] **Reconnect mit Backoff**: `MS_RETRY` 5, 10, 20, 40, 60 s; von vorn erst,
      wenn eine Verbindung mindestens 60 s hielt. **S**
- [x] **Rückfall auf Miniserver-Favoriten ist unerreichbar**: `_view_sources`
      verzweigt nur danach, ob ein Ereignis-Client existiert, nicht darauf, ob
      die Anmeldung am Audioserver geklappt hat. Schlägt sie fehl, greift der
      dafür gedachte Rückfall (`_audio_favs`) nie — der Zweig ist toter Code.
      Prüft jetzt dieselbe Bedingung wie `prime_favs()` (nicht gekoppelt oder
      angemeldet). **S**

## 3. Sichtbare Fehler in der Visu

- [x] **Escaping in `panel.html`**: `esc()` um `"` und `'` ergänzen. Betrifft
      Attribute mit Miniserver-Namen und Freitext-Schriftarten. (F10) **S**
- [ ] **Panel-`states`-Farben validieren** mit `_color_ok` in
      `_sanitize_panels`, oder das Feld entfernen, da der Konfigurator es nicht
      anbietet. (F11) **S**
- [ ] **Icon-Routen `/gicon` und `/uicon`**: entweder registrieren (Google
      Material Icons per Proxy, Upload-Verzeichnis für eigene Icons) oder die
      Erzeugung in `_apply_tile_style` und die Annahme in `_clean_icon`
      entfernen, bis das Feature gebaut wird. (F1) **S** (entfernen) / **M** (bauen)
- [x] **`updatePanel()` robust machen**: gelöst über eine Struktur-Signatur
      (`blockSig()`): weicht Art/Reihenfolge der Blöcke vom zuletzt Gerenderten
      ab, wird komplett neu aufgebaut, sonst weiter in-place (kein Flackern).
      Zusätzlich werden alle Blöcke einer Art über ihre Position gepatcht statt
      nur der erste Treffer — das war die Ursache für eingefrorene Statuszeilen
      auf der Sauna-Detailseite. (F12) **M**
- [ ] **Stiller Verlust beim Speichern**: `_sanitize_panels` soll melden, welche
      Felder verworfen wurden, und der Konfigurator zeigt es an. (W7) **M**
- [ ] **Speicher-Vorzeichen im Energiemanager prüfen**: `_flow_text(Spwr, …)`
      und `classify()` nehmen an, dass ein positiver `Spwr` „Speicher lädt"
      bedeutet. Die Loxone-Doku beschreibt es umgekehrt (positiv = Speicher
      wird entladen). Wenn das stimmt, sind Laden/Entladen in Text **und**
      Flussrichtung des Radials vertauscht. An einer Anlage mit echtem Speicher
      gegenprüfen, bevor etwas geändert wird — betrifft auch den
      Energiefluss-Beitrag an Upstream. **S**

## 4. Performance

- [x] **Nur senden, was sich geändert hat**: umgesetzt in `broadcast_task`
      (`bin/webvisu.py`, `self._last_sent` pro WebSocket). Nicht nur `view`,
      sondern auch `player`, `energy` und `camera` werden je Verbindung
      verglichen und bei Gleichheit übersprungen. Upstream angenommen als
      [#21](https://github.com/Lenardo1/loxpanel/pull/21). (P1) **S**
- [ ] **Nur rendern, was betroffen ist**: pro Route die Menge der State-UUIDs
      merken, die sie liest, und nur bei Änderung einer dieser UUIDs neu rendern.
      Zweiter Schritt nach dem ersten Punkt. (P1) **M**
- [ ] **JSON-States einmal parsen**: `moodList`, `entryList`, `sourceList`
      beim Eintreffen in `_on_value` parsen und geparst cachen statt bei jedem
      Rendering. (P1) **M**
- [ ] **`panels.json` einmal lesen**: `load_panels` und `load_devices`
      zusammenlegen. (P2) **S**
- [ ] **Klingel- und Wecker-Pushes filtern**: nur an Panels, die den
      betreffenden Baustein überhaupt anzeigen dürfen. (P3) **S**

## 5. Unraid-Betrieb

- [ ] **`HEALTHCHECK` im Dockerfile**, z. B. `GET /api/settings`. Unraid zeigt
      dann den Zustand im Docker-Tab. **S**
- [ ] **Altlasten aus dem Image halten**: `.dockerignore` um
      `webfrontend/htmlauth`, `config/visu.*`, `daemon/`, `postinstall.sh`,
      `apt`, `plugin.cfg` ergänzen. **S**
- [ ] **Log-Level per Umgebungsvariable** (`LOXPANEL_LOG_LEVEL`), damit der
      Zugriffs-Log von aiohttp im Normalbetrieb ruhig ist. **S**
- [ ] **Backup-Endpunkt** `GET /api/backup` liefert die drei Config-Dateien als
      ZIP, die Rubrik Settings bekommt einen Download-Button. Ersetzt die
      Widget-Funktion des LoxBerry-Plugins auch auf Unraid. **M**

## 6. Wartbarkeit

- [ ] **Agent nur einmal pflegen**: Server liefert `agent/loxpanel-agent.py`
      unter `/loxpanel-agent.py` aus, `install-agent.sh` holt die Datei per
      `curl` statt sie als Heredoc zu enthalten. (W2) **S**
- [ ] **Duplikate zusammenführen**: `esc()` doppelt, `ICONS`/`BICONS`,
      Overlay-Berechnung,
      Config-Leser `_config`/`_audio_config`/`_intercom_config`,
      `api_testtone` gegen `_push`. (W3) **M**
- [ ] **Magische Zahlen als Konstanten** am Dateianfang: Broadcaster-Takt,
      Reconnect-Pausen, Agent-Timeouts, Ports, Daytimer-Dauern,
      Farbtemperaturen. (W5) **S**
- [ ] **Bausteinketten aufteilen**: Tabelle `Typ → (kachel_fn, detail_fn)`
      statt der `elif`-Ketten, ein Modul pro Bausteinfamilie. Protokoll bleibt
      gleich. (W1) **L**
- [ ] **Kategorie-Farben exakt statt per Teilstring** zuordnen, mit
      Rückwärtskompatibilität für bestehende `theme.json`. (W6) **S**
- [ ] **`_irc_modes`-Filter** nicht über den Text „schutz", sondern über die
      Modus-ID. (W4) **S**
- [ ] **Altlasten entfernen**: `daemon/`, `postinstall.sh`, `apt`, Root-
      `plugin.cfg`, `webfrontend/htmlauth/index.php`, `bin/loxone_live.py`,
      `bin/loxone_client.py`, `bin/importer.py`, `config/visu.*`,
      `deploy/kiosk.sh`, `deploy/loxpanel-webvisu.service`,
      `agent/loxpanel-agent.service`. Vorher entscheiden, wie eng dem Upstream
      gefolgt wird, sonst Merge-Konflikte. **S**
- [ ] **Diagnose-Skripte in `bin/`** bereinigen: fest kodierte UUIDs und IPs
      durch Argumente ersetzen oder die Skripte in einen Ordner `tools/`
      verschieben und aus dem Image ausschließen. `requests` in
      `requirements.txt` aufnehmen oder die drei Nutzer umstellen. (F14) **M**
- [ ] **Doku angleichen**: Changelog ab 0.3.0 nachtragen, `armhf` durch
      `armv7l` ersetzen, Stromspar-Pause als optional beschreiben,
      `loxpanel-kiosk.conf.example` vervollständigen, `DOCKER.md`/`DEPLOY.md`
      vom „späteren Plugin" befreien, Root-`docker-compose.yml` auf das fertige
      Image umstellen. **S**
- [ ] **Toter Zweig im EFM-Detail entfernen**: in `_view_control_inner` kann
      `energy_blocks()` im `EFM`-Zweig nie `None` liefern, damit sind die dort
      aufgebauten `rows` und der `else`-Zweig unerreichbar. Entweder entfernen
      oder den Aufruf absichern. **S**
- [ ] **`loxpanel-kiosk.conf.example` vervollständigen**: der Agent liest 13
      Schlüssel, die Beispieldatei dokumentiert 10. Es fehlen `PROFILE_DIR`,
      `BL_DEVICE` und `STATE_FILE`; besonders `BL_DEVICE` ist nutzerrelevant,
      wenn die Backlight-Erkennung danebengreift. **S**

## 7. Tests und CI

- [x] **pytest für reine Funktionen**: `_fmt_num`, `_color_parse`,
      `_alarm_next_text`, `_alarm_entries`, `_audio_favs`, `_tracker_lines`,
      `_resolve_ids`, `_sanitize_panels`, `LoxoneWS._parse_values`,
      `LoxoneWS._parse_texts` in `tests/test_reine_funktionen.py`, dazu die
      Statistik-Rechnungen. Eine `App` ohne Verbindung reicht dafür. (W8) **M**
- [x] **Server-Tests gegen einen Miniserver-Nachbau** (`tests/lox.py`):
      Verläufe V1/V2, Kachel-Stile, Token-Erneuerung, Stabilität; Visu und
      Konfigurator in Chromium (`tests/browser/`). **M**
- [x] **Lint im Workflow** (`ruff`): gleich als harte Prüfung, weil mit den
      Fehlerregeln (`F`, `E9`) nur eine tote Zuweisung übrig war
      (`loxone_weather.py`, entfernt). **S**
- [x] **Rauchtest im Workflow**: `tests/test_rauchtest.py` startet den Server
      als eigenen Prozess ohne Miniserver und ruft alle Oberflächen und die
      Lese-APIs ab; kein Stacktrace im Log. **S**
- [x] **Workflow auch für Pull Requests**: `tests.yml` auf jedem PR und Push auf
      `main`, dazu bei PRs ein Probe-Build des Images (amd64, ohne Push); der
      Multi-Arch-Build mit Push bleibt in `docker-image.yml` auf `main`. **S**

## 8. Bausteine: was fehlt

Stand aus dem Code (Commit `de31d76`): `_control_item()` und
`_view_control_inner()` in `bin/webvisu.py` behandeln 59 Typen. Ein
unbekannter Typ ergibt eine tote Kachel ohne Untertitel und ohne Reaktion, so
wie „Energieflussmonitor" in der Testanlage. Vorgehen je Typ: Rezept (a) in
[`ARCHITEKTUR.md`](ARCHITEKTUR.md), State- und Befehlsnamen aus der eigenen
Strukturdatei (`LoxAPP3.json`) des Miniservers ablesen.

### 8.1 Zuerst

- [x] **Diagnose-Endpunkt `/api/types`**: listet alle Bausteintypen der
      verbundenen Anlage mit Anzahl, Beispielnamen, Unterstützungsstatus
      (voll / teilweise / keine), State-Namen und `details`-Schlüsseln je Typ
      sowie die toten Kacheln mit Raum. `?format=text` für den Browser, Link
      unter *Einstellungen → Miniserver*. **S**
- [ ] **Unbekannte Typen sichtbar machen**: im Fallback von `_control_item()`
      Untertitel „Typ nicht unterstützt" statt leerer Kachel, und die Kachel
      per `hide` ausblendbar lassen. **S**
- [ ] **README-Tabelle angleichen**: `AudioZoneV2` und `EIBDimmer` sind im Code
      umgesetzt, fehlen aber in der Tabelle (die Roadmap nennt `AudioZoneV2`
      noch als offen). `ColorPicker` steht als „voll" in der Tabelle, der Code
      prüft `Colorpicker` (kleines p); den tatsächlichen Typnamen in der
      Strukturdatei prüfen und Code oder Tabelle korrigieren. **S**

### 8.2 Komplett fehlend, im README als geplant geführt (16)

Kurz: was der Baustein ist und was ein Zweig mindestens braucht.

- [ ] `MoodSwitch` (Stimmungsschalter): wie `LightControllerV2`, Stimmungsliste
      und aktive Stimmung, Befehl `changeTo/<id>`; Licht-Adapter wiederverwenden. **S**
- [ ] `Sequential` (Sequenzer): aktueller Schritt, Befehle Weiter/Start/Stop. **S**
- [ ] `Heatmixer` (Heizungsmischer): Ist- und Solltemperatur, Ventilstellung,
      nur Anzeige. **S**
- [ ] `LoadManager` (Lastmanager): Lastliste mit Zustand, nur Anzeige. **S**
- [ ] `NfcCodeTouch`: letzter Zutritt und Zustand, nur Anzeige; Codes werden
      nicht in der Visu gepflegt. **S**
- [ ] `SolarPumpController` (Solarpumpe): Temperaturen, Pumpenzustand, Modus
      umschalten. **M**
- [ ] `ClimateController` (Klimaregelung EU): Betriebsart, Solltemperatur,
      Zustände Heizen/Kühlen. **M**
- [ ] `IRoomController` (alte Raumregelung): Ist/Soll, Betriebsarten,
      Override wie bei V2. **M**
- [x] `Sauna` (Sauna-Steuerung): **vollständig**. Anzeige von Ist/Soll/Bank,
      Betriebsart (`mode` 0..6 als Klartext), Feuchte (Ist/Soll), Lüftung,
      Trocknung, Tür, Betriebstemperatur, Wassermangel, Timer und Störung.
      Bedienung: Ein/Aus (`on`/`off`), Solltemperatur (`temp/<wert>`, ±1/±5 °C)
      und Betriebsart (`mode/<0..6>` als Aufklapper). States und Befehle an der
      echten Anlage verifiziert (`bin/sauna_probe.py`). **M**
- [ ] `PoolController` (Pool): Modus, Temperaturen, Filterlauf, Befehle. **M**
- [ ] `LightsceneRGB` (RGB-Lichtszene): Szenenliste, aktive Szene, Farbe
      setzen; Farbwahl aus `ColorPickerV2` wiederverwenden. **M**
- [ ] `Remote` (Fernbedienung): Modusliste und Tastenbefehle als Button-Raster. **M**
- [ ] `Wallbox` (Ladestation): Ladeleistung, Energie, Ladezustand, Modus und
      Leistungsgrenze setzen. **M**
- [x] `EnergyManager2` (Energiemanager): Erzeugung, Netz, Speicher mit
      Ladestand und Reserve, Verbraucherliste aus `loads`; nur Anzeige. **M**
- [ ] `SpotPriceOptimizer` (Strompreis-Optimierer): Preisverlauf und Plan,
      nur Anzeige. **M**
- [ ] `MediaClient` (Media Client, alt): Steuerung veralteter Geräte;
      niedrige Priorität, nur bei Bedarf. **L**

### 8.3 Weder im Code noch im README erwähnt

Typen, die Loxone in der Strukturdatei liefert, hier aber nirgends vorkommen.
Welche davon relevant sind, zeigt der Diagnose-Endpunkt aus 8.1.

- [x] `EFM` (Energieflussmonitor, Typname in der Strukturdatei ist `EFM`):
      Erzeugung, Netz mit Bezug/Einspeisung, Speicher mit Laden/Entladen,
      Knoten aus `details.nodes` mit `actual0..5`; nur Anzeige. Annahme
      Vorzeichen wie in der Loxone-App (positiv = Bezug bzw. Laden), auf der
      Anlage gegenprüfen. **M**
- [x] `PvProductionForecast` (PV-Produktionsvorhersage): heute, morgen,
      Zeitraum, danach, Anlagenleistung. **S**
- [x] `SteakThermo` (Touch & Grill Thermometer): Fühlertemperaturen aus
      `currentTemperatures`, Zielwerte, Alarmtext, Timer, Akku. Struktur von
      `currentTemperatures` auf der Anlage gegenprüfen. **S**
- [ ] `EnergyManager` (Energiemanager, alte Version), `Wallbox2`, `CarCharger`:
      ältere bzw. neuere Varianten der Energie-Bausteine. **M**
- [ ] `IntercomV2`: neue Türsprechstelle, nach dem Muster von `Intercom`. **M**
- [ ] `IRCDaytimer`, `IRCV2Daytimer`: Zeitpläne der Raumregelung, nach dem
      Muster von `Daytimer`. **S**
- [x] `Irrigation` (Bewässerung): Zustand, aktive Zone, Zonenliste,
      erwarteter Niederschlag als Anzeige; Bedienung Start/Erzwingen/Stopp und
      alle Zonen an/aus (`start`/`startForce`/`stop`/`select/9`/`select/0`, aus
      der Loxone-Structure-File-Doku). Offen: Auswahl EINZELNER Zonen
      (`select/<n>`) — Zonennummerierung mit `bin/steuer_probe.py --zones`
      an der Anlage klären. **M**
- [ ] `AlarmChain`, `AalEmergency`, `AalSmartAlarm` (Alarmkette, Notfall,
      Smart Alarm): Zustand und Quittieren nach dem Muster von `Alarm`. **S**
- [x] `MailBox` (Briefkasten): Post da / Paket da / leer als Anzeige.
      Offen: Quittieren, Befehlsname auf der Anlage prüfen. **S**
- [ ] `LeafSystem`, `PowerUnit`: Anzeige-Bausteine, nur Werte. **S**
- [ ] `UpDownLeftRightAnalog`, `UpDownLeftRightDigital`: vier Richtungstasten,
      nach dem Muster von `UpDownDigital`. **S**
- [ ] `Application`, `MsShortcut`: Verknüpfungen, in der Visu ausblenden statt
      tote Kachel. **S**

### 8.4 Nur teilweise umgesetzt (6)

- [x] `AudioZoneV2` (Loxone Audioserver Gen 2, gekoppelt): vollständig.
      Play/Pause/Skip und Lautstärke laufen über den Miniserver (`sps/io`),
      Titel/Sender/Cover live über den Ereigniskanal (`remotecontrol`). Die
      Raumfavoriten liefert der gekoppelte Audioserver nur einer angemeldeten
      Verbindung; die Anmeldung wurde wie in der Loxone-App nachgebaut
      (`bin/audioserver_auth.py`): Session-Token aus dem Banner,
      `audio/cfg/getkey` → RSA-Schlüssel, Miniserver-JWT mit AES-256-CBC
      verschlüsselt, `key:iv:sessionToken` mit RSA-PKCS#1-v1.5, dann
      `secure/authenticate/<user>/<rsa>/<chiffre>`. Danach `getroomfavs` und
      `roomfav/play/<id>` auf derselben Verbindung. An der echten Anlage (LWSS
      17.2) verifiziert. **M**
- [x] `AudioZone` (Musikserver Gen 1, MS4H, Sonn) und `AudioZoneV2`
      (Audioserver Gen 2): Favoriten und Steuerung laufen direkt am
      Audioserver (Port 7091) — aber nur bei einem **ungekoppelten**
      Audioserver (`paired is False`). Am gekoppelten Audioserver läuft die
      Steuerung bewusst über den Miniserver (`sps/io`); so seit dem Fix der
      Paired-Weiche. **M**
- [ ] `AlarmClock` (Wecker): Anzeige + Weckton; beim Klingeln Schlummer
      (`snooze`) und Aus (`dismiss`). Offen: Master-Ein/Aus (`setActive`, zu
      verifizieren) und Bearbeiten/Anlegen der Weckzeiten (braucht Zeit-/
      Wochentag-Picker im Frontend, eigenes Feature). **M/L**
- [ ] `Intercom`: Kamera, Live-Klingelanzeige (`bell`) auf Kachel/Detail,
      Tür/Ausgänge öffnen (`pulse` je Sub-Control). Offen: Gegensprechen (SIP,
      eigener Medien-Stack), Klingel-Historie mit Vorschaubildern (neue
      Bild-Route, Format an der Anlage zu prüfen). **L**
- [ ] `TextInput`: nur Anzeige, keine Eingabe. **S**
- [ ] `UpDownAnalog`: nur Anzeige. Setz-Befehl noch nicht belegt (Roh-Wert vs.
      Auf/Ab-Puls unklar) — mit `bin/steuer_probe.py --updown` an der Anlage
      klären, dann Steuerung bauen. **S**
- [ ] `Ventilation` (Lüftung): nur Stufe anzeigen, kein Umschalten. **S**

## 9. Weitere Funktionen

- [x] **Positionsring: eingefroren, zu kräftig, und die Kachel schwieg zur
      Fahrt.** Drei Befunde aus einer Messung am echten Code, nicht aus dem
      Gefühl:
      *(a)* `updateGrid()` patcht die Kachel in-place, fasste `.posring` aber
      nie an — der Bogen blieb auf dem Stand vom letzten Vollrender stehen,
      während die Zweitzeile weiterzählte (im Browser nachgestellt: Text 20 →
      95 %, Ring unverändert bei 20 %). Jetzt wird er mitgezogen, dazu
      `transition:stroke-dasharray .4s` — er folgt der Fahrt, animiert aber
      nichts im Stand.
      *(b)* Die Strichstärke hing an einem festen `stroke-width:6` in einer
      Box von `--ico-size + 18px`. Durch den festen Summanden fällt der Ring
      bei kleinen Icons dicker aus als die Icon-Linien: gemessen 1,25× bei
      38 px, 1,48× bei 24 px, 2,75× bei 8 px. Jetzt über `ring`/`rtrk`/`rw`
      im vorhandenen `overlay`-Dict regelbar, Defaults = die alten Hartwerte.
      *(c)* Die Kachel kannte nur die Stellung, nicht die Fahrt, obwohl der
      Server `up`/`down` für die Detailansicht längst liest. Sie zeigt jetzt
      „▲ fährt … 40% zu". **M**

      *Upstream angenommen* als PR #30. Lenardo hatte den eingefrorenen Ring
      unabhängig selbst gefunden (`updateTileRing()`) und die Strichstärke als
      Live-Regler `?ring=` gebaut; beim Zusammenführen hat seine Benennung
      gewonnen — die CSS-Variablen heißen `--posring-w`/`--posring-op`/
      `--posring-trk`, die Schlüssel in `panels.json` unverändert
      `rw`/`ring`/`rtrk`. Sein `?ring=` schlägt die Konfiguration
      (`posringOverride()` greift nach dem Theme-Push erneut).

- [ ] **Bedientasten auf der Kachel: erst den Auslöser reparieren.** Auf/Ab
      direkt auf der Beschattungs-Kachel wäre über die vorhandene
      `controls`-Mechanik des Audioplayers billig zu haben, ist aber bewusst
      NICHT gebaut: die Tasten lösen per `pointerdown` schon beim Aufsetzen
      des Fingers aus und schlucken dabei die Wischgeste. Das Kachelraster
      scrollt (`.grid{overflow-y:auto}`) — ein Wischer, der auf so einer
      Taste beginnt, ließe die Beschattung losfahren statt zu scrollen.
      Gemessen: ein blankes `pointerdown` sendet `{"t":"cmd","cmd":"Up"}` und
      setzt `defaultPrevented`. Beim Player kostet das einen Titel, bei einer
      Jalousie eine halbe Minute Fahrt. Die Kachel selbst hat das Problem
      nicht, sie wartet auf einen echten Klick. Vorbedingung für Tasten auf
      Kacheln ist also, `.tctrls .tb` auf eine echte Tippgeste umzustellen
      (Aufsetzen und Loslassen ohne nennenswerte Bewegung) — das nützt dem
      Player gleich mit. **S**

- [x] **Raum als Startseite (Raum-Direkt-Tab).** Aus dem Forum: die kleinen
      Panels bedienen meist EINEN Raum, nicht das ganze Haus — sie sollen nach
      dem Aufwecken direkt in diesem Raum stehen, ohne vorher Raum oder
      Kategorie zu wählen. Umgesetzt als Gegenstück zum vorhandenen
      Kategorie-Direkt-Tab: `room:<uuid>` in `_is_tab()`, `_view_tab()` und
      `_tab_meta()`, in der Tab-Auswahl der Konfiguration angeboten. Am
      Aufwach-Verhalten war nichts zu ändern — es hängt am ersten Tab
      (`conn_route` beim Verbinden, `resetIdle()` nach 60 s Leerlauf). Dazu ein
      Bugfix, ohne den die Direkt-Tabs ihren Zweck nicht erfüllen konnten:
      `toggleTab()` sortierte die gewählten Tabs hart nach der Reihenfolge von
      `/api/meta`, wo Kategorien und Räume hinten stehen — sie rutschten damit
      immer ans Ende und konnten nie Startseite sein, außer als einziger Tab.
      Das betraf auch die schon vorhandenen `cat:`-Tabs. Jetzt ist die
      Klickreihenfolge die Reihenfolge der Leiste. **S**

- [x] **Frei zusammengestellte Seite („Eigene Auswahl").** Aus dem Forum: eine
      Seite aus beliebigen Bausteinen, unabhängig von Raum und Kategorie. Eine
      je Panel, Schlüssel `auswahl` (`PICK_TAB`), Profil trägt `picks` (geordnete
      UUID-Liste, gedeckelt bei 60) und `pickName`. Der Panelfilter gilt hier
      bewusst **nicht** — wer einen Baustein ausdrücklich wählt, will ihn sehen;
      nur `hide` bleibt als Sicherheitsnetz.

      Danach nachgebessert, weil sich die Bedienung nicht gut anfühlte: die
      Seite ist jetzt der **dritte Modus** der unteren Leiste, neben Raum-Panel
      und Klassisch. Der Umschalter wechselt in Wahrheit die *Bedeutung* der
      Leiste — bei Raum-Panel und Eigener Auswahl sind es Sprungmarken statt
      Seiten. Die Auswahl gruppiert nach **Raum**, die Leiste zeigt bis zu vier
      Räume als Sprungmarken (erst ab zwei Räumen), ein Tipp scrollt zur Gruppe.
      Dieselbe Mechanik wie beim Raum-Panel (`catKey` als Anker, `catTabs`).
      Zusammenstellen und Sichtbarmachen liegen damit an einer Stelle; der
      eigene Unterreiter ist entfallen. Dazu eine geführte Einrichtung in drei
      Schritten, ein Raumfilter über der Bausteinliste und eine Vorschau der
      Sprungmarken. Drei Fehler nebenbei behoben: der Chip in der Konfiguration
      zeigte das feste Serverlabel statt des vergebenen Namens; ein
      Moduswechsel verwarf eine selbst zusammengestellte Tab-Leiste ohne
      Rückfrage; und eine leere `catTabs`-Liste wurde im Panel als „kein Wert"
      statt als Aussage gelesen, sodass Sprungmarken stehen blieben, die ins
      Leere zeigten. Raumnamen stehen als Text in der Leiste, wenn der Raum
      kein Bild hat — mit vier gleichen Symbolen wäre sie nicht zu treffen.

      Eine Gegenprüfung des fertigen Standes vor dem Merge fand noch einen
      **kritischen Fehler**: Sprungmarken ersetzen im Panel die *ganze* untere
      Leiste. Stand der Auswahl-Tab in einer klassischen Leiste neben anderen
      Seiten, waren diese damit unerreichbar — der Zurück-Knopf hilft nicht,
      weil die Seite die unterste im Stapel ist, und der Leerlauf springt nach
      60 s wieder auf denselben ersten Tab. Behoben an beiden Enden: der Server
      liefert Sprungmarken und Anker nur noch, wenn die Seite allein in der
      Leiste steht (`prof["tabs"] == [PICK_TAB]`), und `renderTabs()` ersetzt
      die Leiste nur noch im Ein-Seiten-Modus. Die zweite Sperre behebt
      dieselbe Falle für einen `room:`-Tab in einer klassischen Leiste, die es
      schon vorher gab — **dafür lohnt ein Hinweis an Upstream**.

      Dazu drei kleinere Funde derselben Prüfung: die Konfiguration zählte
      ausgeblendete Bausteine bei der Gruppierung mit (der Server wirft sie per
      `_shown()` vorher weg), wodurch ein unsichtbarer Baustein die
      Raumreihenfolge und alle Nummern dahinter verschob; ein enger
      `I18N.autoChrome()`-Aufruf im Auswahl-Editor hätte den modulweiten
      Selektor verengt und damit die Übersetzung der restlichen
      Konfigurationsseite abgeschaltet (jetzt `applyChrome` auf den Teilbaum);
      und zwei neue Code-Kommentare trugen Umlaute entgegen der Konvention. **M**

- [x] **Front: Kalender + Wetter auf dem Screensaver.** Neu `bin/front_info.py`
      (eigenständig, keine Fremdabhängigkeit): iCal-Abo laden und parsen
      (`icalendar` + `python-dateutil`, löst Serientermine auf) und Wetter von
      Open-Meteo (kein API-Key, nur Koordinaten). Der Server holt beides alle
      15 Min (`front_task`) und pusht `{t:"front"}`; die Uhr-Startseite zeigt
      Wetter oben und die nächsten Termine unten. Pflegbar unter *Settings →
      Kalender & Wetter*, gespeichert im `calendar`-Block von `loxpanel.cfg`. **M**
- [x] **Screensaver: rechte Spalte nutzbar machen.** Im Querformat stand rechts
      neben der Uhr nur die Terminliste — gab es keine Termine (oder kein
      iCal-Abo), blieb die halbe Fläche leer, während das Wetter links auf 50 %
      gedrängt blieb. Jetzt entscheidet je Panel `ui.svPane`, was dort steht:
      Automatik (Termine, sonst die Wetter-Details mit Stundenverlauf,
      Luftfeuchte, Wind, Sonne), fest Termine, fest Wetter, Energiefluss,
      Kamera, frei gewählte Bausteine als Werte-Kacheln (neu `status_blocks()`
      + `{t:"svstatus"}`, gebaut über `_control_item()` wie jede Kachel) oder
      gar nichts — dann rücken Uhr und Wetter auf die volle Breite. Geprüft an
      einer Stelle (`_clean_svpane()`), einstellbar unter *Panels → Aussehen &
      Verhalten*. Hochkant und auf dem 4″-Panel unverändert. Nebenbei behoben:
      eine Kamera-Pane streamte bisher hinter dem Screensaver weiter. **M**
- [x] **Display-Auflösungen erkennen und die Visu darauf skalieren.** Die Visu
      rechnet mit festen 240er Kacheln; auf einem größeren Display stand der
      Kasten mit schwarzem Rand da (1280×800: 55 % ungenutzt), und „Bildschirm
      füllen" vergrößerte nur die Kacheln, nicht Schrift und Icons. Jetzt
      meldet jedes Panel seine Größe (Anzeige unter Settings → Panels:
      sichtbare Fläche, physische Pixel, Faktor, genutzter Anteil), und je
      Profil lässt sich eine Skalierung wählen: aus, automatisch oder ein
      fester Faktor. Pro Gerät übersteuerbar, sodass zwei Displays mit
      demselben Profil unterschiedlich laufen können; die Geräteeinstellung
      wirkt ohne Neuladen. Geräte, die nur eine Skalierung tragen, fielen beim
      Speichern bisher still weg (Server und Konfigurator) — behoben. **L**
- [x] **Skalierung auch global unter Global → Darstellung.** Gilt für alle
      Panels, deren Profil „Wie global" eingestellt hat (das ist jedes Profil,
      das keine eigene Skalierung trägt); das Profil zeigt den geerbten Wert in
      Klammern. Nebenbei behoben: `_write_theme()` und `/api/meta` führten je
      eine eigene Liste der globalen Darstellungs-Keys, ein neuer Key ging so
      beim Speichern still verloren. Die Liste steht jetzt einmal in
      `THEME_UI_KEYS`. Die Skalierungs-Auswahl schnitt bei „Automatisch
      (Bildschirm ausnutzen)" ab (allgemeine 220-px-Grenze für Auswahlfelder)
      — behoben. **S**
- [x] **Uhr-Seite mit Energiefluss/Kamera: Proportionen.** Links nutzten Uhr
      und Wetter nur 49 % der Höhe, die Uhr hatte noch die 60 px des
      Querformats, die Box rechts wirkte dadurch übergroß. Jetzt gleich breite
      Spalten, Uhr 96 px, links 70 % der Höhe genutzt. Energiegrafik unverändert
      392 px (höhenbegrenzt), Kamerabild 454×341 → 418×314. **S**
- [x] **Energiefluss: Beschriftungen ab sieben Knoten laufen in die Nachbarringe.**
      Erledigt mit „Beschriftung außerhalb der Ringe" (#31), an der Anlage
      bestätigt.
      Die Namen und Werte stehen mit festem Abstand über bzw. unter ihrem Ring.
      Ab sieben Knoten rücken die Ringe so eng zusammen (40° Abstand, Radius 34),
      dass die Beschriftungen der Seitenknoten in die Ringe der Nachbarn ragen —
      gemessen bei neun Knoten mit üblichen Namen („Klimaanlage OG",
      „Wärmepumpe Keller"): sechs Überschneidungen. Betrifft Hauptschirm und
      Screensaver gleichermaßen, weil beide dasselbe SVG zeichnen
      (`energyInner()` in `panel.html`). Die Grafik trägt dann die Klasse
      `dicht`; der Screensaver vergrößert die Namen in dem Fall bewusst nicht.
      Lösungsidee: Beschriftung der Seitenknoten nach außen statt nach oben/unten
      setzen. **M**
- [ ] **Kalender/Wetter als eigener Tab**: volle Terminliste zum Durchscrollen
      und größere Wetteransicht, nicht nur die Front. **M**
- [ ] **Heizung: Modus-Umschaltung** im `IRoomControllerV2` über die
      Betriebsart, nicht nur Override. **M**
- [ ] **Panel-Texte mehrsprachig**: die rund 90 hart deutschen Strings im Server
      in einen Katalog ziehen, `lang` aus dem Profil auswerten. Nur nötig,
      wenn ein Panel nicht deutsch sein soll. **L**

- [x] **Verlaufs-Diagramme** (#78–#80): Aufzeichnungen des Miniservers
      (`statistic` V1 und `statisticV2`) auf der Detailseite, als Split-Hälfte
      (`chart:<uuid>`) und als Mini-Verlauf in der Kachel mit drei Stilen
      (Trend, Tagesmuster, Tagesspanne). Beschreibung in `ARCHITEKTUR.md` §3.9.
- [x] **Wetterdaten vom Loxone-Wetterserver bevorzugen**: Hat die Anlage den
      Loxone-Wetterdienst, schickt der Miniserver das Wetter über den WebSocket
      als eigene Binärtabelle (Kennung 7). `loxone_ws.py` zerlegt sie,
      `loxone_weather.py` rechnet sie in dieselbe Form wie
      `front_info.fetch_weather()` um; Open-Meteo bleibt Rückfall und wird gar
      nicht mehr abgefragt, solange der Miniserver liefert. Wetterlage-Texte
      (`weatherTypeTexts`) und Einheiten (`format`) kommen aus der Struktur des
      Miniservers — im Code steht keine Tabelle mit Loxone-Wettercodes, weil die
      Nummern je nach Quelle unterschiedlich dokumentiert sind. Was der Dienst
      nicht führt, bleibt leer (Regenwahrscheinlichkeit, UV-Index); lässt sich
      ein Wert nicht sicher beschriften, fällt er weg statt falsch angezeigt zu
      werden. Diagnose unter *Settings → Diagnose* (`weatherServer`). **M**
- [x] **Nachtmodus über ein frei wählbares Control auslösen**: Statt am
      Sonnenstand soll der Nachtmodus an einem Baustein hängen können — Auswahl
      über die Controls der Anlage, gewählter Baustein `active` = Nacht.
      Rangfolge dann: gewähltes Control → Sonnenzeiten (Miniserver →
      Wetterdienst) → festes Fenster. Das deckt **Betriebsmodi mit ab**, sobald
      sie in der Visu liegen: Der Modus selbst ist nicht abgreifbar, wohl aber
      ein Status-Baustein, auf den er in Loxone Config gelegt wird — wie
      „Fernsehen abend" (`InfoOnlyDigital`) und „Frostsicherung" (`Switch`) in
      der untersuchten Anlage. Begründung und Messwerte siehe „Grundregel" in
      [`ARCHITEKTUR.md`](ARCHITEKTUR.md), Abschnitt 6. **M**

## 10. Sicherheit (zurückgestuft)

Nur relevant, wenn der Server jemals außerhalb des Heimnetzes erreichbar wird
oder Gäste im WLAN nicht vertrauenswürdig sind.

- [ ] **Optionales Zugriffs-Token** für `/config` und alle
      schreibenden `/api/*`-Routen; `/`, `/ws` und die Bild-Proxys bleiben frei.
      Abschaltbar per Umgebungsvariable. (S1) **M**
- [ ] **Cover-Proxy auf bekannte Hosts** (Miniserver, Audioserver)
      einschränken. (S2) **S**
- [ ] **Agent-HTTP absichern**: gemeinsames Token zwischen Server und Agent,
      alternativ nur Anfragen von der Server-IP annehmen. (S4) **S**
- [ ] **Gleichzeitige MJPEG-Streams begrenzen**. (S6) **S**
- [ ] **HTTPS** über einen Reverse-Proxy auf Unraid; dann muss der
      Installer-Befehl in `config.html` das Schema übernehmen. (S3) **M**
- [ ] LoxBerry-`sudoers` enger fassen. Betrifft nur den LoxBerry-Betrieb. (S5) **S**
