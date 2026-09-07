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
alle Commits stammen von einem Autor, Version 0.3.1. Der Code ist funktional weit,
aber es gibt keine automatisierten Tests, keine Authentifizierung und einige
Altlasten aus einer früheren Konzeptphase (openHASP/MQTT).

**Umfang:** rund 9.900 Zeilen, davon `bin/webvisu.py` allein 3.080 Zeilen.

---

## 2. Verzeichnisstruktur und Rollen

### 2.1 Aktiver Code

| Pfad | Rolle |
|---|---|
| `bin/webvisu.py` | Der gesamte Server: aiohttp-App, Miniserver-Verbindung, Rendering aller Ansichten, alle Routen, WebSocket zum Browser. Monolith. |
| `bin/loxone_ws.py` | Loxone-WebSocket-Client: Token-Handshake, Binärparsing der Value- und Text-State-Tabellen |
| `bin/adapters.py` | Nur `LightControllerV2Adapter` und `JalousieAdapter` werden genutzt. Die Adapter-Registry darin ist aufgegeben. |
| `bin/audioserver.py` | Backend für Loxone-Audioserver Gen1 / MS4H über WebSocket Port 7091 |
| `webfrontend/html/panel.html` | Die Visu (Kacheln, Detailseiten, Screensaver, PIN, Weckton) |
| `webfrontend/html/config.html` | Konfigurator (Panels, Tabs, Räume, Kacheln, Design) |
| `webfrontend/html/settings.html` | Einstellungen (Miniserver, Intercom, Agenten, Betriebsmodus, Audio) |
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
| `bin/*_probe.py`, `bin/*_check.py`, `bin/*_test.py` (20 Dateien) | Manuelle Diagnose-Skripte gegen einen echten Miniserver oder den laufenden Server. Keine automatisierten Tests. Viele enthalten fest kodierte UUIDs und IPs der Entwickler-Anlage. |
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
(`jdev/sps/io/<uuid>/<cmd>`) oder, bei AudioZone-Befehlen mit bekannter
`playerid`, an den Audioserver auf Port 7091.

### 3.2 Start

`main()` (`webvisu.py:3036`) liest `--port` bzw. `LOXPANEL_PORT` (Default 8099),
baut `App(_config(), _audio_config())`, registriert alle Routen und startet beim
`on_startup` zwei Dauer-Tasks: `stream_task()` (Miniserver-Verbindung) und
`broadcaster()` (Verteilung). Der HTTP-Server ist sofort erreichbar, auch ohne
Miniserver-Zugang. So bleibt `/settings` immer bedienbar.

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
| `icon_cache` | unbegrenzter Cache für Loxone-Icons |
| `last_mode` | zuletzt gesetzter Betriebsmodus |

Achtung: `op_modes` wird nicht in `__init__` angelegt, sondern erst in
`_apply_structure()`. Zugriffe vor der ersten Strukturladung brauchen `getattr`.

### 3.4 Verbindung und Reconnect

- `App.start()` (`:414`): Client bauen, `getkey2`, `authenticate` (JWT), Struktur
  laden, Icon-Session anlegen, WebSocket öffnen.
- `stream_task()` (`:2409`): Endlosschleife. Bei Fehler wird das Token erneuert,
  scheitert das, wird die Verbindung hart zurückgesetzt. Danach feste 10 s Pause,
  kein Backoff.
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
| `theme` | `vars`, `tabs`, `tabMeta`, `title`, `lang`, `fill` | einmalig nach Verbindungsaufbau: CSS-Variablen, Tab-Leiste, Sprache |
| `view` | `title`, `tab`, `route`, `items[]` **oder** `blocks[]`, `layout`, `anchor`, `secured` | eine komplette Ansicht |
| `ring` | `id` | Klingel: Panel springt auf die Intercom-Seite |
| `alarm` | `id`, `on` | Weckton starten/stoppen |
| `testtone` | | Testton |
| `switch` | `panel` | Betriebsmodus: Seite mit neuem Profil neu laden |
| `reload` | | `location.reload()` |
| `goto` | `route` | auf eine Seite springen |
| `notify` | `text`, `level`, `secs` | Einblendung |
| `cmdresult` | `ok` | Ergebnis eines PIN-gesicherten Befehls |
| `display` | `on` | Display über die Kiosk-App aus- oder einschalten |
| `setdevice` | `name` | Gerät wurde in den Einstellungen benannt: Visu merkt sich den Namen und verbindet neu |

