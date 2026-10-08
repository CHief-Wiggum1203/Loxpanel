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
| `bin/loxone_ws.py` | Loxone-WebSocket-Client: Token-Handshake, Binärparsing der Value-, Text- und Wetter-Tabellen. Nicht behandelte Kennungen werden einmal pro Verbindung protokolliert. Lebenszeichen: Frist je Antwort, `keepalive` im Stream (Werte vom Aufrufer, §3.4) |
| `bin/adapters.py` | Nur `LightControllerV2Adapter` und `JalousieAdapter` werden genutzt. Die Adapter-Registry darin ist aufgegeben. |
| `bin/audioserver.py` | Backend für Loxone-Audioserver Gen1 / MS4H über WebSocket Port 7091 |
| `bin/audioserver_events.py` | Event-Client für Audioserver Gen2 (WebSocket Port 7091): Cover, Titel, Favoriten; Adressen aus der Struktur |
| `bin/front_info.py` | Front (Screensaver): iCal-Abo laden und parsen (`icalendar` + `python-dateutil`, löst Serientermine auf) und Wetter von Open-Meteo (kein API-Key, nur Koordinaten). Eigenständig, keine Fremdabhängigkeit. `webvisu.py` ruft `load_front()` im `front_task` (alle 15 Min) und pusht das Ergebnis als `{t:"front"}` an die Panels. Ein einzeln abgesagter, verschobener oder geänderter Serientermin (eigenes VEVENT mit derselben UID und `RECURRENCE-ID`) ersetzt sein ursprüngliches Auftreten. Bewusst nicht unterstützt ist `RANGE=THISANDFUTURE`: Die Ausnahme ersetzt nur ihr eines Auftreten, eine eigene RRULE an ihr bleibt unbeachtet. Abgeglichen wird in der Ortszeit des Servers. Trägt die Ausnahme einer ganztägigen Serie eine Uhrzeit (Exchange-Form), trifft sie ihr Original nur bei richtig eingestellter Zeitzone des Containers, sonst stehen beide da |
| `bin/loxone_weather.py` | Wetter vom Loxone-Wetterserver: rechnet die Wetter-Tabelle des Miniservers in genau die Form um, die `front_info.fetch_weather()` liefert, und hat damit Vorrang vor Open-Meteo. Wetterlage-Texte und Einheiten kommen aus der Struktur (`weatherServer`), nicht aus einer Tabelle im Code. Gibt `None` zurück, wenn sich die Daten nicht sicher beschriften lassen — dann bleibt Open-Meteo |
| `bin/theme_colors.py` | Leitet aus EINER Grundfarbe den ganzen Panel-Farbsatz ab (Flächen, Schrift, Icon- und Zustandsfarben) und rechnet jeden Wert gegen die Fläche nach, auf der er steht: Hauptschrift AAA, Rest AA, Grafik 3:1, dazu Deuteranopie und Protanopie. Liefert `None`, wenn eine Farbe kein tragfähiges Theme hergibt. Nur Standardbibliothek. Aufgerufen aus `_theme_vars()` |
| `bin/loxone_secure.py` | Verschlüsselte Befehle an den Miniserver (Command Encryption über HTTP, `jdev/sys/fenc`). Grundlage für die gesicherten Details (`App.secured_details()`), siehe Abschnitt 3.10. Braucht `cryptography`; fehlt das Paket, läuft der Server ohne diese Befehle weiter |
| `bin/sip_probe.py` | SIP-Prüfung der Türstation: OPTIONS über UDP, Anmeldung per Digest, Codecs aus dem SDP. Nur Standardbibliothek, siehe Abschnitt 3.10 |
| `bin/version_info.py` | Welcher Stand läuft: liest `bin/version.json` (Version, Commit, Bauzeit), die beim Bauen entsteht: in der APK schreibt sie `syncLoxpanelAssets` (Commit aus `LOXPANEL_COMMIT` oder Git), im Image das Dockerfile über `python bin/version_info.py schreiben` (Commit als Build-Argument aus `tests.yml`, Job `veroeffentlichen`). Ohne die Datei, also im Git-Checkout, Version aus `loxberry-plugin/plugin.cfg` und Commit aus Git. Die App packt bei jedem Update `bin/` neu aus, deshalb liegt die Datei dort |
| `webfrontend/html/panel.html` | Die Visu (Kacheln, Detailseiten, Screensaver mit Wetter + Terminen, PIN, Weckton) |
| `webfrontend/html/config.html` | Konfigurator mit den Rubriken „Übersicht", „Panel Configuration" (Panel-Assistent, Panels, Tabs, Räume, Kacheln, Design, Split-Player), „Displays" (Geräte & Ansicht, Betriebsmodus-Assistent und -Automatik, Display-Steuerung, Nachtmodus), „Settings" (Miniserver, Kamera / Türstation, SIP, Audio, Kalender & Wetter, Neues Panel, Sicherung) und „unterstützte Geräte" |
| `webfrontend/html/settings.html` | Nur noch Weiterleitung nach `/config`, ohne Anker: der Konfigurator wertet keinen aus |
| `webfrontend/html/i18n.js` | Übersetzungskatalog de/en für Konfigurator und Einstellungen |
| `agent/loxpanel-agent.py` | Panel-Agent auf dem Wandpanel |
| `deploy/install-agent.sh` | Installer für den Agenten. Enthält den Agent-Quelltext als eingebettete Kopie. |
| `config/*.example` | Vorlagen für `loxpanel.cfg`, `panels.json`, `theme.json` |
| `loxberry-plugin/` | LoxBerry-Plugin (Docker-Starter, Widget, Backup) |
| `unraid/loxpanel.xml` | Unraid-Docker-Template |
| `android/` | LoxPanel-App für Android (Lenardos #61, Paket `com.loxpanel.spike`): Kotlin mit Chaquopy, der Server läuft im Gerät (`ServerService`), die Visu in einer eigenen Vollbild-WebView (`KioskActivity`) mit der JS-Brücke `LoxKiosk` (siehe Abschnitt 8). Der Gradle-Task `syncLoxpanelAssets` kopiert vor jedem Build `bin/`, `webfrontend/`, `deploy/` und `config/` (ohne die echten Config-Dateien) aus dem Arbeitsbaum in die App. Bauen, Signieren und Einrichten: `android/README.md` |
| `packaging/deb/` | `.deb`-Paket für Linux-Panels (Lenardos #62): Server als systemd-Dienst, Kiosk-Start mit Chromium oder Cog, Display-Abschaltung. Im Fork nicht weiterentwickelt ([`TODO.md`](TODO.md), Block 0c) |
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
der Ereignis-Client je Host vor dem Verbinden (`audioserver_events.py`,
`_check_paired()`, HTTP `audio/cfg/all`): Steht „not allowed when paired" in der
Antwort, ist er gekoppelt, gleich mit welchem HTTP-Status. 5xx, 408, 429,
Zeitlimit und Verbindungsfehler sagen nichts über die Kopplung, der bisherige
Wert bleibt. Jede andere Antwort heißt nicht gekoppelt; Nachbauten und
Musikserver Gen 1 antworten nicht einheitlich (auch 404 oder leer), deshalb gibt
es kein strengeres Kriterium. Solange der Status unbekannt ist, gilt der
Audioserver wie gekoppelt ohne Anmeldung: Befehle und Favoriten laufen über den
Miniserver, auf dem Ereigniskanal wird nur gehört, und die Prüfung wiederholt
sich alle `audiometa.retry_interval` Sekunden. Ergibt sie „gekoppelt", baut der
Client die Verbindung sofort neu auf und meldet sich an; ergibt sie „nicht
gekoppelt", fordert er die Favoriten über 7091 an. Bis der Audioserver als
gekoppelt erkannt ist, läuft die Prüfung vor jedem Verbinden; so heilt ein
falsches „nicht gekoppelt": Ein gekoppelter Audioserver schließt den Kanal beim
ersten Befehl ohne Anmeldung. Ein erkanntes „gekoppelt" bleibt dagegen bis zum
nächsten Start des Clients. Es entsteht nur aus dem Kopplungstext, und eine
Antwort beim Hochfahren des Audioservers (404, leer) würde es sonst kippen;
Transportbefehle gingen dann ohne Anmeldung an 7091 und ins Leere.
`roomfav/get` bleibt immer am Miniserver (füllt den `sourceList`-State
für die Anzeige). Ausnahme roomfav/play: bei einem gekoppelten Loxone-Audioserver
läuft `roomfav/play/<slot>` über die angemeldete Ereignis-Verbindung
(`play_roomfav`), weil der unangemeldete Direktkanal solche Befehle ablehnt;
Nachbauten (`authed=false`) nutzen den Direktkanal. Ist die Ereignis-Verbindung
dabei schon weg, meldet `play_roomfav` das, und die Visu zeigt wie bei anderen
gescheiterten Befehlen einen Hinweis.
Titel, Sender und Cover für `AudioZoneV2` kommen über den
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
| `conn_info` | je Browser-WebSocket: Gerätekennung, Kiosk-App (`fully` oder `loxpanel`, `KIOSK_APPS`), IP, Verbindungszeit; Basis von `device_list()` |
| `panels`, `devices` | aus `panels.json` |
| `agents` | `ip → Agent-Datensatz` (Announce, mit `features`) |
| `agent_wunsch` | `ip → Profil`, das ein Agent mit seiner nächsten Meldung übernehmen soll (Displays, Betriebsmodus); fällt weg, sobald er es meldet |
| `bell_map`, `alarm_map` | State-UUID → Control für Klingel- und Wecker-Flanken |
| `icon_cache` | Cache für Loxone-Icons, höchstens `ICON_CACHE_MAX` (500) Einträge, der am längsten unbenutzte fliegt zuerst |
| `last_mode` | zuletzt gesetzter Betriebsmodus |
| `ansicht_gewaehlt` | Geräte, deren Ansicht unter Displays gewählt wurde („Ansicht wechseln“ oder „Start“): `ws_handler()` zieht sie nicht auf `last_mode`, bis der Betriebsmodus wieder wechselt |

`op_modes` (Betriebsarten) ist ab `__init__` ein leeres Dict und wird in
`_apply_structure()` gefüllt; `/api/types` funktioniert damit auch ohne Miniserver.

### 3.4 Verbindung und Reconnect

- `App.start()` (`:414`): Client bauen, `getkey2`, `authenticate` (JWT), Struktur
  laden, Icon-Session anlegen, WebSocket öffnen.
- `stream_task()` (`:2409`): Endlosschleife. Bei Fehler wird das Token erneuert,
  scheitert das, wird die Verbindung hart zurückgesetzt. Danach wachsende Pause
  (`MS_RETRY`: 5, 10, 20, 40, 60 s). Von vorn beginnt sie erst, wenn eine
  Verbindung mindestens 60 s lang Nachrichten lieferte (`LoxoneWS.lebenszeit()`,
  Anmeldung bis letzte Nachricht) — ein Miniserver, der sofort wieder trennt
  oder nach der Anmeldung schweigt, bekommt so nicht alle paar Sekunden eine
  neue Anmeldung. Wie lange die Verbindung bloß offen war, zählt nicht: Eine
  stumme endet erst nach `keepalive_interval` + `response_timeout` (Standard
  70 s), also nach mehr als `MS_RETRY[-1]`.
- **Lebenszeichen der Live-Verbindung:** Nach der Anmeldung sendet LoxPanel auf
  dem WebSocket sonst nichts (Befehle gehen über HTTP). Ein still abgerissener
  Socket (Strom, WLAN, NAT ohne RST) oder ein Miniserver, der annimmt und
  schweigt, blieb deshalb unbemerkt hängen: `stream_task` wartete für immer,
  die Panels zeigten eingefrorene Werte. Jetzt haben Verbindungsaufbau,
  `getkey` und `authwithtoken` je die Frist `miniserver.response_timeout`
  (`_ms_antwortfrist()`), und `stream()` sendet alle
  `miniserver.keepalive_interval` Sekunden (`_ms_keepalive_abstand()`,
  Standard `MS_KEEPALIVE` = 60 s) `keepalive`. Der Miniserver antwortet mit
  einem Header der Kennung 6 (Loxone-Doku „Communicating with the Miniserver“,
  „Keeping the connection alive“); das Log meldet einmal je Verbindung
  „Miniserver beantwortet keepalive“. Kommt `keepalive_interval` +
  `response_timeout` lang keine Nachricht, endet `stream()` mit
  `ConnectionError` und `stream_task` verbindet neu. Die Grenze gilt je
  Nachricht, auch für den Voll-Dump nach der Anmeldung, der im LAN einen
  Bruchteil davon braucht. Laut Doku trennt der Miniserver außerdem Clients,
  die über 5 Minuten nichts senden; an der eigenen Anlage hielt der WebSocket
  aber auch ohne `keepalive` tagelang. `/api/health` bleibt dabei, wie es ist:
  Ein fehlender Miniserver ist kein Fehler (§4).
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
  einen Fehlversuch. Die Anmeldung (`getkey2`, `getjwt`) hat eine Frist,
  `miniserver.response_timeout` in `loxpanel.cfg`, Standard `MS_CMD_TIMEOUT`
  (`_ms_antwortfrist()`); das Laden der Struktur hängt an ihrer Größe und hat
  keine. `api_settings_ms` übergibt den zu prüfenden Zugang und schreibt erst
  danach (§5.1).
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
| `theme` | `vars`, `tabs`, `tabMeta`, `title`, `lang`, `fill`, `split`, `catFilter`, `tileLayout`, `gridAuto`, `gridGrow`, `panes`, `svPane`, `scale`, `dpmsOff`, `pinMerken`, `reloadHours`, `reloadAt`, `night`, `agent`, `presence` | einmalig nach Verbindungsaufbau: CSS-Variablen, Tab-Leiste, Sprache, Sprungmarken springen oder filtern, Kachel-Aufbau, beim automatischen Raster die Zielkachel in px (`gridAuto`, Gerät vor Profil über `effective_grid_auto()`, 0 = festes Raster, §7.1) und bis zu welchem Vielfachen die Kacheln wachsen, wenn alle auf eine Seite passen (`gridGrow` = `KACHEL_WACHSEN`), Split-Panes je Tab, die rechte Spalte der Uhr-Seite, die wirksame Skalierung (Gerät vor Profil vor global, `effective_scale()`) und die Display-Einstellungen ohne Agent: Leerlaufzeit, Auto-Neustart (`reloadHours`, `null` ohne Eintrag: dann nachts um `reloadAt` Uhr), Nachtmodus, ob ein Agent das Display übernimmt, und ob der Präsenzmelder des Geräts gerade jemanden meldet (`presence`, dann schaltet der Leerlauf nicht ab). `pinMerken`: so viele Sekunden behält die Visu eine bestätigte PIN (0 = jedes Mal fragen) |
| `view` | `title`, `tab`, `route`, `items[]` **oder** `blocks[]`, `layout`, `anchor`, `secured`, `front`, `leiste[]` | eine komplette Ansicht. `leiste` (nur auf Seiten aus `ui.valueBar`): die Anzeige-Bausteine der Seite als Werteleiste über dem Raster, gleiche Form wie `items`, dort fehlen sie dann (§7.1 „Werteleiste“). `front` (`calendar`/`weather`) bei den Tabs `kalender`/`wetter`: `items` ist leer, das Panel zeichnet die Seite aus den zuletzt empfangenen `front`-Daten (`renderFrontTab()`) und neu, sobald neue kommen |
| `ring` | `id` | Klingel: Panel springt auf die Intercom-Seite |
| `alarm` | `id`, `on` | Weckton starten/stoppen |
| `testtone` | | Testton |
| `switch` | `panel` | Betriebsmodus: Seite mit neuem Profil neu laden |
| `reload` | | `location.reload()` |
| `goto` | `route` | auf eine Seite springen |
| `notify` | `text`, `level`, `secs` | Einblendung |
| `einrichtung` | `aktiv`, dazu bei `aktiv`: `titel`, `grund`, `hinweis`, `pfad`, `adressen[]`, `unbekannt` | Einrichtungshinweis, solange der Server keine Struktur vom Miniserver hat und entweder kein Zugang eingetragen ist oder der letzte Versuch scheiterte (`_einrichtung_stand()` nach `_einrichtung_info()`, Fehlertext aus `stream_task`, höchstens `EINRICHTUNG_FEHLER_MAX` Zeichen). Beim Verbinden und bei jeder Änderung (`_einrichtung_melden()`). Die Visu setzt die Adresse des Konfigurators zusammen: die, über die sie geladen wurde, bei `127.0.0.1` (App auf dem Panel) eine aus `adressen` (`_lan_adressen()`: Quelladresse der Standardroute, ohne Paket) |
| `cmdresult` | `ok`, `code`, `uuid`, `cmd` | Ergebnis eines PIN-gesicherten Befehls. `uuid` und `cmd` ordnen es dem Befehl zu (Drücken und Loslassen einer Halten-Taste kommen kurz hintereinander), `code` `null` heißt „keine Antwort“, nicht „PIN falsch“ |
| `display` | `on`, optional `presence` | Display über die Kiosk-App aus- oder einschalten. `presence` kommt vom Präsenzmelder des Geräts (§8): solange `true`, schaltet der Leerlauf nicht ab |
| `front` | `weather` (`temp`, `cond`, `icon`, `hi`, `lo`, `wind` + `wind_unit`, `forecast[]`), `events[]` (`day`, `time`, `title`), `calName` | Kalender + Wetter für den Screensaver; beim Verbinden und alle 15 Min bzw. nach dem Speichern (`front_task`) — oder sofort, wenn der Miniserver neues Wetter schickt (§3.8) |
| `scale` | `scale` (`"off"` \| `"auto"` \| Faktor) | Skalierung live umstellen, gesendet nach `POST /api/devices` an alle verbundenen Panels — ohne Neuladen |
| `energy` | `control`, `name`, `nodes[]`, `totals` (`prod`, `cons`, `grid`) | Energiefluss-Pane (Pane 2, Widget-Seite, Uhr-Seite); nach `setenergy` und bei jeder Änderung, die der Broadcaster sieht (`energy_blocks()`) |
| `camera` | `blocks[]` | Kamera-Pane: die Intercom-Ansicht ohne `more` und ohne die Zeile `klingel` (Klingel abstellen, verpasste Klingeln); nach `setcamera` und bei jeder Änderung (`intercom_blocks()`) |
| `player` | `blocks[]` | Player-Pane: die Blöcke der Audio-Zone ohne `more`; nach `setplayer` und bei jeder Änderung (`player_blocks()`) |
| `chart` | `controls[]`, `range`, `ranges[]`, `charts[]` (je Baustein `control`, `name`, `value`, `blocks[]` mit Blöcken `chart`, §3.7) | Verlaufs-Pane (Pane 2, Widget-Seite, Uhr-Seite) mit einem oder mehreren Bausteinen; nach `setchart` und bei jeder Änderung, die der Broadcaster sieht (gebaut in `chart_stack()`, je Baustein `chart_blocks()`). `controls` nennt nur Bausteine mit Aufzeichnung. Die Visu verwirft eine Nachricht, die Bausteine außerhalb ihrer Anfrage nennt (ein Push, der beim Wechsel schon unterwegs war), und der Broadcaster schickt keine, wenn die Verbindung nach dem Berechnen einen anderen Stapel angemeldet hat |
| `svstatus` | `items[]` (dieselbe Form wie Kachel-`items`, ohne `nav`/`controls`) | Werte der frei gewählten Bausteine für die rechte Spalte der Uhr-Seite; gebaut in `status_blocks()` über `_control_item()`, also dieselbe Kette wie jede Kachel |
| (Browser → Server) `idle` | | Visu ohne Kiosk-JS meldet Leerlauf nach `dpmsOff`; Server schaltet über den Display-Treiber aus |
| `setdevice` | `name` | Gerät wurde in den Einstellungen benannt: Visu merkt sich den Namen und verbindet neu |

Browser → Server (`ws_handler`, `webvisu.py:2991`):

| `t` | Inhalt |
|---|---|
| `nav` | `route` (z. B. `{"view":"tab","tab":"raeume"}` oder `{"view":"control","id":uuid}`). Unterseiten einzelner Bausteine: `{"view":"irrzone","id","zone"}` (Zone einer Bewässerung), `{"view":"alarmentry","id","entry"}` (Weckzeit, `entry` leer = neue), `{"view":"alarmsettings","id"}` (Einstellungen eines Weckers), `{"view":"bells","id"}` (verpasste Klingeln), siehe §6 |
| `cmd` | `uuid`, `cmd`, optional `pin` |
| `screen` | `vw`, `vh` (sichtbare Fläche, CSS-px), `sw`, `sh` (Bildschirm laut Gerät), `dpr` (Pixeldichte), `bw`, `bh` (ungeskalierter Kasten der Visu), `k` (wirksamer Faktor), `rc`, `rr` (Spalten und Zeilen der Kachelansicht, beim automatischen Raster das Ergebnis). Beim Verbinden, nach jeder Größenänderung und nach jedem Neuaufbau des Rasters, entprellt und nur bei Änderung. Nur zur Anzeige unter Displays; geprüft in `_clean_screen()`, abgelegt in `conn_info[ws]["screen"]` |
| `setchart` | `uuid`, `range` — Bausteine (komma-getrennt, getrimmt, höchstens `SV_STATUS_MAX`) und Zeitraum der Verlaufs-Pane des aktiven Tabs bzw. der Uhr-Seite (`uuid` leer = keine). Der Server antwortet sofort mit `chart` und hält den Stand je Verbindung (`conn_chart`: Bausteine als Tupel, Zeitraum) |
| `setsvstatus` | `uuids[]` — die Bausteine der Status-Spalte auf der Uhr-Seite (leer = keine). Der Server antwortet sofort mit `svstatus` und hält den Stand je Verbindung (`conn_status`) |
| `setenergy` | `uuid` — EFM oder EnergyManager2 der Energiefluss-Pane des aktiven Tabs bzw. der Uhr-Seite (leer = keine). Der Server antwortet sofort mit `energy` und hält den Stand je Verbindung (`conn_energy`) |
| `setcamera` | `uuid` — Intercom der Kamera-Pane (leer = keine). Antwort `camera`, Stand in `conn_camera` |
| `setplayer` | `zone` — Audio-Zone der Player-Pane (leer = keine). Antwort `player`, Stand in `conn_player` |

Die `set*`-Nachrichten sind Abos. Der Server hält sie je Verbindung und räumt
sie ab, wenn die Verbindung endet (`ws_handler`, `_send_or_drop()`). Die Visu
merkt sich, was sie gemeldet hat (`curEnergyUuid`, `curCameraUuid`,
`curPlayerZone`, `curSvStatus`, `curChartKey`), und `applyPane()` meldet nur
Änderungen. Nach jedem Verbindungsaufbau vergisst sie diesen Stand
(`abosVergessen()` in `ws.onopen`), und der `theme`-Push, der als Erstes kommt,
meldet über `applyPane()` alle aktiven Abos neu an. Ohne das blieb nach einem
Neustart des Servers, einem Netzabbruch oder dem Benennen eines Geräts jedes
Widget auf dem letzten Stand stehen. Ein neues Abo mit eigener Kennung gehört
in `abosVergessen()`. Geprüft in `tests/browser/test_abo_neuverbindung_browser.py`.

### 3.7 Das Block-Vokabular

Detailseiten bestehen aus `blocks[]`, jeder mit einem Schlüssel `k`. Frontend und
Server teilen dieses Vokabular, es ist aber nirgends formal spezifiziert:

`hero`, `cover`, `video`, `web`, `status`, `title`, `value`, `big`, `astat`,
`slider`, `row` (mit `cells`, Varianten `transport`, `wrap`, `hidden`), `head`,
`favs`, `alarmlist`, `chart`, `more`, `stepper`, `field`, `timepick`, `chips`,
`gallery`. Zellen innerhalb `row`: `cmd`, `hold`+`release`, `menu`, `icon`,
`big`, `on`, `label`, `nav`, `form`, `confirm`, `back`.

- `alarmlist`: Einträge mit `name`, `hm`, `active`, `repeat`; mit `cmd` steht
  vorn ein Schalter (schaltet, öffnet nichts), mit `nav` öffnet ein Tipp auf die
  Zeile die Unterseite.
- `stepper`: Wert mit −/+ (`label`, `value`, `step`, `min`, `max`, `fmt`
  `dauer` oder `prozent`, `sub`). Ohne `cmd` nur Anzeige. Die Visu zählt selbst
  und schickt `cmd.tmpl` mit `{v}` erst, wenn 0,9 s niemand tippt
  (`STP_SENDEN_MS`); gedrückt halten zählt weiter.
- Formular: `field` (Text), `timepick` (Uhrzeit in Sekunden ab Mitternacht) und
  `chips` (Auswahl, `multi` für mehrere) tragen je einen `name`. Eine Zelle mit
  `form` (`uuid`, `tmpl`) setzt beim Tippen deren Werte für `{name}` ein: Text
  URL-kodiert, Auswahl mit Komma. Ist ein Feld leer oder nichts gewählt, bleibt
  sie gesperrt. Die Werte gehören der Visu, bis gespeichert ist; Updates vom
  Server ändern sie nicht.
- Zellen mit `nav`, `form`, `confirm` oder `back` wirken beim Tippen (`click`),
  nicht beim Aufsetzen des Fingers. `confirm` fragt beim ersten Tipp nach,
  `back` geht nach dem Befehl eine Seite zurück.
- `gallery`: Bilder (`src`, `label`); ein Tipp zeigt eins groß.

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
   Rohdaten je UUID ab und weckt die Front sofort. Die baut sich dann aus dem
   letzten Stand mit dem neuen Wetter neu (`_front_nur_wetter()`). Kalender und
   Open-Meteo holt `front_task` nur im 15-Minuten-Takt (`FRONT_INTERVAL`) oder
   nach dem Speichern. Früher löste jede Wetter-Änderung auch einen
   Kalenderabruf aus, und iCloud sperrte das Abo mit 503 und `Retry-After`.
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

- **Verlaufs-Pane** (`panes`: `chart:<uuid>,…`): zweite Hälfte im Split-Layout (quer rechts, hochkant unten)
  mit einem oder mehreren Bausteinen (Upstream #77), je Baustein Name, aktueller
  Wert und Diagramme (`.cpsec`), wie beim Energiefluss über `setchart` angemeldet
  und vom Broadcaster aktualisiert. Die Zeitraum-Knöpfe stehen einmal oben
  (`.cpr`), gelten für alle Bausteine und melden nur den Zeitraum neu
  (`setchart`), die Kachelseite links bleibt. Ab zwei Bausteinen bekommt die
  Seite `.stack`: nur der Bereich mit den Bausteinen (`.cpbody`) scrollt, jedes
  Diagramm in seinem Seitenverhältnis, die Leiste bleibt stehen. Im
  Konfigurator wählt man die Bausteine als Chips, in der gewählten
  Reihenfolge.
  Seit Upstream #60 teilen sich die Diagramme dort (und auf einer Widget-Seite)
  die Höhe der Pane, statt unten aus ihr herauszuragen: Die Seite ist eine
  Flex-Spalte, jedes Diagramm bekommt `flex:1`, das SVG
  (`preserveAspectRatio="none"`) füllt seine Fläche in voller Breite und wird
  dafür leicht verzerrt (mit einem Baustein; im Stapel scrollt die Pane, siehe
  oben). Diese Regeln gelten nur im `#frontpane`. Die Uhr-Seite
  zeichnet denselben Baustein (`renderChartPane()`), hochkant ist ihre Box aber
  so hoch wie ihr Inhalt, und Diagramme mit `flex-basis: 0` fielen dort auf 0 px
  zusammen. Auf der Uhr-Seite stehen die Diagramme deshalb im
  Seitenverhältnis der Zeichnung (440:150), solange der Kasten reicht. Reicht er
  nicht (quer hat er eine feste Höhe, hochkant bleibt die Fläche unter Uhr und
  Wetter), schrumpfen sie (`flex:0 1 auto`), statt unten abgeschnitten zu
  werden, etwa bei drei Diagrammen eines Zählers oder in einem niedrigen
  Fenster. Die Hüllen um die Diagramme (`.cpbody`, je Baustein `.cpsec`, seit
  #77) schrumpfen mit; ohne sie ragten drei Diagramme bei 960 × 480 um 144 px
  heraus. Mehrere Bausteine teilen sich dort den Kasten, statt zu scrollen: Jede
  Berührung schließt den Bildschirmschoner. Geprüft in
  `test_split_haelfte_und_kachel` und `test_split_hochkant_uebereinander` (kein
  Überlauf), `test_uhrseite_hochkant_zweite_flaeche_unten` (Seitenverhältnis
  quer und hochkant), `test_uhrseite_verlauf_schrumpft_statt_abzuschneiden`
  (drei Diagramme quer und hochkant, zwei bei 960 × 400, zwei Bausteine mit fünf
  Diagrammen: nichts abgeschnitten), `test_verlauf_pane_stapelt_mehrere_bausteine`
  (Stapel scrollt, Leiste fest) und `test_verlauf_pane_verwirft_fremden_stapel`
  bzw. `test_veralteter_stapel_kommt_nicht_hinterher` (nach einem Wechsel kein
  Diagramm des vorigen Stapels).
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

### 3.10 Gesicherte Details und SIP-Prüfung

Zugangsdaten, die zu einem Baustein gehören, gibt der Miniserver nur auf einen
verschlüsselten Befehl heraus: `jdev/sps/io/{uuid}/securedDetails`. Bei der
Intercom sind das Kamera (`videoInfo`) und SIP (`audioInfo`: `host`, `user`,
`pass`). Ob ein Baustein welche hat, steht in der Struktur: das Kennzeichen
`securedDetails` am Control (Strukturdoku, Controls, „indicates that there is
sensitive information available“). Ohne das Kennzeichen fragt
`App.secured_details()` gar nicht erst und meldet `OhneGesicherteDetails`
(eine Unterart von `ZugangFehler`). Sonst folgt es der Loxone-Doku
„Communicating with the Miniserver“ 16.0, Abschnitt Command Encryption,
Variante für HTTP:

1. `jdev/sys/getPublicKey` liefert den RSA-Schlüssel des Miniservers, als PEM
   mit der Beschriftung CERTIFICATE, aber mit einem SubjectPublicKeyInfo darin.
   Die App behält ihn (`_ms_pubkey`); `start()` und `reconnect()` verwerfen ihn.
2. `jdev/sys/getkey` liefert den Schlüssel für den Token-Hash. Die Anmeldung
   steckt im Befehl selbst: `?autht={HMAC(Token)}&user={Benutzer}`, mit SHA1
   oder SHA256 wie bei der WebSocket-Anmeldung (`getkey2`).
3. `loxone_secure.encrypt_command()`: `salt/{salt}/{cmd}` mit AES-256-CBC,
   Nullbytes als Ende und Auffüllung; `{key}:{iv}` mit RSA PKCS#1 v1.5. Daraus
   wird `jdev/sys/fenc/{chiffre}?sk={sitzungsschluessel}`.
4. Mit `fenc` verschlüsselt der Miniserver auch die Antwort (Base64, derselbe
   Schlüssel und IV), `decrypt_response()` macht sie wieder lesbar.

Neuversuche: HTTP 401 heißt „Befehl nicht zu entschlüsseln“, meist ein neuer
Schlüssel nach einem Neustart. Dann holt die App ihn einmal neu. LL-Code 401
heißt „Token abgelaufen“, dann meldet sie sich über `_renew_token()` neu an,
aber nicht öfter als `TOKEN_RENEW_MIN`. Alles andere wird zu `ZugangFehler` mit
einem Satz, den der Konfigurator zeigt: 403 nennt die Rechte in Loxone Config.

`_sip_zugang()` nimmt daraus `audioInfo` (`App.intercom_sip()` für die
Prüfung). Der Reiter SIP listet beide Türsprechstellen-Typen (`INTERCOM_TYPES`):
`Intercom`, in Loxone Config die Türsteuerung („Door Controller“, auch mit einer
benutzerdefinierten Intercom), und `IntercomV2`, den Baustein Intercom. `/api/sip`
nennt den Typ und vom Zugang nur Adresse, Benutzer und `hasPass`, denn die
Routen haben keine Anmeldung. Hat der Miniserver geantwortet, nennt aber keinen
SIP-Zugang, steht `ohneSip` in der Antwort; so unterscheidet der Konfigurator
das von einem Fehler bei Verbindung oder Rechten, ohne Fehlertexte zu
vergleichen. Hat der Baustein gesicherte Details ohne `host`, zeigt der Reiter
ihren Aufbau (`_gesichert_felder()`: Feldnamen und ob sie gefüllt sind, nie
Werte), etwa „videoInfo: streamUrl, user, pass · audioInfo: leer“. Daran sieht
man, ob der Miniserver überhaupt Audio kennt. Darunter steht, wo die Adresse
hingehört: am Baustein in Loxone Config, bei einer benutzerdefinierten Intercom
„Host für Audio (intern)“. Steht sie dort und fehlt trotzdem, gibt der
Miniserver sie für diesen Baustein nicht heraus, und der Hinweis sagt genau
das. Für die Loxone Intercom am Baustein Intercom (`IntercomV2`, `deviceType`
1) beschreibt die Strukturdoku 17.0 keinen SIP-Zugang, also auch keine
gesicherten Details; der Hinweis sagt auch das.
`/api/sip/pruefen` nimmt aus der Anfrage nur die `uuid`. Adresse und Zugang
kommen vom Miniserver, so geht die Anmeldung nur an die Türstation.

Die Kamera der Intercom kommt auf demselben Weg (`App.intercom_video()`, für
`/mjpeg`): Eine in LoxPanel eingetragene Adresse (Settings → Kamera /
Türstation, `loxpanel.cfg` `intercom`) hat Vorrang. Sonst nimmt LoxPanel
`videoInfo` aus den gesicherten Details (`_kamera_aus_details()`: `streamUrl`,
`user`, `pass`; eine Adresse ohne Schema, wie sie in Loxone Config steht, mit
`http://`). Das Ergebnis steht in `ms_video`, bis eine neue Struktur kommt
(nach dem Speichern in Loxone Config); zwei Panels zugleich fragen einmal
(`_video_sperre`). Ein Fehler bei Verbindung oder Rechten wird nicht gemerkt,
beim nächsten Mal fragt LoxPanel neu. Steht statt Host „cloudDNS“ oder
„remoteConnect“ in der `streamUrl`, ersetzt LoxPanel den Platzhalter wie die
Loxone-App (Strukturdoku 17.0, Intercom): „cloudDNS“ durch die Adresse des
Miniservers (der Port bleibt), „remoteConnect“ durch Host und Port des
Miniservers mit `https`; der Miniserver leitet das Kamerabild weiter. Die Detailseite zeigt
das Video, solange offen ist, ob der Miniserver eine Kamera nennt
(`_intercom_video_block()`); `/mjpeg` fragt ihn, setzt `_dirty`, und danach
stehen Bild oder Grund da.

`sip_probe.pruefen()` schickt ein OPTIONS (RFC 3261, Abschnitt 11) über UDP,
das bei der Türstation keinen Anruf auslöst:

- Ohne Antwort wiederholt es nach T1 = 0,5 s mit Verdopplung, bis `WARTEN`
  (4 s) um ist. Nach einer vorläufigen Antwort (1xx) wartet es ohne
  Wiederholung auf die endgültige.
- Antworten zählen nur mit derselben Call-ID und CSeq; fremde Pakete, auch
  leere, gehen unter.
- Auf 401/407 folgt ein zweites OPTIONS mit Digest (RFC 2617; SHA-256 nach
  RFC 8760; `-sess`; mit `qop=auth` oder in der alten Form ohne).
- Ein ICMP „Port unerreichbar“ (`ConnectionRefusedError` in
  `error_received`) beendet die Prüfung sofort mit „Port geschlossen“.
- Gegenstelle, erlaubte Methoden und die Codecs aus einem mitgeschickten SDP
  kommen ins Ergebnis.

Getestet wird gegen Nachbauten in `tests/lox.py`: Der Miniserver entschlüsselt
mit eigenem RSA-Schlüssel, und `SipTuer` rechnet die Anmeldung unabhängig nach.
Die Digest-Werte stammen aus den Beispielen von RFC 2617 und RFC 7616.

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
| GET | `/api/meta` | `api_meta` | Räume, Kategorien, alle Controls, Icons, Profile, Geräte (Display-Kennwort nur als `hasPass`, `_devices_export()`), Theme, Bausteine mit `active`-State (`activeControls`, Auswahl Präsenzmelder), Stunde des nächtlichen Neuladens (`reloadAt`) | Konfigurator, Einstellungen |
| POST | `/api/panels` | `api_save_panels` | `panels.json` schreiben, danach `reload` an alle Panels; die Antwort nennt unter `verworfen`, was `_sanitize_panels` nicht übernommen hat | Konfigurator |
| POST | `/api/theme` | `api_save_theme` | `theme.json` schreiben, danach `reload` | Konfigurator |
| GET | `/api/settings` | `api_settings` | Miniserver-Status (ohne Passwort), Intercom-Liste, Einrichtungsstand `einrichtung` (`_einrichtung_info()`: `stand` `kein_zugang`, `verbindet` oder `fehler`, dazu `host` und `fehler`; mit Struktur `null`), `version` (`version`, `commit`, `gebaut`; `version_info.lesen()`, Seitenleiste des Konfigurators) | Einstellungen, LoxBerry-Widget |
| GET | `/api/health` | `api_health` | Zustand: Hintergrund-Aufgaben (`miniserver`, `broadcaster`, `audio`, `front`), Miniserver verbunden, Zahl der Panels, Laufzeit, `version` wie bei `/api/settings`. 503, sobald eine Aufgabe beendet ist; ein fehlender Miniserver allein ist kein Fehler | Docker-`HEALTHCHECK` (Unraid) |
| GET | `/api/backup` | `api_backup` | ZIP mit `loxpanel.cfg`, `panels.json`, `theme.json`, Kennwörter (`pass`, `password`) leer, dazu `LIESMICH.txt` und `sicherung.json` (je Datei die Pfade der entfernten Kennwörter, für `/api/restore`). Nicht lesbares JSON bleibt draußen | Settings → Sicherung |
| POST | `/api/restore` | `api_restore` | Sicherung einspielen, Body = ZIP aus `/api/backup`. Immer nur eine zur Zeit. Erst alles prüfen, in einem Thread, damit die Visu bedienbar bleibt (`_sicherung_lesen`, `_sicherung_pruefen`: nur Deflate oder ungepackt, je Datei höchstens 2 MiB – auch so, wie sie danach geschrieben wird, damit sich der Stand wieder einspielen lässt –, höchstens 32 Ebenen tief und 200.000 Einträge, nur endliche Zahlen und gültiges Unicode, Typen der gelesenen Abschnitte von `loxpanel.cfg`, Profile, Geräte und globale `ui` durch dieselben Sanitizer wie beim Speichern), dann schreiben (vorher `.bak`) und ohne Neustart auffrischen (`_sicherung_schreiben`). Ein vorhandenes Kennwort bleibt nur bei gleichem Ziel (Host, URL, Benutzer, Treiber). Wo eines entfernt wurde, sagt `sicherung.json`, bei älteren Sicherungen die Liste in `LIESMICH.txt`. Ein laufender Zugang bleibt stehen, wenn die Sicherung keinen Miniserver hat oder ihrem Zugang Benutzer oder Kennwort fehlt, ebenso einer aus `LOXPANEL_MS_*`; neu verbunden wird nur bei geändertem Zugang, scheitert das, bleibt der alte (auch der aus `LOXPANEL_MS_*`). Antwort: `dateien`, `nichtEnthalten`, `nichtEingespielt` (nach einem Schreibfehler), `kennwoerter` (`behalten`, `fehlen`), `verworfen`, `miniserver`, `miniserverZiel`, `miniserverFehler`, `reloaded`; 400 bei kaputter Sicherung (nichts geschrieben), 500 nach einem Schreibfehler (Teilergebnis mit `error` und `nichtEingespielt`), 413 über 1 MiB | Settings → Sicherung |
| GET | `/api/types` | `api_types` | Diagnose: Bausteintypen der Anlage mit Status (voll/teilweise/keine), Anzahl, Beispielen, State-Namen, `details`-Schlüsseln und Liste der toten Kacheln; `?format=text` als Tabelle | Einstellungen, Entwicklung |
| POST | `/api/settings/miniserver` | `api_settings_ms` | Zugang erst prüfen (`reconnect(ms)`), dann speichern. Abgelehnt: nichts gespeichert. Nicht erreichbar: gespeichert, `gespeichert: true` mit Warnung, eine bestehende Verbindung bleibt bis zum nächsten Aufbau. `error` ist ein fester Text, der Fehler des Miniservers steht in `fehler`. Nacheinander, auch mit `/api/restore` (`_zugang_sperre`) | Einstellungen, LoxBerry-Widget |
| POST | `/api/settings/intercom` | `api_settings_intercom` | Kamera-URL/Login je Intercom | Einstellungen |
| GET | `/api/sip` | `api_sip` | Intercoms der Anlage (Türsteuerung `Intercom` und Baustein Intercom `IntercomV2`) mit `uuid`, `name`, `type`, `room`, `deviceType` und dem SIP-Zugang aus den gesicherten Details (`sip`: `host`, `user`, `hasPass`) oder dem Grund, warum es keinen gibt (`error`; `ohneSip`, wenn der Miniserver geantwortet hat, aber keinen nennt; hat der Baustein gesicherte Details ohne SIP-Teil, dazu `felder`: je Abschnitt die Feldnamen und ob sie gefüllt sind, ohne Werte); dazu `connected`. Das Passwort steht nie darin. Jede Intercom mit dem Kennzeichen `securedDetails` kostet eine verschlüsselte Anfrage an den Miniserver, darum lädt der Konfigurator erst beim Öffnen des Reiters | Settings → SIP |
| POST | `/api/sip/pruefen` | `api_sip_pruefen` | Body `{uuid}`: OPTIONS an die Türstation mit dem Zugang vom Miniserver (`sip_probe.pruefen()`). Antwort `ok`, `ziel`, `erreichbar`, `antwort`, `anmeldung` (`angenommen`, `abgelehnt`, `nicht verlangt`, `kein Passwort`, `unbekanntes Verfahren`, `keine Antwort`), `gegenstelle`, `methoden`, `codecs`, `ms`, `error`. Adresse und Passwort kommen nie aus der Anfrage; 404 für eine unbekannte Intercom, 400 ohne gültiges JSON | Settings → SIP |
| POST | `/api/settings/audiometa` | `api_settings_audiometa` | Audioserver-Live-Daten (Gen2-Events) ein/aus | Einstellungen |
| POST | `/api/settings/calendar` | `api_settings_calendar` | iCal-Abo + Wetter-Koordinaten für die Front speichern, `front_task` lädt sofort neu | Einstellungen |
| POST | `/api/agent/announce` | `api_agent_announce` | Agent meldet sich (`features: ["panel"]`: kann eine Ansicht übernehmen), Antwort enthält `dpmsOff`, `reloadHours` (`null` ohne Eintrag: der Agent nimmt `RELOAD_HOURS` seiner kiosk.conf) und, wenn für ihn eine Ansicht ansteht (`agent_wunsch`), `panel`; die beiden Werte gelten dann schon für sie | Panel-Agent |
| GET | `/api/agents` | `api_agents` | bekannte Agenten (`online` < `AGENT_ONLINE` = 60 s, gelistet < 600 s) | Einstellungen |
| POST | `/api/agent/command` | `api_agent_command` | `start`/`reload`/`stop` an einen Agenten weiterleiten (Zeitlimit `AGENT_BEFEHL_TIMEOUT`). `start` verwirft eine offene Wahl und hebt `last_mode` für das Gerät auf, `reload` mit offener Wahl wird zu `start` mit ihr | Einstellungen |
| POST | `/api/devices` | `api_save_devices` | Betriebsmodus-Zuordnung je Gerät. Ein leeres Display-Kennwort heißt „unverändert“, aber nur bei gleichem Ziel wie beim Einspielen (`_KENNWORT_ZIEL`: Host und Treiber, genau verglichen, auch Groß-/Kleinschreibung; der Port zählt nicht). Antwort: `devices` (Kennwort nur als `hasPass`) und `kennwortVerworfen` (Geräte, deren Kennwort wegen eines anderen Ziels verworfen wurde, der Konfigurator warnt) | Einstellungen |
| GET | `/api/devices` | `api_devices_get` | alle Anzeigegeräte (Agent, Kiosk-App, Browser) mit Online-Status, Ansicht, Typ und Präsenzstand (`presence`, nur mit gekoppeltem Präsenzmelder); Browser ohne Kennung nach IP | Einstellungen |
| POST | `/api/device/switch` | `api_device_switch` | Ansicht eines Geräts wechseln (`{device, panel, ip}`): offene Visu per WebSocket-Push; der Agent der Zeile (über `ip`, nicht den Namen, online) bekommt die Wahl über die nächste Meldung (`agent: "announce"`), ein älterer Agent oder ein Kiosk ohne offene Visu `/start` (`agent: "start"`; scheitert es bei einem Agenten mit `features`, `"announce"`). Hebt `last_mode` für das Gerät auf | Einstellungen |
| POST | `/api/device/name` | `api_device_name` | Browser ohne Kennung benennen (`{ip, name}`), Visu merkt sich den Namen und verbindet neu | Einstellungen |
| GET/POST | `/api/display` | `api_display` | Display schalten (`on=1|0`), Filter `panel`/`device`; wirkt bei Kiosk-Apps. `drivers[].error` nennt die Adresse nicht (bei Fully stünde das Kennwort darin); das Kennwort ersetzt der Server nur im Text der Gegenstelle, nicht in selbst gebildeten Meldungen wie „Cannot connect to host Host:Port“, sonst verriete die Ersetzung über den frei wählbaren Port eine PIN | Einstellungen, Loxone, extern |
| GET/POST | `/api/mode`, `/api/mode/{mode}` | `api_mode` | Betriebsmodus umschalten | Loxone-Ausgang, extern |
| POST | `/api/testtone` | `api_testtone` | Testton an Panels | Einstellungen |
| GET/POST | `/api/reload` | `api_reload` | Panels neu laden, Filter `panel`/`device` | Loxone, extern |
| GET/POST | `/api/goto` | `api_goto` | Panels auf Control oder Tab schicken (jeder gültige Tab, auch `kalender`/`wetter`) | Loxone, extern |
| GET/POST | `/api/notify` | `api_notify` | Nachricht einblenden | Loxone, extern |
| GET | `/icon?p=` | `icon_handler` | Loxone-Icon-Proxy, 24 h Cache | Visu, Konfigurator |
| GET | `/cover?u=` | `cover_handler` | Cover-Bild-Proxy, 60 s Cache | Visu |
| GET | `/mjpeg?id=` | `mjpeg_handler` | MJPEG-Relais der Türstation: die in LoxPanel eingetragene Kamera, sonst die aus den gesicherten Details des Miniservers (`App.intercom_video()`, Abschnitt 3.10); 404 ohne Kamera | Visu |
| GET | `/bellimg?id=&ts=` | `bellimg_handler` | Bild einer verpassten Klingel (`camimage/{uuidAction}/{ts}` vom Miniserver), 24 h Cache, die letzten `BELL_CACHE_MAX` im Speicher | Visu |
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

`_config()` (`:200`), dahinter `_ms_zugang()`, das auch die Quelle nennt:

1. `loxpanel.cfg` → `miniserver` (nur wenn `host` gesetzt, dann gilt der
   Abschnitt ganz)
2. Umgebungsvariablen `LOXPANEL_MS_HOST/USER/PASS/PORT/VERIFY_TLS`; ein leerer
   oder ungültiger Port wird 443
3. leer, Server startet trotzdem, wartet und zeigt den Panels den
   Einrichtungshinweis (§3, `einrichtung`); der Konfigurator führt dann zuerst
   zu Settings → Miniserver (§7.3)

`loxpanel.cfg.example` gilt nie als Zugang: Ihr `miniserver`-Abschnitt ist ein
Platzhalter (`192.168.1.50`, `CHANGEME`). Die Android-App bringt die Vorlage
mit; früher meldete sich ein frisches Panel damit endlos bei `192.168.1.50`
an. Auch `_load_cfg()` lässt den Abschnitt der Vorlage weg, damit Settings ihn
nicht vorausfüllt und kein Speichern einer anderen Einstellung ihn in die
`loxpanel.cfg` schreibt. Die übrigen Abschnitte der Vorlage bleiben Vorgaben.

Ein unter `/config` (Settings → Miniserver) gespeicherter Zugang hat also Vorrang vor Docker-Variablen.

Settings zeigt genau diesen Zugang (`/api/settings`), und `api_settings_ms`
geht von ihm aus. Speichern prüft zuerst und schreibt dann:

- Lehnt der Miniserver ab (Kennwort, Benutzer, Zertifikat, keine
  Loxone-Antwort), bleiben Datei und Verbindung, wie sie sind.
- Ist er nicht erreichbar (Frist, Verbindung, DNS), wird gespeichert. Eine
  bestehende Verbindung bleibt; `stream_task` baut die nächste mit dem neuen
  Zugang auf (`_zugang_neu`). Ohne Verbindung versucht es der Loop sofort damit.
- Ein leeres Kennwortfeld behält das bisherige Kennwort, aber nur für denselben
  Host und Benutzer.
- Wird der Zugang aus `LOXPANEL_MS_*` unverändert gespeichert, schreibt das
  nichts in die Datei; die Variablen gelten weiter. Ändert sich etwas (Port,
  Zertifikat), kommt der ganze Zugang samt Kennwort in die Datei, denn ein
  Abschnitt mit Host gilt nur ganz.
- Weitere Schlüssel des Abschnitts (`msno`, `_comment`, `response_timeout`,
  `keepalive_interval`) bleiben stehen.

Zertifikat prüfen (`verify_tls`): Mit `true` prüfen alle Verbindungen zum
Miniserver Zertifikat und Namen gegen den Standard-Truststore, also Anmeldung
und Struktur (`loxone_api`), WebSocket (`LoxoneWS`) und die `icon_session`
(Statistik, Bilder, gesicherte Details, dazu die Cover von außen). Den Kontext
für WebSocket und `icon_session` baut `ms_ssl_kontext()` in `loxone_ws.py` so
wie `loxone_api` seinen; die CAs lädt ein eigener Thread
(`asyncio.to_thread`), damit die Ereignisschleife nicht steht.

- Verbunden wird nur, wenn `host` ein Name ist, den das Zertifikat nennt. Mit
  der IP-Adresse scheitert die Prüfung („IP address mismatch“), auch bei einem
  sonst gültigen Zertifikat. Der Name muss im lokalen Netz auflösen.
- Es zählen die CAs des Systems, auf dem der Server läuft (im Docker-Image die
  von Debian). Die Android-App prüft gegen die CA-Liste, die Chaquopy
  mitbringt (certifi); eine unter Android selbst installierte CA kennt sie
  nicht. Eine eigene CA-Datei lässt sich nicht angeben.
- Mit `false` (Standard) prüft keine der Verbindungen, wie es ein Gen2 mit
  selbstsigniertem Zertifikat braucht.

### 5.2 `loxpanel.cfg`

| Sektion | Felder | Gelesen von |
|---|---|---|
| `miniserver` | `host`, `user`, `pass`, `port`, `verify_tls`; `response_timeout` (s, Frist für eine Antwort des Miniservers, auch beim Aufbau der Live-Verbindung und auf `keepalive`, Standard `MS_CMD_TIMEOUT`); `keepalive_interval` (s, Abstand der `keepalive` auf dem WebSocket, Standard `MS_KEEPALIVE` = 60; ohne Nachricht binnen Abstand + Frist wird neu verbunden, §3.4). Ungültige Werte: Standard mit Warnung im Log | `_config()`, `_ms_antwortfrist()`, `_ms_keepalive_abstand()` |
| `intercom` | `{control-uuid: {url, user, pass}}` | `_intercom_config()` |
| `audio` | `host` (optional, sonst Auto-Erkennung aus Cover-URLs), `port` (7091), `enabled` | `_audio_config()` |
| `audiometa` | `enabled` (Audioserver-Live-Daten); `retry_interval` (s, Pause vor dem nächsten Verbindungsversuch des Ereignis-Clients und, solange die Kopplung unklar ist, vor der nächsten Prüfung, Standard `AudioEventClient.NEU_VERSUCH_S` = 5); `response_timeout` (s, Zeitlimit der Kopplungsprüfung, Standard `PRUEF_ZEITLIMIT_S` = 6). Beide gelten ab dem nächsten Start des Clients | `_audiometa_config()`, `_audiometa_sekunden()` |
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
      "roomCats": ["<cat-uuid>"],            // Raum-Panel: Kategorien der unteren Leiste, max. 4,
                                             // in Klickreihenfolge; fehlt = die ersten 4 im Raum
      "hide":  ["<control-uuid>"],           // einzelne Kacheln ausblenden
      "ui": {
        "iconSize": 38, "nameSize": 18, "subSize": 15,   // px; fehlt = global, sonst Standard des
        "roomSize": 12, "bigSize": 36,       // Kachel-Aufbaus (GROESSEN_STANDARD, §5.4)
        "font": "Inter",
        "textColor": "#e8eaed", "bold": true, "lang": "de",
        "tileLayout": "classic",             // Kachel-Aufbau: nur "classic"; fehlt = der neue (§7.1)
        "grid": "auto",                      // automatisches Raster (Tablet): cols/rows gelten dann nicht (§7.1)
        "tileSize": 200,                     // Zielkachel des automatischen Rasters in px (KACHEL_ZIEL_MIN
                                             // bis KACHEL_ZIEL_MAX); fehlt = KACHEL_ZIEL_STANDARD; die alten
                                             // Stufen "small" | "medium" | "large" werden gelesen
        "nudgeX": -6, "dpmsOff": 180, "reloadHours": 12,
        "pinMerken": 60,                     // Sek., die die Visu eine bestätigte Visu-PIN behält;
                                             // 0 = jedes Mal fragen, fehlt = PIN_MERKEN_STANDARD
        "cols": 4, "rows": 3, "fill": true,
        "scale": "auto",                     // "off" | "auto" | Faktor 0.5–2.0; fehlt = wie global
        "catFilter": true,                   // Sprungmarken filtern statt springen (nur true, fehlt = springen)
        "valueBar": ["favoriten", "room:<uuid>", "raeume"],   // Seiten, deren Anzeige-Bausteine (WERTE_LEISTE_TYPEN)
                                             // als Werteleiste in EINER Zeile über dem Raster stehen statt
                                             // als Kacheln; "raeume"/"kategorien" = die Raum- bzw.
                                             // Kategorie-Seiten darunter; fehlt = alles Kacheln (§7.1)
        "panes": {"favoriten": "chart:<uuid>"},   // zweite Hälfte je Tab (quer rechts, hochkant unten): "weather" | "calendar" |
                                             // "player:<uuid>" | "energy:<uuid>" | "camera:<uuid>" |
                                             // "chart:<uuid>,…" (Verlauf eines oder mehrerer
                                             // Bausteine mit Aufzeichnung, untereinander) |
                                             // "status:<uuid>,…" (frei gewählte
                                             // Werte) | "header" bzw. "header:<uuid>,…"
                                             // (Kopfzeile: Uhr, Wetter und bis zu
                                             // SV_STATUS_MAX Werte in EINER Zeile ÜBER
                                             // dem Raster statt einer Pane daneben);
                                             // fehlt = Screen füllen
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
          "chartStyle": "pattern",           // Darstellung: fehlt = Trend | "pattern" | "span" (nur mit chart)
          "w": 2                             // Breite in Spalten: 1 | 2; fehlt = nach Typ (KACHEL_BREIT_TYPEN:
                                             // Audio, Raumregelung, Energiefluss sind 2, alles andere 1; §7.1)
        }
      }
    }
  },
  "devices": {
    "<Gerätename>": {
      "auto": true, "modes": {"<Modusname>": "<panel-id>"},
      "display": {"driver": "fully", "host": "192.168.1.60", "port": 2323, "password": "..."},  // optional; auch "wallpanel" (Port 2971)
                                             // Kennwort verlässt den Server nicht: /api/meta nennt nur hasPass
      "scale": "off",                        // optional; übersteuert Profil und global ("off" | "auto" | Faktor)
      "tileTarget": 260,                     // optional; Zielkachel des automatischen Rasters für dieses Gerät
                                             // (Gerät vor Profil, nur im Kachel-Layout „Automatisch“; §7.1)
      "presence": "<control-uuid>"           // optional; Präsenzmelder (Baustein mit active-State):
                                             // Display an, solange er jemanden meldet (§8)
    }
  }
}
```

Die Validierung in `_sanitize_panels()` ist eine Whitelist, die unbekannte
oder falsch getypte Felder verwirft. Die Antwort nennt das Verworfene
(`verworfen`), der Konfigurator zeigt es als Warnung. Wer eine neue Option
ergänzt, muss sie dort eintragen und zusätzlich in `_panel_export()`, das die
Profile an den Konfigurator gibt: Der schickt beim Speichern zurück, was er
bekam, und eine Option, die dort fehlt, geht beim nächsten Speichern still
verloren. So geschah es mit `catFilter` und `roomCats`.
`test_jede_gespeicherte_option_kommt_beim_konfigurator_an` (in
`tests/test_kachel_aufbau.py`) prüft beide Listen gegeneinander: Ein Profil, das
jedes gespeicherte Feld belegt (`VOLL`), muss nach `_panel_export()` und
erneutem Speichern unverändert sein. `test_vorlage_belegt_jedes_gespeicherte_feld`
schreibt mit, welche Felder `_sanitize_panels()` liest, und schlägt an, sobald
eines davon in `VOLL` fehlt. Ein neues Feld gehört also auch dorthin.

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

Die Größen (`iconSize`, `nameSize`, `subSize`, `roomSize`, `bigSize`) stehen
nur drin, wenn sie eingestellt sind. Fehlt eine im Panel und global, gilt der
Standard des Kachel-Aufbaus aus `GROESSEN_STANDARD` (neu Haupttext 16,
Zweittext 14, Raum 13; klassisch 18, 15, 12; Icon 38 und Messwert 36 in
beiden). `_theme_vars()` rechnet damit, `/api/meta` gibt die Tabelle als
`sizeDefaults` an den Konfigurator, der leere Felder grau mit dem Wert zeigt,
der dann gilt (im Panel erst der globale, sonst der Standard). Weder
`load_theme()` noch die Vorlage `theme.example.json` legen Größen fest.
Bis Oktober 2026 taten sie es (18/15 bzw. 20/15). Die Standardwerte wirkten
deshalb nie, und der Konfigurator zeigte Werte, die niemand gewählt hatte.
Eine `theme.json` aus jener Zeit trägt noch 20/15, wer den Standard will,
leert die Felder unter Global → Darstellung.

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

**Tasten auf der Kachel** (`controls[]`, je `icon` und `cmd`) haben der Player
(◀ ⏯ ▶) und die Beschattung (▲ ▼). Die Beschattung sendet dieselben Befehle wie
Auf/Ab der Detailseite (`_jal_fahrt()`): Im Stand startet eine Taste die
Fahrt, während der Fahrt halten beide an (`Stop`), und die fahrende Richtung
zeigt ■. Die Visu bindet die Tasten an `click`; ein Wischer, der auf einer
Taste beginnt, scrollt das Raster. Unter dem Text stehen sie nur, wenn die
Kachel hoch genug ist. Sonst rücken sie in die Kopfzeile neben das Icon
(`ctrltight`), und ist auch die zu schmal (3x3, drei Tasten), an seine Stelle
(`ctrlnarrow`). Das misst `placeCtrls()` wie beim Mini-Verlauf, bei jeder neuen
Kachel und bei neuem Text, nicht bei jeder Meldung. Geprüft in
`tests/test_beschattung.py` und `tests/browser/test_kachel_tasten_browser.py`
(Tippen, Wischen, Stop während der Fahrt, alle vier Raster für Beschattung und
Player).

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

**Bedienung nach der Loxone-Strukturdoku.** Befehle und Bedeutung der States
stehen in der Strukturdoku von Loxone („Structure File“, Stand 16.0,
`loxone.com/wp-content/uploads/datasheets/StructureFile.pdf`), Grenzen und
Eingänge der Bausteine in der Loxone-Wissensdatenbank. Danach gebaut:

- **UpDownAnalog** („UpDownLeftRight analog“): Befehl ist der Wert selbst,
  zwischen `details.min` und `details.max`, −/+ um `details.step`. Dieselbe
  Detailseite wie der Slider (State `error` → „Ungültiger Wert“).
- **Irrigation:** `zones[].id` zählt ab 0, `currentZone` ist −1 (aus), die id
  der laufenden Zone oder 8 (alle). `select` folgt dem Eingang „Sel“ des
  Bausteins (Ventil 1..8, 0 alle aus, 9 alle an), eine Zone startet also mit
  `select/{id+1}` (`IRR_SELECT_*`). Laufzeit `setDuration/{id}={Sekunden}`, nicht
  bei `setByLogic`. Die Zone hat eine Unterseite (`irrzone`).
- **AlarmClock:** `entryList/put/{entryID}/{name}/{alarmTime}/{isActive}/{modes|daily}`
  schreibt einen Eintrag, `entryList/delete/{entryID}` löscht ihn. Einträge mit
  `nightLight` kennen nur `daily` (einmalig/täglich), die übrigen Betriebsarten:
  3..9 sind Montag bis Sonntag, 0..2 (Feiertag, Urlaub, freie Tage) haben Vorrang
  (`WECKER_*`). Eine neue Weckzeit bekommt die kleinste freie ID. Kommt
  `entryList` als Liste ohne IDs, wird nur angezeigt. Dauern per
  `setSnoozeDuration` (60..1800 s), `setRingDuration`, `setPrepDuration`; mit
  Touch Nightlight (`deviceState` 1 oder 2) auch Wecksound, lauter werdend,
  Signalton, Lautstärke und Helligkeit. `isEnabled` 0 (Eingang DisA) zeigt
  „Ausgeschaltet“.
- **Intercom:** `answer` stellt die Klingel ab. `lastBellEvents` (JJJJMMTTHHMMSS,
  mit `|`) sind die Klingeln, auf die niemand reagiert hat; mit
  `details.lastBellEventImages` holt `/bellimg` das Bild dazu per
  `camimage/{uuidAction}/{ts}`. Gegensprechen (SIP) fehlt, darum bleibt der Typ
  in `PARTIAL_TYPES`. Den SIP-Zugang (`audioInfo`: `host`, `user`, bei
  Loxone-Intercoms `pass`) gibt der Miniserver seit 8.1 nur noch in den
  gesicherten Details heraus; `details.audioInfo` ist leer. Lesen und Prüfen:
  Abschnitt 3.10. Die Kamera kommt aus LoxPanel oder aus denselben gesicherten
  Details (`videoInfo`), ebenfalls Abschnitt 3.10.
- **IntercomV2** (Baustein Intercom, Strukturdoku 17.0): Kachel, Klingel-Popup,
  Kamera-Pane, Ausgänge und `answer` wie bei `Intercom`, die gemeinsamen Stellen
  fragen `INTERCOM_TYPES` ab. Dazu nur hier: `answers` ist die Liste der
  Antworten (JSON-Text), `playTts/{idx}` spielt eine an der Tür ab; der Index
  ist der in der Liste, leere Einträge bekommen keine Taste
  (`_intercom_antworten()`). `muted` mit `mute/1` und `mute/0` (die Taste nur,
  wenn der State da ist). `deviceState` 2 (StateRebooting) und 3
  (StateInitializing) zeigen Kachel und Detailseite als „Startet neu“ und
  „Startet“; 0 (StateUnknown) sagt nichts Sicheres und bleibt ohne Hinweis
  (`INTERCOM_V2_ZUSTAND`). `lastBellEvents` und `camimage` nennt die Doku nur
  bei `Intercom`, die v2 hat darum keine verpassten Klingeln. Video- und
  SIP-Zugang beschreibt die Doku für die v2 nicht; trägt der Baustein trotzdem
  `securedDetails` (etwa eine benutzerdefinierte Intercom daran), nutzt
  LoxPanel sie wie bei `Intercom`. Gegensprechen fehlt bei beiden, darum steht
  auch `IntercomV2` in `PARTIAL_TYPES`.

Die Bausteine dazu stehen in `tests/lox.py` (`aufab_baustein`,
`bewaesserung_baustein`, `wecker_baustein`, `intercom_baustein`,
`intercom_v2_baustein`), die Tests in `tests/test_auf_ab_wert.py`,
`test_bewaesserung.py`, `test_wecker.py`, `test_intercom.py`,
`test_intercom_v2.py`, `test_intercom_video.py` und
`tests/browser/test_bausteine_browser.py`.

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
  über `/icon`, `/cover`, `/mjpeg`, `/bellimg`.
- Zwei Renderer: `render()` (`:597`) für Kachelraster aus `items[]`,
  `renderPanel()` (`:472`) für Detailseiten aus `blocks[]`, dazu `updatePanel()`
  (`:550`) als Delta-Update, das bei Live-Werten nur Texte und Slider anfasst.
- Block-Rendering in `bh()` (`:486-516`), ein Zweig je `k`.
- Detailseite höher als der Schirm (480×480 mit vielen Zeilen): `panelEinpassen()`
  setzt nach jedem Neuaufbau und beim Drehen `eng`, dann fallen Deko-Kreis
  (`hero`) und Größe des großen Werts weg wie bei Diagramm-Seiten. Reicht das
  nicht, scrollt die Seite. Der obere Teil einer `anchor:bottom`-Seite schrumpft
  nicht unter seinen Inhalt (`.pantop{flex:1 0 auto}`); früher schob er sich
  unter die Bedienung (Sauna mit vielen Statuszeilen). Geprüft in
  `test_volle_seite_ueberlappt_nicht`.
- Kachel-Grid über CSS-Variablen `--cols`/`--rows` (2×2, 3×2, 4×3), Kachelgröße
  auf 240 px gedeckelt, außer bei `fill`. Seiten-Snapping pro `cols*rows` Kacheln.
- Kachel-Aufbau (`ui.tileLayout`, mit der `theme`-Nachricht als `tileLayout`):
  Standard ist der neue nach den Kacheln der Loxone-App, `"classic"` der
  bisherige. Das Raster (`cols`/`rows`) ist in beiden gleich, die
  Listen-Ansicht behält ihren Aufbau. `kachelNeu()` entscheidet, `render()`
  setzt `.lx` am Grid. Im neuen Aufbau steht der Raum klein oben rechts im
  Kopf statt in Versalien über dem Namen, der Pfeil fällt weg, Tasten liegen
  als Leiste über die ganze Breite unten (44 px hoch). Zustand vorn (`.zv`,
  `zustandVorn()`): Der Zustand steht groß, der Name klein darunter. Das gilt
  nicht für Kacheln, die direkt schalten (`it.cmd`, dort zeigt die
  Hervorhebung den Zustand), und nicht, wenn die zweite Zeile nur beschreibt
  (`it.subInfo` vom Server, Klasse `.bi`, etwa „Türsprechanlage“ oder
  „Zentral“). Ein Messwert ersetzt das Symbol (`.bigv`). Der Server schickt
  dafür `big` und `bigSub`: bei der Raumregelung die Ist-Temperatur, darunter
  Soll und Tätigkeit, bei der Sauna die Temperatur, darunter den Zustand.
  `subText()` setzt mehrteilige Zustände (` · `) untereinander. Enge Kacheln
  misst `fitTile()` nach `placeCtrls()`; Stufe für Stufe weicht das
  Unwichtigste. `eng1`: Text einzeilig, bei `.bi` fällt die Beschreibung weg
  und der Name behält zwei Zeilen. `eng2`: Die Angabe zum Mini-Verlauf fällt
  weg, der Verlauf selbst bleibt im Kopf. `eng3`: Die zweite Zeile fällt weg.
  Der Name geht so vor der Angabe, und der Verlauf hat auch dort Platz, wo
  der klassische Aufbau keinen findet (18 Kacheln auf 800×480). `updateGrid()`
  behält die gemessenen Klassen (`spark*`, `ctrltight`, `ctrlnarrow`,
  `eng1`–`eng3`) und setzt `bigv` an Ort und Stelle. Kommt oder geht ein
  Messwert, baut es neu auf. Schriftgrößen: `--name-size` (Haupttext, im
  neuen Aufbau meist der Zustand), `--sub-size` (Zweittext), `--room-size`,
  `--big-size`. Die Schrift einer Kachel aus „Kacheln gestalten“
  (`--tile-txt`, `--tile-fw`, `--tile-fst`) gilt für den Haupttext, auch wenn
  er der Zustand ist. Am 4″-Panel (3×3) schneidet der neue Aufbau nichts ab,
  was der klassische ganz zeigt, mit den Standardgrößen wie mit 20/15 aus
  älteren `theme.json`. Geprüft in `tests/test_kachel_aufbau.py`,
  `tests/browser/test_kachel_aufbau_browser.py` und
  `test_mini_verlauf_im_neuen_aufbau`.
- Kachelfaktor (Oktober 2026): Der Inhalt einer Kachel wächst mit ihrer
  Größe. `setzeFaktor()` setzt `--ks` am `.screen`: Kachelbreite durch
  `KACHEL_REF` (170 px, die mittlere Stufe des automatischen Rasters), die
  Höhe durch `KACHEL_REF_H` (150 px) begrenzt, das Ganze auf `KS_MIN` 0,85 bis
  `KS_MAX` 2,0. CSS multipliziert damit Symbol (`--ico-size`), Haupttext,
  Zweittext, Raum, Messwert, Innenabstand, Radius, Positionsring,
  Mini-Verlauf, Tastenleiste und die Kopfzeile (`--kopf-h`). Die eingestellten
  Größen (`--name-size` usw.) gelten damit „bei 170-px-Kachel“: Tablets im
  automatischen Raster sehen aus wie zuvor, eine 415-px-Kachel trägt 32-px-
  Schrift und ein 76-px-Symbol statt derselben 16/38 wie eine 122-px-Kachel,
  die 13,6/32 bekommt. Im automatischen Raster rechnet `autoRaster()` den
  Faktor aus der Spaltenbreite, bevor es die Zeilen bestimmt (die Kopfzeile
  wird mit ihm höher); beim festen Raster liest `render()` ihn aus der ersten
  Kachel, nachdem `renderTabs()` Split und Kopfzeile gesetzt hat, und misst
  nach, bis er steht (`faktorEinmessen()`): mit Kopfzeile hängt die
  Kachelhöhe an `--kopf-h` und die wieder am Faktor, einmal gemessen hing er
  an der Seite davor (Codex-Befund an #122). `setzeFaktor()` passt danach
  die Kopfzeile neu ein, denn ihre Schrift wächst mit. Ändert sich
  die Kachelbreite ohne neues Raster (Fenster, Split an/aus), zieht
  `faktorNachziehen()` nach und `kachelnNeuMessen()` misst die Kacheln neu
  ein. Zwei Grenzen: Tasten sind Touch-Ziele und schrumpfen nie
  (`max(1, var(--ks))`), und ein Text, der in seine Zeilen nicht mehr passt
  (`line-clamp`, im klassischen Aufbau „…“), nimmt den Faktor über die
  Textstufen `kst1`–`kst3` (`--kst`, in `fitTile()` gemessen, vor und nach
  den Eng-Stufen) zurück: über Faktor 1 höchstens auf 1, den Stand ohne
  Faktor, auf kleiner Kachel auch darunter, denn ein kleiner ganzer Text
  liest sich besser als ein großer mit „…“. Dieselben Stufen nimmt eine
  Kachel mit Mini-Verlauf über Faktor 1 auch, wenn ein Zustand mit dem
  Faktor auf zwei Zeilen geht („4,200 kW • 9,1 MWh“ auf 200 px) und der
  Mitte damit die Höhe für den Verlauf (`SPARK_MIN_H`) fehlt: der Text gibt
  seinen Zuwachs her, sobald eine Stufe die Zeile wieder einzeilig macht und
  die Mitte reicht, der Verlauf bleibt dort. Eine Stufe, die nur die Schrift
  verkleinert, ohne eine Zeile zu lösen, zählt nicht, sie brächte die Mitte
  höchstens knapp über die Schwelle und einen gequetschten Verlauf. Reicht
  auch Faktor 1 nicht („0,600 kW • 10,0 MWh“), bleibt der Text groß und
  `placeSpark()` setzt den Verlauf wie bisher in den Kopf. `sparkFrei()`
  misst dafür die freie Mitte, `fitTile()` setzt den Verlauf nach den Stufen
  neu. Im Kopf
  füllt der Verlauf die Kopfhöhe (das Symbol gibt sie vor), auch im neuen
  Aufbau: mit Faktor 0,85 blieben ihm mit den Rändern der Mitte sonst 27 px
  von 36. Gemessen mit 23 Favoriten in acht
  Bildschirmgrößen: auf 800×480 mit 3×3 und Füllen sank die Zahl
  abgeschnittener Namen von 15 auf 1, am 4″-Panel mit 3×3 von 8 auf 0, die
  flache 225×128-Kachel (2×3) läuft nicht mehr über, das 2×2 des 4″-Panels
  trägt 21-px-Schrift und 50-px-Symbol statt 16/38 in sonst leerer Fläche.
  Geprüft in `tests/browser/test_kachel_faktor_browser.py`, dazu die
  Lesbarkeits-Prüfung auf den Standardgeräten (nichts wird mit Faktor mehr
  abgeschnitten als ohne, keine Kachel läuft über).
- Raumnamen aus Kachelnamen (Oktober 2026): Auf einer Raum-Seite (Tab
  `room:<uuid>`, Raum aus „Räume“ über `_view_group`) nennt der Titel den
  Raum schon, also fällt er aus den Kachelnamen: `_control_item(…,
  ohne_raum=<Raumname>)` ruft `_ohne_raum()`, das nur ganze Wörter streicht
  („Jalousie Wohnzimmer Süd“ → „Jalousie Süd“, „Wohnzimmer: Decke“ →
  „Decke“, „Wohnzimmerlampe“ bleibt), die Reihenfolge der übrigen Wörter
  behält, Trenner am Rand mitnimmt und den Namen lässt, wenn nichts übrig
  bliebe. Seiten über mehrere Räume (Favoriten, Kategorie, freie Auswahl)
  behalten die vollen Namen und tragen den Raum an der Kachel (`show_room`).
  In der Messreihe zum Kachelfaktor trugen die meisten abgeschnittenen Namen
  den Raum. Geprüft in `tests/test_raumname.py`.
- Werteleiste (Oktober 2026, `ui.valueBar`): Je Seite wählbar stehen die
  Anzeige-Bausteine (`WERTE_LEISTE_TYPEN`: Messwert, Zähler, Text,
  Textzustand, Ein/Aus-Anzeige, Präsenz, Betriebsstunden; nicht Rauchmelder
  und Klimaregelung) als Kette von Werten in **einer** Zeile über dem
  Raster statt als Kacheln, das Raster bleibt dem Bedienbaren. Der Server
  trennt (`_leiste_trennen()`, vor dem Gruppieren, damit Anker und
  Sprungmarken zu den Kacheln im Raster gehören) und schickt sie als
  `view.leiste` in derselben Form wie `items` (`_leiste_items()`, also mit
  Wert, Symbol, Farbe, Raum und der Wertseite als `nav`); bliebe im Raster
  nichts, bleibt alles Kachel. `ui.valueBar` nennt Tab-Kennungen
  (`_clean_werteleiste()`, auch `raeume`/`kategorien` für die Seiten
  darunter), `resolve_profile()` gibt sie als `valueBar` weiter. Die Visu
  (`renderLeiste()`) setzt `.leiste` am `.screen` (eigene Grid-Zeile über
  dem Raster, unter der Kopfzeile; im Split quer nur über dem Raster, das
  Widget reicht über beide Zeilen) und baut die Zeile aus denselben Chips
  wie die Werte der Kopfzeile (`kopfWertHtml()`); was nicht passt, scrollt
  waagerecht (Mausrad eingeschlossen), denn diese Werte haben keine Kachel
  mehr. Höhe `--leiste-h` = `LEISTE_H` (48 px) × Faktor (`setzeFaktor()`),
  `autoRaster()` zieht sie wie die Kopfzeile ab (`leisteHoehe()`). Bei
  neuen Werten derselben Seite zieht `updateLeiste()` nur Zustand, Symbol
  und Texte der Chips nach (kein Neuaufbau, die Scroll-Lage bleibt). Ein
  Tipp öffnet die Wertseite. Konfigurator: Kästchen „Werte als Leiste über
  den Kacheln“ je Tab im Feld „Widget je Tab“. Geprüft in
  `tests/test_werteleiste.py` und `tests/browser/test_werteleiste_browser.py`.
- Breite Kacheln (Oktober 2026): Audio, Raumregelung und Energiefluss
  (`KACHEL_BREIT_TYPEN`: AudioZone, AudioZoneV2, IRoomController(V2), EFM,
  EnergyManager2) belegen zwei Spalten, je Kachel übersteuerbar über
  `tiles[uuid].w` (1 oder 2, Kachel-Editor „Breite“; der Konfigurator bekommt
  die Typen als `kachelBreit` aus `/api/meta`). `_apply_tile_style()` setzt
  `w: 2` nur an die breite Kachel, die Visu macht daraus die Klasse `w2`
  (`grid-column: span 2`), aber nur, wo das Raster zwei Spalten hat. Das
  Raster fließt dicht (`grid-auto-flow: row dense`): eine Lücke vor einer
  breiten Kachel füllt die nächste schmale. Damit Seiten und Rastpunkte
  stimmen, rechnet `rasterLage()` die Lage nach, wie CSS sie setzt (je
  Kachel die Zeile, daraus die Seitenzahl): `render()` und `updateGrid()`
  setzen `snap` auf jede Kachel in der ersten Zeile einer Seite und `snapy`
  ab der zweiten Seite, `springeZu()` springt zur ersten Kachel dieser Zeile,
  `autoRaster()` prüft mit derselben Lage, ob alle Kacheln auf eine Seite
  passen (Wachsen, Punkt 2). `kachelGemessen()` nimmt für den Kachelfaktor
  eine schmale Kachel, notfalls die halbe Breite einer breiten. Auf der
  breiten Kachel bleibt ein mehrteiliger Zustand („PV 0,55 kW · Bezug
  0,15 kW“) auf einer Zeile (`subText()`), statt wie auf der schmalen
  untereinander zu stehen: untereinander kostete er auf der 126-px-Kachel des
  4″-Panels die Höhe, und die Eng-Stufe kappte den zweiten Teil. Geprüft in
  `tests/test_kachel_breit.py` und `tests/browser/test_kachel_breit_browser.py`.
- Automatisches Raster (Kachel-Layout „Automatisch“, `ui.grid = "auto"`, für
  Tablets): Die Visu rechnet Spalten und Zeilen selbst (`autoRaster()`), statt
  `cols`/`rows` aus dem Profil zu nehmen. Grundlage ist die Zielkachel in
  CSS-Pixeln, die der Server schickt (`gridAuto`): eine Zahl aus `ui.tileSize`
  (`KACHEL_ZIEL_MIN` bis `KACHEL_ZIEL_MAX`, fehlt = `KACHEL_ZIEL_STANDARD`;
  die alten Stufen klein/mittel/groß stehen in `KACHEL_ZIEL` und werden beim
  Speichern zur Zahl), je Gerät übersteuerbar unter Displays
  (`devices[name].tileTarget`, Gerät vor Profil wie bei der Skalierung,
  `effective_grid_auto()`; beim Speichern bekommt jede offene Visu
  `{t:"gridAuto"}` und baut ihr Raster ohne Neuladen neu). Der Konfigurator
  schlägt je Gerät einen Wert aus der gemeldeten Größe vor
  (`_kachel_vorschlag()` in `/api/devices` als `tileSuggest`: Pixeldichte ab
  1,5 ist ein Tablet in der Hand, dort der Standard; ohne Pixeldichte ein
  Fünftel der kürzeren Seite, auf Zehner gerundet, mindestens der Standard,
  höchstens 300 px: FullHD 220, 2560×1600 300). Spalten = Breite durch
  Zielkachel, gerundet; Zeilen so, dass die Kacheln etwa quadratisch werden.
  Die Automatik kennt die Kachelanzahl der Seite (`_lastAnzahl` aus
  `render()`): passen alle Kacheln auf eine Seite, nimmt sie Spalten weg,
  solange die Seite alle noch fasst und die Kachel nicht breiter als
  `gridGrow` × Zielkachel wird (`KACHEL_WACHSEN`, 1,4; mit der theme-Nachricht
  geschickt). Fünf Kacheln auf dem 10″-Tablet quer stehen so in 6 × 3 zu
  204 px statt in 7 × 4 zu 174 px; mit mehr Kacheln als Zellen bleibt es bei
  der Zielkachel und dem Blättern. Mit Widget daneben wachsen sie nicht: es
  belegt ganze Kachelspalten, und mit weniger Spalten ließe sich sein Anteil
  von rund 40 % nicht halten (2 von 5 Spalten sind 40 %, 2 von 4 schon 50 %,
  die Wetter-Pane wechselte von „schmal“ auf „breit“).
  Abstand und Innenrand liest sie aus dem CSS (`--gap`, `--pad` am Raster),
  die Höhe der Tab-Leiste aus der Seite. Ein größerer Schirm zeigt so mehr
  Kacheln statt größerer: am Tab A9 (893×533 CSS-px) quer 5 × 3 Kacheln zu
  etwa 167 × 146 px, hochkant 3 × 5, am 10″-Tablet (1280×800) quer 7 × 4. Ein
  Widget belegt ganze Kachelspalten (quer) bzw. -zeilen (hochkant), rund
  `PANE_ANTEIL` (40 %) der Fläche. Die Aufteilung setzt `render()` als
  `--auto-k`/`--auto-p` (fr), die Kacheln bleiben damit mit und ohne Widget
  gleich groß: am Tab A9 quer 3 × 3 neben dem Widget statt 5 × 3. Der Kasten
  ist der ganze Schirm (Klasse `.fill` mit `.auto`), „Bildschirm füllen“,
  Skalierung und die Verdopplung „Screen füllen“ wirken nicht
  (`applyScale()` bleibt bei 1). Geblättert wird seitenweise wie bisher (je
  Seite Spalten × Zeilen Kacheln). Beim Drehen rechnet `rasterKey()` neu, der
  `resize`-Handler baut dann neu auf. Der Online-Punkt sitzt wie im Split in
  der Ecke, weil die Mitte bei ungeraden Zahlen (5 × 3) auf einer Kachel läge.
  Das Panel meldet das Raster mit seiner Bildschirmgröße (`rc`, `rr`), der
  Konfigurator zeigt es unter Displays bei den Geräten. Das feste Raster
  (4″-Panel, jedes Profil ohne `grid`) bleibt unverändert. Der Assistent
  „Neues Panel“ schlägt „Automatisch“ für 2 Panes (Tablet) vor. Geprüft in
  `tests/test_auto_raster.py` (Prüfer, Standard, Gerät vor Profil, Vorschlag)
  und `tests/browser/test_auto_raster_browser.py` (Raster je Gerät, Wachsen
  mit wenigen Kacheln, Zielkachel je Gerät wirkt sofort, Konfigurator).
- Eingebaute Icons: `ICONS` (`:273-296`, 22 SVGs). Loxone-Icons als CSS-Maske,
  damit sie die Zustandsfarbe annehmen.
- Skalierung, Kette global (`theme.json` `ui.scale`) → Profil (`ui.scale`) →
  Gerät (`devices[name].scale`): die spätere gewinnt, fehlt sie, gilt die
  frühere. Profil und Gerät speichern deshalb auch `"off"` ausdrücklich, sonst
  könnte ein Profil ein globales `"auto"` nicht abschalten. Die Visu
  rechnet mit festen 240er Kacheln, der Kasten ist also 480×480 bzw. im Split
  960×480 (hochkant 480×960). Ein größeres Display zeigte ihn bisher mit Rand (1280×800: 55 % des
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
- Split hochkant: Ist das Fenster höher als breit, liegen Visu und Pane 2
  übereinander statt nebeneinander (oben Kacheln, darunter die Pane, unten die
  Tab-Leiste über die volle Breite). `applyHoch()` setzt dafür `.hoch` am
  `.screen`, sobald `.split` gesetzt ist; die Maße sind gespiegelt
  (`--cols`·240 breit, `--rows`·480 hoch), „Bildschirm füllen“ gilt weiter.
  `applyHoch()` läuft in `applyPane()` und im `resize`-Handler, weil beim
  Drehen nicht in jedem Fall neu gerendert wird (Anlagenschema, Screensaver
  oben). Mit festem Raster ist die Pane hochkant fast so groß wie quer (Tab A9:
  480×419 gegen 480×425 auf 960×480); mit „Automatisch“ und je nach Gerät
  schwankt sie stärker, darum passen sich Wetter, Kalender und Werte ihrer
  Fläche an (siehe „Pane 2 nutzt ihre Fläche“).
  Geprüft in `test_split_hochkant_uebereinander`, `test_split_dreht_mit` und
  `test_split_haelfte_wetter_und_kalender[hochkant]`.
- „Screen füllen“ (Tab ohne Pane 2) verdoppelt das Raster: quer die Spalten
  (2×2 → 4×2), hochkant die Zeilen (2×2 → 2×4). Hochkant nur, wenn das Raster
  dadurch besser zur Fensterform passt: `rasterFuer()` verdoppelt, sobald
  Breite/Höhe kleiner ist als Spalten/Zeilen geteilt durch √2 (das
  geometrische Mittel zwischen einfachem und doppeltem Raster). Auf einem
  Hochkant-Tablet werden so 2×2, 3×2 und 3×3 verdoppelt; 2×3 („Tablet hoch“ im
  Editor) ist schon ein Hochformat-Raster und bleibt, sonst wären es sechs
  flache Zeilen. Das quadratische 4″-Panel bleibt, Split „Aus“ verdoppelt nie.
  Gemessen auf 533×893: vorher ein 533×533-Quadrat mit je 180 px leer darüber
  und darunter (mit „Bildschirm füllen“ auf 252×404 gestreckte Kacheln),
  jetzt 2×4 Kacheln mit 225×197, mit „Bildschirm füllen“ 252×197. Der
  `resize`-Handler vergleicht Lage und Raster (`rasterKey()`) statt nur
  quer/nicht quer und rendert neu, sobald eines kippt.
  Geprüft in `test_screen_fuellen_hochkant_nach_unten`.
- Screensaver: zweite Fläche je Panel einstellbar (`ui.svPane`): quer die
  rechte Spalte, hochkant unter Uhr und Wetter, auf dem quadratischen
  4″-Panel keine. Werte: `""` = Automatik (Termine, und sobald keine anstehen die
  Wetter-Details — so bleibt die halbe Fläche nie leer), `off`, `calendar`,
  `weather`, `player:<zone>`, `energy:<uuid>`, `camera:<uuid>`, `chart:<uuid>,…`, `status:<uuid>,…`. Geprüft an
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
  Hochkant setzt `applySaverSplit()` neben `.split` die Klasse `.hoch`, sobald
  der Kasten mindestens √2-mal so hoch wie breit ist (gemessen am Kasten, denn
  in ihm liegt der Screensaver; dieselbe Grenze wie bei der Verdopplung nach
  unten). Uhr (80 px), Wetter und die zweite Fläche stehen dann untereinander
  über die volle Breite. Listen wachsen nach unten, `svFit()` kürzt sie wie
  quer. Energiefluss und Kamera bekommen die ganze Höhe unter Uhr und Wetter.
  Der Verlauf nicht: seine Diagramme richten die Höhe nach der Breite, eine
  hohe Box bliebe unten leer (gemessen 100 px). Dort ist die Box so hoch wie
  der Inhalt und der ganze Block mittig (`.verlauf`). Vorher zeigte das Tab A9
  hochkant (533×893) dieselbe Uhr-Seite wie das 4″-Panel: 440×442 in der Mitte,
  je 225 px leer darüber und darunter, und eine gewählte zweite Fläche
  erschien nie. Beim Start steht der Kasten kurz im Profilraster, bevor die
  erste Ansicht ihn verdoppelt. Der `ResizeObserver` am `.screen` ruft deshalb
  `onScreenResize()` auf: neu skalieren und, wenn die Uhr-Seite oben liegt,
  ihre Aufteilung neu wählen und neu einpassen, damit `svFit()` keine Termine
  kürzt, die im größeren Kasten Platz haben.
  Geprüft in `test_uhrseite_hochkant_zweite_flaeche_unten`.
- Widget-Seite (seit Upstream 0.6.0): Eine freie Seite kann statt Kacheln ein
  Widget sein (`pickTabs[].widget`, dieselben Werte wie eine Pane,
  `_clean_tabpane()`). Der Server liefert dann `view.widget` ohne `items`, das
  Panel setzt `.screen.widgettab`, blendet das Kachelgrid aus und zeichnet das
  Widget über die ganze Fläche; `paneRawNow()` liefert es den Push-Handlern
  (Energie, Kamera, Verlauf, Werte, Audio) wie eine Pane 2. Das Raster bleibt
  beim Profil (keine Verdopplung, auch nicht hochkant), eine Widget-Seite hat
  keine Sprungmarken. Den Verbindungspunkt blendet sie aus wie die Kalender-
  und Wetter-Seite, er säße sonst mitten im Widget. Geprüft in
  `test_widget_seite_quer_und_hochkant` (quer, hochkant, quadratisch).
- Pane 2 nutzt ihre Fläche (Oktober 2026): Wie groß die zweite Fläche ist,
  hängt von Split, Raster, Lage und Gerät ab (gemessen von 240×403 bis
  778×723). Wetter, Kalender und Werte messen deshalb nach dem Zeichnen und
  bei jeder Größenänderung von `#frontpane` nach (`ResizeObserver` →
  `paneEinpassen()`) und setzen Stufen wie `fitTile()` bei den Kacheln.
  Container-Queries kämen ohne JS aus, gibt es aber erst ab Chrome 105.
  - Wetter (`wetterEinpassen()`): Seite 1 ist so hoch wie die Fläche. Die
    Kurve nimmt den Rest (`flex:1 1 0`) und wird in genau dieser Größe
    gezeichnet (`fpCurve(hourly, W, H)`), ihre Zahlen sind echte 11 px; Uhr-Seite
    und Wetter-Tab zeichnen weiter 700×150 und skalieren. Breiter als 1,45 × hoch
    (`PANE_BREIT`) stehen Lage und Kurve nebeneinander (`.breit`), schmaler als
    380 px (`WX_SCHMAL`) die Beschreibung unter der Temperatur und die Vorschau
    zum Wischen (`.schmal`). Die Details stehen einmal im Dokument: unter der
    Vorschau, wenn der Kurve dann noch 96 px bleiben (`WX_KURVE_MIN`), sonst
    auf Seite 2. Bleiben ihr weniger als 64 px (`WX_KURVE_KNAPP`) oder ragt ein
    Teil aus seinem Feld, rückt die Lage zusammen und „Heute hoch/tief“
    entfällt, das in der Vorschau steht (`.eng`). Eng bleibt auch das Datum der
    Vorschau einzeilig: Ein zweistelliges („Sa 10.10.“) bräche sonst um und machte
    die Vorschau eine Zeile höher. Wo es nicht in seine Zelle passt, verkleinert
    `vorschauDatumEinpassen()` es genau so weit, wie die Zelle verlangt. Beschriftet ist jeder dritte
    Punkt, auf schmaler Kurve seltener (mindestens 26 px Abstand).
  - Kalender (`kalenderEinpassen()`): eine Seite, unter dem Monat die Termine
    (`.kal-liste`, scrollt für sich, ohne zweite Legende). Ein Tipp auf einen
    Tag zeigt dessen Termine gleich darunter; beim Blättern im Monat bleibt
    die Liste stehen. Nebeneinander (`.breit`), wenn zwei Spalten à 220 px
    passen (`KAL_SPALTE_MIN`) und die Fläche breit ist oder darunter weniger
    als 160 px blieben (`KAL_LISTE_MIN`). Passt der Monat nicht, rücken die Tage
    in zwei Stufen zusammen (`.eng`, `.eng2`).
  - Werte (`renderWertePane()`, `werteEinpassen()`): gerahmt wie die anderen
    Widgets, die Zeilen teilen sich die Höhe, Symbol und Schrift wachsen mit
    der Zeilenhöhe (`--zh`). Ab 80 px (`WERTE_HOCH`) steht der Wert groß unter
    Symbol und Name. Reicht die Höhe nicht (acht Werte), scrollt die Pane wie
    bisher. Die Uhr-Seite zeichnet dieselben Zeilen ohne Rahmen
    (`renderSvStatus()`, `svStatusZeilen()`).
  - Energiefluss, Kamera, Audio und Verlauf füllten ihre Fläche schon.

  Vorher, gemessen am Tab A9: Wetter quer mit 3 × 3 und „Bildschirm füllen“
  59 px leer unter der Vorschau; mit „Automatisch“ quer die Beschreibung zu
  einer Spalte gequetscht und die Vorschau seitlich abgeschnitten, hochkant
  unten abgeschnitten. Kalender 30 % leer, die Termine auf Seite 2; zwei Werte
  69 % leer. Geprüft in `tests/browser/test_pane_hoehe_browser.py`.
