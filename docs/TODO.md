# LoxPanel – ToDo

Priorisierte Liste der Änderungen für den eigenen Betrieb auf Unraid. Nummern in
Klammern verweisen auf die Befunde in [`ARCHITEKTUR.md`](ARCHITEKTUR.md)
(F = Fehler, S = Sicherheit, P = Performance, W = Wartbarkeit). Aufwand:
**S** = unter einer Stunde, **M** = ein halber Tag, **L** = mehrere Tage.

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

Upstream 0.3.2 (Lenardo1) ist eingepflegt: Audioserver-Favoriten direkt am
Audioserver (Port 7091), Split-Player je Panel, vereinte Web-UI (`/settings`
→ Rubrik Settings in `/config`), flackerfreie Live-Updates, Broadcaster
überlebt Render-Fehler. Neue Upstream-Releases per
`git fetch upstream && git merge upstream/main` holen, Konflikte lösen, als
Merge-Commit nach `main`.

- [ ] **Upstream 0.3.2 an der Anlage prüfen:** Audioserver-Favoriten in der
      AudioZone, Split-Player (Panel Configuration → „Fester Player"),
      Live-Updates ohne Flackern, Settings-Rubrik mit Geräteliste und
      Display-Treibern. **S**
- [ ] **Allgemein nützliche Fork-Teile Upstream anbieten:** die sieben
      Bausteintypen, `/api/types`, Unraid-Template. Was Upstream übernimmt,
      muss der Fork nicht mehr mitschleppen. **M**

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
      `ms["user"]`, verständliche Fehlermeldung in `/config` (Settings). (F7) **S**

## 2. Server-Stabilität

- [ ] **Broadcaster absichern**: Upstream 0.3.2 fängt Render-Fehler je
      Verbindung im `broadcaster()` und bei `nav` ab. Offen: `send_json` in
      `_push()`, `switch_mode()` und `api_testtone` gegen andere Ausnahmen als
      `ConnectionError` absichern. (F3) **S**
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
      erwarteter Niederschlag als Anzeige. Offen: Start/Stop und Zone starten,
      Befehlsnamen auf der Anlage prüfen. **M**
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
- [x] `AudioZone` (Musikserver Gen 1, MS4H, Sonn): Upstream 0.3.2 holt
      Favoriten und Steuerung direkt vom Audioserver (Port 7091); mit
      `audio.directV2` auch für `AudioZoneV2`-Nachbauten. **M**
- [ ] `AlarmClock` (Wecker): nur Anzeige und Weckton, kein Bearbeiten der
      Weckzeiten. **M**
- [ ] `Intercom`: Kamera und Klingel-Popup, kein Gegensprechen (SIP). **L**
- [ ] `TextInput`: nur Anzeige, keine Eingabe. **S**
- [ ] `UpDownAnalog`: nur Anzeige, keine Auf/Ab-Befehle. **S**
- [ ] `Ventilation` (Lüftung): nur Stufe anzeigen, kein Umschalten. **S**

## 9. Weitere Funktionen

- [x] **Front: Kalender + Wetter auf dem Screensaver.** Neu `bin/front_info.py`
      (eigenständig, keine Fremdabhängigkeit): iCal-Abo laden und parsen
      (`icalendar` + `python-dateutil`, löst Serientermine auf) und Wetter von
      Open-Meteo (kein API-Key, nur Koordinaten). Der Server holt beides alle
      15 Min (`front_task`) und pusht `{t:"front"}`; die Uhr-Startseite zeigt
      Wetter oben und die nächsten Termine unten. Pflegbar unter *Settings →
      Kalender & Wetter*, gespeichert im `calendar`-Block von `loxpanel.cfg`. **M**
- [ ] **Kalender/Wetter als eigener Tab**: volle Terminliste zum Durchscrollen
      und größere Wetteransicht, nicht nur die Front. **M**
- [ ] **Heizung: Modus-Umschaltung** im `IRoomControllerV2` über die
      Betriebsart, nicht nur Override. **M**
- [ ] **Panel-Texte mehrsprachig**: die rund 90 hart deutschen Strings im Server
      in einen Katalog ziehen, `lang` aus dem Profil auswerten. Nur nötig,
      wenn ein Panel nicht deutsch sein soll. **L**

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