Browser → Server (`ws_handler`, `webvisu.py:2991`):

| `t` | Inhalt |
|---|---|
| `nav` | `route` (z. B. `{"view":"tab","tab":"raeume"}` oder `{"view":"control","id":uuid}`) |
| `cmd` | `uuid`, `cmd`, optional `pin` |

### 3.7 Das Block-Vokabular

Detailseiten bestehen aus `blocks[]`, jeder mit einem Schlüssel `k`. Frontend und
Server teilen dieses Vokabular, es ist aber nirgends formal spezifiziert:

`hero`, `cover`, `video`, `web`, `status`, `title`, `value`, `big`, `astat`,
`slider`, `row` (mit `cells`, Varianten `transport`, `wrap`, `hidden`), `head`,
`favs`, `alarmlist`, `more`. Zellen innerhalb `row`: `cmd`, `hold`+`release`,
`menu`, `icon`, `big`, `on`, `label`.

Kachelseiten bestehen aus `items[]` mit `id`, `label`, `sublabel`, `room`,
`icon|iconUrl|iconImg`, `on`, `tone`, `color`, `style`, `nav` oder `cmd`,
`controls[]`, `secured`.

Ein Tippfehler im Server erzeugt stumm eine leere Seite.

---

## 4. HTTP- und WebSocket-Schnittstelle

Alle Routen werden in `main()` (`webvisu.py:3044`) registriert. Es gibt keine
Authentifizierung, keine Middleware, kein CORS. Jeder im Netz kann alles.

| Methode | Pfad | Handler | Zweck | Genutzt von |
|---|---|---|---|---|
| GET | `/` | `index` | `panel.html` | Visu |
| GET | `/config` | `config_index` | `config.html` | Konfigurator |
| GET | `/settings` | `settings_index` | `settings.html` | Einstellungen |
| GET | `/i18n.js` | `i18n_js` | Übersetzungskatalog | Konfigurator, Einstellungen |
| GET | `/install-agent.sh` | `install_script` | Installer als Text | Panel-Installation |
| GET | `/api/meta` | `api_meta` | Räume, Kategorien, alle Controls, Icons, Profile, Geräte, Theme | Konfigurator, Einstellungen |
| POST | `/api/panels` | `api_save_panels` | `panels.json` schreiben, danach `reload` an alle Panels | Konfigurator |
| POST | `/api/theme` | `api_save_theme` | `theme.json` schreiben, danach `reload` | Konfigurator |
| GET | `/api/settings` | `api_settings` | Miniserver-Status (ohne Passwort), Intercom-Liste | Einstellungen, LoxBerry-Widget |
| POST | `/api/settings/miniserver` | `api_settings_ms` | Zugang speichern, sofort `reconnect()` | Einstellungen, LoxBerry-Widget |
| POST | `/api/settings/intercom` | `api_settings_intercom` | Kamera-URL/Login je Intercom | Einstellungen |
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
| GET/POST | `/api/goto` | `api_goto` | Panels auf Control oder Tab schicken | Loxone, extern |
| GET/POST | `/api/notify` | `api_notify` | Nachricht einblenden | Loxone, extern |
| GET | `/icon?p=` | `icon_handler` | Loxone-Icon-Proxy, 24 h Cache | Visu, Konfigurator |
| GET | `/cover?u=` | `cover_handler` | Cover-Bild-Proxy, 60 s Cache | Visu |
| GET | `/mjpeg?id=` | `mjpeg_handler` | MJPEG-Relais der Türstation | Visu |
| GET | `/ws?panel=&device=` | `ws_handler` | Haupt-WebSocket | Visu |

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

Ein unter `/settings` gespeicherter Zugang hat also Vorrang vor Docker-Variablen.

### 5.2 `loxpanel.cfg`