- Kopfzeile (Widget `"header"`, Oktober 2026): Statt einer Pane daneben eine
  Zeile **über** dem Kachelraster mit Uhr, Wetter in Kurzform (Symbol,
  Temperatur, Lage, „Heute hoch / tief“) und nach Wahl Werten
  (`"header:<uuid>,…"`, bis `SV_STATUS_MAX`). Das Vorbild ist die Startseite
  der Loxone-App; auf einem Tablet quer nimmt die Zeile 64 px statt der 40 %
  eines Widgets. `applyPane()` setzt `.kopf` am `.screen` (dritte Grid-Zeile,
  volle Breite), nicht `.split`: das Raster bleibt ungeteilt, „Screen füllen“
  verdoppelt weiter, hochkant ändert sich nichts. Die Höhe steht als
  `--kopf-h` am `.screen`; `autoRaster()` zieht sie über `kopfHoehe()` von der
  freien Höhe ab, bevor die Klasse gesetzt ist, damit die Zeilenzahl stimmt.
  Beim festen Raster geht sie vom Kasten ab (4″ 2×2: Kacheln 225×166 statt
  225×198). `renderKopfzeile()` baut die Zeile aus `frontData` (Wetter) und
  `svStatusData` (Werte, angemeldet wie bei „Werte“ per `setsvstatus`, der
  Server schickt `{t:"svstatus"}` über `status_blocks()`), `tickClock()`
  stellt die Uhr. Was rechts nicht mehr in die Zeile passt, blendet
  `kopfEinpassen()` aus, bei jeder Größenänderung neu. Weil sie keine Pane
  ist, gilt sie auch mit Split „Aus“ (4″-Panel): `paneRawNow()` lässt
  `header` an `themeSplit` vorbei, der Konfigurator zeigt das Feld „Widget je
  Tab“ dann mit gesperrter Widget-Gruppe, der Assistent bietet für 1 Pane
  „Kopfzeile je Tab“ an. Die Kopfzeile gibt es nur je Tab: Widget-Seite
  (`_clean_widget_tab()`) und Uhr-Seite (`_clean_svpane()`) nehmen sie nicht
  an, der Konfigurator bietet sie dort nicht an. `ui.panes` wird beim
  Speichern, im Export und in `resolve_profile()` **normiert** abgelegt
  (`"header:A, B"` → `"header:A,B"`), nicht roh; vorher hätte das Panel
  `" B"` als UUID gemeldet. Geprüft in `tests/test_kopfzeile.py` und
  `tests/browser/test_kopfzeile_browser.py` (quer, hochkant, 10″, 4″ mit
  Split „Aus“, zu viele Werte, Drehen, Konfigurator mit und ohne Split,
  Assistent).
