# LoxPanel – Architektur und Codeanalyse

Stand: Commit `6898440` (2026-09-06). Zeilenangaben beziehen sich auf diesen Stand
und verschieben sich bei Änderungen. Diese Analyse dient als Einstieg für eigene
Weiterentwicklungen im Fork `CHief-Wiggum1203/Loxpanel`.

## Inhalt

1. [Überblick](#1-überblick)
2. [Verzeichnisstruktur und Rollen](#2-verzeichnisstruktur-und-rollen)
3. [Laufzeit-Architektur des Servers](#3-laufzeit-architektur-des-servers)
4. [HTTP- und WebSocket-Schnittstelle](#4-http--und-websocket-schnittstelle)
5. [Konfigurationsdateien](#5-konfigurationsdateien)
6. [Loxone-Bausteine](#6-loxone-bausteine)
7. [Frontend](#7-frontend)
8. [Panel-Agent](#8-panel-agent)
9. [LoxBerry-Plugin, Unraid, Build und Release](#9-loxberry-plugin-unraid-build-und-release)
10. [Erweiterungs-Rezepte](#10-erweiterungs-rezepte)
11. [Bekannte Schwachstellen](#11-bekannte-schwachstellen)
12. [Aufräumkandidaten](#12-aufräumkandidaten)
13. [Empfohlene nächste Schritte](#13-empfohlene-nächste-schritte)

---

## 1. Überblick

LoxPanel ist eine Web-Touch-Visualisierung für den Loxone Miniserver. Der Server
verbindet sich per WebSocket mit dem Miniserver, lädt die Struktur (`LoxAPP3.json`),
empfängt Live-Zustände und rendert daraus Ansichten, die ein Browser (Wandpanel,
Tablet, Handy) nur noch anzeigt.

**Kernidee:** Die gesamte Logik liegt im Server. Der Browser ist ein dummer
Renderer, der fertige Ansichten als JSON über einen WebSocket bekommt und nur zwei
Nachrichtentypen zurückschickt (Navigation, Befehl). Es gibt keinen Build-Schritt,
kein Frontend-Framework und keine Datenbank.

**Technik:**

| Bereich | Technik |
|---|---|
| Server | Python 3.12, `aiohttp`, Bibliothek `loxone-api` (Token-Auth, Struktur), eigener Binär-WebSocket-Parser |
| Frontend | drei Single-File-HTML-Seiten mit Vanilla JS, eine gemeinsame `i18n.js` |
| Panel-Agent | Python-Standardbibliothek, läuft auf dem Wandpanel |
| Auslieferung | Docker-Image (amd64/arm64/armv7) auf GHCR, LoxBerry-Plugin als Wrapper, Unraid-Template |
| Persistenz | drei JSON-Dateien im Ordner `config/` (im Container `/app/config`) |

**Projektstand:** Das Projekt ist jung. Der erste Commit stammt vom 28.08.2026,
alle Commits stammen von einem Autor, Version 0.3.2 (Upstream-Stand vom
07.09.2026, in den Fork gemergt). Der Code ist funktional weit,
es gibt Tests gegen einen Miniserver-Nachbau (`tests/`, Abschnitt 9.3), aber keine Authentifizierung und einige
Altlasten aus einer früheren Konzeptphase (openHASP/MQTT).

**Umfang:** rund 9.900 Zeilen, davon `bin/webvisu.py` allein 3.080 Zeilen.

---

## 2. Verzeichnisstruktur und Rollen

### 2.1 Aktiver Code

| Pfad | Rolle |
|---|---|
| `bin/webvisu.py` | Der gesamte Server: aiohttp-App, Miniserver-Verbindung, Rendering aller Ansichten, alle Routen, WebSocket zum Browser. Monolith. |
| `bin/loxone_ws.py` | Loxone-WebSocket-Client: Token-Handshake, Binärparsing der Value-, Text- und Wetter-Tabellen. Nicht behandelte Kennungen werden einmal pro Verbindung protokolliert |
| `bin/adapters.py` | Nur `LightControllerV2Adapter` und `JalousieAdapter` werden genutzt. Die Adapter-Registry darin ist aufgegeben. |
| `bin/audioserver.py` | Backend für Loxone-Audioserver Gen1 / MS4H über WebSocket Port 7091 |
| `bin/audioserver_events.py` | Event-Client für Audioserver Gen2 (WebSocket Port 7091): Cover, Titel, Favoriten; Adressen aus der Struktur |
| `bin/front_info.py` | Front (Screensaver): iCal-Abo laden und parsen (`icalendar` + `python-dateutil`, löst Serientermine auf) und Wetter von Open-Meteo (kein API-Key, nur Koordinaten). Eigenständig, keine Fremdabhängigkeit. `webvisu.py` ruft `load_front()` im `front_task` (alle 15 Min) und pusht das Ergebnis als `{t:"front"}` an die Panels |
| `bin/loxone_weather.py` | Wetter vom Loxone-Wetterserver: rechnet die Wetter-Tabelle des Miniservers in genau die Form um, die `front_info.fetch_weather()` liefert, und hat damit Vorrang vor Open-Meteo. Wetterlage-Texte und Einheiten kommen aus der Struktur (`weatherServer`), nicht aus einer Tabelle im Code. Gibt `None` zurück, wenn sich die Daten nicht sicher beschriften lassen — dann bleibt Open-Meteo |
| `bin/theme_colors.py` | Leitet aus EINER Grundfarbe den ganzen Panel-Farbsatz ab (Flächen, Schrift, Icon- und Zustandsfarben) und rechnet jeden Wert gegen die Fläche nach, auf der er steht: Hauptschrift AAA, Rest AA, Grafik 3:1, dazu Deuteranopie und Protanopie. Liefert `None`, wenn eine Farbe kein tragfähiges Theme hergibt. Nur Standardbibliothek. Aufgerufen aus `_theme_vars()` |
| `webfrontend/html/panel.html` | Die Visu (Kacheln, Detailseiten, Screensaver mit Wetter + Terminen, PIN, Weckton) |
| `webfrontend/html/config.html` | Konfigurator mit zwei Rubriken: „Panel Configuration" (Panels, Tabs, Räume, Kacheln, Design, Split-Player) und „Settings" (Miniserver, Intercom, Geräte, Betriebsmodus, Display-Steuerung, Audio, Kalender & Wetter, Neues Panel) |
| `webfrontend/html/settings.html` | Nur noch Weiterleitung nach `/config`, ohne Anker: der Konfigurator wertet keinen aus |
| `webfrontend/html/i18n.js` | Übersetzungskatalog de/en für Konfigurator und Einstellungen |
| `agent/loxpanel-agent.py` | Panel-Agent auf dem Wandpanel |
| `deploy/install-agent.sh` | Installer für den Agenten. Enthält den Agent-Quelltext als eingebettete Kopie. |
| `config/*.example` | Vorlagen für `loxpanel.cfg`, `panels.json`, `theme.json` |
| `loxberry-plugin/` | LoxBerry-Plugin (Docker-Starter, Widget, Backup) |
| `unraid/loxpanel.xml` | Unraid-Docker-Template |
| `Dockerfile`, `docker-compose.yml`, `.github/workflows/` | Build und Release |

### 2.2 Randsysteme und Hilfsmittel

| Pfad | Rolle |
|---|---|
| `bin/*_probe.py`, `bin/*_check.py`, `bin/*_test.py` (20 Dateien) | Manuelle Diagnose-Skripte gegen einen echten Miniserver oder den laufenden Server, keine automatisierten Tests. Viele enthalten fest kodierte UUIDs und IPs der Entwickler-Anlage. |
| `tests/` | Automatisierte Tests (pytest): reine Funktionen, Server gegen einen Miniserver-Nachbau (`tests/lox.py`), Rauchtest als eigener Prozess, Visu und Konfigurator in Chromium (`tests/browser/`, Marker `browser`) |
| `deploy/kiosk.sh`, `deploy/loxpanel-webvisu.service`, `deploy/DEPLOY.md` | Ältere Bare-Metal-Variante. Funktional vom Agenten abgelöst. |
| `agent/loxpanel-agent.service` | systemd-Unit, die der Installer nie installiert |

### 2.3 Altlasten (nicht mehr genutzt)

Aus einer früheren Konzeptphase, in der ein ESP32-Display per openHASP/MQTT
angesteuert werden sollte und das Plugin direkt auf dem LoxBerry lief:

| Pfad | Belege |
|---|---|
| `daemon/loxpanel-daemon.py` | MQTT-Gerüst, `main()` schläft nur. Nur von `postinstall.sh` referenziert. |
| `postinstall.sh`, `apt`, `plugin.cfg` (Repo-Root) | Phase-1-Plugin ohne Docker. Root-`plugin.cfg` steht auf 0.1.0 mit anderer Autor-E-Mail als das echte Plugin. |
| `webfrontend/htmlauth/index.php` | Designer-Frontend Phase 1, verweist auf nicht existierende `importer.php`. Reist über `COPY webfrontend/` ins Docker-Image. |
| `bin/loxone_client.py`, `bin/loxone_live.py`, `bin/importer.py` | Polling-Vorläufer. `loxone_live.py` wird von niemandem importiert. |
| `config/visu.schema.json`, `config/visu.example.json` | Deklaratives Vorgängerformat mit openHASP-Ziel. Wird von keiner Codezeile gelesen. |

---

## 3. Laufzeit-Architektur des Servers

### 3.1 Datenfluss

```
Loxone Miniserver
   │  WebSocket ws(s)://host/ws/rfc6455, Token-Auth, Binär-States
   ▼
LoxoneWS.stream()  ──► App._on_value(uuid, wert)  ──► App.states[uuid] = wert
                                                     _dirty = True
                                                     Flanken: Klingel, Wecker
   ┌───────────────────────────────────────────────────────────┘
   ▼
App.broadcaster()  alle 0,3 s:
   für jede offene Browser-Verbindung:
      render(route, profil)  ──► {"t":"view", ...}  ──► Browser
   ▲
   │  {"t":"nav"} / {"t":"cmd"}
Browser (panel.html)
```

Befehle vom Browser gehen über `App.command()` entweder an den Miniserver
(`jdev/sps/io/<uuid>/<cmd>`) oder direkt an den Audioserver auf Port 7091
(`audio/<playerid>/<cmd>`). Welcher Weg, hängt am Kopplungsstatus des
Audioservers: Ein mit dem Miniserver **gekoppelter** Loxone-Audioserver lehnt
Befehle ohne Anmeldung ab („command not allowed when paired", prüfbar mit
`bin/audioserver_probe.py`) und schließt die Verbindung; seine Transportbefehle
(play/pause, next/prev, volume) laufen deshalb über den Miniserver. Nur ein
nachweislich **nicht** gekoppelter Audioserver (Nachbau Sonn/MS4H bzw.
Musikserver Gen 1, `paired=false`) bekommt sie direkt auf Port 7091 (die
`playerid` dafür stammt aus `details.playerid`). Den `paired`-Status ermittelt
der Ereignis-Client je Host automatisch (`audioserver_events.py`, HTTP
`audio/cfg/all`); solange er unbekannt ist, wird sicher über den Miniserver
geleitet. `roomfav/get` bleibt immer am Miniserver (füllt den `sourceList`-State
für die Anzeige). Ausnahme roomfav/play: bei einem gekoppelten Loxone-Audioserver
läuft `roomfav/play/<slot>` über die angemeldete Ereignis-Verbindung
(`play_roomfav`), weil der unangemeldete Direktkanal solche Befehle ablehnt;
Nachbauten (`authed=false`) nutzen den Direktkanal. Titel, Sender und Cover für `AudioZoneV2` kommen über den
Ereigniskanal (`audioserver_events.py`): Der WebSocket muss das Unterprotokoll
`remotecontrol` anfordern, dann schickt auch der gekoppelte Audioserver die
Ereignisse aller Zonen ohne Anmeldung. Befehle auf diesem Kanal setzen bei einem
gekoppelten Audioserver eine Anmeldung voraus. LoxPanel meldet sich wie die
Loxone-App an (`bin/audioserver_auth.py`): Session-Token aus dem Banner,
`audio/cfg/getkey` → RSA-Schlüssel, das Miniserver-JWT AES-256-CBC-verschlüsselt
und `key:iv:sessionToken` per RSA an `secure/authenticate`. Danach laufen
`getroomfavs` und `roomfav/play/<id>` über dieselbe Verbindung.

Tree-Turbo-Geräte (Stereo Extension, Install Speaker/Sub/Satellite Master,
künftig das Wall Display 10") hängen laut Loxone per IP-Powerline an einer
Tree-Turbo-Schnittstelle des Audioservers bzw. Miniserver Compact und holen sich
per DHCP eine IP im normalen Heimnetz — sie sind also im LAN direkt erreichbar.
`bin/treeturbo_probe.py` sucht sie dort: liest die bekannten Adressen
(Miniserver + Audioserver) aus Konfiguration, laufendem Panel und Struktur,
leitet die zugehörigen `/24`-Netze ab und prüft jede Adresse per TCP auf
80/443/8080 und 7090–7092. Ein Gerät zählt als vorhanden, sobald es antwortet –
auch mit Ablehnung, so tauchen auch Geräte ohne offenen Loxone-Port auf. Die
Liste zeigt je Gerät den Namen aus dem Router-DNS und markiert Miniserver und
Audioserver; Geräte mit offenen Ports werden genauer abgefragt (HTTP-Banner,
Audioserver-Banner auf 7091 über das Unterprotokoll `remotecontrol`, nur
zuhören). Aufruf `docker exec -i LoxPanel python3 -u bin/treeturbo_probe.py`,
solange die Datei nicht im Image steckt per `curl … | docker exec -i LoxPanel
python3 -u -` (`-u` zeigt die Ausgabe sofort statt erst am Ende); `host <ip>`
prüft eine Adresse, `net <cidr>` ein bestimmtes Netz, `full` (kombinierbar) die
Ports 1–10000 je abgefragtem Gerät. Die Sonde liest nur. So lässt sich feststellen, welche Tree-Turbo-Geräte im Netz auftauchen und
welche Dienste sie ohne Anmeldung anbieten — die Grundlage, um ein eigenes Panel
als Ersatz für das Wall Display anzubinden, statt es zu kaufen.

### 3.2 Start

`main()` (`webvisu.py:3036`) liest `--port` bzw. `LOXPANEL_PORT` (Default 8099),
baut `App(_config(), _audio_config())`, registriert alle Routen und startet beim
`on_startup` drei Dauer-Tasks: `stream_task()` (Miniserver-Verbindung),
`broadcaster()` (Verteilung) und `audio_events_task()` (Audioserver-Gen2-Events). Der HTTP-Server ist sofort erreichbar, auch ohne
Miniserver-Zugang. So bleibt `/config` immer bedienbar.

### 3.3 Zentrale Klasse `App` (`webvisu.py:328`)

Wichtige Felder:

| Feld | Inhalt |
|---|---|
| `states` | `state-UUID → Wert`, der flache Live-Zustand der gesamten Anlage |
| `controls`, `rooms`, `cats` | rohe Teilbäume aus `LoxAPP3.json` |
| `conn_route`, `conn_prof`, `conn_dev` | je Browser-WebSocket: aktuelle Route, aufgelöstes Panel-Profil, Gerätekennung |
| `conn_info` | je Browser-WebSocket: Gerätekennung, Kiosk-App (`fully`), IP, Verbindungszeit; Basis von `device_list()` |
| `panels`, `devices` | aus `panels.json` |
| `agents` | `ip → Agent-Datensatz` (Announce) |
| `bell_map`, `alarm_map` | State-UUID → Control für Klingel- und Wecker-Flanken |
| `icon_cache` | Cache für Loxone-Icons, höchstens `ICON_CACHE_MAX` (500) Einträge, der am längsten unbenutzte fliegt zuerst |
| `last_mode` | zuletzt gesetzter Betriebsmodus |

`op_modes` (Betriebsarten) ist ab `__init__` ein leeres Dict und wird in
`_apply_structure()` gefüllt; `/api/types` funktioniert damit auch ohne Miniserver.

### 3.4 Verbindung und Reconnect

- `App.start()` (`:414`): Client bauen, `getkey2`, `authenticate` (JWT), Struktur
  laden, Icon-Session anlegen, WebSocket öffnen.
- `stream_task()` (`:2409`): Endlosschleife. Bei Fehler wird das Token erneuert,
  scheitert das, wird die Verbindung hart zurückgesetzt. Danach wachsende Pause
  (`MS_RETRY`: 5, 10, 20, 40, 60 s). Von vorn beginnt sie erst, wenn eine
  Verbindung mindestens 60 s hielt — ein Miniserver, der sofort wieder trennt,
  bekommt so nicht alle paar Sekunden eine neue Anmeldung.
- **Token-Erneuerung für HTTP-Anfragen:** Die WebSocket-Verbindung braucht das
  Token nur beim Anmelden, die HTTP-Anfragen (Befehle `sps/io`, gesicherte
  Befehle, Icons, Verläufe) tragen es bei jedem Aufruf als Bearer. Läuft es ab,
  während der WebSocket stabil bleibt, kamen früher weiter Werte, aber jeder
  Befehl scheiterte still. Das passt zur Beobachtung an der eigenen Anlage,
  dass sich das Panel nach ein bis zwei Tagen nicht mehr bedienen ließ. Deshalb laufen alle HTTP-Anfragen an den Miniserver über
  `_ms_http()`: Bei HTTP 401 meldet `_renew_token()` sich einmal neu an und die
  Anfrage wird wiederholt. Gleichzeitige Anfragen lösen nur eine Anmeldung aus
  (Lock und Zähler `_auth_gen`), und innerhalb von `TOKEN_RENEW_MIN` (60 s) nach
  der letzten Anmeldung wird nicht erneut angemeldet, weil ein 401 dann nicht am
  Token liegt (z. B. fehlende Rechte). Der zweite Aufruf eines gesicherten
  Befehls (`sps/ios`) erneuert nie: Ein Fehler heißt dort falsches
  Visu-Passwort. Befehle haben `MS_CMD_TIMEOUT` (10 s), weil sie den
  Nachrichten-Loop ihres Panels blockieren. Scheitert ein Befehl trotzdem,
  bekommt das Panel einen gelben Hinweis (`notify`) statt nichts.
- `reconnect()` (`:438`): zweiter Weg über `/api/settings/miniserver`. Baut einen
  neuen Client und übernimmt ihn nur bei Erfolg, die alte Verbindung überlebt
  einen Fehlversuch.
- Bei Port 80 (Gen1) wird die Basis-URL von Hand auf `http://` gesetzt, weil
  `loxone-api` HTTPS annimmt.

### 3.5 Verteilung an die Browser

`broadcaster()` (`:2443`) pollt alle 0,3 s das `_dirty`-Flag. Ist es gesetzt,
wird für jede offene Verbindung die aktuell betrachtete Route komplett neu
gerendert und als vollständige `view`-Nachricht geschickt. Es gibt kein
Delta-Protokoll und keine Drosselung. Bei vielen laufenden Werten (Zähler,
Temperaturen) bedeutet das bis zu drei Voll-Renderings pro Sekunde pro Panel.
Das ist die wahrscheinlichste Skalierungsgrenze.

### 3.6 Nachrichtenprotokoll

Server → Browser (`panel.html:700`):

| `t` | Inhalt | Zweck |
|---|---|---|
| `theme` | `vars`, `tabs`, `tabMeta`, `title`, `lang`, `fill`, `split`, `panes`, `svPane`, `scale` | einmalig nach Verbindungsaufbau: CSS-Variablen, Tab-Leiste, Sprache, Split-Panes je Tab, die rechte Spalte der Uhr-Seite und die wirksame Skalierung (Gerät vor Profil vor global, `effective_scale()`) |
| `view` | `title`, `tab`, `route`, `items[]` **oder** `blocks[]`, `layout`, `anchor`, `secured`, `front` | eine komplette Ansicht. `front` (`calendar`/`weather`) bei den Tabs `kalender`/`wetter`: `items` ist leer, das Panel zeichnet die Seite aus den zuletzt empfangenen `front`-Daten (`renderFrontTab()`) und neu, sobald neue kommen |
| `ring` | `id` | Klingel: Panel springt auf die Intercom-Seite |
| `alarm` | `id`, `on` | Weckton starten/stoppen |
| `testtone` | | Testton |
| `switch` | `panel` | Betriebsmodus: Seite mit neuem Profil neu laden |
| `reload` | | `location.reload()` |
| `goto` | `route` | auf eine Seite springen |
| `notify` | `text`, `level`, `secs` | Einblendung |
| `cmdresult` | `ok` | Ergebnis eines PIN-gesicherten Befehls |
| `display` | `on` | Display über die Kiosk-App aus- oder einschalten |
| `front` | `weather` (`temp`, `cond`, `icon`, `hi`, `lo`, `wind` + `wind_unit`, `forecast[]`), `events[]` (`day`, `time`, `title`), `calName` | Kalender + Wetter für den Screensaver; beim Verbinden und alle 15 Min bzw. nach dem Speichern (`front_task`) — oder sofort, wenn der Miniserver neues Wetter schickt (§3.8) |
| `scale` | `scale` (`"off"` \| `"auto"` \| Faktor) | Skalierung live umstellen, gesendet nach `POST /api/devices` an alle verbundenen Panels — ohne Neuladen |
| `chart` | `control`, `name`, `value`, `range`, `blocks[]` (Blöcke `chart`, §3.7) | Verlaufs-Pane im Split-Layout; nach `setchart` und bei jeder Änderung, die der Broadcaster sieht (gebaut in `chart_blocks()`) |
| `svstatus` | `items[]` (dieselbe Form wie Kachel-`items`, ohne `nav`/`controls`) | Werte der frei gewählten Bausteine für die rechte Spalte der Uhr-Seite; gebaut in `status_blocks()` über `_control_item()`, also dieselbe Kette wie jede Kachel |
| (Browser → Server) `idle` | | Visu ohne Kiosk-JS meldet Leerlauf nach `dpmsOff`; Server schaltet über den Display-Treiber aus |
| `setdevice` | `name` | Gerät wurde in den Einstellungen benannt: Visu merkt sich den Namen und verbindet neu |

Browser → Server (`ws_handler`, `webvisu.py:2991`):

| `t` | Inhalt |
|---|---|
| `nav` | `route` (z. B. `{"view":"tab","tab":"raeume"}` oder `{"view":"control","id":uuid}`) |
| `cmd` | `uuid`, `cmd`, optional `pin` |
| `screen` | `vw`, `vh` (sichtbare Fläche, CSS-px), `sw`, `sh` (Bildschirm laut Gerät), `dpr` (Pixeldichte), `bw`, `bh` (ungeskalierter Kasten der Visu), `k` (wirksamer Faktor). Beim Verbinden und nach jeder Größenänderung, entprellt. Nur zur Anzeige unter Settings → Panels; geprüft in `_clean_screen()`, abgelegt in `conn_info[ws]["screen"]` |
| `setchart` | `uuid`, `range` — Baustein und Zeitraum der Verlaufs-Pane des aktiven Tabs (`uuid` leer = keine). Der Server antwortet sofort mit `chart` und hält den Stand je Verbindung (`conn_chart`) |
| `setsvstatus` | `uuids[]` — die Bausteine der Status-Spalte auf der Uhr-Seite (leer = keine). Der Server antwortet sofort mit `svstatus` und hält den Stand je Verbindung (`conn_status`) |

### 3.7 Das Block-Vokabular

Detailseiten bestehen aus `blocks[]`, jeder mit einem Schlüssel `k`. Frontend und
Server teilen dieses Vokabular, es ist aber nirgends formal spezifiziert:

`hero`, `cover`, `video`, `web`, `status`, `title`, `value`, `big`, `astat`,
`slider`, `row` (mit `cells`, Varianten `transport`, `wrap`, `hidden`), `head`,
`favs`, `alarmlist`, `chart`, `more`. Zellen innerhalb `row`: `cmd`,
`hold`+`release`, `menu`, `icon`, `big`, `on`, `label`.

`chart` (Verlaufs-Diagramm) trägt `kind` (`line`, `digital`, `counter`), `unit`,
`t0`/`t1`, `series[]` (`name`, `dec`, `pts` als `[sekunden, wert]`) und `state`
(`ok`, `loading`, `error`, `empty`); das erste Diagramm einer Seite dazu `range`
und `ranges` für die Zeitraum-Knöpfe. Gezeichnet in `paintChart()` der Visu.

Kachelseiten bestehen aus `items[]` mit `id`, `label`, `sublabel`, `room`,
`icon|iconUrl|iconImg`, `on`, `tone`, `color`, `style`, `nav` oder `cmd`,
`controls[]`, `secured`.

Ein Tippfehler im Server erzeugt stumm eine leere Seite.

---

### 3.8 Woher das Wetter kommt

Zwei Quellen, feste Rangfolge. Der **Loxone-Wetterserver** gewinnt, sobald er
brauchbare Daten liefert; **Open-Meteo** ist der Rückfall und wird dann gar nicht
mehr abgefragt (`load_front(..., skip_weather=True)`).

Weg der Miniserver-Daten:

1. Die Struktur führt den Block `weatherServer` — nur vorhanden, wenn die Anlage
   den (kostenpflichtigen) Loxone-Wetterdienst hat. Darin stehen die State-UUIDs
   (`states.actual`, `states.forecast`), die Wetterlage-Texte
   (`weatherTypeTexts`) und die Formatstrings mit den Einheiten (`format`).
   `_apply_structure()` legt ihn in `self.weather_cfg` ab.
2. Der Miniserver schickt das Wetter über denselben WebSocket wie alle States,
   aber als eigene Binärtabelle mit der **Kennung 7**: 16-Byte-UUID +
   `lastUpdate` + `nrEntries`, danach je Eintrag 68 Byte (5 × int32 + 6 × double).
   `loxone_ws.py:_parse_weather()` zerlegt sie, `App._on_weather()` legt die
   Rohdaten je UUID ab und weckt die Front sofort.
3. `loxone_weather.build()` macht daraus genau die Form, die
   `front_info.fetch_weather()` liefert — das Panel merkt vom Quellenwechsel
   nichts.

**Zeitstempel sind UTC.** Die Einträge zählen Sekunden seit dem 01.01.2009 in
UTC, nicht in der Ortszeit des Miniservers — an einer Anlage in Österreich lagen
die Stundenwerte durchgängig um den UTC-Abstand daneben. Umgerechnet wird je
Eintrag einzeln (Sommerzeit). Zusätzlich gleicht `build()` einen verbleibenden
vollen Stundenversatz selbst aus: der aktuelle Messwert **ist** „jetzt", der
Abstand zur laufenden Stunde wird gemessen und auf alle Einträge angewandt.
Damit stimmt die Zuordnung auch, wenn eine Anlage anders rechnet als hier
angenommen. Ohne das rutschen Stunden über die Tagesgrenze und „heute" bekommt
Werte von morgen früh.

**Heute zählt der aktuelle Messwert mit.** Die Vorhersage beginnt bei der
laufenden Stunde; ohne den aktuellen Wert kann das Tageshoch unter der jetzigen
Temperatur liegen. Die Loxone-App rechnet genauso.

Zwei Regeln, die das Modul trägt:

* **Keine Wettercode-Tabelle im Code.** Die Nummern des Wetterdienstes sind je
  nach Quelle unterschiedlich dokumentiert; der Miniserver selbst liefert die
  Texte mit. Das Panel-Icon wird aus diesem Text abgeleitet (deutsch und
  englisch). Passt kein Begriff, gilt die Quelle als nicht beschriftbar.
* **Lieber nichts als falsch.** Zeitstempel werden gegen die aktuelle Zeit
  geprüft, die Temperatur-Einheit gegen Fahrenheit, Wind und Luftdruck werden nur
  mit belegter Einheit angezeigt (m/s wird auf km/h gerechnet, die Einheit geht
  als `wind_unit` ans Panel). Scheitert eine dieser Prüfungen, gibt `build()`
  `None` zurück und Open-Meteo übernimmt wieder. Die Einheit steht immer im
  `format`-Block: die Loxone-App rendert dieselben States damit, Wert und
  Formatstring passen also zwangsläufig zusammen — Niederschlag führt der Dienst
  z.B. als `l/m²/h`, was 1:1 mm entspricht.

Was der Wetterdienst nicht führt, bleibt leer: **Regenwahrscheinlichkeit** und
**UV-Index** gibt es dort nicht (`solarRadiation` ist Einstrahlung in W/m²). Das
Panel blendet leere Werte von sich aus aus — das Regenband im Stundenverlauf und
die UV-Kachel fehlen dann.

Sonnenauf- und -untergang kommen unabhängig davon aus den globalen States
(`_ms_sun_hhmm()`), also aus derselben Quelle wie der Nachtmodus.

*Settings → Diagnose* zeigt unter `weatherServer`, was die Anlage meldet: die
State-UUIDs, wie viele Einträge angekommen sind, den aktuellen Rohdatensatz mit
seinen Werten, die Wetterlage-Texte und die Formatstrings.

### 3.9 Woher die Verläufe kommen

Bausteine mit Aufzeichnung tragen in der Struktur `statistic` (ältere Art) oder
`statisticV2` (Energie-Zähler, EFM). Ihre Detailseite bekommt unter dem
aktuellen Wert Verlaufs-Diagramme (Block `chart`, §3.7). Für `statistic`
liegen die Daten am Miniserver als Monatsdateien
`/stats/<uuidAction>.<JJJJMM>.xml`, jede Zeile `<S T="JJJJ-MM-TT hh:mm:ss"
V="…"/>`, bei mehreren Ausgängen weitere Wert-Attribute. So listet sie
`/stats/`, und so führt sie die Loxone-App (Befehlstabelle `STATISTIC` in
`scripts4.js` der Weboberfläche); ermittelt an der Anlage mit
`bin/statistic_probe.py`.

- **Abruf:** `_stat_load()` holt eine Monatsdatei über `_ms_http()` (Token,
  Erneuerung bei 401, §3.4), im Hintergrund (`_spawn`), sobald eine Detailseite sie
  braucht. Danach `_dirty`, der Broadcaster schickt die Seite mit Diagramm neu
  (vorher `state: loading`). 404 heißt: kein Eintrag in diesem Monat.
- **Cache:** `stat_cache` je (uuidAction, Monat). Ein Monat, der beim Abruf
  schon vorbei war, ändert sich nicht mehr; der laufende wird nach
  `STAT_REFRESH` (5 Min.) neu geholt, nach einem Fehler frühestens nach
  `STAT_RETRY`. `stat_memo` hält die fertigen Blöcke für den Rest der Minute,
  damit der Broadcaster-Takt nicht jede Monatsdatei neu durchrechnet.
- **Zeitraum:** läuft in der Route mit, `{"view":"control","id":…,
  "range":"24h"|"7d"|"30d"}`. Die Knöpfe ersetzen die oberste Seite im Stapel,
  statt eine neue aufzulegen.
- **Darstellung** nach `visuType` des Ausgangs (an der Anlage beobachtet):
  0 Linie, 1 Digitalwert als Stufen mit Ein-Dauer, 2 Zählerstand als Verbrauch
  je Stunde (24 h) bzw. je Tag ab Mitternacht (7/30 Tage). Ausgänge gleicher
  Art und Einheit teilen sich ein Diagramm. Linien werden auf 240 Punkte
  ausgedünnt (Mittelwert, bei Digitalwerten Maximum). Beim Zählerstand zählt
  ein Absturz auf weniger als die Hälfte als Reset, ein kleiner Rücksprung
  (Rundung) nicht als Verbrauch.
- **Zeit:** Die Zeitstempel sind Ortszeit des Miniservers und werden als
  Wanduhr-Sekunden (`timegm`) geführt, die Visu formatiert sie mit `getUTC*`.
  So zeigen Server und Panel dieselbe Uhrzeit, unabhängig von der Zeitzone des
  Browsers; „jetzt" kommt aus der Container-Zeit (`TZ`, wie beim Nachtmodus).

**`statisticV2`** (an der Anlage die Energie-Zähler und der EFM) kommt nicht
aus Dateien, sondern je Datenpunkt über
`jdev/sps/getStatistic/<uuidAction>/raw/<vonUnixUtc>/<bisUnixUtc>/all/<gruppe>/<ausgang>`.
So baut ihn die Loxone-App (`StatisticV2Ext.getStatisticRaw` in `AppHub.js`,
ermittelt mit `bin/statistic_probe.py v2`). Die Antwort ist binär, je Eintrag
4 Byte Zeitstempel (uint32, Unix-UTC) und 8 Byte Wert (float64),
little-endian; an der Anlage kamen Leistungswerte im 30-Minuten-, Zählerstände
im Stundenabstand. `_parse_stat2_bin()` rechnet die UTC-Zeit in dieselben
Wanduhr-Sekunden um wie bei den Monatsdateien.

- Gruppen mit `accumulated` sind Zählerstände (Balken wie oben), die übrigen
  Linien. Die Formate schreibt V2 als Maske (`0,000kW`, `0,0kWh`, `0,00€`),
  `_stat_fmt()` versteht beide Schreibweisen.
- Abgerufen wird je (Baustein, Gruppe, Ausgang, Zeitraum) das ganze Fenster
  plus eine Stunde Vorlauf für den Stand vor dem ersten Balken, neu nach
  `STAT_REFRESH`. Höchstens zwei Abrufe gleichzeitig (`stat2_sem`); die
  Loxone-App erlaubt vier (Gen 2) bzw. einen (Gen 1).
- Leere Antwort oder JSON statt Binärdaten gilt als „keine Aufzeichnung".
- Gleiche Titel in einer Gruppe (Netz: zweimal „Zählerstand" für `total` und
  `totalNeg`) bekommen den Ausgangsnamen dazu; mehrere Zählerreihen stehen
  als Balken nebeneinander.
- Die `diff`-Variante desselben Befehls (Verbrauch je Einheit) wird nicht
  genutzt: ihre zulässigen Einheiten sind nicht bekannt, und der Verbrauch
  ergibt sich ebenso aus den Zählerständen.

**Außerhalb der Detailseite** gibt es die Verläufe an zwei weiteren Stellen,
beide im Konfigurator einstellbar und beide aus demselben `_stat_blocks()`:

- **Verlaufs-Pane** (`panes`: `chart:<uuid>`): rechte Hälfte im Split-Layout
  mit Name, aktuellem Wert und den Diagrammen, wie beim Energiefluss über
  `setchart` angemeldet und vom Broadcaster aktualisiert. Die Zeitraum-Knöpfe
  melden dort nur den Zeitraum neu (`setchart`), die Kachelseite links bleibt.
- **Mini-Verlauf in der Kachel** (`tiles.<uuid>.chart` = Zeitraum,
  `tiles.<uuid>.chartStyle` = Darstellung): `_apply_tile_style()` hängt `spark`
  an die Kachel, gebaut in `_stat_spark()` aus dem ersten Linien-Diagramm des
  Bausteins (sonst dem ersten überhaupt, `_stat_primary()`), erste Reihe. Drei
  Darstellungen, im Konfigurator unter „Verlauf" wählbar:
  - **Trend** (Standard, Schlüssel fehlt): Kurve über den Zeitraum, auf 48
    Punkte ausgedünnt, Tief und Hoch markiert und beschriftet, aktueller Wert
    als Punkt. Dazu ein Kennzeichen im Kachelkopf: bei Messwerten die Änderung
    gegenüber vor 24 h (`▲ 1,2 °C in 24 h`), bei Ein/Aus die Einschaltdauer im
    Zeitraum, bei Zählern der Verbrauch (`Σ …`, als Balken je Stunde/Tag).
  - **Tagesmuster** (`pattern`): 7 Tage × 24 Stunden als Farbraster in der
    Akzentfarbe, je Zelle der zeitgewichtete Stundenmittelwert
    (`_stat_buckets()`), bei Zählern der Stundenverbrauch, bei Ein/Aus der
    Einschaltanteil. Stunden in der Zukunft bleiben leer umrandet.
  - **Tagesspanne** (`span`, nur Messwerte): je Tag ein Balken von Tief bis
    Hoch mit Strich beim Tagesmittel (`_stat_day_range()`), heute
    hervorgehoben; Kennzeichen `heute Tief–Hoch Einheit`. Für Zähler und
    Ein/Aus fällt der Server auf Trend zurück; `/api/meta` meldet dafür
    `statKind`, damit der Konfigurator die Spanne nur bei Messwerten anbietet.

  Tagesmuster und Tagesspanne zeigen immer die letzten 7 Kalendertage bis
  jetzt, der Zeitraum gilt nur für den Trend. Alle Texte (Wochentage,
  Kennzeichen) baut der Server. Die Visu zeichnet nach dem Einfügen in der
  echten Pixelgröße der Kachel (`paintSpark()` → `sparkSvg(sp, W, H)`), damit
  Schrift und Striche nicht verzerrt werden; `updateGrid()` zeichnet bei
  Änderungen an Ort und Stelle neu. Ergebnisse sind je Minute zwischengespeichert
  (`stat_memo`). Nur Bausteine mit Aufzeichnung; `/api/meta` kennzeichnet sie
  mit `stat`.

  Anpassung an die Kachelgröße (`paintSpark()`; Querformat ohne rechte Hälfte
  verdoppelt die Spalten, dann werden Kacheln schnell klein):
  - Ist die freie Mitte niedriger als `SPARK_MIN_H` (36 px), rückt der Verlauf
    in die Kopfzeile neben das Icon (Klasse `sparktight`), die Kurzangabe
    ersetzt die Raumzeile. Ist auch dort zu wenig Breite, entfällt der Verlauf,
    die Kurzangabe bleibt.
  - Passt die Kurzangabe nicht in den Kopf, steht sie ebenfalls in der
    Raumzeile (`sparkbadge`).
  - Kacheln ohne Raumzeile (Raum-Ansicht, Favoriten aus nur einem Raum)
    bekommen dafür eine eigene Zeile über dem Namen. Die Mitte wird dadurch
    niedriger, deshalb misst `paintSpark()` nach jedem Wechsel von
    `sparkbadge` neu (`placeSpark()`) und zeichnet den Verlauf in der neuen
    Höhe oder rückt ihn in den Kopf.
  - Beschriftungen entfallen bei zu wenig Platz (Tief/Hoch und Wochentage unter
    48 px Höhe, Wochentage auch unter 16 px je Tag), statt sich zu überlappen.

## 4. HTTP- und WebSocket-Schnittstelle

Alle Routen werden in `main()` (`webvisu.py:3044`) registriert. Es gibt keine
Authentifizierung, keine Middleware, kein CORS. Jeder im Netz kann alles.

| Methode | Pfad | Handler | Zweck | Genutzt von |
|---|---|---|---|---|
| GET | `/` | `index` | `panel.html` | Visu |
| GET | `/config` | `config_index` | `config.html` | Konfigurator |
| GET | `/settings` | `settings_index` | Weiterleitung nach `/config` (Anker bleibt) | alte Links |
| GET | `/i18n.js` | `i18n_js` | Übersetzungskatalog | Konfigurator, Einstellungen |
| GET | `/install-agent.sh` | `install_script` | Installer als Text | Panel-Installation |
| GET | `/api/meta` | `api_meta` | Räume, Kategorien, alle Controls, Icons, Profile, Geräte, Theme | Konfigurator, Einstellungen |
| POST | `/api/panels` | `api_save_panels` | `panels.json` schreiben, danach `reload` an alle Panels | Konfigurator |
| POST | `/api/theme` | `api_save_theme` | `theme.json` schreiben, danach `reload` | Konfigurator |
| GET | `/api/settings` | `api_settings` | Miniserver-Status (ohne Passwort), Intercom-Liste | Einstellungen, LoxBerry-Widget |
| GET | `/api/health` | `api_health` | Zustand: Hintergrund-Aufgaben (`miniserver`, `broadcaster`, `audio`, `front`), Miniserver verbunden, Zahl der Panels, Laufzeit. 503, sobald eine Aufgabe beendet ist; ein fehlender Miniserver allein ist kein Fehler | Docker-`HEALTHCHECK` (Unraid) |
| GET | `/api/backup` | `api_backup` | ZIP mit `loxpanel.cfg`, `panels.json`, `theme.json`, Kennwörter (`pass`, `password`) leer, dazu `LIESMICH.txt`. Nicht lesbares JSON bleibt draußen | Settings → Sicherung |
| GET | `/api/types` | `api_types` | Diagnose: Bausteintypen der Anlage mit Status (voll/teilweise/keine), Anzahl, Beispielen, State-Namen, `details`-Schlüsseln und Liste der toten Kacheln; `?format=text` als Tabelle | Einstellungen, Entwicklung |
| POST | `/api/settings/miniserver` | `api_settings_ms` | Zugang speichern, sofort `reconnect()` | Einstellungen, LoxBerry-Widget |
| POST | `/api/settings/intercom` | `api_settings_intercom` | Kamera-URL/Login je Intercom | Einstellungen |
| POST | `/api/settings/audiometa` | `api_settings_audiometa` | Audioserver-Live-Daten (Gen2-Events) ein/aus | Einstellungen |
| POST | `/api/settings/calendar` | `api_settings_calendar` | iCal-Abo + Wetter-Koordinaten für die Front speichern, `front_task` lädt sofort neu | Einstellungen |
| POST | `/api/agent/announce` | `api_agent_announce` | Agent meldet sich, Antwort enthält `dpmsOff`, `reloadHours` | Panel-Agent |
| GET | `/api/agents` | `api_agents` | bekannte Agenten (`online` < 60 s, gelistet < 600 s) | Einstellungen |
| POST | `/api/agent/command` | `api_agent_command` | `start`/`reload`/`stop` an einen Agenten weiterleiten | Einstellungen |
| POST | `/api/devices` | `api_save_devices` | Betriebsmodus-Zuordnung je Gerät | Einstellungen |
| GET | `/api/devices` | `api_devices_get` | alle Anzeigegeräte (Agent, Kiosk-App, Browser) mit Online-Status, Ansicht, Typ; Browser ohne Kennung nach IP | Einstellungen |
| POST | `/api/device/switch` | `api_device_switch` | Ansicht eines Geräts wechseln (`{device, panel}`), per WebSocket-Push, sonst über den Agenten | Einstellungen |
| POST | `/api/device/name` | `api_device_name` | Browser ohne Kennung benennen (`{ip, name}`), Visu merkt sich den Namen und verbindet neu | Einstellungen |
| GET/POST | `/api/display` | `api_display` | Display schalten (`on=1|0`), Filter `panel`/`device`; wirkt bei Kiosk-Apps | Einstellungen, Loxone, extern |
| GET/POST | `/api/mode`, `/api/mode/{mode}` | `api_mode` | Betriebsmodus umschalten | Loxone-Ausgang, extern |
| POST | `/api/testtone` | `api_testtone` | Testton an Panels | Einstellungen |
| GET/POST | `/api/reload` | `api_reload` | Panels neu laden, Filter `panel`/`device` | Loxone, extern |
| GET/POST | `/api/goto` | `api_goto` | Panels auf Control oder Tab schicken (jeder gültige Tab, auch `kalender`/`wetter`) | Loxone, extern |
| GET/POST | `/api/notify` | `api_notify` | Nachricht einblenden | Loxone, extern |
| GET | `/icon?p=` | `icon_handler` | Loxone-Icon-Proxy, 24 h Cache | Visu, Konfigurator |
| GET | `/cover?u=` | `cover_handler` | Cover-Bild-Proxy, 60 s Cache | Visu |
| GET | `/mjpeg?id=` | `mjpeg_handler` | MJPEG-Relais der Türstation | Visu |
| GET | `/ws?panel=&device=` | `ws_handler` | Haupt-WebSocket | Visu |

### Parameter an der Panel-URL

Neben `?panel=<id>` und `?device=<name>` kennt `panel.html` zwei Regler, die
das Gerät selbst merkt (`localStorage`) — gedacht zum Einstellen direkt am
Wandpanel, ohne Konfigurator:

| Parameter | Wirkung | Gemerkt als |
|---|---|---|
| `?x=-6` | Feinversatz der ganzen Visu nach links (`--nudge-x`) | `lp_nudge_x` |
| `?ring=4` | Strichstärke des Positionsrings (`--posring-w`), 6 = Standard | `lp_posring_w` |

Beide **schlagen die Konfiguration**: der Theme-Push setzt dieselben Variablen,
danach greift `posringOverride()` erneut. Das ist gewollt — der Wert am Gerät
gewinnt, sonst wäre der Live-Test beim nächsten Push weg. Ohne gemerkten Wert
gilt wieder, was unter *Panel Configuration → Positionsring* eingestellt ist.

Fehlend: `_apply_tile_style()` erzeugt URLs `/gicon?name=` und `/uicon?f=` für
Google- und Custom-Icons (`:1598`, `:1601`), aber diese Routen sind nicht
registriert. Im Konfigurator ist der entsprechende Reiter deaktiviert.

---

## 5. Konfigurationsdateien

Alle liegen in `config/` (im Container `/app/config`, als Volume gemountet).
Pfade sind Modul-Globals in `webvisu.py:67-70`.

### 5.1 Miniserver-Zugang, Priorität

`_config()` (`:200`):

1. `loxpanel.cfg` → `miniserver` (nur wenn `host` gesetzt)
2. Umgebungsvariablen `LOXPANEL_MS_HOST/USER/PASS/PORT/VERIFY_TLS`
3. `loxpanel.cfg.example`
4. leer, Server startet trotzdem

Ein unter `/config` (Settings → Miniserver) gespeicherter Zugang hat also Vorrang vor Docker-Variablen.

### 5.2 `loxpanel.cfg`

| Sektion | Felder | Gelesen von |
|---|---|---|
| `miniserver` | `host`, `user`, `pass`, `port`, `verify_tls` | `_config()` |
| `intercom` | `{control-uuid: {url, user, pass}}` | `_intercom_config()` |
| `audio` | `host` (optional, sonst Auto-Erkennung aus Cover-URLs), `port` (7091), `enabled` | `_audio_config()` |
| `calendar` | `ical_url`, `name`, `lat`, `lon`, `days`, `fore_days` (Front: iCal-Abo + Wetter) | `_calendar_config()` |
| `night` | `control` (UUID eines Bausteins mit `active`-State; leer = Sonnenzeiten entscheiden) | `_night_config()` |

In der Beispieldatei stehen zusätzlich `loxone.poll_interval`, `mqtt`, `web`,
`lms` und `miniserver.msno`. Diese Sektionen wertet der Server **nicht** aus.

Geschrieben wird die Datei komplett neu durch `_write_cfg()`, nur über die
Settings-Endpunkte. Passwörter liegen im Klartext.

### 5.3 `panels.json`

Gelesen von `load_panels()` und `load_devices()`, geschrieben über
`POST /api/panels` bzw. `POST /api/devices`. Struktur:

```jsonc
{
  "panels": {
    "wohnzimmer": {
      "title": "Wohnzimmer",                 // max. 40 Zeichen
      "tabs": ["room:<uuid>", "favoriten", "cat:<uuid>"],  // max. 4, leer = alle 4 Standard-Tabs
                                             // `cat:`/`room:` = Direkt-Tab in eine
                                             // Kategorie bzw. einen Raum,
                                             // `kalender`/`wetter` = eigene Seite
                                             // aus der Front (FRONT_TABS). Der ERSTE
                                             // Tab ist die Startseite: das Panel
                                             // verbindet sich dorthin und kehrt nach
                                             // 60 s Leerlauf dorthin zurueck -> ein
                                             // Raum als erster Tab heisst, das Panel
                                             // wacht direkt in diesem Raum auf.
                                             // Die Reihenfolge der Liste IST die
                                             // Reihenfolge der Leiste; im Konfigurator
                                             // legt die Klickreihenfolge sie fest.
      "rooms": ["<uuid oder Namensteil>"],   // Whitelist, leer = alle
      "cats":  ["<uuid oder Namensteil>"],
      "hide":  ["<control-uuid>"],           // einzelne Kacheln ausblenden
      "ui": {
        "iconSize": 38, "nameSize": 18, "subSize": 15, "font": "Inter",
        "textColor": "#e8eaed", "bold": true, "lang": "de",
        "nudgeX": -6, "dpmsOff": 180, "reloadHours": 12,
        "cols": 4, "rows": 3, "fill": true,
        "scale": "auto",                     // "off" | "auto" | Faktor 0.5–2.0; fehlt = wie global
        "panes": {"favoriten": "chart:<uuid>"},   // rechte Hälfte je Tab: "weather" | "calendar" |
                                             // "player:<uuid>" | "energy:<uuid>" | "camera:<uuid>" |
                                             // "chart:<uuid>" (Verlauf eines Bausteins mit
                                             // Aufzeichnung); fehlt = Screen füllen
        "overlay": {"mode": "both", "fill": 16, "bord": 55, "bw": 1,
                    "ibord": 8, "ibw": 1,          // Rahmen inaktiver Kacheln
                    "ring": 100, "rtrk": 18, "rw": 6}  // Positionsring
      },
      "states": {"active": "#..", "good": "#..", "warn": "#..", "crit": "#.."},
      "tiles": {
        "<control-uuid>": {
          "bg": "#..", "border": "#..", "iconColor": "#..", "textColor": "#..",
          "font": "..", "bold": true, "italic": false,
          "icon": {"src": "builtin", "id": "bulb"},   // oder {"src":"loxone","p":"..svg"}
          "overlay": {...},
          "chart": "24h",                    // Mini-Verlauf in der Kachel: "24h" | "7d" | "30d"
          "chartStyle": "pattern"            // Darstellung: fehlt = Trend | "pattern" | "span" (nur mit chart)
        }
      }
    }
  },
  "devices": {
    "<Gerätename>": {
      "auto": true, "modes": {"<Modusname>": "<panel-id>"},
      "display": {"driver": "fully", "host": "192.168.1.60", "port": 2323, "password": "..."},  // optional; auch "wallpanel" (Port 2971)
      "scale": "off"                         // optional; übersteuert Profil und global ("off" | "auto" | Faktor)
    }
  }
}
```

Die Validierung in `_sanitize_panels()` (`:933`) ist eine Whitelist, die unbekannte
oder falsch getypte Felder **still verwirft**. Die Antwort ist trotzdem
`{"ok": true}`. Wer eine neue Option ergänzt, muss sie dort eintragen, sonst geht
sie beim Speichern verloren.

### 5.4 `theme.json`

Globale Darstellung: `states` (Zustandsfarben), `categories` (Farbe je
Kategorie, Teilstring-Match auf den Namen, entweder eine Farbe oder `{on, off}`),
`ui` (wie oben, gilt für alle Panels). Panel-`ui` überschreibt Theme-`ui`.
`_write_theme()` löscht `ui`-Keys, die nicht im Payload stehen. Welche Keys
der Konfigurator unter Global → Darstellung setzt, steht einmal in
`THEME_UI_KEYS`: `_write_theme()` schreibt genau diese, `/api/meta` liefert
genau diese. Was `_sanitize_theme_ui()` neu erlaubt, muss auch dort stehen,
sonst geht es beim Speichern still verloren. Dazu gehört `scale`, die
Skalierung für alle Panels; fehlt sie, ist sie aus.

In `ui` steckt auch `baseColor`: die Grundfarbe des Panel-Themes. Steht sie da,
leitet `theme_colors.derive()` daraus den ganzen Farbsatz ab — Hintergrund,
Kachel, Leiste, Schrift, Zweitzeile, Icon- und Zustandsfarben — und
`_theme_vars()` schickt ihn als CSS-Variablen mit. Ohne `baseColor` ändert sich
nichts: jede Farbe in `panel.html` trägt ihren bisherigen Wert als Rückfall.
Ausdrücklich gesetzte `states` schlagen die Herleitung.

---

## 6. Loxone-Bausteine

**Grundregel: Wir sehen genau das, was in der Visualisierung steht.** LoxPanel
liest ausschließlich die `LoxAPP3.json` des Miniservers und den zugehörigen
State-Stream. Was dort als Control auftaucht (Objekt mit Raum *und* Kategorie,
Verwendung in der Visu aktiviert), können wir anzeigen und — wo der Baustein es
hergibt — auch bedienen. Was nicht drinsteht, existiert für uns nicht, egal wie
sichtbar es in Loxone Config ist.

**Lehrstück Betriebsmodi** (an einer echten Anlage nachgemessen, 09/2026):
`globalStates.operatingMode` führt nur den **Kalendertag**-Modus (Wert `5` =
„Mittwoch"). Die gleichzeitig laufenden Sondermodi — in Loxone Config an den
negativen IDs erkennbar: „Abendstimmung" (−13), „Nachtruhe" (−12), „Anwesend"
(−7) — stehen dort **nicht** und sind über die Struktur nicht abgreifbar. Auch
nicht, wenn der Config-Baum hinter dem Modusnamen Raum und Kategorie anzeigt:
Das sind die Räume der *Logikbausteine*, die den Modus füttern (z. B.
„\*Anwesend – ODER", „Anwesend – Monoflop"), nicht die des Modus selbst.

Der Ausweg ist derselbe wie für alles andere: **den Zustand in Loxone auf ein
Visu-Objekt legen.** In der untersuchten Anlage war das für zwei Modi bereits so
gemacht — „Fernsehen abend" als `InfoOnlyDigital`, „Frostsicherung" als
`Switch`. Beide liefern ihren Zustand über denselben State `active` und sind
damit ohne Sonderbehandlung auswertbar. Wer einen weiteren Modus braucht, hängt
ihn in Loxone Config an einen Status-Baustein mit Raum und Kategorie — danach
sieht LoxPanel ihn ohne jede Codeänderung.

Die Liste der unterstützten Typen steht im README (39 voll, 6 teilweise, 16
geplant). Technisch gibt es zwei Ebenen, beide in `webvisu.py`:

- **Kachel:** `_control_item()` (`:1292-1559`), eine ~270 Zeilen lange `elif`-Kette
  über den Typ. Setzt `icon`, `on`/`tone`, `sublabel` und entweder `nav`
  (Detailseite) oder `cmd` (Direktschaltung) oder `controls[]` (Mini-Buttons).
- **Detailseite:** `_view_control_inner()` (`:1731-2308`), eine ~580 Zeilen lange
  `if`-Kette, die `blocks[]` zusammenstellt.

Sonderfälle:

- Schalter mit `active`-State stehen in der Konstante `SWITCHY` (`:88`).
- Reine Anzeigen stehen in `STATUS_BIG` (`:98`) und bekommen eine generische
  Großansicht über `_big_view()`.
- Analoge Werte ohne An/Aus stehen in `_ANALOG` (`:102`), damit die
  Kategorie-Ampel neutral bleibt.
- Zentralbausteine werden über den Präfix `Central` am Ende der Kette gefangen.
- Die Reihenfolge der Kette ist semantisch relevant (z. B. `SWITCHY` vor
  `TimedSwitch`).

**Unbekannte Typen:** Es gibt keinen `else`-Zweig. Die Kachel bleibt bei
`{"label": name, "icon": "info", "on": false}` ohne `nav` und ohne `cmd`, ist also
sichtbar, aber tot. Welche Typen der eigenen Anlage betroffen sind, zeigt
`/api/types` (`App.types_overview()`, Status aus dem Rendering abgeleitet,
`PARTIAL_TYPES` markiert die teilweise umgesetzten).

**Adapter:** `adapters.py` war als Erweiterungsmuster gedacht. Der Server nutzt
nur die zwei konkreten Klassen als Modul-Globals `LIGHT` und `JAL`. Die Registry
`get_adapter()` wird nicht abgefragt. Neue Typen gehören in die beiden Ketten,
nicht in einen Adapter.

---

## 7. Frontend

Zwei Single-File-Seiten ohne Framework, `settings.html` ist seit Upstream 0.3.2
nur noch eine Weiterleitung. Nur `config.html` lädt `/i18n.js`; die Visu nicht.

### 7.1 `panel.html` (Visu, 772 Zeilen)

- Spricht ausschließlich über den WebSocket, kein einziger `fetch`. Bilder kommen
  über `/icon`, `/cover`, `/mjpeg`.
- Zwei Renderer: `render()` (`:597`) für Kachelraster aus `items[]`,
  `renderPanel()` (`:472`) für Detailseiten aus `blocks[]`, dazu `updatePanel()`
  (`:550`) als Delta-Update, das bei Live-Werten nur Texte und Slider anfasst.
- Block-Rendering in `bh()` (`:486-516`), ein Zweig je `k`.
- Kachel-Grid über CSS-Variablen `--cols`/`--rows` (2×2, 3×2, 4×3), Kachelgröße
  auf 240 px gedeckelt, außer bei `fill`. Seiten-Snapping pro `cols*rows` Kacheln.
- Eingebaute Icons: `ICONS` (`:273-296`, 22 SVGs). Loxone-Icons als CSS-Maske,
  damit sie die Zustandsfarbe annehmen.
- Skalierung, Kette global (`theme.json` `ui.scale`) → Profil (`ui.scale`) →
  Gerät (`devices[name].scale`): die spätere gewinnt, fehlt sie, gilt die
  frühere. Profil und Gerät speichern deshalb auch `"off"` ausdrücklich, sonst
  könnte ein Profil ein globales `"auto"` nicht abschalten. Die Visu
  rechnet mit festen 240er Kacheln, der Kasten ist also 480×480 bzw. im Split
  960×480. Ein größeres Display zeigte ihn bisher mit Rand (1280×800: 55 % des
  Schirms ungenutzt). `applyScale()` setzt `--ui-scale` am `.screen`
  (`transform: scale`): bei `"auto"` so groß, wie ohne Rand und Verzerrung
  geht, ein fester Faktor höchstens so groß, dass alles passt. Das Layout
  bleibt unverändert, nur die Anzeige wächst — deshalb muss jeder Code, der
  sichtbare Maße (`getBoundingClientRect`, Pointer-Koordinaten) mit Layout-Maßen
  (`offsetWidth`, CSS-Werte) verrechnet, durch `visScale(el)` teilen (Menü,
  Grundriss-Zoom; `svFit()` misst nur noch Layout-Höhen). `overflow:hidden`
  steht nur auf `html`: `body` ist Grid-Element mit `place-items:center` und
  damit so schmal wie der ungeskalierte Kasten — dort schnitte es die
  vergrößerte Anzeige ab. Ein `ResizeObserver` am `.screen` rechnet den Faktor
  neu, wenn sich der Kasten ändert (Split an/aus beim Tab-Wechsel).
- Screensaver: rechte Spalte je Panel einstellbar (`ui.svPane`), wirksam nur im
  Querformat. Werte: `""` = Automatik (Termine, und sobald keine anstehen die
  Wetter-Details — so bleibt die halbe Fläche nie leer), `off`, `calendar`,
  `weather`, `energy:<uuid>`, `camera:<uuid>`, `status:<uuid>,…`. Geprüft an
  EINER Stelle (`_clean_svpane()`), gezeichnet in `renderSvSide()`. Energiefluss
  und Kamera haben beim Server je Verbindung nur einen Platz: liegt die Uhr-Seite
  oben, gilt ihre Wahl, und die Kamera-Pane darunter wird geleert — sonst liefe
  ihr MJPEG-Stream unsichtbar weiter.
  Steht rechts Energiefluss oder Kamera, schaltet die Uhr-Seite auf das Layout
  `.tall`: Uhr und Wetter links, die Grafik rechts über die volle Höhe. Beide
  brauchen Höhe (Energiefluss quadratisch, Kamera 4:3); über beiden Spalten nahm
  ihnen die Uhr ein Fünftel davon. Gemessen bei 960×480: Energiefluss 299 → 392 px,
  Knotennamen 7,5 → 11,4 px, Kamerabild 362×269 → 418×314. Die beiden Spalten
  sind gleich breit, und links füllen Uhr und Wetter die Höhe: die Uhr (96 px)
  sitzt unten in der oberen Hälfte, das Wetter oben in der unteren. Mit der
  60-px-Uhr des Querformats nutzte die linke Seite nur 49 % der Höhe und die
  Box rechts wirkte übergroß, jetzt 70 %. Die Energiegrafik behält dabei ihre
  392 px, weil sie von der Höhe begrenzt wird, nicht von der Breite. Ohne
  Wetter steht die Uhr allein mittig.
- Screensaver-Uhr nach 60 s, Start immer mit Uhr. Weckton synthetisch per Web
  Audio (880 Hz). PIN-Ziffernblock für `isSecured`-Controls. Wisch nach rechts =
  zurück. Reconnect nach 1,5 s.
- Sprache wirkt nur auf Datum und Uhrzeit. Alle anderen Panel-Texte sind hart
  deutsch, sowohl im Frontend als auch in den vom Server erzeugten Texten
  („Offen", „Heizt", „Heute", Wochentage, Button-Beschriftungen).

### 7.2 `config.html` (Konfigurator, 715 Zeilen)

- Liest `GET /api/meta`, schreibt `POST /api/panels` und `POST /api/theme`.
- Die gesamte rechte Seite wird per `innerHTML` neu aufgebaut; Zustand in vier
  Modulvariablen (`META`, `PANELS`, `cur`, `dirty`).
- Virtuelles Profil `__global__` landet in `theme.json` statt `panels.json`.
  Die Skalierung dort hat keine Erb-Option („Aus" ist das Fehlen des Keys),
  das Profil bietet „Wie global (…)" mit dem geerbten Wert in Klammern, das
  Gerät „Wie im Profil".
- Kachelliste auf 400 Einträge begrenzt.
- Eigene Icon-Map `BICONS` (20 Icons, `fan` und `list` fehlen gegenüber der Visu).
- Overlay-Vorschau rechnet die Alphas selbst nach (`ovPreview()`), parallel zur
  Server-Logik `_overlay_alphas()`.

### 7.3 Rubrik „Settings" in `config.html` (früher `settings.html`)

Die frühere Einstellungsseite liegt als zweite Rubrik im Konfigurator; die
Speicherleiste unten gilt nur für „Panel Configuration". Sieben Reiter:
Miniserver (mit Link auf `/api/types`), Kamera/Türstation, SIP (nur
Platzhalter), Panels (alle Anzeigegeräte: Agent, Kiosk-App, Browser; Polling
alle 6 s; Betriebsmodus-Automatik und Display-Treiber je Gerät), Audio (Testton,
Audioserver-Live-Daten), Kalender & Wetter (iCal-Abos, Wetter der Uhr-Seite),
Neues Panel (Start-URL für Kiosk-Apps, SSH-Befehl für Linux-Panels). Zu einem
Reiter führen die Kacheln der Übersicht (`data-goto="settings:<reiter>"`) oder
die Reiterleiste; einen Anker in der URL (`/config#panels`) wertet die Seite
nicht aus, sie öffnet wie immer die Übersicht. Kein Dirty-Flag, ungespeicherte
Eingaben gehen beim Verlassen verloren.

### 7.4 `i18n.js`

Schlüssel ist der deutsche Quelltext, Katalog nur `en`. Drei Wege: `data-i18n`
auf statischem Markup, `T('...')` im JS, und `autoChrome()` mit
`MutationObserver` für per `innerHTML` erzeugte Texte. Sprachwahl über
`localStorage['lp_ui_lang']`, sonst Browser-Sprache. Der Konfigurator bietet
sechs Panel-Sprachen an, der Katalog kennt zwei.

---

## 8. Panel-Agent

`agent/loxpanel-agent.py`, reine Standardbibliothek, läuft auf dem Wandpanel als
Login-Benutzer aus `~/.xsession`.

**Eingehend:** HTTP-Server auf `0.0.0.0:8130` ohne Authentifizierung mit
`GET /status`, `POST /start` (mit optionalem `panel`), `POST /reload`, `POST /stop`.
Mehr kennt der Agent nicht. `goto`, `notify` und `reload` als Push-Aktionen laufen
über den Server direkt an den Browser.

**Ausgehend:** alle 15 s `POST /api/agent/announce` mit `{name, panel, ip, port,
kiosk}`. Die Antwort trägt `dpmsOff` und `reloadHours` aus dem Panel-Profil, die
der Agent lokal anwendet.

**Konfiguration:** erste existierende Datei aus `$LOXPANEL_KIOSK_CONF`,
`../deploy/loxpanel-kiosk.conf`, `/etc/loxpanel/kiosk.conf`. Umgebungsvariablen
`LOXPANEL_<KEY>` haben Vorrang. Schlüssel: `SERVER`, `AGENT_PORT`, `AGENT_NAME`,
`PANEL`, `AUTOSTART`, `X`, `DPMS_OFF`, `PROFILE_DIR`, `BL_DEVICE`, `BL_ON`,
`PAUSE_ON_BLANK`, `RELOAD_HOURS`, `STATE_FILE`. Die Beispieldatei dokumentiert
nur acht davon.

**Funktionen:** Chromium-Kiosk mit festen Flags, Crash-Dialog-Bereinigung in
`Default/Preferences`, DPMS über `xset`, echte Backlight-Abschaltung über alle
`/sys/class/backlight/*/brightness`, optionale SIGSTOP-Pause (Default aus, weil
der WebSocket dabei stirbt), periodischer Kiosk-Neustart, Panel-Wahl in einer
State-Datei.

**Installation:** `deploy/install-agent.sh`, als Login-Benutzer ohne sudo
aufrufen. Der Agent-Quelltext ist dort als Heredoc eingebettet, nicht kopiert.
Der Code ist derzeit identisch mit `agent/loxpanel-agent.py`, die Kommentare
weichen bereits ab. Der Server liefert ausgerechnet diese Kopie über
`/install-agent.sh` aus. Es gibt keinen Mechanismus, der die beiden synchron
hält.

**Ohne Agent (Android):** Seit dem Umbau-Schritt 1 schickt der Server `dpmsOff`,
`reloadHours` und `agent` mit der `theme`-Nachricht an die Visu. Meldet der
Server keinen Agenten für die Gerätekennung, schaltet die Seite das Display
selbst über die JavaScript-Schnittstelle von Fully Kiosk Browser
(`window.fully`), weckt es bei Klingel, Wecker, Notify und Goto und lädt sich
nach `reloadHours` neu. Der Agent hängt dafür `device=<Name>` an die
Kiosk-URL, damit der Server Agent-Panels am WebSocket erkennt
(`App._has_agent`). `App.device_list()` führt Agenten, verbundene Browser und
konfigurierte Geräte über den Namen zusammen; die Einstellungen zeigen daraus
eine Liste mit Typ, Online-Status, Ansicht und Aktionen (Ansicht wechseln,
Neu laden, Display aus/an). Browser ohne Kennung werden nach IP gelistet und
können benannt werden. Die Visu meldet `kiosk=fully` in der WebSocket-URL,
wenn sie in Fully Kiosk läuft.

**Display-Treiber (Schritt 3):** `App.display_drivers(on, device, panel)`
spricht je Gerät die HTTP-Schnittstelle der Kiosk-App an (`_drive_display`):
Fully Kiosk Remote Admin per `GET /?cmd=screenOn|screenOff&password=`,
WallPanel per `POST /api/command {"wake": true|false}`. Konfiguration in
`panels.json` unter `devices[name].display`, Konstante `DISPLAY_DRIVERS`.
Aufrufer: `/api/display` (wartet auf das Ergebnis), Klingel und Wecker im
`broadcaster`, `/api/notify` und `/api/goto` (im Hintergrund, `_spawn`),
sowie die `idle`-Meldung der Visu. Einrichtung in `deploy/ANDROID.md`.

**Bekannte Schwäche:** Die State-Datei liegt standardmäßig in `/etc/loxpanel/`,
das per `sudo mkdir` als root angelegt wird, während der Agent als
Login-Benutzer läuft. Das Schreiben schlägt dann leise fehl, und die gewählte
Ansicht überlebt vermutlich keinen Reboot.

---

## 9. LoxBerry-Plugin, Unraid, Build und Release

### 9.1 LoxBerry-Plugin

Das Plugin ist nur ein Docker-Starter. `loxpanel-ctl.sh` kennt `start` (pull +
up), `stop` (Marker-Datei + down), `restart`, `check` (Cron alle 5 min und beim
Boot), `backup` und `restore` (tar.gz des Config-Ordners, erzeugt im Container
als root, 20 Stück Rotation). Das Widget `index.cgi` (Perl) spricht
`http://localhost:8099/api/settings` und `/api/settings/miniserver`.

`sudoers` erlaubt dem Benutzer `loxberry` `docker` ohne Passwort, was faktisch
Root-Rechte auf dem LoxBerry bedeutet.

### 9.2 Unraid

Template `unraid/loxpanel.xml`, Anleitung `deploy/UNRAID.md`. Start/Stop, Update
und Backup übernimmt Unraid. Was das LoxBerry-Widget an Funktionen hat, gibt es
auf Unraid über `/config` (Settings, dort auch *Sicherung* = `/api/backup`) und
den appdata-Ordner.

- **Zustand:** `HEALTHCHECK` im Dockerfile ruft alle 30 s `/api/health` auf
  (Python statt curl, das slim-Image hat kein curl); Unraid zeigt healthy /
  unhealthy im Docker-Tab. `tests/test_rauchtest.py` führt genau diesen Befehl
  aus dem Dockerfile aus.
- **Log:** `LOXPANEL_LOG_LEVEL` (`DEBUG`, `INFO`, `WARNING`, `ERROR`; Standard
  `INFO`, Unbekanntes → `INFO` mit Warnung). Der Zugriffs-Log von aiohttp (eine
  Zeile je Anfrage) erscheint nur bei `DEBUG` (`_logging_einrichten()`).
- **Image:** `.dockerignore` hält Altlasten (`webfrontend/htmlauth`,
  `config/visu.*`, `daemon/` …) und Test-/Entwicklungsdateien aus dem Image.

### 9.3 Build und Release

| Workflow | Trigger | Ergebnis |
|---|---|---|
| `tests.yml` | jeder PR, Push auf `main`, manuell | Syntax (alle `bin/*.py`, Workflows, Unraid-Vorlage), `ruff` mit Fehlerregeln (`F`, `E9`), pytest ohne Browser inkl. Rauchtest, Browser-Tests in Chromium (Screenshots als Artefakt), bei PRs Probe-Build des Images für amd64 ohne Push |
| `docker-image.yml` | Push auf `main`, Tags `v*`, manuell | `ghcr.io/chief-wiggum1203/loxpanel` mit Tags `latest`, `v<tag>`, `sha-<kurz>`; Plattformen amd64, arm64, arm/v7 |
| `plugin-release.yml` | GitHub-Release veröffentlicht, manuell | `loxpanel-plugin.zip` aus `loxberry-plugin/` am Release |

Ein App-Update braucht keinen Plugin-Bump, weil `:latest` rollend ist. Für ein
Plugin-Release: `VERSION` in `loxberry-plugin/plugin.cfg` und
`loxberry-plugin/release.cfg` gemeinsam hochzählen, nach `main` pushen,
GitHub-Release mit Tag `v<version>` anlegen. `NAME`, `FOLDER` und `AUTHOR` nie
ändern. Das GHCR-Package muss einmalig auf public stehen (bereits erledigt).

---

## 10. Erweiterungs-Rezepte

### (a) Neuen Loxone-Bausteintyp unterstützen

1. Kachel: neuer `elif t == "<Typ>":`-Zweig in `_control_item()`
   (`webvisu.py:1314-1537`). States lesen über `self._state(c, "<name>")`, Zahlen
   formatieren über `self._fmt_num()`, Texte über `self._text()`.
2. Detailseite: neuer `if t == "<Typ>":`-Zweig in `_view_control_inner()`
   (`:1731-2308`) vor dem Fallback. Blöcke aus dem Vokabular in Abschnitt 3.7.
   Für reine Anzeigen reicht `self._big_view()` plus ein Eintrag in `STATUS_BIG`.
3. Optional: `SWITCHY`, `_ANALOG`, Flanken-Erkennung in `_apply_structure()`.
4. Neues Icon: `ICONS` in `panel.html:273` und, falls im Konfigurator wählbar,
   `BICONS` in `config.html:191`.
5. Neuer Blocktyp: Zweig in `bh()` (`panel.html:486`), ggf. `updatePanel()` und CSS.

Das Frontend muss im Regelfall nicht angefasst werden.

### (b) Neuen API-Endpunkt

Handler als Modul-Funktion zwischen `:2489` und `:2960`, `app: App =
request.app["app"]`, Registrierung in `main()` bei `:3044`. Für JSON-Body das
Muster `try: await request.json() except (ValueError, aiohttp.ContentTypeError)`,
für GET+POST `_json_or_empty()` und `_push_filter()`, für Pushes `_push()`.

### (c) Neue Einstellung in `loxpanel.cfg`

Leser nach dem Muster `_audio_config()` (`:232`), Feld in `App.__init__`, bei
Verbindungsrelevanz auch in `reconnect()` neu einlesen. Schreiben über
`_load_cfg()` + Mutation + `_write_cfg()`. Für die UI: Feld in `api_settings`,
neuer POST-Handler, Rubrik „Settings" in `config.html`, `i18n.js`. Bei Env-Override zusätzlich
`_config()`, `.env.example`, `docker-compose.yml`, `unraid/loxpanel.xml`.

### (d) Neue Option im Konfigurator

1. Feld in `appearanceFields()` (`config.html:311`, global und pro Panel) oder im
   Markup von `renderEditor()` (`:370`). Zahlenfelder nur mit `data-ui="<key>"`.
2. Handler in `bindAppearance()` (`:295`) mit `markDirty()`.
3. Server-Whitelist in `_sanitize_panels()` (`webvisu.py:948-975`) bzw.
   `_sanitize_theme_ui()`, sonst wird die Option still verworfen.
4. Wirkung: CSS-Variable in `_theme_vars()` (`:728`) oder Verhalten in
   `resolve_profile()` (`:766`) plus `theme`-Payload plus Frontend.
5. Übersetzung in `i18n.js`.

### (e) Neue Sprache oder neuer Text

Sprache: Code in `LANGS` (`i18n.js:11`), Block in `CAT`. Text: `data-i18n` im
Markup oder `T('Deutscher Text')` im JS, den deutschen Text zeichengenau als
Schlüssel in jeden Sprachblock. Panel-Texte sind davon nicht erfasst, die stehen
hart im Server.

### (f) Design

Visu statisch in `panel.html:8-256`, zur Laufzeit über CSS-Variablen mit
Defaults in `_theme_vars()`. Admin-CSS liegt seit der Zusammenlegung nur noch in
`config.html`.

---

## 11. Bekannte Schwachstellen

### Fehler

| Nr. | Befund | Stelle |
|---|---|---|
| F1 | Routen `/gicon` und `/uicon` werden erzeugt, aber nie registriert | `webvisu.py:1598`, `:1601` |
| F2 | `op_modes` fehlt in `App.__init__` — behoben, `/api/types` warf ohne Miniserver einen `AttributeError` | `:394`, Workaround `:1235` |
| F3 | Push-Stellen fangen nur `ConnectionError`. Ein `RuntimeError` beim Senden würde den Broadcaster-Task beenden, alle Panels blieben stumm, ohne Log — behoben, alle Push-Stellen senden über `_send_or_drop()` (jeder Fehler, 5 s Zeitlimit) | `:2452-2467`, `:2797` |
| F4 | `icon_cache` unbegrenzt, kein Limit, keine TTL — behoben, `ICON_CACHE_MAX` | `:359`, `:1139` |
| F5 | Kein atomares Schreiben der drei Config-Dateien (kein tmp+rename) | `:84`, `:1020`, `:1119` |
| F6 | `_write_cfg` und die Settings-Handler fangen `OSError` nicht | `:83`, `:2653`, `:2685` |
| F7 | `reconnect()` greift mit `ms["user"]` direkt zu, unvollständige cfg → `KeyError` | `:443` |
| F8 | `fetch_icon` hat kein Timeout und fängt `asyncio.TimeoutError` nicht — behoben, ebenso `fetch_cover` (`COVER_TIMEOUT`) | `:1123` |
| F9 | `JSON.parse` im WebSocket-Handler ohne try/catch — behoben | `panel.html:701` |
| F10 | `esc()` in der Visu escapt keine Anführungszeichen, Ausgabe landet in Attributen. Freitext-Schriftarten und Miniserver-Namen mit `"` zerlegen das Markup | `panel.html:316`, `:631`, `:637` |
| F11 | Panel-`states`-Farben werden nicht validiert und landen direkt in `setProperty` | `webvisu.py:979` |
| F12 | `updatePanel()` mappt Blöcke per Index und erstem Treffer, zwei `status`-Blöcke aktualisieren das falsche Element | `panel.html:550-574` |
| F13 | Agent-State-Datei in root-eigenem Verzeichnis, Panel-Wahl überlebt vermutlich keinen Reboot | `agent/loxpanel-agent.py:111`, `install-agent.sh:33` |
| F14 | `requests` wird von drei Skripten importiert, steht aber nicht in `requirements.txt` | `cover_test.py`, `proxy_test.py`, `loxone_client.py` |
| F16 | Globale Regel `.empty{grid-column:1/-1}` (für „nichts hier" im Kachelraster) traf auch die Leerfelder vor dem 1. im Monatskalender: sie belegten eine ganze Zeile, jeder Monat begann am Montag, alle Tage standen unter dem falschen Wochentag (Split-Pane Kalender) — behoben, Regel auf `.grid>.empty` begrenzt; Regressionstest misst die Spalten im Browser | `panel.html` CSS, `fpMonthHTML()` |
| F15 | Das Miniserver-Token wurde nur beim Neuaufbau des WebSockets erneuert. Blieb der stabil, lief es ab: Werte kamen weiter, Befehle scheiterten still (passt zu: Panel nach ein bis zwei Tagen nicht mehr bedienbar) — behoben, §3.4 | `command()`, `_stat_load()`, `fetch_icon()` |

### Sicherheit

| Nr. | Befund |
|---|---|
| S1 | Keine Authentifizierung auf irgendeiner Route. `POST /api/settings/miniserver` nimmt Zugangsdaten entgegen, `POST /api/panels` überschreibt die Konfiguration, `/api/mode` schaltet Panels um, `/api/meta` liefert die komplette Anlage. Einziger Schutz ist das Netzsegment. |
| S2 | `/cover?u=` ist ein offener Proxy ohne Host-Whitelist (SSRF). |
| S3 | Miniserver- und Kamera-Passwörter im Klartext in `loxpanel.cfg`. PIN wird im Klartext über den WebSocket übertragen. Gesamter Verkehr ist HTTP. |
| S4 | Agent-HTTP auf `0.0.0.0:8130` ohne Auth. Jeder im LAN kann Panels umschalten oder abschalten, der `panel`-Wert wird persistiert. |
| S5 | LoxBerry-`sudoers`: `docker` ohne Passwort ist faktisch Root. |
| S6 | `/mjpeg` ohne Begrenzung gleichzeitiger Streams, jeder hält eine eigene Session. |
| S7 | `verify_tls: false` ist überall Standard und im LoxBerry-Widget fest verdrahtet. |

### Performance

- P1: Vollrendering jeder offenen Ansicht bei jeder State-Änderung, alle 0,3 s,
  inklusive JSON-Parsing von `moodList`, `entryList`, `sourceList` in jedem
  Durchlauf (Abschnitt 3.5).
- P2: `panels.json` wird bei jedem Zugriff zweimal geöffnet (`load_panels`,
  `load_devices`).
- P3: Ring- und Alarm-Pushes gehen an alle Verbindungen ohne Panel-Filter.

### Wartbarkeit

- W1: `_control_item()` und `_view_control_inner()` sind zusammen rund 850 Zeilen
  `if/elif`-Kette, Reihenfolge semantisch relevant.
- W2: Agent-Quelltext doppelt (Datei und Heredoc im Installer), Kommentare
  bereits divergiert.
- W3: `esc()` dreifach mit unterschiedlichem Verhalten; Icon-Maps doppelt
  (`ICONS`/`BICONS`); Admin-CSS doppelt; Overlay-Berechnung doppelt;
  Config-Leser dreifach; `api_testtone` dupliziert `_push()`.
- W4: Alle Panel-Anzeigetexte hart deutsch, rund 90 Stellen im Server. Der
  Filter `_irc_modes` matcht per Substring `"schutz"` und bricht bei englischer
  Loxone-Konfiguration still.
- W5: Magic Numbers ohne Konstante (0,3 s, 10 s, 60/600 s, 8 s, Port 8130,
  Port 7091, Mood 778, Daytimer-Dauern, Farbtemperaturen).
- W6: Kategorie-Farben per Teilstring-Match auf Namen; `"Alarm"` matcht auch
  `"Alarmanlage deaktiviert"`.
- W7: `_sanitize_panels` verwirft still, die UI erfährt nie, was verloren ging.
- W8: Keine automatisierten Tests, kein Linter im CI — behoben: `tests/`
  deckt die reinen Funktionen (`_fmt_num`, `_color_parse`, `_alarm_next_text`,
  `_alarm_entries`, `_audio_favs`, `_tracker_lines`, `_resolve_ids`,
  `_sanitize_panels`, `LoxoneWS._parse_values/_parse_texts`), die Verläufe, die
  Token-Erneuerung und die Stabilität ab; `tests.yml` führt sie samt `ruff` auf
  jedem PR aus.

### Doku-Inkonsistenzen

- README-Changelog endet bei 0.2.6, Plugin steht auf 0.3.2.
- README nennt die Stromspar-Pause als aktives Feature, sie ist per Default aus.
- README nennt `armhf`, laut Plugin-Kommentar matcht nur `armv7l`.
- `DOCKER.md` und `DEPLOY.md` sprechen vom „späteren" LoxBerry-Plugin.
- `docker-compose.yml` im Root steht auf `build:`, `DOCKER.md` beschreibt
  `docker compose pull` als Update-Weg.
- `loxpanel-kiosk.conf.example` und die vom Installer erzeugte Datei stimmen nicht
  überein.
- `install-agent.sh` zählt „1/5" bis „5/5", macht aber acht Schritte.

---

## 12. Aufräumkandidaten

Entfernbar ohne Auswirkung auf den Betrieb (keine Referenz im aktiven Code, nicht
im Plugin-ZIP, teilweise trotzdem im Docker-Image):

| Datei | Bemerkung |
|---|---|
| `daemon/loxpanel-daemon.py` | zusammen mit `postinstall.sh` |
| `postinstall.sh`, `apt`, `plugin.cfg` (Root) | Phase-1-Plugin; Root-`plugin.cfg` kollidiert mit dem echten |
| `webfrontend/htmlauth/index.php` | landet über `COPY webfrontend/` im Image |
| `bin/loxone_live.py` | von niemandem importiert |
| `bin/loxone_client.py`, `bin/importer.py` | nur voneinander abhängig |
| `config/visu.schema.json`, `config/visu.example.json` | totes Format, landet im Image |
| `deploy/kiosk.sh`, `deploy/loxpanel-webvisu.service` | durch Agent bzw. Docker abgelöst |
| `agent/loxpanel-agent.service` | wird nie installiert, ohne Handanpassung nicht lauffähig |

Zu bereinigen, nicht zu löschen: die 20 Skripte in `bin/` enthalten Anlagen-UUIDs
und IPs des Original-Autors. Für den Fork sind sie ohne Anpassung nutzlos.
`data/.gitkeep` bleibt, solange `dump_lights.py` und `importer.py` existieren.

Beim Aufräumen den Upstream-Abgleich bedenken: Gelöschte Dateien, die Lenardo1
weiter pflegt, erzeugen bei jedem Merge Konflikte. Für den Anfang ist es
sicherer, nur eindeutig tote Dateien zu entfernen.

---

## 13. Empfohlene nächste Schritte

Priorisiert nach Nutzen für einen eigenen Betrieb auf Unraid:

1. **Atomares Schreiben der Config-Dateien** (F5, F6). Kleiner Eingriff in
   `_write_cfg`, `_persist_panels_file`, `_write_theme`: in `.tmp` schreiben,
   dann `os.replace`. Schützt die Konfiguration vor Stromausfall.
2. **Broadcaster absichern** (F3). `except Exception` mit Logging um jede
   `send_json`, sonst kann ein einzelner Fehler alle Panels stumm schalten.
3. **Escaping in der Visu** (F10). `esc()` um `"` und `'` ergänzen, eine Zeile.
4. **Delta-Rendering oder Drosselung** (P1). Mindestens: pro Verbindung das
   letzte gesendete JSON merken und nur senden, wenn es sich geändert hat. Das
   allein spart bei laufenden Werten einen Großteil der WebSocket-Last.
5. **Einfacher Zugriffsschutz** (S1). Für ein Heimnetz reicht ein optionales
   Token, das `/config` und die schreibenden `/api/*`-Routen
   schützt, während `/`, `/ws` und die Bild-Proxys frei bleiben. Alternativ ein
   Reverse-Proxy mit Auth auf Unraid, dann muss der Installer-Befehl in
   `config.html` HTTPS können.
6. **Cover-Proxy einschränken** (S2). Nur Hosts zulassen, die als Miniserver
   oder Audioserver bekannt sind.
7. **Agent-Kopie aus dem Installer entfernen** (W2). Der Installer kann die
   Datei per `curl` vom Server holen, wenn der Server `agent/loxpanel-agent.py`
   zusätzlich ausliefert. Dann gibt es nur noch eine Quelle.
8. ~~**Tests für die reinen Funktionen** (W8) plus ein Lint-Job im Workflow, bevor
   größere Umbauten beginnen.~~ Erledigt, `tests/` und `tests.yml`.
9. **Altlasten entfernen** (Abschnitt 12), sobald klar ist, wie eng der Fork dem
   Upstream folgen soll.
10. **Bausteinketten aufteilen** (W1). Eine Tabelle `Typ → (kachel_fn,
    detail_fn)` statt der `elif`-Kette macht neue Bausteine zu einer Datei pro
    Typ, ohne das Protokoll zu ändern.
