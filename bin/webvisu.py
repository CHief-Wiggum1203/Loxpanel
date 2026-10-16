#!/usr/bin/env python3
"""LoxPanel Live-Web-Visu (Phase 3) — Navigations-Shell.

Baut die Loxone-App-Navigation nach, aber aufgeraeumt fuers 480x480-Panel:
kompakter Kopf (Titel + Uhr), 2x2-Kacheln, unten 4 Tabs
(Favoriten / Zentral / Raeume / Kategorien). Licht ist voll ausgebaut:
Kategorie/Raum/Zentral -> Raum-Lichtcontroller -> Stimmungen.

Client<->Server (WebSocket, JSON):
  Client: {t:'nav', route:{...}}     Server: {t:'view', ...}
  Client: {t:'cmd', uuid, cmd}

Start:  python webvisu.py   ->  http://localhost:8099
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hmac
import ipaddress
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from urllib.parse import quote

import aiohttp
from aiohttp import WSMsgType, web

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loxone_api import LoxoneClient  # noqa: E402
from loxone_ws import LoxoneWS  # noqa: E402
from bausteine.gemeinsam import (  # noqa: E402  # gemeinsame Konstanten und Helfer der Bausteine
    INTERCOM_TYPES, _clean)
from audioserver import make_backend, AudioBackend  # noqa: E402
from audioserver_events import AudioEventClient  # noqa: E402
import front_info  # noqa: E402  # Kalender (iCal-Abos) + Wetter (Open-Meteo) fuer die Front
import loxone_secure  # noqa: E402  # verschluesselte Befehle (gesicherte Details der Intercom)
import audioserver_auth  # noqa: E402  # Audioserver-Anmeldung; hier nur HAVE_CRYPTO (_fehlende_pakete_melden)
import sip_probe  # noqa: E402  # SIP-Pruefung der Tuerstation (OPTIONS mit Anmeldung)
from intercom_talk import IntercomTalk, TalkBusy  # noqa: E402
import theme_colors  # noqa: E402  # Panel-Theme aus einer Grundfarbe herleiten
import diagnose  # noqa: E402  # Diagnosepaket (/api/diagnose) und Log-Puffer
import konfig  # noqa: E402  # Konfigdateien: Pfade, Laden, Pruefen, Schreiben
from konfig import (  # noqa: E402  # Konfigdateien: Pfade, Laden, Pruefen, Schreiben
    _audio_config, _audiometa_config, _calendar_config, _CFGDIR, _clean_kachel_aktiv, _clean_kachel_farbton,
    _clean_kachel_set, _clean_screen, _config, FRONT_TABS, GERAETE_KATALOG, GESTEN_HINWEIS_STANDARD,
    GESTEN_STANDARD, GROESSEN_STANDARD, HAUS_AUFBAU_STANDARD, HAUS_AUFBAUTEN, HAUS_TAB, _intercom_config,
    _is_tab, KACHEL_WACHSEN, KACHEL_ZIEL, KACHEL_ZIEL_MAX, KACHEL_ZIEL_MIN, KACHEL_ZIEL_STANDARD, _load_cfg,
    load_devices, load_panels, load_theme, LOXLIB_DIR, _LOXLIB_NAME, _loxlib_names, _ms_zugang,
    NACHT_STANDARD, _night_config, PANE_ANTEIL, PANE_SPALTEN_MAX, PICK_TAB, PIN_MERKEN_MAX,
    PIN_MERKEN_STANDARD, SCALE_MAX, SCALE_MIN, STAT_RANGES, SV_STATUS_MAX, THEME_UI_KEYS, _write_cfg)
from sicherung import (  # noqa: E402  # Backup und Einspielen; die Routen /api/backup, /api/restore hier
    BACKUP_FILES, _backup_zip, _kennwoerter_einsetzen, _sicherung_lesen, _sicherung_pruefen,
    _sicherung_schreiben)
# App setzt sich aus Mixins zusammen, je Thema ein Modul (Reihenfolge wie die Basisklassen).
from statistik import STAT_DEFAULT_RANGE, Statistik  # noqa: E402  # Verlaeufe (Statistik-Dateien)
from bausteine import BausteinHelfer  # noqa: E402  # Helfer der Bausteine
from bausteine.intercom import _BELL_TS  # noqa: E402  # Klingelbilder
from haus import Haus, HAUS_TITEL  # noqa: E402  # Hausuebersicht
from gesten import Gesten  # noqa: E402  # Gesten der Visu
from miniserver import (  # noqa: E402  # Verbindung, Struktur, Befehle
    KEIN_SIP, Miniserver, _ms_unerreichbar, OhneGesicherteDetails, ZugangFehler)
from geraete import (  # noqa: E402  # Geraete, Agenten, Display
    AGENT_BEFEHL_TIMEOUT, AGENT_KANN_PANEL, AGENT_ONLINE, Geraete, KIOSK_APPS, _lan_adressen, NEULADEN_STUNDE,
    VORSCHAU_GERAET_DAUER)
from audiodienst import Audiodienst  # noqa: E402  # Audioserver, Cover, Favoriten
from intercomdienst import (  # noqa: E402  # SIP-Zugang, Kamera, Kamera-Pane
    _gesichert_felder, Intercomdienst, _sip_zugang)
from front import Front  # noqa: E402  # Kalender und Wetter der Uhr-Seite
from verteilung import Verteilung  # noqa: E402  # Senden an die Browser
from medien import Medien  # noqa: E402  # Icons, Cover, Klingelbilder
from diagnosedaten import Diagnosedaten, VERSION  # noqa: E402  # Diagnose und /api/types
from ansicht import Ansicht  # noqa: E402  # Profil, Theme, Export
from seiten import KACHEL_BREIT_TYPEN, Seiten, WERTE_LEISTE_TYPEN  # noqa: E402  # Seiten, Kacheln, Detailseiten

log = logging.getLogger("loxpanel.webvisu")


def server_stand() -> str:
    """Kennung des laufenden Stands fuer Visu und Konfigurator (theme-Nachricht,
    /api/devices): der Commit, ohne ihn die Kennung des Inhalts (lokaler Build
    ohne Git), sonst leer. Meldet ein neu gestarteter Server einen anderen,
    laden offene Seiten neu, statt altes HTML/JS gegen den neuen Server laufen
    zu lassen."""
    return VERSION.get("commit") or VERSION.get("inhalt") or ""


_WEB = Path(__file__).resolve().parent.parent / "webfrontend" / "html"
HTML = _WEB / "panel.html"
CONFIG_HTML = _WEB / "config.html"
SETTINGS_HTML = _WEB / "settings.html"
I18N_JS = _WEB / "i18n.js"
RASTER_JS = _WEB / "raster.js"   # Rasterrechnung fuer Visu und Konfigurator (Punkt 9)
CONFIG_CSS = _WEB / "config.css"  # Stylesheet des Konfigurators
CONFIG_JS = _WEB / "config"       # die Teile des Konfigurator-Skripts, config.html laedt sie der Reihe nach
PANEL_TEILE = _WEB / "panel"      # Stylesheets und Skriptteile der Visu, panel.html laedt sie der Reihe nach
INSTALL_SH = Path(__file__).resolve().parent.parent / "deploy" / "install-agent.sh"


class App(Statistik, BausteinHelfer, Haus, Gesten, Miniserver,
          Geraete, Audiodienst, Intercomdienst, Front, Verteilung, Medien, Diagnosedaten, Ansicht, Seiten):
    # Pruefen und Exportieren der Konfiguration liegt in konfig.py; hier als
    # statische Methoden erreichbar, weil Server, Sicherung und Tests sie so rufen.
    _sanitize_panels = staticmethod(konfig._sanitize_panels)
    _panels_verworfen = staticmethod(konfig._panels_verworfen)
    _panels_doc = staticmethod(konfig._panels_doc)
    _sanitize_devices = staticmethod(konfig._sanitize_devices)
    _sanitize_display = staticmethod(konfig._sanitize_display)
    _devices_export = staticmethod(konfig._devices_export)
    _sanitize_theme_ui = staticmethod(konfig._sanitize_theme_ui)
    _sanitize_categories = staticmethod(konfig._sanitize_categories)

    def __init__(self, ms: dict, audio: dict | None = None,
                 audiometa: dict | None = None):
        # ms kann leer sein (noch kein Miniserver konfiguriert) -> Server startet
        # trotzdem, /settings bleibt bedienbar; verbunden wird erst mit host.
        self.host, self.port = ms.get("host", ""), ms.get("port", 443)
        self.user, self.password = ms.get("user", ""), ms.get("pass", "")
        self.verify_tls = ms.get("verify_tls", False)
        # Einrichtungshinweis an die Panels (_einrichtung_stand): letzter Fehler
        # beim Verbinden mit dem Miniserver, und welcher Stand zuletzt rausging.
        self._ms_fehler = ""
        self._einrichtung_gemeldet: tuple | None = None
        # Verbindungszustand (_verbindung_stand): seit wann der Miniserver weg
        # ist (Unix-Sekunden, None = verbunden oder noch nie versucht), wann er
        # zuletzt etwas schickte, was zuletzt an die Panels ging und wann.
        self._ms_weg_seit: float | None = None
        self._ms_bestaetigt: float | None = None
        self._ms_verbunden_seit: float | None = None   # Datenstrom laeuft seit (Diagnose)
        self._verbindung_gemeldet: tuple | None = None
        self._verbindung_zuletzt = 0.0

        self.audio_cfg = audio or {}
        self.audio: AudioBackend | None = make_backend(self.audio_cfg)
        # Ein Steuerungs-Backend je Audioserver-Host (WS 7091), aufgebaut on
        # demand aus dem in der Struktur hinterlegten mediaServer-Host.
        self.audio_backends: dict[str, AudioBackend] = {}
        # Gen-2-Audioserver-Metadaten (universeller audio_event-Kanal, Port 7091):
        # Adressen werden AUTOMATISCH aus der Loxone-Struktur (/mediaServer/<uuid>
        # /host) gelesen; pro Audioserver ein Event-Client. Zonen-Zuordnung ueber
        # control.details.server (-> host) + details.playerid. Funktioniert mit
        # Original-Audioserver, Sonn und jedem Nachbau, ohne IP-Eingabe.
        self.audiometa_cfg = audiometa or {}
        self.mediaservers: dict[str, str] = {}          # serverUUID -> "host:port"
        self.audio_clients: dict[str, AudioEventClient] = {}  # host -> Client
        # uuidAction -> Loxone-playerid (fuer Audioserver-Kommandos)
        self.playerid_by_action: dict[str, int] = {}
        # uuidAction -> Audioserver-Host (aus mediaServer der Struktur). So
        # steht der Host auch fest, wenn nichts spielt (kein Cover zum Ableiten).
        self.audiohost_by_action: dict[str, str] = {}

        self.client: LoxoneClient | None = None
        self.ws: LoxoneWS | None = None
        self.states: dict[str, object] = {}
        self.controls: dict = {}
        self.rooms: dict = {}
        self.cats: dict = {}
        self.rooms_with: list[str] = []
        self.cats_with: list[str] = []
        self.conn_route: dict[web.WebSocketResponse, dict] = {}
        self.conn_prof: dict[web.WebSocketResponse, dict] = {}
        self.conn_dev: dict[web.WebSocketResponse, str] = {}   # ws -> Geraetename (?device=)
        self.conn_info: dict[web.WebSocketResponse, dict] = {}  # ws -> {dev, kiosk, ip, ts} (Geraeteverwaltung)
        self._drv_session: aiohttp.ClientSession | None = None   # HTTP-Session fuer Display-Treiber (Kiosk-Apps)
        self.conn_player: dict[web.WebSocketResponse, str] = {}   # ws -> AudioZone-UUID der aktiven Player-Pane (via setplayer)
        self.conn_energy: dict[web.WebSocketResponse, str] = {}   # ws -> EFM/EnergyManager2-UUID der aktiven Energiefluss-Pane (via setenergy)
        self.conn_camera: dict[web.WebSocketResponse, str] = {}   # ws -> Intercom-UUID der aktiven Kamera-Pane (via setcamera)
        self.conn_status: dict[web.WebSocketResponse, tuple] = {}  # ws -> UUIDs der Status-Kacheln auf der Uhr-Seite (via setsvstatus)
        self.conn_chart: dict[web.WebSocketResponse, tuple[tuple[str, ...], str]] = {}   # ws -> (Baustein-UUIDs, Zeitraum) der Verlaufs-Pane (via setchart)
        self.conn_geste: dict[web.WebSocketResponse, dict] = {}   # ws -> laufende Geste (Dimmen, Lautstaerke), App.geste()
        self.panels = load_panels()
        self.entwuerfe: dict[str, dict] = {}   # Token -> {id, panel (gesaeubert), ts}, nur im Speicher
        # Geraet -> {token, id, zurueck (Profil davor), bis}: zeigt gerade einen Entwurf (Punkt 12)
        self.vorschau_geraet: dict[str, dict] = {}
        # ... beendet, als keine Verbindung des Geraets den Entwurf zeigte (es lud gerade neu
        # oder war offline): Geraet -> {token, zurueck}. Gilt, bis es mit dem Token wiederkommt
        self.vorschau_ende: dict[str, dict] = {}
        self.devices = load_devices()   # Agent-Name -> {auto, modes:{modus:profil}}
        self.last_mode = ""             # zuletzt gesetzter Betriebsmodus (fuer Nachziehen beim Verbinden)
        # Geraete, deren Ansicht unter Displays ausdruecklich gewaehlt wurde: der
        # Betriebsmodus zieht sie beim Verbinden nicht um, bis er neu wechselt.
        self.ansicht_gewaehlt: set[str] = set()
        self._struct_sig: str | None = None   # Signatur der Loxone-Struktur (erkennt Config-Aenderungen)
        self._pending_reload = False          # -> Panels beim naechsten Tick neu laden ({t:"reload"})
        self.global_states: dict = {}   # globale States der Anlage (Name -> UUID), s. _apply_structure
        self.op_modes: dict = {}        # Betriebsarten der Anlage (Id -> Name), s. _apply_structure
        self._night_on = False          # Nachtmodus aktiv? (-> {t:"night"} an die Panels)
        self.night_cfg = _night_config()  # {"control": uuid} -> dessen active-State = Nacht
        self._dirty = True
        # Zuletzt an JEDE Verbindung zugestellte Nutzlast, je Art getrennt
        # ({"view":…, "player":…, "energy":…}). Grundlage dafuer, unveraenderte
        # Ansichten gar nicht erst zu senden. Eingetragen wird ausschliesslich
        # NACH erfolgreichem Senden - ein abgebrochener Versuch darf nie als
        # zugestellt gelten.
        self._last_sent: dict = {}
        self.jwt: str | None = None
        self.alg: str = "SHA1"
        self._ms_pubkey = None           # RSA-Schluessel des Miniservers fuer verschluesselte Befehle
        # Kamera je Intercom aus den gesicherten Details (intercom_video): {"url",
        # "user", "pass"} oder {"grund"}; gilt bis zur naechsten Struktur
        self.ms_video: dict[str, dict] = {}
        self._video_sperre = asyncio.Lock()
        self._auth_gen = 0               # zaehlt jede Anmeldung (-> _renew_token)
        self._auth_at = 0.0              # monotonic der letzten Anmeldung
        self._auth_lock = asyncio.Lock()
        self.icon_session: aiohttp.ClientSession | None = None
        self.icon_cache: dict[str, tuple[bytes, str]] = {}
        self.bell_cache: dict[str, tuple[bytes, str]] = {}   # camimage-Pfad -> (Bild, Typ)
        # Verlaufsdaten: (uuidAction, "JJJJMM") -> (monotonic, JJJJMM beim Abruf,
        # [(sekunden, [werte])] oder None nach Abruffehler). Ein Monat, der beim
        # Abruf schon vorbei war, aendert sich nicht mehr.
        self.stat_cache: dict[tuple[str, str], tuple[float, str, list | None]] = {}
        self.stat_pending: set[tuple] = set()
        # statisticV2 (Energie-Zaehler): (uuidAction, Gruppe, Ausgang, Zeitraum) ->
        # (monotonic, [(sekunden, [wert])] oder None nach Abruffehler). Hoechstens
        # zwei Abrufe gleichzeitig; die Loxone-App erlaubt 4 (Gen 2) bzw. 1 (Gen 1).
        self.stat2_cache: dict[tuple, tuple[float, list | None]] = {}
        self.stat2_sem = asyncio.Semaphore(2)
        self.stat_gen = 0              # zaehlt jeden Abruf, Schluessel fuer stat_memo
        self.stat_memo: dict[tuple, list] = {}
        self.theme = load_theme()
        self._cat_memo: tuple = (None, {})   # _cat_entry: (categories-Objekt, Name -> Eintrag)
        self._einspiel_sperre = asyncio.Lock()   # /api/restore: nur ein Einspielen zur Zeit
        # Miniserver-Zugang pruefen und speichern (api_settings_ms, auch beim
        # Einspielen) nur nacheinander, sonst laufen Datei und Verbindung
        # auseinander. _zugang_neu: gespeichert, aber beim Pruefen nicht
        # erreichbar - stream_task verbindet beim naechsten Aufbau damit.
        self._zugang_sperre = asyncio.Lock()
        self._zugang_neu: dict | None = None
        self.intercom_cfg = _intercom_config()
        self.intercom_talk = IntercomTalk(self._talk_credentials)
        # Front (Screensaver): Kalender + Wetter. front_task() laedt periodisch,
        # _front ist die zuletzt gebaute Nachricht ({"t":"front",...}), _front_key
        # ihr Abbild zum Vergleich (nur bei Aenderung neu senden), _front_meta der
        # Status fuer die Config-Seite. _front_refresh weckt front_task (nach dem
        # Speichern und bei neuem Wetter vom Miniserver).
        self.calendar_cfg = _calendar_config()
        # Loxone-Wetterserver: Konfiguration aus der Struktur, Rohdaten je
        # State-UUID (kommen ueber den WS als eigene Tabelle) und die zuletzt
        # tatsaechlich verwendete Quelle fuer die Diagnose.
        self.weather_cfg: dict = {}
        self._lox_wx: dict[str, list] = {}
        self._wx_source: str = "open-meteo"
        # Standort des Miniservers (aus msInfo) als Wetter-Fallback ohne Konfiguration.
        self.ms_lat: float | None = None
        self.ms_lon: float | None = None
        self.ms_location: str = ""
        self.ms_struktur: dict = {}   # msInfo fuer das Diagnosepaket (_apply_structure)
        self._front: dict | None = None
        self._front_key: str | None = None
        self._front_meta: dict = {}
        # Letzter erfolgreich geladener Stand je Teil (Feiertage, Wetter) plus
        # dessen Uhrzeit. Ueberbrueckt Aussetzer der Quellen, siehe _front_keep().
        self._front_good: dict = {}
        # Dasselbe fuer die Termine, aber JE KALENDER: {Quellenschluessel ->
        # {"events": [...], "zeit": "HH:MM"}}. Mit mehreren Abos reicht ein
        # gemeinsamer Stand nicht — faellt iCloud aus und Google liefert, waere
        # die Terminliste nicht leer und der alte Stand (mit den iCloud-
        # Terminen darin) wuerde ueberschrieben.
        self._front_good_cal: dict = {}
        self._front_dirty = False
        self._front_refresh = asyncio.Event()
        # Letzter fertig gebauter Front-Stand (nach _front_keep) und ab wann der
        # Kalender wieder aus dem Netz geholt wird (time.monotonic(), 0 = sofort).
        # Ein Wetter-Push des Miniservers baut die Front aus diesem Stand neu und
        # ruft KEINEN Kalender ab, siehe front_task().
        self._front_last: dict | None = None
        self._front_cal_due = 0.0
        self._front_session: aiohttp.ClientSession | None = None
        self.bell_map: dict[str, str] = {}
        self._bell_prev: dict[str, object] = {}
        self._pending_ring: str | None = None
        # Wecker (AlarmClock): isAlarmActive-State-UUID -> Control-UUID. Flanke
        # 0->1/1->0 wird als {"t":"alarm",...} ans Panel gepusht (Weckton an/aus).
        self.alarm_map: dict[str, str] = {}
        self._alarm_prev: dict[str, object] = {}
        self._pending_alarm: list[dict] = []
        # Praesenzmelder je Geraet (devices[name].presence = Control-UUID): solange
        # sein active-State jemanden meldet, bleibt das Display des Geraets an.
        # State-UUID -> Geraete, Stand je Geraet, offene Meldungen an die Panels
        # (verteilt in _broadcast_tick).
        self.presence_map: dict[str, list[str]] = {}
        self._presence_on: dict[str, bool] = {}
        self._pending_presence: list[dict] = []
        self._presence_quelle: tuple = (None, None)   # (devices, controls) hinter presence_map
        self.agents: dict[str, dict] = {}   # ip -> Panel-Agent (Fernstart)
        # ip -> Profil, das ein Agent mit seiner naechsten Meldung uebernehmen
        # soll (Displays, Betriebsmodus); faellt weg, sobald er es meldet
        self.agent_wunsch: dict[str, str] = {}
        self.bg_tasks: set = set()          # laufende Hintergrund-Tasks (z.B. Favs anfordern)
        # Dynamisches Song-Cover (iTunes) fuer Zonen, die nur ein Sender-Logo
        # liefern (z.B. Sonn/Audioserver): "artist\ntitle" -> (url|None, expiry).
        self._cover_cache: dict[str, tuple[str | None, float]] = {}
        self._cover_pending: set[str] = set()
        # Spieler der Hausseite: wann die Favoriten je Zone zuletzt angefordert
        # wurden (_haus_sender_anfordern)
        self._haus_sender_zeit: dict[str, float] = {}

    def _spawn(self, coro) -> None:
        """Hintergrund-Task starten und sauber referenziert halten."""
        task = asyncio.ensure_future(coro)
        self.bg_tasks.add(task)
        task.add_done_callback(self.bg_tasks.discard)

        # vorschau_ende bleibt: eine schon beendete Vorschau kehrt weiter zur Ansicht davor zurueck

    async def close(self) -> None:
        await self.intercom_talk.close()
        if self.ws:
            await self.ws.close()
        if self.icon_session:
            await self.icon_session.close()
        if self.client:
            await self.client.close()
        if self.audio:
            await self.audio.close()
        for be in list(self.audio_backends.values()):
            await be.close()
        self.audio_backends.clear()
        for cl in list(self.audio_clients.values()):
            await cl.close()
        self.audio_clients.clear()


# Panel-/Config-/Settings-HTML immer frisch ausliefern: der Kiosk-Chromium
# cachte die Seite sonst heuristisch und zeigte nach einem Update die alte
# Version (aufklappende Auswahl etc. griff nicht) bis der Profil-Cache geleert
# wurde. no-cache erzwingt Revalidierung -> Updates greifen sofort.
_NOCACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


def _web_file(path: Path, ctype: str) -> web.Response:
    """Eine der Oberflaechen-Dateien ausliefern. Fehlt sie (kaputtes Image,
    falsch gemountetes Volume), gibt es einen 404 mit Dateinamen statt eines
    Stacktrace als 500."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        log.error("%s nicht lesbar: %s", path, err)
        return web.Response(status=404, text=f"{path.name} fehlt im LoxPanel-Image")
    return web.Response(text=text, content_type=ctype, headers=_NOCACHE)