- Sprungmarken: Besteht die untere Leiste aus einem einzigen Raum-Tab
  (`room:`) oder einer einzigen freien Seite, ersetzt `view.catTabs` die Tabs
  durch Marken (Raum-Panel: Kategorien des Raums, freie Auswahl: ihre Räume;
  `isRoomPanel()`). Die Kacheln stehen nach Gruppe sortiert, die erste jeder
  Gruppe trägt `catKey` als Anker, jede Kachel `grp` (Kategorie bzw. Raum).
  Ein Tipp springt (Standard) oder filtert (`ui.catFilter`, im Konfigurator
  „Tipp auf eine Sprungmarke“). Springen geht auf die **Seite**, auf der die
  Gruppe beginnt (`springeZu()`): die Kachelfläche rastet seitenweise ein
  (`scroll-snap-type: y mandatory`, Rastpunkt = erste Kachel jeder Seite), und
  ein Sprung direkt auf eine Kachel im unteren Teil einer Seite landete am
  nächstgelegenen Rastpunkt, oft schon auf der folgenden Seite. Die Zielkachel
  verschwand dann oben (gemessen 2×2: 199 px, 2×3 hochkant: 210 px über dem
  sichtbaren Bereich). Danach leuchten die Kacheln der Gruppe 1,5 s auf
  (`leuchte()`, Klasse `.katleucht`), damit ein Tipp auch dann sichtbar wirkt,
  wenn die Gruppe schon im Bild steht. Filtern (`katTipp()`, `katSichtbar()`)
  zeigt nur die Kacheln mit diesem `grp` und markiert die Marke; ein zweiter
  Tipp zeigt wieder alle. Der Filter gilt auch für die Live-Updates
  (`updateGrid()` bekommt die gefilterte Liste), aus einer Detailansicht führt
  ein Tipp zurück in die gefilterte Seite, und nach Ruhe (`nachRuhe()`) fällt
  er weg. Geprüft in `tests/test_sprungmarken.py` und
  `tests/browser/test_sprungmarken_browser.py`.
