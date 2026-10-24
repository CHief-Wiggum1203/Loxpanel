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
| Frontend | drei Single-File-HTML-Seiten mit Vanilla JS, eine gemeinsame `i18n.js` und eine gemeinsame `raster.js` |
| Panel-Agent | Python-Standardbibliothek, läuft auf dem Wandpanel |
| Auslieferung | Docker-Image (amd64/arm64/armv7) auf GHCR, LoxBerry-Plugin als Wrapper, Unraid-Template |
| Persistenz | drei JSON-Dateien im Ordner `config/` (im Container `/app/config`) |

**Projektstand:** Das Projekt ist jung. Der erste Commit stammt vom 28.08.2026,
alle Commits stammen von einem Autor, Version 0.3.2 (Upstream-Stand vom
07.09.2026, in den Fork gemergt). Der Code ist funktional weit,
es gibt Tests gegen einen Miniserver-Nachbau (`tests/`, Abschnitt 9.3), aber keine Authentifizierung und einige
Altlasten aus einer früheren Konzeptphase (openHASP/MQTT).

**Umfang** (Oktober 2026): rund 20.800 Zeilen Python in `bin/` (mit den
Probe- und Testskripten), davon `bin/webvisu.py` rund 460; Visu und
Konfigurator rund 13.600 Zeilen HTML, CSS und JavaScript; die Tests rund
31.400 Zeilen.

---

## 2. Verzeichnisstruktur und Rollen

### 2.1 Aktiver Code

| Pfad | Rolle |
|---|---|
| `bin/webvisu.py` | Der Kern des Servers: die Klasse `App` (Felder, Hintergrundaufgaben, Schließen; ihre Themen erbt sie als Mixins aus den Modulen unten, §3.3), Start und Logging und `main()` mit der Routentabelle; die Handler liegen in `bin/routen/` |
| `bin/routen/` | Die Routen-Handler je Thema: `oberflaeche.py` (Dateien der Oberfläche), `visu.py` (WebSocket `/ws`), `konfigurator.py`, `einstellungen.py` (dazu Sicherung), `intercom.py` (SIP, Gegensprechen, MJPEG), `geraete.py` (Geräte und Agenten), `medien.py` (Icons, Cover, Klingelbilder), `system.py` (`/api/health`, `/api/diagnose`); `gemeinsam.py` hält `_push()`, `_push_filter()`, `_json_or_empty()`, `_NOCACHE` und `server_stand()`. Die Handler holen die App aus `request.app["app"]`, `main()` trägt sie ein (§4). Importiert `webvisu` nur für die Typangabe `App` unter `TYPE_CHECKING` |
| `bin/konfig.py` | Die Konfigdateien unter `config/`: Pfade, `_load_cfg()`/`_write_cfg()`/`_atomic_write()`, die Leser der `loxpanel.cfg` (`_config()`, `_ms_zugang()`, `_audio_config()`, `_intercom_config()`, `_night_config()`, `_calendar_config()`), `load_theme()`/`load_panels_doc()`/`load_panels()`, die Optionskonstanten (`PANEL_STANDARD`, `THEME_UI_KEYS`, `KACHEL_ZIEL`, `GERAETE_KATALOG` …), die Wertprüfer (`_clean_*`, `_color_ok()`, `_pin_merken()`) und die Sanitizer (`_sanitize_panels()`, `_sanitize_devices()`, `_sanitize_theme_ui()`, `_sanitize_categories()`, `_panels_verworfen()`, `_devices_export()`), die `App` als statische Methoden hält (§5.3). Importiert `webvisu` nicht |
| `bin/bento_format.py` | LoxOS (Fork, [`VISION.md`](VISION.md)): Prüfung der Bento-Seiten (`pickTabs[].bento`), `bento_seite()` und `_clean_iframe_url()`, die Konstanten `BENTO_*`. Importiert nichts aus `konfig.py`; das ruft `bento_seite()` mit `_bento_widget` und `BILDSCHIRM_PX_MAX` (§5.3) |
| `bin/bento.py` | LoxOS (Fork, [`VISION.md`](VISION.md)): Mixin `Bento`. `_view_bento()` rendert eine Bento-Seite mit Widget-Daten inline (dieselben Blockbauer wie die Panes, gelesen über die Lesespur), `bento_task()` prüft die Webseiten-Adressen im Hintergrund (Erreichbarkeit, `X-Frame-Options`, CSP `frame-ancestors`; `einbetten_stand()`, `webseite_pruefen()`). Andockstellen: Weiche in `_view_tab()`, Basisklasse von `App`, Task in `on_startup` |
| `loxos/` | LoxOS-Hülle (Fork, [`VISION.md`](VISION.md)): Electron-App, die die Visu als `?device=<Name>` auf einem Streifen-Display zeigt; `src/einstellungen.js` und `src/monitor.js` reine Logik (Node-Tests in `loxos/test/`), `src/main.js` Fenster, Modi, Tray, Kürzel, Autostart, `src/einrichtung.*` Einstellungen; Versionen festgenagelt (`package-lock.json`, Dependabot), `tests/test_loxos_huelle.py`; Installer mit electron-builder (`build` in `package.json`), gebaut vom Workflow `.github/workflows/loxos.yml` bei Tags `loxos-v*` |
| `bin/symbolquellen.py` | Symbolquellen der Kacheln und freien Seiten (18.10.2026 aus `konfig.py`, das an die Grenze von `test_dateigroessen.py` kam): die Loxone-Icon-Bibliothek (`LOXLIB_DIR`, `_loxlib_names()`, Route `/loxlib` in `routen/medien.py`) und die Prüfung der Icon-Angaben (`_clean_icon()`, `_clean_seiten_icon()`), die `_sanitize_panels()` anwendet. Nur Standardbibliothek, importiert kein Server-Modul |
| `bin/sicherung.py` | Sicherung: `_backup_zip()` (ZIP ohne Kennwörter, mit Vermerk `sicherung.json`) und das Einspielen `_sicherung_lesen()` → `_sicherung_pruefen()` → `_sicherung_schreiben()`; die Routen `/api/backup` und `/api/restore` in `routen/einstellungen.py` rufen hier (§4). Importiert `webvisu` nicht |
| `bin/statistik.py` | Verläufe aus den Statistik-Dateien des Miniservers: Parser (`_parse_stat_xml()`, `_parse_stat2_bin()`), Ausdünnen und Tagesbalken (`_stat_thin()`, `_stat_buckets()`, `_stat_bars()`), dazu als Mixin `Statistik` das Laden mit Cache (`_stat_load()`, `_stat2_load()`), die Verlaufsblöcke (`_stat_blocks()`, `chart_blocks()`, `chart_stack()`) und die Mini-Verläufe der Kacheln (`_stat_spark()`), §3.9. Importiert `webvisu` nicht |
| `bin/haus.py` | Hausübersicht (Tab `haus`) als Mixin `Haus`: Raumkarten, „Gerade aktiv“, Schnellaktionen über die Zentral-Bausteine, Hinweise, Spieler mit Sendern, Energie, die Aufbauten (`HAUS_*`); `_view_haus()` liefert die Seite, §7.1 „Hausübersicht“. Importiert `webvisu` nicht |
| `bin/gesten.py` | Gesten wie auf den Loxone-Tastern als Mixin `Gesten`: `geste()` (Nachricht `{t:"geste"}`), `gesten_hilfe()`, Lichtgruppen und Stimmungen, die Auswahl im Konfigurator (`geste_taster_optionen()`, `licht_stimmung_optionen()`), `GESTEN_*_TYPEN`. Importiert `webvisu` nicht |
| `bin/miniserver.py` | Mixin `Miniserver`: Verbindung zum Miniserver (`start()`, `reconnect()`, `stream_task()` mit wachsender Pause), Token und seine Erneuerung, die Struktur übernehmen (`_apply_structure()`), Werte aus dem WebSocket (`_on_value()`), Befehle (`command()`, gesichert mit Visu-PIN), HTTP an den Miniserver (`_ms_http()`, `_ms_jdev()`) und die gesicherten Details (`secured_details()`), §3.4 und §3.10. Importiert `webvisu` nicht |
| `bin/geraete.py` | Mixin `Geraete`: welche Ansicht ein Gerät zeigt (`ansicht_fuer_geraet()`, Zuordnung, Betriebsmodus, Vorschau am Gerät, Entwurf), Kopplungscode, Anwesenheit, Display (Abschalten, Nacht, Neuladen, Skalierung, Displaytreiber), Agenten-Befehle, `device_list()` und das Schreiben von `panels.json`; dazu `KIOSK_APPS`, `AGENT_*`, `_lan_adressen()`. Importiert `webvisu` nicht |
| `bin/audiodienst.py` | Mixin `Audiodienst`: Ereignis-Clients der Audioserver (`audio_events_task()`), das Backend je Zone, Cover der laufenden Titel und die Favoriten der Zonen. Importiert `webvisu` nicht |
| `bin/intercomdienst.py` | Mixin `Intercomdienst`: SIP-Zugang einer Intercom aus den gesicherten Details (`intercom_sip()`, für Gegensprechen und SIP-Prüfung), die Kamera für den MJPEG-Proxy (`intercom_video()`, aus `loxpanel.cfg` oder den gesicherten Details, `_kamera_aus_details()`) und die Blöcke der Kamera-Pane (`intercom_blocks()`), §3.10. Kachel und Detailseite bleiben in `bausteine/intercom.py`. Importiert `webvisu` nicht |
| `bin/front.py` | Mixin `Front`: Kalender und Wetter der Uhr-Seite, regelmäßig geholt (`front_task()`) und als `{t:"front"}` verteilt, Loxone-Wetterserver mit Vorrang (§3.8), Sonnenzeiten. Importiert `webvisu` nicht |
| `bin/verteilung.py` | Mixin `Verteilung`: der Broadcaster (`broadcaster()`, `_broadcast_tick()`), der je Verbindung nur rendert, was betroffen ist (`_Lesespur`, `_neu_rendern()`, `_rendern()`, `RENDER_SPAETESTENS_S`), `push()` an ausgewählte Browser, Neuladen und die Hinweise zur Verbindung und zur Einrichtung (§3.5). Importiert `webvisu` nicht |
| `bin/medien.py` | Mixin `Medien`: Adressen der Icons, Icons und Klingelbilder vom Miniserver mit Cache (`fetch_icon()`, `fetch_bell_image()`), Cover über den Proxy (`fetch_cover()`), die Liste der Loxone-Icons. Importiert `webvisu` nicht |
| `bin/diagnosedaten.py` | Mixin `Diagnosedaten`: die Angaben fürs Diagnosepaket (`diagnose_daten()`) und die Typübersicht für `/api/types` (`types_overview()`); dazu `VERSION`. Importiert `webvisu` nicht |
| `bin/ansicht.py` | Mixin `Ansicht`: das wirksame Profil einer Ansicht (`resolve_profile()`), die Theme-Variablen der Visu (`_theme_vars()`), Kategorie-Farben, der Export für den Konfigurator (`_panel_export()`) und das Schreiben von `theme.json`. Importiert `webvisu` nicht |
| `bin/seiten.py` | Mixin `Seiten`: `render()` mit den Tabs, Gruppen und Detailseiten (`_view_tab()`, `_view_control()`), die Kachel (`_control_item()` mit Kopf, Typ-Funktion aus `bausteine/` und Fuß, `_apply_tile_style()`), die Werteleiste und die Status-Pane; `STATUS_BIG`, `_ANALOG`, `KACHEL_BREIT_TYPEN`. Importiert `webvisu` nicht |
| `bin/bausteine/` | Kachel und Detailseite je Bausteintyp, ein Modul je Familie; `__init__.py` hält die Tabellen `KACHEL`/`DETAIL` und die Dekoratoren, `gemeinsam.py` Typmengen, Konstanten der Strukturdoku, die Adapter und reine Helfer (§6) |
| `bin/loxone_ws.py` | Loxone-WebSocket-Client: Token-Handshake, Binärparsing der Value-, Text- und Wetter-Tabellen. Nicht behandelte Kennungen werden einmal pro Verbindung protokolliert. Lebenszeichen: Frist je Antwort, `keepalive` im Stream (Werte vom Aufrufer, §3.4) |
| `bin/adapters.py` | Nur `LightControllerV2Adapter` und `JalousieAdapter` werden genutzt. Die Adapter-Registry darin ist aufgegeben. Dazu `json_aus_text()`: JSON-States je Text einmal parsen (LRU-Cache, `JSON_TEXTE_MAX`), genutzt von den Adaptern und den Helfern der Bausteine (§3.5) |
| `bin/audioserver.py` | Backend für Loxone-Audioserver Gen1 / MS4H über WebSocket Port 7091 |
| `bin/audioserver_events.py` | Event-Client für Audioserver Gen2 (WebSocket Port 7091): Cover, Titel, Favoriten; Adressen aus der Struktur |
| `bin/front_info.py` | Front (Screensaver): iCal-Abo laden und parsen (`icalendar` + `python-dateutil`, löst Serientermine auf) und Wetter von Open-Meteo (kein API-Key, nur Koordinaten). Eigenständig, keine Fremdabhängigkeit. Das Mixin `Front` (`front.py`) ruft `load_front()` im `front_task` (alle 15 Min) und pusht das Ergebnis als `{t:"front"}` an die Panels. Ein einzeln abgesagter, verschobener oder geänderter Serientermin (eigenes VEVENT mit derselben UID und `RECURRENCE-ID`) ersetzt sein ursprüngliches Auftreten. Bewusst nicht unterstützt ist `RANGE=THISANDFUTURE`: Die Ausnahme ersetzt nur ihr eines Auftreten, eine eigene RRULE an ihr bleibt unbeachtet. Abgeglichen wird in der Ortszeit des Servers. Trägt die Ausnahme einer ganztägigen Serie eine Uhrzeit (Exchange-Form), trifft sie ihr Original nur bei richtig eingestellter Zeitzone des Containers, sonst stehen beide da |
| `bin/loxone_weather.py` | Wetter vom Loxone-Wetterserver: rechnet die Wetter-Tabelle des Miniservers in genau die Form um, die `front_info.fetch_weather()` liefert, und hat damit Vorrang vor Open-Meteo. Wetterlage-Texte und Einheiten kommen aus der Struktur (`weatherServer`), nicht aus einer Tabelle im Code. Gibt `None` zurück, wenn sich die Daten nicht sicher beschriften lassen — dann bleibt Open-Meteo |
| `bin/theme_colors.py` | Leitet aus EINER Grundfarbe den ganzen Panel-Farbsatz ab (Flächen, Schrift, Icon- und Zustandsfarben) und rechnet jeden Wert gegen die Fläche nach, auf der er steht: Hauptschrift AAA, Rest AA, Grafik 3:1, dazu Deuteranopie und Protanopie. Liefert `None`, wenn eine Farbe kein tragfähiges Theme hergibt. Dazu die Kachel-Sets (`KACHEL_SETS`, §5.4): fertige Looks mit Farben, Maßen und einer Art für Kachel und Tab-Leiste; „touch“ rechnet seine Farben aus einem Farbton (`touch_satz()`). Und die Schrift der Nacht-Uhr auf ihrem schwarzen Grund (`nacht_schrift()`, `NACHT_GRUND`). Nur Standardbibliothek. Aufgerufen aus `_theme_vars()` |
| `bin/loxone_secure.py` | Verschlüsselte Befehle an den Miniserver (Command Encryption über HTTP, `jdev/sys/fenc`). Grundlage für die gesicherten Details (`App.secured_details()` in `miniserver.py`), siehe Abschnitt 3.10. Braucht `cryptography`; fehlt das Paket, läuft der Server ohne diese Befehle weiter |
| `bin/sip_probe.py` | SIP-Prüfung der Türstation: OPTIONS über UDP, Anmeldung per Digest, Codecs aus dem SDP. Nur Standardbibliothek, siehe Abschnitt 3.10 |
| `bin/version_info.py` | Welcher Stand läuft: liest `bin/version.json` (Version, Commit, Bauzeit), die beim Bauen entsteht: in der APK schreibt sie `syncLoxpanelAssets` (Commit aus `LOXPANEL_COMMIT` oder Git), im Image das Dockerfile über `python bin/version_info.py schreiben` (Commit als Build-Argument aus `tests.yml`, Job `veroeffentlichen`). Ohne die Datei, also im Git-Checkout, Version aus `loxberry-plugin/plugin.cfg` und Commit aus Git. Die App packt bei jedem Update `bin/` neu aus, deshalb liegt die Datei dort |
| `bin/diagnose.py` | Diagnosepaket (`/api/diagnose`, je Gerät oder für den Server): ZIP mit `diagnose.md` (Zusammenfassung oben), `diagnose.json`, den Einstellungen und den letzten Log-Zeilen (Puffer `LOG` am Root-Logger, `LOG_ZEILEN`, `LOG_MINUTEN`). Entfernt Kennwörter und Tokens, kürzt Kalender-Abos auf den Host, streicht Zugangsdaten in Adressen und den Standort und schwärzt jeden gefundenen Wert auch im Log, auch URL-kodiert. Nur Standardbibliothek; die Angaben sammelt `App.diagnose_daten()` |
| `webfrontend/html/panel.html`, `webfrontend/html/panel/` | Die Visu (Kacheln, Detailseiten, Screensaver mit Wetter + Terminen, PIN, Weckton); `panel.html` hält nur das Markup und lädt aus `panel/` zwei Stylesheets und zwölf Skriptteile in fester Reihenfolge (§7.1) |
| `webfrontend/html/config.html` | Konfigurator mit den Rubriken „Übersicht", „Ansichten" (Liste der Ansichten, je Ansicht die Reiter Allgemein, Inhalt, Seiten, Raster, Aussehen, Verhalten), „Vorgaben" (Darstellung, Kategorie-Farben, Verhalten), „Geräte" (eine Karte je Gerät, Gerät einrichten, Betriebsmodus-Assistent, Geräte ohne Namen, Erprobte Hardware) und „Einstellungen" (Miniserver, Kamera / Türstation, SIP, Audio, Kalender & Wetter, Sicherung). Begriffe siehe §7.2 |
| `webfrontend/html/settings.html` | Nur noch Weiterleitung nach `/config`, ohne Anker: der Konfigurator wertet keinen aus |
| `webfrontend/html/i18n.js` | Übersetzungskatalog de/en für Konfigurator und Einstellungen |
| `webfrontend/html/raster.js` | Rasterrechnung für Visu und Konfigurator (Kachelfaktor, Lage, automatisches und festes Raster, Standardmaße der Visu, im Fork das Bento-Raster: `bentoRaster`, `bentoMass`, `bentoStufe(n)`, `bentoFrei`), §7.5 |
| `webfrontend/html/config.css`, `webfrontend/html/config/*.js` | Stylesheet und die elf Skriptteile des Konfigurators; `config.html` hält nur das Markup und lädt sie in fester Reihenfolge (§7.2); im Fork dazu `bento-editor.js` (LoxOS: Seiten-Editor für Bento-Seiten, eingehängt über `seInhalt()`/`seZeichnen()` in `seiten-editor.js`, Grenzen aus `/api/meta` `bento`, Stile am Ende von `config.css`) |
| `agent/loxpanel-agent.py` | Panel-Agent auf dem Wandpanel |
| `deploy/install-agent.sh` | Installer für den Agenten. Enthält den Agent-Quelltext als eingebettete Kopie. |
| `config/*.example` | Vorlagen für `loxpanel.cfg`, `panels.json`, `theme.json` |
| `loxberry-plugin/` | LoxBerry-Plugin (Docker-Starter, Widget, Backup) |
| `unraid/loxpanel.xml` | Unraid-Docker-Template |
| `android/` | LoxPanel-App für Android (Lenardos #61, Paket `com.loxpanel.spike`): Kotlin mit Chaquopy, der Server läuft im Gerät (`ServerService`), die Visu in einer eigenen Vollbild-WebView (`KioskActivity`) mit der JS-Brücke `LoxKiosk` (siehe Abschnitt 8). Der Gradle-Task `syncLoxpanelAssets` kopiert vor jedem Build `bin/`, `webfrontend/` und `deploy/` aus dem Arbeitsbaum in die App, aus `config/` nur die Vorlagen (`*.example`, `*.example.json`, `*.schema.json`): Zugang, Ansichten, Farben und ihre Sicherungen (`*.bak`) kommen nie hinein, auch nicht bei einem lokalen Build (`tests/test_apk_inhalt.py`). Bauen, Signieren und Einrichten: `android/README.md` |
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
                                                     _geaendert.add(uuid)
                                                     Flanken: Klingel, Wecker
   ┌───────────────────────────────────────────────────────────┘
   ▼
App.broadcaster()  alle 0,3 s:
   für jede offene Browser-Verbindung, deren Seite betroffen ist (§3.5):
      render(route, profil)  ──► {"t":"view", ...}  ──► Browser (nur bei Änderung)
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

Die Favoriten einer Zone stehen als Reihe Cover direkt unter dem Titel ihrer
Detailseite (`_sender_bloecke()`, Block `favs` mit `bleiben`), alle zusammen
umbrechend in der Musikauswahl hinter ⋮ (`_view_sources()`). Eine
`AudioZoneV2` bekommt sie nur über den Ereigniskanal, der Miniserver-State
`sourceList` fehlt ihr. Scheitert die Anmeldung am gekoppelten Audioserver,
bleibt die Liste deshalb überall leer. Den Grund hält der Client in
`anmeldung` fest (`keine Antwort`, `abgelehnt (…)`, `Paket cryptography fehlt`
…), die Detailseite und die Musikauswahl zeigen ihn statt einer leeren Liste
(`_favoriten_grund()`), und das Diagnosepaket schreibt ihn in die
Zusammenfassung („nicht angemeldet: abgelehnt (denied)“).

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

`main()` (am Ende von `webvisu.py`) liest `--port` bzw. `LOXPANEL_PORT` (Default 8099),
baut `App(_config(), _audio_config())`, registriert alle Routen und startet beim
`on_startup` drei Dauer-Tasks: `stream_task()` (Miniserver-Verbindung),
`broadcaster()` (Verteilung) und `audio_events_task()` (Audioserver-Gen2-Events). Der HTTP-Server ist sofort erreichbar, auch ohne
Miniserver-Zugang. So bleibt `/config` immer bedienbar.

### 3.3 Zentrale Klasse `App` (`webvisu.py`)

`App` setzt sich aus Mixin-Klassen der Themenmodule zusammen, die sie erbt
(Schritt 4 des Zerlegens, §7.2): `Statistik` (`statistik.py`, Verläufe),
`BausteinHelfer` (`bausteine/`, Helfer und Unterseiten der Bausteine, Blöcke
des Spielers), `Haus` (`haus.py`, Hausübersicht), `Gesten` (`gesten.py`),
`Miniserver` (`miniserver.py`, Verbindung, Struktur, Befehle), `Geraete`
(`geraete.py`, Geräte, Agenten, Display), `Audiodienst` (`audiodienst.py`),
`Intercomdienst` (`intercomdienst.py`, SIP-Zugang und Kamera der Intercom),
`Front` (`front.py`, Kalender und Wetter), `Verteilung`
(`verteilung.py`, Senden an die Browser), `Medien` (`medien.py`, Icons, Cover,
Klingelbilder), `Diagnosedaten` (`diagnosedaten.py`), `Ansicht` (`ansicht.py`,
Profil und Theme) und `Seiten` (`seiten.py`, `render()` und Kacheln). In
`webvisu.py` selbst stehen nur noch `__init__()` mit allen Feldern,
`_spawn()` und `close()`. Die Methoden arbeiten mit dem Zustand der App
(`self`), Aufrufe bleiben gleich.

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

- `App.start()` (alles in diesem Abschnitt steht in `miniserver.py`): Client bauen, `getkey2`, `authenticate` (JWT), Struktur
  laden, Icon-Session anlegen, WebSocket öffnen.
- `stream_task()`: Endlosschleife. Bei Fehler wird das Token erneuert,
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
- **Verbindungszustand an den Panels** (Oktober 2026): Früher sah ein Panel
  nicht, dass der Miniserver weg war, sobald einmal eine Struktur geladen war.
  Die Werte blieben ohne Hinweis stehen, Tipps gingen ins Leere, und der
  Online-Punkt zeigte nur die Verbindung Panel ↔ Server. Jetzt merkt sich
  `stream_task` beim Abriss, seit wann der Miniserver weg ist
  (`_ms_weg_seit`), und rechnet die letzte Nachricht der Verbindung
  (`LoxoneWS.letzte_nachricht`, auch die Antwort auf `keepalive`) in eine
  Uhrzeit um (`_ms_bestaetigt`). Weitere Fehlversuche verschieben den
  Zeitpunkt nicht. Gelöscht wird er nach der Anmeldung, unmittelbar bevor
  der Datenstrom beginnt. `_verbindung_stand()` liefert daraus
  (erreichbar, seit, bestätigt). Ohne Struktur gilt der Miniserver als
  erreichbar, dann zeigt das Panel die Einrichtungskarte. Die Nachricht
  `verbindung` geht beim Verbinden an das Panel, bei jeder Änderung an alle
  und alle `VERBINDUNG_TAKT` (15 s) als Lebenszeichen (`_verbindung_melden()`
  im Broadcaster). Die Visu sperrt jeden Befehl, sobald eine der beiden
  Verbindungen fehlt (`verbindungGesperrt()` in `sendCmd()`, über das auch
  die Schnellaktionen der Hausseite gehen, und vor jeder Geste,
  `gesteSenden()`). Die Leiste `#verbindung` mit „seit“ und letztem bestätigtem
  Stand und die blasse Darstellung (`.screen.verbweg`) kommen nach
  `VERBINDUNG_HINWEIS` (8 s), damit ein Neustart des Miniservers nach dem
  Speichern in Loxone Config oder ein kurzer WLAN-Aussetzer nicht jedes Mal
  aufblitzt. Ein gesperrter Tipp zeigt sie sofort. Fehlt der Server, nennt
  die Leiste ihn; als Stand gilt dann die letzte Nachricht, die kam, solange
  der Miniserver erreichbar war (`verbBestaetigt`). Schweigt der Server
  `VERBINDUNG_STUMM` (40 s), gibt die Visu den WebSocket auf und verbindet
  neu (`verbAbgerissen()`): Ein still verschwundener Server (WLAN, Strom)
  schloss ihn sonst nie. Takt, Fristen und Texte (`VERBINDUNG_TEXTE`) stehen
  einmal im Server und kommen mit der Nachricht. Kommt der Miniserver
  zurück, schickt er nach der Anmeldung alle Werte, und der Broadcaster
  liefert die Ansichten neu. Die Leiste steht in der Zeile des Rasters über
  allen Spalten, wie früher der Punkt je Layout (Kopfzeile, Werteleiste,
  Split, Leiste „oben“). Sie hat die Flächen der gefüllten Störungskachel
  (`--crit-fill`/`-ink`/`-muted`), ohne Set eine Auflage in `--crit-rgb` auf
  einem Kasten in `--bg`. Tests: `tests/test_verbindung.py` (Nachbau trennt
  und kommt zurück, Lebenszeichen) und
  `tests/browser/test_verbindung_browser.py` (Sperre, Frist, Server weg und
  zurück, stummer Server); die Lesbarkeit misst
  `test_kachel_set_kontrast_browser.py` (Ansicht `verbindung`).
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
- `reconnect()`: zweiter Weg über `/api/settings/miniserver`. Baut einen
  neuen Client und übernimmt ihn nur bei Erfolg, die alte Verbindung überlebt
  einen Fehlversuch. Die Anmeldung (`getkey2`, `getjwt`) hat eine Frist,
  `miniserver.response_timeout` in `loxpanel.cfg`, Standard `MS_CMD_TIMEOUT`
  (`_ms_antwortfrist()`); das Laden der Struktur hängt an ihrer Größe und hat
  keine. `api_settings_ms` übergibt den zu prüfenden Zugang und schreibt erst
  danach (§5.1).
- HTTP oder HTTPS erkennt die Anmeldung selbst (`_ms_oeffnen()`): Gen1
  spricht nur HTTP, Gen2 beides, und beide Ports sind in Loxone Config
  einstellbar oder liegen hinter einer Weiterleitung. Der erste Abruf
  (`getkey2`) nimmt das Schema, das der Port nahelegt (`_ms_https()`: 80 =
  HTTP, sonst HTTPS). Scheitert er, ohne dass der Miniserver antwortet, folgt
  das andere Schema (`_anderes_schema()`). Das trifft etwa einen HTTP-Port
  wie 8006, an dem auf den TLS-Gruß Klartext kommt („WRONG_VERSION_NUMBER“),
  oder eine Gegenstelle, die schließt oder bis zur Antwortfrist schweigt. Hat
  der Miniserver geantwortet (auch mit Fehler) oder passt das Zertifikat
  nicht, bleibt es beim ersten Schema. Mit „Zertifikat prüfen“ geht es nie
  von HTTPS auf HTTP. Scheitert auch der zweite Versuch, meldet LoxPanel
  dessen Fehler nur, wenn dort jemand geantwortet hat, sonst den ersten. Das
  Ergebnis steht in `App.ms_tls`; WebSocket (`ws`/`wss`) und `_ms_http()`
  folgen ihm, das Diagnosepaket nennt es (`verschluesselt`). Gemerkt wird es
  nicht, jede neue Anmeldung erkennt es neu. Ohne TLS stellt `_make_client()`
  die Basis-URL von Hand auf `http://`, weil `loxone-api` HTTPS annimmt. Bei
  `remoteConnect` der Intercom-Kamera bleibt HTTPS Pflicht (Strukturdoku).

### 3.5 Verteilung an die Browser

`broadcaster()` (`verteilung.py`) läuft alle 0,3 s (`_broadcast_tick()`) und
rendert je offene Verbindung nur, was betroffen ist:

- `_on_value()` sammelt die geänderten States in `_geaendert`. Jedes Rendern
  einer Verbindung liest die States über eine Lesespur (`_Lesespur`), die
  festhält, welche es gelesen hat (`get`, `[]`, `in`); sie steht mit Profil,
  Schlüssel und Zeit in `_render_spur`. Neu gerendert wird eine Verbindung
  (`_neu_rendern()`), wenn ihr letztes Rendern einen der geänderten States
  gelesen hat, wenn sie Seite (Route), Profil oder einen Bereich (Player,
  Energiefluss, Verlauf, Kamera, Statusspalte) gewechselt hat oder wenn es
  `RENDER_SPAETESTENS_S` (10 s) her ist. Die Frist deckt, was an der Uhr hängt
  statt an einem State: Countdowns („wird scharf um …“, Briefkasten-Pause),
  „heute“/„morgen“ beim Wecker und im Klingelarchiv, das Nachladen der
  Verläufe.
- Liest ein Rendern die States im Ganzen (Durchlaufen, Länge, `items()`),
  weiß die Spur nicht, welche es braucht (`alles`): dann rendert die
  Verbindung bei jedem Takt mit einer Änderung.
- `_dirty` heißt „außerhalb der States hat sich etwas geändert“ (Struktur,
  Theme, Audioserver, Verläufe, Intercom-Bild, Sicherung) und rendert alle
  Verbindungen neu.
- Scheitert ein Rendern, bleibt seine Spur bis dahin stehen: Es wird nicht
  jeden Takt wiederholt (das Log liefe voll), sondern wieder, wenn sich etwas
  ändert, das es gelesen hat, oder nach der Frist.

Gerendert wird je Verbindung in `_rendern()`: Ansicht und Bereiche. Geschickt
wird danach nur, was sich seit der letzten Zustellung an diese Verbindung
geändert hat (`_last_sent`); ein Delta-Protokoll innerhalb einer Ansicht gibt
es nicht. JSON-States (`moodList`, `entryList`, `sourceList` …) parst der
Server je Text einmal (`adapters.json_aus_text()`, LRU-Cache mit
`JSON_TEXTE_MAX` Einträgen); ein unlesbarer wird je Text einmal gemeldet
(`_json_fehler_melden()`), nicht bei jedem Rendern.

### 3.6 Nachrichtenprotokoll

Server → Browser (`panel.html:700`):

| `t` | Inhalt | Zweck |
|---|---|---|
| `theme` | `vars`, `tabs`, `tabMeta`, `title`, `lang`, `fill`, `split`, `catFilter`, `tileLayout`, `tileSet`, `tileSetAufbau`, `tileSetLeiste`, `gridAuto`, `gridGrow`, `panes`, `svPane`, `scale`, `dpmsOff`, `pinMerken`, `gesten`, `reloadHours`, `reloadAt`, `night`, `agent`, `presence` | einmalig nach Verbindungsaufbau: CSS-Variablen, Tab-Leiste, Sprache, Sprungmarken springen oder filtern, Kachel-Aufbau, Kachel-Set mit seiner Art (§5.4), beim automatischen Raster die Zielkachel in px (`gridAuto`, Gerät vor Profil über `effective_grid_auto()`, 0 = festes Raster, §7.1) und bis zu welchem Vielfachen die Kacheln wachsen, wenn alle auf eine Seite passen (`gridGrow` = `KACHEL_WACHSEN`), Split-Panes je Tab, die rechte Spalte der Uhr-Seite, die wirksame Skalierung (Gerät vor Profil vor global, `effective_scale()`) und die Display-Einstellungen ohne Agent: Leerlaufzeit, Auto-Neustart (`reloadHours`, `null` ohne Eintrag: dann nachts um `reloadAt` Uhr), Nachtmodus, ob ein Agent das Display übernimmt, und ob der Präsenzmelder des Geräts gerade jemanden meldet (`presence`, dann schaltet der Leerlauf nicht ab). `pinMerken`: so viele Sekunden behält die Visu eine bestätigte PIN (0 = jedes Mal fragen). `gesten`: Zwei-Finger-Gesten an (§7.1 „Gesten“; Ansicht vor Vorgaben, ohne beides `GESTEN_STANDARD`), `gestenHinweis`: dazu das Hinweis-Symbol (Ansicht vor Vorgaben, ohne beides `GESTEN_HINWEIS_STANDARD`) |
| `view` | `title`, `tab`, `route`, `items[]` **oder** `blocks[]`, `layout`, `anchor`, `secured`, `gesperrt`, `front`, `leiste[]`, `gestenHilfe` | eine komplette Ansicht. `gesperrt` (Text, wer gesperrt hat und warum) auf jeder Seite eines gesperrten Bausteins (`jLocked`), siehe §7.1 „Gesperrte Bausteine“. `gestenHilfe` nur auf Seiten, auf denen Gesten wirken und ihr Hinweis an ist (`gesten_hilfe()`): `{raum, doppel, dreifach}`, was zwei Finger hier tun (§7.1 „Gesten“). `leiste` (nur auf Seiten aus `ui.valueBar`): die Anzeige-Bausteine der Seite als Werteleiste über dem Raster, gleiche Form wie `items`, dort fehlen sie dann (§7.1 „Werteleiste“). `front` (`calendar`/`weather`) bei den Tabs `kalender`/`wetter`: `items` ist leer, das Panel zeichnet die Seite aus den zuletzt empfangenen `front`-Daten (`renderFrontTab()`) und neu, sobald neue kommen. `layout:"haus"` beim Tab `haus` (Hausübersicht, §7.1): statt `items` die Felder `aufbau`, `raeume[]`, `aktiv[]`, `aktivZeile` (false: die Ansicht zählt nichts als aktiv, keine Zeile), `ruhig` (Text der Zeile, wenn nichts an ist), `hinweise[]`, `schnell[]`, `spieler`, `energie`, im Aufbau „Spalte links“ `blick[]` und auf einer Unterseite `liste` (`"aktiv"` oder `"hinweise"`); auf einer Bento-Seite (LoxOS, Fork) statt dessen `bento` (`cols`, `rows`) und `cells[]` (je Zelle `x`, `y`, `w`, `h` und entweder `items[]` oder `widget` mit den Daten inline: `energy`, `chart`, `player`, `camera`, `status` wie die gleichnamigen Nachrichten ohne `t`, bei `iframe` `url`, `name`, `pruefung` (`stand`: `ok` \| `eingeschraenkt` \| `gesperrt` \| `fehler` \| `offen`, `grund`) und `ladenS`; `fehler: true`, wenn ein Blockbauer scheiterte), gebaut in `_view_bento()` (`bento.py`) |
| `ring` | `id` | Klingel: Panel springt auf die Intercom-Seite. An jedes Panel, außer dessen Ansicht blendet die Türsprechanlage aus (`hide`) |
| `alarm` | `id`, `on` | Weckton starten/stoppen. `on: true` nur an Panels, deren Ansicht den Wecker zeigt (Raum, Kategorie, `hide`: `_sichtbar()`), und nur deren Display geht an; `on: false` an alle, damit ein Panel, das die Ansicht gewechselt hat, nicht weitertönt |
| `testtone` | | Testton |
| `switch` | `panel` | Betriebsmodus: Seite mit neuem Profil neu laden |
| `reload` | | `location.reload()` |
| `goto` | `route` | auf eine Seite springen |
| `notify` | `text`, `level`, `secs` | Einblendung |
| `verbindung` | `ms`, `seit`, `stand` (ms seit 1970, `null` bei erreichbarem Miniserver), `takt`, `stumm`, `hinweis` (s), `texte` (`ms`, `server`, `stand`, `gesperrt`, mit `{seit}`/`{stand}`) | Verbindungszustand und Lebenszeichen (§3.4, `_verbindung_melden()`): beim Verbinden, bei jeder Änderung und alle `VERBINDUNG_TAKT` s |
| `einrichtung` | `aktiv`, dazu bei `aktiv`: `titel`, `grund`, `hinweis`, `pfad`, `adressen[]`, `unbekannt` | Einrichtungshinweis, solange der Server keine Struktur vom Miniserver hat und entweder kein Zugang eingetragen ist oder der letzte Versuch scheiterte (`_einrichtung_stand()` nach `_einrichtung_info()`, Fehlertext aus `stream_task`, höchstens `EINRICHTUNG_FEHLER_MAX` Zeichen). Beim Verbinden und bei jeder Änderung (`_einrichtung_melden()`). Die Visu setzt die Adresse des Konfigurators zusammen: die, über die sie geladen wurde, bei `127.0.0.1` (App auf dem Panel) eine aus `adressen` (`_lan_adressen()`: Quelladresse der Standardroute, ohne Paket) |
| `cmdresult` | `ok`, `code`, `uuid`, `cmd`, `gesperrt` | Ergebnis eines PIN-gesicherten Befehls. `uuid` und `cmd` ordnen es dem Befehl zu (Drücken und Loslassen einer Halten-Taste kommen kurz hintereinander), `code` `null` heißt „keine Antwort“, nicht „PIN falsch“. `gesperrt`: der Baustein ist gesperrt, der Befehl ging nicht zum Miniserver; die Visu fragt nicht erneut nach der PIN, den Grund nennt ein `notify` |
| `display` | `on`, optional `presence` | Display über die Kiosk-App aus- oder einschalten. `presence` kommt vom Präsenzmelder des Geräts (§8): solange `true`, schaltet der Leerlauf nicht ab |
| `front` | `weather` (`temp`, `cond`, `icon`, `hi`, `lo`, `wind` + `wind_unit`, `forecast[]`), `events[]` (`day`, `time`, `title`), `calName` | Kalender + Wetter für den Screensaver; beim Verbinden und alle 15 Min bzw. nach dem Speichern (`front_task`) — oder sofort, wenn der Miniserver neues Wetter schickt (§3.8) |
| `scale` | `scale` (`"off"` \| `"auto"` \| Faktor) | Skalierung live umstellen, gesendet nach `POST /api/devices` an alle verbundenen Panels — ohne Neuladen |
| `energy` | `control`, `name`, `nodes[]`, `totals` (`prod`, `cons`, `grid`) | Energiefluss-Pane (Pane 2, Widget-Seite, Uhr-Seite); nach `setenergy` und bei jeder Änderung, die der Broadcaster sieht (`energy_blocks()`) |
| `camera` | `blocks[]` | Kamera-Pane: die Intercom-Ansicht ohne `more` und ohne die Zeile `klingel` (Klingel abstellen, verpasste Klingeln); nach `setcamera` und bei jeder Änderung (`intercom_blocks()`) |
| `player` | `blocks[]` | Player-Pane: die Blöcke der Audio-Zone samt `more`, daraus rechts oben das ⋮ zur Musikauswahl (`renderPlayer()`, `#ppmehr`; nach der Wahl eines Senders zurück zur Seite davor); nach `setplayer` und bei jeder Änderung (`player_blocks()`) |
| `chart` | `controls[]`, `range`, `ranges[]`, `charts[]` (je Baustein `control`, `name`, `value`, `blocks[]` mit Blöcken `chart`, §3.7) | Verlaufs-Pane (Pane 2, Widget-Seite, Uhr-Seite) mit einem oder mehreren Bausteinen; nach `setchart` und bei jeder Änderung, die der Broadcaster sieht (gebaut in `chart_stack()`, je Baustein `chart_blocks()`). `controls` nennt nur Bausteine mit Aufzeichnung. Die Visu verwirft eine Nachricht, die Bausteine außerhalb ihrer Anfrage nennt (ein Push, der beim Wechsel schon unterwegs war), und der Broadcaster schickt keine, wenn die Verbindung nach dem Berechnen einen anderen Stapel angemeldet hat |
| `geste` | `art`, `raum`, dazu `phase:"start"` mit `wert` (0–100) und bei „Stimmung beim Einschalten“ `text`, sonst `text` oder `fehler` | Antwort auf eine Geste (`App.geste()`): Startwert zum Dimmen, für die Lautstärke bzw. die Lamellen, der Name der eingeschalteten Stimmung oder des Senders, „Beschattung ab“, „Lamellen 70 %“, „Pause“, „… verlassen“ oder warum nichts geht („Kein Raum auf dieser Seite“). Nach `beschattung`/`beschatten` dazu `wert` (Stellung in %) und danach von sich aus `phase` `wert`/`ende` mit `wert` und `text`, solange die Jalousien fahren (`geste_fahrten()`). Die Visu zeigt sie im Vollbild (§7.1 „Gesten“) |
| `svstatus` | `items[]` (dieselbe Form wie Kachel-`items`, ohne `nav`/`controls`) | Werte der frei gewählten Bausteine für die rechte Spalte der Uhr-Seite; gebaut in `status_blocks()` über `_control_item()`, also dieselbe Kette wie jede Kachel |
| (Browser → Server) `idle` | | Visu ohne Kiosk-JS meldet Leerlauf nach `dpmsOff`; Server schaltet über den Display-Treiber aus |
| `setdevice` | `name` | Gerät wurde in den Einstellungen benannt: Visu merkt sich den Namen und verbindet neu |
| `kopplung` | `code`, `karte`, `titel`, `hinweis`, `pfad`, `adressen[]`, `unbekannt`, `weg` | Browser ohne Gerätekennung, beim Verbinden: sein Kopplungscode (`kopplungscode()`: ein gültig zurückgeschickter `?code=` bleibt, sonst ein neuer aus `KOPPLUNG_ZEICHEN`, `KOPPLUNG_LAENGE` Zeichen, keiner einer anderen Verbindung). Die Visu merkt ihn sich (`lp_kopplung`) und schickt ihn beim nächsten Verbinden zurück. `karte` nur ohne `?panel=` in der Adresse (mit `?panel=` hat jemand das Gerät bewusst eingerichtet, die Karte läge sonst nach jedem Neustart über der Visu): dann zeigt das Panel „Dieses Gerät einrichten“ mit Code und Konfigurator-Adresse (wie `einrichtung`), ein Tipp blendet sie bis zum nächsten Laden aus. Derselbe Code steht unter Displays (`/api/devices` `anonymous[].code`), „Namen vergeben“ dort schickt `setdevice` an genau diese Verbindung; danach vergisst die Visu den Code (Punkt 11, 08.10.2026). Ein Vorschaufenster des Konfigurators (`?entwurf=`, auch mit abgelaufenem Token) bekommt keine Nachricht und keinen Code und steht nicht unter `anonymous` (`conn_info.vorschau`) |

Browser → Server (`ws_handler` in `routen/visu.py`):

| `t` | Inhalt |
|---|---|
| `nav` | `route` (z. B. `{"view":"tab","tab":"raeume"}` oder `{"view":"control","id":uuid}`). Hausübersicht: `{"view":"tab","tab":"haus"}`, dazu `zone` (Audio-Zone des Spielers) und `liste` (`"aktiv"`: Unterseite „Gerade aktiv“, `"hinweise"`: alle Hinweise). Unterseiten einzelner Bausteine: `{"view":"irrzone","id","zone"}` (Zone einer Bewässerung), `{"view":"alarmentry","id","entry"}` (Weckzeit, `entry` leer = neue), `{"view":"alarmsettings","id"}` (Einstellungen eines Weckers), `{"view":"bells","id"}` (verpasste Klingeln), `{"view":"verlauf","id"}` (Verlauf aus dem Tracker-Unterbaustein, etwa beim Briefkasten), `{"view":"ircset","id"}` (Einstellungen einer Raumregelung V2), `{"view":"durchsage","id"}` (Durchsage einer Audio-Zone Gen. 2), `{"view":"sources","id"}` (Musikauswahl einer Audio-Zone), siehe §6 |
| `cmd` | `uuid`, `cmd`, optional `pin` |
| `geste` | `art` (`licht` \| `musik` \| `lamellen` mit `phase` `start`/`wert`/`ende` und `wert` 0–100; `stimmung`; `beschatten`; `wiedergabe`; `stimmungwechsel` \| `sender` mit `richtung` `vor`/`zurueck`; `beschattung` mit `richtung` `auf`/`ab`; `verlassen`; `hausaus`), auf der Hausübersicht dazu `raum` (Raumkarte unter den Fingern) — Zwei-Finger-Geste (§7.1 „Gesten“). Der Server sucht Raum, Bausteine und Befehle selbst; ein laufendes Dimmen hält er je Verbindung (`conn_geste`). Nur, wenn das Profil Gesten erlaubt |
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
  `dauer` oder `prozent`, sonst `unit` wie `kW` oder `°C` mit deutschem
  Komma, `sub`). Die Visu rundet auf die Stellen des Schritts, 0,5er-Schritte
  kommen ohne Rechenrest an. Ohne `cmd` nur Anzeige. Die Visu zählt selbst
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
- `slider`: Regler mit −/+ (`icon`, optional `label` vor dem Regler,
  `value`, `min`, `max`, `step`, `cmd.tmpl` mit `{v}`), schickt beim
  Loslassen; beim Aktualisieren übernimmt die Visu auch `cmd.tmpl` (Farblicht
  trägt darin die Farbe). Eine Seite kann mehrere haben
  (Jalousie: Position und Lamellen); die Visu bindet und patcht jeden an
  seiner Stelle.