async def index(request: web.Request) -> web.Response:
    return _web_file(HTML, "text/html")


async def config_index(request: web.Request) -> web.Response:
    return _web_file(CONFIG_HTML, "text/html")


async def i18n_js(request: web.Request) -> web.Response:
    """Gemeinsamer Uebersetzungs-Katalog fuer /settings und /config."""
    return _web_file(I18N_JS, "application/javascript")


async def raster_js(request: web.Request) -> web.Response:
    """Gemeinsame Rasterrechnung: die Visu baut damit ihr Raster, der
    Seiten-Editor des Konfigurators zeichnet ein Geraet damit vor."""
    return _web_file(RASTER_JS, "application/javascript")


async def config_css(request: web.Request) -> web.Response:
    """Stylesheet des Konfigurators (webfrontend/html/config.css)."""
    return _web_file(CONFIG_CSS, "text/css")


_CONFIG_JS_NAME = re.compile(r"^[a-z][a-z0-9-]*\.js$")


async def config_js(request: web.Request) -> web.Response:
    """Ein Teil des Konfigurator-Skripts (webfrontend/html/config/<name>.js).
    config.html laedt die Teile in fester Reihenfolge; nur schlichte Namen,
    damit kein Pfad aus dem Ordner herausfuehrt."""
    name = request.match_info["name"]
    if not _CONFIG_JS_NAME.match(name):
        raise web.HTTPNotFound()
    return _web_file(CONFIG_JS / name, "application/javascript")


_PANEL_TEIL_NAME = re.compile(r"^[a-z][a-z0-9-]*\.(js|css)$")
_TEIL_TYPEN = {"js": "application/javascript", "css": "text/css"}


async def panel_teil(request: web.Request) -> web.Response:
    """Ein Stylesheet oder ein Teil des Visu-Skripts (webfrontend/html/panel/
    <name>.css|.js). panel.html laedt sie in fester Reihenfolge; nur schlichte
    Namen, damit kein Pfad aus dem Ordner herausfuehrt."""
    name = request.match_info["name"]
    m = _PANEL_TEIL_NAME.match(name)
    if not m:
        raise web.HTTPNotFound()
    return _web_file(PANEL_TEILE / name, _TEIL_TYPEN[m.group(1)])


async def api_kachelset(request: web.Request) -> web.Response:
    """Nachgerechnete Kontraste eines Kachel-Sets zu Farbton und aktiver Kachel
    (?set=touch&farbton=95&aktiv=dunkel), fuer "Nachgerechnet" und die
    Vorschau der Auswahlkarte im Konfigurator. Nur lesend; Ungueltiges gilt als Standard des Sets."""
    q = request.query
    name = _clean_kachel_set(q.get("set"))
    if not name:
        return web.json_response({"error": "unbekanntes Kachel-Set"}, status=404)
    try:
        farbton = _clean_kachel_farbton(int(q.get("farbton", "")))
    except ValueError:
        farbton = None
    aktiv = _clean_kachel_aktiv(q.get("aktiv"))
    return web.json_response({"set": name, "kachel": theme_colors.kachel_set_kachel(name, farbton, aktiv),
                              "vorschau": theme_colors.kachel_set_vorschau(name, farbton, aktiv),
                              "pruefung": theme_colors.kachel_set_pruefung(name, farbton, aktiv)})


