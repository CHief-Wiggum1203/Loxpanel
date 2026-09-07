# LoxPanel – ToDo

Priorisierte Liste der Änderungen für den eigenen Betrieb auf Unraid. Nummern in
Klammern verweisen auf die Befunde in [`ARCHITEKTUR.md`](ARCHITEKTUR.md)
(F = Fehler, S = Sicherheit, P = Performance, W = Wartbarkeit). Aufwand:
**S** = unter einer Stunde, **M** = ein halber Tag, **L** = mehrere Tage.

Sicherheit ist bewusst ganz unten eingeordnet: Der Server läuft nur im Heimnetz
und ist nicht von außen erreichbar. Sollte sich das ändern, rückt Block 8 nach
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
- [ ] **Schritt 2, Geräteverwaltung an der Gerätekennung.** Browser-Geräte
      erscheinen unter *Einstellungen → Panels* mit Name, Online-Status,
      Profil und Typ (Agent / Kiosk-App / Browser), unabhängig von der
      Agent-IP. Gerätename in der Visu setzbar, falls die URL keinen trägt. **M**
- [ ] **Schritt 3, serverseitige Display-Treiber.** Je Gerät ein Treiber:
      Agent (bestehend), Fully Kiosk über dessen REST-API (IP, Port 2323,
      Passwort), WallPanel über dessen HTTP-API. Damit schaltet der Server das
      Display auch, wenn die Seite nicht läuft, und WallPanel wird voll
      unterstützt. **M**
- [ ] **Schritt 4, Einstellungen und Doku.** Start-URL mit `?panel=&device=`
      in den Einstellungen erzeugen und kopieren, Anleitung für Fully Kiosk
      und WallPanel, Installationsskript nur noch für Linux ausweisen. **S**

## 1. Konfiguration vor Datenverlust schützen

- [ ] **Atomares Schreiben** von `loxpanel.cfg`, `panels.json`, `theme.json`:
      in `<datei>.tmp` schreiben, `fsync`, `os.replace`. Stellen: `_write_cfg`,
      `_persist_panels_file`, `_write_theme` in `bin/webvisu.py`. (F5) **S**
- [ ] **Fehlerbehandlung beim Schreiben**: `OSError` in `_write_cfg` und den
      beiden Settings-Handlern fangen und als `{"ok": false, "error": ...}`
      zurückgeben statt 500. (F6) **S**
- [ ] **Sicherung vor dem Überschreiben**: vor jedem Schreiben von `panels.json`
      eine Kopie `panels.json.bak` behalten, eine Generation reicht. **S**
- [ ] **Unvollständige `loxpanel.cfg` abfangen**: `reconnect()` mit `.get()` statt
      `ms["user"]`, verständliche Fehlermeldung in `/settings`. (F7) **S**

## 2. Server-Stabilität

- [ ] **Broadcaster absichern**: `send_json` in `broadcaster()`, `_push()`,
      `switch_mode()` und `api_testtone` mit `except Exception` plus Logging
      umschließen. Ein einzelner Sendefehler darf den Task nicht beenden. (F3) **S**
- [ ] **`op_modes` in `App.__init__` initialisieren**, `getattr`-Workaround in
      `_alarm_repeat` entfernen. (F2) **S**
- [ ] **Timeout für Icon- und Cover-Abrufe** in `fetch_icon`/`fetch_cover`,
      `asyncio.TimeoutError` fangen. (F8) **S**
- [ ] **`icon_cache` begrenzen**, z. B. auf 500 Einträge mit einfacher
      Verdrängung. (F4) **S**
- [ ] **HTTP-Handler für die vier HTML-Dateien** mit `try` um `read_text`,
      damit eine fehlende Datei einen 404 statt eines Stacktrace liefert. **S**
- [ ] **`JSON.parse` im WebSocket-Handler** der Visu in `try/catch`. (F9) **S**
- [ ] **Reconnect mit Backoff** statt fester 10 s, z. B. 5, 10, 20, 40, 60 s. **S**

## 3. Sichtbare Fehler in der Visu

- [ ] **Escaping in `panel.html`**: `esc()` um `"` und `'` ergänzen. Betrifft
      Attribute mit Miniserver-Namen und Freitext-Schriftarten. (F10) **S**
- [ ] **Panel-`states`-Farben validieren** mit `_color_ok` in
      `_sanitize_panels`, oder das Feld entfernen, da der Konfigurator es nicht
      anbietet. (F11) **S**
- [ ] **Icon-Routen `/gicon` und `/uicon`**: entweder registrieren (Google
      Material Icons per Proxy, Upload-Verzeichnis für eigene Icons) oder die
      Erzeugung in `_apply_tile_style` und die Annahme in `_clean_icon`
      entfernen, bis das Feature gebaut wird. (F1) **S** (entfernen) / **M** (bauen)