- `favs`: Cover zum Abspielen (`items` mit `label`, `cover`, `cmd`). Mit `wrap`
  umbrechend (Musikauswahl), sonst eine waagrecht scrollende Reihe. Nach dem
  Tippen geht die Visu eine Seite zurück, mit `bleiben` nicht (Detailseite
  der Zone).

`chart` (Verlaufs-Diagramm) trägt `kind` (`line`, `digital`, `counter`), `unit`,
`t0`/`t1`, `series[]` (`name`, `dec`, `pts` als `[sekunden, wert]`) und `state`
(`ok`, `loading`, `error`, `empty`); das erste Diagramm einer Seite dazu `range`
und `ranges` für die Zeitraum-Knöpfe. Gezeichnet in `paintChart()` der Visu.

Kachelseiten bestehen aus `items[]` mit `id`, `label`, `sublabel`, `room`,
`icon|iconUrl`, `on`, `tone`, `color`, `style`, `nav` oder `cmd`,
`controls[]`, `kopfTaste` (`schieber` | `rund`, Taste oben rechts), `secured`.

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

*Einstellungen → Diagnose* zeigt unter `weatherServer`, was die Anlage meldet: die
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

Der Code liegt in `bin/statistik.py` (Parser auf Modulebene, die Methoden als
Mixin `Statistik`, das `App` erbt).

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
`/mjpeg`): Eine in LoxPanel eingetragene Adresse (Einstellungen → Kamera /
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

Die native Android-App ergänzt direkte Gen-1-Anrufe: `sip_call.py` führt
INVITE/Digest/ACK/BYE und SDP, Android übernimmt RTP-G.711 mit
AudioRecord/AudioTrack. `IntercomTalk` verwaltet eine Sitzung und deren
15-Sekunden-Lebensfrist. Start/Stop/Status sind nur über Loopback mit dem
nativen Prozess-Token erreichbar; SIP-Zugangsdaten bleiben im Python-Prozess.
Die Visu zeigt Sprechen/Auflegen über `LoxKiosk` ausschließlich in der App.
Die Freigabe betrifft nur den Typ `Intercom`; `deviceType` ist keine
zuverlässige Generationskennung. `IntercomV2` behält Kamera, Klingel, Tür,
Antworten und Stummschaltung, bekommt aber keine Sprechbedienung. Ein fehlender
SIP-Host in `audioInfo` bleibt ein Fehler, auch wenn `videoInfo` eine
Kameraadresse enthält. Auf der getesteten Anlage fehlt `audioInfo` trotz
eingetragenem Audio-Host und Zugang in Loxone Config; die Quelle dieses
Zugangs muss dort noch geklärt werden.
Umfang, Schnittstelle, Tests und Hardware-Prüfliste:
[`INTERCOM_GEN1.md`](INTERCOM_GEN1.md).

## 4. HTTP- und WebSocket-Schnittstelle

Alle Routen werden in `main()` (`webvisu.py`) registriert, die Handler stehen
je Thema in `bin/routen/`: `oberflaeche.py` (`/`, `/config`, `/settings`,
`/i18n.js`, `/raster.js`, `/config.css`, `/config/{name}`, `/panel/{name}`),
`visu.py` (`/ws`), `konfigurator.py` (`/api/meta`, `/api/kachelset`,
`/api/panels`, `/api/entwurf`, `/api/theme`, `/api/types`), `einstellungen.py`
(`/api/settings`, `/api/settings/miniserver`, `…/night`, `…/audiometa`,
`…/calendar`, `/api/backup`, `/api/restore`), `intercom.py`
(`/api/settings/intercom`, `/api/sip`, `/api/sip/pruefen`,
`/api/intercom/talk/*`, `/mjpeg`), `geraete.py` (`/install-agent.sh`,
`/api/agent/*`, `/api/agents`, `/api/devices`, `/api/device/*`,
`/api/vorschau/beenden`, `/api/display`, `/api/mode`, `/api/reload`,
`/api/goto`, `/api/notify`, `/api/testtone`), `medien.py` (`/icon`,
`/api/loxicons`, `/loxlib`, `/bellimg`, `/cover`) und `system.py`
(`/api/health`, `/api/diagnose`). Es gibt keine
Authentifizierung, keine Middleware, kein CORS auf den allgemeinen Routen.
Ausnahme: die native Gegensprech-API verlangt Loopback und Prozess-Token
([`INTERCOM_GEN1.md`](INTERCOM_GEN1.md)).

| Methode | Pfad | Handler | Zweck | Genutzt von |
|---|---|---|---|---|
| GET | `/` | `index` | `panel.html` | Visu |
| GET | `/config` | `config_index` | `config.html` | Konfigurator |
| GET | `/settings` | `settings_index` | Weiterleitung nach `/config` (Anker bleibt) | alte Links |
| GET | `/i18n.js` | `i18n_js` | Übersetzungskatalog | Konfigurator, Einstellungen |
| GET | `/raster.js` | `raster_js` | Rasterrechnung (§7.5) | Visu, Konfigurator |
| GET | `/config.css`, `/config/{name}` | `config_css`, `config_js` | Stylesheet und Skriptteile des Konfigurators (`webfrontend/html/config/<name>.js`, nur schlichte Namen) | Konfigurator |
| GET | `/panel/{name}` | `panel_teil` | Stylesheets und Skriptteile der Visu (`webfrontend/html/panel/<name>.css|.js`, nur schlichte Namen) | Visu |
| GET | `/install-agent.sh` | `install_script` | Installer als Text | Panel-Installation |
| GET | `/api/kachelset` | `api_kachelset` | Nachgerechnete Kontraste eines Kachel-Sets mit Rechnung zu `farbton` und `aktiv` (`theme_colors.kachel_set_pruefung()`) und seine Kachelfarbe, nur lesend; unbekanntes Set 404 | Konfigurator („Nachgerechnet“) |
| GET | `/api/meta` | `api_meta` | Räume, Kategorien, alle Controls, Icons, Profile, Geräte (Display-Kennwort nur als `hasPass`, `_devices_export()`), Theme, Bausteine mit `active`-State (`activeControls`, Auswahl Präsenzmelder), Stunde des nächtlichen Neuladens (`reloadAt`) | Konfigurator, Einstellungen |
| POST | `/api/panels` | `api_save_panels` | `panels.json` schreiben, danach `reload` an alle Panels (Vorschau-Fenster mit einem Entwurf bekommen stattdessen `entwurfEnde`) und alle Entwürfe verwerfen; die Antwort nennt unter `verworfen`, was `_sanitize_panels` nicht übernommen hat | Konfigurator |
| POST | `/api/entwurf` | `api_entwurf` | Entwurf eines Profils `{id, panel, token?}` für die Vorschau in der echten Visu: geprüft wie beim Speichern, nur im Speicher; Antwort `token`, `url` (`/?panel=<id>&entwurf=<token>`), `verworfen`, `reloaded` (Visus, die ihn zeigten und neu laden) | Konfigurator |
| POST | `/api/theme` | `api_save_theme` | `theme.json` schreiben, danach `reload` | Konfigurator |
| GET | `/api/settings` | `api_settings` | Miniserver-Status (ohne Passwort), Intercom-Liste, Einrichtungsstand `einrichtung` (`_einrichtung_info()`: `stand` `kein_zugang`, `verbindet` oder `fehler`, dazu `host` und `fehler`; mit Struktur `null`), `version` (`version`, `commit`, `gebaut`; `version_info.lesen()`, Seitenleiste des Konfigurators) | Einstellungen, LoxBerry-Widget |
| GET | `/api/health` | `api_health` | Zustand: Hintergrund-Aufgaben (`miniserver`, `broadcaster`, `audio`, `front`), Miniserver verbunden, Zahl der Panels, Laufzeit, `version` wie bei `/api/settings`. 503, sobald eine Aufgabe beendet ist; ein fehlender Miniserver allein ist kein Fehler | Docker-`HEALTHCHECK` (Unraid) |
| GET | `/api/backup` | `api_backup` | ZIP mit `loxpanel.cfg`, `panels.json`, `theme.json`, Kennwörter (`pass`, `password`) leer, dazu `LIESMICH.txt` und `sicherung.json` (je Datei die Pfade der entfernten Kennwörter, für `/api/restore`). Nicht lesbares JSON bleibt draußen | Einstellungen → Sicherung |
| GET | `/api/diagnose` | `api_diagnose` | Diagnosepaket als ZIP (`bin/diagnose.py`): `?device=` für ein Gerät (Zustand aus `device_list()`, seine Einstellungen, die gezeigte Ansicht), sonst der Server mit allen Geräten. Immer dabei: Version, Laufzeit, Hintergrundaufgaben (`_aufgaben_stand()`, wie `/api/health`), Miniserver (verbunden seit, weg seit, letzte Nachricht, letzter Fehler, Struktur mit Typ, Name und Projekt aus `msInfo`), Audioserver (verbunden, gekoppelt, angemeldet), die Einstellungsdateien und die letzten Log-Zeilen. Geheimnisse entfernt (§9.2). 404 für ein unbekanntes Gerät | Geräte → Diagnose, Einstellungen → Sicherung |
| POST | `/api/restore` | `api_restore` | Sicherung einspielen, Body = ZIP aus `/api/backup`. Immer nur eine zur Zeit. Erst alles prüfen, in einem Thread, damit die Visu bedienbar bleibt (`_sicherung_lesen`, `_sicherung_pruefen`: nur Deflate oder ungepackt, je Datei höchstens 2 MiB – auch so, wie sie danach geschrieben wird, damit sich der Stand wieder einspielen lässt –, höchstens 32 Ebenen tief und 200.000 Einträge, nur endliche Zahlen und gültiges Unicode, Typen der gelesenen Abschnitte von `loxpanel.cfg`, Profile, Geräte und globale `ui` durch dieselben Sanitizer wie beim Speichern), dann schreiben (vorher `.bak`) und ohne Neustart auffrischen (`_sicherung_schreiben`). Ein vorhandenes Kennwort bleibt nur bei gleichem Ziel (Host, URL, Benutzer, Treiber). Wo eines entfernt wurde, sagt `sicherung.json`, bei älteren Sicherungen die Liste in `LIESMICH.txt`. Ein laufender Zugang bleibt stehen, wenn die Sicherung keinen Miniserver hat oder ihrem Zugang Benutzer oder Kennwort fehlt, ebenso einer aus `LOXPANEL_MS_*`; neu verbunden wird nur bei geändertem Zugang, scheitert das, bleibt der alte (auch der aus `LOXPANEL_MS_*`). Antwort: `dateien`, `nichtEnthalten`, `nichtEingespielt` (nach einem Schreibfehler), `kennwoerter` (`behalten`, `fehlen`), `verworfen`, `miniserver`, `miniserverZiel`, `miniserverFehler`, `reloaded`; 400 bei kaputter Sicherung (nichts geschrieben), 500 nach einem Schreibfehler (Teilergebnis mit `error` und `nichtEingespielt`), 413 über 1 MiB | Einstellungen → Sicherung |
| GET | `/api/types` | `api_types` | Diagnose: Bausteintypen der Anlage mit Status (voll/teilweise/keine), Anzahl, Beispielen, State-Namen, `details`-Schlüsseln und Liste der toten Kacheln; `?format=text` als Tabelle | Einstellungen, Entwicklung |
| POST | `/api/settings/miniserver` | `api_settings_ms` | Zugang erst prüfen (`reconnect(ms)`), dann speichern. Abgelehnt: nichts gespeichert. Nicht erreichbar: gespeichert, `gespeichert: true` mit Warnung, eine bestehende Verbindung bleibt bis zum nächsten Aufbau. `error` ist ein fester Text, der Fehler des Miniservers steht in `fehler`. Nacheinander, auch mit `/api/restore` (`_zugang_sperre`) | Einstellungen, LoxBerry-Widget |
| POST | `/api/settings/intercom` | `api_settings_intercom` | Kamera-URL/Login je Intercom | Einstellungen |
| GET | `/api/sip` | `api_sip` | Intercoms der Anlage (Türsteuerung `Intercom` und Baustein Intercom `IntercomV2`) mit `uuid`, `name`, `type`, `room`, `deviceType` und dem SIP-Zugang aus den gesicherten Details (`sip`: `host`, `user`, `hasPass`) oder dem Grund, warum es keinen gibt (`error`; `ohneSip`, wenn der Miniserver geantwortet hat, aber keinen nennt; hat der Baustein gesicherte Details ohne SIP-Teil, dazu `felder`: je Abschnitt die Feldnamen und ob sie gefüllt sind, ohne Werte); dazu `connected`. Das Passwort steht nie darin. Jede Intercom mit dem Kennzeichen `securedDetails` kostet eine verschlüsselte Anfrage an den Miniserver, darum lädt der Konfigurator erst beim Öffnen des Reiters | Einstellungen → SIP |
| POST | `/api/sip/pruefen` | `api_sip_pruefen` | Body `{uuid}`: OPTIONS an die Türstation mit dem Zugang vom Miniserver (`sip_probe.pruefen()`). Antwort `ok`, `ziel`, `erreichbar`, `antwort`, `anmeldung` (`angenommen`, `abgelehnt`, `nicht verlangt`, `kein Passwort`, `unbekanntes Verfahren`, `keine Antwort`), `gegenstelle`, `methoden`, `codecs`, `ms`, `error`. Adresse und Passwort kommen nie aus der Anfrage; 404 für eine unbekannte Intercom, 400 ohne gültiges JSON | Einstellungen → SIP |
| POST | `/api/settings/audiometa` | `api_settings_audiometa` | Audioserver-Live-Daten (Gen2-Events) ein/aus | Einstellungen |
| POST | `/api/settings/calendar` | `api_settings_calendar` | iCal-Abo + Wetter-Koordinaten für die Front speichern, `front_task` lädt sofort neu | Einstellungen |
| POST | `/api/agent/announce` | `api_agent_announce` | Agent meldet sich (`features: ["panel"]`: kann eine Ansicht übernehmen), Antwort enthält `dpmsOff`, `reloadHours` (`null` ohne Eintrag: der Agent nimmt `RELOAD_HOURS` seiner kiosk.conf) und, wenn für ihn eine Ansicht ansteht (`agent_wunsch`), `panel`; die beiden Werte gelten dann schon für sie | Panel-Agent |
| GET | `/api/agents` | `api_agents` | bekannte Agenten (`online` < `AGENT_ONLINE` = 60 s, gelistet < 600 s) | Einstellungen |
| POST | `/api/agent/command` | `api_agent_command` | `start`/`reload`/`stop` an einen Agenten weiterleiten (Zeitlimit `AGENT_BEFEHL_TIMEOUT`). `start` verwirft eine offene Wahl und hebt `last_mode` für das Gerät auf, `reload` mit offener Wahl wird zu `start` mit ihr | Einstellungen |
| POST | `/api/devices` | `api_save_devices` | Betriebsmodus-Zuordnung je Gerät. Ein leeres Display-Kennwort heißt „unverändert“, aber nur bei gleichem Ziel wie beim Einspielen (`_KENNWORT_ZIEL`: Host und Treiber, genau verglichen, auch Groß-/Kleinschreibung; der Port zählt nicht). Antwort: `devices` (Kennwort nur als `hasPass`) und `kennwortVerworfen` (Geräte, deren Kennwort wegen eines anderen Ziels verworfen wurde, der Konfigurator warnt) | Einstellungen |
| GET | `/api/devices` | `api_devices_get` | alle Anzeigegeräte (Agent, Kiosk-App, Browser) mit Online-Status, Ansicht, Typ und Präsenzstand (`presence`, nur mit gekoppeltem Präsenzmelder); Browser ohne Namen nach IP | Einstellungen |
| POST | `/api/device/switch` | `api_device_switch` | Ansicht eines Geräts wechseln (`{device, panel, ip}`) – das ist die Zuordnung des Geräts (`devices[name].panel`, gespeichert; leer = Standardansicht, ein Gerät ohne andere Einstellungen entsteht dabei; nicht online: `ok` mit `offline`, es zeigt sie beim Verbinden): offene Visu per WebSocket-Push; der Agent der Zeile (über `ip`, nicht den Namen, online) bekommt die Wahl über die nächste Meldung (`agent: "announce"`), ein älterer Agent oder ein Kiosk ohne offene Visu `/start` (`agent: "start"`; scheitert es bei einem Agenten mit `features`, `"announce"`). Hebt `last_mode` für das Gerät auf. Mit `entwurf` (Token von `/api/entwurf`, Punkt 12) zeigt das Gerät einen ungespeicherten Entwurf: nur über eine verbundene Visu (sonst „Keine verbundene Visu“), das Profil muss nicht gespeichert sein, Antwort `zurueck` = Profil davor | Einstellungen, Konfigurator |
| POST | `/api/vorschau/beenden` | `api_vorschau_beenden` | Vorschau am Gerät beenden `{device}`: es kehrt zum Profil davor zurück, `beendet` sagt, ob eine Visu zurückgeschaltet wurde | Konfigurator |
| POST | `/api/device/name` | `api_device_name` | Browser ohne Namen benennen: `{code, name}` trifft genau die Verbindung mit diesem Kopplungscode, `{ip, name}` alle ohne Namen unter der IP; Visu merkt sich den Namen und verbindet neu | Einstellungen |
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
gilt wieder, was unter *Ansichten → Aussehen → Aktiv-Overlay* (Positionsring) eingestellt ist.

Kachel-Icons kommen aus drei Quellen, genau denen des Kachel-Editors:
eingebaut (`builtin`), Loxone-Icon des Miniservers (`loxone`, über `/icon`)
und Loxone-Bibliothek (`loxlib`, über `/loxlib`). Google- und eigene Icons
(`google`, `custom`) aus Upstream erzeugten Adressen `/gicon` und `/uicon`,
die es nie gab. Seit 17.10.2026 nimmt `_clean_icon()` sie nicht mehr an, und
die Visu kennt kein `iconImg` mehr.

---

## 5. Konfigurationsdateien

Alle liegen in `config/` (im Container `/app/config`, als Volume gemountet).
Pfade sind Modul-Globals in `konfig.py` (`CFG_FILE`, `PANELS_FILE`, `THEME_FILE`).

### 5.1 Miniserver-Zugang, Priorität

`_config()` (`konfig.py`), dahinter `_ms_zugang()`, das auch die Quelle nennt:

1. `loxpanel.cfg` → `miniserver` (nur wenn `host` gesetzt, dann gilt der
   Abschnitt ganz)
2. Umgebungsvariablen `LOXPANEL_MS_HOST/USER/PASS/PORT/VERIFY_TLS`; ein leerer
   oder ungültiger Port wird 443
3. leer, Server startet trotzdem, wartet und zeigt den Panels den
   Einrichtungshinweis (§3, `einrichtung`); der Konfigurator führt dann zuerst
   zu Einstellungen → Miniserver (§7.3)

`loxpanel.cfg.example` gilt nie als Zugang: Ihr `miniserver`-Abschnitt ist ein
Platzhalter (`192.168.1.50`, `CHANGEME`). Die Android-App bringt die Vorlage
mit; früher meldete sich ein frisches Panel damit endlos bei `192.168.1.50`
an. Auch `_load_cfg()` lässt den Abschnitt der Vorlage weg, damit Settings ihn
nicht vorausfüllt und kein Speichern einer anderen Einstellung ihn in die
`loxpanel.cfg` schreibt. Die übrigen Abschnitte der Vorlage bleiben Vorgaben.

Ein unter `/config` (Einstellungen → Miniserver) gespeicherter Zugang hat also Vorrang vor Docker-Variablen.

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

Gelesen in einem Zug von `load_panels_doc()` (Ansichten und Geräte; `load_panels()`
liefert nur die Ansichten), geschrieben über
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
                                             // aus der Front (FRONT_TABS), `haus` =
                                             // Hausuebersicht (HAUS_TAB). Der ERSTE
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
      "pickTabs": [{                         // freie Seiten, max. PICK_TABS_MAX; ihre Tabs heißen
                                             // "auswahl", "auswahl2" … in "tabs"; ein altes
                                             // picks/pickName wird zur ersten Seite
        "name": "Auswahl",                   // max. 40 Zeichen; fehlt = „Auswahl“
        "icon": "/icon?p=…",                 // optional, nur Adressen der Icon-Auswahl
                                             // (_clean_seiten_icon)
        "picks": ["<control-uuid>"],         // Bausteine der Seite, max. 60
        "widget": "energy:<uuid>",           // optional: ein Widget als ganze Seite statt
                                             // Kacheln, Grammatik wie "panes" ohne "header"
                                             // (_clean_widget_tab)
        "layout": [{"id": "<uuid>", "w": 2, "h": 1}],   // optional, Seiten-Editor: Reihenfolge
                                             // und Größe 1×1, 2×1, 2×2; Bausteine ohne Eintrag
                                             // hängen hinten an (_layout_mit_picks)
        "byRoom": false                      // optional; fehlt = in der Visu nach Raum gruppiert
        "bento": {                           // optional, LoxOS (Fork, VISION.md): Raster mit festen
                                             // Zellen; Vorrang beim Anzeigen bento > widget > Kacheln
          "cols": 6, "rows": 2,              // BENTO_SPALTEN_MIN..MAX, BENTO_ZEILEN_MIN..MAX (begrenzt);
                                             // fehlt = BENTO_SPALTEN_STANDARD, BENTO_ZEILEN_STANDARD
          "format": {"vw": 2560, "vh": 720}, // optional: Fläche des Vorschaugeräts (CSS-px)
          "cells": [                         // leer = gültig; je Zelle Spalte, Zeile, Breite, Höhe
            {"x": 0, "y": 0, "w": 1, "h": 2, "widget": "clock"},   // Widget: wie "widget" oben ohne
                                             // "haus", dazu "clock"; gleiche Quelle je Seite einmal
            {"x": 1, "y": 0, "w": 2, "h": 1, "ids": ["<uuid>"]},  // Bausteine aus picks, je Seite
                                             // einmal, max. BENTO_ZELLE_BAUSTEINE_MAX je Zelle
            {"x": 3, "y": 0, "w": 1, "h": 1, "widget": "iframe",
             "url": "https://…", "name": "Drucker"}               // Webseite: nur http/https mit Host,
                                             // ohne Zugangsdaten (_clean_iframe_url); name optional
          ]                                  // ragt eine Zelle über den Rand oder überlappt eine
        }                                    // frühere, fällt sie weg und wird gemeldet (verworfen)
      }],
      "device": {"name": "tablet", "vw": 1024, "vh": 600},   // Zielgerät: für welches Gerät das Profil gemacht
                                             // ist, mit der beim Wählen gemeldeten Größe (CSS-px,
                                             // optional); Displays warnt bei Abweichung (§6); auch ein
                                             // blosser Name geht; fehlt = keines
      "ui": {
        "iconSize": 38, "nameSize": 18, "subSize": 15,   // px; fehlt = global, sonst Standard des
        "roomSize": 12, "bigSize": 36,       // Kachel-Aufbaus (GROESSEN_STANDARD, §5.4)
        "font": "Inter",
        "textColor": "#e8eaed", "bold": true, "lang": "de",
        "tileLayout": "classic",             // Kachel-Aufbau: nur "classic"; fehlt = der neue (§7.1)
        "tileSet": "touch",                  // Kachel-Set aus theme_colors.KACHEL_SETS; fehlt = Farben aus
                                             // der Grundfarbe, "classic" gilt mit Set nicht (§5.4)
        "tileHue": 160,                      // Farbton des Sets "touch", 0-359; fehlt = 270
        "tileActive": "dunkel",              // aktive Kachel bei "touch": "hell" | "dunkel"; fehlt = "hell"
        "grid": "auto",                      // automatisches Raster (Tablet): cols/rows gelten dann nicht (§7.1)
        "tileSize": 200,                     // Zielkachel des automatischen Rasters in px (KACHEL_ZIEL_MIN
                                             // bis KACHEL_ZIEL_MAX); fehlt = KACHEL_ZIEL_STANDARD; die alten
                                             // Stufen "small" | "medium" | "large" werden gelesen
        "paneCols": 2,                       // Widget-Breite im automatischen Raster in Kachelspalten
                                             // (hochkant Zeilen), 1 bis PANE_SPALTEN_MAX; fehlt = rund
                                             // PANE_ANTEIL der Spalten (§7.1)
        "nudgeX": -6, "dpmsOff": 180, "reloadHours": 12,
        "pinMerken": 60,                     // Sek., die die Visu eine bestätigte Visu-PIN behält;
                                             // 0 = jedes Mal fragen, fehlt = PIN_MERKEN_STANDARD
        "gesten": true,                      // Zwei-Finger-Gesten an/aus; fehlt = wie Vorgaben (§7.1 „Gesten“)
        "gestenRaum": "<room-uuid>",         // Raum der Gesten außerhalb von Raumseiten; fehlt = dort keine
        "gestenHinweis": true,               // Hinweis-Symbol der Gesten an/aus; fehlt = wie Vorgaben
        "nightClock": true,                  // Nacht-Uhr an/aus; fehlt = wie Vorgaben (§7.1 „Gesten“, Stufe 5)
        "nightClockBright": 30,              // ihre Helligkeit in %, NACHT_UHR_HELL_MIN bis 100;
                                             // fehlt = Vorgabe, sonst NACHT_STANDARD
        "cols": 4, "rows": 3, "fill": true,
        "scale": "auto",                     // "off" | "auto" | Faktor 0.5–2.0; fehlt = wie global
        "catFilter": true,                   // Sprungmarken filtern statt springen (nur true, fehlt = springen)
        "valueBar": ["favoriten", "room:<uuid>", "raeume"],   // Seiten, deren Anzeige-Bausteine (WERTE_LEISTE_TYPEN)
                                             // als Werteleiste in EINER Zeile über dem Raster stehen statt
                                             // als Kacheln; "raeume"/"kategorien" = die Raum- bzw.
                                             // Kategorie-Seiten darunter; fehlt = alles Kacheln (§7.1)
        "panes": {"favoriten": "chart:<uuid>"},   // zweite Hälfte je Tab (quer rechts, hochkant unten): "weather" | "calendar" |
                                             // "player:<uuid>" | "energy:<uuid>" | "camera:<uuid>[|<uuid>,…]" (Kamera,
                                             // hinter dem Strich Werte unter dem Bild, `_clean_camera()`) |
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
      "panel": "<panel-id>",                 // die Ansicht, die das Gerät zeigt (Einrichtung neu, Schritt 2):
                                             // die eine Stelle dafür. Schreibt „Ansicht wechseln“ und „Start“
                                             // mit Ansicht; ws_handler zieht das Gerät beim Verbinden darauf,
                                             // egal was ?panel= oder die kiosk.conf sagen; der Agent bekommt
                                             // sie mit seiner Meldung. Fehlt = das Gerät folgt seiner Adresse
      "auto": true, "modes": {"<Modusname>": "<panel-id>"},   // Betriebsmodi überlagern die Zuordnung nur
      "display": {"driver": "fully", "host": "192.168.1.60", "port": 2323, "password": "..."},  // optional; auch "wallpanel" (Port 2971)
                                             // Kennwort verlässt den Server nicht: /api/meta nennt nur hasPass
      "scale": "off",                        // optional; übersteuert Profil und global ("off" | "auto" | Faktor)
      "tileTarget": 260,                     // optional; Zielkachel des automatischen Rasters für dieses Gerät
                                             // (Gerät vor Profil, nur im Kachel-Layout „Automatisch“; §7.1)
      "presence": "<control-uuid>",          // optional; Präsenzmelder (Baustein mit active-State):
                                             // Display an, solange er jemanden meldet (§8)
      "lichtStart": {"lc": "<uuid>", "mood": 1}   // optional; Stimmung beim Einschalten (Gesten, §7.1):
                                             // was zwei Finger einschalten, wenn im Raum alles aus ist,
                                             // und zu welcher Lichtsteuerung das Gerät gehört
    }
  }
}
```

Die Validierung in `_sanitize_panels()` (`konfig.py`, als `App._sanitize_panels()`
erreichbar) ist eine Whitelist, die unbekannte
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
der Konfigurator unter Vorgaben → Darstellung setzt, steht einmal in
`THEME_UI_KEYS`: `_write_theme()` schreibt genau diese, `/api/meta` liefert
genau diese. Was `_sanitize_theme_ui()` neu erlaubt, muss auch dort stehen,
sonst geht es beim Speichern still verloren. Dazu gehört `scale`, die
Skalierung für alle Panels; fehlt sie, ist sie aus. Ebenso `nightDim` und
`nightWake` (Vorgaben → Verhalten, Grenzen wie im Panel 0 bis 90 % und 0 bis
300 s): `panel_night()` nimmt sie, wo das Panel keine eigenen setzt, sonst gilt
`NACHT_STANDARD` (aus, 20 s), das `/api/meta` als `nightDefaults` an den
Konfigurator gibt. Und `dpmsOff` (0 bis 3600 s) und `reloadHours` (0 bis 168 h)
für `panel_dpms()` und `panel_reload()`: ohne Eintrag in Panel und Vorgaben
bleibt es bei `None`, dann nimmt der Agent seine `kiosk.conf` (`DPMS_OFF`,
`RELOAD_HOURS`), die Visu schaltet das Display nicht ab und lädt nachts um
`NEULADEN_STUNDE` neu.

Die Gesten (§7.1) haben vier Einträge unter Vorgaben → Verhalten: `gesten`
(an/aus für alle Ansichten, gespeichert nur, wenn es vom `GESTEN_STANDARD`
abweicht; eine Ansicht kann es selbst setzen), `gestenHinweis` (Hinweis-Symbol,
ebenso gegen `GESTEN_HINWEIS_STANDARD`), `hausAus` (Taster für den
Dreifachtipp) und `raumVerlassen` (`{Raum-UUID: Taster-UUID}` für den
Doppeltipp). Beide Taster sind Bausteine vom Typ `Pushbutton` ohne
Visu-Passwort (`geste_taster_optionen()`, `/api/meta` `gestenTaster`): Laut
Strukturdoku nimmt nur der Taster einen Impuls (`pulse`).

Die Nacht-Uhr hat zwei Einträge neben „Nachts abdunkeln“: `nightClock`
(an/aus, gespeichert nur abweichend vom Standard) und `nightClockBright`
(Helligkeit in Prozent, `NACHT_UHR_HELL_MIN` bis 100). `panel_night()` gibt
sie mit `dim` und `wake` als `uhr` und `uhrHell` an die Visu (`theme`
`night`), ohne Eintrag gilt `NACHT_STANDARD` (aus, 40 %).

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
leert die Felder unter Vorgaben → Darstellung.

In `ui` steckt auch `baseColor`: die Grundfarbe des Panel-Themes. Steht sie da,
leitet `theme_colors.derive()` daraus den ganzen Farbsatz ab — Hintergrund,
Kachel, Leiste, Schrift, Zweitzeile, Icon- und Zustandsfarben — und
`_theme_vars()` schickt ihn als CSS-Variablen mit. Ohne `baseColor` ändert sich
nichts: jede Farbe in `panel.html` trägt ihren bisherigen Wert als Rückfall.
Ausdrücklich gesetzte `states` schlagen die Herleitung.

Ein Kachel-Set (`ui.tileSet`, je Ansicht) ersetzt die Herleitung durch einen
fertigen Look. Jedes Set steht genau einmal in `theme_colors.KACHEL_SETS`:
Name und Beschreibung für den Konfigurator, `aufbau` der Kachel (`lx` flach wie
die Loxone-App, `mitte` mit Symbol mittig und einer aktiven Kachel, die ganz
umkippt, `kreis` mit dem Symbol in einem Kreis), `leiste` (`pille` unten,
`oben` nur Symbole über dem Raster, `links` als Seitenleiste), feste `farben`,
`masse` und `groessen`. Die Maße kommen aus dem Entwurf („LoxPanel Kachel-Set
Loxone“, Design-Canvas): Radien, Schatten, Kreis, Leistenhöhe, Pille,
Tab-Symbole, Rahmen und Feld (touch), Seitenleiste (kreide), Abstand und
Innenrand des Rasters; ein Maß mit `-schmal` gilt unter `SCHMAL_UNTER`
(`raster.js`, 600 px) Breite, die der Tab-Leiste (`--tabs-hoehe`, `--pille-h`,
`--tab-symbol`) auch unter 600 px Höhe: Auf einem breiten, niedrigen Schirm
(Fenster am Mac, flaches Display) nähme die 96-px-Leiste sonst ein Fünftel der
Höhe. Nennt ein Set `--leiste-voll-ab` (loxone: 820 px, iPad quer), gelten
Leistenhöhe und Pille erst ab dieser Schirmhöhe voll, darunter schrumpfen sie
mit der Höhe bis zu ihren `-schmal`-Maßen (`raster.js` `leisteMass()`, die
Visu setzt das Ergebnis in `schmalEinrichten()` als `--k-tabs-h`/`--k-pille-h`
am Kasten). `--pille-tab-breite` macht die Pille je Eintrag so breit, höchstens
560 px wie ohne das Maß; `renderTabs()` setzt die Zahl der Einträge
(`--tab-n`). `groessen` sind Standardgrößen der Kachel, die das Set
mitbringt (touch: größeres Symbol), eine eingestellte geht vor; mit Set gilt
`ui.tileLayout` nicht. „touch“ hat statt fester Farben einen
`satz`: `touch_satz(farbton, aktiv_hell)` rechnet Schrift, Kachel, Fläche,
Taste, aktive Kachel und Tab-Symbole aus dem Farbton (`ui.tileHue`) und lässt
jede Helligkeit wandern, bis ihr Kontrast erreicht ist. Rollen, die ein Set
nicht nennt (Zweitzeile, Zustandsfarben, Störung, Text auf dem Akzent),
rechnet `_ergaenzen()` nach denselben Regeln wie `derive()` gegen die Flächen
des Sets nach. `_theme_vars()` schickt Farben und Maße als CSS-Variablen,
`resolve_profile()` die Art als `tileSetAufbau`/`tileSetLeiste`, `/api/meta`
die Auswahl als `kachelSets` (mit den fertigen Farben der Schnellwahl).
Ausdrücklich gewählte Zustandsfarben und Farben aus „Kacheln gestalten“
gelten auch mit Set. `tests/test_kachel_set.py` rechnet jedes Paar nach, das
die Visu bei der Art des Sets aufeinander setzt, für „touch“ über alle
Farbtöne in 5er-Schritten. Die Trennbarkeit für rot-grün-blinde Augen
verlangt er nur beim Aufbau `lx`, wo allein die Tönung „aktiv“ zeigt: Bei
`mitte` und `kreis` trägt die Form den Zustand, und die festen Farben von
„Kreide“ (Orange, Grün, Grau) fallen unter Deuteranopie zusammen.

Text steht nie auf dem Rahmen. `--bg` ist der Grund der Uhr-Seite, der PIN
und der Seite außerhalb der Kacheln und trägt dieselbe Schrift wie `--screen`
(`_paare()`: Schrift AAA, Zweitzeile AA). Der dunkle Rand um das Feld bei
„touch“ ist eine eigene Rolle, `--rahmen` (fehlt sie, gilt `--bg`), die nur
Kasten, Seitengrund und Leiste färbt. Vorher war der Rand `--bg`, und die
Uhr-Seite stand mit dunkler Schrift auf Schwarz. `--on-accent` gilt nur auf
vollem `--accent`; zu einer eingestellten OK-Farbe rechnet `_theme_vars()`
es mit `schrift_auf()` nach. `tests/browser/test_kachel_set_kontrast_browser.py`
misst im Browser jeden sichtbaren Text jeder Ansicht (Raster, Uhr-Seite,
Kalender- und Wetter-Tab, Front daneben, Kopfzeile, Detailseite, PIN) gegen
die Fläche, auf der er wirklich steht: ohne Set, mit jedem festen Set und mit
„touch“ in jedem Farbton der Schnellwahl und beiden Arten der aktiven Kachel.
Verlangt sind AA, für große Schrift 3:1.

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
geplant). Technisch gibt es zwei Ebenen; seit Schritt 3 des Zerlegens
(15.10.2026) liegen sie je Bausteinfamilie in `bin/bausteine/`:

- **Kachel:** `App._control_item()` baut den Kopf (Name ohne Raum, Raum,
  `secured`, Icon-URL, Kategoriefarbe), ruft dann die Kachel-Funktion des Typs
  aus der Tabelle `bausteine.KACHEL` (`kachel_fuer(t)`, `fn(app, uuid, c, it)`
  ergänzt `icon`, `on`/`tone`, `sublabel` und entweder `nav` (Detailseite) oder
  `cmd` (Direktschaltung) oder `controls[]` (Mini-Buttons)) und schließt mit dem
  Fuß (Status-Bausteine antippbar, gesperrt mit „Gesperrt“ und `nav` statt
  `cmd`/`controls`, Kategorie-Ampel, `_apply_tile_style()`).
- **Detailseite:** `App._view_control_inner()` ruft die Detail-Funktion des Typs
  aus `bausteine.DETAIL` (`detail_fuer(t)`, `fn(app, uuid, c, route)` liefert die
  `view`-Nachricht mit `blocks[]`); `_view_control()` hängt Verlauf und
  verlinkte Objekte an.

Die Familien (je ein Modul): `licht` (LightControllerV2, LightController,
Dimmer, ColorPickerV2), `schalten` (Switch, TimedSwitch, Daytimer, Pushbutton,
UpDownDigital, Radio), `beschattung` (Jalousie, Gate, Window), `klima`
(IRoomControllerV2, IRoomController, AcControl, ClimateControllerUS,
Ventilation), `audio` (AudioZone, AudioZoneV2), `intercom`, `werte`
(ValueSelector, UpDownAnalog, Slider, TextInput, InfoOnly*, TextState, Meter,
Hourcounter, Tracker, Webpage, SystemScheme), `sicherheit` (Alarm, SmokeAlarm,
PresenceDetector, WindowMonitor, MailBox), `wecker` (AlarmClock), `energie`
(Fronius, EFM, EnergyManager2, PvProductionForecast), `garten` (Irrigation),
`wellness` (Sauna, SteakThermo), `zentral` (Präfix `Central`, nur Kachel, die
Detailseite ist die Gruppe). Jede Funktion trägt sich mit `@kachel("Typ", …)`
bzw. `@detail("Typ", …)` ein, ein Typ höchstens einmal je Tabelle (ein zweiter
Eintrag ist ein Fehler beim Import). Die Helfer der Bausteine sind Methoden
von Mixin-Klassen (seit Schritt 4b des Zerlegens): die allgemeinen (`_state`,
`_text`, `_json_state`, `_fmt_num`, `_named_items`, `_big_view` …) in
`bausteine/helfer.py` (`Grundhelfer`), die einer Familie in ihrem Modul
(`KlimaHelfer` mit `_irc1()`, `WeckerHelfer` mit `_alarm_entries()`,
`BeschattungHelfer` mit `_jal_fahrt()`, `EnergieHelfer` mit `energy_blocks()` …),
dort auch die Unterseiten der Familie (Weckzeit und Wecker-Einstellungen,
Bewässerungszone, Klingelbilder, Favoriten der Zone, Anlagenschema), beim
Audio die Blöcke des Spielers (`player_blocks()`). Was den Miniserver braucht,
etwa SIP-Zugang und Kamera der Intercom, steht in einem Themenmodul
(`intercomdienst.py`): Die Bausteine sind die untere Schicht und importieren
kein Themenmodul, die Themen importieren aus ihnen.
`bausteine.BausteinHelfer` fasst sie zusammen, `App` erbt es; gerufen wird
weiter über `app.` bzw. `self.`. Typmengen, Konstanten der Strukturdoku (Sauna,
Raumregelung v1/v2, Bewässerung, Intercom), die Adapter `LIGHT`/`JAL` und die
reinen Helfer `_clean()`, `_pos_pct()`, `_dauer_text()` liegen in
`bausteine/gemeinsam.py`; `webvisu.py` und die Themenmodule importieren, was sie brauchen.
`tests/test_bausteine.py` kennt die Typen je Familie und prüft Tabellen,
Signaturen, Doppeleinträge und den Rückfall für unbekannte Typen.

**Tasten auf der Kachel** (`controls[]`, je `icon` und `cmd`) haben der Player
(◀ ⏯ ▶), die Beschattung (▲ ▼) und die Lichtsteuerung (‹ ›, seit 18.10.2026).
Die Lichtsteuerung schaltet damit die vorige bzw. nächste Stimmung
(`changeTo/<id>`), nach derselben Regel wie das Quer-Wischen der Gesten
(`_lc_schritt()` in `LichtHelfer`, die Liste ohne „Aus“ aus `_lc_ohne_aus()`):
„Aus“ übersprungen, rundum, aus dem Aus heraus die erste bzw. letzte. Erst ab
zwei Stimmungen; der Tipp auf die Kachel öffnet weiter die Detailseite. Die
Beschattung sendet dieselben Befehle wie
Auf/Ab der Detailseite (`_jal_fahrt()`): Im Stand startet eine Taste die
Fahrt, während der Fahrt halten beide an (`Stop`), und die fahrende Richtung
zeigt ■. Die Visu bindet die Tasten an `click`; ein Wischer, der auf einer
Taste beginnt, scrollt das Raster. Die Tasten gibt es nur, wenn die Kachel
hoch genug ist, entschieden aus dem Faktor statt gemessen
(`tastenEinpassen()`, §7.1 „Tasten nur, wenn die Kachel hoch genug ist“);
sonst bleiben sie weg, und der Tipp auf die Kachel öffnet die Detailseite,
die dieselben Befehle hat. Geprüft in `tests/test_beschattung.py` und
`tests/browser/test_kachel_tasten_browser.py` (Tippen, Wischen, Stop während
der Fahrt, alle vier Raster für Beschattung und Player).

**Taste oben rechts** (`kopfTaste`, seit 18.10.2026): Schalter und
Zeitschalter haben einen Schieber (`schieber`), der den Zustand zeigt, der
Taster einen runden Knopf (`rund`). Keine eigenen Befehle: Ein Tipp darauf ist
ein Tipp auf die Kachel, die schon schaltet (`cmd`); so sendet er genau einmal,
und ein Wischer, der dort beginnt, scrollt (`click`). Die Visu setzt sie in
`kopfTasteHtml()` ans Ende des Kopfs (Klasse `kt` an der Kachel), im Aufbau
„mitte“ in die Ecke, in Listen rechts in die Zeile. Passt der Raum im Kopf
nicht mehr daneben (schmale Kachel, Kreis des Sets kreis), rückt er unter die
Taste (`fitTile()`, `.kt-raum`). Aktiv steht der Schieber in `--glow` mit dem
Knopf in `--on-glow`, im Aufbau „mitte“ in Schrift und Fläche der aktiven
Kachel; `--on-glow` rechnet `_theme_vars()` zu dem `--glow`, der gilt (auch zu
einer gewählten Zustandsfarbe und ohne Set und Grundfarbe). Ein Zustandswechsel
zieht nur `aria-checked` und die Klasse `on` nach (`updateGrid()`); gesperrt
(`jLocked`) und auf der Uhr-Seite gibt es die Taste nicht. Kommen, gehen oder
wechseln Tasten einer Kachel (`controls`, `kopfTaste`), baut `updateGrid()` sie
neu, statt alte Befehle an den Tasten zu lassen. Geprüft in
`tests/test_kachel_bedienung.py` und `tests/browser/test_kachel_tasten_browser.py`
(Tippen, Wischen, Zustand live, jeder Aufbau und jedes Set).

Sonderfälle:

- Schalter mit `active`-State stehen in der Konstante `SWITCHY` (`bausteine/gemeinsam.py`).
- Reine Anzeigen stehen in `STATUS_BIG` (`seiten.py`) und bekommen eine generische
  Großansicht über `_big_view()`.
- Analoge Werte ohne An/Aus stehen in `_ANALOG` (`seiten.py`), damit die
  Kategorie-Ampel neutral bleibt.
- Zentralbausteine laufen über den Präfix `Central` (`kachel_praefix`), erst
  nach der genauen Tabelle.

**Unbekannte Typen:** Steht der Typ in keiner Tabelle und ist er keine
Wertseite (`STATUS_BIG`), zeigt die Kachel `{"label": name, "icon": "info", "on":
false}` mit der Zweitzeile „Typ nicht unterstützt“ (`TYP_UNBEKANNT`, als
`subInfo`) und `unbekannt`, ohne `nav` und ohne `cmd`. Ausblenden geht wie bei jeder
Kachel über `hide`. Welche Typen der eigenen Anlage betroffen sind, zeigt
`/api/types` (`App.types_overview()`, Status aus dem Rendering abgeleitet: eine
Kachel mit `nav`, `cmd`, `controls` oder Zweitzeile gilt als unterstützt, außer
sie trägt `unbekannt`; `PARTIAL_TYPES` markiert die teilweise umgesetzten).
Den alten `ColorPicker` gibt es laut Strukturdoku nur als Kreis der
Lichtsteuerung Generation 1 (`LightController`); deren Seite zeigt nur die
Szenen, er ist deshalb nirgends eingetragen (früher als `Colorpicker`, ein Name,
den die Struktur nie liefert).

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
  `camimage/{uuidAction}/{ts}`. Gegensprechen (SIP) ist ausschließlich in der
  nativen Android-App verfügbar; im Browser bleibt der Typ in `PARTIAL_TYPES`.
  Den SIP-Zugang (`audioInfo`: `host`, `user`, bei
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
  LoxPanel sie für Kamera und SIP-Prüfung wie bei `Intercom`. Native
  Gegensprech-Anrufe werden für `IntercomV2` nicht angeboten, auch wenn es
  gesicherte Details liefert; darum bleibt es in `PARTIAL_TYPES`.

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
Beide laden `/raster.js` (§7.5): dieselbe Rasterrechnung in der Visu und im
Assistenten des Konfigurators.

### 7.1 `panel.html` (Visu, 772 Zeilen)

**Aufteilung** (seit 15.10.2026, Schritt 2 des Zerlegens der großen Dateien):
`panel.html` hält nur noch das Markup (rund 60 Zeilen) und lädt aus
`webfrontend/html/panel/` zwei Stylesheets und zwölf Skriptteile per `<link>`
und `<script src>` an den Stellen, an denen vorher Stylesheet und Skript
standen. Stylesheets: `grund.css` (Kasten, Panes, Kopfzeile und Werteleiste,
Kachelfeld, Kacheln, Kachel-Sets, Leisten) und `seiten.css` (Detailseite,
Spieler, Tabs, Verbindung und Einrichtung, Uhr-Seite, Wetter und Kalender,
Hausübersicht, Gesten), in dieser Reihenfolge, damit die Kaskade bleibt.
Skriptteile in Ladefolge: `kern` (Symbole, Tabs, Zustand, Helfer, Weckton,
Navigation, Intercom), `bedienung` (Befehle und Visu-PIN, Zellen und Tasten,
Formular, Wert mit -/+, Bild groß, Menü, `blockSig()`), `kacheln`
(Verlaufsdiagramme und Mini-Verläufe, Kachelfaktor, Kachel einpassen,
Detailseite mit `renderPanel()` und `updatePanel()`), `seiten` (Tabs, Seiten
blättern, Kategorien, Split-Pane, Kopfzeile, Werteleiste, `applyPane()`),
`kachelfeld` (Kachel-Darstellung, Raster und `render()`, Anlagenschema,
Fenster, Wischen im Kachelfeld), `gesten`, `verbindung` (Kennung, Entwurf,
Gerät, Sprache, Regler am Gerät, Verbindungszustand, `connect()` und die
Nachrichten des Servers), `front` (Uhr, Screensaver-Inhalte, Kalender, Wetter,
Energie, Kamera, Pane 2), `haus` (Hausübersicht), `startseite` (Uhr-Seite an
und aus, Einrichtung und Kopplung, Hinweise, fester Spieler, Ruhe-Timer),
`display` (Nachtmodus, Nacht-Uhr, Kiosk-App, Skalierung, Bildschirm melden,
Display-Einstellungen, Neuladen), `start` (Uhren, Uhr-Seite, `connect()`).
Dazu im Fork (LoxOS, [`VISION.md`](VISION.md)) `bento.css` nach `seiten.css`
und `bento.js` nach `front`: Bento-Seiten. `renderBento()` zeichnet das Raster
(Maße, Größenstufen je Achse und Kollision aus `raster.js`), Kacheln mit
`kachelHtml()`/`kachelBinden()` aus `kachelfeld` (dieselben Funktionen, die
`render()` nutzt), Widgets mit den Pane-Renderern und den Daten der Zelle als
Parameter (`renderCameraPane(elc, q)`, `renderChartPane(elc, daten)`,
`svStatusZeilen(daten)`, `paintEnergy`); `updateBento()` zieht bei gleichem
Aufbau nur geänderte Zellen nach (Webseite und Kamerabild laufen weiter).
Die Optik der Panes hängt an `#frontpane`; `bentoPaneStile()` übernimmt beim
ersten Aufbau jede Regel für Pane-Inhalte mit `.grid.bento .bz-box` statt
kopierter Regeln. Mit nur dieser einen Seite und ohne Detailseite darüber
fällt die Tab-Leiste weg (`.screen.bentovoll`).
Wie beim Konfigurator (§7.2): kein Build, keine ES-Module, alle Funktionen
bleiben global, was ein Teil beim Laden ausführt, ruft nur Funktionen
früherer Teile; der Code ist nur verschoben. Der Server liefert
`/panel/{name}` (`panel_teil`, nur `[a-z0-9-]+.js` oder `.css`, sonst 404)
mit `no-cache`. `tests/test_pin.py` liest den Quelltext der Visu aus
`panel.html` und den dort geladenen Teilen (`_visu_quelltext()`), der
Rauchtest ruft `/panel/grund.css` und `/panel/kern.js` ab und prüft, dass
falsche Namen 404 geben. Die Zeilenangaben weiter unten in diesem Abschnitt
stammen aus der Zeit vor der Aufteilung und sind Orientierung, keine Adresse.

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
- Sichtbare Fläche nur über `vpSize()`: `innerWidth`/`innerHeight`, sonst
  `visualViewport`, sonst das Wurzelelement, nie 0. Eine iOS-Web-App vom
  Home-Bildschirm (Lesezeichen „Als Web-App öffnen“) und manche Kiosk-Browser
  melden beim Start 0 × 0 oder die Safari-Fenstergröße ohne späteres `resize`;
  vorher rechnete `autoRaster()` daraus eine Zeile und der Screensaver lag als
  „Uhr-Kachel“ im Mini-Kasten. `fensterGeaendert()` läuft zusätzlich bei
  `pageshow`, `orientationchange` und `visualViewport.resize`. Die Kopf-Metas
  `apple-mobile-web-app-capable`/`-status-bar-style` starten die Web-App im
  Vollbild, `viewport-fit=cover` plus `safe-area-inset-bottom` an `#tabs`
  halten die Tab-Leiste über dem Home-Balken; Höhen stehen in `--vh`
  (`100dvh`, Fallback `100vh`), weil `100vh` auf iOS die eingefahrenen
  Browser-Leisten mitzählt und die Tab-Leiste unten abschneidet.
  Geprüft in `tests/browser/test_tablet_browser.py`.