async def api_meta(request: web.Request) -> web.Response:
    """Alle Räume/Kategorien der Anlage + aktuelle Profile (für den Editor)."""
    app: App = request.app["app"]
    rooms = [{"uuid": ru, "name": _clean(app.rooms[ru].get("name", ""))} for ru in app.rooms_with]
    cats = [{"uuid": cu, "name": _clean(app.cats[cu].get("name", "")),
             "color": app.cats[cu].get("color")}         # Loxone-Voreinstellungsfarbe der Kategorie
            for cu in app.cats_with]
    panels = {pid: app._panel_export(raw) for pid, raw in app.panels.items()}
    controls = []
    for u, c in app.controls.items():
        if not c.get("name"):
            continue
        room = c.get("room")
        # Was die Kachel zeigt, fuer die Vorschau im Seiten-Editor: ihre Tasten
        # (Anzahl) und ein Cover - dieselbe Rechnung wie in der Visu
        kachel = app._control_item(u)
        controls.append({
            "uuid": u, "name": _clean(c.get("name")), "type": c.get("type"),
            "room": room,
            "roomName": _clean((app.rooms.get(room) or {}).get("name", "")) if room else "",
            "cat": c.get("cat"),
            "iconUrl": app._control_icon_url(c),
            # Zeichnet der Baustein auf? Dann bietet der Konfigurator ihn fuer
            # die Verlaufs-Pane und den Mini-Verlauf in der Kachel an.
            "stat": bool(c.get("statistic") or c.get("statisticV2")),
            # Art der Reihe, die die Kachel zeigt (line/digital/counter): die
            # Tagesspanne gibt es nur fuer Linien.
            "statKind": (app._stat_primary(c) or (None, None))[1],
            "tasten": len(kachel.get("controls") or []),
            "cover": kachel.get("cover") or "",
        })
    return web.json_response({
        "rooms": rooms, "cats": cats, "controls": controls,
        # Zeitraeume der Verlaufs-Diagramme (Schluessel, Anzeige) fuer die Auswahl
        # "Verlauf in der Kachel" — eine Quelle mit der Visu (STAT_RANGES).
        "statRanges": [[k, v[0]] for k, v in STAT_RANGES.items()],
        # Wie viele Werte-Kacheln die Uhr-Seite traegt. Der Konfigurator liest
        # die Zahl hier ab, statt sie ein zweites Mal zu fuehren.
        "svStatusMax": SV_STATUS_MAX,
        # Grenzen des Skalierungsfaktors; der Konfigurator bietet nur Stufen
        # innerhalb davon an.
        "scaleRange": [SCALE_MIN, SCALE_MAX],
        # Groessen ohne Einstellung je Kachel-Aufbau: der Konfigurator zeigt sie
        # in leeren Feldern an, statt sie ein zweites Mal zu fuehren.
        "sizeDefaults": GROESSEN_STANDARD,
        # Kachel-Sets [{key, label}]: die Auswahl im Konfigurator, eine Quelle
        # mit _theme_vars() (theme_colors.KACHEL_SETS).
        "kachelSets": theme_colors.kachel_set_liste(),
        # Nachtmodus ohne Einstellung (Abdunkelung, Aufhellen): leere Felder
        # unter Vorgaben -> Nacht und Ansicht -> Verhalten zeigen ihn.
        "nightDefaults": NACHT_STANDARD,
        # Welche ui-Schluessel eine Vorgabe haben (theme.json): der Konfigurator
        # zeigt nur bei ihnen "aus den Vorgaben" und zaehlt die Ansichten, die
        # sie selbst setzen.
        "themeKeys": list(THEME_UI_KEYS),
        # Stunde des naechtlichen Neuladens ohne Einstellung "Auto-Neustart":
        # der Konfigurator nennt sie im leeren Feld.
        "reloadAt": NEULADEN_STUNDE,
        # PIN merken: Standard und Grenze fuer das Feld im Konfigurator
        "pinMerken": {"standard": PIN_MERKEN_STANDARD, "max": PIN_MERKEN_MAX},
        "icons": {"loxone": app._loxone_icons(), "loxlib": len(_loxlib_names())},
        "tabs": [{"tab": "favoriten", "label": "Favoriten"},
                 {"tab": "zentral", "label": "Zentral"},
                 {"tab": "raeume", "label": "Räume"},
                 {"tab": "kategorien", "label": "Kategorien"},
                 {"tab": PICK_TAB, "label": "Eigene Auswahl", "pick": True}]
        + [{"tab": k, "label": titel} for k, (titel, _teil) in FRONT_TABS.items()]
        + [{"tab": HAUS_TAB, "label": HAUS_TITEL}]
        + [{"tab": "cat:" + cu, "label": _clean(app.cats[cu].get("name", "")),
            "iconUrl": app._icon_url(app.cats[cu].get("image")), "cat": True}
           for cu in app.cats_with]
        + [{"tab": "room:" + ru, "label": _clean(app.rooms[ru].get("name", "")),
            "iconUrl": app._icon_url(app.rooms[ru].get("image")), "room": True}
           for ru in app.rooms_with],
        "panels": panels,
        "devices": App._devices_export(app.devices),
        # Zielkachel des automatischen Rasters: Grenzen, Standard, alte Stufen
        "kachelZiel": {"min": KACHEL_ZIEL_MIN, "max": KACHEL_ZIEL_MAX, "std": KACHEL_ZIEL_STANDARD,
                       "stufen": KACHEL_ZIEL, "wachsen": KACHEL_WACHSEN},
        # Widget-Breite im automatischen Raster: groesste feste Spaltenzahl, Anteil der Automatik
        "paneCols": {"max": PANE_SPALTEN_MAX, "anteil": PANE_ANTEIL},
        # Assistent Schritt 1: Geraete zum Vorrechnen, solange keines verbunden ist
        "geraeteKatalog": [dict(k) for k in GERAETE_KATALOG],
        # Bausteintypen, deren Kachel von Haus aus zwei Spalten belegt (Kachel-Editor: Breite)
        "kachelBreit": sorted(KACHEL_BREIT_TYPEN),
        # Bausteintypen, die auf einer Seite mit Werteleiste aus dem Raster in
        # die Leiste wandern (Seiten-Editor: zeigt die Seite wie die Visu)
        "werteLeiste": sorted(WERTE_LEISTE_TYPEN),
        # Bausteine mit active-State: Auswahl fuer den Praesenzmelder je Geraet
        # (dieselbe Liste wie beim Nacht-Ausloeser)
        "activeControls": app.night_control_options(),
        # Gesten: Taster fuer "Raum verlassen" (je Raum) und "Haus aus"
        # (Vorgaben), Lichtsteuerungen mit Stimmungen fuer "Stimmung beim
        # Einschalten" (Geraete) und der Standard ohne Einstellung
        "gestenTaster": app.geste_taster_optionen(),
        "lichtStimmungen": app.licht_stimmung_optionen(),
        "gestenStandard": GESTEN_STANDARD,
        "gestenHinweisStandard": GESTEN_HINWEIS_STANDARD,
        # Aufbau der Hausseite: Auswahl je Ansicht (Aussehen) und ihr Standard
        "hausAufbauten": [{"key": k, "label": v} for k, v in HAUS_AUFBAUTEN.items()],
        "hausAufbauStandard": HAUS_AUFBAU_STANDARD,
        "wsDevices": sorted({d for d in app.conn_dev.values() if d}),
        # LAN-Adresse dieses Servers fuer "Geraet verbinden" (auch wenn der
        # Konfigurator ueber 127.0.0.1 laeuft); leer ohne Route ins Netz
        "adressen": _lan_adressen(),
        "theme": {"ui": {k: v for k, v in (app.theme.get("ui") or {}).items()
                         if k in THEME_UI_KEYS},
                  "categories": {k: v for k, v in (app.theme.get("categories") or {}).items()
                                 if not str(k).startswith("_")}},
    })


async def api_save_panels(request: web.Request) -> web.Response:
    app: App = request.app["app"]
    try:
        data = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        return web.json_response({"ok": False, "error": "kein gültiges JSON"}, status=400)
    panels = data.get("panels")
    if not isinstance(panels, dict):
        return web.json_response({"ok": False, "error": "Feld 'panels' fehlt"}, status=400)
    clean = App._sanitize_panels(panels)
    # Was der Server nicht uebernimmt, meldet er (Konfigurator zeigt es an),
    # statt es still zu verlieren.
    weg = App._panels_verworfen(panels, clean,
                                {u: _clean(c.get("name")) or u for u, c in app.controls.items()})
    try:
        app._write_panels(clean)
    except OSError as err:
        return web.json_response({"ok": False, "error": str(err)}, status=500)
    # Vorschau-Fenster mit einem Entwurf verlassen ihn: die Entwuerfe sind erledigt, sie
    # laden das gespeicherte Profil. Ein blosses Neuladen liesse sie auf der Entwurfs-
    # Adresse, und der Konfigurator koennte sie nicht sicher umlenken (Wettlauf).
    for ws, info in list(app.conn_info.items()):
        if info.get("entwurf"):
            await app._neu_laden(ws, {"t": "entwurfEnde"})
    n = await _push(app, {"t": "reload"})   # offene Panels sofort neu laden
    log.info("panels.json gespeichert: %d Profile (%d Panels neu geladen)", len(clean), n)
    if weg:
        log.warning("panels.json: nicht übernommen: %s", "; ".join(weg))
    # `panels`: was jetzt tatsaechlich in der Datei steht, in der Form von /api/meta.
    # Der Konfigurator fuehrt das als gespeicherten Stand (ohne Verworfenes, normiert).
    return web.json_response({"ok": True, "count": len(clean), "reloaded": n, "verworfen": weg,
                              "panels": {pid: app._panel_export(raw) for pid, raw in app.panels.items()}})


async def api_entwurf(request: web.Request) -> web.Response:
    """Entwurf eines Profils fuer die Vorschau in der echten Visu: {id, panel,
    token?}. `panel` ist das Profil in der Form, in der der Konfigurator es
    speichert; es wird wie dort geprueft (was verworfen wuerde, steht in
    `verworfen`), aber nur im Speicher gehalten - panels.json bleibt unberuehrt.
    Antwort: `token` und `url` der Visu (/?panel=<id>&entwurf=<token>). Mit dem
    Token eines vorhandenen Entwurfs desselben Profils wird er ersetzt, und die
    Visus, die ihn gerade zeigen, laden neu (`reloaded`)."""
    app: App = request.app["app"]
    try:
        data = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        return web.json_response({"ok": False, "error": "kein gültiges JSON"}, status=400)
    pid, panel = data.get("id"), data.get("panel")
    if not isinstance(pid, str) or not pid.strip() or not isinstance(panel, dict):
        return web.json_response({"ok": False, "error": "Felder 'id' und 'panel' fehlen"}, status=400)
    pid = pid.strip()
    try:
        token, weg = app.entwurf_ablegen(pid, panel, str(data.get("token") or ""))
    except ValueError as err:
        return web.json_response({"ok": False, "error": str(err)}, status=400)
    n = 0
    for ws, info in list(app.conn_info.items()):
        if info.get("entwurf") == token and await app._neu_laden(ws):
            n += 1
    for v in app.vorschau_geraet.values():   # der Konfigurator arbeitet noch daran: die Vorschau am Geraet bleibt
        if v["token"] == token:
            v["bis"] = time.time() + VORSCHAU_GERAET_DAUER
    return web.json_response({"ok": True, "token": token, "reloaded": n, "verworfen": weg,
                              "url": "/?panel=" + quote(pid, safe="") + "&entwurf=" + token})


async def api_save_theme(request: web.Request) -> web.Response:
    """Globale Darstellung (theme.json ui) speichern — gilt fuer alle Panels."""
    app: App = request.app["app"]
    try:
        data = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        return web.json_response({"ok": False, "error": "kein gültiges JSON"}, status=400)
    ui = data.get("ui")
    if not isinstance(ui, dict):
        return web.json_response({"ok": False, "error": "Feld 'ui' fehlt"}, status=400)
    clean = App._sanitize_theme_ui(ui)
    cats = data.get("categories")
    clean_cats = App._sanitize_categories(cats) if isinstance(cats, dict) else None
    try:
        app._write_theme(clean, clean_cats)
    except OSError as err:
        return web.json_response({"ok": False, "error": str(err)}, status=500)
    n = await _push(app, {"t": "reload"})   # offene Panels sofort neu laden
    log.info("theme.json (globale Darstellung%s) gespeichert (%d Panels neu geladen)",
             " + Kategorie-Farben" if clean_cats is not None else "", n)
    return web.json_response({"ok": True, "reloaded": n})


async def settings_index(request: web.Request) -> web.Response:
    return _web_file(SETTINGS_HTML, "text/html")


async def install_script(request: web.Request) -> web.Response:
    """Liefert das Panel-Installer-Skript (fuer 'curl ... | bash' vom Panel aus)."""
    try:
        txt = INSTALL_SH.read_text(encoding="utf-8").replace("\r\n", "\n")
    except OSError:
        return web.Response(status=404, text="install-agent.sh nicht gefunden")
    return web.Response(text=txt, content_type="text/plain")


def _aufgaben_stand(a: web.Application) -> tuple[dict, bool]:
    """Hintergrundaufgaben (on_startup) -> ({Name: "läuft" | "beendet[: Fehler]"},
    alle laufen). Fuer /api/health und das Diagnosepaket."""
    tasks, ok = {}, True
    for name, t in (a.get("tasks") or {}).items():
        if not t.done():
            tasks[name] = "läuft"
            continue
        ok = False
        err = None if t.cancelled() else t.exception()
        tasks[name] = f"beendet: {err!r}" if err else "beendet"
    return tasks, ok


async def api_health(request: web.Request) -> web.Response:
    """Zustand fuer den Docker-HEALTHCHECK (Unraid zeigt ihn im Docker-Tab) und
    den Waechter der LoxPanel-App, der die App bei 503 neu startet.

    503, sobald eine Hintergrund-Aufgabe beendet ist: dann bekommen die Panels
    keine Werte oder Ansichten mehr, und ein Neustart des Containers hilft. Die
    Miniserver-Verbindung wird nur gemeldet - ist der Miniserver weg, hilft ein
    Neustart nicht, stream_task verbindet von selbst neu."""
    app: App = request.app["app"]
    tasks, ok = _aufgaben_stand(request.app)
    started = request.app.get("started")
    return web.json_response({
        "ok": ok, "tasks": tasks,
        "miniserver": bool(app.client and app.ws),
        "panels": len(app.conn_route),
        "uptime": round(time.monotonic() - started) if started is not None else None,
        "version": VERSION,
    }, status=200 if ok else 503, headers=_NOCACHE)


# Dateiname des Diagnosepakets: nur, was jeder Browser und jedes Dateisystem nimmt
_DATEINAME_RE = re.compile(r"[^A-Za-z0-9_-]+")


async def api_diagnose(request: web.Request) -> web.Response:
    """Diagnosepaket als ZIP (bin/diagnose.py): ?device= fuer ein Geraet
    (Konfigurator: Geraete -> Diagnose), sonst der Server mit allen Geraeten
    (Einstellungen -> Sicherung). 404 fuer ein unbekanntes Geraet. Die
    Einstellungsdateien wie in der Sicherung; eine unlesbare bleibt draussen,
    ungeprueft koennte sie ein Kennwort enthalten."""
    app: App = request.app["app"]
    geraet = (request.query.get("device") or "").strip()
    aufgaben, _ok = _aufgaben_stand(request.app)
    try:
        daten, geheim = app.diagnose_daten(geraet, aufgaben, request.app.get("started"))
    except KeyError:
        return web.json_response({"ok": False, "error": f"Gerät {geraet!r} unbekannt"}, status=404)
    einstellungen, fehlen = {}, []
    for name in BACKUP_FILES:
        f = _CFGDIR / name
        if not f.is_file():
            continue
        try:
            einstellungen[name] = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            log.warning("Diagnose: %s nicht lesbar (%s) - nicht enthalten", name, err)
            fehlen.append(name)
    if fehlen:
        daten["einstellungen_unlesbar"] = fehlen
    body = diagnose.paket(daten, einstellungen, diagnose.LOG.zeilen(), geheim)
    teil = _DATEINAME_RE.sub("_", geraet).strip("_") or "server"
    name = f"loxpanel-diagnose-{teil}-{datetime.now():%Y-%m-%d_%H%M}.zip"
    return web.Response(body=body, content_type="application/zip",
                        headers={**_NOCACHE, "Content-Disposition": f'attachment; filename="{name}"'})


async def api_backup(request: web.Request) -> web.Response:
    """Einstellungen als ZIP herunterladen (Settings -> Sicherung)."""
    name = f"loxpanel-einstellungen-{datetime.now():%Y-%m-%d_%H%M}.zip"
    return web.Response(body=_backup_zip(_CFGDIR), content_type="application/zip",
                        headers={**_NOCACHE, "Content-Disposition": f'attachment; filename="{name}"'})


# ---- Sicherung einspielen (POST /api/restore) ----
# Ablauf: ZIP lesen (_sicherung_lesen), alles pruefen und vorbereiten, ohne zu
# schreiben (_sicherung_pruefen), erst dann schreiben und den laufenden Server
# auffrischen (_sicherung_schreiben). Eine Sicherung kommt auch von einem
# anderen Server oder aus einer Hand-Bearbeitung; was der Server nicht
# verkraftet, wird deshalb vorher abgelehnt statt geschrieben.