- [ ] **`updatePanel()` robust machen**: Blöcke über einen stabilen Schlüssel
      statt Index und erstem Treffer zuordnen, z. B. Server vergibt `id` je Block.
      (F12) **M**
- [ ] **Stiller Verlust beim Speichern**: `_sanitize_panels` soll melden, welche
      Felder verworfen wurden, und der Konfigurator zeigt es an. (W7) **M**

## 4. Performance

- [ ] **Nur senden, was sich geändert hat**: pro Verbindung das zuletzt
      gesendete `view`-JSON merken und bei Gleichheit nicht senden. Größter
      Hebel bei kleinstem Eingriff. (P1) **S**
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
      ZIP, `/settings` bekommt einen Download-Button. Ersetzt die
      Widget-Funktion des LoxBerry-Plugins auch auf Unraid. **M**

## 6. Wartbarkeit

- [ ] **Agent nur einmal pflegen**: Server liefert `agent/loxpanel-agent.py`
      unter `/loxpanel-agent.py` aus, `install-agent.sh` holt die Datei per
      `curl` statt sie als Heredoc zu enthalten. (W2) **S**
- [ ] **Duplikate zusammenführen**: `esc()` dreifach, `ICONS`/`BICONS`,
      Admin-CSS in `config.html` und `settings.html`, Overlay-Berechnung,
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

## 7. Tests und CI

- [ ] **pytest für reine Funktionen**: `_fmt_num`, `_color_parse`,
      `_alarm_next_text`, `_alarm_entries`, `_audio_favs`, `_tracker_lines`,
      `_resolve_ids`, `_sanitize_panels`, `LoxoneWS._parse_values`,
      `LoxoneWS._parse_texts`. Dafür müssen die Funktionen ohne `App`-Instanz
      aufrufbar sein oder eine `App` ohne Verbindung konstruierbar bleiben. (W8) **M**
- [ ] **Lint im Workflow** (`ruff`), zunächst nur als Warnung. **S**
- [ ] **Rauchtest im Workflow**: Server ohne Miniserver starten, `/api/settings`
      und `/config` abrufen, vor dem Image-Build. **S**
- [ ] **Workflow auch für Pull Requests**: `py_compile`, Lint und Rauchtest auf
      jedem PR, Image-Build weiter nur auf `main`. **S**

## 8. Funktionen

Aus der Roadmap des Original-Autors und den README-Lücken. Reihenfolge nach
eigenem Bedarf festlegen.

- [ ] **Fehlende Bausteine**: 16 laut README geplant, darunter `MoodSwitch`,
      `Remote`, `ClimateController`, `Heatmixer`, `Sauna`, `EnergyManager2`,
      `Wallbox`, `PoolController`, `NfcCodeTouch`. Je Typ ein Zweig in beiden
      Ketten, siehe Rezept (a) in `ARCHITEKTUR.md`. **S** je Typ
- [ ] **AudioZone**: Musikauswahl statt Platzhalter, `AudioZoneV2` mit
      denselben Favoriten wie `AudioZone`. **M**
- [ ] **AlarmClock bearbeiten** (derzeit nur Anzeige und Weckton). **M**
- [ ] **Heizung: Modus-Umschaltung** im `IRoomControllerV2` über die
      Betriebsart, nicht nur Override. **M**
- [ ] **Intercom Gegensprechen** (SIP-Client im Browser oder auf dem Panel). **L**
- [ ] **Panel-Texte mehrsprachig**: die rund 90 hart deutschen Strings im Server
      in einen Katalog ziehen, `lang` aus dem Profil auswerten. Nur nötig,
      wenn ein Panel nicht deutsch sein soll. **L**

## 9. Sicherheit (zurückgestuft)

Nur relevant, wenn der Server jemals außerhalb des Heimnetzes erreichbar wird
oder Gäste im WLAN nicht vertrauenswürdig sind.

- [ ] **Optionales Zugriffs-Token** für `/config`, `/settings` und alle
      schreibenden `/api/*`-Routen; `/`, `/ws` und die Bild-Proxys bleiben frei.
      Abschaltbar per Umgebungsvariable. (S1) **M**
- [ ] **Cover-Proxy auf bekannte Hosts** (Miniserver, Audioserver)
      einschränken. (S2) **S**
- [ ] **Agent-HTTP absichern**: gemeinsames Token zwischen Server und Agent,
      alternativ nur Anfragen von der Server-IP annehmen. (S4) **S**
- [ ] **Gleichzeitige MJPEG-Streams begrenzen**. (S6) **S**
- [ ] **HTTPS** über einen Reverse-Proxy auf Unraid; dann muss der
      Installer-Befehl in `settings.html` das Schema übernehmen. (S3) **M**
- [ ] LoxBerry-`sudoers` enger fassen. Betrifft nur den LoxBerry-Betrieb. (S5) **S**