- Kamera-Pane mit Werten (`camera:<uuid>|<uuid>,…`): unter Video und Tasten
  ein Block `.camwerte.werte` mit denselben Zeilen und `.werte`-Regeln wie die
  Werte-Pane; `applyPane()` meldet die Werte wie bei `status:` per
  `setsvstatus`, der `svstatus`-Push zeichnet nur den Block neu
  (`renderCameraWerte()`), das Video bleibt stehen. `camPaneUuid()` und
  `camPaneWerte()` trennen den Wert, der Konfigurator schreibt ihn mit
  `camPane()`/`camUuid()`/`camWerte()` („Werte unter dem Bild“ bei Kamera).
- Verlinkte Objekte: `_link_blocks()` hängt an jede Block-Detailseite die
  Bausteine aus dem Structure-File-Feld `links` (in Loxone Config am
  Baustein verlinkt, etwa Abholtermine am Müll-Status) als Überschrift
  „Verlinkte Objekte“ und umbrechende `row` (`id: links:<uuid>`) an: je Ziel
  eine Zelle mit Name · Zustand aus `_control_item()`, `nav` auf die
  Detailseite, bei direkt schaltenden Zielen deren `cmd`. Unbekannte Ziele,
  Dubletten und der Baustein selbst fallen weg. Tests in
  `tests/test_verlinkte_objekte.py`.