async def api_restore(request: web.Request) -> web.Response:
    """Sicherung einspielen (Settings -> Sicherung): Body = ZIP aus /api/backup."""
    app: App = request.app["app"]
    try:
        daten = await request.read()
    except web.HTTPRequestEntityTooLarge:
        return web.json_response({"ok": False, "error": "Die Datei ist zu groß für eine LoxPanel-Sicherung."},
                                 status=413)
    if not daten:
        return web.json_response({"ok": False, "error": "Keine Datei erhalten."}, status=400)
    async with app._einspiel_sperre, app._zugang_sperre:
        # _zugang_sperre: Der Plan merkt sich den bisherigen Miniserver-Zugang
        # (ms_alt) und schreibt ihn bei Bedarf zurueck - kein Speichern dazwischen.
        # Lesen und Pruefen kosten bei grossen Sicherungen Sekunden Rechenzeit
        # (Grundfarben je Profil, Sanitizer, Groessenpruefung); im Thread bleibt
        # die Visu derweil bedienbar. Der Thread sieht vom laufenden Server nur
        # eine Momentaufnahme der Bausteinnamen und Geraete.
        stand = SimpleNamespace(controls=dict(app.controls), devices=copy.deepcopy(app.devices))
        try:
            plan = await asyncio.to_thread(lambda: _sicherung_pruefen(stand, *_sicherung_lesen(daten)))
        except ValueError as err:
            log.warning("Sicherung nicht eingespielt: %s", err)
            return web.json_response({"ok": False, "error": str(err)}, status=400)
        ergebnis = await _sicherung_schreiben(app, plan)
    return web.json_response(ergebnis, status=200 if ergebnis["ok"] else 500)


async def api_settings(request: web.Request) -> web.Response:
    app: App = request.app["app"]
    cfg = _load_cfg()
    ms = _config()        # derselbe Zugang, mit dem verbunden wird (Datei, sonst LOXPANEL_MS_*)
    ic = cfg.get("intercom", {})

    def icv(uuid):
        e = ic.get(uuid) or {}
        if isinstance(e, str):
            e = {"url": e}
        return {"url": (e.get("url") or "").strip(), "user": e.get("user", ""),
                "hasPass": bool(e.get("pass"))}

    intercoms = [{"uuid": u, "name": _clean(c.get("name")), **icv(u)}
                 for u, c in app.controls.items() if c.get("type") in INTERCOM_TYPES]
    am = cfg.get("audiometa", {}) if isinstance(cfg.get("audiometa"), dict) else {}
    cal = cfg.get("calendar", {}) if isinstance(cfg.get("calendar"), dict) else {}
    return web.json_response({
        "miniserver": {
            "host": ms.get("host", ""),
            "user": ms.get("user", ""),
            "port": ms.get("port", 443),
            "verify_tls": bool(ms.get("verify_tls", False)),
            "hasPass": bool(ms.get("pass")),
        },
        "intercoms": intercoms,
        "audiometa": {"enabled": bool(am.get("enabled", True)),
                      "servers": sorted(app.mediaservers.values())},
        "calendar": {
            # Quellen normalisiert (inkl. Migration einer alten einzelnen
            # ical_url), damit die Einstellungsseite genau das sieht, womit der
            # Server auch arbeitet.
            "sources": [{"name": q["name"], "url": q["url"], "color": q["color"],
                         "key": q["key"]}
                        for q in front_info.calendar_sources(cal)],
            "holiday_url": (cal.get("holiday_url") or "").strip(),
            "name": cal.get("name") or "Family",
            "colors": bool(cal.get("colors", True)),
            "sv_events": cal.get("sv_events", 3),
            "palette": front_info.CAL_COLORS,
            "max_sources": front_info.MAX_SOURCES,
            "lat": cal.get("lat"),
            "lon": cal.get("lon"),
            "days": cal.get("days", 14),
            "fore_days": cal.get("fore_days", 4),
            "status": app._front_meta,
            # Auto-Standort vom Miniserver (Fallback, wenn keine Koordinaten gesetzt)
            "ms_lat": app.ms_lat, "ms_lon": app.ms_lon, "ms_location": app.ms_location,
        },
        "night": {"control": (app.night_cfg or {}).get("control") or "",
                  "options": app.night_control_options()},
        "connected": app.client is not None,
        "nControls": len(app.controls),
        "version": VERSION,
        # Ohne Struktur fuehrt der Konfigurator zuerst zum Miniserver
        "einrichtung": app._einrichtung_info(),
    })


async def api_types(request: web.Request) -> web.Response:
    """Diagnose: Bausteintypen der Anlage mit Unterstuetzungsstatus. JSON,
    mit ?format=text als lesbare Tabelle fuer den Browser."""
    app: App = request.app["app"]
    if not app.controls:
        data = {"connected": app.client is not None, "controls": 0, "typeCount": 0,
                "typesByStatus": {"full": 0, "partial": 0, "none": 0}, "types": [],
                "unsupportedControls": [],
                "hint": "Keine Struktur geladen. Miniserver unter /config verbinden."}
    else:
        data = app.types_overview()
    if request.query.get("format") == "text":
        lines = [f"LoxPanel Bausteintypen: {data['controls']} Controls, {data['typeCount']} Typen "
                 f"(voll {data['typesByStatus']['full']}, teilweise {data['typesByStatus']['partial']}, "
                 f"keine {data['typesByStatus']['none']})", ""]
        if data.get("hint"):
            lines.append(data["hint"])
        label = {"full": "voll", "partial": "teilw.", "none": "KEINE"}
        lines.append(f"{'Status':8} {'Anzahl':>6}  {'Typ':30} Beispiele")
        for e in data["types"]:
            lines.append(f"{label[e['status']]:8} {e['count']:6}  {e['type']:30} {', '.join(e['examples'])}")
        if data["unsupportedControls"]:
            lines += ["", "Nicht unterstuetzte Controls (tote Kacheln):"]
            lines += [f"  {d['room'] or '-':24} {d['name']:36} {d['type']}" for d in data["unsupportedControls"]]
        lines += ["", "States/Details je Typ:"]
        for e in data["types"]:
            lines.append(f"  {e['type']}: states={', '.join(e['states']) or '-'} | details={', '.join(e['details']) or '-'}")
        return web.Response(text="\n".join(lines) + "\n", content_type="text/plain", charset="utf-8")
    return web.json_response(data, dumps=lambda d: json.dumps(d, ensure_ascii=False, indent=2))


async def api_settings_ms(request: web.Request) -> web.Response:
    """Miniserver-Zugang pruefen, dann speichern (Settings -> Miniserver).
    Lehnt der Miniserver ab, bleibt alles beim Alten, Datei wie Verbindung.
    Antwortet er nicht, ist offen, ob der Zugang stimmt: Er wird gespeichert,
    eine bestehende Verbindung bleibt aber, bis stream_task sie neu aufbaut
    (_zugang_neu). Leeres Kennwort = das bisherige, nur fuer denselben Host
    und Benutzer. "error" ist ein fester Text (i18n), der Fehler des
    Miniservers steht getrennt in "fehler"."""
    app: App = request.app["app"]
    try:
        data = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        return web.json_response({"ok": False, "error": "kein gültiges JSON"}, status=400)
    host = str(data.get("host", "")).strip()
    if not host:
        return web.json_response({"ok": False, "error": "Host fehlt"}, status=400)
    user = str(data.get("user", "")).strip()
    if not user:
        return web.json_response({"ok": False, "error": "Benutzer fehlt"}, status=400)
    try:
        port = int(data.get("port") or 443)
    except (TypeError, ValueError):
        port = 0
    if not 1 <= port <= 65535:
        return web.json_response({"ok": False, "error": "Port ungültig"}, status=400)
    neu = {"host": host, "user": user, "port": port, "verify_tls": bool(data.get("verify_tls"))}
    async with app._zugang_sperre:
        alt, quelle = _ms_zugang()
        if data.get("pass"):
            neu["pass"] = str(data["pass"])
        elif alt.get("pass") and (str(alt.get("host") or "").strip(), str(alt.get("user") or "").strip()) == (host, user):
            neu["pass"] = alt["pass"]
        else:
            return web.json_response({"ok": False, "error": "Neuer Host oder Benutzer: bitte das Passwort eingeben."
                                      if alt.get("pass") else "Passwort fehlt"}, status=400)

        def speichern() -> None:
            if quelle == "umgebung" and all(alt.get(k) == v for k, v in neu.items()):
                return   # unveraendert aus LOXPANEL_MS_*: gilt dort weiter, Kennwort nicht in die Datei
            cfg = _load_cfg()   # erst jetzt: andere Abschnitte koennen sich waehrend der Pruefung geaendert haben
            datei = cfg.get("miniserver") if isinstance(cfg.get("miniserver"), dict) else {}
            cfg["miniserver"] = {**datei, **neu}     # msno, _comment, Zeitwerte bleiben
            _write_cfg(cfg)

        try:
            n = await app.reconnect(neu)
        except Exception as err:
            fehler = " ".join(str(err).split()) or type(err).__name__
            if not _ms_unerreichbar(err):
                log.warning("Miniserver-Zugang nicht gespeichert, Anmeldung an %s gescheitert: %s", host, fehler)
                return web.json_response({"ok": False, "fehler": fehler, "error":
                                          "Anmeldung am Miniserver gescheitert. Der Zugang wurde nicht gespeichert."})
            verbunden = app.client is not None
            try:
                speichern()
            except OSError as err2:
                log.warning("Miniserver-Zugang nicht gespeichert: %s", err2)
                return web.json_response({"ok": False, "connected": verbunden, "fehler": f"{fehler} · {err2}",
                                          "error": "Miniserver nicht erreichbar, und der Zugang ließ sich nicht "
                                                   "speichern. Es bleibt beim bisherigen."}, status=500)
            app._zugang_neu = neu
            log.warning("Miniserver %s nicht erreichbar (%s), Zugang trotzdem gespeichert", host, fehler)
            return web.json_response({
                "ok": False, "gespeichert": True, "connected": verbunden, "fehler": fehler,
                "error": "Miniserver nicht erreichbar. Der Zugang ist trotzdem gespeichert: Die bestehende "
                         "Verbindung bleibt, der neue Zugang gilt ab dem nächsten Verbindungsaufbau." if verbunden
                else "Miniserver nicht erreichbar. Der Zugang ist trotzdem gespeichert, LoxPanel versucht es damit weiter."})
        # Audioserver-Clients merken sich den Benutzer beim Anlegen
        for cl in list(app.audio_clients.values()):
            await cl.close()
        app.audio_clients.clear()
        app._front_refresh.set()
        try:
            speichern()
        except OSError as err:
            log.warning("Miniserver verbunden, Zugang aber nicht gespeichert: %s", err)
            return web.json_response({"ok": False, "connected": True, "nControls": n, "fehler": str(err),
                                      "error": "Verbunden, aber der Zugang ließ sich nicht speichern. "
                                               "Nach einem Neustart gilt er nicht mehr."}, status=500)
    log.info("Miniserver-Settings gespeichert, verbunden (%d Controls)", n)
    return web.json_response({"ok": True, "connected": True, "nControls": n})


async def api_settings_night(request: web.Request) -> web.Response:
    """Nacht-Ausloeser: Baustein, dessen `active`-State den Nachtmodus schaltet.
    Leer = keiner, dann entscheiden die Sonnenzeiten."""
    app: App = request.app["app"]
    try:
        data = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        return web.json_response({"ok": False, "error": "kein gültiges JSON"}, status=400)
    u = str(data.get("control") or "").strip()
    if u and u not in app.controls:
        return web.json_response({"ok": False, "error": "Baustein nicht gefunden"}, status=400)
    cfg = _load_cfg()
    night = dict(cfg.get("night", {}) if isinstance(cfg.get("night"), dict) else {})
    night["control"] = u
    cfg["night"] = night
    try:
        _write_cfg(cfg)
    except OSError as err:
        return web.json_response({"ok": False, "error": str(err)}, status=500)
    app.night_cfg = _night_config()
    log.info("Nacht-Ausloeser gespeichert: %s", u or "(keiner -> Sonnenzeiten)")
    return web.json_response({"ok": True})


async def api_settings_audiometa(request: web.Request) -> web.Response:
    """Audioserver-Live-Daten (Gen-2-Event-Kanal) an/aus. Adressen werden
    automatisch aus der Struktur gelesen — es gibt nur den Master-Schalter."""
    app: App = request.app["app"]
    try:
        data = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        return web.json_response({"ok": False, "error": "kein gültiges JSON"}, status=400)
    cfg = _load_cfg()
    am = dict(cfg.get("audiometa", {}) if isinstance(cfg.get("audiometa"), dict) else {})
    am["enabled"] = bool(data.get("enabled"))
    cfg["audiometa"] = am
    try:
        _write_cfg(cfg)
    except OSError as err:
        return web.json_response({"ok": False, "error": str(err)}, status=500)
    app.audiometa_cfg = _audiometa_config()
    # Bei Deaktivierung laufende Clients sofort schliessen; beim Aktivieren
    # startet der audio_events_task sie beim naechsten Durchlauf automatisch.
    if not am["enabled"]:
        for cl in list(app.audio_clients.values()):
            await cl.close()
        app.audio_clients.clear()
    app._dirty = True
    log.info("Audioserver-Live-Daten %s", "aktiv" if am["enabled"] else "aus")
    return web.json_response({"ok": True})


async def api_settings_intercom(request: web.Request) -> web.Response:
    app: App = request.app["app"]
    try:
        data = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        return web.json_response({"ok": False, "error": "kein gültiges JSON"}, status=400)
    items = data.get("intercoms") or {}
    cfg = _load_cfg()
    ic = dict(cfg.get("intercom", {}))
    for uuid, e in items.items():
        if not isinstance(e, dict):
            continue
        cur = ic.get(uuid)
        cur = dict(cur) if isinstance(cur, dict) else ({"url": cur} if isinstance(cur, str) else {})
        cur["url"] = str(e.get("url", "")).strip()
        cur["user"] = str(e.get("user", "")).strip()
        if e.get("pass"):
            cur["pass"] = str(e["pass"])
        if cur.get("url"):
            ic[uuid] = cur
        else:
            ic.pop(uuid, None)
    cfg["intercom"] = ic
    try:
        _write_cfg(cfg)
    except OSError as err:
        return web.json_response({"ok": False, "error": str(err)}, status=500)
    app.intercom_cfg = _intercom_config()
    log.info("Intercom-Settings gespeichert (%d Einträge)", len(ic))
    return web.json_response({"ok": True})