- Screensaver-Uhr nach 60 s, Start immer mit Uhr. Weckton synthetisch per Web
  Audio (880 Hz). PIN-Ziffernblock für `isSecured`-Controls: Jeder Befehl läuft
  über `sendCmd()` (nur `cmdSchicken()` baut die Nachricht, `tests/test_pin.py`
  wacht darüber). `secured` setzt `render()` für jede Seite des Bausteins, auch
  die Unterseiten, `_pane_msg()` für Player- und Kamera-Bereich. Eine bestätigte
  PIN gilt `ui.pinMerken` Sekunden (Standard `PIN_MERKEN_STANDARD`) auf derselben
  Seite; Uhr-Seite, Display aus, Nachtbeginn und Seitenwechsel vergessen sie.
  Display aus heißt auch mit Agent nach `dpmsOff` ohne Eingabe (`armDpms()`,
  X schaltet dann selbst ab); die LoxPanel-App dunkelt erst nach der Uhr-Seite
  ab. Ohne gemerkte PIN wirkt eine Halten-Taste wie ein Tipp. Wisch nach rechts =
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
- Freie Auswahl: bis zu vier Seiten je Panel (`pickTabs`, Tabs `auswahl` bis
  `auswahl4`), je Seite Name, Icon und Inhalt (Kacheln in Klickreihenfolge
  oder ein Widget). `/api/meta` muss `pickTabs` mitliefern: Fehlt es, kennt der
  Editor nach dem Neuladen nur eine Seite und kürzt beim nächsten Speichern
  die Leiste (so geschehen vor #47). Geprüft über Speichern, Neuladen,
  Weiterbearbeiten und die Visu in `tests/browser/test_auswahl_seiten_browser.py`.
- Reiter Displays: Die Geräteliste fragt `GET /api/devices` alle 6 s ab, von
  dort gehen „Ansicht wechseln" (`/api/device/switch`) und „Namen vergeben"
  (`/api/device/name`). Der Editor darunter speichert Modi, Display-Treiber,
  Skalierung und Präsenzmelder über `POST /api/devices`. Das Display-Kennwort
  bekommt er nicht, nur `hasPass`: Das Feld bleibt leer und zeigt „unverändert
  lassen“, solange Treiber und Host dem gespeicherten Ziel entsprechen
  (`pwHinweis()`, dieselbe Regel wie `_KENNWORT_ZIEL` im Server), sonst
  „Passwort (Fully)“, auch gleich nach dem Speichern. Verwirft der Server ein
  Kennwort wegen eines anderen Ziels, bleibt eine Warnung stehen (`flash()`
  blendet eine Leiste mit `warn` nicht aus). Ein gespeichertes Kennwort
  löschen geht nur über ein anderes Ziel. Geprüft in
  `tests/browser/test_displays_browser.py` und `tests/test_geraete_kennwort.py`.
- Textfelder brauchen `type="text"`: Der dunkle Feldstil hängt an
  `input[type=text|number|password]`, ein Feld ohne `type` steht sonst
  browserweiß im dunklen Konfigurator.
- Eigene Icon-Map `BICONS` (20 Icons, `fan` und `list` fehlen gegenüber der Visu).
- Overlay-Vorschau rechnet die Alphas selbst nach (`ovPreview()`), parallel zur
  Server-Logik `_overlay_alphas()`.

### 7.3 Rubrik „Settings" in `config.html` (früher `settings.html`)

Die frühere Einstellungsseite liegt als zweite Rubrik im Konfigurator; die
Speicherleiste unten gilt nur für „Panel Configuration". Sieben Reiter:
Miniserver (mit Link auf `/api/types`), Kamera/Türstation, SIP (Zugang je
Intercom aus dem Miniserver, „Verbindung prüfen“; lädt erst beim Öffnen,
`loadSip()`), Audio (Testton, Audioserver-Live-Daten), Kalender & Wetter
(iCal-Abos, Wetter der Uhr-Seite), Neues Panel (Start-URL für Kiosk-Apps,
SSH-Befehl für Linux-Panels), Sicherung (Herunterladen und Einspielen). Die
Anzeigegeräte stehen in der eigenen Rubrik „Displays". Zu einem Reiter führen
die Kacheln der Übersicht (`data-goto="settings:<reiter>"`) oder die
Reiterleiste; einen Anker in der URL (`/config#panels`) wertet die Seite nicht
aus, sie öffnet die Übersicht (ohne Struktur Settings → Miniserver, siehe
unten). Kein Dirty-Flag, ungespeicherte Eingaben gehen beim Verlassen verloren.

**Ersteinrichtung.** Solange der Server keine Struktur vom Miniserver hat
(`einrichtung` aus `/api/settings`), führt der Konfigurator zuerst zum Zugang:

- Er öffnet Settings → Miniserver mit einem Hinweis samt Stand: noch kein
  Zugang, gespeicherter Zugang nicht verbunden, Verbindung wird aufgebaut,
  Fehler des Servers oder des eigenen letzten Versuchs.
- Gesperrt sind die übrigen Rubriken, die Profil-Liste, „＋ Neues Panel" und
  die Settings-Reiter außer Miniserver und Sicherung (`EINR_SUBS`): Profile,
  Displays und der Assistent brauchen Räume und Bausteine. `setRubric()` leitet
  jeden anderen Weg zu Settings um, `showSub()` und `wzOpen()` lehnen ab.
- Den Stand fragt er alle `EINR_TAKT_MS` (3 s) nach. Steht die Verbindung, über
  „Verbinden & Speichern" oder von selbst, lädt die Seite neu, damit alles frisch
  vom Server kommt, und zeigt „Mit dem Miniserver verbunden" mit den nächsten
  Schritten (Einrichtungsassistent, Sicherung einspielen; Merker
  `lp_einrichtung_verbunden` in der `sessionStorage`).

Die Karte am Panel kommt aus derselben Quelle (`_einrichtung_stand()` baut auf
`_einrichtung_info()` auf), erscheint aber nicht während des ersten Versuchs,
damit beim normalen Start nichts aufblitzt. Geprüft in
`tests/browser/test_einrichtung_konfigurator_browser.py`.

### 7.4 `i18n.js`

Schlüssel ist der deutsche Quelltext, Katalog nur `en`. Drei Wege: `data-i18n`
auf statischem Markup, `T('...')` im JS, und `autoChrome()` mit
`MutationObserver` für per `innerHTML` erzeugte Texte. Sprachwahl über
`localStorage['lp_ui_lang']`, sonst Browser-Sprache. Der Konfigurator bietet
sechs Panel-Sprachen an, der Katalog kennt zwei.

Zwei Fallen: `autoChrome()` übersetzt nur Elemente ohne Kind-Elemente; ein
Text neben einem Link oder mit `<b>` braucht `data-i18n` (dann ersetzt
`apply()` den ganzen Text) oder `T()`. Und jeder Aufruf von `autoChrome()`
ersetzt die Selektor-Liste für die ganze Seite; für einen Teilbaum gibt es
`applyChrome()`. Bei doppeltem Schlüssel gilt wie in JS der spätere Eintrag.
`tests/test_uebersetzung.py` prüft, dass jeder `T()`-Text und jedes
`data-i18n`-Element in `config.html` einen englischen Eintrag hat und kein
Schlüssel zwei verschiedene Übersetzungen. Was auf Englisch noch deutsch
bleibt, steht in `TODO.md` („Konfigurator auf Englisch vervollständigen“).

---

## 8. Panel-Agent

`agent/loxpanel-agent.py`, reine Standardbibliothek, läuft auf dem Wandpanel als
Login-Benutzer aus `~/.xsession`.

**Eingehend:** HTTP-Server auf `0.0.0.0:8130` ohne Authentifizierung mit
`GET /status`, `POST /start` (mit optionalem `panel`), `POST /reload`, `POST /stop`.
Mehr kennt der Agent nicht. `goto`, `notify` und `reload` als Push-Aktionen laufen
über den Server direkt an den Browser.

**Ausgehend:** alle 15 s (`AGENT_MELDETAKT` im Server) `POST /api/agent/announce`
mit `{name, panel, ip, port, kiosk, features}`. Die Antwort trägt `dpmsOff` und
`reloadHours` aus dem Panel-Profil, die der Agent lokal anwendet. Steht `panel`
darin, übernimmt der Agent diese Ansicht ohne Chromium-Neustart in `_cur_panel`
und die State-Datei und meldet sie ab dann; `features: ["panel"]` sagt dem
Server, dass er das kann.

**Ansicht wechseln unter Displays:** Die Visu wechselt per WebSocket-Push (lädt
sich mit `?panel=` neu). Bis Oktober 2026 erfuhr der Agent davon nichts: Er
meldete weiter das alte Profil, bekam dessen Abschaltzeit und Neustartintervall,
und jeder Kiosk-Neustart (Auto-Reload, Reload, Absturz, Neustart des Panels)
öffnete die alte Ansicht. Heute merkt sich der Server die Wahl für den Agenten
der Zeile (`agent_wunsch`, über die IP, weil geklonte Panels denselben
Hostnamen melden) und gibt sie ihm mit der nächsten Antwort; ältere Agenten ohne
`features` bekommen wie früher `/start` mit dem neuen Profil, also einen
Chromium-Neustart. Ein Agent, der seit `AGENT_ONLINE` (vier Meldetakte) nichts
gemeldet hat, bekommt nichts. Ein Betriebsmoduswechsel gibt das Profil ebenso
an Agenten mit `features` weiter, über den Namen, weil die Zuordnung in
`panels.json` am Namen hängt; `/start` bekommt auch dort nur ein Agent, der
online ist. Zieht `ws_handler()` ein frisch verbundenes Chromium auf das Profil
des laufenden Betriebsmodus, weil der Agent beim Wechsel nicht da war, bekommt
der Agent das Profil ebenso (`_agenten_der_visu()`: der mit der IP der
Verbindung, sonst die mit dem Namen, die online sind); ein älterer Agent ohne
`features` erfährt davon nichts. „Start“ unter Displays
ist eine ausdrückliche Wahl wie „Ansicht wechseln“ und hebt `last_mode` für
das Gerät auf; bei gestopptem Kiosk ist es der einzige Weg dazu. Ein „Reload“
vor der nächsten Meldung startet mit der neuen Ansicht. Startet Chromium in
dieser Zeit anders neu (Absturz, Auto-Reload, Neustart des Agenten), fragt es
noch nach der alten Ansicht; `ws_handler()` zeigt dann die offene Wahl, die der
Agent mit seiner nächsten Meldung übernimmt. Eine Wahl bleibt in
`agent_wunsch`, bis der Agent sie meldet, auch wenn ein Befehl an ihn
scheitert. Geprüft in `tests/test_agent.py` und
`tests/browser/test_displays_browser.py`.

**Konfiguration:** erste existierende Datei aus `$LOXPANEL_KIOSK_CONF`,
`../deploy/loxpanel-kiosk.conf`, `/etc/loxpanel/kiosk.conf`. Umgebungsvariablen
`LOXPANEL_<KEY>` haben Vorrang. Schlüssel: `SERVER`, `AGENT_PORT`, `AGENT_NAME`,
`PANEL`, `AUTOSTART`, `X`, `DPMS_OFF`, `PROFILE_DIR`, `BL_DEVICE`, `BL_ON`,
`PAUSE_ON_BLANK`, `RELOAD_HOURS`, `STATE_FILE`, `KIOSK_RESTART_SECS`,
`KIOSK_RESTART_MAX_SECS`. Die Beispieldatei dokumentiert alle außer
`PROFILE_DIR` und `BL_DEVICE`.

**Funktionen:** Chromium-Kiosk mit festen Flags, Crash-Dialog-Bereinigung in
`Default/Preferences`, DPMS über `xset`, echte Backlight-Abschaltung über alle
`/sys/class/backlight/*/brightness`, optionale SIGSTOP-Pause (Default aus, weil
der WebSocket dabei stirbt), periodischer Kiosk-Neustart (nur mit Antwort des
Servers), Neustart nach Absturz, Panel-Wahl in einer State-Datei.

**Panel-Wahl:** `STATE_FILE`, Standard nach XDG
`$XDG_STATE_HOME/loxpanel/agent-state.json` (ohne absoluten Wert
`~/.local/state/…`), also beim Benutzer, unter dem der Agent läuft. Bis
Oktober 2026 lag sie neben der kiosk.conf in `/etc/loxpanel/`, das der Installer
als root anlegt; das Schreiben scheiterte leise, die Wahl überlebte keinen
Neustart (F13). Eine Datei von dort übernimmt der Agent beim Start einmal und
löscht sie danach, sonst brächte das Löschen der neuen Datei (Weg zurück auf
`PANEL`) die alte Wahl zurück; scheitert das Speichern am neuen Ort, bleibt sie.
Vorrang: `LOXPANEL_PANEL`, dann die gemerkte Wahl (auch `""` = Standardansicht),
dann `PANEL`. Die Datei hält auch `PANEL` beim Merken (`conf`); steht in der
kiosk.conf inzwischen etwas anderes, gilt die kiosk.conf. Woher die Ansicht
kommt, nennt die Startzeile des Agenten. Schreibfehler meldet er mit Pfad und
uid; die Ausgabe ist zeilengepuffert, damit sie gleich in `~/.xsession-errors`
steht.

**Neustart nach Absturz:** Je Chromium-Start wartet ein Thread
(`_kiosk_waechter`) auf genau diesen Prozess. Endet er, ohne dass `stop_kiosk()`
ihn beendet hat (dann ist `_proc` nicht mehr dieser Prozess), startet der Agent
nach `KIOSK_RESTART_SECS` (Standard 5 s wie `RestartSec=5` der Dienstdateien,
0 = aus) mit derselben Ansicht neu, auch ohne Server. Jedes Ende zählt, auch
Code 0 (Alt+F4). Stürzt Chromium wieder ab, bevor es länger als die doppelte
Obergrenze lief, verdoppelt sich die Pause bis `KIOSK_RESTART_MAX_SECS`
(Standard 300 s wie Kubernetes bei CrashLoopBackOff); die Obergrenze liegt über
`DPMS_OFF`, weil jeder Start per `xset` den Leerlaufzähler zurücksetzt. Ein
Befehl von Hand (`/start`, `/reload`, `/stop`) fängt wieder bei
`KIOSK_RESTART_SECS` an, ebenso der Auto-Reload (bis dahin lief der Kiosk
`RELOAD_HOURS` ohne Absturz); die Laufzeit misst der Wächter mit `time.monotonic()`,
weil Panels ohne Echtzeituhr die Uhr beim Booten per NTP stellen.
`start_kiosk()` läuft ganz unter einer `RLock`, die Prüfung des Wächters auch;
die Pause selbst hält sie nicht, `/start` und `/stop` warten also nicht.
Erfasst wird nur das Ende des Browser-Prozesses, ein abgestürzter Tab
(Renderer) bei laufendem Browser nicht. Geprüft in `tests/test_agent.py`.

**Installation:** `deploy/install-agent.sh`, als Login-Benutzer ohne sudo
aufrufen. Der Agent-Quelltext ist dort als Heredoc eingebettet, nicht kopiert.
Der Code ist derzeit identisch mit `agent/loxpanel-agent.py`, die Kommentare
weichen bereits ab. Der Server liefert ausgerechnet diese Kopie über
`/install-agent.sh` aus. `tests/test_agent.py` vergleicht beide per AST und
schlägt fehl, sobald der Code auseinanderläuft.

**Ohne Agent (Android):** Seit dem Umbau-Schritt 1 schickt der Server `dpmsOff`,
`reloadHours` und `agent` mit der `theme`-Nachricht an die Visu. Meldet der
Server keinen Agenten für die Gerätekennung, schaltet die Seite das Display
selbst über die JavaScript-Schnittstelle von Fully Kiosk Browser
(`window.fully`), weckt es bei Klingel, Wecker, Notify und Goto und lädt sich
gegen Einfrieren neu (siehe unten). Der Agent hängt dafür `device=<Name>` an die
Kiosk-URL, damit der Server Agent-Panels am WebSocket erkennt
(`App._has_agent`). `App.device_list()` führt Agenten, verbundene Browser und
konfigurierte Geräte über den Namen zusammen; die Einstellungen zeigen daraus
eine Liste mit Typ, Online-Status, Ansicht und Aktionen (Ansicht wechseln,
Neu laden, Display aus/an). Browser ohne Kennung werden nach IP gelistet und
können benannt werden. Die Visu meldet ihre Kiosk-App in der WebSocket-URL,
`kiosk=fully` in Fully Kiosk und `kiosk=loxpanel` in der LoxPanel-App; der
Server übernimmt nur diese beiden (`KIOSK_APPS`), alles andere gilt als
Browser.

**LoxPanel-App:** Die App (`android/`) stellt der Visu `window.LoxKiosk` bereit,
mit `turnScreenOn`, `turnScreenOff` und `isScreenOn` wie bei Fully. `KIOSK_APPS`
in `panel.html` ordnet jeder Kiosk-App ihre Schnittstelle zu; `kioskKind()` und
`kiosk()` finden die vorhandene, Display wecken und ausschalten laufen damit für
beide gleich. Unterschied: Die App hat einen eigenen Bildschirmschoner. Die
Visu schaltet dort nicht selbst nach der Leerlaufzeit ab (`armDpms()` kehrt
sofort zurück), sondern gibt der App die Zeit (`setDisplayOff(dpmsOff)`, bei
Anwesenheit 0, `appLeerlauf()`), meldet ihr die Uhr-Seite (`setSaver`) und
senkt nachts die echte Helligkeit statt der dunklen Auflage
(`setDisplayBrightness`, `appHelligkeit()`; lehnt die App ab, etwa bei
automatischer Helligkeit, bleibt es bei der Auflage). Geprüft mit
nachgebauter Brücke in `tests/browser/test_loxkiosk_browser.py`,
`test_praesenz_app_browser.py` und `test_nacht_app_browser.py`.

**Neu laden gegen Einfrieren (ohne Agent):** `reloadHours` aus dem Profil
(*Auto-Neustart alle (Std.)*) kommt mit der `theme`-Nachricht, `null` heißt
nicht eingestellt. Dann lädt die Visu einmal je Nacht neu, sobald es nach dem
Laden der Seite `reloadAt` Uhr geworden ist (`NEULADEN_STUNDE` im Server, 3 Uhr;
`/api/meta` gibt sie dem Konfigurator für das leere Feld und den Hinweis). Eine
Zahl lädt so viele Stunden nach dem Laden neu, 0 nie, mit Agent ebenfalls nie
(der startet den Browser selbst neu). `neuladenPruefen()` schaut jede Minute
nach und lädt nur, während die Uhr-Seite steht (`saverOn()`), also nie unter
den Fingern. Die neue Seite startet mit der Uhr und weckt nicht: In der
LoxPanel-App meldet sie nur `setSaver(true)` und die Leerlaufzeit, ein dunkles
Display bleibt dunkel. Bis Oktober 2026 lud die Seite ohne Eintrag nie neu, mit
einer Zahl per `setTimeout` auch mitten in der Bedienung, und jede neue
Verbindung setzte die Frist zurück. Geprüft mit gestellter Uhr in
`tests/browser/test_neuladen_browser.py`, Server-Seite in
`tests/test_neuladen.py`.

**Stabilität der App:** Der Server-Dienst (`ServerService`) startet Server und
Wächter je Prozess einmal (Anzeige, BootReceiver und Android starten den Dienst
mehrfach). Der Wächter fragt `/api/health` alle 30 s. Nach drei Fehlschlägen in
Folge (keine Antwort oder 503, weil eine Hintergrund-Aufgabe endete) beendet er
den Prozess; Android startet Dienst (`START_STICKY`) und Anzeige
(`stateNotNeeded`) neu. Hat der Server seit dem Start noch nie geantwortet,
wartet er bis zu 5 Minuten. Höchstens 3 Neustarts je Stunde, die Zeitpunkte
liegen in den Einstellungen der App (`waechter`). Die Anzeige (`KioskActivity`)
baut nach einem Renderer-Absturz eine neue WebView auf
(`onRenderProcessGone`, ab Android 8), statt dass Android die App beendet; einen
hängenden Renderer beendet sie ab Android 10 nach 6 Meldungen in Folge
(`WebViewRenderProcessClient`, frühestens alle 5 s). Die Regeln stehen ohne
Android in `Waechter.kt`, Unit-Tests in `WaechterTest.kt`.

**Display-Treiber (Schritt 3):** `App.display_drivers(on, device, panel)`
spricht je Gerät die HTTP-Schnittstelle der Kiosk-App an (`_drive_display`):
Fully Kiosk Remote Admin per `GET /?cmd=screenOn|screenOff&password=`,
WallPanel per `POST /api/command {"wake": true|false}`. Konfiguration in
`panels.json` unter `devices[name].display`, Konstante `DISPLAY_DRIVERS`.
Aufrufer: `/api/display` (wartet auf das Ergebnis), Klingel und Wecker im
`broadcaster`, `/api/notify` und `/api/goto` (im Hintergrund, `_spawn`),
sowie die `idle`-Meldung der Visu. Einrichtung in `deploy/ANDROID.md`.

**Präsenzmelder je Gerät:** `devices[name].presence` nennt einen Baustein mit
`active`-State (Präsenzmelder, aber auch Schalter oder digitaler Status; die
Auswahl ist dieselbe wie beim Nacht-Auslöser, `night_control_options()`).
`_presence_rebuild()` bildet nach dem Einlesen der Struktur und nach dem
Speichern der Geräte die State-UUID auf die Geräte ab (`presence_map`) und
führt den Stand je Gerät (`_presence_on`). Ersetzt jemand `devices` oder
`controls`, ohne das aufzurufen (das Einspielen einer Sicherung), holt es der
Broadcaster im nächsten Takt nach: `_presence_quelle` hält fest, aus welchen
beiden Objekten die Zuordnung gebaut ist. `_on_value()` reagiert nur auf einen
echten Wechsel, der Neuversand aller States nach einem Reconnect schaltet also
nichts. Der Broadcaster schickt `{t:"display", on, presence}` an die
Verbindungen genau dieses Geräts und schaltet dessen Display-Treiber mit;
`presence` steht außerdem in der `theme`-Nachricht, damit ein neu geladenes
Panel nicht trotz Anwesenheit abschaltet. Solange `presence` gilt, setzt die
Visu `armDpms()` aus, und der Server ignoriert ihre `idle`-Meldung. Aus schaltet
nur der Melder selbst, wenn der Raum leer wird: Wird ein Melder gewählt,
während jemand da ist, weckt das Speichern das Gerät; wird er entfernt, fällt
nur das Halten weg (`on: true, presence: false`), danach gilt wieder die
Leerlaufzeit. Linux-Panels mit Agent schalten ihr Display per DPMS selbst,
dort wirkt der Melder nicht. Geprüft in `tests/test_praesenz.py` und
`tests/browser/test_praesenz_browser.py`.

---

## 9. LoxBerry-Plugin, Unraid, Build und Release

### 9.1 LoxBerry-Plugin

Das Plugin ist nur ein Docker-Starter. `loxpanel-ctl.sh` kennt `start` (pull +
up), `stop` (Marker-Datei + down), `restart`, `check` (Cron alle 5 min und beim
Boot), `backup` und `restore` (tar.gz des Config-Ordners, erzeugt im Container
als root, Rotation nach `KEEP` im Skript, das Widget fragt die Zahl über
`loxpanel-ctl.sh keep` ab). Das Widget `index.cgi` (Perl) spricht
`http://localhost:8099/api/settings` und `/api/settings/miniserver`. Von dort
zeigt es `error` und darunter `fehler`, `gespeichert` (nicht erreichbar,
trotzdem gespeichert) als Warnung. Eine Antwort mit JSON ist immer eine Meldung
des Servers, auch mit 400 oder 500; „Container nicht erreichbar" heißt es nur
ohne JSON. Die Texte des Servers kodiert es vor der Ausgabe nach UTF-8: `decode_json`
liefert Zeichen, die Seite geht aber ohne Kodierungsschicht als Bytes hinaus.
„Aus LoxBerry übernehmen" ohne Benutzer in der LoxBerry-Konfiguration
meldet das selbst (`tests/test_loxberry_widget.py`).

`backup` schreibt ein Archiv erst als `.part`, liest es ganz zurück und benennt
es danach um, das Widget bietet also nie ein halbes Archiv an; ein vorhandenes
ersetzt es nie, ein leerer Config-Ordner ergibt keins. `restore` ändert
`config/` erst, wenn alles andere gelungen ist: Das Backup wird in einen
Zwischenordner neben `config/` entpackt (`.restore.*`, gleiches Dateisystem) und
muss vollständig sein und `loxpanel.cfg`, `panels.json` oder `theme.json`
enthalten. Dann hält das Skript den Container an, sichert den Ist-Stand als
`…-vor-restore.tar.gz` (scheitert das, bricht es ab) und tauscht nur durch
Umbenennen; scheitert ein Schritt des Tauschs, kommt der Ist-Stand zurück.
Danach startet das Skript den Container mit `docker restart` neu, so liest der
Server die Konfiguration auch dann frisch ein, wenn ihn in der Lücke jemand
gestartet hat. Dateinamen gehen als Argument in den Container, nie in den
Befehlstext. Eine Sperre (`flock` auf `.loxpanel-ctl.lock` im Datenordner)
lässt keine zwei Läufe gleichzeitig zu, der zweite bricht sofort ab; Reste
eines abgebrochenen Laufs räumt der nächste weg. Auch `check` nimmt sie und
überspringt die Prüfung, solange eine Sicherung oder Wiederherstellung läuft,
statt den für den Tausch angehaltenen Container zu starten. Das Skript öffnet
die Sperrdatei nur lesend, so sperrt auch eine, die ein Lauf als root angelegt
hat. Bricht der Tausch hart ab (Stromausfall zwischen den Umbenennungen), kann
`config/` leer oder gemischt sein, und der nächste Lauf räumt den
Zwischenordner samt bisherigem Stand weg. Verloren ist er nicht: Er liegt
schon vor dem Tausch als `…-vor-restore.tar.gz` auf der Platte und lässt sich
im Widget wiederherstellen.
`tests/test_loxberry_ctl.py` führt das echte Skript aus, `docker` und `sudo`
ersetzt der Nachbau in `tests/loxberry.py`.

Bei einem Plugin-Update löscht LoxBerry zwischen `preroot.sh` und
`postroot.sh` den ganzen Datenordner (`purge_installation` in
`plugininstall.pl`). `preroot.sh` kopiert deshalb `backups/` nach
`/tmp/loxpanel-upgrade-archive` (vor dem Stoppen des Containers) und `config/`
nach `/tmp/loxpanel-upgrade-backup`, `postroot.sh` spielt beide zurück und
löscht eine Zwischenkopie erst, wenn sie ganz zurückgespielt ist (sonst Exit 1,
LoxBerry meldet es). Scheitert die Kopie der Konfiguration, endet `preroot.sh`
mit 2: LoxBerry bricht ab, bevor es etwas löscht, die Plugin-Datenbank nennt
dann allerdings schon die neue Version. Scheitert nur die der Archive, warnt
es (`<WARNING>`, Exit 1) und das Update läuft weiter. Fehlt `config/` beim
nächsten Update (ein früheres ist nach dem Löschen abgebrochen), bleiben die
Zwischenkopien stehen und `postroot.sh` spielt sie zurück; sonst ersetzt der
aktuelle Stand sie. `/tmp` ist auf dem LoxBerry eine RAM-Disk: Startet er
zwischen `preroot.sh` und `postroot.sh` neu, sind die Kopien weg.
`tests/test_loxberry_update.py` spielt den Ablauf von `plugininstall.pl` nach.

Zeitzone: Der Server rechnet Termine, „Heute/Morgen", Nachtmodus, Statistik und
Wecker in der Ortszeit des Prozesses. `start` schreibt deshalb jedes Mal
`docker-compose.zeitzone.yml` neben die Compose-Datei und startet mit beiden:
`/etc/localtime` des LoxBerry nur lesend nach `/run/loxberry-localtime`, dazu
`TZ=":/run/loxberry-localtime"` (glibc liest die Zone aus der Datei). Nicht nach
`/etc/localtime` im Container: Dort liegt ein Symlink auf `Etc/UTC`, Docker
folgte ihm und überschriebe die UTC-Zone selbst, dann läse icalendar `Z`-Zeiten
falsch. Ist `/etc/localtime` keine Datei (fehlt, toter Symlink), entfällt die
Override-Datei mit Warnung, der Container läuft in UTC; sonst verhinderte der
Mount den Start oder Docker legte am LoxBerry ein Verzeichnis an. Eine
geänderte Zone gilt nach dem nächsten Start des Containers
(`tests/test_loxberry_zeitzone.py`).

`sudoers` erlaubt dem Benutzer `loxberry` `docker` ohne Passwort, was faktisch
Root-Rechte auf dem LoxBerry bedeutet.

### 9.2 Unraid

Template `unraid/loxpanel.xml`, Anleitung `deploy/UNRAID.md`. Start/Stop, Update
und Backup übernimmt Unraid. Was das LoxBerry-Widget an Funktionen hat, gibt es
auf Unraid über `/config` (Settings, dort auch *Sicherung* = `/api/backup` und
`/api/restore`) und den appdata-Ordner.

- **Zustand:** `HEALTHCHECK` im Dockerfile ruft alle 30 s `/api/health` auf
  (Python statt curl, das slim-Image hat kein curl); Unraid zeigt healthy /
  unhealthy im Docker-Tab. `tests/test_rauchtest.py` führt genau diesen Befehl
  aus dem Dockerfile aus.
- **Log:** `LOXPANEL_LOG_LEVEL` (`DEBUG`, `INFO`, `WARNING`, `ERROR`; Standard
  `INFO`, Unbekanntes → `INFO` mit Warnung). Der Zugriffs-Log von aiohttp (eine
  Zeile je Anfrage) erscheint nur bei `DEBUG` (`_logging_einrichten()`). Fehlt
  ein optionales Paket aus `requirements.txt` (`icalendar`, `python-dateutil`,
  `cryptography`), läuft der Server ohne die Funktion dahinter weiter und nennt
  beides einmal beim Start als Warnung (`_fehlende_pakete_melden()`).
- **Image:** `.dockerignore` hält Altlasten (`webfrontend/htmlauth`,
  `config/visu.*`, `daemon/` …) und Test-/Entwicklungsdateien aus dem Image.

### 9.3 Build und Release

| Workflow | Trigger | Ergebnis |
|---|---|---|
| `tests.yml` („Tests und Image“) | jeder PR, Push auf `main`, Tags `v*`, manuell | Syntax (alle `bin/*.py`, Workflows, Unraid-Vorlage), `ruff` mit Fehlerregeln (`F`, `E9`), pytest ohne Browser inkl. Rauchtest, Browser-Tests in Chromium (Screenshots als Artefakt), bei PRs Probe-Build des Images für amd64 ohne Push. Danach, nur auf `main` und bei Tags `v*` und nur, wenn beide Test-Jobs desselben Laufs grün sind, der Job `veroeffentlichen`: `ghcr.io/chief-wiggum1203/loxpanel` mit Tags `latest` (nur `main`), `v<tag>`, `sha-<kurz>`; Plattformen amd64, arm64, arm/v7. Ein eigenes `docker-image.yml` gibt es im Fork nicht mehr, es veröffentlichte neben den Tests her (`tests/test_workflows.py`) |
| `plugin-release.yml` | GitHub-Release veröffentlicht, manuell | `loxpanel-plugin.zip` aus `loxberry-plugin/` am Release |
| `android-apk.yml` | Tags `v*`, manuell | `LoxPanel-Server.apk`, signiert mit dem festen Schlüssel aus den Secrets `LOXPANEL_KEYSTORE_B64`, `LOXPANEL_KEYSTORE_PASSWORD`, `LOXPANEL_KEY_ALIAS` und `LOXPANEL_KEY_PASSWORD`; ohne sie bricht der Lauf mit einem Hinweis ab, die übrigen Workflows hängen nicht daran |
| `deb.yml` | Tags `v*`, manuell | `loxpanel-server_<version>_all.deb` aus `packaging/deb/` am Release |

Welcher Stand läuft, steht in der Seitenleiste des Konfigurators und in
`/api/health` (`bin/version.json`, `bin/version_info.py`): Version aus
`loxberry-plugin/plugin.cfg`, Commit und Bauzeit. `tests.yml` reicht den
Commit als Build-Argument `LOXPANEL_COMMIT` herein, der APK-Build nimmt ihn aus
derselben Umgebungsvariablen oder aus Git und hängt ihn auch an den
`versionName` der App (App-Info in Android).

Ein App-Update braucht keinen Plugin-Bump, weil `:latest` rollend ist. Für ein
Plugin-Release: `VERSION` in `loxberry-plugin/plugin.cfg` und
`loxberry-plugin/release.cfg` gemeinsam hochzählen, nach `main` pushen,
GitHub-Release mit Tag `v<version>` anlegen. Das Image `v<version>` erscheint erst
nach den Tests des Tags, also rund zehn Minuten später. `NAME`, `FOLDER` und
`AUTHOR` nie ändern. Das GHCR-Package muss einmalig auf public stehen (bereits
erledigt).

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
3. Server-Whitelist in `_sanitize_panels()` bzw. `_sanitize_theme_ui()` (global
   zusätzlich `THEME_UI_KEYS`), sonst wird die Option verworfen. Für Panels
   auch in `_panel_export()`, sonst geht sie beim nächsten Speichern verloren.
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
| F13 | Agent-State-Datei in root-eigenem Verzeichnis, Panel-Wahl überlebte keinen Reboot — behoben, Ablage nach XDG beim Login-Benutzer, §8 | `agent/loxpanel-agent.py` `STATE_FILE`, `install-agent.sh:33` |
| F14 | `requests` wird von drei Skripten importiert, steht aber nicht in `requirements.txt` | `cover_test.py`, `proxy_test.py`, `loxone_client.py` |
| F16 | Globale Regel `.empty{grid-column:1/-1}` (für „nichts hier" im Kachelraster) traf auch die Leerfelder vor dem 1. im Monatskalender: sie belegten eine ganze Zeile, jeder Monat begann am Montag, alle Tage standen unter dem falschen Wochentag (Split-Pane Kalender) — behoben, Regel auf `.grid>.empty` begrenzt; Regressionstest misst die Spalten im Browser | `panel.html` CSS, `fpMonthHTML()` |
| F15 | Das Miniserver-Token wurde nur beim Neuaufbau des WebSockets erneuert. Blieb der stabil, lief es ab: Werte kamen weiter, Befehle scheiterten still (passt zu: Panel nach ein bis zwei Tagen nicht mehr bedienbar) — behoben, §3.4 | `command()`, `_stat_load()`, `fetch_icon()` |
| F17 | Die Live-Verbindung zum Miniserver hatte weder Zeitlimit noch `keepalive`. Riss sie still ab oder nahm der Miniserver an und schwieg, wartete `stream_task` für immer; die Panels zeigten eingefrorene Werte, `/api/health` meldete „läuft“ — behoben, §3.4 (Fristen, `keepalive`, Backoff nur nach gelieferten Daten) | `loxone_ws.py` `connect()`, `stream()`; `stream_task()` |

### Sicherheit

| Nr. | Befund |
|---|---|
| S1 | Keine Authentifizierung auf irgendeiner Route. `POST /api/settings/miniserver` nimmt Zugangsdaten entgegen, `POST /api/panels` überschreibt die Konfiguration, `/api/mode` schaltet Panels um, `/api/meta` liefert die komplette Anlage. Einziger Schutz ist das Netzsegment. |
| S2 | `/cover?u=` ist ein offener Proxy ohne Host-Whitelist (SSRF). |
| S3 | Miniserver- und Kamera-Passwörter im Klartext in `loxpanel.cfg`. PIN wird im Klartext über den WebSocket übertragen. Gesamter Verkehr ist HTTP. |
| S4 | Agent-HTTP auf `0.0.0.0:8130` ohne Auth. Jeder im LAN kann Panels umschalten oder abschalten, der `panel`-Wert wird persistiert. |
| S5 | LoxBerry-`sudoers`: `docker` ohne Passwort ist faktisch Root. |
| S6 | `/mjpeg` ohne Begrenzung gleichzeitiger Streams, jeder hält eine eigene Session. |
| S7 | `verify_tls: false` ist überall Standard und im LoxBerry-Widget fest verdrahtet. `true` prüft gegen den Standard-Truststore und klappt nur mit dem Namen aus dem Zertifikat als Host, nicht mit der IP-Adresse (§5.1). |

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
- W5: Magic Numbers ohne Konstante (0,3 s, 10 s, 600 s, Port 8130,
  Port 7091, Mood 778, Daytimer-Dauern, Farbtemperaturen). Die 60 s und 8 s
  der Agenten sind `AGENT_ONLINE` und `AGENT_BEFEHL_TIMEOUT`.
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