- Kachel-Sets (`ui.tileSet`, §5.4): Die `theme`-Nachricht setzt
  `data-kachelset`, `data-kachelset-aufbau` und `data-kachelset-leiste` am
  `<html>`. Die Regeln hängen an der Art, nie am Namen eines Sets. Maße mit
  `-schmal` lösen die `--k-*` am Kasten auf (`schmalEinrichten()` setzt
  `.schmal` unter `SCHMAL_UNTER` Breite, `.niedrig` bei genug Breite, aber
  weniger Höhe; dort gelten nur die Leistenmaße mit `-schmal`). Für jedes Set (`html[data-kachelset-aufbau]`)
  flache Kacheln ohne Rahmen, Abstand und Innenrand des Rasters aus dem Set,
  Symbole in der Schriftfarbe, aktive Kachel auf `--kachel-an`, Tasten auf
  `--taste` (auch die −/+ an einem Schieber, `.sbtn`), und der Zustand steht vorn, auch bei Kacheln, die direkt
  schalten (`zustandVorn()`). `mitte`: `kachelTexte()` stellt den Zustand vorn
  (neben einem Messwert den, den der Server dazu nennt) und darunter „Name ·
  Raum“, die aktive Kachel trägt `--kachel-an-ink`, ihre Zweitzeile
  `--kachel-an-muted`. Dasselbe gilt für die aktive Zeile einer Liste
  (`layout: "list"`, etwa die Stimmungen der Lichtsteuerung): Ihre Fläche ist
  ebenfalls `--kachel-an`, ohne die Schrift des Sets stünde dort bei „aktiv
  dunkel“ `--ink` auf fast Schwarz. Die große Taste (Play) kippt ebenso
  (`--kachel-an` mit `--kachel-an-ink`), der Schieber füllt sich in `--ink`.
  `--glow` gehört nicht zur Farbsprache von `mitte`: Das Set rechnet es nur
  für seine hellen Flächen nach, beim Farbton Lavendel ergibt das `#553602`,
  also Braun. `kreis`: `render()` legt `.kreis` um das
  Symbol, aktiv füllt er sich mit `--glow`; Zustand und Name stehen unten, eine breite
  Kachel ohne Messwert stellt Kreis, Text und Raum in eine Zeile. Zustandstext
  in Akzentfarbe läuft über `--an-text` (Rückfall `--glow`). Leisten `pille`
  und `oben` haben ihre Höhe und Symbolgröße aus dem Set, Zurück ist ein
  Symbol wie die Tabs. Leiste `oben`: die Tabs stehen in Zeile 1, der Kasten
  ist der Rahmen (`--rahmen`, Innenabstand aus dem Set), das Raster darin das
  abgerundete Feld (`--screen`), die Uhr-Seite ein Feld im selben Rahmen;
  Kopfzeile, Werteleiste und Widget stehen auf dem Rahmen, in den Farben der
  Tabs. Pane 2 steht wie das Feld auf dem Rahmen, ihre Seiten sind deshalb
  flach in seiner Fläche (`--screen`, Radius des Feldes) und oben und unten
  bündig mit ihm. Der Verlauf von `--tile` ins Durchsichtige, den sie sonst
  haben, lief auf dem dunklen Rahmen ins Dunkle, und Schrift und Zweitzeile
  des Sets verschwanden darin. Jede Zeilen-Variante des Kastens (Kopfzeile, Werteleiste, Split
  quer und hochkant, Widget-Seite) rückt eine Zeile nach unten. Leiste
  `links`: Breite `--rail-breite` (schmal `--rail-breite-schmal`, nur
  Symbole), Zurück unten, der aktive Eintrag mit Symbol in der Akzentfarbe;
  der Kasten macht ihr mit `padding-left` Platz, die Leiste liegt absolut
  darin. `autoRaster()` misst Leiste, Seitenleiste und Rahmen (Innenabstand
  des Kastens) und zieht sie ab. Wechselt das Set bei einer neuen Verbindung,
  entfernt die `theme`-Nachricht die Variablen der vorigen. Tests in
  `tests/browser/test_kachel_set_browser.py` (Bilder aller Sets am iPad und am
  4″-Panel).
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
  behält die gemessenen Klassen (`spark*`, `ohnetasten`, `eng1`–`eng3`,
  `kst1`–`kst3`) und setzt `bigv` an Ort und Stelle. Kommt oder geht ein
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
- Tasten nur, wenn die Kachel hoch genug ist (Oktober 2026): Die Tasten
  einer Kachel (Beschattung ▲▼, Player ◀ ⏯ ▶) stehen unter dem Text oder gar
  nicht, entschieden aus dem Faktor statt gemessen (`tastenEinpassen()`):
  Kopf, zwei Textzeilen, Abstände und Innenrand brauchen `tastenTextHoehe()`
  mal Faktor: aus den eingestellten Größen (Symbol, Haupt-, Zweit- und
  Raumtext, `GROESSEN_STANDARD` oder das Profil als `--ico-size` usw.) plus
  den festen Anteilen aus dem CSS (`TASTEN.rand`; mit den Standardgrößen
  130 px im neuen, 122 px im klassischen Aufbau bei Faktor 1), die
  Tastenleiste `TASTEN.leiste` mal max(1, Faktor der Seite)
  (44 bzw. 34 px; Touch-Ziele schrumpfen nie, sie tragen den Faktor der
  Seite als `--ksg`). Die Kachel nimmt den Faktor, bei dem beides in ihre
  Höhe passt, höchstens den der Seite, als eigenes `--ks` an der Kachel (4″
  2×2: rund 1,07 statt 1,31). Liegt er unter `KS_MIN`, bleiben die Tasten weg
  (`hidden`, Klasse `ohnetasten`), und der Tipp auf die Kachel öffnet die
  Detailseite mit denselben Befehlen (3 Zeilen am 4″-Panel: 128 px hoch; im
  automatischen Raster etwa 146-px-Kacheln eines 893×533-Tablets). Das löst
  die flache Kachel ohne die Sonderfälle im Kopf, die es vorher gab (Tasten
  neben dem Symbol, `ctrltight`, oder an seiner Stelle, `ctrlnarrow`, je
  Text gemessen von `placeCtrls()`); die Entscheidung hängt nicht mehr am
  Text, eine fahrende Jalousie mit zwei Zustandszeilen verliert ihre Tasten
  nicht. `updateGrid()` setzt den Style der Kachel gegen den zuletzt
  gesetzten Text (`_stStr`) und behält so den eigenen Faktor;
  `faktorNachziehen()` passt neu ein, wenn sich die Kachelhöhe ändert, auch
  ohne Faktorwechsel (festes, breitenbegrenztes Raster). Listen (Zonen
  einer Zentrale) haben ihre Tasten immer. Geprüft in
  `tests/browser/test_kachel_tasten_browser.py` (vier Raster, Beschattung
  und Player, Tipp öffnet die Detailseite) und
  `tests/browser/test_kachel_aufbau_browser.py` (4″ 2×2 und 3×3, beide
  Aufbauten).
- Spieler-Spalte der breiten Kachel (11.10.2026): Eine 2×1-Kachel mit Tasten
  (`spielerKachel()`: neuer Aufbau, keine Liste, `w2`, `it.controls`; heute
  die Audiozonen) teilt sich: links Kopf und Text, rechts die Spalte
  `.tplay` mit Sender-Logo bzw. Cover (`it.cover`) oben und den Tasten darunter.
  Die Tasten brauchen dort nur die Höhe einer Tastenleiste
  (`spielerEinpassen()`), sie stehen also auch auf der flachen 2×1-Kachel am
  4″-Panel, wo `tastenEinpassen()` sie unter dem Text weglassen müsste. Das
  Cover braucht über den Tasten mindestens `SPIELER_COVER_MIN` (36 px) mal
  Faktor, sonst fällt es weg (`ohnecover`), und ohne Cover stehen die Tasten
  mittig. Das Bild kommt aus `_audio_cover()`, das auch die Detailseite nimmt:
  Gen1 der State `cover`; Gen2 das Album-Cover zum laufenden Titel
  (`_song_cover()`), sonst das Sender-Logo vom Audioserver oder von Sonn.
  Ausgeliefert wird es über `/cover`. `updateGrid()` baut die Kachel neu, wenn
  Spalte oder Cover kommen oder gehen, und zieht sonst nur das Bild nach. Der
  klassische Aufbau bleibt, wie er ist. Der Aufbau „kreis“ legt seine Zeile
  der breiten Kachel (Kreis, Text, Raum) nicht über die Spieler-Spalte. Der
  Seiten-Editor zeigt dieselbe Aufteilung (`seSpieler()`); `/api/meta` nennt
  dafür je Baustein `tasten` (Zahl der Kacheltasten) und `cover`, beide aus
  `_control_item()`. Tests: `tests/browser/test_spieler_kachel_browser.py`
  (jeder Aufbau am 4″-Panel und iPad, flache Kachel, ohne Cover, Taste
  schaltet, klassisch, Editor).