async def api_sip(request: web.Request) -> web.Response:
    """Settings -> SIP: die Intercoms der Anlage mit ihrem SIP-Zugang aus den
    gesicherten Details. Das Passwort verlaesst den Server nie, die Routen haben
    keine Anmeldung; es heisst nur, ob es eines gibt (hasPass wie bei
    /api/settings). Nennt eine Intercom keinen, steht ohneSip darin und, wenn
    sie gesicherte Details hat, unter felder, welche Felder diese haben und ob
    sie gefuellt sind, ohne Werte.
    Laedt erst, wenn der Konfigurator den Reiter oeffnet: jede Intercom mit
    gesicherten Details kostet eine verschluesselte Anfrage an den Miniserver.
    type ist der Bausteintyp (Intercom = Tuersteuerung, IntercomV2 = Baustein
    Intercom), deviceType wie im Baustein (Strukturdoku 17.0): bei Intercom 0
    andere oder unbekannte Tuerstation, 1 Loxone Intercom, 2 Loxone Intercom
    XL; bei IntercomV2 0 andere oder unbekannte, 1 Loxone Intercom."""
    app: App = request.app["app"]
    liste = []
    for uuid, c in app.controls.items():
        if c.get("type") not in INTERCOM_TYPES:
            continue
        e = {"uuid": uuid, "name": _clean(c.get("name")), "type": c.get("type"),
             "room": _clean((app.rooms.get(c.get("room")) or {}).get("name")),
             "deviceType": (c.get("details") or {}).get("deviceType")}
        # ohneSip: der Miniserver nennt keinen SIP-Zugang (anders als bei einem
        # Fehler mit Verbindung oder Rechten); der Konfigurator sagt dann, wo er
        # in Loxone Config hingehoert
        try:
            details = await app.secured_details(uuid)
        except OhneGesicherteDetails as err:
            e.update(error=str(err), ohneSip=True)
        except ZugangFehler as err:
            e["error"] = str(err)
        else:
            sip = _sip_zugang(details)
            if sip:
                e["sip"] = {"host": sip["host"], "user": sip["user"], "hasPass": bool(sip["pass"])}
            else:
                e.update(error=KEIN_SIP, felder=_gesichert_felder(details), ohneSip=True)
        liste.append(e)
    liste.sort(key=lambda e: (e["name"].lower(), e["room"].lower()))
    return web.json_response({"connected": app.client is not None, "intercoms": liste})


async def api_sip_pruefen(request: web.Request) -> web.Response:
    """Settings -> SIP -> "Verbindung prüfen": OPTIONS an die Tuerstation mit
    dem SIP-Zugang aus den gesicherten Details (sip_probe). Body {"uuid"}. Die
    Adresse kommt vom Miniserver, nie aus der Anfrage: so schickt die Route die
    Anmeldung nur an die Tuerstation. Die Antwort sagt, ob sie angenommen
    wurde, das Passwort steht nicht darin."""
    app: App = request.app["app"]
    try:
        data = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        return web.json_response({"ok": False, "error": "kein gültiges JSON"}, status=400)
    uuid = str(data.get("uuid") or "") if isinstance(data, dict) else ""
    if (app.controls.get(uuid) or {}).get("type") not in INTERCOM_TYPES:
        return web.json_response({"ok": False, "error": "Unbekannte Intercom"}, status=404)
    try:
        sip = await app.intercom_sip(uuid)
    except ZugangFehler as err:
        return web.json_response({"ok": False, "error": str(err)})
    erg = await sip_probe.pruefen(sip["host"], sip["user"], sip["pass"])
    log.info("SIP-Prüfung %s: %s", erg.get("ziel"), erg.get("anmeldung") or erg.get("error"))
    return web.json_response({"ok": True, **erg})


def _native_talk(request: web.Request) -> None:
    """Nur die eingebettete App kennt den Prozess-Token; keine LAN-Call-API."""
    token = os.environ.get("LOXPANEL_INTERCOM_TOKEN", "")
    try:
        local = ipaddress.ip_address(request.remote or "").is_loopback
    except ValueError:
        local = False
    if not local or not token or not hmac.compare_digest(
            request.headers.get("X-LoxPanel-Intercom", ""), token):
        raise web.HTTPForbidden(text="Gegensprechen ist nur in der nativen LoxPanel-App verfügbar")


def _talk_session(data: dict) -> str:
    session = data.get("session")
    if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9-]{16,64}", session):
        raise web.HTTPBadRequest(text="Ungültige Verbindung")
    return session


async def _talk_json(request: web.Request) -> dict:
    try:
        data = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        raise web.HTTPBadRequest(text="Kein gültiges JSON") from None
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text="Kein gültiges JSON-Objekt")
    return data


async def api_intercom_talk_start(request: web.Request) -> web.Response:
    _native_talk(request)
    data = await _talk_json(request)
    session = _talk_session(data)
    uuid, port = data.get("uuid"), data.get("rtpPort")
    app: App = request.app["app"]
    if not isinstance(uuid, str) or (app.controls.get(uuid) or {}).get("type") != "Intercom":
        return web.json_response({"ok": False, "message": "Gegensprechen unterstützt nur die Intercom Gen-1"}, status=400)
    if type(port) is not int or not 1024 <= port <= 65535:
        return web.json_response({"ok": False, "message": "Ungültiger RTP-Port"}, status=400)
    try:
        result = await app.intercom_talk.start(session, uuid, port)
    except TalkBusy as err:
        return web.json_response({"ok": False, "message": str(err)}, status=409)
    return web.json_response(result)


async def api_intercom_talk_status(request: web.Request) -> web.Response:
    _native_talk(request)
    session = _talk_session(dict(request.query))
    return web.json_response(request.app["app"].intercom_talk.status(session))


async def api_intercom_talk_stop(request: web.Request) -> web.Response:
    _native_talk(request)
    session = _talk_session(await _talk_json(request))
    return web.json_response(await request.app["app"].intercom_talk.stop(session))


async def api_settings_calendar(request: web.Request) -> web.Response:
    """Kalender (iCal-Abos) + Wetter (Open-Meteo-Koordinaten) fuer die Front."""
    app: App = request.app["app"]
    try:
        data = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        return web.json_response({"ok": False, "error": "kein gültiges JSON"}, status=400)

    def _coord(v):
        # leer = nicht gesetzt; deutsches Komma erlauben; ausserhalb des Bereichs = ungueltig
        if v in (None, ""):
            return None
        try:
            f = float(str(v).replace(",", "."))
        except (TypeError, ValueError):
            return None
        return f if -90.0 <= f <= 180.0 else None

    def _int(v, default, lo, hi):
        try:
            return max(lo, min(hi, int(v)))
        except (TypeError, ValueError):
            return default

    cfg = _load_cfg()
    cal = dict(cfg.get("calendar", {}) if isinstance(cfg.get("calendar"), dict) else {})

    # Kalenderquellen NUR anfassen, wenn die Oberflaeche sie mitgeschickt hat.
    # Eine aeltere /config-Seite, die noch im Browser offen steht, kennt das
    # Feld nicht - ohne diese Pruefung loescht ihr "Speichern" saemtliche Abos.
    # Dasselbe gilt fuer die anderen neuen Felder weiter unten.
    roh = data.get("sources")
    if isinstance(roh, list):
        quellen, gesehen = [], set()
        for q in roh:
            if not isinstance(q, dict):
                continue
            url = front_info.normalize_ical_url(q.get("url"))
            # Doppelte URLs hier schon wegwerfen: calendar_sources() tut es
            # ohnehin, sonst stuenden sie in der Datei und die Oberflaeche
            # zeigte beim naechsten Laden weniger an, als gespeichert wurde.
            if not url or url in gesehen or len(quellen) >= front_info.MAX_SOURCES:
                continue
            gesehen.add(url)
            quellen.append({"name": str(q.get("name", "")).strip()[:40],
                            "url": url,
                            # Leer = spaeter die Vorschlagsfarbe der Position
                            "color": front_info.clean_color(q.get("color"), "")})
        cal["sources"] = quellen
        # Die alte Einzel-URL darf stehen bleiben, solange sie in der Liste
        # steht: calendar_sources() liest sie nur, wenn `sources` nichts
        # hergibt, ein Doppel-Kalender entsteht also nicht - und ein Downgrade
        # auf eine aeltere Version findet seinen Kalender noch vor. Erst wenn
        # der Benutzer sie aus der Liste genommen hat, verschwindet sie auch
        # hier, sonst kaeme sie beim Loeschen des letzten Abos zurueck.
        if front_info.normalize_ical_url(cal.get("ical_url")) not in gesehen:
            cal["ical_url"] = ""
    cal["holiday_url"] = str(data.get("holiday_url", "")).strip()
    cal["name"] = str(data.get("name", "")).strip() or "Family"
    if "colors" in data:
        cal["colors"] = bool(data.get("colors"))
    lat, lon = _coord(data.get("lat")), _coord(data.get("lon"))
    # Nur ein vollstaendiges Koordinatenpaar speichern (halb gesetzt = kein Wetter).
    cal["lat"] = lat if (lat is not None and lon is not None) else None
    cal["lon"] = lon if (lat is not None and lon is not None) else None
    cal["days"] = _int(data.get("days"), 14, 1, 60)
    cal["fore_days"] = _int(data.get("fore_days"), 4, 1, 7)
    if "sv_events" in data:
        cal["sv_events"] = _int(data.get("sv_events"), 3, 1, 10)
    cfg["calendar"] = cal
    try:
        _write_cfg(cfg)
    except OSError as err:
        return web.json_response({"ok": False, "error": str(err)}, status=500)
    app.calendar_cfg = _calendar_config()
    app._front_cal_due = 0.0   # Kalender sofort neu holen, nicht erst im naechsten Takt
    app._front_refresh.set()   # sofort neu laden und an die Panels schicken
    log.info("Kalender/Wetter gespeichert (%d iCal-Abo(s), Wetter %s)",
             len(front_info.calendar_sources(cal)),
             "gesetzt" if cal["lat"] is not None else "leer")
    return web.json_response({"ok": True})


# ---- Panel-Agenten (Fernstart der Displays) ----
async def api_agent_announce(request: web.Request) -> web.Response:
    """Panel-Agent meldet sich periodisch (Auto-Discovery). Steht fuer ihn eine
    Ansicht an (agent_wunsch) und kann er sie uebernehmen, nennt die Antwort
    sie als `panel`, und die Geraeteeinstellungen gelten schon fuer sie."""
    app: App = request.app["app"]
    try:
        d = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        d = {}
    ip = str(d.get("ip") or "").strip() or request.remote or "?"
    feats = d.get("features")
    feats = [f for f in feats if isinstance(f, str)][:8] if isinstance(feats, list) else []
    panel = str(d.get("panel") or "")
    app.agents[ip] = {"ip": ip, "name": str(d.get("name") or ip)[:60],
                      "panel": panel, "port": int(d.get("port") or 8130),
                      "kiosk": bool(d.get("kiosk")), "ts": time.time(), "features": feats}
    wunsch = app.agent_wunsch.get(ip)
    if wunsch is not None and (wunsch == panel or AGENT_KANN_PANEL not in feats):
        app.agent_wunsch.pop(ip, None)   # gemeldet, also uebernommen
        wunsch = None
    # Keine offene Wahl: meldet der Agent eine andere Ansicht als die, die dem
    # Geraet zusteht (Zuordnung oder Betriebsmodus, Schritt 2), bekommt er sie -
    # so gilt sie auch nach einem Neustart des Panels mit altem PANEL in der kiosk.conf
    if wunsch is None and AGENT_KANN_PANEL in feats:
        soll = app.ansicht_fuer_geraet(app.agents[ip]["name"])
        if soll is not None and soll != app.ansicht_wirksam(panel):
            wunsch = soll
    pid = panel if wunsch is None else wunsch
    # Panel-spezifische Geraeteeinstellungen an den Agenten zurueckgeben
    # (der wendet sie am Geraet an, z.B. Display-Abschaltung per xset).
    out = {"ok": True, "dpmsOff": app.panel_dpms(pid, dev=app.agents[ip]["name"]), "reloadHours": app.panel_reload(pid)}
    if wunsch is not None:
        out["panel"] = wunsch
    return web.json_response(out)


async def api_agents(request: web.Request) -> web.Response:
    app: App = request.app["app"]
    now = time.time()
    out = [{**a, "online": (now - a["ts"]) < AGENT_ONLINE}
           for a in app.agents.values() if (now - a["ts"]) < 600]
    out.sort(key=lambda a: a["name"])
    return web.json_response({"agents": out})


async def api_agent_command(request: web.Request) -> web.Response:
    """Leitet Start/Reload/Stop an den Panel-Agenten weiter."""
    app: App = request.app["app"]
    try:
        d = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        return web.json_response({"ok": False, "error": "kein JSON"}, status=400)
    ip = str(d.get("ip", ""))
    action = str(d.get("action", ""))
    a = app.agents.get(ip)
    if not a:
        return web.json_response({"ok": False, "error": "Gerät nicht bekannt"}, status=404)
    if action not in ("start", "reload", "stop"):
        return web.json_response({"ok": False, "error": "unbekannte Aktion"}, status=400)
    payload = {"panel": str(d.get("panel") or "")} if action == "start" else {}
    # "Start" mit Ansicht ist eine ausdrueckliche Wahl wie "Ansicht wechseln"
    # (bei gestopptem Kiosk der einzige Weg dazu)
    wahl = action == "start"
    if wahl:
        app.agent_wunsch.pop(ip, None)   # neuer als eine noch offene Wahl
        if payload["panel"] and payload["panel"] not in app.panels:
            return web.json_response({"ok": False, "error": "unbekannte Ansicht"}, status=400)
        try:
            app.geraet_zuordnen(a["name"], payload["panel"])   # die Wahl ist die Zuordnung (Schritt 2)
        except Exception as err:
            return web.json_response({"ok": False, "error": f"Zuordnung nicht gespeichert: {err}"}, status=500)
    elif action == "reload" and ip in app.agent_wunsch:
        # Wahl noch nicht gemeldet: mit ihr neu starten, sonst oeffnete der
        # Agent die alte Ansicht und uebernaehme die neue erst danach. Sie
        # bleibt stehen, bis er sie meldet: scheitert der Befehl, uebernimmt
        # er sie mit der naechsten Meldung.
        action, payload = "start", {"panel": app.agent_wunsch[ip]}
    url = f"http://{a['ip']}:{a['port']}/{action}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=AGENT_BEFEHL_TIMEOUT)) as r:
                body = await r.text()
                log.info("Agent %s %s -> %s", ip, action, r.status)
                if wahl and r.status == 200:
                    # hebt den Betriebsmodus fuer das Geraet auf: sonst zoege
                    # ws_handler die Visu auf dessen Profil, der Agent bliebe
                    # bei der Wahl
                    app.ansicht_gewaehlt.add(a["name"])
                return web.json_response({"ok": r.status == 200, "status": r.status,
                                          "body": body[:200]})
    except Exception as err:
        return web.json_response({"ok": False, "error": str(err)})