| Sektion | Felder | Gelesen von |
|---|---|---|
| `miniserver` | `host`, `user`, `pass`, `port`, `verify_tls` | `_config()` |
| `intercom` | `{control-uuid: {url, user, pass}}` | `_intercom_config()` |
| `audio` | `host` (optional, sonst Auto-Erkennung aus Cover-URLs), `port` (7091), `enabled` | `_audio_config()` |

In der Beispieldatei stehen zusätzlich `loxone.poll_interval`, `mqtt`, `web`,
`lms` und `miniserver.msno`. Diese Sektionen wertet der Server **nicht** aus.

Geschrieben wird die Datei komplett neu durch `_write_cfg()`, nur über die beiden
Settings-Endpunkte. Passwörter liegen im Klartext.

### 5.3 `panels.json`

Gelesen von `load_panels()` und `load_devices()`, geschrieben über
`POST /api/panels` bzw. `POST /api/devices`. Struktur:

```jsonc
{
  "panels": {
    "wohnzimmer": {
      "title": "Wohnzimmer",                 // max. 40 Zeichen
      "tabs": ["favoriten", "raeume", "cat:<uuid>"],   // max. 4, leer = alle 4 Standard-Tabs
      "rooms": ["<uuid oder Namensteil>"],   // Whitelist, leer = alle
      "cats":  ["<uuid oder Namensteil>"],
      "hide":  ["<control-uuid>"],           // einzelne Kacheln ausblenden
      "ui": {
        "iconSize": 38, "nameSize": 18, "subSize": 15, "font": "Inter",
        "textColor": "#e8eaed", "bold": true, "lang": "de",
        "nudgeX": -6, "dpmsOff": 180, "reloadHours": 12,
        "cols": 4, "rows": 3, "fill": true,
        "overlay": {"mode": "both", "fill": 16, "bord": 55, "bw": 1}
      },
      "states": {"active": "#..", "good": "#..", "warn": "#..", "crit": "#.."},
      "tiles": {
        "<control-uuid>": {
          "bg": "#..", "border": "#..", "iconColor": "#..", "textColor": "#..",
          "font": "..", "bold": true, "italic": false,
          "icon": {"src": "builtin", "id": "bulb"},   // oder {"src":"loxone","p":"..svg"}
          "overlay": {...}
        }
      }
    }
  },
  "devices": {
    "<Agent-Name>": {"auto": true, "modes": {"<Modusname>": "<panel-id>"}}
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
`_write_theme()` löscht `ui`-Keys, die nicht im Payload stehen.

---

## 6. Loxone-Bausteine

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
sichtbar, aber tot.

**Adapter:** `adapters.py` war als Erweiterungsmuster gedacht. Der Server nutzt
nur die zwei konkreten Klassen als Modul-Globals `LIGHT` und `JAL`. Die Registry
`get_adapter()` wird nicht abgefragt. Neue Typen gehören in die beiden Ketten,
nicht in einen Adapter.

---

## 7. Frontend

Drei Single-File-Seiten ohne Framework. Nur `config.html` und `settings.html`
laden `/i18n.js`; die Visu nicht.

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
- Kachelliste auf 400 Einträge begrenzt.
- Eigene Icon-Map `BICONS` (20 Icons, `fan` und `list` fehlen gegenüber der Visu).
- Overlay-Vorschau rechnet die Alphas selbst nach (`ovPreview()`), parallel zur
  Server-Logik `_overlay_alphas()`.

### 7.3 `settings.html` (Einstellungen, 452 Zeilen)

Sechs Bereiche: Miniserver, Intercom, SIP (nur Platzhalter), Panels (Agenten mit
Fernstart, Polling alle 6 s, plus Betriebsmodus-Automatik), Audio (Testton),
Neues Panel (erzeugt nur lokal den SSH-Befehl). Kein Dirty-Flag, ungespeicherte
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
wenn sie in Fully Kiosk läuft. Einrichtung in `deploy/ANDROID.md`.

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
auf Unraid nur über `/settings` und den appdata-Ordner.

### 9.3 Build und Release

| Workflow | Trigger | Ergebnis |
|---|---|---|
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
neuer POST-Handler, `settings.html`, `i18n.js`. Bei Env-Override zusätzlich
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
Defaults in `_theme_vars()`. Admin-Seiten haben ihr CSS doppelt in `config.html`
und `settings.html`, beide parallel ändern.

---

## 11. Bekannte Schwachstellen

### Fehler

| Nr. | Befund | Stelle |
|---|---|---|
| F1 | Routen `/gicon` und `/uicon` werden erzeugt, aber nie registriert | `webvisu.py:1598`, `:1601` |
| F2 | `op_modes` fehlt in `App.__init__` | `:394`, Workaround `:1235` |
| F3 | Push-Stellen fangen nur `ConnectionError`. Ein `RuntimeError` beim Senden würde den Broadcaster-Task beenden, alle Panels blieben stumm, ohne Log | `:2452-2467`, `:2797` |
| F4 | `icon_cache` unbegrenzt, kein Limit, keine TTL | `:359`, `:1139` |
| F5 | Kein atomares Schreiben der drei Config-Dateien (kein tmp+rename) | `:84`, `:1020`, `:1119` |
| F6 | `_write_cfg` und die Settings-Handler fangen `OSError` nicht | `:83`, `:2653`, `:2685` |
| F7 | `reconnect()` greift mit `ms["user"]` direkt zu, unvollständige cfg → `KeyError` | `:443` |
| F8 | `fetch_icon` hat kein Timeout und fängt `asyncio.TimeoutError` nicht | `:1123` |
| F9 | `JSON.parse` im WebSocket-Handler ohne try/catch | `panel.html:701` |
| F10 | `esc()` in der Visu escapt keine Anführungszeichen, Ausgabe landet in Attributen. Freitext-Schriftarten und Miniserver-Namen mit `"` zerlegen das Markup | `panel.html:316`, `:631`, `:637` |
| F11 | Panel-`states`-Farben werden nicht validiert und landen direkt in `setProperty` | `webvisu.py:979` |
| F12 | `updatePanel()` mappt Blöcke per Index und erstem Treffer, zwei `status`-Blöcke aktualisieren das falsche Element | `panel.html:550-574` |
| F13 | Agent-State-Datei in root-eigenem Verzeichnis, Panel-Wahl überlebt vermutlich keinen Reboot | `agent/loxpanel-agent.py:111`, `install-agent.sh:33` |
| F14 | `requests` wird von drei Skripten importiert, steht aber nicht in `requirements.txt` | `cover_test.py`, `proxy_test.py`, `loxone_client.py` |

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
- W8: Keine automatisierten Tests, kein Linter im CI. Gut testbare reine
  Funktionen: `_fmt_num`, `_color_parse`, `_alarm_next_text`, `_alarm_entries`,
  `_audio_favs`, `_tracker_lines`, `_resolve_ids`, `_sanitize_panels`,
  `LoxoneWS._parse_values/_parse_texts`.