- Waagerechte Seiten (Punkt 8, 08.10.2026): Auf einem Tablet wischt man die
  Kachelseiten zur Seite wie in der Loxone-App, mit Punkten darunter; das
  4″-Panel blättert weiter senkrecht. Die Regel ist `seitenQuer()`: Split
  an, kein quadratischer Schirm (Breite und Höhe weniger als ein Zehntel
  auseinander, `quadratisch()`), keine Liste (`layout: "list"`), keine
  Widget- oder Front-Seite. Dann ist `#grid` eine Flex-Zeile (`.hpages`)
  aus `.page`-Elementen in Schirmbreite, jede ein eigenes Raster aus
  `--cols` × `--rows` mit dichtem Fluss, eingerastet je Seite
  (`scroll-snap-type: x mandatory`); `render()` verteilt die Kacheln nach
  der Zeile aus `rasterLage()` (Seite = Zeile ÷ Zeilen) auf die Seiten, die
  Rastpunkte `.snap` entfallen. Die Punkte (`.punkte`, nur ab zwei Seiten,
  Klasse `punkte` am Raster) sind ein Element in Seitenbreite, das als
  `position: sticky; left: 0` mit negativem rechten Rand keinen Platz
  einnimmt und so über jeder Seite an derselben Stelle steht; sie folgen dem
  Scrollen (`punkteNachziehen()`), ein Tipp führt zur Seite (`seiteZu()`),
  das Mausrad senkrecht gedreht blättert eine Seite (waagerechte
  Rad-Bewegungen scrollt der Browser selbst). `autoRaster()` zieht die Höhe
  der Punkte (`--punkte-h`) von der freien Höhe ab, sobald die Kacheln der
  Seite mehr als eine Seite füllen (zweiter Rechenlauf; weniger Höhe gibt
  nie weniger Seiten). Hochkant mit Widget darunter setzt `render()` die
  Widget-Höhe deshalb in Pixeln (`pPx`: Zeilen × Zeilenhöhe samt Abstand)
  statt als Anteil `fr`: ein Anteil nähme die Punkte nur von der
  Kachelhälfte, die Kacheln würden flacher als ohne Widget. `updateGrid()`
  patcht die Kacheln in ihren Seiten,
  wenn jede Seite dieselben Kacheln in derselben Reihenfolge trägt (im DOM
  steht eine schmale Kachel, die in eine Lücke rückte, vor einer breiten
  auf der nächsten Seite), sonst baut `render()` neu und stellt die Seite
  wieder her (`scrollLeft`). Der Wisch nach rechts blättert ab Seite 2
  zurück (der Browser scrollt eingerastet) und heißt nur auf der ersten
  Seite „zurück“, wie am 4″-Panel; Sprungmarken springen zur Seite der
  ersten Kachel ihrer Gruppe (`springeZu()`). Beim Drehen zwischen
  quadratisch und rechteckig wechselt die Richtung mit dem nächsten
  `render()` (`updateGrid()` lehnt den Wechsel ab); `rasterKey()` trägt die
  Richtung mit, damit auch ein Fenster, das quer über die Quadrat-Schwelle
  wächst (520×480 → 560×480, gleiche Lage, gleiches Raster), sofort umbaut
  (Codex an #130). Geprüft in
  `tests/browser/test_seiten_wischen_browser.py` (Tablet quer und hochkant,
  festes Raster, 4″ quadratisch, Split aus, Drehen, Live-Wert, Wisch,
  Sprungmarke).
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
- Kacheln 2 × 2 (Seiten-Editor, Punkt 10, 09.10.2026): Auf einer freien
  Seite kann das Layout (`pickTabs[i].layout`, §7.2) eine Kachel hoch machen
  (`h: 2`, immer auch breit). Die Visu macht daraus `w2 h2` (`grid-row: span
  2`), aber nur, wo das Raster zwei Spalten und zwei Zeilen hat
  (`kachelGroesse()`, `LoxRaster.groesse()`). Eine hohe Kachel belegt zwei
  Zeilen derselben Seite: `rasterLage()` setzt sie in der letzten Zeile einer
  Seite auf die nächste, die Lücke füllt die nächste kleine. Den dichten Fluss
  des Browsers, der keine Seitengrenze kennt, ersetzt die Visu dann durch feste
  Stellen (`kachelPlatz()`: `grid-row`/`grid-column` je Kachel, waagerecht in
  ihrer Seite), sobald die Seite eine hohe trägt (`lage.hoch`); `updateGrid()`
  setzt sie beim Abgleich mit. Geprüft in
  `tests/browser/test_kachel_hoch_browser.py`.
- Automatisches Raster (Kachel-Layout „Automatisch“, `ui.grid = "auto"`, für
  Tablets): Die Visu rechnet Spalten und Zeilen selbst (`autoRaster()`, die
  Rechnung steht seit Punkt 9 in `raster.js`, §7.5), statt
  `cols`/`rows` aus dem Profil zu nehmen. Grundlage ist die Zielkachel in
  CSS-Pixeln, die der Server schickt (`gridAuto`): eine Zahl aus `ui.tileSize`
  (`KACHEL_ZIEL_MIN` bis `KACHEL_ZIEL_MAX`, fehlt = `KACHEL_ZIEL_STANDARD`;
  die alten Stufen klein/mittel/groß stehen in `KACHEL_ZIEL` und werden beim
  Speichern zur Zahl), je Gerät übersteuerbar unter Displays
  (`devices[name].tileTarget`, Gerät vor Profil wie bei der Skalierung,
  `effective_grid_auto()`; bis 09.10.2026 lud und speicherte der
  Konfigurator das Feld nicht, `loadPanelIds()` und `devicesPayload()`
  tragen es jetzt; beim Speichern bekommt jede offene Visu
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
  der Zielkachel und dem Blättern. Umgekehrt schrumpft sie (Punkt 16,
  09.10.2026): bliebe bei mehreren Seiten die letzte mehr als ein Drittel
  leer, gibt sie je eine Spalte dazu und nimmt das erste Raster, das eine
  Seite spart, bis die letzte Seite voll genug ist; nie kleiner als
  Zielkachel durch `gridGrow` (bei 170 px also 121 px). 30 Kacheln auf dem
  10″ quer stehen so in 8 × 5 zu 149 px statt 28 + 2 in 7 × 4; Tab A9 quer
  mit 23 Kacheln bleibt bei 15 + 8, weil sechs Spalten keine Seite sparen und
  sieben unter 121 px lägen. Neben einem Widget mit Anteil wachsen und
  schrumpfen sie nicht: es belegt ganze Kachelspalten, und mit weniger Spalten ließe sich
  sein Anteil von rund 40 % nicht halten (2 von 5 Spalten sind 40 %, 2 von 4
  schon 50 %, die Wetter-Pane wechselte von „schmal“ auf „breit“). Mit fester
  Breite (`ui.paneCols`, unten) wachsen und schrumpfen sie, das Widget bleibt
  so viele Kachelspalten breit und wächst oder schrumpft mit.
  Lesbarkeits-Regel dazu (Punkt 16, `test_seiten_voll_bis_auf_die_letzte`
  in `tests/browser/test_kachel_faktor_browser.py`): die 23 Favoriten der
  Messreihe, gezählt in Zellen (drei breite Kacheln belegen je zwei, zusammen
  26). Passt alles auf eine Seite, bleibt höchstens ein Drittel leer (10″
  quer 7 × 4: 26 von 28); sonst ist jede Seite bis auf die letzte voll, ohne
  Lücke durch eine breite Kachel, und es sind so wenige Seiten, wie das
  Raster hergibt. Im automatischen Raster hält auch die letzte Seite das
  Drittel (Tab A9 quer und hochkant 15 + 11; iPad quer schrumpft auf 7 × 5,
  26 von 35, statt 24 + 2 in 6 × 4); das feste Raster des 4″ (2 × 2) trägt
  auf der letzten Seite den Rest. Das Schrumpfen selbst prüft
  `test_schrumpfen_spart_eine_seite` in `tests/browser/test_auto_raster_browser.py`
  mit und ohne (`gridGrow = 1`).
  Abstand und Innenrand liest sie aus dem CSS (`--gap`, `--pad` am Raster),
  die Höhe der Tab-Leiste aus der Seite. Ein größerer Schirm zeigt so mehr
  Kacheln statt größerer: am Tab A9 (893×533 CSS-px) quer 5 × 3 Kacheln zu
  etwa 167 × 146 px, hochkant 3 × 5, am 10″-Tablet (1280×800) quer 7 × 4. Ein
  Widget belegt ganze Kachelspalten (quer) bzw. -zeilen (hochkant): ohne
  Einstellung rund `PANE_ANTEIL` (40 %) der Spalten, gerundet, oder die feste
  Zahl aus `ui.paneCols` (1 bis `PANE_SPALTEN_MAX`, 3; Punkt 7 vom
  08.10.2026). Beides schickt der Server mit der theme-Nachricht
  (`paneShare`, `paneCols`), die Visu hat keine eigene Zahl dafür; der
  Konfigurator stellt die feste Breite als Schieberegler „Widget-Breite“ ein
  (Grenze und Anteil aus `/api/meta` `paneCols`), nur im Layout
  „Automatisch“ und mit Split, 0 = Automatik wird nicht gespeichert
  (`PANEL_STANDARD`). Das feste Raster kennt die Einstellung nicht, dort
  bleibt das Widget bei der Hälfte. Die Aufteilung setzt `render()` als
  `--auto-k`/`--auto-p` (fr), die Kacheln bleiben damit mit und ohne Widget
  gleich groß: am Tab A9 quer 3 × 3 neben dem Widget statt 5 × 3. Der Kasten
  ist der ganze Schirm (Klasse `.fill` mit `.auto`), „Bildschirm füllen“,
  Skalierung und die Verdopplung „Screen füllen“ wirken nicht
  (`applyScale()` bleibt bei 1). Geblättert wird seitenweise (je Seite
  Spalten × Zeilen Kacheln), auf dem Tablet waagerecht mit Punkten (unten,
  „Waagerechte Seiten“). Beim Drehen rechnet `rasterKey()` neu, der
  `resize`-Handler baut dann neu auf. Über dem Raster steht nichts, solange
  beide Verbindungen stehen (die Verbindungsleiste, §3.4, ersetzt den
  früheren Online-Punkt, der bei 5 × 3 auf einer Kachel lag).
  Das Panel meldet das Raster mit seiner Bildschirmgröße (`rc`, `rr`), der
  Konfigurator zeigt es unter Displays bei den Geräten. Das feste Raster
  (4″-Panel, jedes Profil ohne `grid`) bleibt unverändert. Der Assistent
  „Neues Panel“ schlägt „Automatisch“ für 2 Panes (Tablet) vor. Geprüft in
  `tests/test_auto_raster.py` (Prüfer, Standard, Gerät vor Profil, Vorschlag)
  und `tests/browser/test_auto_raster_browser.py` (Raster je Gerät, Wachsen
  mit wenigen Kacheln, Zielkachel je Gerät wirkt sofort, Widget-Breite in
  Kachelspalten, Konfigurator), `tests/test_widget_breite.py`.
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
  `weather`, `player:<zone>`, `energy:<uuid>`, `camera:<uuid>[|<uuid>,…]`, `chart:<uuid>,…`, `status:<uuid>,…`. Geprüft an
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
  In einem hohen Fenster ist es umgekehrt: Dort begrenzt die Spaltenbreite
  die quadratische Energiegrafik. Bei voller Höhe blieben über und unter dem
  Kreis leere Streifen, und der Kasten ragte weit über Uhr und Wetter hinaus.
  Gemessen bei 1457×900 war der Kasten 846 px hoch, die Grafik darin 418 px
  breit in 784 px Höhe. Die Kamera ist fast immer durch die Breite begrenzt,
  auch am 960×480-Panel (dort blieben 24 px über und unter Bild und Tasten,
  bei 1457×900 221 px). `svFit()` kürzt den Kasten um diese Streifen
  (`--sv-kasten`), und er steht mittig neben Uhr und Wetter. Den freien Platz
  rechnet `svKastenLeer()`: beim Energiefluss aus der `viewBox`, bei der
  Kamera aus dem Seitenverhältnis des Bildes (`.video`, `aspect-ratio`) und
  der Höhe von Tasten, Gegensprechen und Werten. Ein Bild, das sich beim
  Gegensprechen in die Höhe streckt, zählt mit seiner Höhe aus dem
  Seitenverhältnis.
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
  keine Sprungmarken. Verbunden steht über dem Widget nichts; die
  Verbindungsleiste (§3.4) erscheint nur ohne Verbindung. Geprüft in
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
  `kopfEinpassen()` aus, bei jeder Größenänderung neu; fiele ein Wert weg,
  geht zuerst der Wettertext (Lage, Hoch/Tief), Symbol und Temperatur bleiben
  (seit 10.10.2026). Als Wert zeigt ein Chip (`kopfWertHtml()`, auch in der
  Werteleiste) den Messwert der Kachel (`big`, bei der Raumregelung die
  Ist-Temperatur), sonst die Zweitzeile. Weil sie keine Pane
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
- Hausübersicht (Tab `haus`, 11.10.2026, Entwurf im Design-Canvas „LoxPanel
  Kachel-Set Loxone“, Boards „iPad quer – Hausübersicht B“ und „iPad hochkant
  – Hausübersicht“): eine eigene Seite ohne Kachelraster für Tablets und große
  Displays. Der Server rechnet sie in `_view_haus()` (`bin/haus.py`, `layout:"haus"`), die
  Visu zeichnet sie in `renderHaus()`.
  - **Wo sie steht:** als Tab `haus` der klassischen Leiste oder als freie
    Seite der eigenen Auswahl mit dem Inhalt `haus` (`pickTabs[].widget`,
    `_clean_widget_tab()`; `_haus_seite()` erkennt beides, auch für die Route
    mit Zone und Unterseite). Im Seiten-Editor steht die Hausübersicht beim
    „Seiteninhalt“, und die Taste „＋ Haus“ neben dem „＋“ legt sie mit einem
    Tipp an: in der eigenen Auswahl als Seite „Haus“, in der klassischen
    Leiste als Tab `haus` (eine freie Seite zeigte die Visu dort nicht).
    Eine Hausseite hat kein Widget daneben, keine Kopfzeile und keine
    Werteleiste (`paneRawNow()` in der Visu, `sePaneZeichnen()` im
    Konfigurator); ohne eigenes Symbol zeigt die Leiste das Haus
    (`_tab_meta()` meldet `haus`).
  - **Aufbau je Ansicht** (14.10.2026, `ui.hausAufbau`, Auswahl und
    Beschriftung in `HAUS_AUFBAUTEN`, ohne Einstellung `HAUS_AUFBAU_STANDARD`
    = „Status zuerst“; Konfigurator: Aussehen → „Hausübersicht“, Optionen aus
    `/api/meta` `hausAufbauten`). Der Server rechnet je Aufbau dazu, was die
    Visu braucht (`aufbau` in der Ansicht), die Visu wählt in `hausLage()`:
    - *Status zuerst* (`status`, Entwurf „Hausübersicht B“): wie unten
      beschrieben, mit „Gerade aktiv“.
    - *Räume direkt* (`raeume`, Entwurf „Hausübersicht C“): statt „Gerade
      aktiv“ die Titelzeile „Räume · n Geräte an“; die Raumkarte ist keine
      Taste, oben rechts öffnet der Pfeil den Raum, unten schalten bis zu
      `HAUS_TASTEN` runde Tasten direkt (`_haus_tasten()`): Bausteine mit Aus-
      (`HAUS_AUS`) und Ein-Befehl (`_haus_ein()`, `HAUS_EIN` laut
      Strukturdoku; Treppenlicht `pulse`, Lichtsteuerung die erste Stimmung
      ohne „Aus“). Was `HAUS_RUECKFRAGE` nennt (Sauna), fragt vor dem
      Einschalten nach: der erste Tipp zeigt die Frage an der Taste
      (`hsFrage`), erst ein zweiter innerhalb von `ZELLE_BESTAETIGEN_MS`
      schaltet. Die Karte braucht mehr Höhe (`HS_RAUM_HOCH_TASTEN`).
    - *Spalte links* (`spalte`, Entwurf „Großes Display – Hausübersicht“):
      links (`HS_LINKS`) große Uhr mit Wetter, Energie mit Produktion und
      Verbrauch, „Auf einen Blick“ (oben die Hinweise und die Termine, siehe
      „Hinweise“; darunter unter „Status“ `_haus_blick()`: was einen Zustand
      meldet, sich aber nicht abschalten lässt, etwa Postkasten, Lüftung,
      Zentral-Bausteine; ohne Energie-Baustein, ohne Raumregelung/Sauna und
      ohne, was oben schon als Hinweis steht, ein Tipp öffnet den Baustein)
      und die Schnellaktionen untereinander;
      in der Mitte die Raumkarten unter „Räume · n Geräte an“, rechts der
      Spieler. Nur quer und nur, wo neben Spalte und Spieler zwei
      Raumspalten passen (nicht hochkant, nicht auf dem iPad quer neben der
      Leiste links des Sets Kreide), sonst zeigt das Gerät „Status zuerst“.
  - **Kopf:** Uhr, Wetter mit der Vorschau für morgen (`forecast[1]`) und der
    nächste Termin kommen aus der Front. Die Energie stammt vom ersten
    Energieflussmonitor bzw. Energiemanager (`HAUS_ENERGIE_TYPEN`) der Seite,
    sonst der Anlage (`_haus_energie()`): Verbrauch groß, Erzeugung klein, in
    Watt aus `energy_blocks()["totals"]`, ein Tipp öffnet ihn. Je Ansicht
    wählbar (18.10.2026, `ui.hausEnergie`, Konfigurator: Aussehen →
    „Hausübersicht“ → „Energie im Kopf“, Auswahl aus `/api/meta`
    `hausEnergien`): leer = automatisch wie eben, `HAUS_ENERGIE_AUS` („Keine“)
    = ohne Energie im Kopf und in der Spalte, sonst die UUID eines dieser
    Bausteine. Gibt es den gewählten nicht mehr, ist er keiner dieser Typen
    oder blendet die Ansicht ihn aus (`hide`), gilt wieder automatisch.
  - **„Gerade aktiv“:** alle Bausteine der Seite, die an sind **und** sich
    abschalten lassen. Was als abschaltbar gilt, steht einmal in `HAUS_AUS`
    (Befehl, Beschriftung der Taste und Art: Switch, TimedSwitch `off`
    „schalter“, Dimmer `off` und LightControllerV2 `changeTo/778` „licht“,
    Audio-Zonen `pause` „audio“, Sauna `off` „sauna“). Die Lüftung hat keinen
    Aus-Befehl und bleibt Anzeige. Welche Arten zählen, wählt die Ansicht
    (18.10.2026, Konfigurator: Aussehen → „Hausübersicht“ → „Zählt unter
    ‚Gerade aktiv‘“, Arten und Beschriftung in `HAUS_AKTIV_ARTEN`):
    gespeichert wird, was *nicht* zählt (`ui.hausAktivOhne`), ohne Eintrag
    zählt alles; im wirksamen Profil steht, was zählt (`hausAktiv`). Was nicht
    zählt, fehlt auch in „n an“ der Raumkarten und in der Zahl der
    Titelzeile, bleibt aber Symbol der Raumkarte, Taste in „Räume direkt“ und
    Spieler. Zählt keine Art, gibt es die Zeile nicht (`aktivZeile:false`),
    auch nicht die Zahl in der Titelzeile von „Räume direkt“ und „Spalte
    links“. Ist nichts an, steht dort „Alles ruhig“ und darunter, was die
    ersten beiden gezählten Arten sagen (`ruhig`, `_haus_ruhig()`, etwa „Kein
    Licht an, keine Musik“), auch ohne Schnellaktionen (bis 18.10.2026 fiel
    die Zeile dann ganz weg, ein Rest aus der Zeit, als die Zentral-Tasten
    in ihr standen; Codex-Befund an #212). Die Zeile scrollt nie
    waagerecht, dort blättert der Wisch die Seiten: Sie zeigt so viele Karten
    wie Spalten passen (`hausLage()`, Mindestbreite `HS_AKTIV_MIN`), bei mehr
    wird die letzte Stelle „+n weitere“. Ein Tipp darauf öffnet die
    Unterseite (`liste:"aktiv"` in der Route) mit allen untereinander, ist
    dort nichts mehr an, geht es zurück.
  - **Schnellaktionen** (14.10.2026, Entwurf „Großes Display – Hausübersicht“,
    dort unter „Auf einen Blick“): „Alle Lichter aus“ und „Alle Zonen aus“
    als eigene Zeile unter „Gerade aktiv“, auf der Unterseite unter ihrem
    Kopf. Sie schalten über den Zentral-Baustein der Anlage (`HAUS_SCHNELL`,
    `_haus_schnell()`): je Art der erste, den die Ansicht nicht ausblendet
    (`hide`); der Raumfilter gilt nicht, wie beim Tab „Zentral“. Ohne den
    Baustein gibt es die Taste nicht. Befehle laut Strukturdoku (Central
    Objects): `CentralLightController` `reset` (der Eingang „Off“ des
    Bausteins: „Outputs are reset / switched off“), `CentralAudioZone`
    `pause`. Die Visu schickt sie als gewöhnlichen `cmd` (`sendCmd()`), ein
    gesicherter Baustein fragt also nach der PIN. Rechts steht, wie viele
    Mitglieder an sind (`an`, „1 an“, leer bei 0): dieselbe Zahl wie auf
    der Kachel des Zentral-Bausteins (`_zentral_an()`), live, weil jede
    Zustandsänderung die Seite neu rendert (`broadcaster`), die Visu fragt
    nicht nach. Maße wie im Entwurf: 72 px hoch bei `--hk` 1, Fläche und
    Radius der Karten des Sets (`--tile`, `--kachel-radius`, im Set Loxone
    20 px), die Anzahl in `--glow` bzw. `--an-text`, wo ein Set ihn für
    Text nachschärft (wie „n an“ auf den Raumkarten). Die Zeile kostet die
    Raumkarten Höhe; passen sie dann nicht mehr, scrollen sie wie sonst
    auch (etwa bei 1460×1120, nicht auf iPad und großem Display).
  - **Hinweise** (14.10.2026, Entwurf „Auf einen Blick – mit Hinweisen“):
    was Aufmerksamkeit braucht, in jedem Aufbau. Der Server sammelt sie aus
    den Kacheln der Seite (`_haus_hinweise()`): Eine Kachel mit dem Ton
    `crit` (Klingel, Alarm, Rauchmelder, Wecker, Störung der Sauna) ist
    *dringend*, mit `warn` eine *Warnung* (`HINWEIS_TON`), der Text ist ihr
    Zustand. Wo der nicht sagt, was los ist, nennt die Kachel ihren Hinweis
    selbst (`hinweis`: Stufe, Text, Symbol, Zusatz): die Sauna dieselben
    Texte wie ihre Detailseite (`SAUNA_WASSER`, `SAUNA_STOERUNG`), die
    Raumregelung bei offenem Fenster „Fenster offen“ (dringend, solange der
    Raum dabei heizt oder kühlt, sonst eine Warnung), der Postkasten mit
    Post die Stufe *an*. Die Bedingung steht so nur an der Kachel. Folge
    nach Stufe (`HINWEIS_STUFEN`), darin nach Räumen; ein Tipp öffnet den
    Baustein; was die Ansicht ausblendet, meldet nichts; live wie alles auf
    der Seite.
    In „Status zuerst“ und „Räume direkt“ stehen sie als Leiste gleich unter
    dem Kopf: so viele, wie in der Mindestbreite `HS_HINWEIS_MIN`
    nebeneinander passen, der Rest hinter „+n“ (Unterseite
    `liste:"hinweise"`; ist dort keiner mehr, geht es zurück). Ohne Hinweis
    gibt es keine Leiste. In „Spalte links“ stehen sie oben in „Auf einen
    Blick“ mit ihrer Zahl, ohne Hinweis steht dort „Alles in Ordnung“.
    Darunter folgen die Termine von heute und morgen, die noch kommen
    (`hsTermine()` aus der Front, höchstens so viele, wie die Uhr-Seite
    zeigt, `svEvents`); die Spalte hat keinen Kopf mit dem nächsten Termin.
    `tickClock()` zeichnet sie jede Minute neu, ein vergangener Termin fällt
    von selbst weg. Passt die Liste nicht, scrollt sie senkrecht.
    Farben: *dringend* ist die gefüllte Störungsfläche (`--crit-fill`,
    `--crit-ink`, `--crit-muted`), *Warnung* und *an* zeigen es nur am
    Symbol (`--warn`, `--glow`). Das Symbol steht in einem Kreis auf der
    jeweils anderen Grundfläche (Karte `--tile` auf dem Grund, in der Spalte
    umgekehrt): Nur auf `--tile` und `--screen` sind Schrift und
    Rollenfarben gegen AA gerechnet (`theme_colors`), auf `--taste` nur
    Symbole in `--ink`.
  - **Raumkarten:** je Raum mit sichtbaren Bausteinen eine Karte (Raumfilter
    der Ansicht wie beim Tab „Räume“). Der Hauptwert kommt aus
    `_haus_hauptwert()`: die Ist-Temperatur der Raumregelung bzw. Sauna
    (`big`), sonst der Zustand des ersten Bausteins, der an ist, sonst der
    erste Zustand. Darunter bis zu `HAUS_SYMBOLE` Symbole, abschaltbare zuerst,
    und „n an“; in einer schmalen Karte werden die Symbole gemeinsam kleiner
    (`.hs-r .s`), statt mit „n an“ herauszulaufen. Ein Tipp öffnet die
    Raumseite (`group`/`room`). Die
    Spaltenzahl wählt `hausLage()`: die, deren Karten dem Seitenverhältnis
    `HS_RAUM_SEITE` am nächsten kommen, ohne unter `HS_RAUM_HOCH` zu
    schrumpfen; passt das nicht, scrollen die Karten senkrecht. Nach dem
    Zeichnen misst `renderHaus()` nach: Fasst eine Karte ihren Inhalt nicht
    (zweizeiliger Name, lange Zeile), werden die Reihen so hoch wie die
    höchste Karte; ihre Zeilen schrumpfen nie (`.hs-r>*`), sonst lägen
    Hauptwert und Zeile darunter übereinander.
  - **Spieler:** die gewählte Zone (Route `zone`), sonst die erste, die
    spielt. Inhalt aus `player_blocks()`, also dieselben Befehle wie auf der
    Detailseite. Quer ab 860 px Breite steht er als Spalte rechts mit
    Zonenliste, sonst als Leiste unten, die eine Taste durch die Zonen
    schaltet. Ein Zonenwechsel ersetzt die Route, statt eine Seite auf den
    Stapel zu legen.
    Wie auf der Detailseite der Zone öffnen die drei Punkte (⋮) die
    Musikauswahl mit Sendern und Favoriten: quer rechts oben in der Spalte,
    hochkant am Ende der ersten Zeile der Leiste. Die Route kommt aus dem
    `more`-Block der Detailseite (`player_blocks()`, im Spieler `mehr`),
    zurück führt zur Hausseite (14.10.2026). Seit 17.10.2026 hat der Player
    im Split-Layout dasselbe ⋮ rechts oben.
    **Sender** (14.10.2026, Entwurf „Variante große Cover“): die Favoriten
    der Zone als große Cover-Kacheln (`_haus_sender()`, im Spieler
    `sender`, höchstens `HAUS_SENDER`). Sie kommen aus derselben Quelle wie
    die Musikauswahl (`_zonen_favoriten()`: Audioserver-Kanal 7091, sonst
    der `sourceList`-State des Miniservers), mit demselben Befehl
    (`roomfav/play/…`) und Cover über den Proxy `/cover`. Sind noch keine
    da, fordert der Server sie an wie die Musikauswahl beim Öffnen
    (`prime_favs()`), aber höchstens alle `HAUS_SENDER_NEU_S` je Zone
    (`_haus_sender_anfordern()`), denn die Seite wird bei jeder
    Zustandsänderung neu gerechnet. Welcher Favorit läuft, meldet der
    Miniserver nicht: markiert (`laeuft`, Ring wie die gewählte Zone) ist der,
    der genau so heißt wie Titel oder Sender, die die Zone gerade nennt
    (beim Audioserver-Kanal auch dessen Name), und nur solange sie spielt;
    passt keiner, ist keiner markiert. Quer in der Spalte steht die
    Jetzt-läuft-Karte dafür quer (Cover 72 px links, Titel daneben), darunter
    „Favoriten · Alle“ und drei Kacheln (`HS_SENDER_SPALTE`), wenn die
    Spalte die Höhe hat (`hausLage()`). Hochkant hat die Leiste eine dritte
    Zeile mit so vielen Kacheln, wie in der Mindestbreite `HS_SENDER_MIN`
    passen, dahinter „Mehr“; sie kostet die Raumkarten `HS_SENDER_HOCH` und
    steht nur, wenn danach noch eine Reihe Raumkarten Platz hat (kleiner
    oder niedriger Schirm), sonst bleibt die Musikauswahl über ⋮.
    „Alle“ und „Mehr“ öffnen die Musikauswahl. Cover (auch das große des
    Spielers) liegen über dem Musik-Symbol; lädt eines nicht, entfernt
    `hsCoverFehlt()` das Bild und das Symbol bleibt.
  - **Maßstab:** `--hk` aus der kleineren Seite der Fläche (iPad 1, großes
    Display bis 1,5, 4″ nicht unter 0,7). Tasten sind nie kleiner als 44 px.
  - **Farben:** wie die Kacheln des Sets. Eine aktive Karte bekommt
    `--kachel-an` (ohne Set getönt), ihr Zustand `--an-text`, das Symbol
    `--glow`. Im Aufbau „mitte“ kippt sie mit `--kachel-an-ink`/`-muted`, im
    Aufbau „kreis“ steht ein aktives Symbol im `--glow`-Kreis.
  - **Live:** Die Seite besteht aus benannten Blöcken (`data-hb`). Kommt
    dieselbe Seite neu, gleicht `updateHaus()` nur die Blöcke an, deren HTML
    sich geändert hat, solange Lage und Blockfolge (`hausSig()`) gleich
    bleiben; zur Lage zählt, ob die Raumkarten scrollen, nicht ihre Höhe in
    Pixeln (die zieht `hausMasse()` mit `--hk` nach, sonst baute im
    Scroll-Fall jede Größenänderung die Seite neu). Angleichen statt
    ersetzen (`hsAngleichen()`, seit 18.10.2026): Was gleich ist, bleibt
    derselbe Knoten, nur Geändertes kommt neu (Attribute, Text, Kinder). So
    bleibt eine Scroll-Fläche in einem Block stehen („Auf einen Blick“, die
    Zonen des Spielers) und behält ihre Position, auch während eines Wischs;
    vorher zog jeder neue Wert darin die Liste nach oben. Baut
    `renderHaus()` die Seite neu (Drehen, andere Lage, Zone gewechselt),
    merkt es sich vorher, wie weit jede Scroll-Fläche gescrollt war (je
    Block und Klasse, `hsScrollStand()`), und setzt das am Ende wieder
    (`hsScrollZurueck()`, nach Uhr und Leiste, die noch Höhen ändern).
    Bedient wird über einen Klick-Verteiler (`hausKlick()`).
  - Geprüft in `tests/test_haus.py` (Anlage `lox.haus_anlage()`) und
    `tests/browser/test_haus_browser.py`: iPad quer und hochkant und großes
    Display, ohne Set und in jedem Set; kein waagerechtes Scrollen, Tasten ab
    44 px, nichts abgeschnitten; Bedienen am Miniserver-Nachbau, Tausch nur
    des geänderten Blocks; beide weiteren Aufbauten in jedem Set und jeder
    Größe, Bedienen (Tasten, Rückfrage, „Auf einen Blick“) und ihre Wahl im
    Konfigurator; Schnellaktionen im Set Loxone (Maße gegen die
    Tokens, Befehl an den Zentral-Baustein, Anzahl verschwindet über
    `_on_value()` und kommt wieder) und ohne Zentral-Baustein kein Knopf;
    Hinweise in jedem Aufbau, Set und Gerät (Leiste mit „+n“, Spalte mit
    Zahl, Farben gegen die Tokens), Bedienen mit Unterseite und Wegfall
    über `_on_value()`, Termine bei festgestellter Browser-Uhr; Sender quer
    und hochkant (Cover ab 60 px, Bild über einen Nachbau, fehlendes und
    nicht ladendes Cover, Abspielen am Miniserver-Nachbau, Markierung wandert
    über `_on_value()`, „Alle“/„Mehr“).
    Die Lesbarkeit aller Texte in allen Sets misst
    `test_kachel_set_kontrast_browser.py` (Ansichten `haus`, `haus_raeume`,
    `haus_spalte` und mit Hinweisen `haus_hinweise`, `haus_spalte_hinweise`;
    in allen die Sender im Spieler).
- Gesten (13.10.2026, Konzept in `docs/TODO.md` §9 „Loxone-Standard als
  Gesten“): Zwei Finger bedienen den Raum der Seite wie ein Loxone-Taster,
  auf der Hausübersicht den der Raumkarte unter den Fingern (16.10.2026).
  Die Fläche (`.screen`) ist in drei Spalten geteilt (`GESTE_SPALTEN`):
  Mitte Licht (hoch/runter dimmt, quer vorige/nächste Stimmung, Tipp
  schaltet ein bzw. zur nächsten Stimmung), links Beschattung (hoch/runter:
  ganz auf/ab, fährt sie schon, hält sie an; quer die Lamellen; Tipp
  beschatten), rechts Musik (hoch/runter: Lautstärke, quer voriger/nächster
  Sender, Tipp Play/Pause); Doppeltipp Raum verlassen, Dreifachtipp Haus
  aus, beide egal wo. Ein Finger bleibt, wie er war. Was jede Spalte tut,
  steht einmal in `GESTE_ARTEN` (`art` für hoch/runter, `quer`, `tipp`);
  daraus lesen Erkennung, Hilfe und Nacht-Uhr.
  - **Visu:** Touch-Events, nicht Pointer-Events: Nur `touchstart` und
    `touchmove` mit `preventDefault()` (nicht passiv, auf `.screen`) halten
    Scrollen und Klick an. Die Geste springt an bei genau zwei Fingern, die
    sich gemeinsam um `GESTE_MINDESTWEG` (Anteil der Höhe) bewegen, ohne zu
    kneifen (`GESTE_KNEIFEN`). Ob hoch/runter oder quer, entscheidet die
    größere Richtung in diesem Moment, sie gilt bis zum Loslassen. Scrollt der erste
    Finger schon (`cancelable === false`), gibt es keine Geste statt einer
    halben. Ein Tipp sind zwei Finger, die nicht wandern und nach höchstens
    `GESTE_TIPP_MS` oben sind; er wartet `GESTE_MEHRFACH_MS` auf den
    nächsten, der dritte löst sofort aus. Solange zwei Finger lagen
    (`gesteSequenz`), gibt es kein „zurück“ und danach `GESTE_KLICKSPERRE_MS`
    keinen Klick auf Kacheln. Aus bleiben die Gesten im Grundriss (dort
    zoomen zwei Finger), auf Detailseiten, im PIN-Feld, in Menüs und auf der
    Uhr-Seite (`gesteErlaubt()`). Die Einblendung `#geste` deckt das ganze
    Display (Vollbild, 16.10.2026, Vorbild ist das Display von Apple Home),
    siehe „Einblendung im Vollbild“ unten. Ein Fingerweg über die ganze Höhe
    sind 0 → 100 %, quer bei den Lamellen die ganze Breite (nach rechts =
    mehr), beides gezählt ab dem Punkt, an dem das Wischen erkannt ist;
    Zwischenwerte gehen höchstens alle `GESTE_TAKT_MS`. Welche Arten einen
    Wert stellen, sagt `GESTE_WERT_ARTEN`; Stimmung und Sender quer sind
    ein Schritt beim Loslassen (`richtung` `vor`/`zurueck`), bis dahin
    zeigt die Einblendung nur die Richtung. Auf der Hausübersicht schickt
    die Visu den Raum der Karte unter der Mitte der Finger mit
    (`gesteKarte()`, `data-hb="r:<Raum>"`), bei einer Tippfolge den des
    ersten Tipps.
  - **Server:** `App.geste()` (`bin/gesten.py`) sucht Raum, Bausteine und Befehle selbst, die
    Visu nennt nur Art und Wert. Raum ist der der Seite (Raum-Tab oder Raum
    unter „Räume“), auf der Hausübersicht der der Raumkarte (`raum` der
    Nachricht, nur ein Raum, den die Ansicht zeigt), sonst `ui.gestenRaum`
    der Ansicht (`geste_raum()`). Die
    Bausteine sind die der Raumseite (Kategorie-Filter, Ausblendungen),
    ohne Visu-Passwort, denn eine PIN-Abfrage mitten in der Geste geht nicht.
    Licht rechnet mit **Lichtgruppen** (`licht_gruppen()`): jede
    Lichtsteuerung mit ihren dimmbaren Lichtkreisen (Unterbausteine vom Typ
    Dimmer ohne die Master-Helligkeit `details.masterValue`) und jeder
    einzelne Dimmer. So gilt dasselbe für eine Lichtsteuerung mit vielen
    Kreisen, mehrere in einem offenen Raum und lauter einzelne Dimmer.
    Gedimmt wird, was leuchtet, anteilig (Startwert der hellste Kreis, jeder
    Kreis mit demselben Faktor; ein Kreis bekommt nur bei geändertem Wert
    einen Befehl); ganz unten gehen die Kreise aus und die Lichtsteuerung auf
    „Aus“ (`changeTo/778`), statt dunkel auf „Manuell“ zu stehen. Die
    Master-Helligkeit bleibt unberührt: Wie sie sich nach einem
    Stimmungswechsel verhält, sagen weder Strukturdoku noch
    Wissensdatenbank. Leuchtet nichts, schaltet die Bewegung nach oben die
    Stimmung des Geräts ein (`devices[name].lichtStart`, sonst die erste der
    ersten Lichtsteuerung im Raum), genau einmal; weiter gedimmt wird mit der
    nächsten Geste. Der Tipp schaltet aus → diese Stimmung, an → die nächste
    derselben Lichtsteuerung (`moodList`-Folge, „Aus“ übersprungen). Raum
    verlassen löst den Taster aus `ui.raumVerlassen` aus, ohne ihn alles,
    was an ist und sich abschalten lässt (`HAUS_AUS`, wie „Gerade aktiv“;
    das Raumklima bleibt dann unberührt). Haus aus wirkt nur mit dem Taster
    aus `ui.hausAus`. Ein laufendes Dimmen hält `conn_geste` je Verbindung.
    Quer geht die Stimmung in der Folge des Tipps vor oder zurück (ist das
    Licht aus: die erste bzw. letzte). Der Sender läuft durch die Favoriten
    der Zone (`_zonen_favoriten()`, dieselben wie auf Detailseite und
    Hausübersicht), vom laufenden aus, wenn er sich am Namen erkennen lässt
    (Titel, Sender oder Album des Spielers, `_laufende_namen()`), sonst vom
    ersten bzw. letzten; kennt der Server noch keine, fragt er sie an und
    meldet „Keine Sender“. Die Lamellen bekommen erst beim Loslassen einen
    Befehl, denn jeder Zwischenwert ließe den Antrieb anlaufen:
    `manualLamelle/{v}` an alle Raffstores des Raums (Jalousien mit
    `shadePosition` und `details.animation` Raffstore), Startwert das Mittel
    ihrer Lamellenstellung. Tipp links schickt `shade` an alle Jalousien
    des Raums; Tipp rechts pausiert, was im Raum spielt, sonst startet er
    die erste Zone (`play`). Nach auf/ab und beschatten meldet der Server
    die Stellung der Jalousien des Raums, solange sie fahren
    (`geste_fahrten()`, jeder Takt des Broadcasters): die Antwort trägt ihr
    Mittel (`wert`, State `position` in Prozent), danach `{t:"geste",
    phase:"wert"}` mit Stellung und „Fährt ab“/„Fährt auf“, sobald sich
    etwas ändert, und am Ende `phase:"ende"` („Geschlossen“, „Offen“, „40 %
    geschlossen“). Bis der Miniserver die Fahrt meldet, schickt er nichts;
    fährt nach `GESTEN_FAHRT_ANLAUF_S` keine los (Endlage), endet es,
    länger als `GESTEN_FAHRT_MAX_S` beobachtet er nicht. Die Beobachtung
    steht in `conn_geste` wie ein laufendes Dimmen, die nächste Geste der
    Verbindung löst sie ab.
  - **Einblendung im Vollbild:** `gesteBild()` legt `#geste` fest über das
    ganze Fenster (am `body`, nicht in `.screen`, die höchstens so groß wie
    ihre Kacheln ist und skaliert). Licht und Musik füllen es von unten bis
    zum Wert (`pegel`, in `--glow` bzw. `--accent`), die Jalousie fährt als
    Vorhang mit Lamellen von oben ins Bild (`vorhang`, live mit der
    Stellung vom Server), die Lamellen zeigen ihre Kippung (`lamellen`,
    Streifen so dick wie gekippt). Oben stehen Art und Raum mit Symbol, in
    der Mitte groß der Wert (`.gs-wert`, „48 %“) oder das Wort (Stimmung,
    Sender, Fehler), darunter, was der Server dazu meldet (`.gs-sub`). Die
    Schrift steht in zwei Ebenen: über der Füllung `--ink`, auf ihr die
    Schrift zur Füllfarbe; `clip-path` teilt sie an der Kante, auch mitten
    durch die Ziffern. Die Maße wachsen mit dem Display (Container-Einheiten
    wie die Nacht-Uhr, die Zahl 27 % der kürzeren Seite, davor px für
    Browser ohne sie). Im Dunkeln (`leise`) liegt alles gedämpft auf
    `--nacht-grund`, die Nacht-Auflage `#nightdim` bleibt darüber. Die
    Farben rechnet der Server (`theme_colors.geste_farben()`, als
    `--geste-*` im theme): Schrift auf Licht und Musik nach `schrift_auf()`,
    Vorhang und Lamellen in `--ink` über der Fläche, nachts alles von
    `nacht_schrift()` aus (helle Sets haben dunkle Schrift- und
    Rollenfarben, die auf Schwarz verschwänden). Jede Deckung ist eine
    Obergrenze (`GESTE_*`): trägt die Schrift darauf kein AA mehr, nimmt
    `_deckend_bis()` weniger. Ohne Set und Grundfarbe gelten die
    Standardfarben der Visu (`VISU_STANDARD`, dieselben wie in `grund.css`).
  - **Im Dunkeln (Stufe 5):** Auf der Uhr-Seite und im abgedunkelten
    Nachtmodus weckt ein Finger wie bisher, zwei Finger sind eine Geste, die
    das Panel dunkel lässt: keine Uhr weg, kein Aufhellen, die Einblendung
    `leise` (gedämpft auf Schwarz). Ob ein zweiter Finger kommt, steht erst kurz nach dem ersten
    fest, so lange wartet das Wecken (`GESTE_ZWEITER_FINGER_MS`,
    `weckenAufschieben()`); losgelassen weckt er sofort. Ohne Gesten weckt
    jede Berührung ohne Wartezeit wie bisher. Die Geste gilt der Seite unter
    der Uhr, nach der Ruhe der Startseite. Die LoxPanel-App gibt Berührungen
    im Schoner erst bei einem zweiten Finger an die Visu weiter
    (`SchonerBeruehrung.kt`, gleiche Wartezeit, `android/README.md`). Fully
    Kiosk und der Linux-Agent schalten das Display selbst ab; ist es dort
    ganz aus, weckt jede Berührung wie bisher.
  - **Hinweis-Symbol:** Rechts unter dem Kachelfeld steht auf Seiten, auf
    denen Gesten wirken, ein kleines Symbol (zwei Finger mit Doppelpfeil,
    `ICONS.zweiFinger`, in `--muted`). Ein Tipp öffnet die Hilfe
    (`gestenHilfeZeigen()`): die drei Spalten genau dort, wo sie wirken, mit
    Symbol, Titel und was hoch/runter, quer und ein Tipp tun (`GESTE_ARTEN`, aus
    derselben Liste lesen Erkennung und Nacht-Uhr), darunter Doppel- und
    Dreifachtipp mit den Tastern aus den Vorgaben. Diese Zeilen baut der
    Server (`view.gestenHilfe`, `gesten_hilfe()`), denn nur er kennt die
    Taster. Das Symbol steht in einer Fußzeile, in der auch die Seitenpunkte
    sitzen: 24 px hoch (`--hinweis-h`, ein Tippziel nach WCAG 2.5.8). Sie
    gilt auf jeder Seite der Ansicht, sobald Gesten und Hinweis an sind,
    auch wo das Symbol fehlt, damit die Kacheln von Seite zu Seite gleich
    groß bleiben. `raster.js` zieht sie ab (`fussH()`, Maß `hinweisH`), Visu
    und Konfigurator gleich. Nur bei waagerechten Seiten, nicht auf
    schmalen Schirmen (`SCHMAL_UNTER`). Die Hausübersicht hat keine
    Fußzeile und damit kein Symbol. Abschaltbar unter Vorgaben →
    Verhalten → Gesten und je Ansicht (`ui.gestenHinweis`); ohne Eintrag
    an (`GESTEN_HINWEIS_STANDARD`).
  - **Nacht-Uhr:** Nachts zeigt die Uhr-Seite auf Wunsch (`ui.nightClock`)
    nur die Uhrzeit, gedimmt auf Schwarz wie die Nachtanzeige der
    Loxone-Taster (`.saver.nacht`, `#svNacht`). Die Helligkeit
    (`ui.nightClockBright`, Prozent) setzt die Deckkraft von Ziffern und
    Symbolen; „Nachts abdunkeln“ wirkt zusätzlich. Sind Gesten an, steht
    oben über der Mitte jeder Gesten-Spalte ihr Symbol (`NACHT_UHR_SYMBOLE`:
    Beschattung, Licht, Musik). Wetter, Termine und die zweite Spalte ruhen
    (`svSideOn()` ist dann aus), keine Kamera läuft die ganze Nacht. Die
    Ziffern driften wie die Uhr der Uhr-Seite gegen Einbrennen. Grund und
    Schrift kommen aus dem Theme (`--nacht-grund` aus
    `theme_colors.NACHT_GRUND`, `--nacht-ink` aus `nacht_schrift()`): Trägt
    die Schrift des Themes auf Schwarz AAA, bleibt sie, sonst nimmt ihr
    Farbton die Helligkeit, die `derive()` für helle Schrift setzt
    (`HELLE_SCHRIFT`). In 1.1.0 nahmen die Ziffern `--ink`, in hellen Sets
    (Kreide, Touch) also dunkel auf Schwarz, unsichtbar. Die Regel,
    die den Inhalt ausblendet, muss das Raster der geteilten Uhr-Seite
    (`.saver.split .sv-wrap.rich`) schlagen. In 1.1.0 tat sie das nicht: Mit
    Wetter und Terminen lag die Nacht-Uhr quer über dem Inhalt, statt ihn zu
    ersetzen.
  - Geprüft in `tests/test_gesten.py` (Befehle am Miniserver-Nachbau,
    Anlage `lox.gesten_anlage()`, Einstellungen der Nacht-Uhr, Farben der
    Einblendung in jedem Theme, Fahrt der Jalousie),
    `tests/browser/test_gesten_browser.py` (zwei Finger über das
    DevTools-Protokoll, `Input.dispatchTouchEvent`; Uhr-Seite, Nacht,
    nachgebaute App-Brücke, Nacht-Uhr, quer wischen, Raumkarte der
    Hausübersicht, Vollbild auf drei Displaygrößen, Vorhang live) und
    `android/.../SchonerBeruehrungTest.kt`.
- Sprungmarken: Besteht die untere Leiste aus einem einzigen Raum-Tab
  (`room:`) oder einer einzigen freien Seite, ersetzt `view.catTabs` die Tabs
  durch Marken (Raum-Panel: Kategorien des Raums, freie Auswahl: ihre Räume;
  `isRoomPanel()`). Die Kacheln stehen nach Gruppe sortiert, die erste jeder
  Gruppe trägt `catKey` als Anker, jede Kachel `grp` (Kategorie bzw. Raum).
  Ein Tipp springt (Standard) oder filtert (`ui.catFilter`, im Konfigurator
  „Tipp auf eine Sprungmarke“). Springen geht auf die **Seite**, auf der die
  Gruppe beginnt (`springeZu()`, auf dem Tablet die waagerechte Seite, s.
  „Waagerechte Seiten“): die Kachelfläche rastet seitenweise ein
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
- Gesperrte Bausteine (Strukturdoku „Locking and Unlocking Controls“):
  `details.jLockable` sagt, ob ein Baustein sich sperren lässt, der Text-State
  `jLocked` hält bei einer Sperre ein JSON `{locked, reason}` (1 = über die
  Visualisierung, 2 = durch die Logik, leer = frei). Gesperrt nimmt der Baustein
  keine Befehle an. `sperre_state` (`_apply_structure()`) ordnet jedem
  Befehlsempfänger (Baustein, `uuidAction`, Unterbaustein, der ohne eigenen
  `jLocked` seinem Baustein folgt) den State zu, `_sperre_text()` (`Grundhelfer`,
  geparst in `_sperre_lesen()`, zwischengespeichert) liefert „Gesperrt durch die
  Logik: Grund“. Die Kachel nennt „Gesperrt“ und öffnet die Detailseite statt zu
  schalten; `render()` setzt `gesperrt` auf jede Seite des Bausteins (wie
  `secured`) und stellt den Text als `status` nach `hero`/`cover`/`video`. Die
  Visu dimmt dann Regler, Tasten, Favoriten und Formulare des Bausteins und nimmt
  ihnen die Wirkung (`.panel.gesperrt` in `seiten.css`); Zellen mit `nav` und
  die verlinkten Objekte bleiben bedienbar. Der WebSocket-Handler schickt einen
  Befehl an einen gesperrten Empfänger nicht zum Miniserver, sondern antwortet
  mit `notify` (mit PIN dazu `cmdresult` mit `gesperrt`); Gesten überspringen
  ihn (`_geste_befehle()`), bei einem einzigen Ziel nennt die Einblendung den
  Grund. `command()` selbst prüft nicht, damit Abfragen wie `roomfav/get` weiter
  laufen. Tests: `tests/test_sperre.py`, `tests/browser/test_sperre_browser.py`.
- Sprache wirkt nur auf Datum und Uhrzeit. Alle anderen Panel-Texte sind hart
  deutsch, sowohl im Frontend als auch in den vom Server erzeugten Texten
  („Offen", „Heizt", „Heute", Wochentage, Button-Beschriftungen).

### 7.2 Konfigurator: `config.html`, `config.css` und `config/*.js`

**Aufteilung** (seit 15.10.2026, Schritt 1 des Zerlegens der großen Dateien):
`config.html` hält nur noch das Markup (rund 450 Zeilen) und lädt `config.css`
und elf Skriptteile aus `webfrontend/html/config/` per `<script src>` an der
Stelle, an der vorher das eine Skript stand, in dieser Reihenfolge: `kern`
(Zustand, Helfer, Rubriken), `ansicht-aussehen` (Aktiv-Overlay, Kachel-Set,
Gesten), `ansicht-editor` (Vererbung, Skalierung, der Editor je Ansicht),
`speichern` (Speicherleiste, Vorschau in der Visu und am Gerät), `kacheln`
(Kachel-Editor, eigene Auswahl, Kurzfassung), `seiten-editor`, `einrichten`
(Leer anlegen, Duplizieren, gemeinsame Helfer, Gerät einrichten, Gerät
verbinden), `einstellungen` (Rubrik Einstellungen, Ersteinrichtung, SIP,
Kalender), `geraete` (Karten, neues Gerät, Betriebsmodus), `sicherung`
(Testton, Speichern-Knopf, Sicherung einspielen), `start`. Kein Build, keine
ES-Module: Alle Funktionen bleiben global, die Browser-Tests rufen sie weiter
beim Namen; was ein Teil beim Laden ausführt, darf nur Funktionen früherer
Teile rufen (eine spätere Funktionsdeklaration ist dann noch nicht gehoben).
Der Server liefert `/config.css` (`config_css`) und `/config/{name}`
(`config_js`, nur `[a-z0-9-]+.js`, sonst 404) wie die anderen
Oberflächen-Dateien mit `no-cache`. Der Übersetzungstest durchsucht auch die
per `script src` geladenen Teile, der Rauchtest ruft `/config.css` und
`/config/kern.js` ab; APK-Sync, Dockerfile und `.deb` nehmen `webfrontend/`
ganz. `tests/test_dateigroessen.py` wacht, dass keine Quelldatei über 1.500
Zeilen wächst (seit Schritt 4e ohne Ausnahme; `panel.html` ist seit
Schritt 2 aufgeteilt, §7.1; Schritt 3 hat die Bausteine nach `bausteine/`
gebracht, §6, Schritt 4a Konfiguration und Sicherung nach `konfig.py` und
`sicherung.py`, Schritt 4b die Verläufe nach `statistik.py` und die Helfer der
Bausteine als Mixins nach `bausteine/`, Schritt 4c Hausübersicht und Gesten
nach `haus.py` und `gesten.py`, Schritt 4d die übrigen Themen der App nach
`miniserver.py`, `geraete.py`, `audiodienst.py`, `front.py`, `verteilung.py`,
`intercomdienst.py`, `medien.py`, `diagnosedaten.py`, `ansicht.py` und `seiten.py`,
Schritt 4e die Routen-Handler nach `bin/routen/`; `webvisu.py` hat noch rund 460
Zeilen; später aus `konfig.py` die Symbolquellen nach `symbolquellen.py`). Beim Zerlegen des Servers gilt: die herausgelösten Module
importieren `webvisu` nie, `webvisu` importiert sie; wer in Tests eine
Konstante oder einen Helfer ersetzt, nimmt `ersetzen()` aus `tests/lox.py`,
das in jedem Server-Modul mit diesem Namen patcht (`tests/test_schichten.py`).
Methoden der App, die in ein Thema gehören, wandern als Mixin-Klasse in ihr
Modul (`Statistik`, `BausteinHelfer`, `Haus`, `Gesten`, `Miniserver`, `Geraete`, `Audiodienst`,
`Intercomdienst`, `Front`, `Verteilung`, `Medien`, `Diagnosedaten`, `Ansicht`, `Seiten`); `App`
erbt sie, Aufrufe über `self.` bleiben. Braucht ein Themenmodul einen Namen eines anderen,
importiert es ihn von dort (`verteilung.py` `_lan_adressen()` aus `geraete.py`, `seiten.py` die
Overlay-Rechnung aus `ansicht.py`, `intercomdienst.py` `ZugangFehler` aus `miniserver.py`). Die
Bausteine importieren kein Themenmodul (sonst lädt `bausteine/__init__.py` beim ersten Import
eines Themas dessen halb fertiges Modul), und jedes Server-Modul muss sich auch als erstes
laden lassen; beides prüft `tests/test_schichten.py`. Ein neues herausgelöstes Modul gehört in `_ZERLEGT_MODULE` in `tests/lox.py`, und zwar
hinter die Module, aus denen es importiert, sonst wirkt `ersetzen()` dort nicht oder
`ZERLEGT` ordnet einen Namen dem falschen Modul zu.

**Begriffe der Oberfläche** (seit 10.10.2026, Konzept „Konfigurator neu
ordnen“). Jedes Wort hat genau eine Bedeutung; neue Texte halten sich daran:

| Wort | Bedeutet | Im Code |
|---|---|---|
| Ansicht | was ein Gerät zeigt: Leiste, Seiten, Kacheln, Aussehen, Verhalten | ein Profil in `panels.json`, `?panel=` |
| Gerät | was an der Wand hängt oder als Tablet läuft | `devices` in `panels.json`, `?device=` |
| Vorgaben | Werte für alle Ansichten, die eine Ansicht überschreiben kann | `__global__`, `theme.json` |
| Einstellungen | Server und Dienste: Miniserver, Türstation, SIP, Audio, Kalender und Wetter, Sicherung | Rubrik `settings` |
| Kennung | der feste Schlüssel einer Ansicht, mit dem ein Gerät sie öffnet; ein Gerät hat keine Kennung, sondern einen Namen (ohne Namen zeigt es seinen Kopplungscode) | Schlüssel in `panels`, `?panel=<kennung>` |

„Kennung“ meint seit dem Nachlauf der Einrichtung neu (15.10.2026) nur noch
die Ansicht; ein Gerät heißt „ohne Namen“, nicht „ohne Kennung“.
„Panel“ kommt in der Oberfläche nur noch im Produktnamen und als Bauform
(„4″-Wandpanel“) vor, „Display“ nur für den Bildschirm selbst (Display aus,
Display-Steuerung, Display-Treiber). Die Rubriken heißen Übersicht,
Ansichten, Vorgaben (seit Schritt 5, `data-rub="vorgaben"`),
Geräte und Einstellungen (die frühere Rubrik „unterstützte Geräte“ steht seit
Schritt 4 als „Erprobte Hardware“ unter Geräte); die interne Kennung der übrigen
(`data-rub`) blieb dabei gleich. Die Rubrik „Einrichtungsassistent“ gibt es seit
Schritt 7 nicht mehr, ihr Weg ist „Gerät einrichten“. Unter 1200 px Breite rücken die Rubriken enger,
noch schmaler brechen sie um, statt die Seite waagerecht scrollen zu lassen.

- Liest `GET /api/meta`, schreibt `POST /api/panels` und `POST /api/theme`.
- Die gesamte rechte Seite wird per `innerHTML` neu aufgebaut; Zustand in vier
  Modulvariablen (`META`, `PANELS`, `cur`, `OFFEN`).
- **Eine Speicherleiste** (seit 10.10.2026, Schritt 2 des Konzepts): Sie steht unter
  Ansichten, Geräte und Einstellungen und nennt, was offen ist („Nicht gespeichert:
  Ansicht Flur, Geräte, Kalender & Wetter“). `OFFEN` hält dafür je Ansicht
  `ansicht:<Kennung>` (`ansicht:__global__` = Vorgaben) und die Bereiche `geraete`,
  `nacht`, `intercom`, `audio`, `kalender`, jeweils mit einer laufenden Nummer:
  Speichern hakt nur ab, was seit dem Absenden nicht erneut geändert wurde.
  `markDirty()` meldet die Ansicht, `bereichOffen()` einen Bereich; die Karten unter
  Geräte und Einstellungen melden sich über `input`/`change`. `speichernAlles()`
  schreibt nacheinander Ansichten (`/api/panels`, `/api/theme`), Geräte
  (`/api/devices`), Nachtmodus, Kamera, Audio und Kalender und lädt erst danach
  einmal `loadSettings()`. Weder `loadSettings()` noch `loadPanelIds()`
  überschreiben einen offenen Bereich. Ein Rubrikwechsel verliert nichts, nur
  Neuladen oder Schließen der Seite fragt nach (`beforeunload`). „Verbinden &
  Speichern“ des Miniservers bleibt ein eigener Knopf, weil er zuerst die Verbindung
  prüft.
- **Sechs Reiter je Ansicht** (seit 10.10.2026, Schritt 3): `PCONF_TABS` =
  Allgemein (Titel, Sprache, Kennung mit Duplizieren und Löschen),
  Inhalt (untere Leiste, Räume, Kategorien, Widget/Kopfzeile/Werteleiste je
  Standard-Seite in `#panePerTab`), Seiten (Seiten-Editor samt `#sePaneBox` für
  die gewählte freie Seite), Raster (Kachel-Layout, Bildschirm
  füllen, Skalierung, Split, Widget-Breite, Versatz), Aussehen (Kachel-Set,
  Farbe und Aufbau, Schrift, Größen, Kacheln gestalten, Aktiv-Overlay) und
  Verhalten (Screensaver, Display aus, Nacht, Auto-Neustart, PIN merken). Jedes
  Feld steht in genau einem Reiter, die Feld-IDs sind seit Schritt 2 gleich
  geblieben; `test_reiter_ansicht_browser.py` hält beides fest. Aussehen ist in
  Gruppen gegliedert (`aussehenGruppe()`: Überschrift, Felder, ein kurzer
  Hinweis, Erklärungen zum Aufklappen), zuerst das Kachel-Set, weil es Farben,
  Aufbau und Standardgrößen bestimmt. Es wird über Karten gewählt
  (`kachelSetKarten()`, `data-ks-set`): „Eigene Farben“ ohne Set und jedes Set aus
  `/api/meta` (`kachelSets`) mit Name, Beschreibung und einer Vorschau in den
  Farben, die die Visu malt (`kachel_set_vorschau()`: Rahmen, Fläche, Kachel,
  aktive Kachel, Akzent). Bei einem Set mit Farbton (touch) erscheinen darunter
  Regler auf dem Verlauf der Kachelfarben, Schnellwahl, „Aktive Kachel“ hell oder
  dunkel und „Nachgerechnet“ (`kachelSetExtraHtml()`, Werte von `/api/kachelset`,
  das auch die Vorschau der Karte nachzieht). Mit Set weicht die Gruppe „Farbe und
  Aufbau“ (Grundfarbe, Kachel-Aufbau, `#fAgFarbe`) einem Hinweis (`#fAgAusSet`),
  der Kachel-Aufbau ist gesperrt, leere Größenfelder zeigen die Größen des Sets
  (`sizeStd()`). Vorgaben → Darstellung gliedert dasselbe in Grundfarbe, Sprache,
  Schrift und Größen (`appearanceFields()`), der Assistent zeigt dieselben Karten.
  `test_aussehen_reiter_browser.py` prüft Reihenfolge, Ausblenden, Überlappung
  und Überlauf am iPad quer und hochkant. `renderPanes()`
  zeichnet `paneListe()` zweimal: Standard-Seiten unter Inhalt, die freie Seite
  im Seiten-Editor.
- **Vorgaben als Rubrik** (seit 10.10.2026, Schritt 5): Die Vorgaben stehen nicht
  mehr in der Liste der Ansichten, sondern unter der Rubrik Vorgaben mit drei
  Reitern (`VG_TABS`): Darstellung (samt Sprache und Skalierung), Kategorie-Farben
  und Verhalten (bis Schritt 6 „Nacht“). Bearbeitet werden sie im selben Editor wie eine Ansicht
  (`cur='__global__'`, `renderGlobalEditor()`), aber nur in ihrer Rubrik:
  `setRubric()` merkt sich beim Wechsel dorthin die gewählte Ansicht
  (`letzteAnsicht`) und kehrt bei jeder anderen Rubrik zu ihr zurück; der Reiter
  steht in `subVg`. Verhalten trägt den Nacht-Auslöser (vorher unter Geräte, Arbeitskopie
  `NACHT` wie `CALS`, gespeichert über `/api/settings/night`, Bereich `nacht` der
  Speicherleiste) und die Abdunkelung für alle Ansichten (`nightDim`, `nightWake`
  in `theme.json`), seit Schritt 6 auch Display aus und Auto-Neustart (`dpmsOff`,
  `reloadHours`, `displayFelder()`). Unter Verhalten zeigt eine Ansicht ohne eigenen Eintrag grau,
  was sie erbt (`nachtVorgabe()`: Vorgabe, sonst `nightDefaults` aus `/api/meta`).
  `test_vorgaben_browser.py` hält das fest.
- **Vererbung sichtbar** (seit 10.10.2026, Schritt 6): Jedes Feld mit Vorgabe oder
  Gerätewert trägt eine Zeile `.erbt` (`erbtFeld()`), gefüllt von `erbtZeichnen()`
  (Ansicht und Vorgaben, nach jedem Zeichnen und in `markDirty()`) und
  `geraetErbtZeichnen()` (Gerätekarte, nach jeder Eingabe und jeder Abfrage). Die
  Kette ist die des Servers: Gerät vor Ansicht vor Vorgaben vor Standard
  (`effective_scale()`, `effective_grid_auto()`, `resolve_profile()`).
  - In der Ansicht nennt ein leeres Feld, was gilt und woher („19 px · aus den
    Vorgaben“, „38 px · Standard“). Ein gesetztes zeigt „× zurücksetzen“, der Titel
    sagt, was danach gilt. Bei Skalierung und Zielkachel stehen dazu die Geräte, die
    die Ansicht zeigen und den Wert selbst setzen („am Gerät wand: 125 %“).
  - In den Vorgaben zählt die Zeile, für wie viele Ansichten der Wert gilt, und
    nennt die mit eigenem Wert.
  - Auf der Gerätekarte (Technik) steht, was aus der gezeigten Ansicht kommt
    (`geraetAnsicht()`: die gemeldete, sonst die zugeordnete, `DEVICE_ZUORDNUNG`).
  - Welche Schlüssel eine Vorgabe haben, liefert `/api/meta` als `themeKeys`
    (= `THEME_UI_KEYS`); Standardwerte kommen aus `sizeDefaults`, `nightDefaults`
    und `kachelZiel`. „Zurücksetzen“ löscht den Schlüssel, das ist überall die Form
    für „erbt“. Damit die Ansicht die Geräte richtig nennt, folgt `DEV` jeder
    Eingabe auf der Gerätekarte (`readDevFromDom()`).
  - `test_vererbung_browser.py` hält das fest.
- **Gerät einrichten, ein Bildschirm** (seit 15.10.2026, Einrichtung neu
  Schritt 3): `#geOv`, `geOpen(name)`, Zustand `GE`. Öffnet sich aus dem Banner
  „Neues Gerät gefunden“ (mit dem Gerät), aus der Übersicht
  (`#ovGeraetEinrichten`, Kasten „Gerät einrichten“), unter Geräte
  (`#geraetEinrichtenBtn`), nach der Ersteinrichtung (`#einrAssistent`) und über
  „＋ Neue Ansicht“ (`#addBtn`, dann ohne Gerät: „Ansicht anlegen“ statt
  „Fertig – auf … anzeigen“, danach der Editor). Der Kopf nennt Gerät, Klasse
  (`geraeteKlasse()`) und Größe aus `DEVICE_SCREENS`. Links der Name der Ansicht
  (`geNameVorschlag()`: der Raum zum Gerätenamen über `raumZumGeraet()`, sonst
  „Haus“, bei der Kopie der Zielraum oder die Vorlage, sonst das Gerät; die
  Kennung folgt mit `idAusName()`, also eindeutig) und die Frage „Was soll es
  zeigen?“ mit drei Karten (`geKarte()`, `GE.art`): *Einen Raum* (Raum-Auswahl,
  Ansicht `tabs: ["room:<uuid>"]`), *Das ganze Haus* (Aufbau aus
  `META.hausAufbauten`, Ansicht `tabs: ["haus","favoriten"]`; am 4″-Wandpanel,
  `LoxRaster.quadratisch`, gesperrt), *Wie ein anderes Gerät* (Vorlage = jede
  Ansicht, beschriftet mit den Geräten, die sie zeigen, aus `DEVICE_ZUORDNUNG`;
  Raumtausch nach dem Raum zum Gerätenamen, `profilMitRaumtausch()`,
  `geKopieInfo()`).
  `geProfil()` baut die Ansicht: am quadratischen Gerät `ui.split=false` (ein
  Pane, festes 2 × 2), sonst `ui.grid="auto"`, dazu `device` mit Größe; alles
  Weitere kommt aus den Vorgaben. Rechts die echte Visu als Vorschau: `geVorschau()`
  schickt den Entwurf an `POST /api/entwurf` (eigener Token in `GE.token`, 350 ms
  nach der letzten Änderung), der iframe `#geFrame` zeigt `/?panel=<id>&entwurf=…`
  in der gemeldeten Größe und `geVorschauMass()` verkleinert ihn per `transform`
  auf den Platz (die Visu rechnet ihr Raster für die echte Größe); gleicher Token
  und gleiche Kennung: der Server lädt die Visu im iframe selbst neu. Ein
  Vorschaufenster ist kein Gerät (`conn_info.vorschau`, kein Code, nicht unter
  `anonymous`), und die Visu startet dort mit dem Inhalt statt der Uhr-Seite
  (`panel.html`, `ENTWURF`). „Fertig – auf … anzeigen“ (`geFertig()`) trägt die
  Ansicht in `PANELS` ein und ruft `ansichtAmGeraet()`: speichern, dann
  `/api/device/switch` (die Zuordnung, Schritt 2; ein Gerät, das nicht verbunden
  ist, zeigt sie beim Verbinden). Schließen (`geClose()`, ✕, Abbrechen, Esc,
  Klick daneben) ersetzt den iframe, damit keine Verbindung ohne Namen stehen
  bleibt, wenn die Visu darin gerade selbst navigiert. „Leer anlegen“ bleibt
  (`createBlankPanel()`). `test_geraet_einrichten_browser.py` hält den Weg fest:
  Tablet aus dem Banner, Raum, Haus, Kopie mit Raumtausch, Fertig mit Zuordnung,
  4″-Panel ohne Haus, „＋ Neue Ansicht“ mit genau diesen drei Karten.
- **Der frühere sechsstufige Assistent** (`wz*`, „Selbst zusammenstellen“)
  ist seit 15.10.2026 abgebaut: Was er konnte, leisten „Gerät einrichten“
  (Raum, Haus, Kopie mit Raumtausch, Vorschau, Fertig mit Zuordnung) und der
  Editor unter Ansichten (klassische Leiste, freie Seiten mit Seiten-Editor,
  Aussehen, Springen/Filtern, Vorschau am Gerät auch für eine ungespeicherte
  Ansicht). Geblieben sind seine Dialog-Klassen (`.wzov`, `.wzbox`, `.wzbtn`,
  `.wznote`, `.wzq`, `.wzopts`, `.wzo`, `.wzfield` …), die auch „Gerät
  einrichten“, „Gerät verbinden“, Duplizieren und der Betriebsmodus-Assistent
  tragen, und ein Abschnitt gemeinsamer Helfer: die Icons (`IKONEN`,
  `ikon()`), `geraeteMitGroesse()`, `dieserBrowser()`, `geraeteKatalog()`
  (Vorschaugeräte des Seiten-Editors), `raumZumGeraet()` (Raumvorschlag),
  `raumOptionen()`, `paneWert()` (Widget-Wahl → `ui.panes`) und
  `ansichtAmGeraet()` (speichern und umschalten). „Leer anlegen“
  (`createBlankPanel()`) bleibt.
- **Eine Karte je Gerät, fünf Zeilen** (seit 10.10.2026 Schritt 4, seit
  15.10.2026 in der Form der Einrichtung neu, Schritt 4): `#geraete` hält je
  Gerät eine `.gk` (Namen aus `/api/devices`, `KNOWN_NAMES` und `DEV`,
  `geraeteKarten()`). Der Kopf (`.gk-kopf`, `deviceRow()`: Zustand, Name, Typ,
  IP, Neu laden, Display an/aus, Agent, Diagnose) und darunter fünf Zeilen
  (`.gz`, `gzZeile()`: Name der Zeile, Wert und Herkunft, Aktion):
  - *Zeigt* (`zeigtHtml()`): die Auswahl der Ansicht (`.agsel`) mit „Ansicht
    wechseln“ (`/api/device/switch`, auch für ein Gerät, das nicht verbunden ist:
    die Zuordnung, Schritt 2), Kennung, Raster und Kachel-Set der Ansicht, ein
    Betriebsmodus, der gerade gilt; „Feinschliff ›“ öffnet die Ansicht im
    Editor. Editor: Gesten (Stimmung beim Einschalten).
  - *Display* (`displayHtml()`, `displayGilt()`): „Aus nach n s“ und woher –
    am Gerät (`devices[name].dpmsOff`), aus der Ansicht (älterer Eintrag),
    aus den Vorgaben oder Standard – und der Präsenzmelder. Editor: Display aus
    nach (Sek.) am Gerät und Präsenzmelder.
  - *Betriebsmodi* (`modiHtml()`): die Modi mit ihren Ansichten oder „Keine“.
    Editor: Automatik, Modus → Ansicht.
  - *Technik* (`technikHtml()`): Typ, Display-Treiber, Skalierung und Zielkachel
    mit Herkunft. Editor: Skalierung, Zielkachel, Display-Steuerung.
  - *Entfernen* (`entfernenHtml()`): nur für ein Gerät mit Einstellungen; die
    Ansicht bleibt.
  „Ändern“/„Einrichten“/„Gesten“ (`.gz-auf`) klappt den Editor der Zeile
  (`.gz-editor`) auf; offene merkt `GK_AUF` als `<gerät>/<zeile>`. Kopf und
  Zeile Zeigt folgen der Abfrage alle 6 s (`koepfeZeichnen()`, nicht, wo gerade
  jemand wählt), die Werte der übrigen Zeilen folgen der Abfrage und jeder
  Eingabe (`gzWerteZeichnen()`). Nur Eingaben in den Editoren melden `geraete`
  bei der Speicherleiste, die Auswahl der Ansicht schaltet live. Darunter:
  Geräte ohne Namen (`#ag_anon`) und „Erprobte Hardware“; „＋ Gerät
  verbinden“ (`#geraetVerbindenBtn`) öffnet den Bogen mit den drei Wegen.
  Der Nachtmodus steht unter Vorgaben → Nacht. `test_geraetekarte_browser.py`
  hält die fünf Zeilen fest.
- **„Display aus nach“ in den Vorgaben und am Gerät** (seit 15.10.2026,
  Einrichtung neu Schritt 4): `devices[name].dpmsOff` (Sek., 0..3600) gilt vor
  einem Eintrag der Ansicht und vor den Vorgaben (`panel_dpms(pid, roh, dev)`;
  die theme-Nachricht an die Visu und die Antwort an den Agenten nehmen das
  Gerät mit). Die Ansicht hat das Feld nicht mehr (Reiter Verhalten:
  `neustartFeld()` statt `displayFelder()`); trägt sie noch einen Wert aus einer
  älteren Fassung, nennt der Reiter ihn mit „Eintrag entfernen“, und die
  Gerätekarte nennt ihn als Herkunft. `tests/test_display_geraet.py`.
- **Gerät verbinden, drei Wege** (seit 15.10.2026, Einrichtung neu Schritt 5):
  `#gvOv`, `gvOpen()`, aus Geräte (`#geraetVerbindenBtn`), der Übersicht
  (`data-goto="verbinden"`).
  Drei Karten (`gvWeg()`), je eine Zeile zum Kopieren (`data-gv-copy`,
  Zwischenablage): die Server-Adresse für die LoxPanel-App, die Start-Adresse
  `http://<host>/` ohne Parameter für Fully Kiosk, WallPanel oder einen
  Browser (Namen und Ansicht vergibt der Konfigurator über das Banner), und
  `curl -fsSL http://<host>/install-agent.sh | SERVER=<host> bash` für ein
  Linux-Panel, ohne `PANEL` und `AGENT_NAME` (Ansicht und Display kommen vom
  Server, der Name vom Hostnamen). `gvHost()` nimmt die LAN-Adresse aus
  `/api/meta` `adressen` (`_lan_adressen()`) und den Port dieses Fensters,
  damit die Zeilen auch stimmen, wenn der Konfigurator über 127.0.0.1 läuft;
  ohne Route ins Netz die Adresse des Fensters, mit Hinweis. Der Fuß
  (`gvStandZeichnen()`) wartet auf ein neues Gerät: dieselbe Quelle wie das
  Banner (`neueGeraete()`, gemerkt in `NEU_LETZTE`), „Weiter mit Einrichten“
  schließt den Bogen und setzt den Fokus ins Namensfeld des Banners. Der
  frühere Block „Neues Gerät verbinden“ (Start-URL-Generator mit Gerätename
  und Startansicht, SSH-Befehl mit `PANEL`/`AGENT_NAME`, `#wzHeim`) ist weg.
  `tests/browser/test_geraet_verbinden_browser.py`.
- **Skalierung, Zielkachel und Nacht nur am Gerät** (seit 15.10.2026,
  Einrichtung neu Schritt 4b): Die Felder Skalierung (Vorgaben → Darstellung,
  Ansicht → Raster), Zielkachel (Ansicht → Raster) und Nacht (Ansicht →
  Verhalten: Abdunkeln, Aufhellen, Nacht-Uhr) sind weg; der eine Ort ist die
  Gerätekarte (Technik: Skalierung, Zielkachel; Display: Nachts abdunkeln,
  Aufhellen bei Berührung, `devices[name].nightDim`/`nightWake`,
  `panel_night(pid, roh, dev)`). Die Nacht-Uhr und der Nacht-Auslöser bleiben
  allein in den Vorgaben. Der Server rechnet weiter Gerät vor Ansicht vor
  Vorgaben, ein gespeicherter Wert in Ansicht oder Vorgaben gilt also weiter:
  `altEintragHtml()` nennt ihn im Reiter als „älterer Eintrag“ mit „Eintrag
  entfernen“ (`ALT_NAMEN`), `wasGiltInAnsicht()` sagt es als Herkunft auf der
  Gerätekarte (`geraetGilt()`), und die Vorgaben zählen Geräte mit eigenem Wert
  auf (`GERAET_SCHLUESSEL`, `erbtZeichnen()`). Das Automatisch-Raster rechnet ohne Wert
  mit `KACHEL_ZIEL_STANDARD`; `test_automatisch_im_konfigurator` setzt die
  Zielkachel am Gerät. `tests/test_display_geraet.py` (Nacht).
- **Löschen gilt sofort.** „Ansicht löschen“ schickt nach der Rückfrage den zuletzt
  gespeicherten Stand (`GESPEICHERT`) ohne die Ansicht, „Entfernen“ unter Geräte
  bei offenen Eingaben ebenso `GER_GESPEICHERT` ohne das Gerät. Offene Änderungen an
  anderen gehen dabei nicht nebenbei mit, sie bleiben in der Leiste.
- Virtuelles Profil `__global__` landet in `theme.json` statt `panels.json`.
  Die Skalierung dort hat keine Erb-Option („Aus" ist das Fehlen des Keys),
  die Ansicht bietet „Wie Vorgabe (…)" mit dem geerbten Wert in Klammern, das
  Gerät „Wie in der Ansicht".
- Kachelliste auf 400 Einträge begrenzt.
- Freie Auswahl: bis zu vier Seiten je Panel (`pickTabs`, Tabs `auswahl` bis
  `auswahl4`), je Seite Name, Icon und Inhalt (Kacheln in Klickreihenfolge
  oder ein Widget). Als Icon gilt nur, was die Icon-Auswahl schreibt
  (`/icon?p=…`, `/loxlib?n=…`) oder ein relativer Loxone-Pfad, den der Server
  über `/icon` holt (`_clean_seiten_icon()`, beim Speichern und in
  `_pick_tabs()` auch für ältere Dateien). Eine fremde Adresse wie
  `//host/x.png` lud die Visu früher vom fremden Host. `/api/meta` muss `pickTabs` mitliefern: Fehlt es, kennt der
  Editor nach dem Neuladen nur eine Seite und kürzt beim nächsten Speichern
  die Leiste (so geschehen vor #47). Geprüft über Speichern, Neuladen,
  Weiterbearbeiten und die Visu in `tests/browser/test_auswahl_seiten_browser.py`.
  Seit Punkt 10 (09.10.2026) trägt eine Seite dazu `layout` `[{id, w, h}]`
  (Reihenfolge und Größe 1 × 1, 2 × 1, 2 × 2; `_seiten_layout()`) und `byRoom`
  (Standard an: die Visu gruppiert nach Raum und zeigt Sprungmarken; aus:
  genau die Reihenfolge der Seite). `picks` bestimmt, was auf der Seite steht,
  das Layout Reihenfolge und Größe (`_layout_mit_picks()`): Einträge, die
  nicht mehr in `picks` stehen, fallen weg, Bausteine ohne Eintrag kommen
  hinten an. So bleibt eine Seite stimmig, wenn nur `picks` geändert wird
  (Bausteinliste, Raumtausch beim Duplizieren). Geprüft in
  `tests/test_seiten_layout.py`.
- Seiten-Editor am Tablet (10.10.2026): Palette und Fläche müssen zugleich im
  Bild sein, sonst geht das Ziehen nicht. `.se-spalten` ist ein Raster, die
  Palette (`.se-pal`) eine eigene Scrollfläche, die beim Scrollen der Seite
  neben der Fläche stehen bleibt (`position: sticky`). Eine Container-Abfrage auf
  `.se-host` ordnet nach der Breite des Editors: breit drei Spalten, bis 900 px
  steht „Ausgewählt“ unter der Fläche (nie unter der Palette), bis 640 px alles
  untereinander und die Palette unten angedockt. Geprüft in
  `tests/browser/test_tablet_rueckmeldung_browser.py`.
- Seiten-Editor (Punkt 10, Teil 2, 09.10.2026): eigener Reiter im
  Panel-Editor und Schritt 5 des Assistenten für eine freie Seite mit
  Kacheln. Links die Palette (oben die Widgets für Pane 2 und die Kopfzeile,
  darunter alle Bausteine mit Raumfilter und Suche, abgeblendet, was schon auf
  der Seite steht), in der Mitte die Arbeitsfläche in Geräteform,
  rechts „Ausgewählt“ mit Größe 1 × 1, 2 × 1, 2 × 2, „nach vorn“, „nach
  hinten“, „Von der Seite nehmen“ und „Kachel gestalten“. Die Fläche zeigt,
  was die Visu am gewählten Gerät baut (Geräte mit gemeldeter Größe,
  dieser Browser, Katalog; vorgewählt das Zielgerät des Profils): dieselbe
  Folge wie der Server (`seAnsicht()`: ohne ausgeblendete, auf einer Seite
  mit Werteleiste ohne die Anzeige-Bausteine aus `werteLeiste` in
  `/api/meta`, mit `byRoom` nach Raum gruppiert), dasselbe Raster aus
  `raster.js` mit den Kacheln der Seite (`seRaster()`: Automatik mit
  Zielkachel des Geräts vor der des Profils, Widget nur mit Split, Kopfzeile
  und Werteleiste nehmen Höhe; fest mit Verdopplung durch den Split) und
  dieselbe Lage (`rasterLage()`), die Flächen in Prozent der Gerätegröße
  (`seGeometrie()`). Bedienung mit Pointer-Events: Kacheln der Fläche zieht
  man direkt, in der Palette nimmt der Finger den Griff, damit die Liste
  scrollbar bleibt; eine Marke zeigt genau die Zellen, die die Kachel an der
  Stelle belegen würde, zurück in die Palette gezogen verlässt sie die
  Seite, über dem Blätterknopf kurz verweilt wechselt die Seite. Ohne Ziehen:
  Kachel antippen, Pfeiltasten verschieben (links/rechts um eine Stelle,
  hoch/runter um eine Zeile), Entf nimmt sie von der Seite. Jede Änderung
  schreibt `picks` und `layout` zusammen (`seSchreiben()`); `profilMitRaumtausch()`
  hält das Layout stimmig, ohne Gruppierung gibt es keine Sprungmarken.
  Über der Fläche steht im Panel-Editor der Bereich „Seite“ (`seEigenHtml()`,
  09.10.2026): Name, Seiteninhalt (Kacheln oder ein Widget über die ganze
  Fläche samt Musikzone, Baustein oder gestapelten Werten) und das Icon aus
  der Bibliothek, die sich erst beim Aufklappen füllt. `seZeichnen()` schreibt
  den Bereich nicht neu, damit das Namensfeld beim Tippen den Fokus und die
  Icon-Suche ihren Text behält; die Seitenleiste darüber legt Seiten an und
  entfernt sie. Unter Tabs bleiben die Wahl der Leiste, die Seiten und „Tipp
  auf eine Sprungmarke“; je Seite steht dort nur eine Kurzfassung
  (`pickKurzHtml()`: Icon, Name, wie viele Bausteine aus wie vielen Räumen
  oder welches Widget, die Sprungmarken) mit „Im Seiten-Editor bearbeiten“.
  Ist die Kopfzeile gewählt, stehen ihre Werte (die Badges neben Uhr und
  Wetter) unter den Widgets der Palette (`seKopfWerteHtml()`) (`ui.panes[tab]` =
  `header:<uuid>,…`); das Band auf der Fläche nennt sie. Unter der Fläche steht
  die Zeile „Widget, Kopfzeile, Werteleiste dieser Seite“ (`sePaneZeichnen()`,
  dieselbe `paneListe()` wie unter Inhalt): Widget daneben samt Wahl (Zone,
  Kamera, Bausteine) und Werteleiste; die Kopfzeilen-Werte lässt sie weg, die
  stehen schon auf der Fläche.
  „Vorschau“ in der Speicherleiste (Punkt 10, Teil 3) zeigt das Profil mit
  allen ungespeicherten Änderungen in der echten Visu: `entwurfOeffnen()` schickt
  es an `POST /api/entwurf` und öffnet `/?panel=<id>&entwurf=<token>` in einem
  Fenster in der Größe des Vorschaugeräts. Der Server hält den Entwurf nur im
  Speicher (`App.entwurf_ablegen()`: `_sanitize_panels()` wie beim Speichern,
  höchstens `ENTWURF_MAX` = 8, `ENTWURF_DAUER` = 1 h nach der letzten Nutzung,
  `panels.json` bleibt unberührt); `ws_handler` setzt ihn bei `?entwurf=` an die
  Stelle des gespeicherten Profils (`resolve_profile(pid, entwurf)`, die
  Nachschlager nach Profil-Kennung lesen dann `prof["roh"]`) und meldet
  `entwurf` in der `theme`-Nachricht: die Visu kennzeichnet ihn mit einem
  schwebenden Etikett (`#entwurfMarke`, nimmt keinen Platz), ein Token, der nichts
  mehr trifft, zeigt das gespeicherte Profil mit rotem Etikett. Jede Änderung im
  Editor zieht über denselben Token nach (`entwurfNachziehen()`, 600 ms Verzug,
  `api_entwurf` lässt die Fenster mit diesem Entwurf neu laden). Speichern
  verwirft alle Entwürfe; Fenster mit einem Entwurf bekommen dabei
  `{t:"entwurfEnde"}` und laden das gespeicherte Profil (ein bloßes
  `reload` ließe sie auf der Entwurfs-Adresse, und eine Umleitung durch den
  Konfigurator liefe gegen das Neuladen). Eine Antwort von `/api/entwurf`, die erst
  nach dem Speichern eintrifft (die 600 ms waren schon abgelaufen), verwirft der
  Konfigurator über eine Zählung (`ENTWURF.gen`, beim Start des Speicherns
  erhöht) und lenkt das Fenster nicht zurück. Ein Entwurf geht der
  Geräte-Zuordnung vor (Agent-Wunsch, Betriebsmodus): ein Vorschau-Fenster erbt
  die Gerätekennung aus dem `localStorage` (derselbe Ursprung) und würde sonst auf
  ein fremdes Profil umgelenkt. Geprüft in `tests/test_entwurf.py` und
  `tests/browser/test_entwurf_browser.py`.
  Vorschau am Gerät (Punkt 12): „Am Gerät ansehen“ (Speicherleiste, Ziel ist das
  Vorschaugerät des Seiten-Editors, sonst das Zielgerät des Profils; auch für eine
  neu angelegte, noch ungespeicherte Ansicht) schickt den Entwurf an das Gerät: `POST /api/device/switch` mit `entwurf`, als `{t:"switch",
  panel, entwurf}` nur an die verbundenen Visus des Geräts. Ein Agent ohne offene
  Visu kann den Token nicht in die Kiosk-URL tragen, dort meldet der Server
  „Keine verbundene Visu“. Der Server merkt sich je Gerät, was es vorher zeigte
  (`App.vorschau_geraet`: Token, Profil, `zurueck`, `bis`; bei einer weiteren
  Vorschau bleibt `zurueck`). Zurück zur vorigen Ansicht (`{t:"switch"}` ohne
  Entwurf, nur an Verbindungen, die den Entwurf noch zeigen) geht es auf
  `POST /api/vorschau/beenden`, nach `VORSCHAU_GERAET_DAUER` = 15 min ohne
  Auffrischen (der Takt prüft; jede Änderung im Editor frischt über
  `api_entwurf` auf und lädt das Gerät neu) und beim Schließen des Assistenten ohne
  Anlegen. Speichern, ein Betriebsmodus oder eine ausdrückliche Wahl unter
  Displays beenden sie ebenfalls (Speichern: das Gerät zeigt das gespeicherte
  Profil, `entwurfEnde`). Ein Betriebsmodus schaltet auch dann um, wenn er auf das
  Profil des Entwurfs zeigt: dieselbe Kennung ist nicht das gespeicherte Profil.
  Endet die Vorschau, während das Gerät noch zum Entwurf umlädt (die alte Seite
  trägt `entwurfKommt`, eine Verbindung mit dem Entwurf gibt es noch nicht), merkt
  sich der Server das Ende in `App.vorschau_ende`; `ws_handler` schickt die neue
  Verbindung einmal zurück, höchstens `VORSCHAU_UNTERWEGS` = 30 s lang und nur für
  dieses Gerät und diesen Token. Die Visu nimmt bei jedem `switch` den `?entwurf=` aus der
  Adresse, sonst setzt sie ihn. `/api/devices` nennt je Gerät `vorschau` `{id, bis}`;
  der Konfigurator gleicht den Knopf damit ab. Die Zielkachel, die der Assistent am
  Gerät merken will, gilt erst beim Anlegen: die Vorschau rechnet mit der
  bisherigen. Geprüft in `tests/test_vorschau_geraet.py` und
  `tests/browser/test_vorschau_geraet_browser.py`.
  Geprüft in `tests/browser/test_seiten_editor_browser.py`: Fläche gleich der
  Visu in neun Fällen (Widget quer und hochkant, Kopfzeile mit Werteleiste,
  fest 3 × 3, 4″ mit 2 × 2, Automatik ohne Gruppierung), Ziehen, Tasten,
  Größe und Speichern ohne Verworfenes, Finger nur am Griff, Widgets, der
  Assistent, die Kurzfassung unter Inhalt und das Duplizieren; Name, Icon und
  Inhalt von vier Seiten über Speichern und Neuladen in
  `tests/browser/test_auswahl_seiten_browser.py`.
- Panel duplizieren mit Raumtausch (Punkt 14, 08.10.2026): „Duplizieren“ in
  der Speicherleiste öffnet einen Dialog (`dupOpen()`), der ID und Titel aus
  dem Zielraum vorschlägt (`idAusName()`: klein, Umlaute ausgeschrieben,
  frei oder mit `-2`; der Titel ersetzt den Namen des Quellraums). Die Kopie
  (`profilMitRaumtausch()`) ersetzt jeden Baustein aus dem Quellraum
  (`profilRaum()`: `room:`-Tab, sonst Raum-Liste, sonst der Raum der meisten
  gewählten Bausteine, der feste Player zählt mit) durch den gleichnamigen aus dem Zielraum, gleicher Typ
  vor gleichem Namen: in `tabs` und `ui.valueBar` (`room:`), `rooms`, `hide`,
  `picks`/`pickTabs[].picks` und `.widget`, den Schlüsseln von `tiles`,
  `ui.panes` (`paneTausch()`: `player:`, `energy:`, `camera:` samt Werten,
  `chart:`/`status:`/`header:`-Listen), `ui.svPane` und `ui.player`. Wer im
  Zielraum kein Gegenstück hat, fällt weg und wird im Dialog und nach dem
  Anlegen genannt; Bausteine anderer Räume und ohne Raum bleiben. War der
  Zielraum schon im Profil, fallen die Dubletten des Tauschs weg (ein
  `room:`-Tab, jeder Baustein einmal; bei `ui.panes` gewinnt die getauschte
  Seite). Ohne Zielraum entsteht eine reine Kopie („… (Kopie)“). Alles im Konfigurator,
  der Server bekommt das neue Profil erst beim Speichern. Geprüft in
  `tests/browser/test_duplizieren_browser.py`.
- Raumvorschlag aus dem Gerätenamen (seit Punkt 13, 09.10.2026; seit 15.10.2026
  in „Gerät einrichten“): `raumZumGeraet()` nimmt den Raum, dessen Name den
  Gerätenamen enthält oder darin steckt, bei mehreren den mit der nächsten
  Namenslänge (der gleiche Name immer, sonst etwa `badezimmer-oben` → Badezimmer
  vor Bad), `geRaumVorschlag()` setzt ihn als Raum, Zielraum und Namen.
  Geprüft in `tests/browser/test_geraet_einrichten_browser.py`. Die frühere
  Vorrechnung je Gerät (`wzVorrechnung()`, Katalog des Servers
  `GERAETE_KATALOG`, `/api/meta` `geraeteKatalog`) lebt im Seiten-Editor weiter:
  `seRaster()` rechnet mit derselben `raster.js` und denselben Maßen wie die
  Visu, der Katalog steht dort als Vorschaugerät. Dass Maße und Raster auf fünf
  Standardgeräten in vier Profilen gleich der Visu sind, prüft
  `tests/browser/test_raster_am_geraet_browser.py`, dazu die Zielkachel am
  Gerät; den Ablauf bis zum umgeschalteten Gerät `test_geraet_einrichten_browser.py`.
  Eine Verbindung, die gerade `{t:"reload"}` bekam (`App._neu_laden()`), zählt
  `_push()` nicht mehr: das Umschalten ginge mit der alten Seite verloren,
  erreicht wird erst die neue Verbindung (`tests/test_umschalten_nach_neuladen.py`).
- Gerät eines Profils (`device`, Punkt 15, 08.10.2026; seit 15.10.2026 ohne
  Feld und Warnung): „Gerät einrichten“ schreibt
  `device` mit Name und der zuletzt gemeldeten Größe des Geräts
  (`DEVICE_SCREENS`, `_clean_zielgeraet()` im Server, dieselbe Obergrenze
  `BILDSCHIRM_PX_MAX` wie die Bildschirmmeldung in `_clean_screen()`). Der
  Seiten-Editor und „Am Gerät ansehen“ nehmen es als Vorschaugerät
  (`seGeraetReiter()`). Welche Ansicht ein Gerät zeigt, sagt seit der
  Einrichtung neu allein die Zuordnung (`devices[name].panel`, Schritt 2):
  das Feld „Zielgerät“ im Reiter Allgemein und die Warnung „Ansicht ist für …
  gemacht“ unter Geräte sind weg. Geprüft in `tests/test_zielgeraet.py`.
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
  löschen geht nur über ein anderes Ziel. „Entfernen“ (09.10.2026,
  `devEntfernen()`) steht nur an Geräten mit gespeicherten Einstellungen
  (`configured` in `/api/devices`): Nach einer Rückfrage fallen sie aus der
  Arbeitskopie, gespeichert wird sofort die ganze Liste wie mit „Speichern“.
  Ein Gerät ohne Einstellungen verschwindet von selbst, sobald es nicht mehr
  verbunden ist; ein verbundenes kommt nach dem Entfernen ohne Einstellungen
  wieder, das sagt die Rückfrage vorher. Ohne Geräte fällt `devices` aus
  `panels.json`. Die Ansicht je Gerät ist das Profil, das die Visu wirklich
  zeigt: Fragt sie nach einem unbekannten (gelöscht, vertippt), nennt
  `resolve_profile()` es `default`, wie das Standardprofil, das sie bekommt;
  nur ein Entwurf behält seinen Namen (`tests/test_profil_geloescht.py`). Geprüft in `tests/browser/test_displays_browser.py` und
  `tests/test_geraete_kennwort.py`.
- Textfelder brauchen `type="text"`: Der dunkle Feldstil hängt an
  `input[type=text|number|password]`, ein Feld ohne `type` steht sonst
  browserweiß im dunklen Konfigurator.
- Eigene Icon-Map `BICONS` (20 Icons, `fan` und `list` fehlen gegenüber der Visu).
- Overlay-Vorschau rechnet die Alphas selbst nach (`ovPreview()`), parallel zur
  Server-Logik `_overlay_alphas()`.

### 7.3 Rubrik „Einstellungen" in `config.html` (früher `settings.html`)

Die frühere Einstellungsseite liegt als zweite Rubrik im Konfigurator; die
Speicherleiste unten gilt für alle Rubriken (§7.2). Sechs Reiter:
Miniserver (mit Link auf `/api/types`), Kamera/Türstation, SIP (Zugang je
Intercom aus dem Miniserver, „Verbindung prüfen“; lädt erst beim Öffnen,
`loadSip()`), Audio (Testton, Audioserver-Live-Daten), Kalender & Wetter
(iCal-Abos, Wetter der Uhr-Seite), Sicherung (Herunterladen und Einspielen).
Die Anzeigegeräte stehen in der eigenen Rubrik „Geräte", dort auch „Gerät
verbinden“ (Bogen mit drei Wegen, `data-goto="verbinden"` aus der Übersicht). Zu einem Reiter führen
die Kacheln der Übersicht (`data-goto="settings:<reiter>"`) oder die
Reiterleiste; einen Anker in der URL (`/config#panels`) wertet die Seite nicht
aus, sie öffnet die Übersicht (ohne Struktur Einstellungen → Miniserver, siehe
unten). Ungespeichertes nennt die Speicherleiste; Neuladen oder Schließen der Seite fragt nach.

**Ersteinrichtung.** Solange der Server keine Struktur vom Miniserver hat
(`einrichtung` aus `/api/settings`), führt der Konfigurator zuerst zum Zugang:

- Er öffnet Einstellungen → Miniserver mit einem Hinweis samt Stand: noch kein
  Zugang, gespeicherter Zugang nicht verbunden, Verbindung wird aufgebaut,
  Fehler des Servers oder des eigenen letzten Versuchs.
- Gesperrt sind die übrigen Rubriken, die Liste der Ansichten, „＋ Neue Ansicht" und
  die Reiter der Einstellungen außer Miniserver und Sicherung (`EINR_SUBS`): Ansichten,
  Vorgaben, Geräte und der Assistent brauchen Räume und Bausteine. `setRubric()` leitet
  jeden anderen Weg zu den Einstellungen um, `showSub()` und `geOpen()` lehnen ab.
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

### 7.5 `raster.js`

Gemeinsame Rasterrechnung, ausgeliefert unter `/raster.js` (`raster_js`),
geladen von `panel.html` und `config.html` (Punkt 9, 09.10.2026). Reine
Rechnung ohne DOM unter `window.LoxRaster`: `kachelFaktorFuer()`
(Kachelfaktor, `KACHEL_REF` usw.), `quadratisch()`, `groesse()` und
`rasterLage()` (Lage der Kacheln mit Zeile und Spalte: breite belegen zwei
Spalten, hohe zwei Zeilen derselben Seite), `festesRaster()` (Profilraster
samt Verdopplung durch den Split) und `autoRaster()` (Spalten und Zeilen aus
Fläche und Zielkachel, Widget-Spalten, Wachsen und Schrumpfen, zweiter
Durchgang mit Seitenpunkten). Die Visu misst Fläche, Abstand, Innenrand,
Seitenpunkte, Tab-Leiste, Kopfzeile und Werteleiste und übergibt sie; ihre
Funktionen gleichen Namens reichen nur weiter. Der Assistent rechnet ein
Gerät mit `VISU_MASSE` vor (Abstand 10, Innenrand 10, Seitenpunkte 14,
Tab-Leiste 55 px: 2 × 13 Innenabstand, 28 Symbol, 1 Linie); ein Raum-Panel
mit Sprungmarken ohne Bild hat eine niedrigere Tab-Leiste, dort ist die
Vorrechnung eine Näherung. `test_vorrechnung_wie_die_visu` vergleicht die
gemessenen Maße mit `VISU_MASSE` und das vorgerechnete mit dem gebauten
Raster. Ein Kachel-Set bringt eigene Maße mit (§5.4): `SCHMAL_UNTER` (600 px)
entscheidet für Visu und Konfigurator, ob die Maße mit `-schmal` gelten,
`setMass()` liest eines aus den Maßen in `/api/meta`, `leisteMass()` dasselbe
für die Maße der Tab-Leiste (`LEISTE_MASSE`), die auch nach der Höhe gehen
(`leisteSchmal()`). Der Konfigurator
(`leisteMasse()`) rechnet damit Leistenhöhe, Seitenleiste (`railW`, nimmt
Breite statt Höhe), Rahmen (`rahmenX`, `rahmenY`), Abstand und Innenrand vor;
`autoRaster()` zieht Seitenleiste und Rahmen von der Fläche ab, die Visu misst
sie am Kasten.

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
Server, dass er das kann. Seit der Einrichtung neu (Schritt 2) nennt die
Antwort `panel` auch ohne offene Wahl, sobald der Agent etwas anderes meldet
als die Ansicht, die dem Gerät zusteht (`ansicht_fuer_geraet()`: laufender
Betriebsmodus, sonst die Zuordnung `devices[name].panel`): Ein Panel, das mit
altem `PANEL` in der kiosk.conf neu startet, landet so wieder auf seiner
Ansicht. Die Zuordnung hängt am Namen; zwei geklonte Panels mit demselben
Hostnamen zeigen deshalb dasselbe und brauchen verschiedene `AGENT_NAME`.

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
`PROFILE_DIR` und `BL_DEVICE`. Pflicht ist nur `SERVER`: `PANEL` ist die
Startansicht, bis der Server dem Gerät eine Ansicht zuordnet (Konfigurator,
Geräte), und `DPMS_OFF` gilt nur, solange der Server keinen Wert schickt
(Vorgaben oder Gerät, `panel_dpms()`); der Installer schreibt beide nur, wenn
sie gesetzt sind (seit 15.10.2026, Einrichtung neu Schritt 4).

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
Neu laden, Display aus/an). Browser ohne Namen werden mit ihrem
Kopplungscode gelistet (Nachricht `kopplung`, §3.2): Das Panel zeigt ihn unter
„Dieses Gerät einrichten“ (nur ohne `?panel=` in der Adresse; mit `?panel=`
behält es den Code, zeigt aber keine Karte über der Visu), und „Namen
vergeben“ neben dem Code trifft genau dieses Gerät, auch
bei mehreren hinter einer IP. Der Konfigurator wartet nicht, bis jemand unter
Geräte nachsieht: `neuBannerZeichnen()` meldet ein Gerät ohne Namen und ein
frisch verbundenes ohne Zuordnung, das die Standardansicht zeigt, oben in
jeder Rubrik als Banner „Neues Gerät gefunden“ mit Klasse (`geraeteKlasse()`:
480×480 = 4″-Wandpanel, groß = Display, sonst Tablet), Größe und Code.
„Benennen und einrichten“ vergibt den Namen und öffnet „Gerät einrichten“ mit
dem Gerät, sobald es damit zurück ist; „Später“ merkt sich das Gerät im Browser
(`lp_neu_weg`). Die Visu
meldet ihre Kiosk-App in der WebSocket-URL,
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

**Server der App (Schritt 6 des Umbaus):** Beim ersten Start fragt die App
(`ServerActivity`), wo der Server läuft, bevor die Anzeige etwas lädt: *auf
diesem Gerät* (eingebetteter Server wie bisher) oder *im Netz* (`host[:port]`,
ohne Port 8099; die Zeile aus „Gerät verbinden“ darf samt `http://` hinein,
`Visu.serverEingabe`). „Weiter“ fragt `/api/health` des Servers
(`ServerPruefung`: JSON mit `version`, 200 oder 503 ist ein LoxPanel-Server),
bei Fehlschlag steht der Grund da und „Trotzdem übernehmen“. Die Wahl liegt in
den SharedPreferences `visu` (`server`, leer = dieses Gerät); `Visu.basis(ctx)`
ersetzt die feste Basis-Adresse, daran hängen Start-Adresse, gemerkte
Visu-Adresse (fällt beim Serverwechsel weg), die Herkunftsprüfung der
JS-Brücke und die Statusseite. Mit einem Server im Netz startet die App weder
Dienst noch Python noch Wächter (`ServerService.starten` prüft
`Visu.eigenerServer`); fällt er aus, zeigt die Anzeige eine eigene Fehlerseite
mit „Server ändern“ und lädt alle 2 s neu. Die App verhält sich dann wie Fully
Kiosk: Visu ohne Parameter, Kopplungscode, Banner im Konfigurator; die
Sprechfunktionen fehlen dann in `LoxKiosk`, weil der Gesprächsdienst
(`IntercomCallClient`, Prozess-Token) zum eingebetteten Server gehört. Später
erreichbar ist die Einrichtung mit einem langen Druck auf der Uhr-Seite
(`KioskActivity.LANGER_DRUCK_MS`, 3 s; das Wecken nach 120 ms bleibt) und über
die Fehlerseite. Ein Wechsel vom eigenen Server weg startet den Prozess neu,
weil sich der eingebettete Server nicht beenden lässt. Installationen von vor
dieser Einstellung (ausgerolltes `loxpanel/config` in `filesDir`) gelten als
„dieses Gerät“ und fragen nicht. Unit-Tests: `VisuTest`,
`ServerPruefungTest`.

**Stabilität der App:** Der Server-Dienst (`ServerService`, nur mit dem Server
auf diesem Gerät) startet den Server je Prozess einmal (Anzeige, BootReceiver
und Android starten den Dienst mehrfach), den Wächter je Dienst. Der Wächter fragt `/api/health` alle 30 s. Nach drei Fehlschlägen in
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
up), `stop` (Marker-Datei `loxpanel_stopped.cfg` + down), `restart`, `check`
(Cron alle 5 min), `boot` (Daemon beim Start des LoxBerry: wie `check`, löscht
vorher die Marker-Datei, „Stoppen“ hält also nur bis zum nächsten Neustart),
`backup` und `restore` (tar.gz des Config-Ordners, erzeugt im Container als
root, Rotation nach `KEEP` im Skript, das Widget fragt die Zahl über
`loxpanel-ctl.sh keep` ab), `port` und `zustand`.

Port am LoxBerry: `PORT=` in `loxpanel_plugin.cfg` im Config-Ordner des
Plugins, ohne Datei oder bei einem ungültigen Eintrag `PORT_STANDARD` (8099,
derselbe wie `LOXPANEL_PORT` im Container). `port` gibt ihn aus, `port <port>`
prüft ihn (1–65535, nicht belegt), schreibt die Datei und fährt ein laufendes
LoxPanel damit neu hoch (`up -d` ohne pull legt den Container neu an). `start`
schreibt `docker-compose.port.env` (`LOXPANEL_LB_PORT`) und ruft Compose mit
`--env-file`; über `sudo` käme eine Umgebungsvariable nicht an. Die
Compose-Datei hat `${LOXPANEL_LB_PORT:-8099}:8099`. Vor dem Hochfahren prüft
`start`, ob jemand anderes als LoxPanel den Port hält (Verbindungsaufbau über
`/dev/tcp/127.0.0.1`, wer: `docker ps --filter publish=`), und startet dann
nicht erst: Docker scheiterte erst nach dem Anlegen, und das Widget erreichte
unter dem Port das andere Programm. `start`, `restart`, `check` und `boot`
enden dann mit 1. `zustand` meldet dem Widget `port`, `laeuft`, `gestoppt`
(seit wann, aus dem Zeitstempel der Marker-Datei) und `belegt`.
`preroot.sh`/`postroot.sh` nehmen `loxpanel_plugin.cfg` über ein Update mit
(`/tmp/loxpanel-upgrade-plugin.cfg`); scheitert der Start danach, meldet
`postroot.sh` es als `<WARNING>`.

Das Widget `index.cgi` (Perl) fragt den Port bei `loxpanel-ctl.sh port` ab und
spricht `http://localhost:<port>/api/settings` und `/api/settings/miniserver`.
LoxPanel erkennt es an `/api/settings` mit `miniserver` und `version`;
antwortet dort etwas anderes, schickt es keinen Zugang und nennt im
Status-Feld den Grund aus `zustand`: Port belegt (von wem, wo umstellen),
gestoppt (seit wann, wie es wieder startet), Container läuft, antwortet aber
nicht, sonst „Container nicht erreichbar“. Von LoxPanel zeigt es `error` und
darunter `fehler`, `gespeichert` (nicht erreichbar, trotzdem gespeichert) als
Warnung. Eine Antwort mit JSON ist immer eine Meldung des Servers, auch mit 400
oder 500. Die Texte des Servers kodiert es vor der Ausgabe nach UTF-8:
`decode_json` liefert Zeichen, die Seite geht aber ohne Kodierungsschicht als
Bytes hinaus. „Aus LoxBerry übernehmen" ohne Benutzer in der
LoxBerry-Konfiguration meldet das selbst; bei „HTTPS bevorzugen“
(`PreferHttps`, als JSON-Wahrheitswert oder Text) nimmt es `PortHttps`, sonst
`Port` (`tests/test_loxberry_widget.py`, `tests/test_loxberry_port.py`).

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
- **Diagnose:** Die letzten Log-Zeilen hält außerdem ein Puffer im Speicher
  (`diagnose.LOG`, höchstens `LOG_ZEILEN`, davon die der letzten
  `LOG_MINUTEN`). Das Diagnosepaket (`/api/diagnose`, Konfigurator: je Gerät
  unter Geräte, für den Server unter Einstellungen → Sicherung) legt sie mit
  Version, Verbindungen, Geräten und Einstellungen in ein ZIP, oben in
  `diagnose.md` ein Satz je Verbindung. Die Route hat keine Anmeldung, darum
  ist es strenger als die Sicherung: Neben `pass` und `password` fallen
  `token`, `jwt` und `secret`, die Kalender-Abos behalten nur Schema und Host
  (ihr Pfad ist der Zugang), Benutzer:Kennwort in Adressen wird gestrichen
  und der Standort (`lat`/`lon`) entfernt. Jeder gefundene Wert, dazu Kennwort
  und Token aus dem Speicher, wird anschließend in allen Texten des Pakets
  geschwärzt, auch URL-kodiert (`diagnose.kodierungen()`), damit er nicht
  über das Log hinausgeht. `tests/test_diagnose.py` legt jede Art Geheimnis an
  und sucht sie in jeder Datei des Pakets.
- **Image:** `.dockerignore` hält Altlasten (`webfrontend/htmlauth`,
  `config/visu.*`, `daemon/` …) und Test-/Entwicklungsdateien aus dem Image.

### 9.3 Build und Release

| Workflow | Trigger | Ergebnis |
|---|---|---|
| `tests.yml` („Tests und Image“) | jeder PR, Push auf `main`, Tags `v*`, manuell | Syntax (alle `bin/*.py`, Workflows, Unraid-Vorlage), `ruff` mit Fehlerregeln (`F`, `E9`), pytest ohne Browser inkl. Rauchtest, Browser-Tests in Chromium (Screenshots als Artefakt), bei PRs Probe-Build des Images für amd64 ohne Push. Danach, nur auf `main` und bei Tags `v*` und nur, wenn beide Test-Jobs desselben Laufs grün sind, der Job `veroeffentlichen`: `ghcr.io/chief-wiggum1203/loxpanel` mit Tags `latest` (nur `main`), `v<tag>`, `sha-<kurz>`; Plattformen amd64, arm64, arm/v7. Ein eigenes `docker-image.yml` gibt es im Fork nicht mehr, es veröffentlichte neben den Tests her (`tests/test_workflows.py`) |
| `plugin-release.yml` | Tags `v*`, manuell | `loxpanel-plugin.zip` aus `loxberry-plugin/` am Release, dazu als Release-Notizen der Eintrag der Version im Changelog der README |
| `android-apk.yml` | Tags `v*`, manuell | `LoxPanel-Server.apk`, signiert mit dem festen Schlüssel aus den Secrets `LOXPANEL_KEYSTORE_B64`, `LOXPANEL_KEYSTORE_PASSWORD`, `LOXPANEL_KEY_ALIAS` und `LOXPANEL_KEY_PASSWORD`; ohne sie bricht der Lauf mit einem Hinweis ab, die übrigen Workflows hängen nicht daran |
| `deb.yml` | Tags `v*`, manuell | `loxpanel-server_<version>_all.deb` aus `packaging/deb/` am Release: Version aus `loxberry-plugin/plugin.cfg` (der Tag muss dazu passen), `bin/version.json` mit Version, Commit und Bauzeit im Paket, gepackt mit gzip, weil dpkg 1.20 (Debian 11) kein zstd kennt (`test_deb_paket` in `tests/test_version.py`) |

**Abhängigkeiten (Lieferkette).** Fremder Code kommt nur festgenagelt ins
Image. Bis Oktober 2026 zog jeder Bau die jeweils neueste Version: die
Python-Pakete über Mindestversionen in `requirements.txt`, das Grundimage über
das Etikett `3.12-slim`, die Actions über Etiketten wie `v4`. Eine manipulierte
Version, etwa von `loxone-api` (kleines Projekt, bekommt das
Miniserver-Kennwort zu sehen), wäre beim nächsten Push ungeprüft im Image
gelandet. Jetzt:

- `requirements-lock.txt` sperrt alle Pakete aus `requirements.txt` samt den
  mitgezogenen für Python 3.12, je Paket genau eine Version, jede Datei mit
  Prüfsumme (`pip-compile --generate-hashes`, der Befehl steht in ihrem Kopf).
  `Dockerfile` und die Test-Jobs in `tests.yml` installieren nur daraus, mit
  `--require-hashes`: Weicht eine Datei ab oder fehlt ein Paket, bricht der Bau
  ab. Die Tests laufen so mit denselben Versionen wie das Image.
- `requirements.txt` bleibt die Liste mit Bereichen. Danach installieren die
  App (Chaquopy hat eigene Android-Pakete, deren Prüfsummen nicht die von PyPI
  sind), das `.deb` und die Anleitungen ohne Docker, jeweils mit ihrem eigenen
  Python; eine Sperrliste für 3.12 passte dort nicht.
- Das Grundimage steht über die Prüfsumme seines Index (`FROM
  python:3.12-slim@sha256:…`, gilt für amd64, arm64 und arm/v7), jede Action
  über ihren Commit (`uses: …@<sha> # vX.Y.Z`).
- Neue Stände bringt Dependabot als Pull Request, monatlich und je Quelle
  gruppiert (`.github/dependabot.yml`); sie laufen durch dieselben Tests.
  Obergrenzen aus `requirements.txt` und die Python-Version des Grundimages
  schließt die Datei aus. Sicherheitsupdates kommen sofort, wenn sie in den
  Repo-Einstellungen an sind.

`tests/test_abhaengigkeiten.py` wacht darüber: Sperrliste vollständig fest mit
Prüfsummen und passend zu `requirements.txt`, dasselbe Python in Sperrliste,
Image und CI, Installation nur aus der Sperrliste, Actions auf Commits,
Dependabot für alle drei Quellen. Ablauf zum Ändern und Aktualisieren:
[`CONTRIBUTING.md`](CONTRIBUTING.md), Abschnitt „Abhängigkeiten“.

Welcher Stand läuft, steht in der Seitenleiste des Konfigurators und in
`/api/health` (`bin/version.json`, `bin/version_info.py`): Version aus
`loxberry-plugin/plugin.cfg`, Commit und Bauzeit. `tests.yml` reicht den
Commit als Build-Argument `LOXPANEL_COMMIT` herein, der APK-Build nimmt ihn aus
derselben Umgebungsvariablen oder aus Git und hängt ihn auch an den
`versionName` der App (App-Info in Android). Ohne Commit, etwa beim lokalen
`docker compose up -d --build` (die Compose-Datei reicht keinen herein, `.git`
fehlt im Image) oder aus einem entpackten Archiv, steht unter `inhalt` ein
Prüfwert über `bin/`, `webfrontend/`, `deploy/` und `agent/`
(`inhalt_kennung()`): Derselbe Code ergibt dieselbe Kennung, auch beim Neustart
oder erneuten Bauen; jede Änderung ergibt eine neue.

Nach einem Update laden offene Seiten von selbst neu. Sonst liefe in einem Tab,
der vor dem Update offen war, altes HTML und JavaScript gegen den neuen Server,
und auch die Versionszeile bliebe alt. Der Server nennt seinen Stand
(`server_stand()`, der Commit, ohne ihn die Kennung des Inhalts; nur wenn beides
fehlt leer, dann lädt nichts neu) in der
`theme`-Nachricht und in `/api/devices`. Die Visu merkt sich den Stand der ersten
Verbindung (`serverStandPruefen()`); meldet der Server nach dem Wiederverbinden
einen anderen, lädt sie einmal neu. Der Konfigurator prüft ihn bei jeder
Geräte-Abfrage (alle 6 s). Ohne offene Änderungen lädt er neu, mit offenen zeigt
die Speicherleiste „Neuer Stand auf dem Server“ (`#standNeu`, „Jetzt neu laden“)
und lädt nach dem Speichern neu. Tests: `tests/test_neuer_stand.py`,
`tests/browser/test_neuer_stand_browser.py`.

Ein App-Update braucht keinen Plugin-Bump, weil `:latest` rollend ist. Für ein
Release: `VERSION` in `loxberry-plugin/plugin.cfg` und
`loxberry-plugin/release.cfg` gemeinsam hochzählen (`test_versionen_gleich` in
`tests/test_version.py`). APK und `.deb` nehmen die Version beim Bauen aus
`plugin.cfg`, `packaging/deb/control` hat keine eigene. Dazu im
Changelog der README einen Eintrag `- **<version>** – …` anlegen, nach `main`
bringen und den Tag `v<version>` pushen. Ein Release in der GitHub-Oberfläche mit
neuem Tag `v<version>` tut dasselbe, weil es den Tag anlegt. APK, `.deb` und
Plugin-ZIP hängen sich von selbst an, der erste fertige Workflow legt das
Release an. Kein Workflow hängt an `release:`: Ein Release, das ein Workflow mit
`GITHUB_TOKEN` anlegt, löst bei GitHub keinen weiteren aus, und dann fehlte das
ZIP, auf das `ARCHIVEURL` zeigt (`tests/test_release.py`). Das Image
`v<version>` erscheint erst nach den Tests des Tags, also rund zehn Minuten
später. `NAME`, `FOLDER` und
`AUTHOR` nie ändern. Das GHCR-Package muss einmalig auf public stehen (bereits
erledigt).

---

## 10. Erweiterungs-Rezepte

### (a) Neuen Loxone-Bausteintyp unterstützen

1. Kachel: Funktion `@kachel("<Typ>")` mit `(app, uuid, c, it)` in der
   passenden Familie unter `bin/bausteine/` (oder einer neuen, die
   `bausteine/__init__.py` unten importiert). States lesen über
   `app._state(c, "<name>")`, Zahlen formatieren über `app._fmt_num()`, Texte
   über `app._text()`; `it` bekommt `icon`, `on`, `sublabel` und `nav`, `cmd`
   oder `controls`.
2. Detailseite: Funktion `@detail("<Typ>")` mit `(app, uuid, c, route)`, die
   die `view`-Nachricht liefert. Blöcke aus dem Vokabular in Abschnitt 3.7.
   Für reine Anzeigen reicht `app._big_view()` plus ein Eintrag in `STATUS_BIG` (`seiten.py`).
3. Den Typ in `tests/test_bausteine.py` bei seiner Familie eintragen; optional
   `SWITCHY` (`bausteine/gemeinsam.py`), `_ANALOG` (`seiten.py`), Flanken-Erkennung in
   `_apply_structure()` (`miniserver.py`).
4. Neues Icon: `ICONS` in `panel.html:273` und, falls im Konfigurator wählbar,
   `BICONS` in `config.html:191`.
5. Neuer Blocktyp: Zweig in `bh()` (`panel.html:486`), ggf. `updatePanel()` und CSS.

Das Frontend muss im Regelfall nicht angefasst werden.

### (b) Neuen API-Endpunkt

Handler als Modul-Funktion im passenden Modul unter `bin/routen/` (ein neues
Thema bekommt ein eigenes), `app: App = request.app["app"]` mit `App` nur
unter `TYPE_CHECKING` importiert, Registrierung in `main()` (`webvisu.py`)
samt Import oben. Für JSON-Body das Muster
`try: await request.json() except (ValueError, aiohttp.ContentTypeError)`,
für GET+POST `_json_or_empty()` und `_push_filter()`, für Pushes `_push()`
(alle drei aus `routen/gemeinsam.py`).

### (c) Neue Einstellung in `loxpanel.cfg`

Leser nach dem Muster `_audio_config()` (`konfig.py`), Feld in `App.__init__`, bei
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
   auch in `_panel_export()` (`ansicht.py`), sonst geht sie beim nächsten Speichern verloren.
4. Wirkung: CSS-Variable in `_theme_vars()` oder Verhalten in
   `resolve_profile()` (beide `ansicht.py`) plus `theme`-Payload plus Frontend.
5. Übersetzung in `i18n.js`.

### (e) Neue Sprache oder neuer Text

Sprache: Code in `LANGS` (`i18n.js:11`), Block in `CAT`. Text: `data-i18n` im
Markup oder `T('Deutscher Text')` im JS, den deutschen Text zeichengenau als
Schlüssel in jeden Sprachblock. Panel-Texte sind davon nicht erfasst, die stehen
hart im Server.

### (f) Design

Ein neues Kachel-Set ist ein Eintrag in `theme_colors.KACHEL_SETS` mit einer
vorhandenen Art (`aufbau`, `leiste`); Auswahl, Speichern, Kontrasttest und
Browser-Test nehmen es von dort. Eine neue Art braucht Regeln in `panel.html`
an `html[data-kachelset-aufbau|-leiste]` und eine Zeile in `_paare()` von
`tests/test_kachel_set.py`.

Visu statisch in `panel.html:8-256`, zur Laufzeit über CSS-Variablen mit
Defaults in `_theme_vars()`. Admin-CSS liegt seit der Zusammenlegung nur noch in
`config.html`.

---

## 11. Bekannte Schwachstellen

### Fehler

| Nr. | Befund | Stelle |
|---|---|---|
| F1 | Routen `/gicon` und `/uicon` werden erzeugt, aber nie registriert — behoben, die Quellen `google` und `custom` sind entfernt (§4, Kachel-Icons) | `seiten.py` `_apply_tile_style()` |
| F2 | `op_modes` fehlt in `App.__init__` — behoben, `/api/types` warf ohne Miniserver einen `AttributeError` | `:394`, Workaround `:1235` |
| F3 | Push-Stellen fangen nur `ConnectionError`. Ein `RuntimeError` beim Senden würde den Broadcaster-Task beenden, alle Panels blieben stumm, ohne Log — behoben, alle Push-Stellen senden über `_send_or_drop()` (jeder Fehler, 5 s Zeitlimit) | `:2452-2467`, `:2797` |
| F4 | `icon_cache` unbegrenzt, kein Limit, keine TTL — behoben, `ICON_CACHE_MAX` | `:359`, `:1139` |
| F5 | Kein atomares Schreiben der drei Config-Dateien (kein tmp+rename) | `:84`, `:1020`, `:1119` |
| F6 | `_write_cfg` und die Settings-Handler fangen `OSError` nicht | `:83`, `:2653`, `:2685` |
| F7 | `reconnect()` greift mit `ms["user"]` direkt zu, unvollständige cfg → `KeyError` | `:443` |
| F8 | `fetch_icon` hat kein Timeout und fängt `asyncio.TimeoutError` nicht — behoben, ebenso `fetch_cover` (`COVER_TIMEOUT`) | `:1123` |
| F9 | `JSON.parse` im WebSocket-Handler ohne try/catch — behoben | `panel.html:701` |
| F10 | `esc()` in der Visu escapt keine Anführungszeichen, Ausgabe landet in Attributen. Freitext-Schriftarten und Miniserver-Namen mit `"` zerlegen das Markup | `panel.html:316`, `:631`, `:637` |
| F11 | Panel-`states`-Farben werden nicht validiert und landen direkt in `setProperty` — behoben, `_sanitize_panels()` nimmt nur, was `_color_ok()` besteht, und meldet den Rest als verworfen | `konfig.py` `_sanitize_panels()`, `ansicht.py` `resolve_profile()` |
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
| S8 | Python-Pakete, Grundimage und GitHub Actions kamen bei jedem Bau in der jeweils neuesten Version, ungeprüft ins Image — behoben: Sperrliste mit Prüfsummen, Grundimage und Actions über Prüfsumme bzw. Commit, neue Stände als Pull Request von Dependabot (§9.3). |

### Performance

- P1: Vollrendering jeder offenen Ansicht bei jeder State-Änderung, alle 0,3 s,
  inklusive JSON-Parsing von `moodList`, `entryList`, `sourceList` in jedem
  Durchlauf (Abschnitt 3.5) — behoben: Eine Verbindung rendert nur, wenn ihre
  Seite einen geänderten State liest (Lesespur), und JSON-States werden je
  Text einmal geparst (§3.5).
- P2: `panels.json` wird bei jedem Zugriff zweimal geöffnet (`load_panels`,
  `load_devices`) — behoben, `load_panels_doc()` liest einmal.
- P3: Ring- und Alarm-Pushes gehen an alle Verbindungen ohne Panel-Filter —
  behoben: die Klingel an alle außer bei ausgeblendeter Türsprechanlage, der
  Wecker nur, wo die Ansicht ihn zeigt (Nachrichtenprotokoll §3.6).

### Wartbarkeit

- W1: ~~`_control_item()` und `_view_control_inner()` sind zusammen rund 850 Zeilen
  `if/elif`-Kette, Reihenfolge semantisch relevant.~~ Erledigt 15.10.2026:
  Tabellen je Typ in `bin/bausteine/` (§6).
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
4. ~~**Delta-Rendering oder Drosselung** (P1). Mindestens: pro Verbindung das
   letzte gesendete JSON merken und nur senden, wenn es sich geändert hat. Das
   allein spart bei laufenden Werten einen Großteil der WebSocket-Last.~~
   Erledigt: nur senden, was sich geändert hat (`_last_sent`), und nur
   rendern, was betroffen ist (§3.5).
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
10. ~~**Bausteinketten aufteilen** (W1). Eine Tabelle `Typ → (kachel_fn,
    detail_fn)` statt der `elif`-Kette macht neue Bausteine zu einer Datei pro
    Typ, ohne das Protokoll zu ändern.~~ Erledigt, `bin/bausteine/` (§6).