async def api_mode(request: web.Request) -> web.Response:
    """Betriebsmodus-Wechsel von Loxone (virtueller Ausgang). Loxone schickt nur
    den Modusnamen, z.B.  GET /api/mode/gaeste  oder  /api/mode?name=gaeste .
    Die Zuordnung Modus -> Profil je Panel liegt in den Panel-Einstellungen."""
    app: App = request.app["app"]
    mode = request.match_info.get("mode", "")
    if not mode:
        mode = request.query.get("name") or request.query.get("mode") or ""
    if not mode and request.method == "POST":
        try:
            d = await request.json()
            mode = str(d.get("name") or d.get("mode") or "")
        except (ValueError, aiohttp.ContentTypeError):
            pass
    if not mode:
        return web.json_response({"ok": False, "error": "kein Modus angegeben"},
                                 status=400)
    results = await app.switch_mode(mode)
    log.info("Betriebsmodus '%s' -> %d Panel(s) umgeschaltet", mode, len(results))
    return web.json_response({"ok": True, "mode": mode, "switched": results})


async def api_save_devices(request: web.Request) -> web.Response:
    """Speichert die Betriebsmodus-Automatik je Panel (aus den Einstellungen)."""
    app: App = request.app["app"]
    try:
        d = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        return web.json_response({"ok": False, "error": "kein JSON"}, status=400)
    roh = d.get("devices") or {}
    # Die Zuordnung Gerät -> Ansicht (panel) setzt nur /api/device/switch; nennt
    # ein Geraet sie nicht, bleibt die gespeicherte (wie das Display-Kennwort)
    if isinstance(roh, dict):
        for name, cfg in roh.items():
            if isinstance(cfg, dict) and "panel" not in cfg and (app.devices.get(name) or {}).get("panel"):
                cfg["panel"] = app.devices[name]["panel"]
    devices = App._sanitize_devices(roh, set(app.panels))
    # Leeres Display-Kennwort = unveraendert (/api/meta gibt es nicht heraus),
    # aber nur beim selben Ziel wie beim Einspielen (_KENNWORT_ZIEL), sonst
    # ginge das gespeicherte an einen anderen Host. "verworfen": eines war da,
    # das Ziel ist ein anderes. Vor _write_devices, das app.devices ersetzt.
    _, verworfen = _kennwoerter_einsetzen(
        {"devices": devices}, {"devices": app.devices},
        [("devices", n, "display", "password") for n, e in devices.items() if "display" in e],
        nur_wo_eins_war=True)
    try:
        app._write_devices(devices)
    except Exception as err:
        return web.json_response({"ok": False, "error": str(err)}, status=500)
    # Skalierung je Geraet sofort wirksam machen: jedem verbundenen Panel
    # seinen (evtl. neuen) wirksamen Faktor schicken - ohne Neuladen, das
    # beim Speichern von Profilen noetig ist, hier aber nicht.
    for ws, info in list(app.conn_info.items()):
        await app._send_or_drop(ws, {"t": "scale", "scale": app.effective_scale(
            app.conn_prof.get(ws), info.get("dev", ""))})
        # ... und die Zielkachel je Geraet: die Visu baut ihr Raster neu
        await app._send_or_drop(ws, {"t": "gridAuto", "gridAuto": app.effective_grid_auto(
            app.conn_prof.get(ws), info.get("dev", ""))})
    return web.json_response({"ok": True, "devices": App._devices_export(devices),
                              "kennwortVerworfen": [p[1] for p in verworfen]})


async def api_devices_get(request: web.Request) -> web.Response:
    """Alle Anzeigegeraete (Agent, Kiosk-App, Browser) mit Online-Status,
    Ansicht und Typ; Browser ohne Namen getrennt nach IP. Dazu der Stand des
    Servers: der Konfigurator fragt hier alle paar Sekunden nach und laedt
    nach einem Update neu."""
    app: App = request.app["app"]
    return web.json_response({**app.device_list(), "stand": server_stand()})


async def api_device_switch(request: web.Request) -> web.Response:
    """Ansicht eines Geraets wechseln: {device, panel, ip}. Die offene Visu
    wechselt per WebSocket-Push (Browser laedt sich mit neuem Profil neu).
    Hat das Geraet einen Agenten, der online ist, erfaehrt er die Wahl, damit
    sie Kiosk-Neustarts uebersteht und Abschaltzeit und Neustartintervall des
    neuen Profils gelten. Zugeordnet ueber `ip` aus der Geraeteliste, nicht
    ueber den Namen: geklonte Panels melden denselben Hostnamen. Ein Agent mit
    AGENT_KANN_PANEL uebernimmt sie mit seiner naechsten Meldung ohne
    Chromium-Neustart (`agent: "announce"`, auch bei gestopptem Kiosk: der
    startet dann damit). Einen aelteren Agenten, und jeden, dessen Kiosk ohne
    offene Visu laeuft, startet /start mit dem neuen Profil neu (`agent:
    "start"`; scheitert das bei einem Agenten mit AGENT_KANN_PANEL, uebernimmt
    er sie mit der naechsten Meldung: "announce"; "" = der Agent hat die Wahl
    nicht). Die Wahl hebt den Betriebsmodus fuer das Geraet auf."""
    app: App = request.app["app"]
    try:
        d = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        return web.json_response({"ok": False, "error": "kein JSON"}, status=400)
    device = str(d.get("device") or "").strip()
    panel = str(d.get("panel") or "").strip()
    if not device:
        return web.json_response({"ok": False, "error": "device fehlt"}, status=400)
    # Vorschau eines Entwurfs am Geraet (Punkt 12): {entwurf: <Token von /api/entwurf>}. Das Profil
    # muss nicht gespeichert sein (der Assistent zeigt eines, das es noch nicht gibt), der Token
    # gehoert aber zu ihm. Nur eine verbundene Visu kann ihn zeigen: ein Agent startet den Kiosk
    # mit einer Adresse ohne Token und wuerde stattdessen das Profil von der Platte zeigen.
    tok = str(d.get("entwurf") or "").strip()
    if tok:
        if not panel or app.entwurf_profil(tok, panel) is None:
            return web.json_response({"ok": False, "error": "Entwurf unbekannt oder abgelaufen"}, status=400)
        zurueck = app.vorschau_zurueck(device)
        n = await _push(app, {"t": "switch", "panel": panel, "entwurf": tok}, "", device)
        if not n:
            return web.json_response({"ok": False, "sent": 0,
                                      "error": "Keine verbundene Visu – eine Vorschau braucht sie"})
        app.vorschau_ende.pop(device, None)
        for info in app.conn_info.values():   # unterwegs zum Entwurf (laedt gleich neu): vorschau_beenden
            if info.get("dev") == device and not info.get("neuLaden") and info.get("entwurf") != tok:
                info["entwurfKommt"] = tok
        app.vorschau_geraet[device] = {"token": tok, "id": panel, "zurueck": zurueck,
                                       "bis": time.time() + VORSCHAU_GERAET_DAUER}
        return web.json_response({"ok": True, "sent": n, "via": "ws", "agent": "", "zurueck": zurueck})
    if panel and panel not in app.panels:
        return web.json_response({"ok": False, "error": "unbekannte Ansicht"}, status=400)
    app.vorschau_geraet.pop(device, None)   # eine ausdrueckliche Wahl beendet eine Vorschau am Geraet
    app.vorschau_ende.pop(device, None)
    # Die Wahl ist die Zuordnung des Geraets (Einrichtung Schritt 2): gespeichert,
    # damit sie jeden Neustart, jede Start-Adresse und die kiosk.conf ueberlebt.
    # Ein Geraet, das gerade nicht online ist, zieht ws_handler beim Verbinden darauf.
    try:
        app.geraet_zuordnen(device, panel)
    except Exception as err:
        return web.json_response({"ok": False, "error": f"Zuordnung nicht gespeichert: {err}"}, status=500)
    n = await _push(app, {"t": "switch", "panel": panel}, "", device)
    a = app.agents.get(str(d.get("ip") or "").strip())
    weg, ok = "", False
    if a and a["name"] == device and time.time() - a["ts"] < AGENT_ONLINE:
        if AGENT_KANN_PANEL in a.get("features", ()) and (n or not a["kiosk"]):
            app.agent_wunsch[a["ip"]] = panel
            weg, ok = "announce", True
        elif a["kiosk"]:
            weg, ok = "start", await app._agent_start(a, panel)
            if not ok and AGENT_KANN_PANEL in a.get("features", ()):
                weg, ok = "announce", True   # Wahl liegt in agent_wunsch (_agent_start)
    app.ansicht_gewaehlt.add(device)
    if n:
        return web.json_response({"ok": True, "sent": n, "via": "ws", "agent": weg if ok else ""})
    if ok:
        return web.json_response({"ok": True, "sent": 1, "via": "agent", "agent": weg})
    # nicht online: die Zuordnung steht, das Geraet zeigt sie, sobald es verbindet
    return web.json_response({"ok": True, "sent": 0, "via": "", "agent": "", "offline": True})


async def api_vorschau_beenden(request: web.Request) -> web.Response:
    """Vorschau am Geraet beenden: {device}. Es kehrt zum Profil zurueck, das es vor
    der Vorschau zeigte. `beendet` sagt, ob eine Visu zurueckgeschaltet wurde."""
    app: App = request.app["app"]
    try:
        d = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        return web.json_response({"ok": False, "error": "kein JSON"}, status=400)
    device = str(d.get("device") or "").strip()
    if not device:
        return web.json_response({"ok": False, "error": "device fehlt"}, status=400)
    return web.json_response({"ok": True, "beendet": await app.vorschau_beenden(device) > 0})


async def api_device_name(request: web.Request) -> web.Response:
    """Gibt einem Browser ohne Namen einen Geraetenamen: {code, name} trifft
    genau die Verbindung mit diesem Kopplungscode, {ip, name} alle ohne
    Namen unter der IP (wie bisher). Die Visu merkt sich den Namen
    (localStorage) und verbindet sich neu."""
    app: App = request.app["app"]
    try:
        d = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        return web.json_response({"ok": False, "error": "kein JSON"}, status=400)
    ip = str(d.get("ip") or "").strip()
    code = str(d.get("code") or "").strip().upper()
    name = str(d.get("name") or "").strip()[:60]
    if not (ip or code) or not name:
        return web.json_response({"ok": False, "error": "code oder ip und name noetig"}, status=400)
    n = 0
    for ws, info in list(app.conn_info.items()):
        if info.get("dev") or (info.get("code") != code if code else info.get("ip") != ip):
            continue
        try:
            await ws.send_json({"t": "setdevice", "name": name})
            n += 1
        except ConnectionError:
            pass
    fehler = "kein Gerät ohne Namen mit diesem Code" if code else "kein Gerät ohne Namen unter dieser IP"
    return web.json_response({"ok": n > 0, "sent": n, **({} if n else {"error": fehler})})


async def api_display(request: web.Request) -> web.Response:
    """Display der Panels schalten: ?on=1|0, optional ?panel= / ?device=.
    Wirkt auf Geraete mit Kiosk-App (Fully Kiosk, LoxPanel-App), die die Visu offen haben;
    Linux-Panels mit Agent regeln das Display selbst. Auch aus Loxone nutzbar."""
    app: App = request.app["app"]
    d = await _json_or_empty(request)
    raw = d.get("on", request.query.get("on"))
    if isinstance(raw, bool):
        on = raw
    else:
        v = str(raw if raw is not None else "").strip().lower()
        if v in ("1", "true", "on", "an", "ein"):
            on = True
        elif v in ("0", "false", "off", "aus"):
            on = False
        else:
            return web.json_response({"ok": False, "error": "on=1|0 fehlt"}, status=400)
    panel, device = _push_filter(request, d)
    n = await _push(app, {"t": "display", "on": on}, panel, device)
    drivers = await app.display_drivers(on, device, panel)
    return web.json_response({"ok": True, "sent": n, "on": on, "drivers": drivers})


async def _push(app: "App", msg: dict, panel: str = "", device: str = "") -> int:
    """Push an offene Visu-Verbindungen, siehe App.push(); die Routen rufen
    weiter diese Huelle."""
    return await app.push(msg, panel, device)


def _push_filter(request: web.Request, d: dict) -> tuple:
    """panel/device-Filter aus Query ODER JSON lesen."""
    return (str(d.get("panel") or request.query.get("panel") or ""),
            str(d.get("device") or request.query.get("device") or ""))


async def _json_or_empty(request: web.Request) -> dict:
    if request.method == "POST":
        try:
            return await request.json()
        except (ValueError, aiohttp.ContentTypeError):
            return {}
    return {}


async def api_reload(request: web.Request) -> web.Response:
    """Laedt offene Panels neu (Server -> Browser). Optional ?panel= / ?device=.
    Auch aus Loxone per virtuellem Ausgang nutzbar."""
    app: App = request.app["app"]
    d = await _json_or_empty(request)
    panel, device = _push_filter(request, d)
    n = await _push(app, {"t": "reload"}, panel, device)
    return web.json_response({"ok": True, "reloaded": n})


async def api_goto(request: web.Request) -> web.Response:
    """Schickt offene Panels auf eine Seite. ?control=<uuid> (Detailseite) ODER
    ?tab=<favoriten|zentral|raeume|kategorien|kalender|wetter|auswahl|cat:...|room:...>.
    Optional ?panel= / ?device=."""
    app: App = request.app["app"]
    d = await _json_or_empty(request)
    control = str(d.get("control") or d.get("uuid") or request.query.get("control")
                  or request.query.get("uuid") or "").strip()
    tab = str(d.get("tab") or request.query.get("tab") or "").strip()
    if control:
        route = {"view": "control", "id": control}
    elif _is_tab(tab):
        route = {"view": "tab", "tab": tab}
    else:
        return web.json_response({"ok": False, "error": "control oder gueltiges tab noetig"},
                                 status=400)
    panel, device = _push_filter(request, d)
    n = await _push(app, {"t": "goto", "route": route}, panel, device)
    app._spawn(app.display_drivers(True, device, panel))   # Kiosk-Apps wecken
    return web.json_response({"ok": True, "route": route, "sent": n})