### Doku-Inkonsistenzen

- README-Changelog endet bei 0.2.6, Plugin steht auf 0.3.1.
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
   Token, das `/config`, `/settings` und die schreibenden `/api/*`-Routen
   schützt, während `/`, `/ws` und die Bild-Proxys frei bleiben. Alternativ ein
   Reverse-Proxy mit Auth auf Unraid, dann muss der Installer-Befehl in
   `settings.html` HTTPS können.
6. **Cover-Proxy einschränken** (S2). Nur Hosts zulassen, die als Miniserver
   oder Audioserver bekannt sind.
7. **Agent-Kopie aus dem Installer entfernen** (W2). Der Installer kann die
   Datei per `curl` vom Server holen, wenn der Server `agent/loxpanel-agent.py`
   zusätzlich ausliefert. Dann gibt es nur noch eine Quelle.
8. **Tests für die reinen Funktionen** (W8) plus ein Lint-Job im Workflow, bevor
   größere Umbauten beginnen.
9. **Altlasten entfernen** (Abschnitt 12), sobald klar ist, wie eng der Fork dem
   Upstream folgen soll.
10. **Bausteinketten aufteilen** (W1). Eine Tabelle `Typ → (kachel_fn,
    detail_fn)` statt der `elif`-Kette macht neue Bausteine zu einer Datei pro
    Typ, ohne das Protokoll zu ändern.