async def api_notify(request: web.Request) -> web.Response:
    """Blendet auf offenen Panels eine kurze Nachricht ein.
    ?text=... [&level=info|warn|crit] [&secs=5] [&panel=|&device=]."""
    app: App = request.app["app"]
    d = await _json_or_empty(request)
    text = str(d.get("text") or request.query.get("text") or "").strip()[:200]
    if not text:
        return web.json_response({"ok": False, "error": "text fehlt"}, status=400)
    level = str(d.get("level") or request.query.get("level") or "info").strip()
    if level not in ("info", "warn", "crit"):
        level = "info"
    try:
        secs = int(float(d.get("secs") or request.query.get("secs") or 5))
    except (TypeError, ValueError):
        secs = 5
    secs = max(1, min(60, secs))
    panel, device = _push_filter(request, d)
    app._spawn(app.display_drivers(True, device, panel))   # Kiosk-Apps wecken
    n = await _push(app, {"t": "notify", "text": text, "level": level, "secs": secs},
                    panel, device)
    return web.json_response({"ok": True, "sent": n})


async def api_testtone(request: web.Request) -> web.Response:
    """Schickt einen kurzen Test-Weckton an die Panel-Browser (zum Pruefen der
    Audio-Ausgabe am Geraet, z.B. YC-41PM). Mit `panel` auf ein Profil begrenzt,
    sonst an alle offenen Visu-Verbindungen. Der Ton wird im Browser per Web
    Audio erzeugt (derselbe Weg wie der echte Weckton)."""
    app: App = request.app["app"]
    try:
        d = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        d = {}
    target = str(d.get("panel") or "").strip()
    n = 0
    for ws, prof in list(app.conn_prof.items()):
        if target and (prof or {}).get("id") != target:
            continue
        if await app._send_or_drop(ws, {"t": "testtone"}):
            n += 1
    return web.json_response({"ok": True, "sent": n})


async def icon_handler(request: web.Request) -> web.Response:
    app: App = request.app["app"]
    p = request.query.get("p", "")
    if not p or ".." in p or not (p.endswith(".svg") or p.endswith(".png")):
        return web.Response(status=400, text="bad icon")
    res = await app.fetch_icon(p)
    if not res:
        return web.Response(status=404)
    body, ctype = res
    return web.Response(body=body, content_type=ctype.split(";")[0],
                        headers={"Cache-Control": "max-age=86400"})


async def loxicons_handler(request: web.Request) -> web.Response:
    """Namen der Loxone-Bibliothek (fuer den Kachel-Editor, lazy geladen)."""
    return web.json_response({"icons": _loxlib_names()})


async def loxlib_handler(request: web.Request) -> web.Response:
    """Ein SVG der Loxone-Bibliothek aus dem gemounteten Ordner ausliefern.
    Nur flache, validierte Dateinamen - kein Pfad-Ausbruch."""
    n = request.query.get("n", "")
    if not _LOXLIB_NAME.match(n) or ".." in n:
        return web.Response(status=400, text="bad")
    path = os.path.join(LOXLIB_DIR, n)
    if os.path.dirname(os.path.abspath(path)) != os.path.abspath(LOXLIB_DIR):
        return web.Response(status=400, text="bad")
    try:
        with open(path, "rb") as f:
            body = f.read()
    except OSError:
        return web.Response(status=404)
    return web.Response(body=body, content_type="image/svg+xml",
                        headers={"Cache-Control": "max-age=86400"})


async def bellimg_handler(request: web.Request) -> web.Response:
    """Bild einer verpassten Klingel (/bellimg?id=<Intercom>&ts=JJJJMMTTHHMMSS),
    vom Miniserver geholt (fetch_bell_image)."""
    app: App = request.app["app"]
    c = app.controls.get(request.query.get("id", ""))
    ts = request.query.get("ts", "")
    if not c or c.get("type") != "Intercom" or not _BELL_TS.fullmatch(ts):
        return web.Response(status=400, text="bad bell image")
    res = await app.fetch_bell_image(c.get("uuidAction") or "", ts)
    if not res:
        return web.Response(status=404)
    body, ctype = res
    return web.Response(body=body, content_type=ctype.split(";")[0],
                        headers={"Cache-Control": "max-age=86400"})


async def cover_handler(request: web.Request) -> web.Response:
    app: App = request.app["app"]
    u = request.query.get("u", "")
    if not (u.startswith("http://") or u.startswith("https://")):
        return web.Response(status=400, text="bad cover")
    res = await app.fetch_cover(u)
    if not res:
        return web.Response(status=404)
    body, ctype = res
    return web.Response(body=body, content_type=ctype.split(";")[0],
                        headers={"Cache-Control": "max-age=60"})


async def mjpeg_handler(request: web.Request) -> web.StreamResponse:
    """Relais des MJPEG-Streams der Tuerstation (mit Auth) -> Browser. Die
    Kamera kommt aus LoxPanel oder vom Miniserver (App.intercom_video).

    Eigene ClientSession (nicht icon_session): mit dem SSL-Connector der
    icon_session liefert die Mobotix nur ein Einzelbild statt des Streams.
    """
    app: App = request.app["app"]
    cam = await app.intercom_video(request.query.get("id", ""))
    if cam is None:
        return web.Response(status=404)
    url = cam["url"]
    # Session und Antwort der Kamera werden in jedem Fall freigegeben, auch
    # wenn der Handler mitten im Verbindungsaufbau abgebrochen wird
    # (Herunterfahren) - sonst bleiben Socket und Connector offen.
    sess = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_read=30))
    upstream = None
    try:
        try:
            auth = aiohttp.BasicAuth(cam["user"], cam["pass"]) if cam["user"] else None
            upstream = await sess.get(url, auth=auth)
        except (aiohttp.ClientError, ValueError):
            # ValueError: unbrauchbarer Host ("cam..lan") oder Benutzer, der nicht
            # in den Basic-Auth-Kopf passt (Doppelpunkt, Zeichen ausserhalb Latin-1)
            return web.Response(status=502, text="camera unreachable")
        if upstream.status != 200:
            return web.Response(status=502, text=f"camera status {upstream.status}")

        ctype = upstream.headers.get("Content-Type", "multipart/x-mixed-replace")
        resp = web.StreamResponse(status=200, headers={
            "Content-Type": ctype, "Cache-Control": "no-cache, no-store"})
        await resp.prepare(request)
        try:
            async for chunk in upstream.content.iter_any():
                await resp.write(chunk)
        except (aiohttp.ClientError, ConnectionResetError, asyncio.CancelledError):
            pass
        return resp
    finally:
        if upstream is not None:
            upstream.release()
        await sess.close()


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    app: App = request.app["app"]
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    dev = (request.query.get("device", "") or "").strip()[:60]
    pid = request.query.get("panel", "")
    # ?entwurf=<Token>: ein noch nicht gespeichertes Profil (Vorschau aus dem Konfigurator).
    # Er geht der Geraete-Zuordnung unten vor: ein Vorschau-Fenster erbt die Geraetekennung
    # aus dem localStorage (derselbe Ursprung) und wuerde sonst auf ein fremdes Profil
    # umgelenkt. Unbekannt, abgelaufen oder fuer ein anderes Profil: das gespeicherte.
    ent = (request.query.get("entwurf", "") or "")[:64]
    roh = app.entwurf_profil(ent, pid) if ent else None
    agenten = app._agenten_der_visu(dev, request.remote or "") if dev else []
    # Wahl, die der Agent noch nicht gemeldet hat: Chromium startete vorher neu
    # (Absturz, Auto-Reload, Neustart des Agenten) und fragt nach der alten
    # Ansicht. Die Visu zeigt schon die, die der Agent gleich uebernimmt.
    offen = next((app.agent_wunsch[a["ip"]] for a in agenten if a["ip"] in app.agent_wunsch), None)
    if offen is not None and roh is None:
        pid = offen
    # Frisch verbundenes Geraet direkt auf die Ansicht setzen, die ihm zusteht
    # (ansicht_fuer_geraet: laufender Betriebsmodus, sonst die zugeordnete),
    # statt der Start-Ansicht aus ?panel= -> ohne Reload-Flackern gleich die
    # richtige Visu. Was in der Start-Adresse oder der kiosk.conf steht, gilt
    # nur noch fuer ein Geraet ohne Zuordnung.
    if dev and roh is None and offen is None:
        soll = app.ansicht_fuer_geraet(dev)
        if soll is not None and soll != app.ansicht_wirksam(pid):
            pid = soll
            # auch dem Agenten, sonst meldete er weiter ?panel= (dessen
            # Abschaltzeit und Neustartintervall, naechster Kiosk-Start)
            for a in agenten:
                app.agent_wunsch[a["ip"]] = soll
    prof = app.resolve_profile(pid, roh)
    app.conn_prof[ws] = prof
    app.conn_dev[ws] = dev
    kiosk = request.query.get("kiosk", "")
    app.conn_info[ws] = {"dev": dev, "kiosk": kiosk if kiosk in KIOSK_APPS else "",
                         "ip": request.remote or "", "ts": time.time()}
    if prof.get("entwurf"):
        app.conn_info[ws]["entwurf"] = ent   # api_entwurf laedt diese Vorschau bei Aenderungen neu
    if ent:
        app.conn_info[ws]["vorschau"] = True   # Vorschaufenster, auch mit abgelaufenem Token: kein Geraet
    if not dev:   # Browser ohne Namen: Kopplungscode (mitgeschickt oder neu)
        app.conn_info[ws]["code"] = app.kopplungscode(request.query.get("code", ""))
    first_tab = prof["tabs"][0] if prof["tabs"] else "favoriten"
    app.conn_route[ws] = {"view": "tab", "tab": first_tab}
    log.info("Panel verbunden: '%s' (Tabs %s, Räume %s, Kategorien %s)", prof["id"],
             prof["tabs"], "alle" if prof["rooms"] is None else len(prof["rooms"]),
             "alle" if prof["cats"] is None else len(prof["cats"]))
    # Display-Einstellungen gehen auch an die Visu: ohne Agent (Android-Panel,
    # Tablet mit Kiosk-App) schaltet die Seite das Display selbst ab und laedt
    # sich periodisch neu. `agent` sagt ihr, ob ein Agent das uebernimmt.
    await ws.send_json({"t": "theme", "vars": prof["vars"], "tabs": prof["tabs"],
                        "tabMeta": app._tab_meta(prof["tabs"], prof), "title": prof["title"],
                        "lang": prof["lang"], "fill": prof["fill"], "split": prof["split"],
                        "catFilter": prof["catFilter"],   # Leiste filtert statt zu springen
                        "tileLayout": prof["tileLayout"],  # Kachel-Aufbau ("" = neu, "classic")
                        "tileSet": prof["tileSet"],        # Kachel-Set ("" = Standard)
                        "tileSetAufbau": prof["tileSetAufbau"],   # ... seine Kachel-Art ("lx"|"mitte"|"kreis")
                        "tileSetLeiste": prof["tileSetLeiste"],   # ... seine Tab-Leiste ("pille"|"oben"|"links")
                        "gridAuto": app.effective_grid_auto(prof, dev),   # automatisches Raster: Zielkachel px (Geraet vor Profil), 0 = fest
                        "gridGrow": KACHEL_WACHSEN,   # ... Kacheln wachsen bis dahin, wenn alle auf eine Seite passen
                        "paneCols": prof["paneCols"],   # Widget-Breite in Kachelspalten (0 = Automatik)
                        "paneShare": PANE_ANTEIL,       # ... Anteil der Spalten in der Automatik
                        "panes": prof.get("panes") or {},
                        "svPane": prof.get("svPane") or "",   # rechte Spalte der Uhr-Seite
                        "scale": app.effective_scale(prof, dev),  # Skalierung (Geraet vor Profil)
                        "dpmsOff": app.panel_dpms(prof["id"], roh, dev),
                        "pinMerken": prof["pinMerken"],   # Visu-PIN behalten, Sek. (0 = jedes Mal)
                        "gesten": prof["gesten"],         # Zwei-Finger-Gesten (Loxone-Standard) an
                        # ... mit Hinweis-Symbol (reserviert die Fusszeile unter dem Kachelfeld)
                        "gestenHinweis": prof["gesten"] and prof["gestenHinweis"],
                        "reloadHours": app.panel_reload(prof["id"], roh),
                        "reloadAt": NEULADEN_STUNDE,   # nachts neu laden, wenn reloadHours fehlt
                        "night": {**app.panel_night(prof["id"], roh, dev), "on": app._night_on},
                        # Meldet der Praesenzmelder des Geraets gerade jemanden,
                        # bleibt das Display an - auch nach einem Neuladen.
                        "presence": app._presence_on.get(dev, False),
                        "agent": app._has_agent(dev),
                        # Vorschau eines ungespeicherten Entwurfs: die Visu kennzeichnet sie;
                        # ein Token, der nichts mehr trifft (abgelaufen), meldet sie auch
                        "entwurf": bool(prof.get("entwurf")) if ent else None,
                        "stand": server_stand()})   # anderer Stand als beim Laden: Seite neu laden
    _first = app.render(app.conn_route[ws], prof)
    await ws.send_json(_first)
    app._last_sent.setdefault(ws, {})["view"] = _first
    # Vorschau am Geraet beendet, waehrend es neu lud oder offline war: gleich zurueck. Auch
    # mit einem inzwischen abgelaufenen Token - sonst zeigte es das Profil des Entwurfs
    ende = app.vorschau_ende.get(dev) if dev and ent else None
    if ende and ende["token"] == ent:
        del app.vorschau_ende[dev]
        await app._neu_laden(ws, {"t": "switch", "panel": ende["zurueck"], "entwurf": ""})
    # Einrichtungshinweis, solange es keine Struktur vom Miniserver gibt
    await app._einrichtung_melden(neu=ws)
    # Verbindungszustand (Miniserver erreichbar?) und Takt des Lebenszeichens
    await app._verbindung_melden(neu=ws)
    # Browser ohne Namen: Kopplungscode, und die Karte "Dieses Geraet
    # einrichten" nur ohne ?panel= in der Adresse. Mit ?panel= hat jemand das
    # Geraet bewusst eingerichtet (Fully, WallPanel, alte Start-Adresse): die
    # Karte laege sonst nach jedem Neustart ueber der Visu und fienge die
    # Tipps ab. Der Konfigurator meldet das Geraet mit seinem Code trotzdem
    # (Banner "Neues Geraet gefunden", device_list anonymous[].code). Ein
    # Vorschaufenster des Konfigurators (?entwurf=) ist kein Geraet: kein Code.
    if not dev and not ent:
        await ws.send_json(App._kopplung_msg(app.conn_info[ws]["code"], not request.query.get("panel")))
    # Player-Pane fordert der Client selbst an (setplayer), sobald ein Tab mit
    # Player-Pane aktiv ist — je Tab eine eigene Zone moeglich.
    # Kalender/Wetter fuer die Uhr-Startseite sofort mitschicken (falls schon geladen)
    if app._front is not None:
        await ws.send_json(app._front)
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except ValueError:
                continue
            if data.get("t") == "nav" and isinstance(data.get("route"), dict):
                route = data["route"]
                app.conn_route[ws] = route
                try:
                    view_msg = app.render(route, app.conn_prof.get(ws, prof))
                except Exception:
                    # Detailseite wirft -> nicht die Verbindung abreissen lassen
                    # (sonst Reconnect-Loop). Fehler loggen, Hinweis anzeigen.
                    log.exception("render() (nav) fehlgeschlagen fuer route %s", route)
                    view_msg = {"t": "view", "title": "Fehler", "route": route,
                                "blocks": [{"k": "status", "text": "Diese Ansicht konnte nicht geladen werden."}]}
                await ws.send_json(view_msg)
                # Auch die Navigation sendet am Tick vorbei — eintragen, sonst
                # schickt der naechste Tick dieselbe Ansicht ein zweites Mal.
                app._last_sent.setdefault(ws, {})["view"] = view_msg
                # Beim Oeffnen einer AudioZone / Musikauswahl die Zonen-Favoriten
                # aktiv anfordern; das frische Ergebnis wird per broadcaster
                # nachgereicht (roomfav/get befuellt den sourceList-State).
                if route.get("view") in ("control", "sources") and route.get("id"):
                    task = asyncio.create_task(app.prime_favs(route["id"]))
                    app.bg_tasks.add(task)
                    task.add_done_callback(app.bg_tasks.discard)
            elif data.get("t") == "idle":
                # Visu ohne Kiosk-JS meldet Leerlauf -> Display ueber Treiber aus,
                # ausser der Praesenzmelder des Geraets sieht gerade jemanden
                if dev and not app._presence_on.get(dev):
                    app._spawn(app.display_drivers(False, dev))
            elif data.get("t") == "cmd":
                pin = data.get("pin")
                code = await app.command(data.get("uuid"), data.get("cmd"), pin)
                if pin is not None:
                    # uuid/cmd: die Visu ordnet das Ergebnis ihrem Befehl zu
                    # (Druecken und Loslassen kommen kurz hintereinander);
                    # code None = keine Antwort, keine abgelehnte PIN.
                    await ws.send_json({"t": "cmdresult", "ok": code == "200", "code": code,
                                        "uuid": data.get("uuid"), "cmd": data.get("cmd")})
                elif code != "200" and data.get("uuid") and data.get("cmd"):
                    # Sichtbar machen statt still verschlucken (Details im Log)
                    await ws.send_json({"t": "notify", "level": "warn", "secs": 4, "text":
                                        "Befehl nicht ausgeführt – Miniserver antwortet nicht" if code is None
                                        else f"Befehl nicht ausgeführt (Miniserver meldet {code})"})
            elif data.get("t") == "geste":
                # Zwei-Finger-Geste (Loxone-Standard): der Server sucht Raum,
                # Bausteine und Befehle, die Visu blendet die Antwort ein
                antwort = await app.geste(ws, data)
                if antwort:
                    await ws.send_json(antwort)
            elif data.get("t") == "setplayer":
                # Client meldet die AudioZone der aktiven Player-Pane (oder "" = keine).
                zone = str(data.get("zone") or "").strip()
                if zone:
                    app.conn_player[ws] = zone
                    try:
                        pb = app.player_blocks(zone)
                        if pb is not None:
                            _pm = app._pane_msg("player", zone, pb)
                            await ws.send_json(_pm)
                            app._last_sent.setdefault(ws, {})["player"] = _pm
                    except Exception:
                        log.exception("player_blocks (setplayer) fehlgeschlagen (%s)", zone)
                else:
                    app.conn_player.pop(ws, None)
            elif data.get("t") == "setenergy":
                # Client meldet die EFM/EnergyManager2-Kachel der aktiven
                # Energiefluss-Pane (oder "" = keine).
                euid = str(data.get("uuid") or "").strip()
                if euid:
                    app.conn_energy[ws] = euid
                    try:
                        eb = app.energy_blocks(euid)
                        if eb is not None:
                            _em = {"t": "energy", **eb}
                            await ws.send_json(_em)
                            app._last_sent.setdefault(ws, {})["energy"] = _em
                    except Exception:
                        log.exception("energy_blocks (setenergy) fehlgeschlagen (%s)", euid)
                else:
                    app.conn_energy.pop(ws, None)
            elif data.get("t") == "setchart":
                # Client meldet die Bausteine der aktiven Verlaufs-Pane (ein oder
                # mehrere, gestapelt) und den dort gewaehlten Zeitraum. "" = keine Pane.
                _cuu = tuple(x.strip() for x in str(data.get("uuid") or "").split(",")
                             if x.strip())[:SV_STATUS_MAX]
                rng = data.get("range") if data.get("range") in STAT_RANGES else STAT_DEFAULT_RANGE
                if _cuu:
                    app.conn_chart[ws] = (_cuu, rng)
                    try:
                        _cm = {"t": "chart", **app.chart_stack(_cuu, rng)}
                        await ws.send_json(_cm)
                        app._last_sent.setdefault(ws, {})["chart"] = _cm
                    except Exception:
                        log.exception("chart_stack (setchart) fehlgeschlagen (%s)", _cuu)
                else:
                    app.conn_chart.pop(ws, None)
            elif data.get("t") == "screen":
                # Das Panel meldet seine Bildschirmgroesse - beim Verbinden und
                # nach jeder Groessenaenderung. Nur fuer die Anzeige unter
                # Settings -> Panels; nichts davon steuert den Server.
                if ws in app.conn_info:
                    app.conn_info[ws]["screen"] = _clean_screen(data)
            elif data.get("t") == "setsvstatus":
                # Client meldet die Bausteine der Status-Spalte seines
                # Screensavers (oder [] = keine). Antwort sofort, damit die
                # Spalte beim Einblenden nicht leer bleibt.
                _uu = tuple(x.strip() for x in (data.get("uuids") or [])
                            if isinstance(x, str) and x.strip())[:SV_STATUS_MAX]
                if _uu:
                    app.conn_status[ws] = _uu
                    try:
                        sb = app.status_blocks(_uu)
                        _sm = {"t": "svstatus", "items": sb}
                        await ws.send_json(_sm)
                        app._last_sent.setdefault(ws, {})["svstatus"] = _sm
                    except Exception:
                        log.exception("status_blocks (setsvstatus) fehlgeschlagen")
                else:
                    app.conn_status.pop(ws, None)
            elif data.get("t") == "setcamera":
                # Client meldet die Intercom-Kachel der aktiven Kamera-Pane
                # (oder "" = keine).
                cuid = str(data.get("uuid") or "").strip()
                if cuid:
                    app.conn_camera[ws] = cuid
                    try:
                        ib = app.intercom_blocks(cuid)
                        if ib is not None:
                            await ws.send_json(app._pane_msg("camera", cuid, ib))
                    except Exception:
                        log.exception("intercom_blocks (setcamera) fehlgeschlagen (%s)", cuid)
                else:
                    app.conn_camera.pop(ws, None)
    finally:
        app.conn_route.pop(ws, None)
        app.conn_prof.pop(ws, None)
        app.conn_dev.pop(ws, None)
        app.conn_info.pop(ws, None)
        app.conn_player.pop(ws, None)
        app.conn_energy.pop(ws, None)
        app.conn_chart.pop(ws, None)
        app.conn_camera.pop(ws, None)
        app.conn_status.pop(ws, None)
        app.conn_geste.pop(ws, None)
    return ws


async def on_startup(a: web.Application) -> None:
    # HTTP-Server startet SOFORT; die Miniserver-Verbindung baut stream_task im
    # Hintergrund auf (mit Retry) — so ist /settings auch ohne/mit falschen
    # Zugangsdaten erreichbar.
    app: App = a["app"]
    # Benannt, damit /api/health melden kann, welche Aufgabe nicht mehr laeuft.
    # Nur Aufgaben, die nie planmaessig enden: Sonst meldet /api/health 503, und
    # der Waechter der LoxPanel-App startet sie immer wieder neu.
    a["tasks"] = {"miniserver": asyncio.create_task(app.stream_task()),
                  "broadcaster": asyncio.create_task(app.broadcaster()),
                  "audio": asyncio.create_task(app.audio_events_task()),
                  "front": asyncio.create_task(app.front_task())}
    a["started"] = time.monotonic()


async def on_cleanup(a: web.Application) -> None:
    for t in a.get("tasks", {}).values():
        t.cancel()
    sess = a["app"]._drv_session
    if sess is not None and not sess.closed:
        await sess.close()
    await a["app"].close()


def _log_level() -> tuple[int, str | None]:
    """LOXPANEL_LOG_LEVEL (DEBUG, INFO, WARNING, ERROR) -> (Level, Warnung)."""
    roh = os.environ.get("LOXPANEL_LOG_LEVEL", "").strip()
    if not roh:
        return logging.INFO, None
    level = logging.getLevelName(roh.upper())
    if isinstance(level, int):
        return level, None
    return logging.INFO, f"LOXPANEL_LOG_LEVEL={roh!r} unbekannt (DEBUG, INFO, WARNING, ERROR) - INFO gilt"


def _logging_einrichten() -> int:
    """Log-Level aus LOXPANEL_LOG_LEVEL setzen -> Level. Der Zugriffs-Log von
    aiohttp (eine Zeile je HTTP-Anfrage, auch jedes Icon) nur bei DEBUG."""
    level, warnung = _log_level()
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger().setLevel(level)
    # die letzten Zeilen auch im Speicher, fuer das Diagnosepaket
    if diagnose.LOG not in logging.getLogger().handlers:
        logging.getLogger().addHandler(diagnose.LOG)
    logging.getLogger("aiohttp.access").setLevel(logging.DEBUG if level <= logging.DEBUG else logging.WARNING)
    if warnung:
        log.warning(warnung)
    return level


def _fehlende_pakete_melden() -> None:
    """Einmal beim Start: welche optionalen Pakete aus requirements.txt fehlen
    und was dadurch nicht geht. Ohne sie laeuft der Server weiter und meldet
    sich gesund (/api/health); auffallen wuerde es sonst erst am Kalender, an
    der Intercom oder am Audioserver."""
    fehlt: dict[str, list[str]] = {}
    for da, paket, funktion in (
            (front_info.HAVE_ICAL, "icalendar", "Kalender der Front"),
            (front_info.HAVE_RRULE, "python-dateutil", "Serientermine im Kalender"),
            (loxone_secure.HAVE_CRYPTO, "cryptography", "gesicherte Details der Intercom (SIP-Zugang)"),
            (audioserver_auth.HAVE_CRYPTO, "cryptography", "Anmeldung am Audioserver (Favoriten, Steuerung)")):
        if not da:
            fehlt.setdefault(paket, []).append(funktion)
    if fehlt:
        log.warning("Pakete aus requirements.txt fehlen (pip install -r requirements.txt) - %s",
                    "; ".join(f"ohne {paket}: {', '.join(f)}" for paket, f in fehlt.items()))


def main() -> None:
    _logging_einrichten()
    _fehlende_pakete_melden()
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=int(os.environ.get("LOXPANEL_PORT", "8099")))
    args = p.parse_args()

    a = web.Application()
    a["app"] = App(_config(), _audio_config(), _audiometa_config())
    a.router.add_get("/", index)
    a.router.add_get("/config", config_index)
    a.router.add_get("/settings", settings_index)
    a.router.add_get("/i18n.js", i18n_js)
    a.router.add_get("/raster.js", raster_js)
    a.router.add_get("/config.css", config_css)
    a.router.add_get("/config/{name}", config_js)
    a.router.add_get("/panel/{name}", panel_teil)
    a.router.add_get("/install-agent.sh", install_script)
    a.router.add_get("/api/meta", api_meta)
    a.router.add_get("/api/kachelset", api_kachelset)
    a.router.add_post("/api/panels", api_save_panels)
    a.router.add_post("/api/entwurf", api_entwurf)
    a.router.add_post("/api/theme", api_save_theme)
    a.router.add_get("/api/settings", api_settings)
    a.router.add_get("/api/health", api_health)
    a.router.add_get("/api/backup", api_backup)
    a.router.add_get("/api/diagnose", api_diagnose)
    a.router.add_post("/api/restore", api_restore)
    a.router.add_get("/api/types", api_types)
    a.router.add_post("/api/settings/miniserver", api_settings_ms)
    a.router.add_post("/api/settings/intercom", api_settings_intercom)
    a.router.add_get("/api/sip", api_sip)
    a.router.add_post("/api/sip/pruefen", api_sip_pruefen)
    a.router.add_post("/api/intercom/talk/start", api_intercom_talk_start)
    a.router.add_get("/api/intercom/talk/status", api_intercom_talk_status)
    a.router.add_post("/api/intercom/talk/stop", api_intercom_talk_stop)
    a.router.add_post("/api/settings/night", api_settings_night)
    a.router.add_post("/api/settings/audiometa", api_settings_audiometa)
    a.router.add_post("/api/settings/calendar", api_settings_calendar)
    a.router.add_post("/api/agent/announce", api_agent_announce)
    a.router.add_get("/api/agents", api_agents)
    a.router.add_post("/api/agent/command", api_agent_command)
    a.router.add_post("/api/devices", api_save_devices)
    a.router.add_get("/api/devices", api_devices_get)
    a.router.add_post("/api/device/switch", api_device_switch)
    a.router.add_post("/api/vorschau/beenden", api_vorschau_beenden)
    a.router.add_post("/api/device/name", api_device_name)
    a.router.add_get("/api/display", api_display)
    a.router.add_post("/api/display", api_display)
    a.router.add_get("/api/mode", api_mode)
    a.router.add_post("/api/mode", api_mode)
    a.router.add_get("/api/mode/{mode}", api_mode)
    a.router.add_post("/api/mode/{mode}", api_mode)
    a.router.add_post("/api/testtone", api_testtone)
    a.router.add_get("/api/reload", api_reload)
    a.router.add_post("/api/reload", api_reload)
    a.router.add_get("/api/goto", api_goto)
    a.router.add_post("/api/goto", api_goto)
    a.router.add_get("/api/notify", api_notify)
    a.router.add_post("/api/notify", api_notify)
    a.router.add_get("/icon", icon_handler)
    a.router.add_get("/loxlib", loxlib_handler)
    a.router.add_get("/api/loxicons", loxicons_handler)
    a.router.add_get("/cover", cover_handler)
    a.router.add_get("/bellimg", bellimg_handler)
    a.router.add_get("/mjpeg", mjpeg_handler)
    a.router.add_get("/ws", ws_handler)
    a.on_startup.append(on_startup)
    a.on_cleanup.append(on_cleanup)
    web.run_app(a, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
