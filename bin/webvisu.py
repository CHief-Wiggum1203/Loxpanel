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
import calendar
import copy
import hashlib
import hmac
import ipaddress
import json
import logging
import math
import os
import platform
import re
import secrets
import socket
import struct
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import ssl as _ssl
from urllib.parse import quote, unquote, urlencode, urlsplit

import aiohttp
from aiohttp import WSMsgType, web

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loxone_api import LoxoneClient  # noqa: E402
from loxone_ws import LoxoneWS, ms_ssl_kontext  # noqa: E402


def _ms_https(port) -> bool:
    """Schema-Wahl fuer den Miniserver: Loxone Gen1 spricht nur HTTP (Port 80),
    Gen2+ nutzt HTTPS/TLS (443, …). Port 80 -> HTTP/ws, sonst HTTPS/wss."""
    try:
        return int(port) != 80
    except (TypeError, ValueError):
        return True


def _make_client(host, user, password, port, verify_tls) -> LoxoneClient:
    """LoxoneClient bauen und bei Gen1 (Port 80) auf HTTP umstellen – die
    loxone_api setzt die Basis-URL sonst fest auf https://…"""
    c = LoxoneClient(host=host, user=user, password=password, port=port, verify_tls=verify_tls)
    if not _ms_https(port):
        c.base_url = f"http://{host}:{port}/"
    return c
from adapters import LightControllerV2Adapter  # noqa: E402
import bausteine  # noqa: E402  # Kachel und Detailseite je Bausteintyp (bausteine/*.py)
from bausteine.gemeinsam import (  # noqa: E402  # gemeinsame Konstanten und Helfer der Bausteine
    LIGHT, IRC1_TEMPS, IRC1_KOMFORT_HEIZEN, IRC1_KOMFORT_KUEHLEN, IRC1_KUEHL_MODI, IRC1_MANUELL_MODI,
    IRC1_MANUELL, IRC1_BETRIEBSARTEN, IRC1_NUR_KUEHLEN, IRC1_NUR_HEIZEN, IRC2_BETRIEBSARTEN, IRC2_MANUELL,
    IRR_AUS, IRR_ALLE_AKTIV, INTERCOM_TYPES, _clean)
from audioserver import make_backend, AudioBackend  # noqa: E402
from audioserver_events import AudioEventClient  # noqa: E402
import front_info  # noqa: E402  # Kalender (iCal-Abos) + Wetter (Open-Meteo) fuer die Front
import loxone_weather  # noqa: E402  # Wetter vom Loxone-Wetterserver (Vorrang vor Open-Meteo)
import loxone_secure  # noqa: E402  # verschluesselte Befehle (gesicherte Details der Intercom)
import audioserver_auth  # noqa: E402  # Audioserver-Anmeldung; hier nur HAVE_CRYPTO (_fehlende_pakete_melden)
import sip_probe  # noqa: E402  # SIP-Pruefung der Tuerstation (OPTIONS mit Anmeldung)
from intercom_talk import IntercomTalk, TalkBusy  # noqa: E402
import theme_colors  # noqa: E402  # Panel-Theme aus einer Grundfarbe herleiten
import version_info  # noqa: E402  # Version, Commit und Bauzeit (bin/version.json)
import diagnose  # noqa: E402  # Diagnosepaket (/api/diagnose) und Log-Puffer
import konfig  # noqa: E402  # Konfigdateien: Pfade, Laden, Pruefen, Schreiben
from konfig import (  # noqa: E402  # Konfigdateien: Pfade, Laden, Pruefen, Schreiben
    _CFGDIR, PANELS_FILE, _load_cfg, _atomic_write, _write_cfg, VALID_TABS, PICK_TAB, _pick_index, _is_pick,
    _pick_tabs, FRONT_TABS, HAUS_TAB, HAUS_AUFBAUTEN, HAUS_AUFBAU_STANDARD, GESTEN_STANDARD,
    GESTEN_HINWEIS_STANDARD, _is_tab, STAT_RANGES, MS_CMD_TIMEOUT, STAT_TILE_STYLES, PIN_MERKEN_STANDARD,
    PIN_MERKEN_MAX, KACHEL_ZIEL, KACHEL_ZIEL_STANDARD, KACHEL_ZIEL_MIN, KACHEL_ZIEL_MAX, KACHEL_WACHSEN,
    GERAETE_KATALOG, PANE_ANTEIL, PANE_SPALTEN_MAX, _pin_merken, SV_STATUS_MAX, SCALE_MIN, SCALE_MAX,
    THEME_UI_KEYS, GROESSEN_STANDARD, NACHT_STANDARD, NACHT_UHR_HELL_MIN, _clean_kachel_set,
    _clean_kachel_farbton, _clean_kachel_aktiv, _clean_scale, _clean_kachelziel, _clean_pane_spalten,
    _clean_zielgeraet, _kachel_breite, _kachel_vorschlag, _clean_screen, _clean_tabpane, _clean_widget_tab,
    _clean_werteleiste, _clean_kennung, _clean_svpane, LOXLIB_DIR, _LOXLIB_NAME, _loxlib_names, _config,
    _ms_zugang, _ms_antwortfrist, _ms_keepalive_abstand, _audio_config, _audiometa_config,
    _audiometa_sekunden, _intercom_config, _night_config, _calendar_config, DEFAULT_THEME, load_theme,
    load_panels, load_devices)
from sicherung import (  # noqa: E402  # Backup und Einspielen; die Routen /api/backup, /api/restore hier
    BACKUP_FILES, _backup_zip, _sicherung_lesen, _kennwoerter_einsetzen, _sicherung_pruefen,
    _sicherung_schreiben)

log = logging.getLogger("loxpanel.webvisu")
# Welcher Stand laeuft (Seitenleiste des Konfigurators); einmal beim Start gelesen
VERSION = version_info.lesen()


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


# Ziel, ueber das das Betriebssystem nach draussen routen wuerde (RFC 5737,
# TEST-NET-1: im Internet nie vergeben). connect() auf einem UDP-Socket sendet
# nichts, legt aber die Quelladresse fest - das ist die Adresse im Heimnetz.
_ROUTEN_PROBE = ("192.0.2.1", 9)


def _lan_adressen() -> list[str]:
    """IPv4-Adresse dieses Rechners im Netz (ohne 127.x), fuer den
    Einrichtungshinweis eines Panels, das die Visu ueber 127.0.0.1 laedt
    (die App auf dem Panel selbst). Leer, wenn es keine Route gibt."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(_ROUTEN_PROBE)
            adresse = s.getsockname()[0]
    except OSError:
        return []
    return [] if adresse.startswith("127.") or adresse == "0.0.0.0" else [adresse]


HAUS_TITEL = "Haus"
# Aus-Befehl je Bausteintyp (Loxone-Strukturdoku) und die Beschriftung seiner
# Taste. Nur was hier steht, zaehlt unter "Gerade aktiv": ein Geraet, das an
# ist UND sich abschalten laesst. Die Lueftung (Ventilation) hat keinen
# Aus-Befehl, sie bleibt Anzeige.
HAUS_AUS = {
    "Switch": ("off", "Aus"),
    "TimedSwitch": ("off", "Aus"),
    "Dimmer": ("off", "Aus"),
    "EIBDimmer": ("off", "Aus"),
    "LightControllerV2": (f"changeTo/{LightControllerV2Adapter.OFF_MOOD}", "Aus"),
    "AudioZone": ("pause", "Pause"),
    "AudioZoneV2": ("pause", "Pause"),
    "Sauna": ("off", "Aus"),
}
# Schnellaktionen der Hausseite: ein Befehl an den Zentral-Baustein der
# Anlage, Art -> (Typ, Beschriftung, Befehl). Befehle laut Strukturdoku
# (Central Objects): CentralLightController kennt "on" und "reset", "reset"
# ist der Eingang "Off" des Bausteins ("Outputs are reset / switched off",
# Wissensdatenbank "Licht Zentral"); CentralAudioZone "pause". Ohne den
# Baustein gibt es die Taste nicht.
HAUS_SCHNELL = {
    "licht": ("CentralLightController", "Alle Lichter aus", "reset"),
    "audio": ("CentralAudioZone", "Alle Zonen aus", "pause"),
}
# Symbole je Raumkarte (schaltbare zuerst)
HAUS_SYMBOLE = 4
# Aufbau "raeume": Ein-Befehl je Bausteintyp laut Strukturdoku, aus schaltet
# HAUS_AUS. Der Treppenlichtschalter (TimedSwitch) startet seinen Ablauf
# (pulse) statt dauerhaft (on). Die Lichtsteuerung schaltet ihre erste
# Stimmung ein (_haus_ein). Was beides nicht hat, bekommt keine Taste.
HAUS_EIN = {
    "Switch": "on",
    "TimedSwitch": "pulse",
    "Dimmer": "on",
    "EIBDimmer": "on",
    "AudioZone": "play",
    "AudioZoneV2": "play",
    "Sauna": "on",
}
# ... vor dem Einschalten fragt die Taste nach (erst der zweite Tipp schaltet)
HAUS_RUECKFRAGE = {"Sauna": "Einschalten?"}
# ... und so viele Tasten hat eine Raumkarte hoechstens
HAUS_TASTEN = 3
# Hinweise der Hausseite (_haus_hinweise): was Aufmerksamkeit braucht, in
# dieser Folge. "dringend" und "warnung" folgen dem Ton der Kachel
# (HINWEIS_TON, ihr Zustand ist der Text), "an" meldet, dass etwas da ist
# (Post). Eine Kachel nennt ihren Hinweis selbst (hinweis: stufe, text, dazu
# symbol und zusatz), wo ihr Zustand ihn nicht benennt.
HINWEIS_STUFEN = ("dringend", "warnung", "an")
HINWEIS_TON = {"crit": "dringend", "warn": "warnung"}
# Unterseiten der Hausseite (Route liste): alle aktiven Geraete, alle Hinweise
HAUS_LISTEN = ("aktiv", "hinweise")
# Spieler der Hausseite: so viele Favoriten der Zone schickt der Server mit
# (die Visu zeigt, was in eine Zeile passt, der Rest liegt hinter "Mehr" in der
# Musikauswahl), und wie oft er sie hoechstens anfordert, solange keine da sind
HAUS_SENDER = 8
HAUS_SENDER_NEU_S = 300
# Raum verlassen und Haus aus loesen einen Taster aus Loxone Config aus. Laut
# Strukturdoku nimmt nur der Taster (Pushbutton, virtueller Eingang) einen
# Impuls (`pulse`); ein Schalter kennt nur on/off.
GESTEN_TASTER_TYPEN = ("Pushbutton",)
# Lichtgruppen eines Raums: jede Lichtsteuerung mit ihren Lichtkreisen und
# jeder einzelne Dimmer. Gedimmt werden die Kreise selbst, nicht die
# Master-Helligkeit: wie sie sich nach einem Stimmungswechsel verhaelt, sagt
# weder die Strukturdoku noch die Wissensdatenbank, die Stimmung dagegen setzt
# jeden Kreis wieder aus ihren eigenen Werten.
GESTEN_LICHT_TYPEN = ("LightControllerV2",)
GESTEN_DIMMER_TYPEN = ("Dimmer", "EIBDimmer")
GESTEN_AUDIO_TYPEN = ("AudioZone", "AudioZoneV2")
GESTEN_BESCHATTUNG_TYPEN = ("Jalousie",)
# Kiosk-Apps, die die Visu beim Verbinden meldet (?kiosk=): Fully Kiosk und die
# LoxPanel-App. Beide schalten das Display aus der Seite heraus (JS-Schnittstelle).
KIOSK_APPS = ("fully", "loxpanel")
# Panel-Agent (agent/loxpanel-agent.py): meldet sich alle AGENT_MELDETAKT s
# (time.sleep in announce_loop). Online heisst hoechstens drei Meldungen in
# Folge verpasst: eine verlorene Meldung (WLAN, Server kurz beschaeftigt) macht
# ein Panel nicht offline. Nur einem Agenten, der online ist, gilt ein Wechsel.
AGENT_MELDETAKT = 15
AGENT_ONLINE = 4 * AGENT_MELDETAKT
# s: Zeitlimit fuer Befehle an den Agenten (/start, /reload, /stop). Er wartet in
# stop_kiosk bis zu 5 s auf das alte Chromium, bevor er es abschiesst und das
# neue startet; 3 s Reserve dafuer und fuer die Antwort auf einem langsamen PX30.
AGENT_BEFEHL_TIMEOUT = 8
# Faehigkeit im Announce (features): der Agent uebernimmt "panel" aus der
# Antwort ohne Chromium-Neustart. Aeltere Agenten bekommen stattdessen /start.
AGENT_KANN_PANEL = "panel"
# Nachtmodus: Rueckfall-Fenster, wenn keine Sonnenzeiten vorliegen (kein Wetter
# konfiguriert). Sobald Sonnenauf-/-untergang bekannt sind, gelten die.
NIGHT_FROM, NIGHT_TO = "22:00", "06:00"
# Neuladen gegen Einfrieren ohne Agent (Android, Tablet): Ist reloadHours nicht
# eingestellt, laedt die Visu einmal je Nacht ab dieser Stunde neu, sobald ihre
# Uhr-Seite steht. Einzige Quelle: die theme-Nachricht bringt sie der Visu,
# /api/meta dem Konfigurator.
NEULADEN_STUNDE = 3


# Reine Anzeige-Bausteine: keine Steuer-2.-Ebene -> Antippen zeigt eine
# grosse 1/1-Wertseite (_view_control -> _big_view).
STATUS_BIG = {"Meter", "InfoOnlyAnalog", "TextState", "InfoOnlyText",
              "InfoOnlyDigital", "SmokeAlarm", "PresenceDetector",
              "ClimateControllerUS", "Hourcounter"}
# Werteleiste (ui.valueBar nennt die Seiten): diese Anzeige-Bausteine stehen
# dort als Kette von Werten in EINER Zeile ueber dem Raster statt als Kacheln,
# das Raster bleibt dem Bedienbaren (_leiste_trennen). Nicht dabei: der
# Rauchmelder (ein Alarm gehoert gross auf eine Kachel) und die Klimaregelung
# (hat Einstellungen, keine reine Anzeige).
WERTE_LEISTE_TYPEN = frozenset(STATUS_BIG - {"SmokeAlarm", "ClimateControllerUS"})
STAT_DEFAULT_RANGE = "24h"
STAT_MAX_POINTS = 240    # Punkte je Linie nach dem Ausduennen (Diagramm ~440 px breit)
STAT_REFRESH = 300       # Monatsdatei, die noch waechst, nach so vielen Sekunden neu holen
STAT_RETRY = 60          # nach einem Abruffehler fruehestens wieder versuchen
TOKEN_RENEW_MIN = 60     # s: nicht oefter neu anmelden (401 kann auch fehlende Rechte heissen)
MS_RETRY = (5, 10, 20, 40, 60)   # s: Wartezeiten zwischen Verbindungsversuchen zum Miniserver
# Verbindungszustand fuer die Panels ({t:"verbindung"}, _verbindung_msg): ob der
# Server den Miniserver erreicht, seit wann nicht und wann er zuletzt von ihm
# hoerte. Die Nachricht geht bei jeder Aenderung und alle VERBINDUNG_TAKT s an
# jedes Panel; so bemerkt die Visu auch einen Server, der still verschwindet
# (WLAN, Strom), und baut nach VERBINDUNG_STUMM s ohne jede Nachricht neu auf.
# Die Bedienung sperrt sie sofort, die Leiste zeigt sie erst nach
# VERBINDUNG_HINWEIS s: der Neustart des Miniservers nach dem Speichern in
# Loxone Config oder ein kurzer WLAN-Aussetzer soll nicht jedes Mal aufblitzen.
VERBINDUNG_TAKT = 15     # s: Lebenszeichen an jedes Panel
VERBINDUNG_STUMM = 40    # s: ohne Nachricht gilt der Server als weg (mehr als zwei Takte)
VERBINDUNG_HINWEIS = 8   # s: so lange fehlt eine Verbindung, bevor die Leiste erscheint
# Texte der Leiste; {seit} und {stand} setzt die Visu als Uhrzeit ein
VERBINDUNG_TEXTE = {
    "ms": "Miniserver seit {seit} nicht erreichbar",
    "server": "Keine Verbindung zum LoxPanel-Server seit {seit}",
    "stand": "Letzter bestätigter Stand: {stand}",
    "gesperrt": "Bedienung gesperrt",
}
EINRICHTUNG_FEHLER_MAX = 160     # Zeichen des Verbindungsfehlers im Einrichtungshinweis (Panel 480 px)
# msInfo.miniserverType laut Strukturdoku (Structure File 17.1, msInfo)
MS_TYPEN = {0: "Miniserver (Gen 1)", 1: "Miniserver Go (Gen 1)", 2: "Miniserver (Gen 2)",
            3: "Miniserver Go (Gen 2)", 4: "Miniserver Compact"}
ICON_CACHE_MAX = 500     # Icons im Speicher (Loxone-SVGs, je wenige KB)
COVER_TIMEOUT = 10       # s: Albumcover vom Audioserver/aus dem Netz (sonst haengt die Anfrage offen)
BELL_CACHE_MAX = 30      # Bilder verpasster Klingeln im Speicher (JPEG, je um 100 KB)
BELL_TIMEOUT = 10        # s: ein Klingel-Bild vom Miniserver
STAT_CACHE_MAX = 240     # Monatsdateien im Speicher (abgeschlossene Monate aendern sich nicht)
FRONT_INTERVAL = 900     # s: Kalender + Open-Meteo so oft neu holen; Wetter-Pushes dazwischen ohne Abruf
# visuType der Statistik-Ausgaenge, wie an der Anlage beobachtet: 0 Analogwert
# (Temperatur, Leistung ...), 1 Digitalwert (Regen, Sonnenschein), 2 Zaehlerstand
# (Gesamtverbrauch kWh). Zaehlerstaende zeigen den Verbrauch je Stunde/Tag als Balken.
STAT_KIND = {1: "digital", 2: "counter"}
# Breite Kacheln (2 x 1): Bausteine, deren Kachel von Haus aus zwei Spalten
# belegt - Audio (Titel und Tasten), Raumregelung (Soll und Ist) und der
# Energiefluss. Je Kachel uebersteuerbar: tiles[uuid].w = 1 | 2
# (KACHEL_BREITEN). Die Visu setzt daraus grid-column: span 2 und rechnet
# Seiten und Rastpunkte mit (rasterLage in panel.html).
KACHEL_BREIT_TYPEN = frozenset({"AudioZone", "AudioZoneV2", "IRoomControllerV2", "IRoomController",
                                "EFM", "EnergyManager2"})
STAT_WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
# Reine Wert-/Analog-Anzeigen (kein an/aus) -> keine Kategorie-Ampel, neutral.
_ANALOG = {"InfoOnlyAnalog", "Slider", "UpDownAnalog", "Meter", "TextState", "InfoOnlyText",
           "Hourcounter", "EFM", "EnergyManager2", "PvProductionForecast", "SteakThermo"}
# Wecker (AlarmClock) laut Strukturdoku: die Betriebsarten 3..9 sind die
# Wochentage Montag bis Sonntag, 0..2 (Feiertag, Urlaub, freie Tage) haben
# Vorrang vor ihnen. Grenzen aus der Loxone-Wissensdatenbank (Baustein
# Wecker): Schlummerdauer 60..1800 s, Lautstaerke des Wecksounds 5..100 %.
# Wecksound, Lautstaerke und Helligkeit gibt es nur mit Touch Nightlight;
# deviceState meldet es (0 keins, 1 offline, 2 online).
WECKER_WOCHENTAGE = range(3, 10)
WECKER_VORRANG = range(0, 3)
WECKER_SCHLUMMER_MIN, WECKER_SCHLUMMER_MAX = 60, 1800
WECKER_LAUT_MIN = 5
NIGHTLIGHT_DA = (1, 2)
# Schrittweite der -/+ Tasten fuer Dauern (Laufzeit einer Zone, Wecker-Dauern)
# und Prozentwerte (Lautstaerke, Helligkeit)
DAUER_SCHRITT = 60
PROZENT_SCHRITT = 5
# Bausteintypen, die nur teilweise umgesetzt sind (Anzeige ohne volle Bedienung);
# Grundlage fuer den Status in /api/types. Vollstaendig = Kachel hat nav/cmd/
# controls/sublabel, unbekannt = nichts davon (tote Kachel).
# Intercom und IntercomV2 bleiben im Browser ohne Gegensprechen. Die native
# Android-Bruecke ergaenzt Audio nur fuer Intercom (Gen-1); SIP-Zugang und
# Pruefung der Tuerstation bleiben unter Settings -> SIP (/api/sip).
PARTIAL_TYPES = {"AudioZone", "Intercom", "IntercomV2", "TextInput", "Ventilation"}
# IntercomV2 deviceState: 1 = StateOk; 0 = StateUnknown sagt nichts Sicheres
# und bleibt ohne Hinweis.
INTERCOM_V2_ZUSTAND = {2: "Startet neu", 3: "Startet"}
# Entwuerfe (Punkt 10 Teil 3): ein Profil, das der Konfigurator noch nicht
# gespeichert hat, laesst sich in der echten Visu ansehen (?entwurf=<Token>).
# Er liegt nur im Speicher: so viele gleichzeitig, so lange nach der letzten
# Nutzung; Speichern verwirft sie alle (die Visu laedt dabei neu).
ENTWURF_MAX = 8
ENTWURF_DAUER = 3600
# Vorschau am Geraet (Punkt 12): so lange zeigt ein Geraet einen Entwurf, wenn der
# Konfigurator ihn nicht mehr auffrischt - dann geht es zur vorigen Ansicht zurueck.
VORSCHAU_GERAET_DAUER = 900
# Zeitstempel einer Klingel (lastBellEvents, camimage): JJJJMMTTHHMMSS
_BELL_TS = re.compile(r"\d{14}")
# Kopplungscode eines Browsers ohne Geraetekennung: der Server vergibt ihn
# beim Verbinden (die Visu merkt ihn sich und schickt ihn beim naechsten
# Verbinden als ?code= zurueck), das Panel zeigt ihn unter "Dieses Geraet
# einrichten", Displays listet ihn, "Namen vergeben" trifft damit genau dieses
# Geraet (mehrere hinter einer IP). Alphabet ohne 0/O und 1/I.
KOPPLUNG_ZEICHEN = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
KOPPLUNG_LAENGE = 4
_KOPPLUNG_RE = re.compile(r"^[A-HJ-NP-Z2-9]{4,8}$")
# Tracker-Zeile: fuehrender Zeitstempel (TT.MM.JJ[JJ] HH:MM[:SS]) wird vom Text
# getrennt, damit er als Untertitel erscheint. Matcht sonst nichts -> ganze Zeile.
_TS_RE = re.compile(r"^\s*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}[ ,]+\d{1,2}:\d{2}(?::\d{2})?)\s+(.+)$")


def _kachel_klassisch(ui: dict) -> bool:
    """Bisheriger Kachel-Aufbau (ui.tileLayout "classic")? Nicht mit einem
    Kachel-Set: das bringt seinen eigenen, neuen Aufbau mit (lx, mitte, kreis)."""
    return ui.get("tileLayout") == "classic" and not _clean_kachel_set(ui.get("tileSet"))


# Trenner, die nach dem Streichen des Raumnamens am Rand eines Kachelnamens
# haengen blieben ("Licht - Wohnzimmer" -> "Licht")
_NAMEN_TRENNER = frozenset({"-", "–", "—", "·", "/", ",", ":", "|"})


def _ohne_raum(name: str, raum: str) -> str:
    """Kachelname ohne den Raumnamen, wenn die Seite den Raum schon nennt
    ("Jalousie Wohnzimmer Süd" auf der Wohnzimmer-Seite -> "Jalousie Süd").
    Nur ganze Woerter zaehlen (Gross-/Kleinschreibung egal, ein Satzzeichen
    am Wort stoert nicht), die uebrigen Woerter bleiben in ihrer Reihenfolge,
    ein uebrig gebliebener Trenner am Rand faellt weg. Kommt der Raum nicht
    vor oder bliebe nichts uebrig ("Wohnzimmer"), bleibt der Name."""
    woerter, rw = (name or "").split(), (raum or "").split()
    if not woerter or not rw:
        return name
    low = [w.lower().strip(",:;") for w in woerter]
    rlow = [w.lower().strip(",:;") for w in rw]
    for i in range(len(low) - len(rw) + 1):
        if low[i:i + len(rw)] == rlow:
            rest = woerter[:i] + woerter[i + len(rw):]
            while rest and rest[0] in _NAMEN_TRENNER:
                rest.pop(0)
            while rest and rest[-1] in _NAMEN_TRENNER:
                rest.pop()
            return " ".join(rest) or name
    return name


_NUMFMT = re.compile(r"^(%[-+ 0-9.]*[dfeg])(.*)$")
_PREFIX = ["k", "M", "G", "T"]


_STAT_ROW = re.compile(r"<S\s([^>]*?)/?>")
_STAT_ATTR = re.compile(r'(\w+)="([^"]*)"')


def _parse_stat_xml(text: str) -> list:
    """Loxone-Statistik-Monatsdatei -> [(sekunden, [werte ...])], zeitlich sortiert.

    Jede Zeile ist <S T="JJJJ-MM-TT hh:mm:ss" V="1.23"/>; bei mehreren
    Ausgaengen stehen weitere Wert-Attribute in Ausgangsreihenfolge dahinter.
    Gelesen wird deshalb jedes Attribut ausser T in Dokumentreihenfolge, ohne
    Annahme ueber seinen Namen. Per Regex statt XML-Parser: die Datei ist flach,
    und so gibt es keine Entitaeten-Aufloesung. Zeitstempel sind Ortszeit des
    Miniservers und werden als Wanduhr-Sekunden (timegm) gefuehrt, damit Server
    und Panel ohne Zeitzonenrechnung dieselbe Uhrzeit zeigen."""
    out = []
    for m in _STAT_ROW.finditer(text or ""):
        ts, vals = None, []
        for name, raw in _STAT_ATTR.findall(m.group(1)):
            if name == "T":
                try:
                    ts = calendar.timegm(datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").timetuple())
                except ValueError:
                    ts = None
            else:
                try:
                    vals.append(float(raw))
                except ValueError:
                    vals.append(None)
        if ts is not None and vals:
            out.append((ts, vals))
    out.sort(key=lambda r: r[0])
    return out


def _stat_fmt(fmt) -> tuple[int, str]:
    """Loxone-Zahlenformat -> (Nachkommastellen, Einheit). Zwei Schreibweisen:
    printf wie bei `statistic` ("%.1f °C", "%.0f%", "%.0fLx") und die Maske von
    `statisticV2` ("0,000kW", "0,0kWh", "0,00€"). Ohne Format -> (0, "")."""
    s = str(fmt or "")
    m = re.search(r"%(?:\.(\d+))?[fd]", s)
    if m:
        return int(m.group(1) or 0), s[m.end():].replace("%%", "%").strip()
    m = re.match(r"^[#0]+(?:[.,]([#0]+))?(.*)$", s.strip())
    if m:
        return len(m.group(1) or ""), m.group(2).strip()
    return 0, ""


def _parse_stat2_bin(body: bytes, nvals: int = 1) -> list | None:
    """Antwort von jdev/sps/getStatistic/.../raw/... -> [(sekunden, [werte])].

    Binaer, je Eintrag 4 Byte Zeitstempel (uint32, Unix-UTC) und je Wert 8 Byte
    (float64), little-endian - an der Anlage so gemessen (PV 7,42 kW, Netz
    -6,26 kW, Eintraege im Abstand der Gruppe). Die Zeit wird wie bei den
    Monatsdateien in Wanduhr-Sekunden der Container-Zeitzone umgerechnet.
    Passt die Laenge nicht zum Eintragsformat -> None (unbekannte Antwort)."""
    size = 4 + 8 * nvals
    if len(body) % size:
        return None
    out = []
    for off in range(0, len(body), size):
        ts, *vals = struct.unpack_from("<I" + "d" * nvals, body, off)
        vals = [v if math.isfinite(v) else None for v in vals]
        out.append((calendar.timegm(time.localtime(ts)), vals))
    out.sort(key=lambda r: r[0])
    return out


def _stat_thin(pts: list, t0: int, t1: int, n: int, digital: bool) -> list:
    """Linie auf hoechstens n Punkte ausduennen: je Zeitfenster der Mittelwert
    (Analog) bzw. das Maximum (Digital: ein kurzes "Ein" soll sichtbar bleiben)."""
    if len(pts) <= n or t1 <= t0:
        return pts
    w = (t1 - t0) / n
    buckets: dict[int, list] = {}
    for t, v in pts:
        buckets.setdefault(min(n - 1, max(0, int((t - t0) / w))), []).append((t, v))
    out = []
    for b in sorted(buckets):
        items = buckets[b]
        if digital:
            out.append((items[-1][0], max(v for _, v in items)))
        else:
            out.append((int(sum(t for t, _ in items) / len(items)),
                        sum(v for _, v in items) / len(items)))
    return out


def _stat_buckets(pts: list, edges: list, t_end: int) -> list:
    """Zeitgewichteter Mittelwert je Abschnitt [edges[i], edges[i+1]). Ein Messwert
    gilt bis zum naechsten (Treppe) - so stimmt das auch fuer Digitalwerte, die nur
    bei Aenderung aufgezeichnet werden: der Mittelwert ist dann der Ein-Anteil.
    Abschnitte ohne bekannten Wert oder nach t_end -> None."""
    out, k, n = [], 0, len(pts)
    for a, b in zip(edges, edges[1:]):
        b2 = min(b, t_end)
        while k + 1 < n and pts[k + 1][0] <= a:
            k += 1
        if b2 <= a or not n or pts[0][0] >= b2:
            out.append(None)
            continue
        acc = dur = 0.0
        j = k
        while j < n and pts[j][0] < b2:
            t, v = pts[j]
            lo, hi = max(a, t), min(b2, pts[j + 1][0] if j + 1 < n else t_end)
            if hi > lo:
                acc += v * (hi - lo)
                dur += hi - lo
            j += 1
        out.append(acc / dur if dur else None)
    return out


def _stat_day_range(pts: list, edges: list, t_end: int) -> list:
    """Tiefst- und Hoechstwert je Abschnitt, mit dem Stand, der zu Beginn des
    Abschnitts galt. Abschnitte ohne bekannten Wert oder nach t_end -> None."""
    out = []
    for a, b in zip(edges, edges[1:]):
        if a >= t_end:
            out.append(None)
            continue
        vals = [v for t, v in pts if a <= t < min(b, t_end + 1)]
        prev = [v for t, v in pts if t < a]
        if prev:
            vals.append(prev[-1])
        out.append((min(vals), max(vals)) if vals else None)
    return out


def _stat_bars(pts: list, edges: list) -> list:
    """Zaehlerstaende -> Verbrauch je Abschnitt [edges[i], edges[i+1]).

    Summiert von Messpunkt zu Messpunkt: Grundlage ist der letzte Stand davor
    (pts beginnt mit dem letzten Wert vor dem Fenster, falls bekannt; sonst ist
    der erste Stand die Basis). Faellt der Stand auf weniger als die Haelfte,
    wurde der Zaehler zurueckgesetzt und zaehlt ab 0 weiter. Ein kleiner
    Ruecksprung (Rundung, 1000,5 -> 1000,4) ist kein Verbrauch, sonst ergaebe
    er einen Balken in Hoehe des ganzen Zaehlerstands."""
    out, i, prev = [], 0, None
    while i < len(pts) and pts[i][0] < edges[0]:
        prev = pts[i][1]
        i += 1
    for a, b in zip(edges, edges[1:]):
        use = 0.0
        while i < len(pts) and pts[i][0] < b:
            v = pts[i][1]
            if prev is not None:
                if v >= prev:
                    use += v - prev
                elif v < prev / 2:
                    use += v              # zurueckgesetzt: ab 0 weitergezaehlt
            prev = v
            i += 1
        out.append((a, use))
    return out


def _hex_rgb(value) -> str | None:
    """#RRGGBB / #RGB -> \"r,g,b\" (fuer rgba() mit variabler Deckkraft). None bei ungueltig."""
    h = str(value or "").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        return f"{int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)}"
    except ValueError:
        return None


def _overlay_alphas(ov: dict) -> tuple[float, float, int]:
    """Overlay-Config -> (Fuellung-Alpha, Rahmen-Alpha, Rahmenbreite px).

    Defaults entsprechen dem bisherigen fest verdrahteten Aussehen. `mode`
    schaltet Fuellung bzw. Rahmen komplett ab (Rahmen/Fuellung/Beides).
    """
    ov = ov if isinstance(ov, dict) else {}
    def _num(key, default):
        try:
            return float(ov.get(key, default))
        except (TypeError, ValueError):
            return float(default)
    fill = max(0.0, min(1.0, _num("fill", 16) / 100.0))
    bord = max(0.0, min(1.0, _num("bord", 55) / 100.0))
    bw = max(1, min(4, int(_num("bw", 1))))
    mode = ov.get("mode")
    if mode == "border":
        fill = 0.0
    elif mode == "fill":
        bord = 0.0
    return fill, bord, bw


def _inactive_border(ov: dict) -> tuple[float, int]:
    """Overlay-Config -> (Rahmen-Alpha, Rahmenbreite px) fuer NICHT aktive Kacheln.

    Defaults entsprechen dem bisherigen fest verdrahteten --line (weiss 8%) und
    1px, damit sich ohne Konfiguration nichts aendert. `ibord`/`ibw` machen den
    sonst kaum sichtbaren Kachelrahmen (z.B. auf hellen Shelly-Displays) staerker.
    """
    ov = ov if isinstance(ov, dict) else {}
    def _num(key, default):
        try:
            return float(ov.get(key, default))
        except (TypeError, ValueError):
            return float(default)
    alpha = max(0.0, min(1.0, _num("ibord", 8) / 100.0))
    bw = max(1, min(4, int(_num("ibw", 1))))
    return alpha, bw


def _posring(ov: dict) -> tuple[float, float, int]:
    """Overlay-Config -> (Deckkraft Bogen, Deckkraft Spur, Strichstaerke viewBox).

    Defaults entsprechen dem bisher fest verdrahteten Aussehen (Bogen voll
    deckend, Spur 18 %, Strichstaerke 6), ohne Konfiguration aendert sich also
    nichts. Die Strichstaerke zaehlt in viewBox-Einheiten des Rings (0..100);
    in Pixeln ergibt sie `rw/100 * (Icon-Groesse + 18)`. Das ist der Regler,
    der zaehlt: weil der Ring 18 px Sockel hat, die Icon-Linie aber sauber mit
    der Icon-Groesse skaliert, faellt der Ring bei kleinen Icons deutlich
    dicker aus als die Linien, die er umschliesst (bei 24 px Icon Faktor 1,5).
    """
    ov = ov if isinstance(ov, dict) else {}

    def _num(key, default):
        try:
            return float(ov.get(key, default))
        except (TypeError, ValueError):
            return float(default)
    ring = max(0.0, min(1.0, _num("ring", 100) / 100.0))
    rtrk = max(0.0, min(1.0, _num("rtrk", 18) / 100.0))
    rw = max(1, min(12, int(_num("rw", 6))))
    return ring, rtrk, rw


def _ms_unerreichbar(err: BaseException) -> bool:
    """Scheiterte die Pruefung eines Zugangs, weil der Miniserver nicht
    antwortete (Zeitlimit, Verbindung, Namensaufloesung)? Dann ist offen, ob
    der Zugang stimmt. Hat er geantwortet und abgelehnt (Kennwort, Benutzer,
    Zertifikat, keine Loxone-Antwort), steht fest, dass er so nicht geht."""
    if isinstance(err, (aiohttp.ClientSSLError, _ssl.SSLError)):
        return False
    return isinstance(err, (asyncio.TimeoutError, aiohttp.ClientConnectionError, OSError))


class ZugangFehler(Exception):
    """Gesicherte Details (Zugangsdaten) nicht zu bekommen; der Text nennt den
    Grund so, dass ihn der Konfigurator anzeigen kann."""


KEIN_SIP = "Die Intercom nennt keinen SIP-Zugang"
KEINE_GESICHERTEN = "Der Baustein hat keine gesicherten Details"


class OhneGesicherteDetails(ZugangFehler):
    """Der Miniserver hat fuer den Baustein keine gesicherten Details, es liegt
    also nicht an Verbindung oder Rechten."""

    def __init__(self):
        super().__init__(KEINE_GESICHERTEN)


def _sip_zugang(details: dict) -> dict | None:
    """SIP-Zugang aus den gesicherten Details einer Intercom (audioInfo: host,
    user und bei Loxone-Intercoms pass; Strukturdoku 16.0 und 17.0, Intercom).
    -> {"host", "user", "pass"}; None, wenn kein host darin steht."""
    ai = details.get("audioInfo")
    host = str(ai.get("host") or "").strip() if isinstance(ai, dict) else ""
    if not host:
        return None
    return {"host": host, "user": str(ai.get("user") or "").strip(), "pass": str(ai.get("pass") or "")}


def _gesichert_felder(details: dict) -> dict:
    """Aufbau gesicherter Details ohne Werte: je Abschnitt die Felder und ob sie
    gefuellt sind, etwa {"videoInfo": {"streamUrl": True}, "audioInfo": {}}.
    Fuer die Diagnose im Reiter SIP; Werte und Passwoerter bleiben im Server."""
    return {k: ({f: bool(w) for f, w in v.items()} if isinstance(v, dict) else bool(v))
            for k, v in details.items()}


KEIN_VIDEO = "Kein Video eingerichtet"


def _mit_miniserver(teile, host: str, port=None) -> str:
    """netloc einer streamUrl mit dem Miniserver als Host: Anmeldedaten in der
    Adresse bleiben, der Port ist der uebergebene oder der aus der Adresse."""
    auth = teile.netloc.rsplit("@", 1)[0] + "@" if "@" in teile.netloc else ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"               # IPv6
    p = teile.port if port is None else port
    return auth + host + (f":{p}" if p else "")


def _kamera_aus_details(details: dict, ms_host: str = "", ms_port=None) -> dict:
    """Kamera einer Intercom aus ihren gesicherten Details (videoInfo:
    streamUrl, user, pass; Strukturdoku 16.0 und 17.0, Intercom).
    -> {"url", "user", "pass"} oder {"grund"} fuer die Intercom-Seite.
    Steht statt Host oder IP ein Platzhalter in der streamUrl, ersetzt ihn
    LoxPanel wie die Loxone-App (Strukturdoku 17.0, Intercom, streamUrl):
    "cloudDNS" durch die Adresse des Miniservers (Port bleibt),
    "remoteConnect" durch Host UND Port des Miniservers mit https - der
    Miniserver leitet das Bild der Kamera weiter. Ohne Miniserver-Adresse
    (ms_host) bleibt so eine Kamera ohne Video. Eine Adresse ohne Schema (so
    wie sie in Loxone Config eingetragen wurde) wird mit http:// angesprochen."""
    vi = details.get("videoInfo")
    url = str(vi.get("streamUrl") or "").strip() if isinstance(vi, dict) else ""
    if not url:
        return {"grund": KEIN_VIDEO}
    if "://" not in url:
        url = "http://" + url
    try:
        teile = urlsplit(url)
        host = (teile.hostname or "").lower()
        teile.port                       # prueft die Port-Angabe mit
    except ValueError:                   # etwa eine kaputte IPv6-Angabe
        return {"grund": KEIN_VIDEO}
    if host in ("clouddns", "remoteconnect"):
        if not ms_host:
            return {"grund": KEIN_VIDEO}
        if host == "clouddns":
            url = teile._replace(netloc=_mit_miniserver(teile, ms_host)).geturl()
        else:
            url = teile._replace(scheme="https", netloc=_mit_miniserver(teile, ms_host, ms_port or 443)).geturl()
    return {"url": url, "user": str(vi.get("user") or "").strip(), "pass": str(vi.get("pass") or "")}


class App:
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

    def _song_cover(self, artist: str, title: str) -> str | None:
        """Album-Cover (ueber /cover-Proxy) zu Interpret+Titel, gecacht.

        Cache-Treffer -> URL bzw. None (kein Album, z.B. Wortbeitrag). Bei einem
        Miss wird der Lookup einmalig im Hintergrund angestossen; das Ergebnis
        erscheint beim naechsten Render (der Lookup setzt _dirty)."""
        artist = (artist or "").strip()
        title = (title or "").strip()
        if not artist or not title:
            return None
        key = f"{artist}\n{title}".lower()
        hit = self._cover_cache.get(key)
        if hit and hit[1] > time.time():
            return ("/cover?u=" + quote(hit[0], safe="")) if hit[0] else None
        if key not in self._cover_pending:
            self._cover_pending.add(key)
            self._spawn(self._lookup_cover(artist, title, key))
        return None

    async def _lookup_cover(self, artist: str, title: str, key: str) -> None:
        """iTunes-Suche nach Interpret+Titel -> Album-Cover-URL (600px)."""
        url = None
        try:
            sess = self.icon_session
            if sess is not None:
                api = "https://itunes.apple.com/search?" + urlencode(
                    {"term": f"{artist} {title}", "media": "music",
                     "entity": "song", "limit": 1})
                async with sess.get(api, timeout=aiohttp.ClientTimeout(total=6)) as r:
                    if r.status == 200:
                        data = await r.json(content_type=None)
                        res = data.get("results") or []
                        if res:
                            art = res[0].get("artworkUrl100") or ""
                            url = art.replace("100x100bb", "600x600bb") or None
        except Exception as err:
            log.debug("Cover-Lookup (%s): %s", key, err)
        # Treffer lange cachen (gleicher Song -> gleiches Cover), Fehlschlag kurz
        # (aus Wortbeitrag wird spaeter wieder ein Titel).
        self._cover_cache[key] = (url, time.time() + (24 * 3600 if url else 900))
        self._cover_pending.discard(key)
        if url:
            self._dirty = True

    def _ssl_ctx(self) -> _ssl.SSLContext:
        return ms_ssl_kontext(self.verify_tls)

    def _apply_structure(self, st: dict) -> None:
        self.controls = st.get("controls", {})
        self.rooms = st.get("rooms", {})
        self.cats = st.get("cats", {})
        # Audioserver-Adressen fuer den Gen-2-Event-Kanal: {serverUUID: "host:port"}
        ms = st.get("mediaServer") or {}
        self.mediaservers = {u: (v or {}).get("host", "")
                             for u, v in ms.items() if isinstance(v, dict) and (v or {}).get("host")}
        # Standort des Miniservers (Loxone setzt latitude/longitude immer, fuer
        # Astro/Sonnenstand) -> Wetter ohne Konfiguration (Fallback fuer loxpanel.cfg).
        info = st.get("msInfo") or {}
        try:
            self.ms_lat = float(info["latitude"]) if info.get("latitude") not in (None, "") else None
            self.ms_lon = float(info["longitude"]) if info.get("longitude") not in (None, "") else None
        except (TypeError, ValueError, KeyError):
            self.ms_lat = self.ms_lon = None
        self.ms_location = str(info.get("location") or "").strip()
        # Fuer das Diagnosepaket: was die Struktur ueber den Miniserver sagt
        # (msInfo laut Strukturdoku; eine Firmware-Version nennt sie nicht)
        self.ms_struktur = {"typ": MS_TYPEN.get(info.get("miniserverType"), info.get("miniserverType")),
                            "name": info.get("msName") or "", "projekt": info.get("projectName") or "",
                            "stand": st.get("lastModified") or ""}
        self.rooms_with = sorted(
            {c.get("room") for c in self.controls.values() if c.get("room") in self.rooms},
            key=lambda r: self.rooms[r].get("name", ""))
        self.cats_with = sorted(
            {c.get("cat") for c in self.controls.values() if c.get("cat") in self.cats},
            key=lambda c: self.cats[c].get("name", ""))
        self.bell_map = {}
        self.alarm_map = {}
        # Betriebsarten (id -> Name) fuer die Wecker-Wiederholung: die `modes`
        # eines Eintrags verweisen hierauf (z.B. Wochentage Mo-So).
        self.op_modes = {str(k): v for k, v in (st.get("operatingModes") or {}).items()}
        # Globale States der Anlage (Name -> UUID): u.a. Sonnenauf-/-untergang und
        # die aktiven Betriebsmodi. Die Werte kommen ueber den WS-Stream in
        # self.states. Roh uebernehmen, die Belegung ist je Anlage verschieden.
        self.global_states = dict(st.get("globalStates") or {})
        # Loxone-Wetterdienst: nur vorhanden, wenn die Anlage ihn gebucht hat.
        # Enthaelt die State-UUIDs (actual/forecast), die Wetterlage-Texte und
        # die Formatstrings mit den Einheiten. Der Wetterpuffer gehoert zu diesen
        # UUIDs und wird mit der Struktur zusammen verworfen.
        wsrv = st.get("weatherServer")
        self.weather_cfg = wsrv if isinstance(wsrv, dict) else {}
        self._lox_wx = {}
        # Neue Struktur heisst meist: in Loxone Config gespeichert. Die Kamera
        # der Intercoms kann sich geaendert haben, also neu fragen.
        self.ms_video = {}
        self.playerid_by_action = {}
        self.audiohost_by_action = {}
        for _u, _c in self.controls.items():
            if _c.get("type") in INTERCOM_TYPES:
                _bu = (_c.get("states") or {}).get("bell")
                if _bu:
                    self.bell_map[_bu] = _u
            elif _c.get("type") == "AlarmClock":
                _au = (_c.get("states") or {}).get("isAlarmActive")
                if _au:
                    self.alarm_map[_au] = _u
            elif _c.get("type") in ("AudioZone", "AudioZoneV2"):
                # Beide Zonentypen werden direkt am Audioserver (7091) gesteuert:
                # AudioZone -> Musikserver, AudioZoneV2 -> Audioserver Gen2 (Sonn).
                # Der Umweg ueber den Miniserver (sps/io) reicht roomfav/play NICHT
                # zuverlaessig durch; der Direktkanal (auch beim Sonn, ohne Token
                # getestet) funktioniert fuer play/pause/next/volume/roomfav.
                _det = _c.get("details") or {}
                _pid = _det.get("playerid")
                _ua = _c.get("uuidAction")
                if _ua and _pid is not None:
                    self.playerid_by_action[_ua] = int(_pid)
                    _hp = self.mediaservers.get(_det.get("server"))
                    if _hp:
                        self.audiohost_by_action[_ua] = _hp.split(":")[0].strip()
        self._presence_rebuild()
        log.info("Struktur: %d Controls, %d Räume, %d Kategorien, %d Intercom-Klingeln, %d Wecker, %d AudioZones",
                 len(self.controls), len(self.rooms_with), len(self.cats_with),
                 len(self.bell_map), len(self.alarm_map), len(self.playerid_by_action))

    @staticmethod
    def _structure_sig(st: dict) -> str:
        """Signatur der Loxone-Struktur (Controls/Raeume/Kategorien). Aendert sich
        nur bei Config-Aenderungen (Namen, neue/entfernte Controls …), nicht bei
        State-Werten – die kommen separat ueber den WS-Stream."""
        try:
            rel = {"controls": st.get("controls", {}), "rooms": st.get("rooms", {}),
                   "cats": st.get("cats", {})}
            raw = json.dumps(rel, sort_keys=True, ensure_ascii=False, default=str)
            return hashlib.md5(raw.encode("utf-8")).hexdigest()
        except (TypeError, ValueError):
            return ""

    def _adopt_structure(self, st: dict) -> bool:
        """Struktur anwenden und melden, ob sie sich seit der letzten Verbindung
        geaendert hat (Grundlage fuer den Panel-Reload). Beim allerersten Anwenden
        (`_struct_sig` noch None) gilt sie nie als 'geaendert' — frisch verbundene
        Panels holen sich die Ansichten ohnehin neu."""
        sig = self._structure_sig(st)
        changed = bool(self._struct_sig and sig and sig != self._struct_sig)
        self._apply_structure(st)
        self._struct_sig = sig
        return changed

    async def _refresh_structure(self) -> bool:
        """Struktur neu vom Miniserver laden und anwenden, WENN sie sich geaendert
        hat (Loxone-Config geaendert). Gibt True bei Aenderung zurueck. Rein lesend;
        Fehler werden vom Aufrufer isoliert, damit die Verbindungs-Schleife lebt."""
        if self.client is None:
            return False
        st = await self.client.load_structure()
        if not self._adopt_structure(st):
            return False                      # unveraendert -> nichts tun (kein Panel-Reload)
        self.states = {}                      # nach Struktur-Wechsel States frisch (MS sendet neu)
        self._dirty = True
        return True

    async def start(self) -> None:
        try:
            self.client = _make_client(self.host, self.user, self.password,
                                       self.port, self.verify_tls)
            await self.client.__aenter__()
            self.alg = (await self.client.getkey2()).hashAlg
            self._set_token(await self.client.authenticate())
            self._ms_pubkey = None
            st = await self.client.load_structure()
            # Reconnect nach Miniserver-Reboot (z.B. Loxone-Config hochgeladen):
            # hat sich die Struktur geaendert, Panels neu laden lassen. Beim
            # allerersten Start ist _struct_sig None -> kein Reload.
            if self._adopt_structure(st):
                self._pending_reload = True
            self.icon_session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=await asyncio.to_thread(self._ssl_ctx)))
            await self._connect_ws()
            log.info("Mit Miniserver verbunden (%s).", self.host)
        except Exception:
            await self._close_conn()   # sauber zuruecksetzen, damit Retry neu aufbaut
            raise

    async def _close_conn(self) -> None:
        for c in (self.ws, self.icon_session, self.client):
            try:
                if c:
                    await c.close()
            except Exception:
                pass
        self.ws = self.icon_session = self.client = None

    def _zugang_setzen(self, ms: dict) -> None:
        """Zugang fuer die naechste Anmeldung uebernehmen (verbindet nicht)."""
        self.host, self.port = ms["host"], ms.get("port", 443)
        self.user, self.password = ms["user"], ms["pass"]
        self.verify_tls = ms.get("verify_tls", False)
        self._zugang_neu = None

    async def reconnect(self, ms: dict | None = None) -> int:
        """Verbindung mit (ge-aenderter) Config neu aufbauen, mit `ms` statt
        _config(), wenn ein Zugang erst geprueft wird (api_settings_ms). Gibt
        Control-Anzahl zurueck; wirft bei falschen Zugangsdaten, TimeoutError,
        wenn die Anmeldung laenger als _ms_antwortfrist() braucht. Alte
        Verbindung bleibt bei Fehler bestehen (neuer Client wird nur bei Erfolg
        uebernommen)."""
        ms = _config() if ms is None else ms
        missing = [k for k in ("host", "user", "pass") if not ms.get(k)]
        if missing:
            raise ValueError(
                "Miniserver-Konfiguration unvollstaendig (fehlt: "
                + ", ".join(missing) + "). Bitte unter Einstellungen -> "
                "Miniserver Host, Benutzer und Passwort eintragen.")
        frist = _ms_antwortfrist()
        newc = _make_client(ms["host"], ms["user"], ms["pass"],
                            ms.get("port", 443), ms.get("verify_tls", False))
        try:
            await newc.__aenter__()
            alg = (await asyncio.wait_for(newc.getkey2(), frist)).hashAlg
            jwt = await asyncio.wait_for(newc.authenticate(), frist)
            st = await newc.load_structure()
            # Kontext der icon_session schon hier (CAs laden blockiert -> Thread),
            # damit die Uebernahme unten ohne await durchlaeuft.
            ssl_ctx = await asyncio.to_thread(ms_ssl_kontext, ms.get("verify_tls", False))
        except Exception as err:
            try:
                await newc.close()
            except Exception:
                pass
            if isinstance(err, asyncio.TimeoutError) and not str(err):   # Frist von wait_for
                raise TimeoutError(f"keine Antwort innerhalb von {frist:g} s") from err
            raise
        # Erfolg -> uebernehmen
        self._zugang_setzen(ms)
        old_client, self.client = self.client, newc
        self.alg = alg
        self._set_token(jwt)
        self._ms_pubkey = None
        # Anderer/geaenderter Miniserver -> Struktur evtl. anders, dann Panels neu laden.
        if self._adopt_structure(st):
            self._pending_reload = True
        self.states = {}
        old_is, self.icon_session = self.icon_session, \
            aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx))
        self.icon_cache, self.bell_cache = {}, {}
        self.stat_cache, self.stat2_cache, self.stat_memo = {}, {}, {}   # anderer Miniserver -> andere Verlaeufe
        self.stat_gen += 1
        old_ws, self.ws = self.ws, None   # stream_task baut WS mit neuen Daten neu auf
        self.intercom_cfg = _intercom_config()
        self._dirty = True
        for closer in (old_client, old_is, old_ws):
            try:
                if closer:
                    await closer.close()
            except Exception:
                pass
        return len(self.controls)

    async def _connect_ws(self) -> None:
        self.ws = LoxoneWS(host=self.host, port=self.port, user=self.user, jwt=self.jwt,
                           hash_alg=self.alg, verify_tls=self.verify_tls,
                           secure=_ms_https(self.port), antwortfrist=_ms_antwortfrist(),
                           keepalive_abstand=_ms_keepalive_abstand())
        await self.ws.connect()

    def _set_token(self, jwt: str) -> None:
        self.jwt = jwt
        self._auth_gen += 1
        self._auth_at = time.monotonic()

    async def _reauth(self) -> None:
        # Token erneuern (kann nach langer Laufzeit ablaufen)
        if self.client:
            self._set_token(await self.client.authenticate())

    async def _renew_token(self, seen_gen: int) -> bool:
        """Nach einem 401 neu anmelden. Hat eine parallele Anfrage das schon
        getan (Zaehler weiter als seen_gen), genuegt es, erneut zu senden. Innerhalb
        von TOKEN_RENEW_MIN nach der letzten Anmeldung nicht noch einmal: dann liegt
        der 401 nicht am Token. -> True, wenn sich ein Neuversuch lohnt."""
        async with self._auth_lock:
            if self._auth_gen != seen_gen:
                return True
            if not self.client or time.monotonic() - self._auth_at < TOKEN_RENEW_MIN:
                return False
            self._auth_at = time.monotonic()     # auch ein Fehlversuch sperrt fuer TOKEN_RENEW_MIN
            try:
                self._set_token(await self.client.authenticate())
            except Exception as err:            # z. B. Passwort geaendert, Miniserver startet neu
                log.warning("Neuanmeldung am Miniserver fehlgeschlagen: %s", err or type(err).__name__)
                return False
            log.info("Miniserver-Token abgelaufen -> neu angemeldet")
            return True

    async def _ms_http(self, path: str, timeout: float, renew: bool = True) -> tuple[int, bytes, str]:
        """GET an den Miniserver mit dem aktuellen Token; bei 401 (und renew)
        einmal neu anmelden und wiederholen. -> (HTTP-Status, Inhalt, Content-Type). Wirft
        ConnectionError ohne Verbindung, sonst aiohttp.ClientError/TimeoutError."""
        async def once() -> tuple[int, bytes, str]:
            if self.icon_session is None:
                raise ConnectionError("keine Verbindung zum Miniserver")
            scheme = "https" if _ms_https(self.port) else "http"
            headers = {"Authorization": f"Bearer {self.jwt}"} if self.jwt else {}
            async with self.icon_session.get(f"{scheme}://{self.host}:{self.port}/{path.lstrip('/')}",
                                             headers=headers,
                                             timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                return r.status, await r.read(), r.headers.get("Content-Type", "")
        gen = self._auth_gen
        res = await once()
        if res[0] == 401 and renew and await self._renew_token(gen):
            res = await once()
        return res

    async def _ms_jdev(self, path: str, timeout: float = MS_CMD_TIMEOUT,
                       renew: bool = True) -> tuple[str, object]:
        """jdev-Befehl ueber _ms_http. -> (Code, LL.value); Code ist der
        LL-Code der Antwort, ohne lesbares JSON der HTTP-Status."""
        status, body, _ = await self._ms_http("jdev/" + path.lstrip("/"), timeout, renew)
        try:
            ll = json.loads(body.decode("utf-8", "replace").lstrip("\ufeff").strip("\x00")).get("LL") or {}
        except (ValueError, AttributeError):
            ll = {}
        code = ll.get("Code") or ll.get("code")
        return (str(code) if code is not None else str(status)), ll.get("value")

    async def secured_details(self, uuid: str) -> dict:
        """Gesicherte Details eines Bausteins (securedDetails), etwa Kamera- und
        SIP-Zugang einer Intercom. Der Miniserver gibt sie nur auf einen
        verschluesselten Befehl heraus (loxone_secure), die Anmeldung steckt im
        Befehl. Lehnt er ab (HTTP 401: Schluessel nicht mehr gueltig, oder LL-Code
        401: Token abgelaufen), einmal mit frischem Schluessel und Token.
        Gefragt wird nur, wenn der Baustein in der Struktur das Kennzeichen
        securedDetails traegt (Strukturdoku, Controls: "indicates that there is
        sensitive information available").
        -> dict; wirft ZugangFehler mit einem Grund fuer den Konfigurator."""
        if not loxone_secure.HAVE_CRYPTO:
            raise ZugangFehler("Paket 'cryptography' fehlt")
        for versuch in range(2):
            if self.icon_session is None or not self.jwt:
                raise ZugangFehler("Keine Verbindung zum Miniserver")
            if not (self.controls.get(uuid) or {}).get("securedDetails"):
                raise OhneGesicherteDetails()
            gen = self._auth_gen
            try:
                if self._ms_pubkey is None:
                    code, wert = await self._ms_jdev("sys/getPublicKey")
                    self._ms_pubkey = loxone_secure.public_key_from_pem(wert)
                    if self._ms_pubkey is None:
                        raise ZugangFehler(f"Der Miniserver liefert keinen Schlüssel (Code {code})")
                code, key_hex = await self._ms_jdev("sys/getkey")
                if code != "200" or not isinstance(key_hex, str):
                    raise ZugangFehler(f"Der Miniserver liefert keinen Anmeldeschlüssel (Code {code})")
                cmd = (f"jdev/sps/io/{uuid}/securedDetails?autht="
                       f"{loxone_secure.token_hash(key_hex, self.jwt, self.alg)}&user={quote(self.user or '', safe='')}")
                enc = loxone_secure.encrypt_command(cmd, self._ms_pubkey)
                status, body, _ = await self._ms_http(enc.pfad, MS_CMD_TIMEOUT, renew=False)
            except ZugangFehler:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError, ValueError) as err:
                raise ZugangFehler(f"Miniserver nicht erreichbar ({err or type(err).__name__})") from err
            if status == 401:
                self._ms_pubkey = None
                if versuch == 0:
                    await self._renew_token(gen)
                    continue
                raise ZugangFehler("Der Miniserver lehnt die verschlüsselte Anfrage ab")
            if status != 200:
                raise ZugangFehler(f"Der Miniserver antwortet mit HTTP {status}")
            try:
                ll = json.loads(loxone_secure.decrypt_response(body, enc.key, enc.iv).lstrip("\ufeff")).get("LL") or {}
            except (ValueError, AttributeError) as err:
                raise ZugangFehler("Die Antwort des Miniservers lässt sich nicht entschlüsseln") from err
            code = str(ll.get("Code") or ll.get("code") or "")
            if code == "401" and versuch == 0 and await self._renew_token(gen):
                continue
            if code == "401":
                raise ZugangFehler("Der Miniserver lehnt die Anmeldung von LoxPanel ab (Code 401)")
            if code == "403":
                raise ZugangFehler("Der Benutzer von LoxPanel darf diese Zugangsdaten nicht lesen "
                                   "(Rechte in Loxone Config)")
            if code != "200":
                raise ZugangFehler(f"Der Miniserver antwortet mit Code {code or '?'}")
            wert = ll.get("value")
            if isinstance(wert, str):
                try:
                    wert = json.loads(wert)
                except ValueError as err:
                    raise ZugangFehler("Die gesicherten Details sind kein JSON") from err
            if not isinstance(wert, dict):
                raise OhneGesicherteDetails()
            return wert
        raise ZugangFehler("Der Miniserver lehnt die verschlüsselte Anfrage ab")

    async def intercom_sip(self, uuid: str) -> dict:
        """SIP-Zugang einer Intercom aus ihren gesicherten Details (_sip_zugang).
        -> {"host", "user", "pass"}; ZugangFehler, wenn sie keinen nennt."""
        sip = _sip_zugang(await self.secured_details(uuid))
        if sip is None:
            raise ZugangFehler(KEIN_SIP)
        return sip

    async def _talk_credentials(self, uuid: str) -> dict:
        """Nur Gen-1 (Door Controller); Gen-2 ist der eigene Typ IntercomV2."""
        if (self.controls.get(uuid) or {}).get("type") != "Intercom":
            raise ValueError("Gegensprechen unterstützt nur die Intercom Gen-1")
        try:
            return await self.intercom_sip(uuid)
        except ZugangFehler as err:
            raise ValueError(str(err)) from err

    async def intercom_video(self, uuid: str) -> dict | None:
        """Kamera einer Intercom fuer /mjpeg: {"url", "user", "pass"}. Eine in
        LoxPanel eingetragene Adresse (loxpanel.cfg intercom) hat Vorrang, sonst
        die aus den gesicherten Details des Miniservers (_kamera_aus_details),
        gemerkt in ms_video bis zur naechsten Struktur. Scheitert die Anfrage
        (Verbindung, Rechte), wird nichts gemerkt und beim naechsten Mal neu
        gefragt. None ohne nutzbare Kamera."""
        ent = self.intercom_cfg.get(uuid)
        if isinstance(ent, str):
            ent = {"url": ent}
        if isinstance(ent, dict) and isinstance(ent.get("url"), str) and ent["url"].strip():
            return {"url": ent["url"].strip(), "user": str(ent.get("user") or ""), "pass": str(ent.get("pass") or "")}
        c = self.controls.get(uuid) or {}
        if c.get("type") not in INTERCOM_TYPES or not c.get("securedDetails"):
            return None
        async with self._video_sperre:   # zwei Panels zugleich: einmal fragen
            cam = self.ms_video.get(uuid)
            if cam is None:
                try:
                    cam = _kamera_aus_details(await self.secured_details(uuid), self.host, self.port)
                except OhneGesicherteDetails:
                    cam = {"grund": KEIN_VIDEO}
                except ZugangFehler as err:
                    log.warning("Kamera der Intercom %s vom Miniserver: %s", uuid, err)
                    return None
                self.ms_video[uuid] = cam
                self._dirty = True       # Intercom-Seite neu: Bild oder Grund
        return cam if cam.get("url") else None

    # ---- Zustands-Helfer ----
    def _state(self, control: dict, name: str):
        su = (control.get("states") or {}).get(name)
        return self.states.get(su) if su else None

    def _endlich(self, control: dict, name: str) -> float | None:
        """Zahl-State als endliche Zahl; None, wenn er fehlt, keine Zahl ist oder
        NaN/unendlich (als Binaer-Double gueltig): dann ist der Wert unbekannt."""
        try:
            v = float(self._state(control, name))
        except (TypeError, ValueError):
            return None
        return v if math.isfinite(v) else None

    def _text(self, control: dict, name: str) -> str:
        """Text-State, URL-dekodiert (Loxone liefert songName/artist prozentkodiert)."""
        v = self._state(control, name)
        return unquote(str(v)) if v not in (None, "") else ""

    def _json_state(self, control: dict, name: str):
        """JSON-State (Loxone liefert Listen/Objekte als ggf. prozentkodierten
        Text). None, wenn leer oder nicht parsebar (dann einmal geloggt)."""
        raw = self._state(control, name)
        if raw in (None, ""):
            return None
        if not isinstance(raw, str):
            return raw
        txt = unquote(raw).strip()
        try:
            return json.loads(txt)
        except ValueError:
            log.warning("%s.%s nicht als JSON parsebar: %r", control.get("type"), name, txt[:160])
            return None

    @staticmethod
    def _named_items(data) -> list[tuple[str, dict]]:
        """Liste/Objekt aus einem JSON-State in (Label, Eintrag)-Paare wandeln.
        Label aus name/title/label, sonst laufende Nummer."""
        if isinstance(data, dict):
            seq = list(data.items())
        elif isinstance(data, (list, tuple)):
            seq = list(enumerate(data))
        else:
            return []
        out = []
        for i, (key, e) in enumerate(seq):
            if isinstance(e, dict):
                label = _clean(e.get("name") or e.get("title") or e.get("label")) or str(key if isinstance(key, str) else i + 1)
                out.append((label, e))
            else:
                out.append((str(key if isinstance(key, str) else i + 1), {"value": e}))
        return out

    def _flow_text(self, value, fmt: str, pos: str, neg: str, zero: str | None = None) -> str:
        """Leistung mit Richtung: Vorzeichen -> Text (z.B. Bezug/Einspeisung).
        Loxone zaehlt aus Sicht des Hauses: positiv = fliesst ins Haus, also
        Netzbezug bzw. Speicher entlaedt; negativ = Einspeisung bzw. Laden.
        zero: Text fuer 0 (ohne Richtung), sonst gilt 0 als positiv."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return ""
        if not math.isfinite(v):   # NaN/unendlich (gueltige Binaer-Doubles): unbekannt
            return ""
        text = zero if (zero and v == 0) else (pos if v >= 0 else neg)
        return f"{text} {self._fmt_num(abs(v), fmt)}"

    def _tracker_lines(self, control: dict) -> list[str]:
        """Ereignis-Zeilen eines Tracker-Bausteins (State 'entries'). Loxone
        liefert einen mehrzeiligen, ggf. prozentkodierten Text; neueste zuerst.
        Der Zeilentrenner variiert je nach Firmware: echtes Newline, Literal
        "\\n"/"\\r" (Backslash+Buchstabe) oder CR -> alle normalisieren, sonst
        landet der ganze Verlauf in EINER Zeile."""
        raw = self._state(control, "entries")
        if raw in (None, ""):
            return []
        txt = unquote(str(raw))
        for sep in ("\r\n", "\\r\\n", "\\n", "\\r", "\r"):
            txt = txt.replace(sep, "\n")
        return [ln.strip() for ln in txt.split("\n") if ln.strip()]

    @staticmethod
    def _split_ts(line: str) -> tuple[str | None, str]:
        """Fuehrenden Zeitstempel abtrennen -> (zeitstempel|None, text)."""
        m = _TS_RE.match(line or "")
        return (m.group(1), m.group(2)) if m else (None, line or "")

    def _song(self, control: dict) -> str:
        """songName, aber rohe Stream-URLs (Radio) ausblenden."""
        s = self._text(control, "songName")
        return "" if s.startswith(("http://", "https://")) else s

    def _lc_scenes(self, c: dict) -> dict:
        """LightController-V1 sceneList (Loxone-Format id=\"name\") -> {id:name}."""
        raw = str(self._state(c, "sceneList") or "")
        return {int(m.group(1)): m.group(2) for m in re.finditer(r'(\d+)="([^"]*)"', raw)}

    def _json_list_map(self, c: dict, name: str) -> dict:
        """State-Wert = JSON-Array [{id,name}] -> {id:name}."""
        raw = self._state(c, name)
        try:
            arr = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            return {}
        return {int(x["id"]): x.get("name") for x in (arr or [])
                if isinstance(x, dict) and x.get("id") is not None}

    def _irc_modes(self, c: dict) -> dict:
        """IRoomControllerV2: Temperatur-/Timer-Modi aus details.timerModes ->
        {id: Name} (z. B. 0=Eco, 1=Komfort, 2=Gebaeudeschutz)."""
        tm = (c.get("details") or {}).get("timerModes") or []
        return {int(m["id"]): _clean(m.get("name"))
                for m in tm if isinstance(m, dict) and m.get("id") is not None}

    @staticmethod
    def _irc_activity(prep, win) -> list:
        """Aktivitaets-Hinweise fuer die Raumregelung: heizt/kuehlt + Fenster."""
        bits = []
        try:
            p = float(prep)
        except (TypeError, ValueError):
            p = 0.0
        if p > 0:
            bits.append("heizt")
        elif p < 0:
            bits.append("kühlt")
        if win:
            bits.append("Fenster")
        return bits

    def _irc1(self, c: dict) -> dict:
        """Zustand der alten Raumregelung (IRoomController, v1):
          kuehlen   laeuft die Kuehlperiode (State mode, IRC1_KUEHL_MODI)
          ix/name   aktive Temperatur (currCoolTempIx bzw. currHeatTempIx)
          stell_ix  Temperatur, die -/+ verstellt: manuell die manuelle, sonst
                    Komfort der Periode
          stell     ihr aktueller Wert; None, wenn unbekannt oder relativ zu
                    Komfort (dann gibt es kein -/+, statt einen Wert zu raten)
          komfort_ix Komfort der Periode (fuer den Komfort-Knopf)
          prep      fuer _irc_activity: Ventil Heizen > 0 = 1, Kuehlen > 0 = -1"""
        def num(name):
            try:
                return float(self._state(c, name))
            except (TypeError, ValueError):
                return None

        mode = num("mode")
        mode = int(mode) if mode is not None else None
        kuehlen = mode in IRC1_KUEHL_MODI
        ix = num("currCoolTempIx" if kuehlen else "currHeatTempIx")
        ix = int(ix) if ix is not None else None
        komfort_ix = IRC1_KOMFORT_KUEHLEN if kuehlen else IRC1_KOMFORT_HEIZEN
        if mode in IRC1_MANUELL_MODI:
            stell_ix, stell = IRC1_MANUELL, num("tempTarget")
        else:
            stell_ix = komfort_ix
            stell = self._irc1_temp(c, komfort_ix) if self._irc1_absolut(c, komfort_ix) else None
        prep = 1 if (num("valveHeat") or 0) > 0 else (-1 if (num("valveCool") or 0) > 0 else 0)
        return {"kuehlen": kuehlen, "ix": ix, "name": IRC1_TEMPS.get(ix), "stell_ix": stell_ix,
                "stell": stell, "komfort_ix": komfort_ix, "prep": prep}

    def _irc_betriebsart(self, c: dict) -> tuple[dict | None, str | None]:
        """Aufklapper "Betriebsart" einer Raumregelung und der Name fuer die
        Statuszeile, wenn manuell geregelt wird (dann laeuft kein Zeitplan).
        V2: State operatingMode, setOperatingMode/<Nr>. Alt: State mode,
        mode/<Nr>; "Automatik, heizt/kuehlt gerade" (1/2) gilt als Automatik,
        details.restrictedToMode blendet Heizen bzw. Kuehlen aus.
        (None, None), wenn der Baustein den State nicht hat."""
        v2 = c.get("type") == "IRoomControllerV2"
        name = "operatingMode" if v2 else "mode"
        ua = c.get("uuidAction")
        if not ua or name not in (c.get("states") or {}):
            return None, None
        try:
            cur = int(float(self._state(c, name)))
        except (TypeError, ValueError):
            cur = None
        if v2:
            arten, befehl, manuell = IRC2_BETRIEBSARTEN, "setOperatingMode", IRC2_MANUELL
            markiert = cur
        else:
            nur = (c.get("details") or {}).get("restrictedToMode")
            weg = {IRC1_NUR_KUEHLEN: {3, 5}, IRC1_NUR_HEIZEN: {4, 6}}.get(nur, set())
            arten = {n: nm for n, nm in IRC1_BETRIEBSARTEN.items() if n not in weg}
            befehl, manuell = "mode", IRC1_MANUELL_MODI
            markiert = 0 if cur in (1, 2) else cur
        zelle = {"label": "Betriebsart", "menu": [
            {"label": nm, "on": n == markiert, "cmd": {"uuid": ua, "cmd": f"{befehl}/{n}"}}
            for n, nm in arten.items()]}
        return zelle, (arten.get(cur) if cur in manuell else None)

    def _irc1_temp(self, c: dict, ix: int):
        """Wert der Temperatur Nr. ix: der State "temperatures" ist bei der
        alten Raumregelung eine Liste mit einer UUID je Nummer."""
        lst = (c.get("states") or {}).get("temperatures")
        if not isinstance(lst, list) or not 0 <= ix < len(lst):
            return None
        try:
            return float(self.states.get(lst[ix]))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _irc1_absolut(c: dict, ix: int) -> bool:
        """details.temperatures[ix].isAbsolute: True = fester Wert, False =
        haengt von Komfort ab. Nummern als Schluessel ("0".."6") oder Liste."""
        tt = (c.get("details") or {}).get("temperatures")
        if isinstance(tt, dict):
            e = tt.get(str(ix), tt.get(ix))
        elif isinstance(tt, list) and 0 <= ix < len(tt):
            e = tt[ix]
        else:
            e = None
        return bool(isinstance(e, dict) and e.get("isAbsolute"))

    def _audio_favs(self, c: dict) -> list:
        """Raum-Favoriten (Radio/Playlist/Spotify) aus dem sourceList-State.

        Loxone legt das Ergebnis von `roomfav/get` in den sourceList-Textstate.
        Die Struktur variiert je nach Firmware:
          {"getroomfavs_result":[{...,"items":[...]}]}  (Gruppe(n) mit items)
          {"getroomfavs_result":[{...item...}]}          (flache Item-Liste)
          {"items":[...]}                                 (direktes Listing)
        Der State ist ausserdem ein transienter Browse-Puffer: er ist nur
        verlaesslich befuellt, nachdem wir `roomfav/get` angefordert haben
        (siehe prime_favs). Wir sammeln alle Items mit gueltigem 'slot' ein.
        """
        raw = self._state(c, "sourceList")
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return []
        buckets = []
        res = data.get("getroomfavs_result")
        if isinstance(res, list):
            for grp in res:
                if isinstance(grp, dict) and isinstance(grp.get("items"), list):
                    buckets.append(grp["items"])
                elif isinstance(grp, dict) and "slot" in grp:
                    buckets.append([grp])
        if isinstance(data.get("items"), list):
            buckets.append(data["items"])
        out, seen = [], set()
        for items in buckets:
            for it in items:
                if not isinstance(it, dict):
                    continue
                slot = it.get("slot")
                if slot is None or slot in seen:
                    continue
                seen.add(slot)
                out.append({"slot": slot, "cover": it.get("coverurl") or "",
                            "type": (it.get("type") or "").lower(),
                            "name": unquote(str(it.get("name") or it.get("title") or f"Favorit {slot}"))})
        out.sort(key=lambda f: f["slot"])
        return out

    async def prime_favs(self, uuid: str) -> None:
        """Fordert die Zonen-Favoriten aktiv an (`roomfav/get`), damit der
        sourceList-State frisch befuellt wird. Das Ergebnis kommt asynchron
        per WS -> _on_value setzt _dirty -> broadcaster re-rendert die offene
        Ansicht (Musikauswahl) mit den nun vorhandenen Favoriten."""
        c = self.controls.get(uuid, {})
        t = c.get("type")
        if t not in ("AudioZone", "AudioZoneV2"):
            return
        # Zone mit laufendem Audioserver-Event-Client (Gen1 Musikserver ODER
        # Gen2 Audioserver): Raumfavoriten direkt ueber den 7091-Kanal anfordern
        # (Ergebnis kommt async -> _dirty). Der Loxone-sourceList-State ist bei
        # vielen Setups leer, deshalb ist das der zuverlaessige Weg.
        cl, pid = self._audio_client_for(c)
        if cl is not None and pid is not None and (cl.paired is False or cl.authed):
            await cl.request_favs(pid)
            return
        # Fallback ohne Event-Client (z.B. MS4H ohne 7091), bei gekoppeltem
        # Audioserver ohne Anmeldung oder unklarer Kopplung (paired None):
        # Favoriten ueber den Miniserver holen.
        ua = c.get("uuidAction")
        if ua:
            await self.command(ua, "roomfav/get/0/20")

    def _fmt_num(self, value, fmt: str) -> str:
        """Loxone-Formatstring anwenden, Einheiten skalieren (kWh→MWh), Komma-Dezimal."""
        try:
            value = float(value)
        except (TypeError, ValueError):
            return ""
        m = _NUMFMT.match(fmt or "%.1f")
        numfmt, unit = (m.group(1), m.group(2)) if m else ("%.1f", "")
        unit = unit.strip().replace("%%", "%")   # "%.2f kW"/"%.2fkW" -> "3,25 kW"; Loxone-Escape "%%" -> "%"
        if unit[:1] in _PREFIX:
            i = _PREFIX.index(unit[0]); rest = unit[1:]
            while abs(value) >= 1000 and i < len(_PREFIX) - 1:
                value /= 1000.0
                i += 1
            unit = _PREFIX[i] + rest
        try:
            s = numfmt % value
        except (TypeError, ValueError):
            s = str(value)
        s = s.replace(".", ",")
        return (s + " " + unit) if unit else s

    def _with_uuid(self, uuid: str) -> dict:
        c = dict(self.controls[uuid])
        c["uuid"] = uuid
        return c

    def _jal_status(self, c: dict) -> str:
        s = c.get("states") or {}
        ai = s.get("autoInfoText")
        if ai and self.states.get(ai):
            return str(self.states.get(ai))
        aa = s.get("autoActive")
        if aa:
            return "Automatik aktiv" if self.states.get(aa) else "Sonnenstandsautomatik inaktiv"
        return "Manuell"

    def _jal_fahrt(self, c: dict) -> tuple[bool, bool, dict, dict]:
        """(faehrt auf, faehrt ab, Befehl Auf, Befehl Ab) einer Jalousie, wie in
        der Original-Visu: Im Stand startet die Richtung die Fahrt, waehrend
        der Fahrt haelt jede der beiden an. Kachel und Detailansicht nehmen
        beide dies, damit sie sich gleich bedienen."""
        s = c.get("states") or {}
        auf = bool(self.states.get(s.get("up")))
        ab = bool(self.states.get(s.get("down")))
        ua = c.get("uuidAction")
        return (auf, ab, {"uuid": ua, "cmd": "Stop" if auf or ab else "Up"},
                {"uuid": ua, "cmd": "Stop" if auf or ab else "Down"})

    @staticmethod
    def _icon_url(image: str | None) -> str | None:
        if image and (image.endswith(".svg") or image.endswith(".png")):
            return f"/icon?p={quote(image)}"
        return None

    def _control_icon_url(self, c: dict) -> str | None:
        """Echtes Loxone-Icon eines Controls. Reihenfolge wie in der Loxone-App:
        control-eigenes Bild -> `defaultIcon` (hier legt Loxone das pro Control
        gewaehlte/GEAENDERTE Icon ab, auch eigene Uploads) -> Kategorie-Icon."""
        di = (c.get("details") or {}).get("image")
        if isinstance(di, str):
            img = di
        elif isinstance(di, dict):
            img = di.get("on") or di.get("off")
        else:
            img = None
        if not img:
            img = c.get("defaultIcon")      # pro-Control gewaehltes Icon (inkl. Aenderung/Upload)
        if not img:
            img = (self.cats.get(c.get("cat")) or {}).get("image")   # Kategorie als Fallback
        return self._icon_url(img)

    def _node_icon_url(self, nd: dict) -> str | None:
        """Echtes Loxone-Icon eines EFM-Knotens (Verbraucher/Quelle). Die Icons
        gibt der Miniserver pro Knoten vor; das Feld heisst je nach Firmware
        unterschiedlich, deshalb erst die von Controls bekannten Felder, dann
        notfalls irgendein Bildpfad (.svg/.png) im Knoten. `image` kann ein Pfad
        oder ein {on/off}-Objekt sein (wie bei Controls)."""
        if not isinstance(nd, dict):
            return None
        cands = [nd.get("image"), nd.get("defaultIcon"), nd.get("icon"),
                 nd.get("iconSrc")] + list(nd.values())
        for v in cands:
            if isinstance(v, dict):
                v = v.get("on") or v.get("off")
            u = self._icon_url(v) if isinstance(v, str) else None
            if u:
                return u
        return None

    def _cat_entry(self, cat_uuid: str | None):
        """Passender categories-Eintrag (Match: Schluessel als Teilstring des
        Kategorienamens). Rueckgabe: str (nur Icon-Farbe) | dict {on,off}
        (Zustandsfarben) | None."""
        name = _clean((self.cats.get(cat_uuid) or {}).get("name") or "").lower()
        if not name:
            return None
        # Ergebnis je Kategoriename merken: jede Kachel fragt hier, und die
        # Suche laeuft ueber alle Eintraege (100.000 aus einer Sicherung ->
        # 0,7 s je Seite). Jede Theme-Aenderung laedt das Theme neu, also
        # gilt der Speicher genau solange wie dieses categories-Objekt.
        quelle = self.theme.get("categories", {})
        if self._cat_memo[0] is not quelle:
            self._cat_memo = (quelle, {})
        memo = self._cat_memo[1]
        if name not in memo:
            memo[name] = next((val for key, val in quelle.items()
                               if not key.startswith("_") and key.lower() in name), None)
        return memo[name]

    def _cat_color(self, cat_uuid: str | None) -> str | None:
        val = self._cat_entry(cat_uuid)
        if isinstance(val, dict):
            return val.get("on") or val.get("off")   # Icon-Farbe = Aktiv-Farbe
        return val if isinstance(val, str) else None

    def _cat_states(self, cat_uuid: str | None):
        """Zustandsfarben {on, off} einer Kategorie (Ampel) oder None."""
        val = self._cat_entry(cat_uuid)
        return val if isinstance(val, dict) else None

    # ---- Panel-Profile ----
    def _resolve_ids(self, entries, table: dict):
        """Whitelist-Einträge (UUID ODER Name) auf UUID-Menge abbilden.

        Leer/fehlend -> None (= keine Einschränkung, alles sichtbar). Namen
        matchen exakt oder als Teilstring (Loxone-Räume haben Präfixe wie
        „1.0.2 Terrasse" -> Eintrag „Terrasse" genügt).
        """
        if not entries:
            return None
        names = {k: _clean(v.get("name", "")).lower() for k, v in table.items()}
        out = set()
        gesehen = set()
        for e in entries:
            e = str(e).strip()
            if not e or e in gesehen:          # doppelte Eintraege kosten sonst je einen Durchlauf
                continue
            gesehen.add(e)
            if e in table:                       # exakte UUID
                out.add(e)
                continue
            el = _clean(e).lower()
            exact = [k for k, n in names.items() if n == el]
            if exact:
                out.update(exact)
            elif el:                             # Teilstring-Treffer
                out.update(k for k, n in names.items() if el in n)
        return out

    @staticmethod
    def _theme_vars(states: dict, ui: dict) -> dict:
        # Grundfarbe zuerst: daraus faellt der ganze Satz ab - Flaechen, Schrift,
        # Zweitzeile, Icon- und Zustandsfarben. Ohne Grundfarbe bleibt v leer und
        # es aendert sich nichts gegenueber frueher.
        # Ein Kachel-Set bringt seine Farben fertig mit und ersetzt die Herleitung
        # aus der Grundfarbe; ausdruecklich gewaehlte Zustandsfarben gelten auch dort.
        _set = theme_colors.kachel_set(_clean_kachel_set(ui.get("tileSet")),
                                       _clean_kachel_farbton(ui.get("tileHue")),
                                       _clean_kachel_aktiv(ui.get("tileActive")))
        if _set:
            v = _set
        else:
            v = dict(theme_colors.derive(ui["baseColor"]) or {}) if ui.get("baseColor") else {}
        # Ausdruecklich eingestellte Zustandsfarben schlagen die Herleitung.
        # Aber: "nicht gesetzt" gibt es bei states gar nicht - load_theme()
        # fuellt sie immer aus DEFAULT_THEME, und theme.example.json liefert
        # dieselben Werte. Als ausdrueckliche Wahl zaehlt deshalb nur ein Wert,
        # der von der eingebauten Vorgabe abweicht. Sonst wuerden die alten
        # Festfarben jedes hergeleitete Theme ueberschreiben und die ganze
        # Nachrechnung in theme_colors.py waere fuer diese Rollen wirkungslos.
        _hergeleitet = bool(v)
        _vorgabe = DEFAULT_THEME["states"]

        def _gewaehlt(key: str):
            wert = states.get(key)
            if not wert:
                return None
            if _hergeleitet and str(wert).strip().lower() == str(_vorgabe.get(key, "")).lower():
                return None
            return wert

        for _var, _key in (("--glow", "active"), ("--good", "good"),
                           ("--crit", "crit"), ("--warn", "warn")):
            _wert = _gewaehlt(_key)
            if _wert:
                v[_var] = _wert
        if _gewaehlt("good"):
            # Der Akzent zieht mit der OK-Farbe mit, damit aktiver Tab,
            # Energiefluss-Ring und Kalender ("heute") die eingestellte Farbe
            # uebernehmen statt auf dem Default (#52b881) zu bleiben - AUCH ohne
            # Panel-Farbe (loest #16: --accent wurde vorher nie an die Panels
            # geschickt). Mit Panel-Farbe schlaegt eine ausdrueckliche OK-Farbe
            # den hergeleiteten Akzent, sonst bleibt der hergeleitete Wert.
            v["--accent"] = _gewaehlt("good")
            _rgb = _hex_rgb(_gewaehlt("good"))
            if _rgb:
                v["--accent-rgb"] = _rgb
                # Schrift auf dem Akzent (Kalender "heute", Entwurfsmarke)
                # zieht mit, sonst bleibt sie fuer den alten Akzent gerechnet
                v["--on-accent"] = theme_colors.schrift_auf(_gewaehlt("good"))
        # Groessen in px: Panel, sonst global, sonst der Standard des Kachel-Aufbaus
        std = GROESSEN_STANDARD["classic" if _kachel_klassisch(ui) else "neu"]
        # ... ein Kachel-Set bringt eigene Standardgroessen mit (KACHEL_SETS "groessen")
        _ks_e = theme_colors.KACHEL_SETS.get(_clean_kachel_set(ui.get("tileSet")) or "") or {}
        std = {**std, **(_ks_e.get("groessen") or {})}
        for _var, _key in (("--ico-size", "iconSize"), ("--name-size", "nameSize"),
                           ("--sub-size", "subSize"), ("--room-size", "roomSize"),
                           ("--big-size", "bigSize")):
            v[_var] = f"{ui.get(_key) or std[_key]}px"
        v["--name-weight"] = "700" if ui.get("bold") else "450"
        # Zustands-Farben zusaetzlich als R,G,B-Tripel, damit das Aktiv-Overlay
        # (Fuellung/Rahmen) die konfigurierte Farbe mit variabler Deckkraft nutzt.
        for skey, rvar in (("active", "--on-rgb"), ("good", "--good-rgb"),
                           ("crit", "--crit-rgb"), ("warn", "--warn-rgb")):
            rgb = _hex_rgb(_gewaehlt(skey))
            if rgb:
                v[rvar] = rgb
        # Aussehen des Aktiv-Overlays (global fuers Panel; pro Kachel ueberschreibbar).
        if isinstance(ui.get("overlay"), dict):
            fill, bord, bw = _overlay_alphas(ui["overlay"])
            v["--ov-fill"] = f"{fill:.3g}"
            v["--ov-bord"] = f"{bord:.3g}"
            v["--ov-bw"] = f"{bw}px"
            # Rahmen der NICHT aktiven Kacheln (sonst kaum sichtbar auf hellen Displays).
            ialpha, ibw = _inactive_border(ui["overlay"])
            v["--tile-bord"] = f"rgba(255,255,255,{ialpha:.3g})"
            v["--tile-bw"] = f"{ibw}px"
            # Positionsring (Rollladen/Tor/Fenster/Dimmer) - herunterdrehbar, wo
            # er zu kraeftig wirkt.
            rop, rtrk, rw = _posring(ui["overlay"])
            v["--posring-op"] = f"{rop:.3g}"
            v["--posring-trk"] = f"{rtrk:.3g}"
            v["--posring-w"] = f"{rw}"
        if ui.get("font"):
            v["--font"] = ui["font"]
        if ui.get("textColor"):
            v["--name-color"] = ui["textColor"]
        if ui.get("cols") == 3:
            v["--cols"] = "3"          # 3 Spalten (3x2 / 3x3); Default 2
        if ui.get("rows") == 3:
            v["--rows"] = "3"          # 3 Zeilen (2x3 / 3x3); Default 2
        nudge = ui.get("nudgeX")
        if nudge not in (None, ""):
            # Horizontaler Feinversatz der ganzen Visu (px, negativ = nach links)
            # gegen Display-Overscan. Wird vom Frontend als --nudge-x angewandt.
            try:
                v["--nudge-x"] = f"{float(nudge):g}px"
            except (TypeError, ValueError):
                pass
        # Nacht-Uhr: ihr Grund und eine Schrift, die darauf traegt. Ohne
        # Schrift aus Set oder Grundfarbe gelten die Standardfarben der Visu
        # (dunkel, helle Schrift), dort nimmt sie --ink.
        v["--nacht-grund"] = theme_colors.NACHT_GRUND
        if v.get("--ink"):
            v["--nacht-ink"] = theme_colors.nacht_schrift(v["--ink"])
        return {k: val for k, val in v.items() if val}

    def entwurf_ablegen(self, pid: str, roh: dict, token: str = "") -> tuple[str, list]:
        """Entwurf eines Profils (UI-Form, wie der Konfigurator es speichert)
        im Speicher ablegen -> (Token, nicht uebernommene Angaben). Geprueft wird
        wie beim Speichern (_sanitize_panels), geschrieben wird nichts. Mit dem
        Token eines vorhandenen Entwurfs desselben Profils wird dieser ersetzt,
        sonst entsteht ein neuer; ist der Platz voll, geht der aelteste."""
        clean = self._sanitize_panels({pid: roh})
        if pid not in clean:
            raise ValueError("Ansicht nicht brauchbar (leere oder mit _ beginnende Kennung?)")
        weg = self._panels_verworfen({pid: roh}, clean,
                                     {u: _clean(c.get("name")) or u for u, c in self.controls.items()})
        now = time.time()
        for t in [t for t, e in self.entwuerfe.items() if now - e["ts"] > ENTWURF_DAUER]:
            del self.entwuerfe[t]
        alt = self.entwuerfe.get(token)
        if not alt or alt["id"] != pid:
            token = secrets.token_urlsafe(9)
            while len(self.entwuerfe) >= ENTWURF_MAX:
                del self.entwuerfe[min(self.entwuerfe, key=lambda t: self.entwuerfe[t]["ts"])]
        self.entwuerfe[token] = {"id": pid, "panel": clean[pid], "ts": now}
        return token, weg

    def entwurf_profil(self, token: str, pid: str | None) -> dict | None:
        """Der Entwurf zu Token und Profil-Kennung, sonst None (unbekannt,
        abgelaufen oder fuer ein anderes Profil). Jede Nutzung verlaengert ihn."""
        e = self.entwuerfe.get(token or "")
        now = time.time()
        if not e or e["id"] != (pid or "") or now - e["ts"] > ENTWURF_DAUER:
            return None
        e["ts"] = now
        return e["panel"]

    def vorschau_zurueck(self, device: str) -> str:
        """Profil, zu dem ein Geraet nach der Vorschau zurueckkehrt: das, was es vor
        der ersten Vorschau zeigte (bleibt bei jeder weiteren Vorschau gleich)."""
        alt = self.vorschau_geraet.get(device)
        if alt:
            return alt["zurueck"]
        return next((p.get("id", "") for ws, p in self.conn_prof.items()
                     if self.conn_dev.get(ws) == device and not p.get("entwurf")), "")

    async def vorschau_beenden(self, device: str) -> int:
        """Die Vorschau am Geraet beenden: es kehrt zum Profil davor zurueck
        ({t:"switch"} ohne Entwurf). Nur Verbindungen, die den Entwurf noch zeigen -
        wurde das Geraet inzwischen anders umgeschaltet, bleibt es dabei. Zeigt ihn
        gerade keine (die Seite laedt noch neu, oder das Geraet ist offline), merkt
        sich der Server das Ende ohne Frist: ws_handler schickt die naechste Verbindung
        des Geraets mit diesem Token zurueck, auch nach einem langen WLAN-Ausfall.
        -> Anzahl (ein vorgemerktes Ende zaehlt mit)."""
        e = self.vorschau_geraet.pop(device, None)
        self.vorschau_ende.pop(device, None)
        if not e:
            return 0
        n, unterwegs = 0, False
        for ws, info in list(self.conn_info.items()):
            if info.get("dev") != device:
                continue
            if info.get("entwurf") == e["token"]:
                if await self._neu_laden(ws, {"t": "switch", "panel": e["zurueck"], "entwurf": ""}):
                    n += 1
            elif info.get("entwurfKommt") == e["token"]:
                unterwegs = True
        if unterwegs or not n:
            self.vorschau_ende[device] = {"token": e["token"], "zurueck": e["zurueck"]}
            n += 1
        return n

    def resolve_profile(self, pid: str | None, entwurf: dict | None = None) -> dict:
        """Aufgeloestes Panel-Profil: Theme-Vars, Tabs, Raum-/Kategorie-Filter.
        Mit `entwurf` (entwurf_profil) gilt dieses Profil statt des gespeicherten.
        Ein unbekanntes Profil (geloescht, vertippt) zeigt das Standardprofil und
        heisst auch so: sonst nennte die Geraeteliste eine Ansicht, die es nicht
        mehr gibt."""
        prof = entwurf if entwurf is not None else \
            (self.panels.get(pid or "") or self.panels.get("default") or {})
        pid = pid if pid and (entwurf is not None or pid in self.panels) else "default"
        ui = {**self.theme.get("ui", {}), **(prof.get("ui") or {})}
        states = {**self.theme.get("states", {}), **(prof.get("states") or {})}
        tabs = [t for t in (prof.get("tabs") or ui.get("tabs") or []) if _is_tab(t)] or \
            ["favoriten", "zentral", "raeume", "kategorien"]
        return {
            "id": pid,
            # Entwurf (nicht gespeichert): die Visu zeigt es an, die ID-Nachschlager
            # (panel_dpms, panel_night, panel_reload) lesen dann `roh` statt der Datei
            **({"entwurf": True, "roh": prof} if entwurf is not None else {}),
            "title": prof.get("title") or "LoxPanel",
            "tabs": list(tabs),
            "rooms": self._resolve_ids(prof.get("rooms"), self.rooms),
            "cats": self._resolve_ids(prof.get("cats"), self.cats),
            "vars": self._theme_vars(states, ui),
            "tiles": prof.get("tiles") or {},
            "roomCats": [c for c in (prof.get("roomCats") or []) if isinstance(c, str)],
            "hide": {u for u in (prof.get("hide") or []) if isinstance(u, str)},
            # Liste, kein Set: die Reihenfolge ist die Anzeigereihenfolge.
            "picks": [u for u in (prof.get("picks") or []) if isinstance(u, str)],
            "pickName": prof.get("pickName") or "",
            "pickTabs": _pick_tabs(prof),   # bis 4 freie Seiten [{name, picks}]
            "lang": (ui.get("lang") or "de"),   # Panel-Sprache (Datum/Uhr; spaeter i18n der Texte)
            "fill": bool(ui.get("fill")),       # Visu fuellt grosse Screens (quadratische Kacheln)
            # Split-Screen an/aus (aus = 4"-Panel: nur die Visu, keine Pane 2, keine
            # Verdopplung). Default an; nur bei explizitem False aus.
            "split": ui.get("split") is not False,
            # Sprungmarken der unteren Leiste (Raum-Panel, freie Auswahl): ein
            # Tipp springt zur Gruppe (Standard) oder zeigt nur sie (Filter).
            "catFilter": ui.get("catFilter") is True,
            # Kachel-Aufbau: "" = neuer (Raum oben rechts, Zustand gross, Bedienleiste
            # unten), "classic" = der bisherige. Das Raster (cols/rows) bleibt davon
            # unberuehrt. Ein Kachel-Set bringt seinen eigenen (neuen) Aufbau mit.
            "tileLayout": "classic" if _kachel_klassisch(ui) else "",
            # Kachel-Set: "" = Standard, sonst Name aus theme_colors.KACHEL_SETS.
            # Die Visu setzt ihn als html[data-kachelset], dazu seine Art fuer
            # Kachel und Tab-Leiste (html[data-kachelset-aufbau|-leiste], dort
            # haengen die Regeln); die Farben und Masse stehen in vars.
            "tileSet": _clean_kachel_set(ui.get("tileSet")) or "",
            "tileSetAufbau": theme_colors.kachel_set_art(_clean_kachel_set(ui.get("tileSet")))[0],
            "tileSetLeiste": theme_colors.kachel_set_art(_clean_kachel_set(ui.get("tileSet")))[1],
            # Automatisches Raster: Zielgroesse einer Kachel in px; 0 = festes
            # Raster aus cols/rows (4"-Panel und jedes Profil ohne "auto").
            "gridAuto": ((_clean_kachelziel(ui.get("tileSize")) or KACHEL_ZIEL_STANDARD)
                         if ui.get("grid") == "auto" else 0),
            # Feste Breite des Widgets im automatischen Raster in Kachelspalten
            # (hochkant Zeilen); 0 = Automatik, rund PANE_ANTEIL der Spalten.
            "paneCols": _clean_pane_spalten(ui.get("paneCols")) or 0,
            # Split-Pane pro Tab: Tab-Kennung -> "weather"|"calendar"|"player:<uuid>".
            # Nur wirksam, wenn split an ist. Das Panel rendert die passende Pane.
            # Normiert, denn die Datei wird beim Laden nicht sanitisiert: eine
            # von Hand geschriebene "status:A, B" kaeme sonst roh ins Panel.
            "panes": ({str(k): _clean_tabpane(v) for k, v in ui["panes"].items()
                       if isinstance(k, str) and _clean_tabpane(v)}
                      if isinstance(ui.get("panes"), dict) else {}),
            # Seiten (Tab-Kennungen), deren Anzeige-Bausteine als Werteleiste
            # in einer Zeile ueber dem Raster stehen statt als Kacheln.
            "valueBar": _clean_werteleiste(ui.get("valueBar")),
            # Rechte Spalte der Uhr-Seite: "" = Automatik (Termine, sonst
            # Wetter-Details), sonst off/calendar/weather/energy:/camera:/status:.
            "svPane": _clean_svpane(ui.get("svPane")),
            # Skalierung laut Profil, sonst global (ui ist oben schon aus Theme
            # und Profil gemischt): "off" | "auto" | Faktor. Ein Geraet kann
            # sie uebersteuern, siehe effective_scale().
            "scale": _clean_scale(ui.get("scale")) or "off",
            # Visu-PIN gesicherter Bausteine so viele Sekunden behalten (0 = nie)
            "pinMerken": _pin_merken(ui.get("pinMerken")),
            # Gesten wie auf den Loxone-Tastern (ui ist aus Vorgaben und Ansicht
            # gemischt: die Ansicht geht vor) und ihr Raum ausserhalb von
            # Raumseiten ("" = dort keine Wirkung)
            "gesten": ui["gesten"] if isinstance(ui.get("gesten"), bool) else GESTEN_STANDARD,
            "gestenRaum": _clean_kennung(ui.get("gestenRaum")),
            # ... und ihr Hinweis-Symbol (Vorgaben und Ansicht gemischt wie oben)
            "gestenHinweis": (ui["gestenHinweis"] if isinstance(ui.get("gestenHinweis"), bool)
                              else GESTEN_HINWEIS_STANDARD),
            # Aufbau der Hausseite (HAUS_AUFBAUTEN)
            "hausAufbau": ui["hausAufbau"] if ui.get("hausAufbau") in HAUS_AUFBAUTEN else HAUS_AUFBAU_STANDARD,
        }

    def player_blocks(self, uuid: str, mehr: bool = False):
        """Player-Bloecke (Cover/Titel/Transport/Lautstaerke) einer festen
        AudioZone fuer die linke Split-Player-Region. None, wenn keine gueltige
        Audio-Zone. Der `more`-Block (schwebender ⋮-Button) wird entfernt,
        ausser mit mehr=True (Spieler der Hausseite: ⋮ zur Musikauswahl)."""
        c = self.controls.get(uuid or "")
        if not c or c.get("type") not in ("AudioZone", "AudioZoneV2"):
            return None
        try:
            v = self._view_control_inner(uuid)
        except Exception:
            log.exception("player_blocks fehlgeschlagen (%s)", uuid)
            return None
        return [b for b in (v.get("blocks") or []) if mehr or b.get("k") != "more"]

    def intercom_blocks(self, uuid: str):
        """Volle Intercom-Ansicht (Video + Tuer-/Ausgang-Buttons + Klingel-Banner)
        einer Intercom-UUID fuer die Kamera-Pane. Gleiche Bloecke wie die
        Detailansicht -> das Bild wird wie beim Baustein direkt geladen (robust,
        auch wo ein nacktes MJPEG-<img> nicht anzeigt). None, wenn kein Intercom.
        Was nur auf die Detailseite gehoert (Klingel-Zeile, Geraetezustand,
        Antworten und Stumm der v2), bleibt draussen."""
        c = self.controls.get(uuid or "")
        if not c or c.get("type") not in INTERCOM_TYPES:
            return None
        try:
            v = self._view_control_inner(uuid)
        except Exception:
            log.exception("intercom_blocks fehlgeschlagen (%s)", uuid)
            return None
        return [b for b in (v.get("blocks") or [])
                if b.get("k") != "more" and b.get("id") not in ("klingel", "zustand", "antworten", "stumm")]

    def status_blocks(self, uuids) -> list:
        """Frei gewaehlte Bausteine als Nur-Lese-Kacheln fuer die rechte Spalte
        des Screensavers. Baut bewusst ueber _control_item() — damit stehen dort
        Name, Wert, Icon und Zustandsfarbe genau so wie auf einer Kachel, und ein
        neuer Bausteintyp wirkt hier mit, ohne dass jemand daran denken muss.
        Unbekannte UUIDs (geloeschter Baustein) fallen still weg."""
        raus = []
        for u in list(uuids or [])[:SV_STATUS_MAX]:
            if u not in self.controls:
                continue
            try:
                it = self._control_item(u, show_room=True)
            except Exception:
                log.exception("status_blocks: Baustein uebersprungen (%s)", u)
                continue
            # Die Uhr-Seite zeigt nur an — Navigation und Steuer-Buttons haetten
            # dort keine Wirkung (ein Tipp weckt das Panel) und wuerden Platz
            # kosten. Deshalb hier raus, statt sie im Panel zu ignorieren.
            for k in ("nav", "controls", "secured"):
                it.pop(k, None)
            raus.append(it)
        return raus

    def energy_blocks(self, uuid: str, max_cons: int = 6):
        """Energiefluss-Daten (Radial, Loxone-Standard) einer EFM/EnergyManager2-
        Kachel fuers Panel. EFM: genau die in der Loxone-Config angelegten Knoten
        (actual0..5, Name UND Icon vom Miniserver) – das ist wie in der Loxone-App
        die vollstaendige Liste inkl. PV/Netz/Speicher, daher KEINE zusaetzlichen
        Summen-Knoten (sonst Dopplung). EnergyManager2 (oder EFM ohne eigene
        Knoten): Summen-Knoten aus Ppwr/Gpwr/Spwr. 0-W-Knoten werden mitgezeigt
        (grau/inaktiv); nur nicht existierende (kein State) entfallen. Leistung in
        WATT, Flussrichtung fuers Diagramm. None bei ungueltiger Kachel. Reine
        Anzeige, keine Steuerung. max_cons = Loxones Grenze (actual0..5, max. 6).

        Vorzeichen wie bei Loxone aus Sicht des Hauses (siehe _flow_text):
        Gpwr>0 = Netzbezug (rein), <0 = Einspeisung (raus); Spwr>0 = Speicher
        entlaedt (rein), <0 = laedt (raus); Ppwr = Erzeugung (rein). Dasselbe
        gilt fuer EFM-Knoten mit nodeType Storage. flow: "in" = zur Mitte
        (gruen), "out" = nach aussen (orange), None = 0/inaktiv (grau)."""
        c = self.controls.get(uuid or "")
        if not c or c.get("type") not in ("EFM", "EnergyManager2"):
            return None
        det = c.get("details") or {}
        fmt = det.get("actualFormat") or "%.2f kW"
        to_w = 1000.0 if "kw" in fmt.lower() else 1.0   # States meist in kW -> Watt

        def watt(key):
            """Leistung in W; None, solange sie fehlt - auch bei NaN/unendlich, die als
            Binaer-Double gueltig sind: unbekannt, nicht 0 und nicht in Summen."""
            v = self._state(c, key)
            try:
                w = float(v) * to_w
            except (TypeError, ValueError):
                return None
            return w if math.isfinite(w) else None

        def classify(nt, v):
            """Richtung (flow: in/out/None) UND Farbe/Rolle (kind) je Knoten aus
            Loxone-nodeType + Vorzeichen:
              kind "prod" = Quelle, gruen  (PV/Production; Netz-Einspeisung; Speicher entladen)
              kind "grid" = Netzbezug, ROT (Netz liefert Strom ins Haus)
              kind "load" = Verbraucher, orange (Load/Group; Speicher laden)
              kind "idle" = 0 W, grau
            PV/Production ist immer Quelle (kann nie beziehen). Netz: Bezug (v>0)
            rein/rot, Einspeisung (v<0) raus/gruen. Speicher wie das Netz aus
            Sicht des Hauses: entladen (v>0) rein/gruen, laden (v<0) raus/orange."""
            ntl = (nt or "").lower()
            if not v:
                return (None, "idle")
            if ntl == "production":
                return ("in", "prod")
            if ntl == "grid":
                return ("in", "grid") if v > 0 else ("out", "prod")
            if ntl in ("storage", "battery"):
                return ("in", "prod") if v > 0 else ("out", "load")
            return ("out", "load") if v > 0 else ("in", "prod")

        pv = watt("Ppwr")                       # Erzeugung
        g = watt("Gpwr")                        # Netz: >0 Bezug (rein), <0 Einspeisung (raus)
        sp = watt("Spwr")                       # Speicher: >0 entlaedt (rein), <0 laedt (raus)
        try:
            soc = float(self._state(c, "Ssoc"))
        except (TypeError, ValueError):
            soc = None
        if soc is not None and not math.isfinite(soc):
            soc = None

        def agg_nodes():
            """Feste Summen-Knoten (PV/Netz/Speicher) aus Ppwr/Gpwr/Spwr – fuer
            EnergyManager2 und als Rueckfall, wenn ein EFM keine eigenen Knoten hat."""
            def mk(name, icon, val, nt, extra=None):
                fl, kd = classify(nt, val)
                n = {"name": name, "icon": icon, "w": abs(val) if val else 0.0,
                     "flow": fl, "kind": kd}
                if extra:
                    n.update(extra)
                return n
            ns = [mk("PV", "pv", pv, "production"),
                  mk("Netz", "grid", g, "grid")]
            if soc is not None or (sp not in (None, 0.0)):
                ns.append(mk("Speicher", "battery", sp, "storage",
                             {"soc": max(0.0, min(100.0, soc))} if soc is not None else None))
            return ns

        # EFM: die actual0..5-Knoten SIND – wie in der Loxone-App – die vollstaendige
        # Liste (inkl. PV/Netz/Speicher, falls dort angelegt). Daher KEINE
        # zusaetzlichen Summen-Knoten oben drauf (sonst Dopplung). Name, Icon UND
        # Rolle (nodeType) kommen vom Miniserver; 0-W-Knoten bleiben (grau).
        def bilanz():
            """Hausverbrauch aus der Energiebilanz (Sicht des Hauses: was
            hereinkommt, wird verbraucht) = Erzeugung + Netz + Speicher. Ohne
            Netzwert unbekannt (None), ebenso solange PV oder Speicher angelegt
            sind, aber noch keinen Wert haben. Fehlt der State ganz (beim EM2
            auch HasSpwr false), hat die Anlage keinen: Beitrag 0."""
            if g is None:
                return None
            summe = g
            for key, val, da in (("Ppwr", pv, True), ("Spwr", sp, det.get("HasSpwr", True))):
                if not da or key not in (c.get("states") or {}):
                    continue
                if val is None:
                    return None
                summe += val
            return max(0.0, summe)

        cons = []
        prod_sum = cons_sum = 0.0
        hat_verbraucher = prod_knoten = prod_fehlt = False
        if c.get("type") == "EFM":
            for i, (label, nd) in enumerate(self._named_items(det.get("nodes"))[:max_cons]):
                v = watt(f"actual{i}")
                nt = nd.get("nodeType") if isinstance(nd, dict) else None
                if v is None:
                    if (nt or "").lower() == "production":
                        prod_fehlt = True
                    continue
                flow, kind = classify(nt, v)
                cons.append({"name": label or f"Knoten {i + 1}", "icon": "load",
                             "iconUrl": self._node_icon_url(nd),
                             "w": abs(v), "flow": flow, "kind": kind})
                ntl = (nt or "").lower()
                if ntl == "production":
                    prod_knoten = True
                    prod_sum += abs(v)
                elif ntl in ("load", "group"):
                    hat_verbraucher = True
                    if v > 0:
                        cons_sum += abs(v)
        def erzeugung():
            """Erzeugung in W: die Erzeugungs-Knoten, sonst Ppwr. None, wenn eine
            Erzeugung angelegt ist, aber keinen Wert hat - keine erfundene Null."""
            if prod_sum:
                return prod_sum
            if pv is not None:
                return abs(pv)
            if prod_knoten:
                return 0.0
            if prod_fehlt or "Ppwr" in (c.get("states") or {}):
                return None
            return 0.0

        if cons:
            cons.sort(key=lambda n: (n["flow"] is None, -n["w"]))   # aktiv zuerst, 0 W ans Ende
            nodes = cons
            prod_total = erzeugung()
            # gemessene Verbraucher-Knoten, sonst die Bilanz
            cons_total = cons_sum if hat_verbraucher else bilanz()
        else:
            nodes = agg_nodes()   # EM2 oder EFM ohne eigene Knoten
            prod_total = erzeugung()
            cons_total = bilanz()
        return {"control": uuid, "name": _clean(c.get("name")) or "Energiefluss",
                "nodes": nodes,
                "totals": {"prod": prod_total, "cons": cons_total, "grid": g or 0.0}}

    def _tab_meta(self, tab_keys, prof: dict | None = None) -> dict:
        """Label + Icon fuer dynamische Tabs (Kategorie-, Raum- und Auswahl-Tab).
        Die 4 Standard-Tabs kennt das Frontend selbst; hier nur `cat:`/`room:`
        und `auswahl` - letzteres traegt einen frei gewaehlten Namen, sein
        Symbol bringt das Panel selbst mit."""
        meta = {}
        for t in tab_keys or []:
            if _is_pick(t):
                _pts = _pick_tabs(prof)
                _i = _pick_index(t)
                _e = _pts[_i] if 0 <= _i < len(_pts) else {}
                _ic = _e.get("icon") or ""
                # Fertige URL (/icon?p=… oder /loxlib?n=…) direkt, sonst ein
                # Loxone-Pfad ueber _icon_url aufloesen (rueckwaertskompatibel).
                _url = _ic if (isinstance(_ic, str) and _ic.startswith("/")) else (self._icon_url(_ic) or "")
                meta[t] = {"label": (_e.get("name") or "Auswahl"), "iconUrl": _url}
                if _e.get("widget") == HAUS_TAB:
                    meta[t]["haus"] = True   # ohne eigenes Symbol das Haus der Leiste
            elif isinstance(t, str) and t.startswith("cat:"):
                cat = self.cats.get(t[4:], {})
                meta[t] = {"label": _clean(cat.get("name")) or "Kategorie",
                           "iconUrl": self._icon_url(cat.get("image")) or ""}
            elif isinstance(t, str) and t.startswith("room:"):
                room = self.rooms.get(t[5:], {})
                meta[t] = {"label": _clean(room.get("name")) or "Raum",
                           "iconUrl": self._icon_url(room.get("image")) or ""}
        return meta

    def ansicht_wirksam(self, pid: str | None) -> str:
        """Die Ansicht, die die Visu fuer `pid` tatsaechlich zeigt (wie resolve_profile):
        eine leere, geloeschte oder vertippte Kennung zeigt das Standardprofil."""
        return pid if pid and pid in self.panels else "default"

    def _ui_roh(self, pid: str | None, roh: dict | None) -> dict:
        """ui des Profils `pid` aus der Datei, bei einem Entwurf (`roh`) aus ihm. Eine
        unbekannte Kennung gilt wie in der Visu als Standardprofil (ansicht_wirksam):
        sonst bekaeme ein Agent mit ?panel= leer oder geloescht nur die Vorgaben."""
        if roh is None:
            roh = self.panels.get(self.ansicht_wirksam(pid)) or {}
        return roh.get("ui") or {}

    def panel_dpms(self, pid: str | None, roh: dict | None = None, dev: str = ""):
        """Display-Abschaltzeit (Sek.) fuer ein Panel: am Geraet (devices[name].dpmsOff,
        Einrichtung Schritt 4: Display-Regeln stehen in den Vorgaben und am Geraet),
        sonst aus dem Profil (ein aelterer Eintrag ui.dpmsOff gilt weiter), sonst die
        Vorgabe (0=nie, None=nicht gesetzt -> Agent nutzt seinen kiosk.conf-Default).
        Wird dem Panel-Agenten in der Announce-Antwort mitgegeben (er fuehrt xset aus)."""
        d = self.devices.get(dev) if dev else None
        if isinstance(d, dict) and isinstance(d.get("dpmsOff"), (int, float)) and not isinstance(d.get("dpmsOff"), bool):
            return max(0, min(3600, int(d["dpmsOff"])))
        ui = {**self.theme.get("ui", {}), **self._ui_roh(pid, roh)}
        v = ui.get("dpmsOff")
        return max(0, min(3600, int(v))) if isinstance(v, (int, float)) else None

    def panel_night(self, pid: str | None, roh: dict | None = None, dev: str = "") -> dict:
        """Nachtmodus je Panel: `dim` = Abdunklung in Prozent (0 = aus), `wake` =
        Sekunden, die eine Beruehrung wieder voll aufhellt (0 = nicht aufhellen).
        Wie panel_dpms(): am Geraet (devices[name].nightDim/nightWake, Einrichtung
        Schritt 4b), sonst ein aelterer Eintrag des Profils, sonst die Vorgabe.
        Die Nacht-Uhr hat keinen Wert je Geraet."""
        ui = {**self.theme.get("ui", {}), **self._ui_roh(pid, roh)}
        d = self.devices.get(dev) if dev else None
        if isinstance(d, dict):
            ui = {**ui, **{k: d[k] for k in ("nightDim", "nightWake")
                           if isinstance(d.get(k), (int, float)) and not isinstance(d.get(k), bool)}}

        def _num(key, lo, hi, default):
            v = ui.get(key)
            return max(lo, min(hi, int(v))) if isinstance(v, (int, float)) else default

        uhr = ui.get("nightClock")
        return {"dim": _num("nightDim", 0, 90, NACHT_STANDARD["nightDim"]),
                "wake": _num("nightWake", 0, 300, NACHT_STANDARD["nightWake"]),
                # Nacht-Uhr statt der Uhr-Seite und ihre Helligkeit in Prozent
                "uhr": uhr if isinstance(uhr, bool) else NACHT_STANDARD["nightClock"],
                "uhrHell": _num("nightClockBright", NACHT_UHR_HELL_MIN, 100, NACHT_STANDARD["nightClockBright"])}

    def night_control_options(self) -> list:
        """Bausteine, die als Nacht-Ausloeser oder Praesenzmelder eines Geraets
        taugen: alles mit einem `active`-State
        (Switch, InfoOnlyDigital, PresenceDetector ...). Damit laesst sich auch ein
        Loxone-Betriebsmodus nutzen, sobald er in der Visu auf so einem Baustein
        liegt — der Modus selbst steht nicht in der Struktur (s. ARCHITEKTUR.md)."""
        out = []
        for u, c in self.controls.items():
            if not (c.get("states") or {}).get("active"):
                continue
            name = _clean(c.get("name"))
            if not name:
                continue
            out.append({"uuid": u, "name": name, "type": c.get("type"),
                        "room": _clean((self.rooms.get(c.get("room")) or {}).get("name"))})
        return sorted(out, key=lambda d: (d["room"], d["name"]))

    def geste_taster_optionen(self) -> list:
        """Taster, die "Raum verlassen" und "Haus aus" ausloesen koennen
        (GESTEN_TASTER_TYPEN, ohne Visu-PIN): [{uuid, name, room}]."""
        out = []
        for u, c in self.controls.items():
            name = _clean(c.get("name"))
            if c.get("type") in GESTEN_TASTER_TYPEN and not c.get("isSecured") and name:
                out.append({"uuid": u, "name": name,
                            "room": _clean((self.rooms.get(c.get("room")) or {}).get("name"))})
        return sorted(out, key=lambda d: (d["room"], d["name"]))

    def licht_stimmung_optionen(self) -> list:
        """Lichtsteuerungen mit ihren Stimmungen fuer "Stimmung beim Einschalten"
        je Geraet: [{uuid, name, room, moods: [{id, name}]}]."""
        out = []
        for u, c in self.controls.items():
            if c.get("type") not in GESTEN_LICHT_TYPEN:
                continue
            out.append({"uuid": u, "name": _clean(c.get("name")),
                        "room": _clean((self.rooms.get(c.get("room")) or {}).get("name")),
                        "moods": [{"id": m, "name": n} for m, n in self._geste_stimmungen(u)]})
        return sorted(out, key=lambda d: (d["room"], d["name"]))

    def _sun_minutes(self) -> tuple[int, int] | None:
        """Sonnenauf-/-untergang als Minuten seit Mitternacht (Ortszeit).

        Rangfolge: zuerst der MINISERVER (globalStates `sunrise`/`sunset` liefern
        genau dieses Format), sonst der Wetterdienst aus den Front-Daten ("HH:MM").
        None, wenn keine Quelle brauchbare Werte hat."""
        gs = self.global_states or {}
        ms = []
        for key in ("sunrise", "sunset"):
            u = gs.get(key)
            v = self.states.get(u) if isinstance(u, str) else None
            ms.append(int(v) if isinstance(v, (int, float)) and 0 <= v < 1440 else None)
        if ms[0] is not None and ms[1] is not None:
            return ms[0], ms[1]
        w = (self._front or {}).get("weather") or {}
        out = []
        for key in ("sunrise", "sunset"):
            hm = w.get(key)
            if not (isinstance(hm, str) and ":" in hm):
                return None
            h, _, m = hm.partition(":")
            try:
                out.append(int(h) * 60 + int(m))
            except ValueError:
                return None
        return out[0], out[1]

    def _night_now(self) -> bool:
        """Ist gerade Nacht?

        Rangfolge: ein in den Einstellungen gewaehlter Baustein (sein `active`-State
        = Nacht), sonst die Sonnenzeiten nach _sun_minutes() (Miniserver vor
        Wetterdienst), zuletzt NIGHT_FROM..NIGHT_TO. Ein gewaehlter, aber nicht
        (mehr) vorhandener Baustein faellt still auf die Sonnenzeiten zurueck."""
        u = (self.night_cfg or {}).get("control")
        if u:
            c = self.controls.get(u)
            if c:
                return bool(self._state(c, "active"))
        now = datetime.now()
        sun = self._sun_minutes()
        if sun:
            cur = now.hour * 60 + now.minute
            return cur >= sun[1] or cur < sun[0]
        hm = now.strftime("%H:%M")
        return hm >= NIGHT_FROM or hm < NIGHT_TO

    def panel_reload(self, pid: str | None, roh: dict | None = None):
        """Auto-Neustart-Intervall (Stunden) fuer ein Panel aus dem Profil, 0 =
        aus. Gegen Einfrieren: der Agent startet Chromium periodisch neu, ohne
        Agent laedt sich die Visu neu. None = nicht eingestellt: Der Agent nimmt
        seinen Wert aus der kiosk.conf, die Visu laedt nachts neu
        (NEULADEN_STUNDE). Geht in die Announce-Antwort und die theme-Nachricht."""
        ui = {**self.theme.get("ui", {}), **self._ui_roh(pid, roh)}
        v = ui.get("reloadHours")
        return max(0, min(168, float(v))) if isinstance(v, (int, float)) else None

    def _has_agent(self, name: str) -> bool:
        """True, wenn zu einer Geraetekennung (?device=) ein Panel-Agent bekannt
        ist, der sich in den letzten 10 Minuten gemeldet hat. Dann schaltet der
        Agent das Display und startet Chromium neu; die Visu haelt sich mit
        eigener Abschaltung und eigenem Reload zurueck."""
        if not name:
            return False
        now = time.time()
        return any(a.get("name") == name and (now - a.get("ts", 0)) < 600
                   for a in self.agents.values())

    def _agenten_der_visu(self, dev: str, ip: str) -> list[dict]:
        """Agenten mit AGENT_KANN_PANEL hinter einer Visu, die als Geraet `dev`
        von `ip` verbindet. Vorrang hat der Agent mit dieser IP, auch wenn
        seine letzte Meldung aelter ist: Sein Chromium verbindet gerade, das
        Panel lebt (etwa gleich nach dem Booten). Meldet er eine andere Adresse
        (NAT), gelten alle mit dem Namen, die online sind, wie in switch_mode."""
        now = time.time()
        gleich = [a for a in self.agents.values() if a["name"] == dev]
        gleich = ([a for a in gleich if a["ip"] == ip]
                  or [a for a in gleich if now - a["ts"] < AGENT_ONLINE])
        return [a for a in gleich if AGENT_KANN_PANEL in a.get("features", ())]

    def geraet_ansicht(self, dev: str) -> str | None:
        """Die dem Geraet zugeordnete Ansicht (devices[dev].panel, Einrichtung
        Schritt 2), wirksam wie in der Visu (eine geloeschte zeigt das
        Standardprofil); None, wenn dem Geraet keine zugeordnet ist."""
        pid = (self.devices.get(dev) or {}).get("panel") if dev else None
        return self.ansicht_wirksam(pid) if pid else None

    def ansicht_fuer_geraet(self, dev: str) -> str | None:
        """Was ein Geraet zeigen soll, aus einer Stelle: laeuft ein Betriebsmodus
        mit Zuordnung fuer das Geraet (und hat niemand seitdem ausdruecklich
        gewaehlt), dessen Profil, sonst die zugeordnete Ansicht; None, wenn
        weder noch (dann gilt, was die Visu mit ?panel= verlangt)."""
        if not dev:
            return None
        cfg = self.devices.get(dev) or {}
        if self.last_mode and dev not in self.ansicht_gewaehlt and cfg.get("auto", True):
            mapped = (cfg.get("modes") or {}).get(self.last_mode)
            if mapped:
                return self.ansicht_wirksam(mapped)
        return self.geraet_ansicht(dev)

    def geraet_zuordnen(self, dev: str, panel: str) -> None:
        """Ansicht `panel` dem Geraet zuordnen und speichern (leer = Standard-
        ansicht, der Schluessel faellt weg). Die uebrigen Einstellungen des
        Geraets bleiben; ein Geraet ohne andere Einstellungen entsteht damit."""
        devices = {n: dict(c) for n, c in self.devices.items()}
        cfg = devices.setdefault(dev, {"auto": True, "modes": {}})
        if panel:
            cfg["panel"] = panel
        else:
            cfg.pop("panel", None)
        self._write_devices(self._sanitize_devices(devices, set(self.panels)))

    def effective_scale(self, prof: dict | None, dev: str) -> str | float:
        """Wirksame Skalierung eines Panels: die des Geraets, falls dort eine
        gesetzt ist, sonst die des Profils (resolve_profile() hat dort schon
        die globale eingemischt). So lassen sich zwei Displays mit demselben
        Profil unterschiedlich einstellen."""
        d = self.devices.get(dev) if dev else None
        if isinstance(d, dict):
            sc = _clean_scale(d.get("scale"))
            if sc is not None:
                return sc
        return (prof or {}).get("scale") or "off"

    def effective_grid_auto(self, prof: dict | None, dev: str) -> int:
        """Zielkachel des automatischen Rasters fuer ein Panel: die des Geraets
        (devices[name].tileTarget), falls dort eine steht, sonst die des
        Profils - wie bei der Skalierung. Nur im Kachel-Layout "Automatisch"
        (gridAuto > 0): ein festes Raster bleibt fest, auch wenn das Geraet
        eine Zielkachel traegt."""
        g = int((prof or {}).get("gridAuto") or 0)
        d = self.devices.get(dev) if dev else None
        if g and isinstance(d, dict):
            z = _clean_kachelziel(d.get("tileTarget"))
            if z is not None:
                return z
        return g

    def device_list(self) -> dict:
        """Alle bekannten Anzeigegeraete, zusammengefuehrt ueber den Namen:
        Panel-Agenten (Announce), verbundene Browser (?device=) und die in
        panels.json konfigurierten Geraete (Betriebsmodus-Automatik). Browser
        ohne Namen stehen getrennt unter `anonymous` (nach IP) und koennen
        aus den Einstellungen benannt werden (`/api/device/name`)."""
        now = time.time()
        devs: dict[str, dict] = {}

        def entry(name: str) -> dict:
            return devs.setdefault(name, {
                "name": name, "agent": None, "connections": 0, "online": False,
                "profile": "", "kiosk": "", "ip": "", "lastSeen": 0.0, "configured": False,
                "zugeordnet": "", "screen": {}, "presence": None, "vorschau": None})

        for a in self.agents.values():
            if (now - a["ts"]) >= 600:
                continue
            e = entry(a["name"])
            e["agent"] = {"ip": a["ip"], "port": a["port"], "kiosk": a["kiosk"],
                          "panel": a["panel"], "online": (now - a["ts"]) < AGENT_ONLINE}
            e["ip"] = a["ip"]
            e["lastSeen"] = max(e["lastSeen"], a["ts"])
            e["online"] = e["online"] or e["agent"]["online"]
        anonymous = []
        for ws, info in list(self.conn_info.items()):
            prof = (self.conn_prof.get(ws) or {}).get("id", "")
            if not info.get("dev"):
                if info.get("vorschau"):   # Vorschaufenster des Konfigurators: kein Geraet
                    continue
                anonymous.append({"ip": info.get("ip", ""), "code": info.get("code", ""), "profile": prof,
                                  "kiosk": info.get("kiosk", ""), "since": info.get("ts", 0),
                                  "screen": info.get("screen") or {}})
                continue
            e = entry(info["dev"])
            e["connections"] += 1
            e["online"] = True
            e["profile"] = prof
            e["kiosk"] = info.get("kiosk") or e["kiosk"]
            e["ip"] = e["ip"] or info.get("ip", "")
            e["lastSeen"] = max(e["lastSeen"], info.get("ts", 0))
            if info.get("screen"):
                e["screen"] = info["screen"]   # zuletzt gemeldete Groesse (bei mehreren Fenstern das letzte)
        for name, cfg in self.devices.items():
            e = entry(name)
            e["configured"] = True
            e["zugeordnet"] = cfg.get("panel") or ""   # die eine Stelle: was das Geraet zeigen soll
        for name, on in self._presence_on.items():
            entry(name)["presence"] = on   # nur Geraete mit gekoppeltem Praesenzmelder
        for name, v in self.vorschau_geraet.items():   # Geraet zeigt einen Entwurf (Punkt 12)
            if name in devs:
                devs[name]["vorschau"] = {"id": v["id"], "bis": v["bis"]}
        for e in devs.values():
            e["type"] = "agent" if e["agent"] else (e["kiosk"] if e["kiosk"] in KIOSK_APPS else "browser")
            e["tileSuggest"] = _kachel_vorschlag(e["screen"])   # Zielkachel aus der gemeldeten Groesse
            if e["agent"] and not e["profile"]:
                # was die Visu des Agenten zeigt: eine geloeschte Ansicht ist dort das Standardprofil
                e["profile"] = self.ansicht_wirksam(e["agent"]["panel"])
        anonymous.sort(key=lambda a: (a["ip"], a["code"]))
        return {"devices": sorted(devs.values(), key=lambda e: e["name"].lower()),
                "anonymous": anonymous, "profiles": sorted(self.panels)}

    def diagnose_daten(self, geraet: str = "", aufgaben: dict | None = None,
                       gestartet: float | None = None) -> tuple[dict, set]:
        """Angaben fuer das Diagnosepaket (diagnose.paket) -> (daten, Werte, die
        zusaetzlich geschwaerzt werden: Kennwort und Token im Speicher). Mit
        `geraet` dessen Zustand und Ansicht, sonst alle Geraete in Kurzform.
        KeyError, wenn es das Geraet nicht gibt. Zeiten als Unix-Sekunden."""
        liste = self.device_list()["devices"]
        ok, seit, bestaetigt = self._verbindung_stand()
        daten = {
            "erstellt": datetime.now().isoformat(timespec="seconds"),
            "version": dict(VERSION),
            "server": {"python": platform.python_version(), "system": platform.platform(),
                       "laufzeit_s": round(time.monotonic() - gestartet) if gestartet is not None else None,
                       "aufgaben": aufgaben or {}, "panels": len(self.conn_route),
                       "log_level": logging.getLevelName(logging.getLogger().level)},
            "miniserver": {"host": self.host, "port": self.port, "benutzer": self.user,
                           "verbunden": self._ms_verbunden_seit is not None,
                           "verbunden_seit": self._ms_verbunden_seit,
                           "weg_seit": seit, "bestaetigt": bestaetigt, "fehler": self._ms_fehler,
                           "struktur": bool(self.controls), "bausteine": len(self.controls),
                           "raeume": len(self.rooms), "kategorien": len(self.cats), **self.ms_struktur},
            "audioserver": [{"host": h, "port": c.port, "verbunden": c.verbunden,
                             "gekoppelt": c.paired, "angemeldet": c.authed}
                            for h, c in sorted(self.audio_clients.items())],
        }
        if geraet:
            e = next((x for x in liste if x["name"] == geraet), None)
            if e is None:
                raise KeyError(geraet)
            daten["geraet"] = {"name": e["name"], "typ": e["type"], "online": e["online"],
                               "ansicht": e["profile"], "verbindungen": e["connections"], "ip": e["ip"],
                               "zuletzt": e["lastSeen"] or None, "bildschirm": e["screen"],
                               "agent": e["agent"], "praesenz": e["presence"],
                               "eingerichtet": e["configured"], "einstellungen": self.devices.get(geraet) or {}}
            roh = self.panels.get(e["profile"]) if e["profile"] else None
            if roh is not None:
                exp = self._panel_export(roh)
                ui = exp.get("ui") or {}
                daten["ansicht"] = {"id": e["profile"], "titel": exp.get("title") or "", "tabs": exp.get("tabs"),
                                    "kachelSet": ui.get("tileSet") or "", "farbton": ui.get("tileHue"),
                                    "aktiv": ui.get("tileActive"), "raster": ui.get("grid") or
                                    ([ui.get("cols"), ui.get("rows")] if ui.get("cols") else None)}
                daten["ansicht_einstellungen"] = exp
        else:
            daten["geraete"] = [{"name": e["name"], "typ": e["type"], "online": e["online"],
                                 "ansicht": e["profile"]} for e in liste]
        return daten, {g for g in (self.password, self.jwt) if g}

    def kopplungscode(self, wunsch: str) -> str:
        """Code fuer einen Browser ohne Namen: der mitgeschickte, wenn er
        gueltig ist (die Visu hat ihn sich beim letzten Verbinden gemerkt),
        sonst ein neuer, der gerade keiner anderen Verbindung gehoert."""
        wunsch = (wunsch or "").strip().upper()
        if _KOPPLUNG_RE.fullmatch(wunsch):
            return wunsch
        vergeben = {i.get("code") for i in self.conn_info.values()}
        while True:
            code = "".join(secrets.choice(KOPPLUNG_ZEICHEN) for _ in range(KOPPLUNG_LAENGE))
            if code not in vergeben:
                return code

    @staticmethod
    def _kopplung_msg(code: str, karte: bool) -> dict:
        """Nachricht an einen Browser ohne Namen: sein Code, und ob er die
        Karte "Dieses Geraet einrichten" zeigen soll (ohne ?panel= und ohne
        Namen hat niemand dieses Geraet eingerichtet). Die Adresse des
        Konfigurators setzt das Panel wie beim Einrichtungshinweis zusammen."""
        return {"t": "kopplung", "code": code, "karte": karte,
                "titel": "Dieses Gerät einrichten",
                "hinweis": "Der Konfigurator meldet dieses Gerät von selbst – dort Namen vergeben und einrichten:",
                "pfad": "/config", "adressen": _lan_adressen(),
                "unbekannt": "Die Adresse dieses Geräts steht in seinen WLAN-Einstellungen.",
                "weg": "Tippen blendet die Karte bis zum nächsten Laden aus."}

    def _presence_rebuild(self) -> None:
        """Praesenzmelder der Geraete (devices[name].presence) auf den active-State
        ihres Bausteins abbilden. Laeuft nach dem Einlesen der Struktur und nach
        dem Speichern der Geraete; wer devices oder controls sonst ersetzt (z. B.
        das Einspielen einer Sicherung), dem holt der Broadcaster das im
        naechsten Takt nach (_presence_quelle). Aendert sich dabei der Stand eines Geraets
        (Melder gewaehlt, waehrend jemand da ist, oder wieder entfernt), erfahren
        es seine Panels als Wecken, nie als Abschalten: aus schaltet nur der
        Melder selbst, wenn der Raum leer wird (_on_value). Ein Baustein, den es
        in der Struktur nicht (mehr) gibt, koppelt nichts."""
        self._presence_quelle = (self.devices, self.controls)
        pmap: dict[str, list[str]] = {}
        for name, cfg in (self.devices or {}).items():
            u = cfg.get("presence") if isinstance(cfg, dict) else None
            su = ((self.controls.get(u) or {}).get("states") or {}).get("active") if u else None
            if su:
                pmap.setdefault(su, []).append(name)
        self.presence_map = pmap
        jetzt = {n: bool(self.states.get(su)) for su, names in pmap.items() for n in names}
        for name in set(self._presence_on) | set(jetzt):
            neu = jetzt.get(name, False)
            if neu != self._presence_on.get(name, False):
                self._pending_presence.append({"dev": name, "on": True, "presence": neu})
        self._presence_on = jetzt
        if jetzt:
            log.info("Präsenz: %d Gerät(e) an einen Präsenzmelder gekoppelt", len(jetzt))

    async def display_drivers(self, on: bool, device: str = "", panel: str = "") -> list:
        """Display ueber die HTTP-Schnittstelle der Kiosk-App schalten (Fully
        Kiosk Remote Admin, WallPanel). Betroffen sind Geraete mit `display`-
        Treiber in panels.json: bei `device` genau dieses, bei `panel` die, die
        das Profil gerade zeigen, sonst alle. Liefert je Geraet ein Ergebnis."""
        showing = {}
        for ws, info in list(self.conn_info.items()):
            if info.get("dev"):
                showing[info["dev"]] = (self.conn_prof.get(ws) or {}).get("id", "")
        out = []
        # Ein bestimmtes Geraet direkt nachschlagen: der Praesenzmelder ruft das
        # je Geraet auf, ueber alle Geraete waere es quadratisch.
        geraete = ({device: self.devices[device]} if device in self.devices else {}) if device \
            else self.devices
        for name, cfg in geraete.items():
            disp = cfg.get("display") if isinstance(cfg, dict) else None
            if not disp:
                continue
            if panel and not device and showing.get(name) != panel:
                continue
            out.append(await self._drive_display(name, disp, on))
        return out

    async def _drive_display(self, name: str, disp: dict, on: bool) -> dict:
        sess = self._drv_session
        if sess is None or sess.closed:
            sess = self._drv_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=6))
        drv = disp.get("driver")
        res = {"device": name, "driver": drv, "on": on}
        pw = str(disp.get("password") or "")

        def von_gegenstelle(text: str) -> str:
            # Gibt die Gegenstelle die Anfrage wieder (Echo, Fehlerseite), stuende
            # das Kennwort im Klartext darin. Nur hier ersetzen: In selbst
            # gebildeten Meldungen ("Cannot connect to host h:port") verriete die
            # Ersetzung ueber den frei waehlbaren Port, ob er das Kennwort enthaelt.
            return text.replace(pw, "***") if pw else text
        try:
            if drv == "fully":
                # Fully Kiosk Browser, Remote Admin: GET /?cmd=screenOn|screenOff&password=...
                url = (f"http://{disp['host']}:{disp['port']}/?cmd="
                       f"{'screenOn' if on else 'screenOff'}&type=json"
                       f"&password={quote(str(disp.get('password') or ''), safe='')}")
                async with sess.get(url) as r:
                    txt = (await r.text())[:300]
                    ok = r.status == 200
                    try:
                        j = json.loads(txt)
                        if isinstance(j, dict) and str(j.get("status", "")).lower() == "error":
                            ok, txt = False, str(j.get("statustext") or txt)
                    except ValueError:
                        pass
            else:
                # WallPanel: POST /api/command {"wake": true|false}. false gibt nur
                # den Bildschirmschoner von WallPanel frei (eigene Abschaltzeit dort).
                url = f"http://{disp['host']}:{disp['port']}/api/command"
                async with sess.post(url, json={"wake": bool(on)}) as r:
                    txt = (await r.text())[:300]
                    ok = r.status == 200
            if not ok:
                res["error"] = f"HTTP {r.status}: {von_gegenstelle(txt)}".strip()
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as err:
            # ValueError: Host, den die Namensaufloesung nicht annimmt
            # ("tablet..home", Label ueber 63 Zeichen) - sonst bricht die
            # Schleife in display_drivers fuer alle folgenden Geraete ab
            ok = False
            # Ohne die Adresse: InvalidURL und ClientResponseError nennen sie
            # ganz, bei Fully samt Kennwort.
            if isinstance(err, aiohttp.InvalidURL):
                res["error"] = f"ungültige Adresse {disp['host']}:{disp['port']}"
            elif isinstance(err, aiohttp.ClientResponseError):
                res["error"] = f"HTTP {err.status}: {von_gegenstelle(err.message)}"
            else:
                res["error"] = str(err) or err.__class__.__name__
        res["ok"] = ok
        if not ok:
            # Das Kennwort so, wie es verschickt wurde (yarl kodiert anders als
            # quote()): aus einem Echo der Anfrage oder einer Meldung mit der
            # ganzen Adresse (Zeitueberschreitung beim Verbinden). Ersetzt den
            # ganzen Wert, das Ergebnis haengt also nicht vom Kennwort ab.
            res["error"] = re.sub(r"password=[^&\s]*", "password=***", res["error"])
            log.warning("Display-Treiber %s (%s): %s", name, drv, res["error"])
        return res

    async def _agent_start(self, agent: dict, profile: str) -> bool:
        """Startet den Kiosk eines Panel-Agenten mit einem Profil (Fernbefehl).
        Das Profil ersetzt eine offene Wahl. Ein Agent mit AGENT_KANN_PANEL
        behaelt es als Wahl, bis er es meldet: Scheitert der Befehl (Zeitlimit,
        Port gesperrt), uebernimmt er es so mit seiner naechsten Meldung."""
        if AGENT_KANN_PANEL in agent.get("features", ()):
            self.agent_wunsch[agent["ip"]] = profile
        else:
            self.agent_wunsch.pop(agent["ip"], None)
        url = f"http://{agent['ip']}:{agent['port']}/start"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json={"panel": profile},
                                  timeout=aiohttp.ClientTimeout(total=AGENT_BEFEHL_TIMEOUT)) as r:
                    return r.status == 200
        except Exception as err:
            log.warning("Agent %s Start(%s) fehlgeschlagen: %s",
                        agent.get("name"), profile, err)
            return False

    async def switch_mode(self, mode: str) -> list:
        """Betriebsmodus-Wechsel (von Loxone via /api/mode): jedes Panel mit
        aktiver Automatik und einer Zuordnung fuer diesen Modus auf sein Profil
        umschalten. Zwei Wege je Panel (adressiert ueber seinen Namen):
        1. geraeteunabhaengig: offene Browser-Verbindung mit `?device=<name>`
           bekommt per WS ein `{t:'switch'}` -> laedt sich mit neuem Profil neu
           (funktioniert auf jedem Browser/Kiosk, kein Agent noetig);
        2. Fallback: Linux-Panel-Agent per Fernstart (`?device=` nicht gesetzt),
           nur wenn er online ist; einen anderen zieht ws_handler beim
           Verbinden seines Chromium nach.
        Ein Agent, der das kann (AGENT_KANN_PANEL), uebernimmt das Profil im
        ersten Fall mit seiner naechsten Meldung (Abschaltzeit, Neustart-
        intervall, naechster Kiosk-Start). Ausdrueckliche Wahlen unter
        Displays gelten ab hier nicht mehr. Zeigt die Zuordnung auf eine Ansicht,
        die es nicht (mehr) gibt, gilt wie in der Visu das Standardprofil; die
        Zuordnung selbst bleibt (`statt` nennt sie im Ergebnis).
        """
        mode = (mode or "").strip()
        results: list = []
        if not mode:
            return results
        self.last_mode = mode   # merken -> frisch verbundene Geraete ziehen darauf nach
        self.ansicht_gewaehlt.clear()
        now = time.time()
        by_name = {a["name"]: a for a in self.agents.values() if (now - a["ts"]) < AGENT_ONLINE}
        for name, cfg in self.devices.items():
            if not cfg.get("auto", True):
                continue
            zugeordnet = (cfg.get("modes") or {}).get(mode)
            if not zugeordnet:
                continue
            profile = self.ansicht_wirksam(zugeordnet)
            statt = {} if profile == zugeordnet else {"statt": zugeordnet}
            ws_targets = [ws for ws, dev in self.conn_dev.items() if dev == name]
            if ws_targets:
                self.vorschau_geraet.pop(name, None)   # der Modus schaltet um: eine Vorschau endet damit
                self.vorschau_ende.pop(name, None)
                sent = 0
                for ws in ws_targets:
                    p = self.conn_prof.get(ws) or {}
                    if p.get("id") == profile and not p.get("entwurf"):
                        sent += 1            # zeigt bereits das richtige Profil (ein Entwurf davon nicht)
                        continue
                    if await self._send_or_drop(ws, {"t": "switch", "panel": profile}):
                        sent += 1
                for a in self.agents.values():
                    if (a["name"] == name and AGENT_KANN_PANEL in a.get("features", ())
                            and (now - a["ts"]) < AGENT_ONLINE):
                        self.agent_wunsch[a["ip"]] = profile
                results.append({"panel": name, "profile": profile,
                                "ok": sent > 0, "via": "ws", **statt})
                continue
            agent = by_name.get(name)
            if agent:
                ok = await self._agent_start(agent, profile)
                results.append({"panel": name, "profile": profile,
                                "ok": ok, "via": "agent", **statt})
            else:
                results.append({"panel": name, "profile": profile,
                                "ok": False, "error": "Gerät nicht online", **statt})
        return results

    def _room_ok(self, uuid: str, prof: dict | None) -> bool:
        ar = prof.get("rooms") if prof else None
        if ar is None:
            return True
        return self.controls.get(uuid, {}).get("room") in ar

    def _cat_ok(self, uuid: str, prof: dict | None) -> bool:
        ac = prof.get("cats") if prof else None
        if ac is None:
            return True
        return self.controls.get(uuid, {}).get("cat") in ac

    def _shown(self, uuid: str, prof: dict | None) -> bool:
        """False, wenn diese Kachel auf dem Panel einzeln ausgeblendet wurde
        (zusaetzlich zum Raum-/Kategorie-Filter). Gilt panelweit."""
        return not (prof and uuid in prof.get("hide", ()))

    # ---- Config-Seite (Panel-Editor) ----
    def _panel_export(self, raw: dict) -> dict:
        """Rohes Profil aus der Datei -> UI-Form (rooms/cats als UUID-Listen,
        in Anzeige-Reihenfolge; leere Liste = alle)."""
        r = self._resolve_ids(raw.get("rooms"), self.rooms)
        c = self._resolve_ids(raw.get("cats"), self.cats)
        tabs = [t for t in (raw.get("tabs") or VALID_TABS) if _is_tab(t)]
        ui = {k: v for k, v in (raw.get("ui") or {}).items()
              if k in ("iconSize", "nameSize", "subSize", "roomSize", "bigSize", "font", "nudgeX",
                       "dpmsOff", "reloadHours", "nightDim", "nightWake",
                       "cols", "rows", "fill", "baseColor",
                       "overlay", "textColor", "bold", "lang", "player", "panes", "split",
                       "svPane", "scale", "catFilter", "tileLayout", "tileSet", "tileHue", "tileActive",
                       "grid", "tileSize", "pinMerken",
                       "valueBar", "paneCols", "gesten", "gestenRaum", "gestenHinweis",
                       "nightClock", "nightClockBright", "hausAufbau")}
        # Widget je Tab: nur gueltige Tab-Kennung und gueltiger Pane-Wert, und
        # zwar der NORMIERTE ("header:A, B" -> "header:A,B"): Dateien von Hand
        # oder ueber die API koennen Leerzeichen tragen, die das Panel sonst
        # als Teil der UUID meldete.
        if isinstance(ui.get("panes"), dict):
            ui["panes"] = {str(k): _clean_tabpane(v) for k, v in ui["panes"].items()
                           if isinstance(k, str) and _is_tab(k) and _clean_tabpane(v)}
            if not ui["panes"]:
                ui.pop("panes", None)
        else:
            ui.pop("panes", None)
        # Rechte Spalte des Screensavers: derselbe Pruefer wie beim Speichern,
        # damit der Konfigurator nie einen Wert anzeigt, den der Server verwirft.
        _sp = _clean_svpane(ui.get("svPane"))
        if _sp:
            ui["svPane"] = _sp
        else:
            ui.pop("svPane", None)
        # Skalierung: "off" | "auto" | Faktor; fehlt sie, gilt die globale.
        _sc = _clean_scale(ui.get("scale"))
        if _sc is not None:
            ui["scale"] = _sc
        else:
            ui.pop("scale", None)
        # Zielkachel als Zahl, auch wenn die Datei noch eine Stufe nennt
        _tz = _clean_kachelziel(ui.get("tileSize"))
        if _tz is not None:
            ui["tileSize"] = _tz
        else:
            ui.pop("tileSize", None)
        # Werteleiste: nur gueltige Tab-Kennungen, jede einmal
        _vb = _clean_werteleiste(ui.get("valueBar"))
        if _vb:
            ui["valueBar"] = _vb
        else:
            ui.pop("valueBar", None)
        return {
            "title": raw.get("title") or "",
            "tabs": tabs or list(VALID_TABS),
            "rooms": [u for u in self.rooms_with if r and u in r],
            "cats": [u for u in self.cats_with if c and u in c],
            # Raum-Panel: gewaehlte Kategorie-Tabs in Klickreihenfolge, wie sie
            # _sanitize_panels speichert (nicht sortieren, nicht gegen die
            # Struktur filtern). Fehlt es hier, zeigt der Editor "automatisch",
            # und das naechste Speichern - auch eines anderen Profils - loescht es.
            "roomCats": [x for x in (raw["roomCats"] if isinstance(raw.get("roomCats"), list) else [])
                         if isinstance(x, str)][:4],
            "ui": ui,
            "states": {k: v for k, v in (raw.get("states") or {}).items()
                       if k in ("active", "good", "warn", "crit")},
            "tiles": raw.get("tiles") if isinstance(raw.get("tiles"), dict) else {},
            "hide": [u for u in (raw.get("hide") or [])
                     if isinstance(u, str) and u in self.controls],
            # Zielgeraet (Punkt 15): nur, wenn eines gesetzt ist
            **({"device": _z} if (_z := _clean_zielgeraet(raw.get("device"))) else {}),
            # Reihenfolge ist die Klickreihenfolge, deshalb NICHT sortieren -
            # anders als rooms/cats, die der Loxone-Reihenfolge folgen.
            "picks": [u for u in (raw.get("picks") or [])
                      if isinstance(u, str) and u in self.controls],
            "pickName": raw.get("pickName") or "",
            # Bis zu 4 freie Seiten [{name, picks, icon}]. MUSS mit exportiert
            # werden, sonst verliert der Konfigurator beim Neuladen die Seiten
            # 2-4: er baut aus den (leeren) Legacy-Feldern nur EINE Pick-Seite,
            # waehrend "tabs" noch vier Kennungen fuehrt - beim naechsten
            # Bearbeiten synct der Client "tabs" dann auf die eine Seite herunter.
            "pickTabs": _pick_tabs(raw),
        }

    def _loxone_icons(self) -> list:
        """Alle im Struktur-Baum referenzierten Loxone-Icon-Pfade (für den Picker)."""
        paths = set()
        for c in self.controls.values():
            di = (c.get("details") or {}).get("image")
            if isinstance(di, str):
                paths.add(di)
            elif isinstance(di, dict):
                for v in (di.get("on"), di.get("off")):
                    if isinstance(v, str):
                        paths.add(v)
        for table in (self.cats, self.rooms):
            for v in table.values():
                im = v.get("image")
                if isinstance(im, str):
                    paths.add(im)
        return sorted(p for p in paths if p.endswith(".svg") or p.endswith(".png"))


    def _persist_panels_file(self, panels: dict, devices: dict) -> None:
        """Schreibt config/panels.json (Profile + Geraete-Automatik) in einem Rutsch."""
        doc = self._panels_doc(panels, devices)
        # Eine Generation Sicherung: die aktuelle (funktionierende) panels.json
        # vor dem Ueberschreiben nach panels.json.bak kopieren (best effort; ein
        # fehlgeschlagenes Backup darf das Speichern nicht blockieren).
        try:
            if PANELS_FILE.is_file():
                _atomic_write(PANELS_FILE.with_name(PANELS_FILE.name + ".bak"),
                              PANELS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:   # ValueError = UnicodeDecodeError bei kaputtem UTF-8
            log.warning("panels.json.bak nicht geschrieben: %s", err)
        _atomic_write(PANELS_FILE,
                      json.dumps(doc, indent=2, ensure_ascii=False) + "\n")

    def _write_panels(self, panels: dict) -> None:
        self._persist_panels_file(panels, self.devices)
        self.panels = load_panels()
        self.entwuerfe.clear()   # gespeichert: die Entwuerfe sind erledigt (die Visu laedt neu)
        self.vorschau_geraet.clear()   # ... auch am Geraet: es zeigt jetzt das gespeicherte Profil
        # vorschau_ende bleibt: eine schon beendete Vorschau kehrt weiter zur Ansicht davor zurueck

    def _write_devices(self, devices: dict) -> None:
        # Erst schreiben, dann uebernehmen: scheitert das Schreiben, laeuft der
        # Server mit dem Stand der Datei weiter
        self._persist_panels_file(self.panels, devices)
        self.devices = devices
        self._presence_rebuild()


    def _write_theme(self, ui: dict, categories=None) -> None:
        """Globale Darstellung in theme.json schreiben (Darstellungs-Keys ersetzen,
        uebrige Theme-Inhalte wie states/tabs bleiben erhalten). categories wird,
        wenn uebergeben, komplett ersetzt (der _comment-Schluessel bleibt)."""
        base = Path(__file__).resolve().parent.parent / "config"
        f = base / "theme.json"
        src = f if f.is_file() else (base / "theme.example.json")   # Vorlage als Basis
        try:
            doc = json.loads(src.read_text(encoding="utf-8")) if src.is_file() else {}
        except ValueError:
            doc = {}
        cur = doc.get("ui") if isinstance(doc.get("ui"), dict) else {}
        for k in THEME_UI_KEYS:
            if k in ui:
                cur[k] = ui[k]
            else:
                cur.pop(k, None)
        doc["ui"] = cur
        if categories is not None:
            keep = {k: v for k, v in (doc.get("categories") or {}).items()
                    if str(k).startswith("_")}   # _comment behalten
            doc["categories"] = {**keep, **categories}
        _atomic_write(f, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        self.theme = load_theme()
        self._dirty = True   # verbundene Panels neu rendern lassen

    async def fetch_icon(self, path: str) -> tuple[bytes, str] | None:
        if path in self.icon_cache:
            hit = self.icon_cache.pop(path)       # neu einsortieren = zuletzt benutzt
            self.icon_cache[path] = hit
            return hit
        try:
            status, body, ctype = await self._ms_http(path, 6)
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError):
            return None
        if status != 200:
            return None
        ctype = ctype or "application/octet-stream"
        self.icon_cache[path] = (body, ctype)
        while len(self.icon_cache) > ICON_CACHE_MAX:
            self.icon_cache.pop(next(iter(self.icon_cache)))   # am laengsten unbenutzt
        return self.icon_cache[path]

    async def fetch_bell_image(self, ua: str, ts: str) -> tuple[bytes, str] | None:
        """Bild einer verpassten Klingel vom Miniserver: laut Strukturdoku
        camimage/{uuidAction}/{Zeitstempel}, Bearer-Token wie bei den Icons.
        Zu einem Zeitstempel aendert sich das Bild nicht, darum ein kleiner
        Zwischenspeicher (zuletzt benutzte zuletzt verdraengt)."""
        pfad = f"camimage/{ua}/{ts}"
        if pfad in self.bell_cache:
            hit = self.bell_cache.pop(pfad)
            self.bell_cache[pfad] = hit
            return hit
        try:
            status, body, ctype = await self._ms_http(pfad, BELL_TIMEOUT)
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError):
            return None
        if status != 200 or not body:
            return None
        self.bell_cache[pfad] = (body, ctype or "image/jpeg")
        while len(self.bell_cache) > BELL_CACHE_MAX:
            self.bell_cache.pop(next(iter(self.bell_cache)))
        return self.bell_cache[pfad]

    async def _stat_load(self, ua: str, ym: str) -> None:
        """Eine Statistik-Monatsdatei holen (/stats/<uuidAction>.<JJJJMM>.xml,
        Bearer-Token wie bei den Icons) und in stat_cache legen. 404 heisst:
        fuer diesen Monat gibt es keine Aufzeichnung (leere Liste). Andere
        Fehler legen None ab, dann wird erst nach STAT_RETRY erneut versucht.
        Danach neu rendern lassen, damit offene Detailseiten das Diagramm zeigen."""
        key = (ua, ym)
        rows: list | None = None
        try:
            status, body, _ = await self._ms_http(f"stats/{ua}.{ym}.xml", 20)
            if status == 404:
                rows = []
            elif status == 200:
                rows = _parse_stat_xml(body.decode("utf-8", "replace"))
            else:
                log.info("Statistik %s.%s: HTTP %s", ua, ym, status)
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError) as err:
            log.info("Statistik %s.%s nicht abrufbar: %s", ua, ym, err)
        finally:
            self.stat_pending.discard(key)
        self.stat_cache.pop(key, None)          # neu einsortieren = zuletzt benutzt
        self.stat_cache[key] = (time.monotonic(), datetime.now().strftime("%Y%m"), rows)
        while len(self.stat_cache) > STAT_CACHE_MAX:
            self.stat_cache.pop(next(iter(self.stat_cache)))
        self.stat_gen += 1
        self.stat_memo = {}
        self._dirty = True

    async def _stat2_load(self, key: tuple, ua: str, gid: str, out: str, span: int) -> None:
        """Verlauf eines statisticV2-Ausgangs holen: jdev/sps/getStatistic/<uuid>/raw/
        <vonUnixUtc>/<bisUnixUtc>/all/<gruppe>/<ausgang> (so baut ihn die Loxone-App,
        StatisticV2Ext.getStatisticRaw). Eine Stunde Vorlauf liefert den Stand vor
        dem ersten Balken. Leere Antwort oder JSON statt Binaerdaten heisst: keine
        Aufzeichnung (leere Liste); andere Fehler legen None ab."""
        rows: list | None = None
        now = int(time.time())
        path = f"jdev/sps/getStatistic/{ua}/raw/{now - span - 3600}/{now}/all/{quote(gid)}/{quote(out)}"
        try:
            async with self.stat2_sem:
                status, body, _ = await self._ms_http(path, 30)
            if status != 200:
                log.info("Statistik V2 %s: HTTP %s", path, status)
            elif not body:
                rows = []
            elif body[:1] == b"{":
                rows = []
                log.info("Statistik V2 %s: keine Daten (%s)", path, body[:160].decode("utf-8", "replace"))
            else:
                rows = _parse_stat2_bin(body)
                if rows is None:
                    log.info("Statistik V2 %s: unerwartete Antwort, %d Bytes", path, len(body))
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError) as err:
            log.info("Statistik V2 %s nicht abrufbar: %s", path, err)
        finally:
            self.stat_pending.discard(key)
        self.stat2_cache.pop(key, None)
        self.stat2_cache[key] = (time.monotonic(), rows)
        while len(self.stat2_cache) > STAT_CACHE_MAX:
            self.stat2_cache.pop(next(iter(self.stat2_cache)))
        self.stat_gen += 1
        self.stat_memo = {}
        self._dirty = True

    async def fetch_cover(self, url: str) -> tuple[bytes, str] | None:
        if not self.icon_session:
            return None
        try:
            async with self.icon_session.get(url, timeout=aiohttp.ClientTimeout(total=COVER_TIMEOUT)) as r:
                if r.status != 200:
                    return None
                return (await r.read(), r.headers.get("Content-Type", "image/jpeg"))
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None

    # ---- Kachel fuer ein Control ----
    def _spans_rooms(self, uuids) -> bool:
        """True, wenn die Bausteine ueber mehr als einen bekannten Raum verteilt
        sind. Dann lohnt es sich, den Raum je Kachel zu zeigen (Kategorie Licht
        ueber mehrere Raeume). Bausteine ohne Raum (z.B. Zentral) zaehlen nicht."""
        rooms = {self.controls[u].get("room") for u in uuids
                 if u in self.controls and self.controls[u].get("room") in self.rooms}
        return len(rooms) > 1

    def _alarm_next_text(self, c: dict) -> str:
        """Naechste Weckzeit eines Weckers (AlarmClock) als Text. Loxone liefert
        `nextEntryTime` in Sekunden seit dem 1.1.2009 (lokale Wanduhr); 0/leer =
        kein aktiver Eintrag. Ausgabe z.B. 'Heute 06:30', 'Morgen 06:30',
        'Mo 06:30' oder '24.12. 06:30'."""
        v = self._state(c, "nextEntryTime")
        try:
            ts = int(float(v))
        except (TypeError, ValueError):
            return ""
        if ts <= 0:
            return ""
        # Wert als Wanduhr behandeln (TZ-neutral): 2009-Basis + Sekunden.
        dt = datetime(2009, 1, 1) + timedelta(seconds=ts)
        today = datetime.now().date()
        d = (dt.date() - today).days
        hm = dt.strftime("%H:%M")
        if d == 0:
            return "Heute " + hm
        if d == 1:
            return "Morgen " + hm
        if 2 <= d <= 6:
            return ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][dt.weekday()] + " " + hm
        return dt.strftime("%d.%m.") + " " + hm

    def _alarm_aus(self, c: dict) -> bool:
        """Wecker per Logik ausgeschaltet (State isEnabled 0). Fehlt der State
        (aeltere Firmware), gilt er als eingeschaltet."""
        v = self._state(c, "isEnabled")
        return v is not None and not v

    def _alarm_raw(self, c: dict) -> tuple[dict[str, dict], bool] | None:
        """State entryList eines Weckers -> ({entryID: Eintrag}, IDs echt).
        Laut Strukturdoku ein JSON-Objekt {entryID: {name, isActive, alarmTime
        (Sekunden ab Mitternacht), modes, nightLight, daily}}, ggf.
        prozentkodiert. Kommt eine Liste, steht die Position an Stelle der ID;
        dann wird nur angezeigt, nicht geschrieben (IDs echt = False), sonst
        traefe ein Befehl womoeglich einen anderen Eintrag. None, wenn der
        State fehlt oder nicht lesbar ist (dann wird der Rohwert geloggt)."""
        raw = self._state(c, "entryList")
        if raw in (None, ""):
            return None
        data = raw
        if isinstance(raw, str):
            txt = unquote(raw).strip()
            try:
                data = json.loads(txt)
            except ValueError:
                log.warning("Wecker entryList nicht als JSON parsebar: %r", txt[:200])
                return None
        if isinstance(data, dict):
            return {str(k): e for k, e in data.items() if isinstance(e, dict)}, True
        if isinstance(data, list):
            return {str(i): e for i, e in enumerate(data) if isinstance(e, dict)}, False
        return None

    @staticmethod
    def _alarm_secs(e: dict) -> int:
        try:
            return int(float(e.get("alarmTime") or 0)) % 86400
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _alarm_modes(e: dict) -> list[int]:
        out = []
        for m in e.get("modes") or []:
            try:
                out.append(int(m))
            except (TypeError, ValueError):
                continue
        return out

    def _alarm_put(self, eid: str, e: dict, aktiv: bool) -> str:
        """Befehl entryList/put/{entryID}/{name}/{alarmTime}/{isActive}/{modes|daily}
        laut Strukturdoku: schreibt den Eintrag mit neuem Aktiv-Stand zurueck.
        Name URL-kodiert, Zeit in Sekunden ab Mitternacht, zuletzt bei
        Eintraegen mit nightLight daily (0/1), sonst die Betriebsarten mit Komma."""
        letzter = (("1" if e.get("daily") else "0") if e.get("nightLight") is True
                   else ",".join(str(m) for m in self._alarm_modes(e)))
        return (f"entryList/put/{quote(eid, safe='')}/{quote(str(e.get('name') or ''), safe='')}"
                f"/{self._alarm_secs(e)}/{1 if aktiv else 0}/{letzter}")

    def _alarm_entries(self, uuid: str) -> list[dict]:
        """Weckzeit-Eintraege eines Weckers fuer die Liste der Detailseite:
        [{id, name, hm, active, repeat, cmd, nav}], aktive zuerst, dann nach
        Uhrzeit. cmd schaltet den Eintrag ein bzw. aus, nav oeffnet ihn zum
        Bearbeiten."""
        c = self.controls.get(uuid, {})
        roh, echt = self._alarm_raw(c) or ({}, False)
        ua = c.get("uuidAction")
        out = []
        for eid, e in roh.items():
            secs = self._alarm_secs(e)
            it = {"id": eid, "name": _clean(str(e.get("name") or "")) or "Weckzeit",
                  "hm": "%02d:%02d" % (secs // 3600, secs % 3600 // 60),
                  "active": bool(e.get("isActive")), "repeat": self._alarm_repeat(e)}
            if echt:
                it["cmd"] = {"uuid": ua, "cmd": self._alarm_put(eid, e, not e.get("isActive"))}
                it["nav"] = {"view": "alarmentry", "id": uuid, "entry": eid}
            out.append(it)
        out.sort(key=lambda x: (not x["active"], x["hm"]))
        return out

    def _alarm_repeat(self, e: dict) -> str:
        """Wiederholungs-Text eines Weckzeit-Eintrags. Eintraege mit nightLight
        kennen nur daily (taeglich oder einmalig). Sonst die Betriebsarten: 3..9
        sind laut Strukturdoku Montag bis Sonntag (Mo/Di/...), alle sieben
        heissen "Täglich"; andere (Feiertag, Urlaub ...) mit ihrem Namen aus den
        operatingModes der Anlage."""
        if e.get("nightLight") is True:
            return "Täglich" if e.get("daily") else "Einmalig"
        if e.get("daily"):
            return "Täglich"
        modes = self._alarm_modes(e)
        tage = [m for m in WECKER_WOCHENTAGE if m in modes]
        andere = [m for m in modes if m not in WECKER_WOCHENTAGE]
        namen = (["Täglich"] if len(tage) == len(WECKER_WOCHENTAGE)
                 else [STAT_WEEKDAYS[m - WECKER_WOCHENTAGE[0]] for m in tage])
        namen += [self._op_mode_name(m) for m in andere]
        return " ".join(namen)

    def _op_mode_name(self, m: int) -> str:
        """Name einer Betriebsart aus der Struktur, sonst "Betriebsart <Nr>"."""
        return _clean(str(self.op_modes.get(str(m)) or "")) or f"Betriebsart {m}"

    def _alarm_mode_items(self, modes: list[int]) -> list[dict]:
        """Waehlbare Tage einer Weckzeit: Mo..So (Betriebsarten 3..9), dazu die
        Vorrang-Betriebsarten 0..2, soweit die Anlage sie kennt (damit klingelt
        der Wecker auch an Feiertagen oder im Urlaub), und jede weitere, die der
        Eintrag schon hat. -> [{v, label, on}]"""
        gesetzt = set(modes)
        items = [{"v": m, "label": STAT_WEEKDAYS[i], "on": m in gesetzt}
                 for i, m in enumerate(WECKER_WOCHENTAGE)]
        weitere = [m for m in WECKER_VORRANG if str(m) in self.op_modes]
        weitere += sorted(m for m in gesetzt if m not in WECKER_WOCHENTAGE and m not in weitere)
        items += [{"v": m, "label": self._op_mode_name(m), "on": m in gesetzt} for m in weitere]
        return items

    def _daytimer_mode(self, c: dict) -> str:
        """Aktiver Modus/Tag eines Daytimers als Name. `mode` (Zahl) wird ueber
        `modeList` aufgeloest, Format: '0:mode=0;name=\"Feiertag\",1:mode=3;
        name=\"Montag\",...' (Anfuehrungszeichen escaped)."""
        raw = str(self._state(c, "modeList") or "").replace('\\"', '"')
        modes = {int(m): n for m, n in re.findall(r'mode=(\d+);name="([^"]*)"', raw)}
        try:
            return modes.get(int(float(self._state(c, "mode"))), "")
        except (TypeError, ValueError):
            return ""

    def _daytimer_value(self, c: dict) -> str:
        """Aktueller Wert eines Daytimers als Text: 0/leer -> „Aus"; analog ->
        formatiert (details.format); digital -> „Ein"."""
        val = self._state(c, "value")
        if not val:
            return "Aus"
        det = c.get("details") or {}
        if det.get("analog"):
            return self._fmt_num(val, det.get("format") or "%.1f")
        return "Ein"

    @staticmethod
    def _color_parse(raw) -> tuple:
        """Loxone color-State parsen. RGB: 'hsv(h,s,v)' (h 0-360, s/v 0-100) ->
        ('rgb', h, s, v). Tunable White: 'temp(brightness,kelvin)' ->
        ('temp', brightness, kelvin, None). Sonst ('none', 0, 0, 0)."""
        s = str(raw or "")
        m = re.match(r"hsv\((\d+),(\d+),(\d+)\)", s, re.I)
        if m:
            return ("rgb", int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.match(r"temp\((\d+),(\d+)\)", s, re.I)
        if m:
            return ("temp", int(m.group(1)), int(m.group(2)), None)
        return ("none", 0, 0, 0)

    @staticmethod
    def _hsv_hex(h, s, v) -> str:
        """HSV (h 0-360, s/v 0-100) -> #rrggbb fuer die Farb-Vorschau."""
        import colorsys
        r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, s / 100.0, v / 100.0)
        return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))

    def types_overview(self) -> dict:
        """Diagnose fuer /api/types: alle Bausteintypen der geladenen Anlage mit
        Anzahl, Beispielnamen, Unterstuetzungsstatus (full / partial / none),
        den State-Namen und details-Schluesseln je Typ, dazu die Liste der
        Controls, die als tote Kachel enden. Der Status wird nicht aus einer
        Liste geraten, sondern aus dem Rendering: `_control_item()` liefert
        fuer unterstuetzte Typen nav, cmd, controls oder sublabel."""
        types: dict[str, dict] = {}
        for uuid, c in self.controls.items():
            t = str(c.get("type") or "?")
            e = types.setdefault(t, {"type": t, "count": 0, "examples": [], "states": set(),
                                     "details": set(), "supported": False, "controls": []})
            e["count"] += 1
            name = _clean(c.get("name"))
            if name and len(e["examples"]) < 3:
                e["examples"].append(name)
            e["states"].update(k for k in (c.get("states") or {}) if isinstance(k, str))
            e["details"].update(k for k in (c.get("details") or {}) if isinstance(k, str))
            room = _clean((self.rooms.get(c.get("room")) or {}).get("name"))
            e["controls"].append({"uuid": uuid, "name": name, "room": room})
            if not e["supported"]:
                try:
                    it = self._control_item(uuid)
                except Exception as err:  # Diagnose darf nie an einem Baustein scheitern
                    log.warning("types_overview: %s (%s): %s", name, t, err)
                    it = {}
                if any(k in it for k in ("nav", "cmd", "controls", "sublabel")):
                    e["supported"] = True
        out, dead = [], []
        for t in sorted(types, key=str.lower):
            e = types[t]
            status = "none" if not e["supported"] else ("partial" if t in PARTIAL_TYPES else "full")
            if status == "none":
                dead.extend({**ctl, "type": t} for ctl in e["controls"])
            out.append({"type": t, "status": status, "count": e["count"], "examples": e["examples"],
                        "states": sorted(e["states"]), "details": sorted(e["details"])})
        counts = {s: sum(1 for e in out if e["status"] == s) for s in ("full", "partial", "none")}
        # Diagnose Energiefluss: rohe Knotenstruktur + aktuelle Werte je EFM/EM2.
        # Damit laesst sich die Rolle/Richtung je Knoten belegen (statt raten).
        energy = []
        for uuid, c in self.controls.items():
            if c.get("type") in ("EFM", "EnergyManager2"):
                det = c.get("details") or {}
                energy.append({
                    "uuid": uuid, "name": _clean(c.get("name")), "type": c.get("type"),
                    "actualFormat": det.get("actualFormat"), "storageFormat": det.get("storageFormat"),
                    "Ppwr": self._state(c, "Ppwr"), "Gpwr": self._state(c, "Gpwr"),
                    "Spwr": self._state(c, "Spwr"), "Ssoc": self._state(c, "Ssoc"),
                    "nodes": det.get("nodes"),
                    "actuals": {f"actual{i}": self._state(c, f"actual{i}") for i in range(6)},
                })
        # Diagnose globale States (Sonnenzeiten, aktive Betriebsmodi ...): Name,
        # UUID und aktueller Wert. Sonst nirgends sichtbar; Grundlage dafuer, die
        # Nacht-Erkennung an den Miniserver zu haengen statt an einen Wetterdienst.
        gstates = []
        for _n, _ref in (self.global_states or {}).items():
            if isinstance(_ref, str):
                gstates.append({"name": _n, "uuid": _ref, "value": self.states.get(_ref)})
            else:
                gstates.append({"name": _n, "raw": _ref})
        return {"connected": self.client is not None, "controls": len(self.controls),
                "typeCount": len(out), "typesByStatus": counts, "types": out,
                "energyDetails": energy,
                "globalStates": sorted(gstates, key=lambda g: g["name"]),
                "operatingModes": self.op_modes,
                "weatherServer": self._weather_diag(),
                "unsupportedControls": sorted(dead, key=lambda d: (d["room"], d["name"]))}

    def _weather_diag(self) -> dict:
        """Diagnose zum Loxone-Wetterserver: was die Anlage meldet und was davon
        ankommt. Sonst nirgends sichtbar — und die einzige verlaessliche Auskunft
        darueber, unter welchen Namen und in welchen Einheiten diese Anlage ihre
        Wetterwerte fuehrt."""
        cfg = self.weather_cfg or {}
        states = cfg.get("states") if isinstance(cfg.get("states"), dict) else {}
        eintraege = {rolle: len(self._lox_wx.get(u) or [])
                     for rolle, u in states.items() if isinstance(u, str)}
        akt = (self._lox_wx.get(states.get("actual")) or [None])[0]
        if isinstance(akt, dict):
            # NaN/Inf wuerde ungueltiges JSON ergeben — die Tabelle kann beides fuehren.
            akt = {k: (v if isinstance(v, int) or (isinstance(v, float) and math.isfinite(v)) else None)
                   for k, v in akt.items()}
        return {
            "vorhanden": bool(cfg),
            "quelle": self._wx_source,
            "states": states,
            "eintraege": eintraege,
            "aktuellerEintrag": akt,      # Rohwerte: zeigt Einheiten und Groessenordnung
            "wetterlagen": loxone_weather.weather_texts(cfg),
            "format": cfg.get("format"),
            "feldtypen": cfg.get("weatherFieldTypes"),
        }

    def _leiste_trennen(self, uuids: list, tab, prof: dict | None) -> tuple[list, list]:
        """Seite mit Werteleiste (ui.valueBar nennt den Tab): die Anzeige-
        Bausteine (WERTE_LEISTE_TYPEN) wandern aus dem Raster in die Leiste ->
        (Raster, Leiste), beide in der Reihenfolge von uuids. Ohne Leiste, und
        wenn im Raster nichts bliebe (eine Seite nur aus Werten: dann SIND die
        Kacheln die Seite), bleibt alles im Raster."""
        if not prof or tab not in (prof.get("valueBar") or []):
            return uuids, []
        leiste = [u for u in uuids if (self.controls.get(u) or {}).get("type") in WERTE_LEISTE_TYPEN]
        if not leiste or len(leiste) == len(uuids):
            return uuids, []
        weg = set(leiste)
        return [u for u in uuids if u not in weg], leiste

    def _leiste_items(self, uuids: list, prof: dict | None, **kw) -> dict:
        """Die Werteleiste einer Ansicht als {"leiste": [...]}: dieselben
        Kacheln wie im Raster (_control_item: Name, Wert, Symbol, Farbe,
        Wertseite), das Panel zeigt sie als Kette ueber dem Raster
        (renderLeiste). Leer: kein Schluessel, die Ansicht bleibt wie bisher."""
        if not uuids:
            return {}
        return {"leiste": [self._control_item(u, prof, **kw) for u in uuids]}

    def _zentral_an(self, c: dict) -> int:
        """Wie viele Mitglieder eines Zentral-Bausteins (details.controls) an
        sind: Lichtsteuerungen mit aktiver Stimmung, Audio-Zonen, die spielen,
        Tore und Fenster, die offen stehen. Andere Zentralen: 0. Dieselbe Zahl
        zeigen seine Kachel und die Schnellaktion der Hausseite."""
        t = c.get("type")
        muuids = [m.get("uuid") for m in ((c.get("details") or {}).get("controls") or [])
                  if m.get("uuid") in self.controls]
        if t == "CentralLightController":
            return sum(1 for mu in muuids if LIGHT.render(self._with_uuid(mu), self.states)["on"])
        if t == "CentralAudioZone":
            return sum(1 for mu in muuids if self._state(self.controls[mu], "playState") == 2)
        if t in ("CentralGate", "CentralWindow"):
            return sum(1 for mu in muuids if (self._state(self.controls[mu], "position") or 0) > 0)
        return 0

    def _control_item(self, uuid: str, prof: dict | None = None,
                      show_room: bool = False, ohne_raum: str = "") -> dict:
        """Kachel eines Bausteins. show_room: Raum an der Kachel (Seite ueber
        mehrere Raeume). ohne_raum: Name des Raums, den die Seite schon nennt
        (Raum-Seite) - er faellt aus dem Kachelnamen (_ohne_raum), die
        meisten abgeschnittenen Namen der Messung trugen ihn."""
        c = self.controls.get(uuid)
        if not c:
            return {"id": uuid, "label": "?", "icon": "info", "on": False}
        t = c.get("type")
        name = _clean(c.get("name"))
        if ohne_raum:
            name = _ohne_raum(name, ohne_raum)
        it: dict = {"id": uuid, "label": name, "on": False, "icon": "info"}
        # Raum-Kennzeichnung: nur wenn die Ansicht mehrere Raeume umfasst (z.B.
        # Kategorie Licht ueber alle Raeume). Zentralbausteine haben keinen Raum.
        if show_room:
            rn = _clean((self.rooms.get(c.get("room")) or {}).get("name"))
            if rn:
                it["room"] = rn
        if c.get("isSecured"):
            it["secured"] = True
        iu = self._control_icon_url(c)
        if iu:
            it["iconUrl"] = iu
        cc = self._cat_color(c.get("cat"))
        if cc:
            it["color"] = cc
        fn = bausteine.kachel_fuer(t)
        if fn:
            fn(self, uuid, c, it)
        # Status-Bausteine antippbar machen -> grosse Wertseite
        if t in STATUS_BIG and "nav" not in it and "cmd" not in it:
            it["nav"] = {"view": "control", "id": uuid}
        # Kategorie-Ampel: Bausteine mit an/aus-Zustand einer Kategorie mit
        # Zustandsfarben leuchten aktiv (on-Farbe) bzw. ok (off-Farbe). Analoge
        # Anzeigen, Zentralbausteine und Bausteine mit eigenem tone (Rauch/…)
        # bleiben unberuehrt.
        cs = self._cat_states(c.get("cat"))
        if cs and t not in _ANALOG and not (t or "").startswith("Central") and not it.get("tone"):
            rgb = _hex_rgb(cs.get("on") if it.get("on") else cs.get("off"))
            if rgb:
                st = it.setdefault("style", {})
                # Deckkraft folgt den Overlay-Reglern (--ov-fill/--ov-bord, Panel-
                # bzw. Pro-Kachel-Einstellung, inkl. Modus nur-Rahmen/nur-Fuellung)
                # statt fest .16/.55 -> "Hintergrund/Rahmen transparenter" wirkt
                # damit auch auf die Kategorie-Ampel-Kacheln. Fallback = altes
                # Aussehen, wenn kein Overlay konfiguriert ist.
                st.setdefault("bg", "rgba(%s,var(--ov-fill,.16))" % rgb)
                st.setdefault("border", "rgba(%s,var(--ov-bord,.55))" % rgb)
        return self._apply_tile_style(it, uuid, prof)

    def _apply_tile_style(self, it: dict, uuid: str, prof: dict | None) -> dict:
        """Pro-Kachel-Overrides (Farben/Icon/Schrift/Breite) aus dem Panel-Profil."""
        ov = (prof.get("tiles") if prof else {}).get(uuid) if prof else None
        # Breite: zwei Spalten fuer Audio, Raumregelung und Energiefluss
        # (KACHEL_BREIT_TYPEN), je Kachel uebersteuerbar (w = 1 | 2); nur die
        # breite Kachel traegt das Feld, schmal ist der Standard der Visu.
        w = _kachel_breite(ov.get("w")) if isinstance(ov, dict) else None
        if w is None:
            w = 2 if (self.controls.get(uuid) or {}).get("type") in KACHEL_BREIT_TYPEN else 1
        if w == 2:
            it["w"] = 2
        if not isinstance(ov, dict):
            return it
        if ov.get("iconColor"):
            it["color"] = ov["iconColor"]           # Icon-Farbe (--ico)
            it["colorFixed"] = ov["iconColor"]      # gewinnt auch im Aktiv-Zustand
        style = dict(it.get("style") or {})         # Kategorie-Ampel als Basis, manuell ueberschreibt
        for src, dst in (("bg", "bg"), ("border", "border"),
                         ("textColor", "txt"), ("font", "font")):
            if ov.get(src):
                style[dst] = ov[src]
        if ov.get("bold"):
            style["weight"] = 700
        if ov.get("italic"):
            style["italic"] = True
        if isinstance(ov.get("overlay"), dict):
            fill, bord, bw = _overlay_alphas(ov["overlay"])
            style["ovFill"] = f"{fill:.3g}"     # ueberschreibt --ov-* nur fuer diese Kachel
            style["ovBord"] = f"{bord:.3g}"
            style["ovBw"] = bw
            ialpha, ibw = _inactive_border(ov["overlay"])
            style["tileBord"] = f"rgba(255,255,255,{ialpha:.3g})"   # inaktiver Rahmen nur fuer diese Kachel
            style["tileBw"] = ibw
            rop, rtrk, rw = _posring(ov["overlay"])
            style["ringOp"] = f"{rop:.3g}"      # Positionsring nur fuer diese Kachel
            style["ringTrk"] = f"{rtrk:.3g}"
            style["ringW"] = rw
        if style:
            it["style"] = style
        ic = ov.get("icon")
        if isinstance(ic, dict):
            s = ic.get("src")
            if s == "builtin" and ic.get("id"):
                it["icon"] = ic["id"]
                it.pop("iconUrl", None)
                it.pop("iconImg", None)
            elif s == "loxone" and ic.get("p"):
                u = self._icon_url(ic["p"])
                if u:
                    it["iconUrl"] = u
                    it.pop("iconImg", None)
            elif s == "loxlib" and ic.get("name"):
                it["iconUrl"] = "/loxlib?n=" + quote(str(ic["name"]))
                it.pop("iconImg", None)
            elif s == "google" and ic.get("name"):
                it["iconUrl"] = "/gicon?name=" + quote(str(ic["name"]))
                it.pop("iconImg", None)
            elif s == "custom" and ic.get("file"):
                it["iconImg"] = "/uicon?f=" + quote(str(ic["file"]))
                it.pop("iconUrl", None)
        # Mini-Verlauf in der Kachel (tiles.<uuid>.chart = Zeitraum), nur fuer
        # Bausteine mit Aufzeichnung. Ein Tipp oeffnet wie bisher die Detailseite.
        rng = ov.get("chart")
        c = self.controls.get(uuid) or {}
        if rng in STAT_RANGES and (c.get("statistic") or c.get("statisticV2")):
            style = ov.get("chartStyle") if ov.get("chartStyle") in STAT_TILE_STYLES else "trend"
            sp = self._stat_spark(c, rng, style)
            if sp:
                it["spark"] = sp
        return it

    # ---- Views ----
    def _view_tab(self, tab: str, prof: dict | None = None) -> dict:
        if tab == HAUS_TAB:
            return self._view_haus({"view": "tab", "tab": tab}, prof)
        if tab in FRONT_TABS:
            titel, teil = FRONT_TABS[tab]
            return {"t": "view", "title": titel, "tab": tab,
                    "route": {"view": "tab", "tab": tab}, "items": [], "front": teil}
        ar = prof.get("rooms") if prof else None
        ac = prof.get("cats") if prof else None
        if self._haus_seite(tab, prof):
            return self._view_haus({"view": "tab", "tab": tab}, prof)
        if _is_pick(tab):
            # Freie Auswahl: genau die handverlesenen Bausteine, in der
            # gespeicherten Reihenfolge (= Klickreihenfolge in der Konfig).
            #
            # BEWUSST OHNE _room_ok/_cat_ok: wer einen Baustein ausdruecklich
            # auswaehlt, will ihn sehen - auch wenn sein Raum oder seine
            # Kategorie im Panelfilter fehlt. Sonst waere das Auswaehlen
            # wirkungslos und der Sinn der Seite dahin.
            #
            # _shown bleibt: "hide" ist panelweit und das Sicherheitsnetz.
            # Die Konfigurationsseite zeigt so einen Baustein ausgegraut.
            _pts = _pick_tabs(prof)
            _i = _pick_index(tab)
            _entry = _pts[_i] if 0 <= _i < len(_pts) else {"name": "Auswahl", "picks": []}
            # Widget-Seite: die ganze Seite ist EIN Widget (Vollbild-Tab), keine
            # Kacheln. Das Panel rendert es wie eine Pane, nur ueber die volle
            # Flaeche; der Datenkanal (energy/camera/status/player/chart) laeuft
            # ueber dieselbe set*-Mechanik wie Pane 2.
            _wdg = _clean_widget_tab(_entry.get("widget"))
            if _wdg:
                return {"t": "view", "title": _clean(_entry.get("name")) or "",
                        "tab": tab, "widget": _wdg,
                        "route": {"view": "tab", "tab": tab}}
            gewaehlt = _entry["picks"]
            uuids, gesehen = [], set()
            for u in gewaehlt:
                # Doppelte ueberspringen: zwei Kacheln mit derselben id wuerden
                # den In-place-Abgleich im Panel (updateGrid) durcheinander bringen.
                if u in gesehen or u not in self.controls or not self._shown(u, prof):
                    continue
                gesehen.add(u)
                uuids.append(u)
            sr = self._spans_rooms(uuids)
            # Werteleiste statt Anzeige-Kacheln - VOR dem Gruppieren, damit
            # Anker und Marken zu den Kacheln gehoeren, die im Raster bleiben
            uuids, leiste = self._leiste_trennen(uuids, tab, prof)
            # Groessen aus dem Seiten-Editor (Punkt 10): 1x1, 2x1 oder 2x2 je
            # Baustein, uebersteuern Typ und tiles[uuid].w auf dieser Seite
            groessen = {e["id"]: e for e in (_entry.get("layout") or [])}

            def kachel(u, **kw):
                it = self._control_item(u, prof, show_room=sr, **kw)
                g = groessen.get(u)
                if g:
                    if g["w"] == 2:
                        it["w"] = 2
                    else:
                        it.pop("w", None)
                    if g["h"] == 2:
                        it["h"] = 2
                return it
            title = _entry["name"] or "Auswahl"
            if not _entry.get("byRoom", True):
                # Ohne Gruppierung: genau die Reihenfolge der Seite, ohne
                # Sprungmarken - so, wie der Seiten-Editor sie zeigt
                return {"t": "view", "title": title, "tab": tab,
                        "route": {"view": "tab", "tab": tab}, "items": [kachel(u) for u in uuids],
                        "catTabs": [], **self._leiste_items(leiste, prof, show_room=sr)}
            # Nach RAUM gruppieren, damit die untere Leiste die vorkommenden
            # Raeume als Sprungmarken zeigen kann und ein Tipp zur Gruppe
            # scrollt - dieselbe Bauform wie das Raum-Panel, nur nach Raum
            # statt nach Kategorie. Ohne das ist eine Seite aus 40 Bausteinen
            # quer durchs Haus auf einem 4-Zoll-Panel nicht mehr zu bedienen.
            #
            # Reihenfolge der Raeume = erstes Vorkommen in der Auswahl. Damit
            # bleibt die Klickreihenfolge aus der Konfiguration die fuehrende
            # Ordnung; innerhalb eines Raums stehen die Bausteine ebenfalls so,
            # wie sie gewaehlt wurden. Dicts halten die Einfuegereihenfolge.
            nach_raum: dict = {}
            for u in uuids:
                nach_raum.setdefault(self.controls[u].get("room"), []).append(u)
            raeume = [ru for ru in nach_raum if ru in self.rooms]
            # Sprungmarken ERSETZEN im Panel die ganze untere Leiste. Das ist
            # nur dann richtig, wenn diese Seite die einzige des Panels ist.
            # Steht der Auswahl-Tab dagegen neben anderen Seiten in der
            # klassischen Leiste, waeren die uebrigen Tabs nicht mehr
            # erreichbar - und der Zurueck-Knopf hilft nicht, weil die Seite
            # die unterste im Stapel ist.
            # Erst ab zwei Raeumen sind Sprungmarken ausserdem etwas wert: bei
            # einem einzigen zeigte die Leiste nur den Raum, in dem man steht.
            allein = list((prof.get("tabs") or []) if prof else []) == [tab]
            marken = allein and len(raeume) > 1
            items = []
            for ru in raeume:
                for j, u in enumerate(nach_raum[ru]):
                    it = kachel(u)
                    if marken and j == 0:
                        # Scroll-Anker fuer die Sprungmarke. Der Schluessel
                        # heisst im Panel catKey, weil dieselbe Mechanik schon
                        # fuer die Kategorien des Raum-Panels da ist - fuer das
                        # Panel ist er ein undurchsichtiger Schluessel. Ohne
                        # Leiste waere er ein totes Attribut, also nur dann.
                        it["catKey"] = ru
                    if marken:
                        # Gruppe an JEDER Kachel: das Panel laesst beim Sprung
                        # die ganze Gruppe aufleuchten und filtert nach ihr.
                        it["grp"] = ru
                    items.append(it)
            # Bausteine ohne bekannten Raum ans Ende, wie im Raum-Panel.
            for ru, us in nach_raum.items():
                if ru not in self.rooms:
                    items += [kachel(u) for u in us]
            raum_tabs = ([{"key": ru,
                           "label": _clean(self.rooms[ru].get("name")) or "Raum",
                           "iconUrl": self._icon_url(self.rooms[ru].get("image")) or ""}
                          for ru in raeume[:4]] if marken else [])
            return {"t": "view", "title": title, "tab": tab,
                    "route": {"view": "tab", "tab": tab}, "items": items,
                    "catTabs": raum_tabs, **self._leiste_items(leiste, prof, show_room=sr)}
        if isinstance(tab, str) and tab.startswith("cat:"):
            # Kategorie-Direkt-Tab: dieselben Controls wie im Kategorie-Drilldown
            cu = tab[4:]
            uuids = [u for u, c in self.controls.items()
                     if c.get("cat") == cu and self._room_ok(u, prof) and self._shown(u, prof)]
            sr = self._spans_rooms(uuids)
            uuids, leiste = self._leiste_trennen(uuids, tab, prof)
            items = [self._control_item(u, prof, show_room=sr) for u in uuids]
            title = _clean(self.cats.get(cu, {}).get("name")) or "Kategorie"
            return {"t": "view", "title": title, "tab": tab,
                    "route": {"view": "tab", "tab": tab}, "items": items,
                    **self._leiste_items(leiste, prof, show_room=sr)}
        if isinstance(tab, str) and tab.startswith("room:"):
            # Raum-Direkt-Tab: dieselben Controls wie im Raum-Drilldown. Als
            # ERSTER Tab ist er die Startseite - dann weckt das Panel direkt in
            # diesem Raum auf, ohne vorher Raum oder Kategorie zu waehlen.
            # Der Raumname steht schon im Tab, deshalb nicht noch an jeder Kachel.
            ru = tab[5:]
            uuids = [u for u, c in self.controls.items()
                     if c.get("room") == ru and self._cat_ok(u, prof) and self._shown(u, prof)]
            # Werteleiste VOR dem Gruppieren: Anker (catKey) und Marken gehoeren
            # zu den Kacheln, die im Raster bleiben
            uuids, leiste = self._leiste_trennen(uuids, tab, prof)
            # Raum-Panel: nach Kategorie gruppieren, damit die untere Leiste die
            # im Raum vorkommenden Kategorien als Tabs zeigt und ein Tipp zur
            # jeweiligen Kachel-Gruppe scrollt (keine Ueberschriften, Kacheln
            # bleiben normal 2x2). Die erste Kachel jeder Gruppe traegt catKey als
            # Scroll-Anker. Reihenfolge = cats_with; Bausteine ohne bekannte
            # Kategorie kommen ans Ende. Tabs: die ersten 4 Kategorien.
            by_cat: dict = {}
            for u in uuids:
                cu = self.controls[u].get("cat")
                by_cat.setdefault(cu if cu in self.cats else None, []).append(u)
            present = [c for c in self.cats_with if c in by_cat]
            # Gewaehlte Tab-Kategorien (Config) vor die uebrigen; leer = automatisch.
            chosen = [c for c in (prof.get("roomCats") or []) if c in by_cat] if prof else []
            if chosen:
                order = chosen + [c for c in present if c not in chosen]
                tab_cats = chosen[:4]
            else:
                order = present
                tab_cats = present[:4]
            # Der Raumname steht im Titel der Seite: aus den Kachelnamen faellt er heraus
            raumname = _clean(self.rooms.get(ru, {}).get("name"))
            items = []
            for cu in order:
                for j, u in enumerate(by_cat[cu]):
                    it = self._control_item(u, prof, ohne_raum=raumname)
                    if j == 0:
                        it["catKey"] = cu       # Scroll-Anker fuer den Kategorie-Tab
                    it["grp"] = cu              # Gruppe: Aufleuchten und Filter im Panel
                    items.append(it)
            cat_tabs = [{"key": cu,
                         "label": _clean(self.cats.get(cu, {}).get("name")) or "Kategorie",
                         "iconUrl": self._icon_url(self.cats.get(cu, {}).get("image")) or ""}
                        for cu in tab_cats]
            for u in by_cat.get(None, []):
                items.append(self._control_item(u, prof, ohne_raum=raumname))
            title = raumname or "Raum"
            return {"t": "view", "title": title, "tab": tab,
                    "route": {"view": "tab", "tab": tab}, "items": items,
                    "catTabs": cat_tabs, **self._leiste_items(leiste, prof, ohne_raum=raumname)}
        extra: dict = {}   # Werteleiste der Seite (nur Favoriten; Zentral, Raeume, Kategorien sind Listen)
        if tab == "favoriten":
            uuids = [u for u, c in self.controls.items()
                     if c.get("isFavorite") and self._room_ok(u, prof) and self._shown(u, prof)]
            sr = self._spans_rooms(uuids)
            uuids, leiste = self._leiste_trennen(uuids, tab, prof)
            items = [self._control_item(u, prof, show_room=sr) for u in uuids]
            extra = self._leiste_items(leiste, prof, show_room=sr)
            title = "Favoriten"
        elif tab == "zentral":
            items = [self._control_item(u, prof) for u, c in self.controls.items()
                     if (c.get("type") or "").startswith("Central") and self._shown(u, prof)]
            title = "Zentral"
        elif tab == "raeume":
            rooms = [ru for ru in self.rooms_with if ar is None or ru in ar]
            items = [{"id": ru, "label": _clean(self.rooms[ru].get("name")), "icon": "folder",
                      "iconUrl": self._icon_url(self.rooms[ru].get("image")),
                      "on": False, "nav": {"view": "group", "kind": "room", "id": ru}}
                     for ru in rooms]
            title = "Räume"
        else:
            if ac is not None:
                cats = [cu for cu in self.cats_with if cu in ac]
            elif ar is not None:
                present = {c.get("cat") for c in self.controls.values() if c.get("room") in ar}
                cats = [cu for cu in self.cats_with if cu in present]
            else:
                cats = list(self.cats_with)
            items = [{"id": cu, "label": _clean(self.cats[cu].get("name")), "icon": "folder",
                      "iconUrl": self._icon_url(self.cats[cu].get("image")),
                      "color": self._cat_color(cu),
                      "on": False, "nav": {"view": "group", "kind": "cat", "id": cu}}
                     for cu in cats]
            title = "Kategorien"
        return {"t": "view", "title": title, "tab": tab, "route": {"view": "tab", "tab": tab},
                "items": items, **extra}

    def _view_group(self, route: dict, prof: dict | None = None) -> dict:
        kind, gid = route.get("kind"), route.get("id")
        layout = None
        ohne_raum = ""   # Raum-Seite: der Raumname steht im Titel, nicht noch in jedem Kachelnamen
        if kind == "cat":
            uuids = [u for u, c in self.controls.items()
                     if c.get("cat") == gid and self._room_ok(u, prof) and self._shown(u, prof)]
            title = _clean(self.cats.get(gid, {}).get("name")); tab = "kategorien"
            sr = self._spans_rooms(uuids)
            uuids, leiste = self._leiste_trennen(uuids, tab, prof)
            return {"t": "view", "title": title, "tab": tab, "route": route,
                    "layout": layout,
                    "items": [self._control_item(u, prof, show_room=sr) for u in uuids],
                    **self._leiste_items(leiste, prof, show_room=sr)}
        elif kind == "room":
            uuids = [u for u, c in self.controls.items()
                     if c.get("room") == gid and self._cat_ok(u, prof) and self._shown(u, prof)]
            title = _clean(self.rooms.get(gid, {}).get("name")); tab = "raeume"
            ohne_raum = title
        elif kind == "central":
            c = self.controls.get(gid, {})
            members = (c.get("details") or {}).get("controls") or []
            uuids = [m.get("uuid") for m in members
                     if m.get("uuid") in self.controls and self._shown(m.get("uuid"), prof)]
            title = _clean(c.get("name")); tab = "zentral"
            if c.get("type") == "CentralAudioZone":
                layout = "list"
        else:
            uuids, title, tab = [], "", None
        uuids, leiste = self._leiste_trennen(uuids, tab, prof)
        return {"t": "view", "title": title, "tab": tab, "route": route,
                "layout": layout, "items": [self._control_item(u, prof, ohne_raum=ohne_raum) for u in uuids],
                **self._leiste_items(leiste, prof, ohne_raum=ohne_raum)}

    # ---- Hausuebersicht (Tab "haus") ----
    @staticmethod
    def _haus_seite(tab, prof: dict | None) -> bool:
        """Zeigt dieser Tab die Hausuebersicht? Der Tab "haus" der klassischen
        Leiste oder eine freie Seite, deren Inhalt sie ist (pickTabs[].widget)."""
        if tab == HAUS_TAB:
            return True
        if not _is_pick(tab):
            return False
        seiten, i = _pick_tabs(prof), _pick_index(tab)
        return 0 <= i < len(seiten) and seiten[i].get("widget") == HAUS_TAB

    def _haus_raeume(self, prof: dict | None) -> list:
        """Raeume der Hausseite mit ihren sichtbaren Bausteinen, in der Folge der
        Raumliste (rooms_with) und mit dem Raumfilter der Ansicht wie der Tab
        "Raeume": [(raum_uuid, [baustein_uuid, ...])]. Raeume ohne sichtbaren
        Baustein fallen weg."""
        ar = prof.get("rooms") if prof else None
        out = []
        for ru in self.rooms_with:
            if ar is not None and ru not in ar:
                continue
            uuids = [u for u, c in self.controls.items()
                     if c.get("room") == ru and self._cat_ok(u, prof) and self._shown(u, prof)]
            if uuids:
                out.append((ru, uuids))
        return out

    @staticmethod
    def _haus_hauptwert(items: list) -> tuple[str, str]:
        """Grosser Wert einer Raumkarte und die Zeile darunter, aus den Kacheln
        des Raums: die Ist-Temperatur (big) der ersten Raumregelung oder Sauna,
        sonst der Zustand des ersten Bausteins, der an ist, sonst der erste
        Zustand ueberhaupt. Beschreibende Zeilen (subInfo) zaehlen nicht."""
        for it in items:
            if it.get("big") is not None:
                return str(it["big"]), str(it.get("bigSub") or it.get("label") or "")
        for wahl in (lambda it: it.get("on"), lambda it: True):
            for it in items:
                if wahl(it) and it.get("sublabel") and not it.get("subInfo"):
                    return str(it["sublabel"]), str(it.get("label") or "")
        return "", ""

    @staticmethod
    def _haus_symbol(it: dict) -> dict:
        """Symbol einer Kachel fuer die Hausseite (eingebaut, Loxone-Symbol oder
        eigenes Bild, wie auf der Kachel)."""
        s = {"icon": it.get("icon") or "info"}
        for k in ("iconUrl", "iconImg"):
            if it.get(k):
                s[k] = it[k]
        return s

    def _haus_aus(self, uuid: str) -> dict | None:
        """Aus-Befehl eines Bausteins fuer die Hausseite ({uuid, cmd, taste}) oder
        None, wenn sein Typ keinen hat (HAUS_AUS)."""
        c = self.controls.get(uuid) or {}
        e = HAUS_AUS.get(c.get("type"))
        if not e or not c.get("uuidAction"):
            return None
        return {"uuid": c["uuidAction"], "cmd": e[0], "taste": e[1]}

    def _haus_ein(self, uuid: str) -> dict | None:
        """Ein-Befehl eines Bausteins fuer die Tasten der Raumkarte (Aufbau
        "raeume", HAUS_EIN) oder None. Die Lichtsteuerung schaltet ihre erste
        Stimmung ohne "Aus" ein; ohne Stimmung hat sie keinen."""
        c = self.controls.get(uuid) or {}
        if not c.get("uuidAction"):
            return None
        if c.get("type") == "LightControllerV2":
            stimmungen = self._geste_stimmungen(uuid)
            return {"uuid": c["uuidAction"], "cmd": f"changeTo/{stimmungen[0][0]}"} if stimmungen else None
        cmd = HAUS_EIN.get(c.get("type"))
        return {"uuid": c["uuidAction"], "cmd": cmd} if cmd else None

    def _haus_tasten(self, uuids: list, items: list) -> list:
        """Tasten einer Raumkarte im Aufbau "raeume": die ersten HAUS_TASTEN
        Bausteine, die sich ab- und einschalten lassen (HAUS_AUS, _haus_ein),
        mit dem Befehl, der ihren Zustand umkehrt. Was HAUS_RUECKFRAGE nennt,
        fragt vor dem Einschalten nach (frage)."""
        out = []
        for u, it in zip(uuids, items):
            aus, ein = self._haus_aus(u), self._haus_ein(u)
            if not (aus and ein):
                continue
            an = bool(it.get("on"))
            t = {"id": u, "name": it.get("label") or "", "an": an, "zustand": it.get("sublabel") or "",
                 "cmd": {"uuid": aus["uuid"], "cmd": aus["cmd"]} if an else ein, **self._haus_symbol(it)}
            frage = HAUS_RUECKFRAGE.get(self.controls[u].get("type"))
            if frage and not an:
                t["frage"] = frage
            if it.get("secured"):
                t["secured"] = True
            out.append(t)
            if len(out) == HAUS_TASTEN:
                break
        return out

    def _haus_blick(self, uuids: list, items: list, raum: str, energie: str | None, hinweise: set) -> list:
        """"Auf einen Blick" im Aufbau "spalte": Bausteine, die einen Zustand
        melden, sich aber nicht abschalten lassen (nicht in HAUS_AUS, etwa
        Postkasten, Lueftung, Zentral-Bausteine). Was einen grossen Wert hat
        (Raumregelung, Sauna), steht schon auf der Raumkarte, der Energie-
        Baustein im Kopf der Spalte, ein Baustein mit Hinweis darueber unter
        den Hinweisen; beschreibende Zeilen (subInfo) zaehlen nicht. Ein Tipp
        oeffnet den Baustein."""
        out = []
        for u, it in zip(uuids, items):
            if self._haus_aus(u) or it.get("big") is not None or u == energie or u in hinweise \
                    or not it.get("sublabel") or it.get("subInfo"):
                continue
            b = {"id": u, "zustand": str(it["sublabel"]), "name": " · ".join(x for x in (it.get("label"), raum) if x),
                 **self._haus_symbol(it)}
            if it.get("nav"):
                b["nav"] = it["nav"]
            out.append(b)
        return out

    def _haus_hinweise(self, kacheln: list) -> list:
        """Hinweise der Hausseite aus den Kacheln ihrer Raeume [(uuid, kachel,
        raum)]: was die Kachel selbst nennt (hinweis), sonst ihr Ton
        (HINWEIS_TON) mit ihrem Zustand als Text. Nach Stufe (HINWEIS_STUFEN),
        innerhalb einer Stufe in der Folge der Raeume. Ein Tipp oeffnet den
        Baustein. Die Bedingung steht damit nur an der Kachel; die Seite kommt
        mit jeder Zustandsaenderung neu (broadcaster)."""
        out = []
        for u, it, raum in kacheln:
            h = it.get("hinweis") or {}
            stufe = h.get("stufe") or HINWEIS_TON.get(it.get("tone"))
            text = h.get("text") or it.get("sublabel")
            if stufe not in HINWEIS_STUFEN or not text:
                continue
            label = it.get("label") or ""
            wo = [label] + ([raum] if raum != label else []) + [h.get("zusatz")]
            x = {"id": u, "stufe": stufe, "titel": str(text), "wo": " · ".join(w for w in wo if w),
                 **({"icon": h["symbol"]} if h.get("symbol") else self._haus_symbol(it))}
            if it.get("nav"):
                x["nav"] = it["nav"]
            out.append(x)
        out.sort(key=lambda x: HINWEIS_STUFEN.index(x["stufe"]))
        return out

    def _haus_spieler(self, zonen: list, wahl, prof: dict | None) -> dict | None:
        """Spieler der Hausseite: die gewaehlte Zone (Route "zone"), sonst die
        erste, die spielt, sonst die erste. Inhalt aus den Bloecken der
        Detailseite (player_blocks: Cover, Titel, Transport, Lautstaerke), damit
        Befehle und Texte dieselben sind; dazu alle Zonen zum Umschalten,
        wie auf der Detailseite das ⋮ zur Musikauswahl (Route des more-Blocks)
        und die ersten HAUS_SENDER Favoriten der Zone (_haus_sender)."""
        if not zonen:
            return None
        kacheln = {u: self._control_item(u, prof) for u in zonen}
        spielt = {u: bool(kacheln[u].get("on")) for u in zonen}
        zone = wahl if wahl in zonen else next((u for u in zonen if spielt[u]), zonen[0])
        bloecke = self.player_blocks(zone, mehr=True) or []

        def block(k):
            return next((b for b in bloecke if b.get("k") == k), {})

        def zname(u):
            c = self.controls.get(u) or {}
            return _clean((self.rooms.get(c.get("room")) or {}).get("name")) or _clean(c.get("name"))
        titel, regler = block("title"), block("slider")
        sp = {"zone": zone, "name": zname(zone), "spielt": spielt[zone],
              "titel": str(titel.get("text") or ""), "sub": str(titel.get("sub") or ""),
              "cover": block("cover").get("src") or "",
              "tasten": [{"icon": z.get("icon"), "cmd": z.get("cmd")}
                         for z in (block("row").get("cells") or []) if z.get("cmd")],
              # je Zone, was sie spielt (Zustand ihrer Kachel), fuer die Zonenliste
              "zonen": [{"id": u, "name": zname(u), "spielt": spielt[u],
                         "titel": str(kacheln[u].get("sublabel") or "") if spielt[u] else ""} for u in zonen]}
        if regler.get("cmd"):
            sp["laut"] = {"wert": int(regler.get("value") or 0), "cmd": regler["cmd"],
                          "min": int(regler.get("min") or 0), "max": int(regler.get("max") or 100),
                          "schritt": PROZENT_SCHRITT}
        if block("more").get("route"):
            sp["mehr"] = block("more")["route"]
        sp["sender"] = self._haus_sender(zone, spielt[zone], (sp["titel"], sp["sub"]))
        if self._gesichert(zone):
            sp["secured"] = True
        return sp

    def _haus_sender(self, zone: str, spielt: bool, texte: tuple) -> list:
        """Favoriten der Zone fuer den Spieler der Hausseite, dieselben wie in
        der Musikauswahl (_zonen_favoriten): [{name, cover, cmd}], hoechstens
        HAUS_SENDER. Welcher laeuft (laeuft), sagt der Miniserver nicht; die
        Zone nennt nur Titel und Sender. Ein Favorit gilt als laufend, wenn
        die Zone spielt und er genau so heisst wie einer dieser Texte (oder
        der Name, den der Audioserver-Kanal meldet), sonst ist keiner markiert.
        Sind noch keine Favoriten da, fordert der Server sie an
        (_haus_sender_anfordern)."""
        favs, _ = self._zonen_favoriten(zone)
        if not favs:
            self._haus_sender_anfordern(zone)
            return []
        jetzt = set()
        if spielt:
            sm = self._sonn_for(self.controls.get(zone) or {}) or {}
            jetzt = {str(t).strip().casefold() for t in (*texte, sm.get("name"), sm.get("album")) if t}
        out = []
        for f in favs[:HAUS_SENDER]:
            x = {"name": f["label"], "cover": f["cover"], "cmd": f["cmd"]}
            if str(f["label"]).strip().casefold() in jetzt:
                x["laeuft"] = True
            out.append(x)
        return out

    def _haus_sender_anfordern(self, zone: str) -> None:
        """Favoriten einer Zone im Hintergrund anfordern (prime_favs), wie es
        die Musikauswahl beim Oeffnen tut: hoechstens alle HAUS_SENDER_NEU_S je
        Zone, denn die Hausseite wird bei jeder Zustandsaenderung neu
        gerechnet. Das Ergebnis kommt ueber _dirty mit dem naechsten Rendern.
        Ohne laufende Ereignisschleife (Aufruf ausserhalb des Servers) nichts."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        jetzt = time.monotonic()
        zuletzt = self._haus_sender_zeit.get(zone)
        if zuletzt is not None and jetzt - zuletzt < HAUS_SENDER_NEU_S:
            return
        self._haus_sender_zeit[zone] = jetzt
        self._spawn(self.prime_favs(zone))

    def _haus_energie(self, uuids: list, prof: dict | None) -> dict | None:
        """Energie fuer den Kopf der Hausseite: der erste Energieflussmonitor bzw.
        Energiemanager unter den Bausteinen der Seite, sonst der erste sichtbare
        der Anlage. Text wie auf seiner Kachel, dazu Erzeugung und Verbrauch in
        Watt wie im Energiefluss (energy_blocks); ein Tipp oeffnet ihn."""
        typen = ("EFM", "EnergyManager2")
        u = next((x for x in uuids if (self.controls.get(x) or {}).get("type") in typen), None)
        if u is None:
            u = next((x for x, c in self.controls.items() if c.get("type") in typen and self._shown(x, prof)), None)
        if u is None:
            return None
        it = self._control_item(u, prof)
        e = {"id": u, "label": it.get("label") or "", "wert": it.get("sublabel") or "",
             "nav": it.get("nav") or {"view": "control", "id": u}}
        summen = (self.energy_blocks(u) or {}).get("totals") or {}

        def watt(v):   # gerundet; unbekannt (None, NaN, unendlich) bleibt weg
            return round(v) if isinstance(v, (int, float)) and math.isfinite(v) else None
        cons, prod = watt(summen.get("cons")), watt(summen.get("prod"))
        if cons is not None:
            e["cons"] = cons
            if prod is not None:
                e["prod"] = prod
        return e

    def _haus_schnell(self, prof: dict | None) -> list:
        """Schnellaktionen der Hausseite (HAUS_SCHNELL): je Art der erste
        Zentral-Baustein der Anlage, den die Ansicht nicht ausblendet, mit
        seinem Befehl und wie viele seiner Mitglieder an sind (_zentral_an).
        Ohne den Baustein keine Taste. Die Anzahl kommt mit jeder
        Zustandsaenderung neu (broadcaster rendert die Seite), die Visu fragt
        nicht nach. Ein gesicherter Baustein (Visu-PIN) fragt in der Visu nach
        der PIN wie jede Taste."""
        out = []
        for art, (typ, label, cmd) in HAUS_SCHNELL.items():
            u = next((x for x, c in self.controls.items()
                      if c.get("type") == typ and c.get("uuidAction") and self._shown(x, prof)), None)
            if u is None:
                continue
            c = self.controls[u]
            s = {"art": art, "id": u, "label": label, "an": self._zentral_an(c),
                 "cmd": {"uuid": c["uuidAction"], "cmd": cmd}}
            if c.get("isSecured"):
                s["secured"] = True
            out.append(s)
        return out

    # ---- Gesten (Loxone-Standard wie auf den Tastern, docs/TODO.md §9) ----
    def geste_raum(self, route: dict | None, prof: dict | None) -> str | None:
        """Raum, den eine Geste trifft: der der Seite (Raum-Tab oder Raum unter
        "Raeume"), sonst der feste Raum der Ansicht (gestenRaum). None, wenn es
        keinen gibt oder der Miniserver ihn nicht kennt."""
        r = route or {}
        ru = None
        if r.get("view") == "group" and r.get("kind") == "room":
            ru = r.get("id")
        elif r.get("view") == "tab" and isinstance(r.get("tab"), str) and r["tab"].startswith("room:"):
            ru = r["tab"][5:]
        if not ru:
            ru = (prof or {}).get("gestenRaum")
        return ru if isinstance(ru, str) and ru in self.rooms else None

    def gesten_hilfe(self, route: dict | None, prof: dict | None) -> dict | None:
        """Was zwei Finger auf dieser Seite tun, fuer das Hinweis-Symbol der Visu
        und seine Hilfe: der Raum der Seite (geste_raum), Doppel- und
        Dreifachtipp mit den Tastern aus den Vorgaben, so wie geste() sie
        ausloest. None, wo Gesten oder ihr Hinweis aus sind oder kein Raum gilt."""
        if not (prof or {}).get("gesten") or not (prof or {}).get("gestenHinweis"):
            return None
        ru = self.geste_raum(route, prof)
        if not ru:
            return None
        ui = self.theme.get("ui") or {}
        raum = _clean(self.rooms[ru].get("name")) or "diesem Raum"

        def taster(uuid) -> str:
            c = self.controls.get(uuid or "")
            ok = c and c.get("type") in GESTEN_TASTER_TYPEN and not c.get("isSecured")
            return f"Taster „{_clean(c.get('name')) or uuid}“" if ok else "Taster nicht gefunden"
        verlassen = (ui.get("raumVerlassen") or {}).get(ru)
        haus = ui.get("hausAus")
        return {"raum": raum,
                "doppel": f"{raum} verlassen: " + (taster(verlassen) if verlassen
                                                    else "aus, was an ist und sich abschalten lässt"),
                "dreifach": "Haus aus: " + (taster(haus) if haus else "nicht eingerichtet (Vorgaben → Verhalten)")}

    def _geste_bausteine(self, ru: str, prof: dict | None, typen: tuple) -> list:
        """Bausteine dieser Typen im Raum, so wie seine Raumseite sie zeigt
        (Kategorie-Filter und Ausblendungen der Ansicht). Gesicherte bleiben
        aussen vor: eine PIN-Abfrage mitten in einer Geste geht nicht."""
        return [u for u, c in self.controls.items()
                if c.get("room") == ru and c.get("type") in typen and not c.get("isSecured")
                and self._cat_ok(u, prof) and self._shown(u, prof)]

    def _geste_kreis(self, d: dict, uuid: str) -> dict | None:
        """Dimmbarer Kreis (Dimmer oder Lichtkreis einer Lichtsteuerung) mit den
        States der Strukturdoku: {ziel, wert, min, max}; None ohne Stellung."""
        wert = self._endlich(d, "position")
        if wert is None:
            return None
        mn = self._endlich(d, "min")
        mx = self._endlich(d, "max")
        mn = 0.0 if mn is None else mn
        mx = 100.0 if mx is None or mx <= mn else mx
        return {"ziel": d.get("uuidAction") or uuid, "wert": wert, "min": mn, "max": mx}

    def licht_gruppen(self, ru: str, prof: dict | None) -> list:
        """Lichtgruppen eines Raums: jede Lichtsteuerung mit ihren dimmbaren
        Lichtkreisen (Unterbausteine vom Typ Dimmer ohne die Master-Helligkeit,
        details.masterValue) und jeder einzelne Dimmer als Gruppe mit einem
        Kreis. So gelten dieselben Regeln fuer eine Lichtsteuerung mit vielen
        Kreisen, mehrere in einem offenen Raum und lauter einzelne Dimmer.
        Je Gruppe: {uuid, typ, an, kreise}."""
        out = []
        for u in self._geste_bausteine(ru, prof, GESTEN_LICHT_TYPEN + GESTEN_DIMMER_TYPEN):
            c = self.controls[u]
            if c.get("type") in GESTEN_LICHT_TYPEN:
                master = (c.get("details") or {}).get("masterValue")
                kreise = [self._geste_kreis(s, su) for su, s in (c.get("subControls") or {}).items()
                          if isinstance(s, dict) and s.get("type") in GESTEN_DIMMER_TYPEN
                          and master not in (su, s.get("uuidAction"))]
                an = LIGHT.render(self._with_uuid(u), self.states)["on"]
            else:
                kreise = [self._geste_kreis(c, u)]
                an = None
            kreise = [k for k in kreise if k]
            out.append({"uuid": u, "typ": c.get("type"), "kreise": kreise,
                        "an": any(k["wert"] > 0 for k in kreise) if an is None else an})
        return out

    def _geste_stimmungen(self, uuid: str) -> list:
        """Stimmungen einer Lichtsteuerung ohne "Aus", in der Folge ihrer
        moodList: [(id, name)]."""
        out = []
        for m in LIGHT.moods(self._with_uuid(uuid), self.states):
            try:
                mid = int(m.get("id"))
            except (TypeError, ValueError):
                continue
            if mid != LightControllerV2Adapter.OFF_MOOD:
                out.append((mid, _clean(m.get("name")) or str(mid)))
        return out

    def _geste_lichtsteuerung(self, gruppen: list, dev: str) -> tuple:
        """Lichtsteuerung des Geraets und ihre Stimmung beim Einschalten
        (devices[dev].lichtStart), wenn sie in diesem Raum liegt, sonst die
        erste des Raums mit ihrer ersten Stimmung: (gruppe, stimmungs_id) oder
        (None, None)."""
        lcs = [g for g in gruppen if g["typ"] in GESTEN_LICHT_TYPEN]
        start = (self.devices.get(dev) or {}).get("lichtStart") if dev else None
        for g in lcs:
            if start and g["uuid"] == start.get("lc"):
                ids = [m for m, _n in self._geste_stimmungen(g["uuid"])]
                return g, (start.get("mood") if start.get("mood") in ids else (ids[0] if ids else None))
        if lcs:
            ids = [m for m, _n in self._geste_stimmungen(lcs[0]["uuid"])]
            return lcs[0], (ids[0] if ids else None)
        return None, None

    async def _geste_befehle(self, befehle: list) -> int:
        """Befehle einer Geste gleichzeitig schicken; Zahl der fehlgeschlagenen."""
        codes = await asyncio.gather(*(self.command(u, c) for u, c in befehle))
        return sum(1 for code in codes if code != "200")

    async def _geste_taster(self, uuid: str, text: str, fehlt: str) -> dict:
        """Taster aus Loxone Config ausloesen (pulse): Raum verlassen, Haus aus."""
        c = self.controls.get(uuid or "")
        if not c or c.get("type") not in GESTEN_TASTER_TYPEN or c.get("isSecured"):
            return {"fehler": fehlt}
        if await self._geste_befehle([(c.get("uuidAction") or uuid, "pulse")]):
            return {"fehler": "Miniserver hat nicht ausgelöst"}
        return {"text": text}

    async def geste(self, ws, data: dict) -> dict | None:
        """Geste der Visu ausfuehren ({t:"geste", art, ...}) und die Antwort fuer
        ihre Einblendung liefern ({t:"geste", art, raum, wert|text|fehler}).
        None: nichts zu melden (Zwischenwert beim Dimmen) oder Gesten aus.

        art: "licht" und "musik" mit phase start/wert/ende (Mitte bzw. rechts
        hoch/runter), "stimmung" (Tipp Mitte), "beschattung" mit richtung
        auf/ab (links hoch/runter), "verlassen" (Doppeltipp), "hausaus"
        (Dreifachtipp)."""
        prof = self.conn_prof.get(ws) or {}
        art = str(data.get("art") or "")
        if not prof.get("gesten"):
            return None
        if art == "hausaus":
            ziel = (self.theme.get("ui") or {}).get("hausAus")
            if not ziel:
                return {"t": "geste", "art": art,
                        "fehler": "„Haus aus“ ist nicht eingerichtet (Vorgaben → Verhalten)"}
            return {"t": "geste", "art": art, **await self._geste_taster(
                ziel, "Haus aus", "Taster für „Haus aus“ nicht gefunden")}
        ru = self.geste_raum(self.conn_route.get(ws), prof)
        if not ru:
            return {"t": "geste", "art": art, "fehler": "Kein Raum auf dieser Seite"}
        antwort = {"t": "geste", "art": art, "raum": _clean(self.rooms[ru].get("name"))}
        raum = antwort["raum"] or "diesem Raum"
        if art in ("licht", "musik"):
            phase = data.get("phase")
            if phase == "start":
                lauf, start = (self._geste_licht_start(ru, prof, self.conn_dev.get(ws, ""))
                               if art == "licht" else self._geste_musik_start(ru, prof))
                if not lauf:
                    self.conn_geste.pop(ws, None)
                    return {**antwort, "fehler": start}
                self.conn_geste[ws] = lauf
                return {**antwort, "phase": "start", **start}
            lauf = self.conn_geste.get(ws)
            if not lauf or lauf["art"] != art:
                return None
            try:
                wert = max(0.0, min(100.0, float(data.get("wert"))))
            except (TypeError, ValueError):
                return None
            if phase == "ende":
                self.conn_geste.pop(ws, None)
            text = await self._geste_wert(lauf, wert, phase == "ende")
            return {**antwort, "text": text} if text else None
        if art == "stimmung":
            return {**antwort, **await self._geste_stimmung(ru, prof, self.conn_dev.get(ws, ""), raum)}
        if art == "beschattung":
            jal = self._geste_bausteine(ru, prof, GESTEN_BESCHATTUNG_TYPEN)
            if not jal:
                return {**antwort, "fehler": f"Keine Beschattung in {raum}"}
            fahrend = [u for u in jal if any(self._jal_fahrt(self.controls[u])[:2])]
            if fahrend:
                befehle = [(self.controls[u].get("uuidAction") or u, "Stop") for u in fahrend]
                text = "Beschattung gestoppt"
            else:
                auf = data.get("richtung") == "auf"
                befehle = [(self.controls[u].get("uuidAction") or u, "FullUp" if auf else "FullDown") for u in jal]
                text = "Beschattung auf" if auf else "Beschattung ab"
            fehl = await self._geste_befehle(befehle)
            return {**antwort, **({"fehler": f"{fehl} von {len(befehle)} Befehlen nicht ausgeführt"}
                                  if fehl else {"text": text})}
        if art == "verlassen":
            ziel = ((self.theme.get("ui") or {}).get("raumVerlassen") or {}).get(ru)
            if ziel:
                return {**antwort, **await self._geste_taster(
                    ziel, f"{raum} verlassen", f"Taster für „{raum} verlassen“ nicht gefunden")}
            # Ohne Taster aus Loxone: aus, was im Raum an ist und sich abschalten
            # laesst (wie "Gerade aktiv"). Das Raumklima bleibt unberuehrt.
            befehle = []
            for u in self._geste_bausteine(ru, prof, tuple(HAUS_AUS)):
                aus = self._haus_aus(u)
                if aus and self._control_item(u, prof).get("on"):
                    befehle.append((aus["uuid"], aus["cmd"]))
            if not befehle:
                return {**antwort, "text": f"In {raum} ist nichts an"}
            fehl = await self._geste_befehle(befehle)
            return {**antwort, **({"fehler": f"{fehl} von {len(befehle)} Befehlen nicht ausgeführt"}
                                  if fehl else {"text": f"{raum}: {len(befehle)} aus"})}
        return None

    def _geste_licht_start(self, ru: str, prof: dict | None, dev: str) -> tuple:
        """Beginn von Mitte hoch/runter: (lauf, antwort) oder (None, fehler).
        Leuchtet etwas, wird es anteilig gedimmt (Startwert der hellste Kreis).
        Ist alles aus, schaltet die Bewegung nach oben die Stimmung des Geraets
        ein (lichtStart) bzw. setzt die einzelnen Dimmer des Raums."""
        gruppen = self.licht_gruppen(ru, prof)
        an = [(g, k) for g in gruppen for k in g["kreise"] if k["wert"] > 0]
        if an:
            start = max(k["wert"] for _g, k in an)
            return ({"art": "licht", "modus": "dimmen", "start": start,
                     "kreise": [dict(k) for _g, k in an],
                     "lcs": sorted({g["uuid"] for g, _k in an if g["typ"] in GESTEN_LICHT_TYPEN}),
                     "gesendet": {}},
                    {"wert": round(start)})
        g, mood = self._geste_lichtsteuerung(gruppen, dev)
        if g and not g["an"] and mood is not None:
            name = dict(self._geste_stimmungen(g["uuid"])).get(mood, "")
            return ({"art": "licht", "modus": "stimmung", "lc": g["uuid"], "mood": mood, "name": name,
                     "gesendet": {}},
                    {"wert": 0, "text": name})
        kreise = [k for gr in gruppen if gr["typ"] in GESTEN_DIMMER_TYPEN for k in gr["kreise"]]
        if kreise:
            return ({"art": "licht", "modus": "neu", "kreise": kreise, "gesendet": {}}, {"wert": 0})
        return None, "Kein dimmbares Licht in " + (_clean(self.rooms[ru].get("name")) or "diesem Raum")

    def _geste_musik_start(self, ru: str, prof: dict | None) -> tuple:
        """Beginn von rechts hoch/runter: Lautstaerke der Audio-Zonen des Raums,
        Startwert die der ersten, die spielt (sonst der ersten)."""
        zonen = self._geste_bausteine(ru, prof, GESTEN_AUDIO_TYPEN)
        if not zonen:
            return None, "Keine Musik in " + (_clean(self.rooms[ru].get("name")) or "diesem Raum")
        erste = next((u for u in zonen if self._state(self.controls[u], "playState") == 2), zonen[0])
        start = self._endlich(self.controls[erste], "volume") or 0.0
        return ({"art": "musik", "zonen": [self.controls[u].get("uuidAction") or u for u in zonen],
                 "gesendet": {}},
                {"wert": round(start)})

    async def _geste_wert(self, lauf: dict, wert: float, ende: bool) -> str:
        """Zwischen- oder Endwert einer laufenden Geste umsetzen; Text fuer die
        Einblendung, wenn es einen gibt. Jeder Kreis bekommt nur einen Befehl,
        wenn sich sein Wert aendert."""
        befehle = []
        danach = []     # erst, wenn die Befehle davor beim Miniserver angekommen sind
        text = ""
        if lauf["art"] == "musik":
            v = round(wert)
            befehle = [(z, f"volume/{v}") for z in lauf["zonen"] if lauf["gesendet"].get(z) != v]
            for z, _c in befehle:
                lauf["gesendet"][z] = v
        elif lauf["modus"] == "stimmung":
            # Erst die Bewegung nach oben schaltet ein, genau einmal; weiter
            # gedimmt wird mit der naechsten Geste, wenn die Kreise leuchten
            if wert > 0 and not lauf["gesendet"]:
                lauf["gesendet"]["mood"] = lauf["mood"]
                befehle = [(self.controls[lauf["lc"]].get("uuidAction") or lauf["lc"],
                            f"changeTo/{lauf['mood']}")]
                text = lauf["name"]
        else:
            # Anteilig: jeder Kreis um denselben Faktor, das Verhaeltnis (das
            # Lichtbild der Stimmung) bleibt. "neu": alle auf den Wert.
            faktor = wert / lauf["start"] if lauf["modus"] == "dimmen" else None
            for k in lauf["kreise"]:
                v = round(k["wert"] * faktor) if faktor is not None else round(wert)
                v = 0 if v <= 0 else max(round(k["min"]), min(round(k["max"]), v))
                if lauf["gesendet"].get(k["ziel"]) != v:
                    lauf["gesendet"][k["ziel"]] = v
                    befehle.append((k["ziel"], str(v)))
            if ende and wert <= 0:
                # Ganz unten: Lichtsteuerungen sauber auf "Aus", statt mit
                # dunklen Kreisen auf "Manuell" stehen zu bleiben. Erst nach den
                # Kreisen: _geste_befehle schickt gleichzeitig (je Befehl eine
                # HTTP-Anfrage), und ein Kreis, der nach dem "Aus" ankommt,
                # stellte die Lichtsteuerung wieder auf "Manuell".
                danach = [(self.controls[u].get("uuidAction") or u,
                           f"changeTo/{LightControllerV2Adapter.OFF_MOOD}") for u in lauf.get("lcs", ())]
                text = "Aus"
        fehl = await self._geste_befehle(befehle) if befehle else 0
        if danach:
            fehl += await self._geste_befehle(danach)
        return "Nicht alle Befehle ausgeführt" if fehl else text

    async def _geste_stimmung(self, ru: str, prof: dict | None, dev: str, raum: str) -> dict:
        """Tipp Mitte: aus -> Stimmung beim Einschalten, an -> naechste Stimmung
        derselben Lichtsteuerung (changeTo, "Aus" uebersprungen). Ohne
        Lichtsteuerung schaltet er die einzelnen Dimmer ein."""
        gruppen = self.licht_gruppen(ru, prof)
        g, mood = self._geste_lichtsteuerung(gruppen, dev)
        if g:
            stimmungen = self._geste_stimmungen(g["uuid"])
            if not stimmungen:
                return {"fehler": f"Keine Stimmungen in {raum}"}
            ids = [m for m, _n in stimmungen]
            if g["an"]:
                aktiv = [m for m in LIGHT.active_moods(self._with_uuid(g["uuid"]), self.states) if m in ids]
                mood = ids[(ids.index(aktiv[0]) + 1) % len(ids)] if aktiv else ids[0]
            ua = self.controls[g["uuid"]].get("uuidAction") or g["uuid"]
            if await self._geste_befehle([(ua, f"changeTo/{mood}")]):
                return {"fehler": "Miniserver hat nicht umgeschaltet"}
            return {"text": dict(stimmungen)[mood]}
        dimmer = [gr for gr in gruppen if gr["typ"] in GESTEN_DIMMER_TYPEN]
        if not dimmer:
            return {"fehler": f"Kein Licht in {raum}"}
        if any(gr["an"] for gr in dimmer):
            return {"text": "Licht ist an"}
        befehle = [(k["ziel"], "on") for gr in dimmer for k in gr["kreise"]]
        if await self._geste_befehle(befehle):
            return {"fehler": "Nicht alle Befehle ausgeführt"}
        return {"text": "Licht an"}

    def _view_haus(self, route: dict, prof: dict | None = None) -> dict:
        """Hausuebersicht: je Raum eine Karte (Hauptwert, Symbole, wie viel an
        ist; ein Tipp oeffnet den Raum), "Gerade aktiv" (was an ist und sich
        abschalten laesst, mit Aus-Taste), die Schnellaktionen (_haus_schnell),
        der Spieler einer Audio-Zone und die Energie fuer den Kopf. Uhr, Wetter
        und Termine kommen in der Visu aus der Front. Route: zone (gewaehlte
        Zone), liste (HAUS_LISTEN: Unterseite mit allen aktiven Geraeten bzw.
        allen Hinweisen). Die Hinweise (_haus_hinweise) hat jeder Aufbau.
        Der Aufbau der Ansicht (HAUS_AUFBAUTEN) bringt dazu: "raeume" je
        Raumkarte ihre Tasten (_haus_tasten), "spalte" "Auf einen Blick"
        (_haus_blick)."""
        aufbau = (prof or {}).get("hausAufbau")
        aufbau = aufbau if aufbau in HAUS_AUFBAUTEN else HAUS_AUFBAU_STANDARD
        raeume, aktiv, zonen, alle, blick_roh, kacheln = [], [], [], [], [], []
        for ru, uuids in self._haus_raeume(prof):
            name = _clean(self.rooms[ru].get("name")) or "Raum"
            items = [self._control_item(u, prof, ohne_raum=name) for u in uuids]
            wert, sub = self._haus_hauptwert(items)
            schaltbar, sonst, an = [], [], 0
            for u, it in zip(uuids, items):
                alle.append(u)
                kacheln.append((u, it, name))
                t = self.controls[u].get("type")
                if t in ("AudioZone", "AudioZoneV2"):
                    zonen.append(u)
                aus = self._haus_aus(u)
                if it.get("big") is None:
                    # mit grossem Wert steht der Baustein schon als Hauptwert da
                    (schaltbar if aus else sonst).append(it)
                if aus and it.get("on"):
                    an += 1
                    a = {"id": u, "label": it.get("label") or "", "raum": name,
                         "zustand": it.get("sublabel") or "", "aus": {"uuid": aus["uuid"], "cmd": aus["cmd"]},
                         "taste": aus["taste"], **self._haus_symbol(it)}
                    if it.get("secured"):
                        a["secured"] = True
                    aktiv.append(a)
            symbole = [dict(self._haus_symbol(it), on=bool(it.get("on")))
                       for it in (schaltbar + sonst)[:HAUS_SYMBOLE]]
            raum = {"id": ru, "name": name, "wert": wert, "sub": sub, "an": an,
                    "anzahl": len(uuids), "symbole": symbole,
                    "nav": {"view": "group", "kind": "room", "id": ru}}
            if aufbau == "raeume":
                raum["tasten"] = self._haus_tasten(uuids, items)
            elif aufbau == "spalte":
                blick_roh.append((uuids, items, name))
            raeume.append(raum)
        energie = self._haus_energie(alle, prof)
        tab = (route or {}).get("tab") or HAUS_TAB
        if _is_pick(tab):
            # freie Seite: ihr Name ist der Titel
            seiten, i = _pick_tabs(prof), _pick_index(tab)
            titel = (seiten[i].get("name") if 0 <= i < len(seiten) else "") or HAUS_TITEL
        else:
            titel = HAUS_TITEL
        hinweise = self._haus_hinweise(kacheln)
        out = {"t": "view", "title": titel, "tab": tab, "route": route, "layout": "haus", "aufbau": aufbau,
               "raeume": raeume, "aktiv": aktiv, "hinweise": hinweise, "schnell": self._haus_schnell(prof),
               "spieler": self._haus_spieler(zonen, (route or {}).get("zone"), prof),
               "energie": energie}
        if aufbau == "spalte":
            eid, mit = (energie or {}).get("id"), {h["id"] for h in hinweise}
            out["blick"] = [b for uuids, items, name in blick_roh
                            for b in self._haus_blick(uuids, items, name, eid, mit)]
        if (route or {}).get("liste") in HAUS_LISTEN:
            out["liste"] = route["liste"]
        return out

    def _zonen_favoriten(self, uuid: str) -> tuple[list, bool]:
        """Favoriten einer Audio-Zone fuer die Musikauswahl und den Spieler der
        Hausseite: ([{label, cmd, cover}], ob sie vom Audioserver-Kanal kommen).

        Zuerst aus dem Audioserver-Event-Kanal (Port 7091) - fuer Gen1
        (Musikserver) UND Gen2 (Audioserver/Sonn). Der Loxone-sourceList-State
        ist bei vielen Setups leer, dies ist der zuverlaessige Weg. Der
        Abspiel-Index (`play`) beruecksichtigt, dass Musikserver per `slot` und
        Sonn per Item-`id` adressiert (siehe AudioEventClient._apply_favs).
        Nur wenn der Kanal die Favoriten auch liefern darf: ein gekoppelter
        Audioserver ohne geglueckte Anmeldung (oder unklare Kopplung) schickt
        keine (dieselbe Bedingung wie beim Anfordern in prime_favs) -> dann
        die des Miniservers (_audio_favs)."""
        c = self.controls.get(uuid, {})
        ua = c.get("uuidAction")

        def cover(url):
            return ("/cover?u=" + quote(url, safe="")) if url else ""
        cl, pid = self._audio_client_for(c) if c.get("type") in ("AudioZone", "AudioZoneV2") else (None, None)
        if cl is not None and pid is not None and (cl.paired is False or cl.authed):
            return ([{"label": f["name"], "cmd": {"uuid": ua, "cmd": f"roomfav/play/{f.get('play', f['slot'])}"},
                      "cover": cover(f["cover"])}
                     for f in cl.favs.get(pid, []) if f.get("slot") is not None], True)
        return ([{"label": f["name"], "cmd": {"uuid": ua, "cmd": f"roomfav/play/{f['slot']}"},
                  "cover": cover(f["cover"])} for f in self._audio_favs(c)], False)

    def _view_sources(self, uuid: str) -> dict:
        """Musikauswahl einer AudioZone: feste Rubriken (immer sichtbar, auch leer).

        'Favoriten' = die Zonen-Favoriten (_zonen_favoriten). 'Playlisten' ist
        vorerst ein Platzhalter (Bibliothek/Playlisten liegen im Audioserver
        und werden noch nicht abgefragt).
        """
        c = self.controls.get(uuid, {})
        items, vom_kanal = self._zonen_favoriten(uuid)
        if vom_kanal:
            body = ({"k": "favs", "wrap": True, "items": items} if items else
                    {"k": "status", "text": "noch keine – in der App/am Tablet anlegen"})
            return {"t": "view", "title": _clean(c.get("name")),
                    "route": {"view": "sources", "id": uuid},
                    "blocks": [{"k": "title", "text": _clean(c.get("name")), "sub": "Musikauswahl"},
                               {"k": "head", "text": "Favoriten"}, body]}

        empty = {"k": "status", "text": "noch keine – im Tablet / der App anlegen"}
        blocks = [{"k": "title", "text": _clean(c.get("name")), "sub": "Musikauswahl"},
                  {"k": "head", "text": "Favoriten"},
                  {"k": "favs", "wrap": True, "items": items} if items else dict(empty),
                  {"k": "head", "text": "Playlisten"},
                  dict(empty)]
        return {"t": "view", "title": _clean(c.get("name")),
                "route": {"view": "sources", "id": uuid}, "blocks": blocks}

    @staticmethod
    def _gone_view(route: dict, title: str, text: str) -> dict:
        """Unterseite, deren Gegenstand es (nicht mehr) gibt: nur der Hinweis."""
        return {"t": "view", "title": title, "route": route, "blocks": [{"k": "status", "text": text}]}

    def _view_irr_zone(self, uuid: str, zone) -> dict:
        """Eine Zone der Bewaesserung: starten (select, Nummer siehe
        IRR_SELECT_*) bzw. stoppen (stop) und ihre Laufzeit
        (setDuration/{id}={Sekunden}). Gibt die Logik die Laufzeit vor
        (setByLogic), steht sie nur da."""
        c = self.controls.get(uuid or "", {})
        route = {"view": "irrzone", "id": uuid, "zone": zone}
        try:
            zid = int(zone)
        except (TypeError, ValueError):
            zid = None
        z = (next((z for z in self._irr_zones(c) if z["id"] == zid), None)
             if c.get("type") == "Irrigation" else None)
        if z is None:
            return self._gone_view(route, _clean(c.get("name")), "Diese Zone gibt es nicht mehr.")
        ua = c.get("uuidAction")
        cur = self._irr_current(c)
        an = cur in (zid, IRR_ALLE_AKTIV)
        blocks = [{"k": "title", "text": z["name"], "sub": _clean(c.get("name"))},
                  {"k": "big", "text": "Läuft" if an else "Aus", **({"tone": "good"} if an else {})}]
        if z["duration"] is not None:
            dauer = {"k": "stepper", "label": "Laufzeit", "value": z["duration"], "fmt": "dauer"}
            if z["logic"]:
                dauer["sub"] = "von der Logik vorgegeben"
            else:
                dauer.update(step=DAUER_SCHRITT, min=0,
                             cmd={"uuid": ua, "tmpl": f"setDuration/{zid}={{v}}"})
            blocks.append(dauer)
        if an:
            knopf = {"label": "Alle Zonen stoppen" if cur == IRR_ALLE_AKTIV else "Zone stoppen",
                     "cmd": {"uuid": ua, "cmd": "stop"}}
        else:
            knopf = {"label": "Zone starten", "cmd": {"uuid": ua, "cmd": f"select/{zid + 1}"}}
        blocks.append({"k": "row", "cells": [knopf]})
        return {"t": "view", "title": z["name"], "route": route, "anchor": "bottom", "blocks": blocks}

    def _view_alarm_entry(self, uuid: str, entry) -> dict:
        """Weckzeit bearbeiten oder (entry leer) anlegen: Name, Uhrzeit und
        Tage. Die Visu setzt die drei in die Befehlsvorlage von "Speichern"
        ein (form, entryList/put wie _alarm_put); der Aktiv-Stand bleibt, eine
        neue Weckzeit ist aktiv und beginnt mit der aktuellen Uhrzeit.
        Loeschen per entryList/delete/{entryID}, mit Rueckfrage."""
        c = self.controls.get(uuid or "", {})
        route = {"view": "alarmentry", "id": uuid, "entry": entry}
        roh = self._alarm_raw(c) if c.get("type") == "AlarmClock" else None
        if not roh or not roh[1]:
            return self._gone_view(route, _clean(c.get("name")), "Diese Weckzeit gibt es nicht mehr.")
        eintraege = roh[0]
        neu = entry in (None, "")
        if neu:
            n = 0
            while str(n) in eintraege:
                n += 1
            eid, jetzt = str(n), datetime.now()
            e = {"name": "Weckzeit", "isActive": True, "alarmTime": jetzt.hour * 3600 + jetzt.minute * 60}
        else:
            eid = str(entry)
            e = eintraege.get(eid)
            if e is None:
                return self._gone_view(route, _clean(c.get("name")), "Diese Weckzeit gibt es nicht mehr.")
        ua = c.get("uuidAction")
        name = _clean(str(e.get("name") or "")) or "Weckzeit"
        if e.get("nightLight") is True:
            tage = {"k": "chips", "name": "tage", "items": [
                {"v": 0, "label": "Einmalig", "on": not e.get("daily")},
                {"v": 1, "label": "Täglich", "on": bool(e.get("daily"))}]}
        else:
            tage = {"k": "chips", "name": "tage", "multi": True,
                    "items": self._alarm_mode_items(self._alarm_modes(e))}
        aktiv = 1 if e.get("isActive") else 0
        cells = []
        if not neu:
            cells.append({"label": "Löschen", "confirm": "Wirklich löschen?", "back": True,
                          "cmd": {"uuid": ua, "cmd": f"entryList/delete/{quote(eid, safe='')}"}})
        cells.append({"label": "Speichern", "back": True, "form": {
            "uuid": ua, "tmpl": f"entryList/put/{quote(eid, safe='')}/{{name}}/{{zeit}}/{aktiv}/{{tage}}"}})
        return {"t": "view", "title": name, "route": route, "blocks": [
            {"k": "title", "text": "Neue Weckzeit" if neu else name, "sub": _clean(c.get("name"))},
            {"k": "field", "name": "name", "label": "Name", "value": str(e.get("name") or name)},
            {"k": "timepick", "name": "zeit", "value": self._alarm_secs(e)},
            tage,
            {"k": "row", "cells": cells},
        ]}

    def _view_alarm_settings(self, uuid: str) -> dict:
        """Einstellungen eines Weckers laut Strukturdoku, jeweils fest, wenn
        die Logik sie vorgibt (details.*Connected): Schlummerdauer
        (setSnoozeDuration), maximale Weckdauer (setRingDuration), Vorweckzeit
        (setPrepDuration). Mit Touch Nightlight dazu Wecksound
        (setWakeAlarmSound, Auswahl aus details.wakeAlarmSounds), lauter
        werdend (setWakeAlarmSlopingOn), Signalton (setBeepOn), Lautstaerke
        (setWakeAlarmVolume) und Helligkeit (setBrightnessInactive/Active)."""
        c = self.controls.get(uuid or "", {})
        route = {"view": "alarmsettings", "id": uuid}
        if c.get("type") != "AlarmClock":
            return self._gone_view(route, "", "Diesen Wecker gibt es nicht mehr.")
        ua = c.get("uuidAction")
        det = c.get("details") or {}
        blocks = [{"k": "title", "text": "Einstellungen", "sub": _clean(c.get("name"))}]

        def stufe(label, wert, befehl, schritt, minimum, maximum, fmt, fest):
            if not isinstance(wert, (int, float)) or isinstance(wert, bool):
                return
            b = {"k": "stepper", "label": label, "value": int(wert), "fmt": fmt}
            if fest:
                b["sub"] = "von der Logik vorgegeben"
            else:
                b.update(step=schritt, min=minimum, cmd={"uuid": ua, "tmpl": befehl + "/{v}"})
                if maximum is not None:
                    b["max"] = maximum
            blocks.append(b)

        stufe("Schlummerdauer", self._state(c, "snoozeDuration"), "setSnoozeDuration", DAUER_SCHRITT,
              WECKER_SCHLUMMER_MIN, WECKER_SCHLUMMER_MAX, "dauer", bool(det.get("snoozeDurationConnected")))
        stufe("Maximale Weckdauer", self._state(c, "ringDuration"), "setRingDuration", DAUER_SCHRITT,
              DAUER_SCHRITT, None, "dauer", False)
        stufe("Vorweckzeit", self._state(c, "prepareDuration"), "setPrepDuration", DAUER_SCHRITT,
              0, None, "dauer", False)
        if self._state(c, "deviceState") in NIGHTLIGHT_DA:
            geraet = self._json_state(c, "deviceSettings")
            geraet = geraet if isinstance(geraet, dict) else {}
            ton = self._json_state(c, "wakeAlarmSoundSettings")
            ton = ton if isinstance(ton, dict) else {}
            blocks.append({"k": "head", "text": "Touch Nightlight"})
            sounds = [x for x in det.get("wakeAlarmSounds") or [] if isinstance(x, dict) and x.get("id") is not None]
            jetzt = next((x for x in sounds if str(x.get("id")) == str(ton.get("sound"))), None)
            name = _clean(str((jetzt or {}).get("name") or ""))
            zellen = []
            if sounds and not det.get("wakeAlarmSoundConnected"):
                zellen.append({"label": "Wecksound" + (": " + name if name else ""), "menu": [
                    {"label": _clean(str(x.get("name") or "")) or str(x.get("id")), "on": x is jetzt,
                     "cmd": {"uuid": ua, "cmd": f"setWakeAlarmSound/{x.get('id')}"}} for x in sounds]})
            elif name:
                blocks.append({"k": "status", "text": "Wecksound: " + name})
            if "isSloping" in ton and not det.get("wakeAlarmSlopingConnected"):
                an = bool(ton.get("isSloping"))
                zellen.append({"label": "Lauter werdend", "on": an,
                               "cmd": {"uuid": ua, "cmd": f"setWakeAlarmSlopingOn/{0 if an else 1}"}})
            if "beepUsed" in geraet:
                an = bool(geraet.get("beepUsed"))
                zellen.append({"label": "Signalton", "on": an,
                               "cmd": {"uuid": ua, "cmd": f"setBeepOn/{0 if an else 1}"}})
            if zellen:
                blocks.append({"k": "row", "wrap": True, "cells": zellen})
            stufe("Lautstärke", ton.get("volume"), "setWakeAlarmVolume", PROZENT_SCHRITT, WECKER_LAUT_MIN, 100,
                  "prozent", bool(det.get("wakeAlarmVolumeConnected")))
            stufe("Helligkeit inaktiv", geraet.get("brightInactive"), "setBrightnessInactive", PROZENT_SCHRITT,
                  0, 100, "prozent", bool(det.get("brightInactiveConnected")))
            stufe("Helligkeit aktiv", geraet.get("brightActive"), "setBrightnessActive", PROZENT_SCHRITT,
                  0, 100, "prozent", bool(det.get("brightActiveConnected")))
        return {"t": "view", "title": "Einstellungen", "route": route, "blocks": blocks}

    def _bell_events(self, c: dict) -> list[str]:
        """Zeitstempel der verpassten Klingeln, neueste zuerst. Laut
        Strukturdoku State lastBellEvents: JJJJMMTTHHMMSS, mit | getrennt."""
        txt = unquote(str(self._state(c, "lastBellEvents") or ""))
        return sorted({t.strip() for t in txt.split("|") if _BELL_TS.fullmatch(t.strip())}, reverse=True)

    def _intercom_video_block(self, uuid: str, c: dict) -> dict:
        """Video der Intercom-Seite: eine in LoxPanel eingetragene Kamera oder
        die des Miniservers (intercom_video). Solange offen ist, ob er eine
        nennt, steht das Video schon da: /mjpeg fragt ihn, und die Seite zeigt
        danach Bild oder Grund."""
        ent = self.intercom_cfg.get(uuid)
        eigene = ent.get("url") if isinstance(ent, dict) else ent
        cam = self.ms_video.get(uuid)
        if (isinstance(eigene, str) and eigene.strip()) or \
                (c.get("securedDetails") and (cam is None or cam.get("url"))):
            return {"k": "video", "src": f"/mjpeg?id={quote(uuid)}"}
        return {"k": "status", "text": (cam or {}).get("grund") or KEIN_VIDEO}

    def _intercom_zustand(self, c: dict) -> str:
        """Hinweis zum Geraetezustand einer IntercomV2 (deviceState, Strukturdoku
        17.0) wie "Startet neu"; leer, wenn sie bereit ist, ohne State und bei v1."""
        if c.get("type") != "IntercomV2":
            return ""
        try:
            return INTERCOM_V2_ZUSTAND.get(int(float(self._state(c, "deviceState"))), "")
        except (TypeError, ValueError):
            return ""

    def _intercom_antworten(self, c: dict) -> list[tuple[int, str]]:
        """Antworten einer IntercomV2 als (Index, Text). Laut Strukturdoku 17.0
        ist der State answers eine Liste, playTts/{idx} spielt die mit dem Index
        an der Tuer ab, setAnswers/{answer0}/{answer1}/... setzt sie als Texte.
        Der Index bleibt der in der Liste, auch wenn ein Eintrag leer ist."""
        liste = self._json_state(c, "answers")
        if not isinstance(liste, list):
            return []
        return [(i, a.strip()) for i, a in enumerate(liste) if isinstance(a, str) and a.strip()]

    @staticmethod
    def _bell_text(ts: str, heute: date | None = None) -> str:
        """Zeitpunkt einer Klingel: 'Heute 07:49', 'Gestern 07:49', 'Mo 07:49'
        (die letzte Woche), sonst mit Datum ('01.10. 07:49', aus einem anderen
        Jahr '01.10.2025 07:49'). Wanduhr des Miniservers, wie geliefert."""
        try:
            dt = datetime.strptime(ts, "%Y%m%d%H%M%S")
        except ValueError:
            return ts
        heute = heute or datetime.now().date()
        tage = (heute - dt.date()).days
        hm = dt.strftime("%H:%M")
        if tage == 0:
            return "Heute " + hm
        if tage == 1:
            return "Gestern " + hm
        if 2 <= tage <= 6:
            return STAT_WEEKDAYS[dt.weekday()] + " " + hm
        return dt.strftime("%d.%m. " if dt.year == heute.year else "%d.%m.%Y ") + hm

    def _view_bells(self, uuid: str) -> dict:
        """Verpasste Klingeln einer Tuersprechstelle, neueste zuerst. Mit
        details.lastBellEventImages speichert der Miniserver ein Bild je
        Klingel; die Visu holt es ueber /bellimg (camimage)."""
        c = self.controls.get(uuid or "", {})
        route = {"view": "bells", "id": uuid}
        if c.get("type") not in INTERCOM_TYPES:
            return self._gone_view(route, "", "Diese Türsprechstelle gibt es nicht mehr.")
        evs = self._bell_events(c)
        blocks = [{"k": "title", "text": "Verpasste Klingeln", "sub": _clean(c.get("name"))}]
        if not evs:
            blocks.append({"k": "status", "text": "Keine verpassten Klingeln"})
        elif (c.get("details") or {}).get("lastBellEventImages"):
            blocks.append({"k": "gallery", "items": [
                {"src": f"/bellimg?id={quote(uuid, safe='')}&ts={ts}", "label": self._bell_text(ts)}
                for ts in evs]})
        else:
            blocks += [{"k": "status", "text": self._bell_text(ts)} for ts in evs]
        return {"t": "view", "title": "Verpasste Klingeln", "route": route, "blocks": blocks}

    def _big_view(self, uuid: str, icon: str, big: str, sub: str = "", tone=None) -> dict:
        """Grosse 1/1-Wertseite fuer reine Status-Bausteine. Das Hero-Icon ist
        dasselbe wie auf der Kachel vorne: Loxone-eigenes Icon, falls vorhanden,
        sonst das Builtin-Icon (`icon`)."""
        c = self.controls.get(uuid, {})
        hero = {"k": "hero", "icon": icon}
        iu = self._control_icon_url(c)
        if iu:
            hero["iconUrl"] = iu
        blk = {"k": "big", "text": big}
        if tone:
            blk["tone"] = tone
        blocks = [hero, blk]
        if sub:
            blocks.append({"k": "status", "text": sub})
        return {"t": "view", "title": _clean(c.get("name")),
                "route": {"view": "control", "id": uuid}, "blocks": blocks}

    @staticmethod
    def _stat_months(t0: int, t1: int) -> list[str]:
        """Monatsschluessel JJJJMM, die das Fenster [t0, t1] (Wanduhr-Sekunden) beruehrt."""
        a = datetime(1970, 1, 1) + timedelta(seconds=t0)
        b = datetime(1970, 1, 1) + timedelta(seconds=t1)
        y, m, out = a.year, a.month, []
        while (y, m) <= (b.year, b.month):
            out.append(f"{y:04d}{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out

    @staticmethod
    def _stat_edges(rng: str, t1: int) -> list[int]:
        """Abschnittsgrenzen der Verbrauchsbalken: bei 24 h je volle Stunde, sonst
        je Tag ab Mitternacht. Der letzte Abschnitt laeuft bis jetzt."""
        if rng == "24h":
            step, n = 3600, 24
        else:
            step, n = 86400, STAT_RANGES[rng][1] // 86400
        start = t1 - t1 % step - (n - 1) * step
        return [start + k * step for k in range(n)] + [t1 + 1]

    def _stat_rows(self, ua: str, t0: int, t1: int) -> tuple[list, bool, bool]:
        """Zeilen im Fenster aus stat_cache, vorneweg der letzte Stand davor (falls
        bekannt). Fehlende oder noch wachsende Monate werden im Hintergrund
        nachgeladen. -> (zeilen, laedt_noch, abruffehler)"""
        allrows, loading, error = [], False, False
        now = time.monotonic()
        for ym in self._stat_months(t0, t1):
            key = (ua, ym)
            ent = self.stat_cache.get(key)
            if ent is None:
                want = True
            elif ent[2] is None:
                want = now - ent[0] >= STAT_RETRY
            else:
                want = ent[1] <= ym and now - ent[0] >= STAT_REFRESH
            if want and key not in self.stat_pending:
                self.stat_pending.add(key)
                self._spawn(self._stat_load(ua, ym))
            if ent is None:
                loading = True
            elif ent[2] is None:
                error = True
            else:
                allrows.extend(ent[2])
        allrows.sort(key=lambda r: r[0])
        before = [r for r in allrows if r[0] < t0]
        return ([before[-1]] if before else []) + [r for r in allrows if t0 <= r[0] <= t1], loading, error

    def _stat2_rows(self, ua: str, gid: str, out: str, rng: str, t0: int, t1: int) -> tuple[list, bool, bool]:
        """Wie _stat_rows, fuer einen statisticV2-Ausgang: Zeilen im Fenster, vorneweg
        der letzte Stand davor; fehlend oder aelter als STAT_REFRESH -> im
        Hintergrund neu holen. -> (zeilen, laedt_noch, abruffehler)"""
        key = (ua, gid, out, rng)
        ent = self.stat2_cache.get(key)
        age = time.monotonic() - ent[0] if ent else 0.0
        if ent is None or age >= (STAT_RETRY if ent[1] is None else STAT_REFRESH):
            if key not in self.stat_pending:
                self.stat_pending.add(key)
                self._spawn(self._stat2_load(key, ua, gid, out, STAT_RANGES[rng][1]))
        if ent is None:
            return [], True, False
        if ent[1] is None:
            return [], False, True
        before = [r for r in ent[1] if r[0] < t0]
        return ([before[-1]] if before else []) + [r for r in ent[1] if t0 <= r[0] <= t1], False, False

    @staticmethod
    def _stat_series_defs(c: dict) -> list:
        """Alle aufgezeichneten Reihen eines Bausteins als (name, art, stellen,
        einheit, quelle). `statistic`: je Ausgang, Art aus visuType, Quelle
        ("v1", index in der Monatsdatei). `statisticV2`: je Datenpunkt einer
        Gruppe, `accumulated` = Zaehlerstand, Quelle ("v2", gruppe, ausgang).
        Gleiche Titel in einer Gruppe (Netz: zweimal "Zaehlerstand") bekommen
        den Ausgangsnamen dazu."""
        defs = []
        for i, o in enumerate((c.get("statistic") or {}).get("outputs") or []):
            if isinstance(o, dict):
                dec, unit = _stat_fmt(o.get("format"))
                defs.append((_clean(o.get("name")) or f"Wert {i + 1}",
                             STAT_KIND.get(o.get("visuType"), "line"), dec, unit, ("v1", i)))
        for g in (c.get("statisticV2") or {}).get("groups") or []:
            if not isinstance(g, dict):
                continue
            dps = [d for d in (g.get("dataPoints") or []) if isinstance(d, dict) and d.get("output")]
            titles = [d.get("title") for d in dps]
            for d in dps:
                dec, unit = _stat_fmt(d.get("format"))
                name = _clean(d.get("title")) or d["output"]
                if titles.count(d.get("title")) > 1:
                    name = f"{name} · {d['output']}"
                defs.append((name, "counter" if g.get("accumulated") else "line", dec, unit,
                             ("v2", str(g.get("id")), str(d["output"]))))
        return defs

    def _stat_blocks(self, c: dict, rng: str) -> list:
        """Diagramm-Bloecke fuer einen Baustein mit `statistic` oder `statisticV2`.
        Reihen gleicher Art und Einheit teilen sich ein Diagramm (zwei Grillfuehler,
        Netz-Bezug und -Einspeisung), sonst je eines (Zaehler: Leistung als Linie,
        Verbrauch als Balken)."""
        defs = self._stat_series_defs(c)
        ua = c.get("uuidAction")
        if not (ua and defs):
            return []
        now = calendar.timegm(datetime.now().timetuple())
        t1 = now - now % 60                    # Fenster rueckt je Minute vor
        mkey = (ua, rng, t1, self.stat_gen)
        if mkey in self.stat_memo:
            return self.stat_memo[mkey]
        t0 = t1 - STAT_RANGES[rng][1]
        v1 = None                              # Monatsdateien: eine Abfrage fuer alle Ausgaenge
        groups: dict[tuple[str, str], list] = {}
        for d in defs:
            groups.setdefault((d[1], d[3]), []).append(d)
        blocks = []
        for kind, unit in groups:
            edges = self._stat_edges(rng, t1) if kind == "counter" else None
            series, any_rows, loading, error = [], False, False, False
            for name, _kind, dec, _unit, src in groups[(kind, unit)]:
                if src[0] == "v1":
                    if v1 is None:
                        v1 = self._stat_rows(ua, t0, t1)
                    rows, ld, er = v1
                    i = src[1]
                    pts = [(r[0], r[1][i]) for r in rows if i < len(r[1]) and r[1][i] is not None]
                else:
                    rows, ld, er = self._stat2_rows(ua, src[1], src[2], rng, t0, t1)
                    pts = [(r[0], r[1][0]) for r in rows if r[1] and r[1][0] is not None]
                any_rows, loading, error = any_rows or bool(rows), loading or ld, error or er
                if kind == "counter":
                    pts = _stat_bars(pts, edges)
                else:
                    if pts and pts[0][0] < t0:
                        pts[0] = (t0, pts[0][1])   # letzter Stand vor dem Fenster = Startwert
                    pts = _stat_thin(pts, t0, t1, STAT_MAX_POINTS, kind == "digital")
                series.append({"name": name, "dec": dec,
                               "pts": [[int(t), round(v, dec + 2)] for t, v in pts]})
            has = any_rows if kind == "counter" else any(s["pts"] for s in series)
            blk = {"k": "chart", "kind": kind, "unit": unit, "series": series,
                   "t0": edges[0] if edges else t0, "t1": t1,
                   "state": "ok" if has else ("loading" if loading else ("error" if error else "empty"))}
            if not blocks:                     # Zeitraum-Wahl nur am ersten Diagramm der Seite
                blk.update(range=rng, ranges=[[k, v[0]] for k, v in STAT_RANGES.items()])
            blocks.append(blk)
        if len(self.stat_memo) > 64:
            self.stat_memo = {}
        self.stat_memo[mkey] = blocks
        return blocks

    def chart_blocks(self, uuid: str, rng: str | None = None) -> dict | None:
        """Inhalt der Verlaufs-Pane im Split-Layout (panes "chart:<uuid>"): Name,
        aktueller Wert wie auf der Detailseite und die Diagramme aus
        _stat_blocks (dieselben Abrufe, Caches und Zustaende). None, wenn der
        Baustein fehlt oder nichts aufzeichnet."""
        c = self.controls.get(uuid)
        if not c or not (c.get("statistic") or c.get("statisticV2")):
            return None
        rng = rng if rng in STAT_RANGES else STAT_DEFAULT_RANGE
        v = self._view_control_inner(uuid)
        big = next((b.get("text") or "" for b in v.get("blocks") or [] if b.get("k") == "big"), "")
        return {"control": uuid, "name": _clean(c.get("name")), "value": big,
                "range": rng, "blocks": self._stat_blocks(c, rng)}

    def chart_stack(self, uuids, rng: str | None = None) -> dict:
        """Mehrere Verlaufs-Bausteine gestapelt fuer die Verlaufs-Pane
        (panes "chart:<uuid>,<uuid>,..."). Je Baustein Name, aktueller Wert und
        Diagramme (chart_blocks); der Zeitraum gilt fuer den ganzen Stapel. Die
        Zeitraum-Knoepfe traegt die Pane nur einmal oben (`ranges`), nicht jeder
        Baustein — die Visu blendet die Knoepfe der einzelnen Bloecke daher aus.
        Unbekannte/aufzeichnungslose Bausteine fallen still weg."""
        rng = rng if rng in STAT_RANGES else STAT_DEFAULT_RANGE
        charts = []
        for u in list(uuids or [])[:SV_STATUS_MAX]:
            cb = self.chart_blocks(u, rng)
            if cb is not None:
                charts.append(cb)
        return {"controls": [c["control"] for c in charts], "range": rng,
                "ranges": [[k, v[0]] for k, v in STAT_RANGES.items()],
                "charts": charts}

    def _stat_primary(self, c: dict) -> tuple | None:
        """Die Reihe, die eine Kachel zeigt: die erste Linie, sonst die erste Reihe."""
        defs = self._stat_series_defs(c)
        return next((d for d in defs if d[1] == "line"), defs[0] if defs else None)

    def _stat_raw(self, c: dict, d: tuple, rng: str, t0: int, t1: int) -> tuple[list, bool, bool]:
        """Rohpunkte einer Reihe im Fenster, vorneweg der letzte Stand davor, aus
        denselben Caches wie die Diagramme. -> (punkte, laedt_noch, abruffehler)"""
        ua, src = c.get("uuidAction"), d[4]
        if src[0] == "v1":
            rows, ld, er = self._stat_rows(ua, t0, t1)
            i = src[1]
            return [(r[0], r[1][i]) for r in rows if i < len(r[1]) and r[1][i] is not None], ld, er
        rows, ld, er = self._stat2_rows(ua, src[1], src[2], rng, t0, t1)
        return [(r[0], r[1][0]) for r in rows if r[1] and r[1][0] is not None], ld, er

    @staticmethod
    def _stat_dur(sec: float) -> str:
        """Dauer als "3 h 20 min" bzw. "40 min"."""
        h, m = int(sec // 3600), int(round(sec % 3600 / 60))
        if m == 60:
            h, m = h + 1, 0
        return f"{h} h" + (f" {m} min" if m else "") if h else f"{m} min"

    def _stat_spark(self, c: dict, rng: str, style: str = "trend") -> dict | None:
        """Mini-Verlauf fuer eine Kachel (tiles.<uuid>.chart/.chartStyle).

        trend    Verlauf im gewaehlten Zeitraum: Linie mit Tiefst-/Hoechstwert,
                 Digitalwert als Stufen, Zaehlerstand als Verbrauchsbalken.
        pattern  Tagesmuster: 7 Tage x 24 Stunden, je Stunde der zeitgewichtete
                 Mittelwert (Digital: Ein-Anteil, Zaehler: Verbrauch der Stunde).
        span     Tagesspanne (nur Linien): je Tag Tiefst-, Hoechst- und Mittelwert.

        `badge` ist die kurze Angabe im Kopf der Kachel; die Visu zeigt sie nur an."""
        d = self._stat_primary(c)
        ua = c.get("uuidAction")
        if not (d and ua):
            return None
        name, kind, dec, unit, src = d
        if style == "span" and kind != "line":
            style = "trend"
        now = calendar.timegm(datetime.now().timetuple())
        t1 = now - now % 60
        mkey = ("spark", ua, rng, style, t1, self.stat_gen)
        if mkey in self.stat_memo:
            return self.stat_memo[mkey]
        fmt = f"%.{dec}f{unit}"
        out: dict | None = None
        if style == "trend":
            blocks = self._stat_blocks(c, rng)
            b = next((x for x in blocks if x.get("kind") == kind and x.get("unit") == unit), None)
            if b is None:
                return None
            se = next((x for x in b.get("series") or [] if x.get("name") == name), (b.get("series") or [{}])[0])
            full = [tuple(p) for p in se.get("pts") or []]
            out = {"style": "trend", "kind": kind, "state": b.get("state"), "t0": b.get("t0"),
                   "t1": b.get("t1"), "dec": dec}
            if kind == "counter":
                out["pts"] = [list(p) for p in full]
                if full:
                    out["badge"] = "Σ " + self._fmt_num(sum(v for _, v in full), fmt)
            else:
                out["pts"] = [[int(t), round(v, dec + 2)]
                              for t, v in _stat_thin(full, b["t0"], b["t1"], 48, kind == "digital")]
                if full and kind == "line":
                    lo, hi = min(full, key=lambda p: p[1]), max(full, key=lambda p: p[1])
                    out["lo"], out["hi"] = [int(lo[0]), lo[1]], [int(hi[0]), hi[1]]
                    ago = [v for t, v in full if t <= t1 - 86400]
                    if ago:
                        delta = full[-1][1] - ago[-1]
                        step = 10 ** -dec / 2
                        arrow = "▲" if delta >= step else ("▼" if delta <= -step else "=")
                        out["badge"] = f"{arrow} {self._fmt_num(abs(delta), fmt)} in 24 h"
                elif full:
                    t0 = b["t0"]
                    raw, _ld, _er = self._stat_raw(c, d, rng, t0, t1)
                    share = _stat_buckets(raw, [t0, t1], t1)[0]
                    if share is not None:
                        out["badge"] = "Ein " + self._stat_dur(share * (t1 - t0))
        else:
            start = t1 - t1 % 86400 - 6 * 86400        # Mitternacht vor 6 Tagen
            raw, loading, error = self._stat_raw(c, d, "7d", start, t1)
            days = [STAT_WEEKDAYS[((start // 86400) + i + 3) % 7] for i in range(7)]   # 1.1.1970 = Do
            state = "ok" if raw else ("loading" if loading else ("error" if error else "empty"))
            out = {"style": style, "kind": kind, "state": state, "dec": dec, "days": days}
            if style == "pattern":
                edges = [start + h * 3600 for h in range(7 * 24 + 1)]
                if kind == "counter":
                    cells = [None if a >= t1 else v for (a, v) in _stat_bars(raw, edges)]
                else:
                    cells = _stat_buckets(raw, edges, t1)
                out["cells"] = [None if v is None else round(v, dec + 2) for v in cells]
                vals = [v for v in cells if v is not None]
                if vals and kind == "counter":
                    out["badge"] = "7 Tage · Σ " + self._fmt_num(sum(vals), fmt)
                elif vals and kind == "line":
                    out["badge"] = "7 Tage · max " + self._fmt_num(max(vals), fmt)
                elif vals:
                    out["badge"] = "7 Tage"
            else:
                edges = [start + i * 86400 for i in range(8)]
                rngs = _stat_day_range(raw, edges, t1)
                avgs = _stat_buckets(raw, edges, t1)
                out["spans"] = [None if r is None else [round(r[0], dec + 2), round(r[1], dec + 2),
                                                        None if a is None else round(a, dec + 2)]
                                for r, a in zip(rngs, avgs)]
                if rngs[-1] is not None:
                    lo, hi = rngs[-1]
                    out["badge"] = "heute " + self._fmt_num(lo, f"%.{dec}f") + "–" + self._fmt_num(hi, fmt)
        if len(self.stat_memo) > 64:
            self.stat_memo = {}
        self.stat_memo[mkey] = out
        return out

    def _irr_zones(self, c: dict) -> list[dict]:
        """Zonen der Bewaesserung aus dem State zones (JSON, laut Strukturdoku
        [{id, name, duration, setByLogic}], id ab 0), nach id sortiert ->
        [{id, name, duration (Sekunden oder None), logic}]. Eine Zone ohne
        Nummer faellt weg: ohne sie gaebe es keinen Befehl fuer sie."""
        data = self._json_state(c, "zones")
        seq = data.values() if isinstance(data, dict) else (data if isinstance(data, list) else [])
        out = []
        for z in seq:
            if not isinstance(z, dict):
                continue
            try:
                zid = int(z.get("id"))
            except (TypeError, ValueError):
                continue
            try:
                dauer = int(round(float(z.get("duration"))))
            except (TypeError, ValueError):
                dauer = None
            out.append({"id": zid, "name": _clean(str(z.get("name") or "")) or f"Zone {zid + 1}",
                        "duration": dauer, "logic": bool(z.get("setByLogic"))})
        return sorted(out, key=lambda z: z["id"])

    def _irr_current(self, c: dict) -> int | None:
        """currentZone als Zahl: id der laufenden Zone oder IRR_ALLE_AKTIV;
        None, wenn keine laeuft (IRR_AUS) oder der Wert fehlt."""
        try:
            cur = int(float(self._state(c, "currentZone")))
        except (TypeError, ValueError):
            return None
        return None if cur == IRR_AUS else cur

    def _irr_running(self, c: dict) -> bool:
        """Bewaesserung laeuft: State active (neuere Firmware) oder laut
        Strukturdoku currentZone ungleich -1."""
        return bool(self._state(c, "active")) or self._irr_current(c) is not None

    def _irrigation_zone_name(self, c: dict) -> str:
        """Name der laufenden Zone (currentZone = id aus zones), 'Alle Zonen'
        bei IRR_ALLE_AKTIV, sonst leer."""
        cur = self._irr_current(c)
        if cur is None:
            return ""
        if cur == IRR_ALLE_AKTIV:
            return "Alle Zonen"
        for z in self._irr_zones(c):
            if z["id"] == cur:
                return z["name"]
        return f"Zone {cur + 1}"

    def _steak_temps(self, c: dict) -> list[tuple[str, float]]:
        """Fuehler-Temperaturen des Grillthermometers aus currentTemperatures
        (Liste von Zahlen oder Objekten mit name/value)."""
        data = self._json_state(c, "currentTemperatures")
        out = []
        for label, e in self._named_items(data):
            v = e.get("value", e.get("temperature", e.get("temp")))
            try:
                out.append((label if not label.isdigit() else f"Fühler {label}", float(v)))
            except (TypeError, ValueError):
                continue
        return out

    # ---- Anlagenschema (SystemScheme) -----------------------------------
    def _resolve_control(self, uuid: str | None) -> dict | None:
        """Baustein zu einer UUID liefern – auch wenn es ein Subcontrol ist.
        self.controls enthaelt nur die Top-Level-Bausteine; die Referenzen im
        Anlagenschema zeigen teils auf Subcontrols (z.B. InfoOnly eines Oelkessels)."""
        if not uuid:
            return None
        c = self.controls.get(uuid)
        if c:
            return c
        for pc in self.controls.values():
            sub = (pc.get("subControls") or {}).get(uuid)
            if sub:
                return sub
        return None

    def _scheme_value(self, c: dict | None) -> dict:
        """Kompakter Anzeige-Wert eines im Schema referenzierten Bausteins:
        {text, on, tone}. Deckt die im Anlagenschema ueblichen Typen ab
        (Slider/InfoOnlyAnalog = Zahl, InfoOnlyDigital = Ein/Aus, TextState)."""
        if not c:
            return {"text": "", "on": False}
        t = c.get("type")
        det = c.get("details") or {}
        if t in ("Slider", "InfoOnlyAnalog", "Meter"):
            return {"text": self._fmt_num(self._state(c, "value") if t != "Meter"
                                          else self._state(c, "actual"),
                                          det.get("format", "%.1f")), "on": False}
        if t == "InfoOnlyDigital":
            on = bool(self._state(c, "active"))
            txt = det.get("text") or {}
            return {"text": (txt.get("on") if on else txt.get("off"))
                    or ("Ein" if on else "Aus"), "on": on}
        if t in ("TextState", "InfoOnlyText"):
            return {"text": str(self._state(c, "textAndIcon")
                               or self._state(c, "text") or ""), "on": False}
        # Fallback: erster vorhandener State als Text.
        for name in (c.get("states") or {}):
            v = self._state(c, name)
            if v not in (None, ""):
                return {"text": str(v), "on": False}
        return {"text": "", "on": False}

    def _view_scheme(self, uuid: str, c: dict, route: dict) -> dict:
        """Anlagenschema als Ansicht: Hintergrundbild vom Miniserver (ueber den
        /icon-Proxy) plus die Live-Werte der referenzierten Bausteine als Overlay
        an ihren Positionen. schemeSize ist das Original-Koordinatensystem, in dem
        pos/size angegeben sind – der Client skaliert es auf die Panelbreite."""
        det = c.get("details") or {}
        sz = det.get("schemeSize") or {}
        img = det.get("imagePath")
        # /icon liefert .png vom Miniserver (mit JWT); &v busted den Browser-Cache
        # bei geaenderter imageVersion. Hinweis: der Server-seitige icon_cache wird
        # per Pfad gehalten – aendert sich das Bild im Config, ggf. Server neu laden.
        src = None
        if img:
            src = "/icon?p=" + quote(img, safe="")
            if det.get("imageVersion"):
                src += "&v=" + str(det["imageVersion"])
        items = []
        for ref in (det.get("controlReferences") or []):
            rc = self._resolve_control(ref.get("uuidAction"))
            if not rc:
                continue
            val = self._scheme_value(rc)
            pos = ref.get("pos") or {}
            size = ref.get("size") or {}
            entry = {
                "x": pos.get("x", 0), "y": pos.get("y", 0),
                "w": size.get("width"), "h": size.get("height"),
                "text": (ref.get("text") or "") + val["text"],
                "on": val["on"],
            }
            # Bedienbare Referenzen (actionsVisible) sind antippbar -> Detailansicht
            # des Bausteins. Nur fuer Top-Level-Bausteine, die eine eigene View haben.
            ru = ref.get("uuidAction")
            if ref.get("actionsVisible") and ru in self.controls:
                entry["nav"] = {"view": "control", "id": ru}
            items.append(entry)
        return {"t": "view", "title": _clean(c.get("name")), "route": route,
                "layout": "scheme", "image": src,
                "sw": sz.get("width") or 1300, "sh": sz.get("height") or 866,
                "items": items}

    def _view_control(self, uuid: str, rng: str | None = None, prof: dict | None = None) -> dict:
        v = self._view_control_inner(uuid)
        c = self.controls.get(uuid, {})
        # Verlaufs-Diagramme unter die Detailseite haengen, wenn der Baustein eine
        # Aufzeichnung hat. Nur bei Block-Seiten; die Route traegt dann den Zeitraum.
        if (c.get("statistic") or c.get("statisticV2")) and isinstance(v.get("blocks"), list):
            rng = rng if rng in STAT_RANGES else STAT_DEFAULT_RANGE
            charts = self._stat_blocks(c, rng)
            if charts:
                v["blocks"] = v["blocks"] + charts
                v["route"] = dict(v.get("route") or {}, range=rng)
        # Verlinkte Objekte (Structure File "links": Bausteine, die in Loxone
        # Config am Baustein verlinkt sind, etwa die Abholtermine am
        # Muell-Status): unter die Detailseite als Zeile tippbarer Zellen,
        # wie in der Loxone-App. Jede Zelle zeigt Name und Zustand, ein Tipp
        # oeffnet die Detailseite des Ziels oder schaltet es (Kacheln, die
        # direkt schalten). Nur bekannte, auf dem Panel nicht ausgeblendete
        # Bausteine; nur Block-Seiten.
        if isinstance(v.get("blocks"), list):
            links = self._link_blocks(c, uuid, prof)
            if links:
                v["blocks"] = v["blocks"] + links
        return v

    def _link_blocks(self, c: dict, uuid: str, prof: dict | None = None) -> list:
        """Blocks fuer die verlinkten Objekte eines Bausteins: Ueberschrift und
        eine umbrechende Zeile mit einer Zelle je Ziel. Leer, wenn der
        Baustein keine (bekannten) Links hat oder nur auf sich selbst zeigt.
        Auf dem Panel ausgeblendete Ziele (hide) bleiben weg wie ueberall
        sonst; ein gesichertes Ziel (Visu-PIN) traegt secured an der Zelle,
        die Visu fragt dann vor dem Schalten die PIN ab (Codex-Befunde)."""
        ziele = [u for u in (c.get("links") or []) if isinstance(u, str)
                 and u != uuid and u in self.controls and self._shown(u, prof)]
        if not ziele:
            return []
        cells = []
        for u in dict.fromkeys(ziele):   # Reihenfolge wie in Loxone Config, ohne Dubletten
            it = self._control_item(u, show_room=True)
            label = it.get("label") or "?"
            if it.get("sublabel"):
                label = f"{label} · {it['sublabel']}"
            cell = {"label": label, "on": bool(it.get("on"))}
            if it.get("nav"):
                cell["nav"] = it["nav"]
            elif it.get("cmd"):
                cell["cmd"] = it["cmd"]
                if it.get("secured"):
                    cell["secured"] = True
            else:
                cell["nav"] = {"view": "control", "id": u}
            cells.append(cell)
        return [{"k": "head", "text": "Verlinkte Objekte"},
                {"k": "row", "id": f"links:{uuid}", "wrap": True, "cells": cells}]

    def _view_control_inner(self, uuid: str) -> dict:
        c = self.controls.get(uuid, {})
        t = c.get("type")
        route = {"view": "control", "id": uuid}
        fn = bausteine.detail_fuer(t)
        if fn:
            return fn(self, uuid, c, route)
        return {"t": "view", "title": _clean(c.get("name")), "route": route,
                "items": [self._control_item(uuid)]}

    def render(self, route: dict, prof: dict | None = None) -> dict:
        out = self._render_seite(route, prof)
        # Seiten, auf denen Gesten wirken: was zwei Finger hier tun (Hinweis-Symbol)
        if (route or {}).get("view", "tab") in ("tab", "group"):
            hilfe = self.gesten_hilfe(route, prof)
            if hilfe:
                out["gestenHilfe"] = hilfe
        # Jede Seite eines gesicherten Bausteins, auch seine Unterseiten (Zone,
        # Weckzeit, Musikauswahl ...): die Visu fragt vor jedem Befehl die
        # Visu-PIN ab. Gruppe und Tab nicht - dort zaehlt die einzelne Kachel.
        if (out.get("route") or {}).get("view") not in ("group", "tab") \
                and self._gesichert((route or {}).get("id")):
            out["secured"] = True
        return out

    def _render_seite(self, route: dict, prof: dict | None = None) -> dict:
        v = (route or {}).get("view", "tab")
        if v == "group":
            return self._view_group(route, prof)
        if v == "control":
            return self._view_control(route.get("id"), route.get("range"), prof)
        if v == "sources":
            return self._view_sources(route.get("id"))
        if v == "irrzone":
            return self._view_irr_zone(route.get("id"), route.get("zone"))
        if v == "alarmentry":
            return self._view_alarm_entry(route.get("id"), route.get("entry"))
        if v == "alarmsettings":
            return self._view_alarm_settings(route.get("id"))
        if v == "bells":
            return self._view_bells(route.get("id"))
        if v == "tab" and self._haus_seite((route or {}).get("tab"), prof):
            # Hausuebersicht braucht die ganze Route (gewaehlte Zone, Unterseite)
            return self._view_haus(route, prof)
        return self._view_tab(route.get("tab", "favoriten"), prof)

    def _gesichert(self, uuid) -> bool:
        """Baustein mit Visu-Passwort (isSecured): Befehle nur mit PIN (sps/ios)."""
        return isinstance(uuid, str) and bool((self.controls.get(uuid) or {}).get("isSecured"))

    def _pane_msg(self, art: str, uuid: str, blocks: list) -> dict:
        """{t:"player"|"camera"} fuer Player- bzw. Kamera-Bereich. Gesichert wie
        die Detailseite derselben Zone bzw. Intercom, sonst bedienten
        Lautstaerke, Transport und Tueroeffner sie ohne PIN."""
        m = {"t": art, "blocks": blocks}
        if self._gesichert(uuid):
            m["secured"] = True
        return m

    async def audio_events_task(self) -> None:
        """Verwaltet je Audioserver (aus /mediaServer der Struktur) einen
        Gen-2-Event-Client (WS 7091). Startet neue Server, stoppt verschwundene;
        reagiert so auf Struktur-/Config-Aenderungen. `enabled` (audiometa) ist
        der Master-Schalter. Adressen kommen automatisch aus der Struktur —
        keine IP-Eingabe noetig."""
        while True:
            enabled = (self.audiometa_cfg or {}).get("enabled", True)
            want = set()
            if enabled:
                for hp in self.mediaservers.values():
                    host = (hp or "").split(":")[0].strip()
                    if host:
                        want.add(host)
            for host in want:
                if host not in self.audio_clients:
                    am = self.audiometa_cfg or {}
                    cl = AudioEventClient(host, 7091, user=self.user,
                                          token_provider=lambda: self.jwt,
                                          neu_versuch_s=_audiometa_sekunden(
                                              am, "retry_interval", AudioEventClient.NEU_VERSUCH_S),
                                          pruef_zeitlimit_s=_audiometa_sekunden(
                                              am, "response_timeout", AudioEventClient.PRUEF_ZEITLIMIT_S))
                    self.audio_clients[host] = cl
                    asyncio.create_task(self._run_audio_client(host, cl))
                    log.info("Audioserver-Event-Client gestartet: %s", host)
            for host in list(self.audio_clients):
                if host not in want:
                    cl = self.audio_clients.pop(host, None)
                    if cl:
                        await cl.close()
                        log.info("Audioserver-Event-Client gestoppt: %s", host)
            await asyncio.sleep(10)

    async def _run_audio_client(self, host: str, cl: AudioEventClient) -> None:
        try:
            await cl.run(self._mark_dirty)
        except Exception as err:
            log.debug("audio client %s: %s", host, err)
        finally:
            if self.audio_clients.get(host) is cl:
                self.audio_clients.pop(host, None)

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _audio_client_for(self, c: dict):
        """(Event-Client, playerid) zur AudioZoneV2-Zone `c` — via
        details.server -> mediaServer-Host und details.playerid. (None, None),
        wenn kein passender Client laeuft."""
        det = c.get("details") or {}
        pid = det.get("playerid")
        hp = self.mediaservers.get(det.get("server"))
        if pid is None or not hp:
            return None, None
        host = hp.split(":")[0].strip()
        return self.audio_clients.get(host), pid

    def _audio_cover(self, c: dict) -> str | None:
        """Bild einer Audiozone als fertige /cover-URL, None ohne Bild - fuer
        Detailseite und breite Kachel dasselbe. AudioZone (Gen1): der State
        "cover". AudioZoneV2: der Audioserver (oder Sonn, wo Loxone leer ist)
        liefert bei Radio oft nur das Sender-Logo; laeuft ein echter Titel,
        gilt das passende Album-Cover (_song_cover), sonst das Logo."""
        t = c.get("type")
        cover = self._state(c, "cover")
        if t == "AudioZoneV2":
            sm = self._sonn_for(c)
            playing = self._state(c, "playState") == 2 or bool(sm and sm.get("playing"))
            title = self._song(c) or (sm.get("title") if sm else "") or ""
            cover = cover or (sm.get("cover") if sm else None)
            art = (self._text(c, "artist") or (sm.get("artist") if sm else "") or "").strip()
            if playing and title and art:
                dyn = self._song_cover(art, title)
                if dyn:
                    return dyn   # schon eine fertige /cover-URL
        elif t != "AudioZone":
            return None
        return ("/cover?u=" + quote(str(cover), safe="")) if cover else None

    def _sonn_for(self, c: dict) -> dict | None:
        """Now-Playing zur Zone `c` aus dem passenden Audioserver-Event-Client."""
        cl, pid = self._audio_client_for(c)
        return cl.now.get(pid) if cl else None

    def _sonn_zone_id(self, c: dict):
        """playerid der Zone `c`, nur wenn ein Event-Client dafuer laeuft."""
        cl, pid = self._audio_client_for(c)
        return pid if cl else None

    def _detect_audio_host(self) -> str | None:
        """Audioserver-Host aus einer AudioZone-Cover/sourceList-URL ableiten.

        Loxone-Musik-Cover werden ueber den Audioserver-Proxy ausgeliefert
        (z.B. http://10.0.2.2:7092/...), die Host-IP ist also dort ablesbar.
        """
        for c in self.controls.values():
            if c.get("type") != "AudioZone":
                continue
            s = c.get("states") or {}
            for key in ("cover", "sourceList"):
                v = self.states.get(s.get(key))
                if isinstance(v, str):
                    m = re.search(r"https?://(\d{1,3}(?:\.\d{1,3}){3}):\d+/", v)
                    if m:
                        return m.group(1)
        return None

    def _audio_backend_for(self, uuid: str) -> AudioBackend | None:
        """Liefert das Steuer-Backend fuer eine AudioZone (uuidAction).

        Host-Reihenfolge: manuell konfiguriert (audio_cfg) -> mediaServer-Host
        aus der Struktur (steht IMMER fest, auch wenn nichts spielt) -> als
        letzter Ausweg aus einer Cover-URL abgeleitet. Pro Host ein Backend.
        """
        if self.audio is not None:               # explizit konfiguriert
            return self.audio
        host = self.audiohost_by_action.get(uuid) or self._detect_audio_host()
        if not host:
            return None
        be = self.audio_backends.get(host)
        if be is None:
            be = make_backend({"host": host, "port": self.audio_cfg.get("port", 7091)})
            if be is not None:
                self.audio_backends[host] = be
                log.info("Audioserver-Backend fuer %s", host)
        return be

    async def command(self, uuid: str, cmd: str, pin: str | None = None) -> str | None:
        """Fuehrt einen Befehl aus. Mit pin: gesicherter Befehl (Visu-Passwort)."""
        if not (self.client and uuid and cmd):
            return None
        try:
            if pin is not None:
                return await self._secured_command(uuid, cmd, pin)
            # AudioZone-Steuerung: Ein mit dem Miniserver GEKOPPELTER Loxone-
            # Audioserver lehnt Befehle auf Port 7091 OHNE Anmeldung ab
            # ("command not allowed when paired") und schliesst die Verbindung.
            # Transportbefehle (play/pause/next/prev/volume/{n}) laufen bei ihm
            # deshalb ueber den Miniserver (sps/io/{uuid}/{cmd}), wie in
            # audioserver_events.py dokumentiert und an der echten Anlage
            # (LWSS 17.2) verifiziert. Nur ein NACHWEISLICH nicht gekoppelter
            # Audioserver (Nachbau Sonn/MS4H bzw. Musikserver Gen 1, paired=False)
            # nimmt Direktbefehle an -> dann direkt an Port 7091
            # (audio/{playerid}/{cmd}, schneller, und roomfav/play laeuft dort
            # ohne Anmeldung). Ist der Kopplungsstatus (noch) unbekannt
            # (Event-Client noch nicht gesondet, HTTP-Probe fehlgeschlagen oder
            # audiometa aus), wird sicher ueber den Miniserver geleitet. Ausnahme
            # roomfav/get: immer ueber den Miniserver, sie befuellt den
            # sourceList-State fuer die Anzeige.
            pid = self.playerid_by_action.get(uuid)
            host = self.audiohost_by_action.get(uuid)
            acl = self.audio_clients.get(host) if host else None
            # Direkt an den Audioserver nur bei positiv bekanntem Nachbau
            # (acl.paired is False). None (unbekannt) / kein Event-Client /
            # gekoppelt -> Miniserver.
            direct_ok = acl is not None and acl.paired is False
            # Raumfavorit abspielen: bei einem gekoppelten Audioserver ueber die
            # angemeldete Ereignis-Verbindung (der Direktkanal ohne Anmeldung
            # wuerde die Verbindung schliessen). Nachbauten (authed=False)
            # ueberspringen das und spielen unten direkt ab (direct_ok).
            if pid is not None and cmd.startswith("roomfav/play/"):
                if acl is not None and acl.authed:
                    ok = await acl.play_roomfav(pid, cmd.rsplit("/", 1)[-1])
                    return "200" if ok else None
            if pid is not None and not cmd.startswith("roomfav/get") and direct_ok:
                backend = self._audio_backend_for(uuid)
                if backend:
                    ok = await backend.command(pid, cmd)
                    return "200" if ok else None
                log.warning("AudioZone-Befehl ohne Audio-Backend (uuid=%s, cmd=%s)", uuid, cmd)
                return None
            # Miniserver: gekoppelte Zonen (Transport + roomfav-Fallback),
            # unbekannter Kopplungsstatus, roomfav/get und Nicht-Audio-Befehle.
            code, _ = await self._ms_jdev(f"sps/io/{uuid}/{cmd}")
            if code == "200":
                log.info("cmd %s/%s", uuid, cmd)
            else:
                log.warning("cmd %s/%s -> Code %s", uuid, cmd, code)
            return code
        except Exception as err:  # Befehl darf den Server nicht killen
            log.warning("cmd %s/%s fehlgeschlagen: %s", uuid, cmd, err or type(err).__name__)
            return None

    async def _secured_command(self, uuid: str, cmd: str, pin: str) -> str | None:
        """Loxone secured-command: getvisusalt -> Hash(visuPw:salt) -> HMAC(key) -> ios."""
        # Ein abgelaufenes Token faellt hier auf (und wird erneuert), nicht erst
        # beim ios-Aufruf: dort hiesse ein Fehler "Visu-Passwort falsch".
        _, val = await self._ms_jdev(f"sys/getvisusalt/{quote(self.user)}")
        val = val if isinstance(val, dict) else {}
        key, salt = val.get("key", ""), val.get("salt", "")
        alg = (val.get("hashAlg") or "SHA1").upper()
        digest = hashlib.sha256 if alg == "SHA256" else hashlib.sha1
        pwhash = digest(f"{pin}:{salt}".encode()).hexdigest().upper()
        h = hmac.new(bytes.fromhex(key), pwhash.encode(), digest).hexdigest()
        # Der Hash gilt nur einmal, und ein Fehler hier heisst meist falsches
        # Visu-Passwort -> nicht neu anmelden (das Token war eben noch gueltig).
        code, _ = await self._ms_jdev(f"sps/ios/{h}/{uuid}/{cmd}", renew=False)
        log.info("secured cmd %s/%s -> Code %s", uuid, cmd, code)
        return code

    def _on_value(self, uuid: str, value: object) -> None:
        self.states[uuid] = value
        self._dirty = True
        if uuid in self.bell_map:
            if value and not self._bell_prev.get(uuid):
                self._pending_ring = self.bell_map[uuid]
            self._bell_prev[uuid] = value
        if uuid in self.alarm_map:
            now = bool(value)
            if now != bool(self._alarm_prev.get(uuid)):
                # Beide Flanken pushen: 0->1 startet den Weckton, 1->0 (z.B. in
                # Loxone/App oder am Panel quittiert) stoppt ihn wieder.
                self._pending_alarm.append({"id": self.alarm_map[uuid], "on": now})
            self._alarm_prev[uuid] = value
        if uuid in self.presence_map:
            # Praesenzmelder: jemand kommt -> Display an und halten, Raum leer
            # -> aus. Nur bei echtem Wechsel, damit der Neuversand aller States
            # nach einem Reconnect nichts schaltet.
            on = bool(value)
            for name in self.presence_map[uuid]:
                if on != self._presence_on.get(name, False):
                    self._presence_on[name] = on
                    self._pending_presence.append({"dev": name, "on": on, "presence": on})

    def _on_weather(self, uuid: str, entries: list) -> None:
        """Wetter-Tabelle vom Miniserver uebernehmen (nur mit Wetterdienst).

        Die Front wird sofort neu gebaut, statt bis zum naechsten 15-Minuten-Takt
        zu warten: aus dem letzten Stand, mit neuem Wetter und OHNE neuen
        Kalenderabruf (siehe _front_nur_wetter()). Nur bei echter Aenderung,
        sonst baute jeder Wiederholungs-Push die Front umsonst neu."""
        if self._lox_wx.get(uuid) == entries:
            return
        self._lox_wx[uuid] = entries
        self._front_refresh.set()

    def _ms_sun_hhmm(self) -> tuple[str | None, str | None]:
        """Sonnenauf-/-untergang des Miniservers als "HH:MM".

        Quelle sind die globalen States (Minuten seit Mitternacht) — dieselbe,
        an der auch der Nachtmodus haengt. Ohne Werte (None, None)."""
        gs = self.global_states or {}
        out: list[str | None] = []
        for key in ("sunrise", "sunset"):
            u = gs.get(key)
            v = self.states.get(u) if isinstance(u, str) else None
            if isinstance(v, (int, float)) and 0 <= v < 1440:
                out.append(f"{int(v) // 60:02d}:{int(v) % 60:02d}")
            else:
                out.append(None)
        return out[0], out[1]

    def _loxone_weather(self) -> dict | None:
        """Wetter vom Loxone-Wetterserver aufbereitet — oder None, wenn die
        Anlage keinen hat bzw. die Daten nicht tragfaehig sind. Dann bleibt
        Open-Meteo zustaendig."""
        states = (self.weather_cfg or {}).get("states")
        if not isinstance(states, dict):
            return None
        actual = self._lox_wx.get(states.get("actual")) or []
        if not actual:
            return None
        forecast = self._lox_wx.get(states.get("forecast")) or []
        sr, ss = self._ms_sun_hhmm()
        try:
            fore = int((self.calendar_cfg or {}).get("fore_days") or 4)
        except (TypeError, ValueError):
            fore = 4
        try:
            return loxone_weather.build(self.weather_cfg, actual, forecast,
                                        sunrise=sr, sunset=ss, fore_days=fore)
        except Exception:
            log.exception("Wetterserver: Aufbereitung fehlgeschlagen — Open-Meteo bleibt")
            return None

    async def stream_task(self) -> None:
        # Dauer-Loop: Erstverbindung + Reconnect zum Miniserver. Bricht NIEMALS
        # den HTTP-Server ab — auch wenn der Miniserver (noch) nicht erreichbar
        # oder das Passwort falsch ist (dann bleibt /settings bedienbar).
        # Wartezeit zwischen Versuchen waechst (MS_RETRY). Von vorn beginnt sie
        # erst, wenn eine Verbindung mindestens so lange Daten lieferte wie die
        # laengste Wartezeit (LoxoneWS.lebenszeit()) - sonst liefe ein
        # Miniserver, der sofort wieder trennt, in eine Anmeldung alle paar
        # Sekunden. Offen sein allein genuegt nicht: Eine stumme Verbindung
        # endet erst nach keepalive_interval + response_timeout, im Betrieb
        # laenger als MS_RETRY[-1].
        retry, verbunden = 0, None
        while True:
            try:
                if self._zugang_neu is not None and self.client is None:
                    self._zugang_setzen(self._zugang_neu)   # beim Speichern nicht erreichbar gewesen
                if not self.host:
                    # Noch kein Miniserver konfiguriert -> auf /settings warten
                    # (kein Verbindungsversuch, kein Log-Spam).
                    await asyncio.sleep(5)
                    continue
                if self.client is None:
                    await self.start()          # Erstverbindung / nach hartem Reset
                elif self.ws is None:
                    # Reiner WS-Neuaufbau (z.B. nach Miniserver-Reboot durch eine
                    # Loxone-Config-Aenderung): Struktur mitziehen, damit neue/
                    # umbenannte Controls ohne LoxPanel-Neustart erscheinen. Fehler
                    # isoliert -> Reconnect scheitert nie an der Struktur.
                    try:
                        if await self._refresh_structure():
                            self._pending_reload = True   # Panels neu laden lassen
                            log.info("Loxone-Struktur geaendert -> uebernommen, Panels werden neu geladen")
                    except Exception:
                        log.exception("Struktur-Refresh beim Reconnect uebersprungen")
                    await self._connect_ws()    # WS neu (Settings-Reconnect / nach Abriss)
                verbunden = self.ws
                self._ms_fehler = ""
                self._ms_weg_seit = None   # angemeldet, der Voll-Dump kommt gleich
                self._ms_verbunden_seit = time.time()
                await self.ws.stream(self._on_value, self._on_weather)
                raise ConnectionError("WS-Stream regulär beendet")
            except asyncio.CancelledError:
                raise
            except Exception as err:
                if verbunden is not None and verbunden.lebenszeit() >= MS_RETRY[-1]:
                    retry = 0
                if verbunden is not None and verbunden.letzte_nachricht is not None:
                    # letzte Nachricht (monotone Uhr) als Uhrzeit fuer die Panels
                    self._ms_bestaetigt = time.time() - (time.monotonic() - verbunden.letzte_nachricht)
                if self._ms_weg_seit is None:
                    self._ms_weg_seit = time.time()
                self._ms_verbunden_seit = None
                verbunden = None
                wait = MS_RETRY[min(retry, len(MS_RETRY) - 1)]
                retry += 1
                log.warning("Miniserver nicht verbunden (%s) — neuer Versuch in %ss", err, wait)
                text = " ".join(str(err).split()) or err.__class__.__name__
                self._ms_fehler = text if len(text) <= EINRICHTUNG_FEHLER_MAX \
                    else text[:EINRICHTUNG_FEHLER_MAX] + " …"
                try:
                    if self.ws:
                        await self.ws.close()
                except Exception:
                    pass
                self.ws = None
                try:
                    if self.client and self._zugang_neu is not None:
                        await self._close_conn()    # neuer Zugang gespeichert -> damit neu aufbauen
                    elif self.client:
                        await self._reauth()    # Token erneuern, Client behalten
                except Exception:
                    await self._close_conn()    # Client kaputt -> harter Reset (start() baut neu)
                await asyncio.sleep(wait)

    async def push(self, msg: dict, panel: str = "", device: str = "") -> int:
        """Push an offene Visu-Verbindungen (Server -> Browser). Optional gefiltert
        auf ein Panel-Profil (`panel`) oder ein Geraet (`device`, aus ?device=).
        Gibt die Anzahl erreichter Panels zurueck. Ein Panel, das gerade neu laedt
        (App._neu_laden), zaehlt nicht mehr: erreicht wird erst seine neue Verbindung."""
        panel = (panel or "").strip()
        device = (device or "").strip()
        n = 0
        for ws in list(self.conn_prof):
            if panel and (self.conn_prof.get(ws) or {}).get("id") != panel:
                continue
            if device and self.conn_dev.get(ws) != device:
                continue
            if (self.conn_info.get(ws) or {}).get("neuLaden"):
                continue
            if await (self._neu_laden(ws) if msg.get("t") == "reload" else self._send_or_drop(ws, msg)):
                n += 1
        return n

    async def _send_or_drop(self, ws, payload) -> bool:
        """Sendet an ein Panel; bei JEDEM Fehler ODER Haenger (Timeout) wird die
        Verbindung getrennt (nicht nur bei ConnectionError — aiohttp wirft bei
        sterbenden Sockets auch RuntimeError, oder send blockiert bei half-open).
        Das ws wird zusaetzlich geschlossen, damit das Panel den Abbruch bemerkt
        und sich neu verbindet (statt still ohne Live-Updates weiterzulaufen)."""
        try:
            await asyncio.wait_for(ws.send_json(payload), timeout=5)
            return True
        except Exception:
            self.conn_route.pop(ws, None)
            self.conn_prof.pop(ws, None)
            self.conn_dev.pop(ws, None)
            self.conn_info.pop(ws, None)
            self.conn_player.pop(ws, None)
            self.conn_energy.pop(ws, None)
            self.conn_chart.pop(ws, None)
            self.conn_camera.pop(ws, None)
            self.conn_status.pop(ws, None)
            self.conn_geste.pop(ws, None)
            try:
                await ws.close()
            except Exception:
                pass
            return False

    async def _neu_laden(self, ws, msg: dict | None = None) -> bool:
        """Ein Panel neu laden ({t:"reload"}, oder `msg`, das die Seite neu laedt,
        etwa {t:"entwurfEnde"}) und die Verbindung als abgeloest kennzeichnen: die
        Seite verschwindet gleich, ein weiterer Push an sie (etwa das Umschalten
        gleich nach dem Speichern) ginge mit ihr verloren und darf in _push()
        nicht als erreicht zaehlen."""
        if not await self._send_or_drop(ws, msg or {"t": "reload"}):
            return False
        if ws in self.conn_info:
            self.conn_info[ws]["neuLaden"] = True
        return True

    async def _broadcast_tick(self) -> None:
        await self._einrichtung_melden()
        await self._verbindung_melden()
        if self.vorschau_geraet:   # Vorschau am Geraet abgelaufen: zurueck zur vorigen Ansicht
            jetzt = time.time()
            for dev in [d for d, e in self.vorschau_geraet.items() if jetzt > e["bis"]]:
                await self.vorschau_beenden(dev)
        if self._pending_ring is not None:
            rid, self._pending_ring = self._pending_ring, None
            log.info("Klingel → Popup: %s", rid)
            self._spawn(self.display_drivers(True))   # Kiosk-Apps ueber HTTP wecken
            for ws in list(self.conn_route):
                await self._send_or_drop(ws, {"t": "ring", "id": rid})
        while self._pending_alarm:
            ev = self._pending_alarm.pop(0)
            log.info("Wecker %s → %s", "an" if ev["on"] else "aus", ev["id"])
            if ev["on"]:
                self._spawn(self.display_drivers(True))
            for ws in list(self.conn_route):
                await self._send_or_drop(ws, {"t": "alarm", "id": ev["id"], "on": ev["on"]})
        if self._presence_quelle[0] is not self.devices or self._presence_quelle[1] is not self.controls:
            self._presence_rebuild()   # Geraete oder Struktur ersetzt, ohne neu zu koppeln
        ereignisse, self._pending_presence = self._pending_presence, []
        for ev in ereignisse:
            # Nur an das Geraet mit diesem Praesenzmelder: seine Visu haelt das
            # Display (presence) bzw. schaltet es ueber die Kiosk-App, die
            # Display-Treiber (Fully Remote Admin, WallPanel) schalten mit.
            # Einmal durch die Liste (pop(0) waere quadratisch); was waehrend
            # des Sendens dazukommt, laeuft im naechsten Takt.
            log.info("Präsenz %s: %s → Display %s", ev["dev"],
                     "jemand da" if ev["presence"] else "Raum leer", "an" if ev["on"] else "aus")
            if ((self.devices.get(ev["dev"]) or {}).get("display")):
                self._spawn(self.display_drivers(ev["on"], ev["dev"]))
            for ws, info in list(self.conn_info.items()):
                if info.get("dev") == ev["dev"]:
                    await self._send_or_drop(ws, {"t": "display", "on": ev["on"],
                                                  "presence": ev["presence"]})
        if self._front_dirty:
            # Front (Kalender/Wetter) an alle Panels. Neu verbundene bekommen den
            # aktuellen Stand ausserdem direkt beim Verbinden (ws_handler).
            self._front_dirty = False
            if self._front is not None:
                for ws in list(self.conn_route):
                    await self._send_or_drop(ws, self._front)
        if self._pending_reload:
            # Loxone-Struktur hat sich geaendert (Config) -> Panels neu laden, damit
            # neue/umbenannte Controls erscheinen. Nur bei echter Aenderung gesetzt.
            self._pending_reload = False
            for ws in list(self.conn_route):
                await self._neu_laden(ws)
        if self._last_sent:
            # Merkzettel von Verbindungen befreien, die es nicht mehr gibt.
            # Selbstheilend, damit nicht an jeder der vier Stellen, die eine
            # Verbindung schliessen, daran gedacht werden muss.
            for _tot in [w for w in self._last_sent if w not in self.conn_route]:
                del self._last_sent[_tot]
        night = self._night_now()
        if night != self._night_on:
            # Nur beim Wechsel senden — die Panels halten den Zustand selbst.
            self._night_on = night
            log.info("Nachtmodus %s", "an" if night else "aus")
            for ws in list(self.conn_route):
                await self._send_or_drop(ws, {"t": "night", "on": night})
        if self._dirty and self.conn_route:
            self._dirty = False
            for ws, route in list(self.conn_route.items()):
                prof = self.conn_prof.get(ws)
                try:
                    msg = self.render(route, prof)
                except Exception:
                    # EINE fehlerhafte Kachel/Route darf NIEMALS die Live-Update-
                    # Schleife killen. Fehler loggen, diese Verbindung ueberspringen.
                    log.exception("render() fehlgeschlagen (route=%s) — uebersprungen", route)
                    continue
                # Split-Layout: Player-Pane des aktiven Tabs mitrendern (Zone kommt
                # vom Client via setplayer -> conn_player). Fehler isolieren.
                player_msg = None
                _zone = self.conn_player.get(ws)
                if _zone:
                    try:
                        pb = self.player_blocks(_zone)
                        player_msg = self._pane_msg("player", _zone, pb) if pb is not None else None
                    except Exception:
                        log.exception("player_blocks fehlgeschlagen (%s)", _zone)
                # Split-Layout: Energiefluss-Pane des aktiven Tabs mitrendern (Kachel
                # kommt vom Client via setenergy -> conn_energy). Fehler isolieren.
                energy_msg = None
                _euid = self.conn_energy.get(ws)
                if _euid:
                    try:
                        eb = self.energy_blocks(_euid)
                        energy_msg = {"t": "energy", **eb} if eb is not None else None
                    except Exception:
                        log.exception("energy_blocks fehlgeschlagen (%s)", _euid)
                # Split-Layout: Verlaufs-Pane (chart:<uuid>) des aktiven Tabs
                # mitrendern (kommt vom Client via setchart -> conn_chart).
                chart_msg = None
                _chart = self.conn_chart.get(ws)
                if _chart:
                    try:
                        chart_msg = {"t": "chart", **self.chart_stack(*_chart)}
                    except Exception:
                        log.exception("chart_stack fehlgeschlagen (%s)", _chart)
                # Split-Layout: Kamera-Pane (Intercom-Vollansicht) des aktiven Tabs
                # mitrendern (kommt vom Client via setcamera -> conn_camera).
                camera_msg = None
                _cuid = self.conn_camera.get(ws)
                if _cuid:
                    try:
                        ib = self.intercom_blocks(_cuid)
                        camera_msg = self._pane_msg("camera", _cuid, ib) if ib is not None else None
                    except Exception:
                        log.exception("intercom_blocks fehlgeschlagen (%s)", _cuid)
                # Screensaver-Statusspalte: frei gewaehlte Bausteine dieses
                # Panels (kommt vom Client via setsvstatus -> conn_status).
                status_msg = None
                _suu = self.conn_status.get(ws)
                if _suu:
                    try:
                        status_msg = {"t": "svstatus", "items": self.status_blocks(_suu)}
                    except Exception:
                        log.exception("status_blocks fehlgeschlagen")
                # Nur senden, was sich seit der letzten Zustellung an DIESE
                # Verbindung geaendert hat. Der Tick laeuft, sobald sich
                # irgendein Wert im Haus bewegt — meist betrifft das die
                # Ansicht dieses Panels gar nicht, und das Panel wuerde
                # dieselbe Ansicht erneut bekommen und komplett neu zeichnen.
                last = self._last_sent.setdefault(ws, {})
                if msg != last.get("view"):
                    if not await self._send_or_drop(ws, msg):
                        self._last_sent.pop(ws, None)
                        continue
                    last["view"] = msg
                if player_msg is not None and player_msg != last.get("player"):
                    if await self._send_or_drop(ws, player_msg):
                        last["player"] = player_msg
                    else:
                        self._last_sent.pop(ws, None)
                        continue
                if energy_msg is not None and energy_msg != last.get("energy"):
                    if await self._send_or_drop(ws, energy_msg):
                        last["energy"] = energy_msg
                    else:
                        self._last_sent.pop(ws, None)
                        continue
                # Hat das Panel waehrend der Sendungen oben einen anderen Stapel
                # gewaehlt, hat setchart den neuen schon geschickt; chart_msg ist
                # dann veraltet und wuerde ihn in der Pane wieder ersetzen.
                if (chart_msg is not None and chart_msg != last.get("chart")
                        and self.conn_chart.get(ws) == _chart):
                    if await self._send_or_drop(ws, chart_msg):
                        last["chart"] = chart_msg
                    else:
                        self._last_sent.pop(ws, None)
                        continue
                if camera_msg is not None and camera_msg != last.get("camera"):
                    if await self._send_or_drop(ws, camera_msg):
                        last["camera"] = camera_msg
                    else:
                        self._last_sent.pop(ws, None)
                        continue
                if status_msg is not None and status_msg != last.get("svstatus"):
                    if await self._send_or_drop(ws, status_msg):
                        last["svstatus"] = status_msg
                    else:
                        self._last_sent.pop(ws, None)

    def _einrichtung_info(self) -> dict | None:
        """Stand der Ersteinrichtung, solange der Server keine Struktur vom
        Miniserver hat: "kein_zugang" (nichts eingetragen), "fehler" (letzter
        Versuch gescheitert, mit Grund) oder "verbindet" (erster Versuch
        laeuft). Mit Struktur None. Der Konfigurator fuehrt damit zuerst zum
        Miniserver (/api/settings), die Panels zeigen ihre Karte daraus
        (_einrichtung_stand). Billig genug fuer jeden Broadcast-Takt."""
        if self.controls:
            return None
        if not self.host:
            return {"stand": "kein_zugang"}
        if self._ms_fehler:
            return {"stand": "fehler", "host": self.host, "fehler": self._ms_fehler}
        return {"stand": "verbindet", "host": self.host}

    def _einrichtung_stand(self) -> tuple | None:
        """(Titel, Grund) fuer die Karte der Panels nach _einrichtung_info,
        aber nicht waehrend des ersten Verbindungsversuchs: Beim normalen
        Start soll nichts aufblitzen. Sonst None."""
        info = self._einrichtung_info()
        if info is None or info["stand"] == "verbindet":
            return None
        if info["stand"] == "kein_zugang":
            return ("Miniserver einrichten", "Noch kein Miniserver eingetragen.")
        return ("Keine Verbindung zum Miniserver", f"{info['host']}: {info['fehler']}")

    def _einrichtung_msg(self, stand: tuple | None) -> dict:
        """Nachricht an die Panels zum Stand aus _einrichtung_stand. Die Adresse
        des Konfigurators setzt das Panel zusammen: die, ueber die es die Visu
        geladen hat, oder - bei 127.0.0.1 - eine aus "adressen"."""
        if stand is None:
            return {"t": "einrichtung", "aktiv": False}
        titel, grund = stand
        return {"t": "einrichtung", "aktiv": True, "titel": titel, "grund": grund,
                "hinweis": "Konfigurator im Browser eines Computers oder Handys im selben Netz öffnen:",
                "pfad": "/config", "adressen": _lan_adressen(),
                "unbekannt": "Die Adresse dieses Geräts steht in seinen WLAN-Einstellungen."}

    async def _einrichtung_melden(self, neu=None) -> None:
        """Einrichtungshinweis an alle Panels, wenn sich der Stand geaendert
        hat; sonst nur an das neu verbundene Panel `neu`. Beides an einer
        Stelle, damit nie ein Panel einen Stand hat, den der Broadcaster nicht
        als gemeldet kennt (sonst bliebe die Karte nach der Rueckkehr zum
        alten Stand stehen)."""
        stand = self._einrichtung_stand()
        if stand != self._einrichtung_gemeldet:
            self._einrichtung_gemeldet = stand
            ziele = list(self.conn_route)
        else:
            ziele = [neu] if neu is not None else []
        if ziele:
            msg = self._einrichtung_msg(stand)
            for ws in ziele:
                await self._send_or_drop(ws, msg)

    def _verbindung_stand(self) -> tuple[bool, float | None, float | None]:
        """(Miniserver erreichbar, seit wann nicht, wann zuletzt von ihm
        gehoert) als Unix-Sekunden. Ohne Struktur gilt er als erreichbar: dann
        zeigen die Panels die Einrichtungskarte (_einrichtung_stand), und es
        gibt keine Werte, die veralten koennten."""
        if self._ms_weg_seit is None or not self.controls:
            return (True, None, None)
        return (False, self._ms_weg_seit, self._ms_bestaetigt)

    @staticmethod
    def _verbindung_msg(stand: tuple) -> dict:
        """Nachricht an die Panels zum Stand aus _verbindung_stand, Zeiten in
        Millisekunden (Date der Visu), dazu Takt, Fristen und Texte der Leiste."""
        ok, seit, bestaetigt = stand
        return {"t": "verbindung", "ms": ok,
                "seit": round(seit * 1000) if seit is not None else None,
                "stand": round(bestaetigt * 1000) if bestaetigt is not None else None,
                "takt": VERBINDUNG_TAKT, "stumm": VERBINDUNG_STUMM,
                "hinweis": VERBINDUNG_HINWEIS, "texte": VERBINDUNG_TEXTE}

    async def _verbindung_melden(self, neu=None) -> None:
        """Verbindungszustand an alle Panels, wenn er sich geaendert hat oder
        die letzte Meldung VERBINDUNG_TAKT s her ist (Lebenszeichen, an dem die
        Visu einen still verschwundenen Server erkennt); sonst nur an das neu
        verbundene Panel `neu`."""
        stand = self._verbindung_stand()
        jetzt = time.monotonic()
        if stand != self._verbindung_gemeldet or jetzt - self._verbindung_zuletzt >= VERBINDUNG_TAKT:
            if self._verbindung_gemeldet is not None and stand[0] != self._verbindung_gemeldet[0]:
                log.info("Panels: Miniserver %s", "wieder erreichbar" if stand[0] else "nicht erreichbar")
            self._verbindung_gemeldet, self._verbindung_zuletzt = stand, jetzt
            ziele = list(self.conn_route)
        else:
            ziele = [neu] if neu is not None else []
        if ziele:
            msg = self._verbindung_msg(stand)
            for ws in ziele:
                await self._send_or_drop(ws, msg)

    async def broadcaster(self) -> None:
        # Diese Schleife darf NIEMALS sterben — sonst bekommen ALLE Panels keine
        # Live-Updates mehr (Symptom: Aktion wird ausgefuehrt, aber erst nach
        # Weg-/Zurueck-Navigieren angezeigt). Der ganze Tick ist deshalb gekapselt.
        while True:
            await asyncio.sleep(0.3)
            try:
                await self._broadcast_tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("broadcaster-Tick fehlgeschlagen — Schleife laeuft weiter")

    def _front_payload(self, data: dict) -> dict:
        return {"t": "front", "weather": data.get("weather"),
                "events": data.get("events") or [], "holidays": data.get("holidays") or {},
                "calName": data.get("calName") or "Family",
                # Legende der Kalender (Name + Farbe, ohne die Abo-URLs) und
                # die Anzeigeoptionen, die das Panel dafuer braucht.
                "cals": data.get("cals") or [],
                "calColors": bool(data.get("colors", True)),
                "svEvents": data.get("sv_events") or 3}

    def _front_cached_events(self, events: list) -> list:
        """Gespeicherte Termine auf HEUTE umschreiben.

        Der gespeicherte Stand kann von gestern sein — dauert der Aussetzer
        ueber Mitternacht, zeigt sein "Heute" auf den Vortag und laengst
        vergangene Tage stehen noch in der Liste. Beides hier richtigstellen,
        statt einen falschen Tag aufs Panel zu schicken.
        """
        heute = date.today()
        raus = []
        for e in events:
            try:
                d = date.fromisoformat(e.get("date") or "")
            except (ValueError, TypeError):
                continue
            if d < heute:
                continue
            label = front_info.day_label(d, heute)
            raus.append(e if e.get("day") == label else dict(e, day=label))
        return raus

    def _front_wetter(self, data: dict, wx: dict | None) -> None:
        """Wetter vom Loxone-Wetterserver einsetzen (Vorrang vor Open-Meteo) und
        die tatsaechlich verwendete Quelle fuer die Diagnose festhalten."""
        if wx is not None:
            data["weather"] = wx
            data["meta"]["wx_configured"] = True
            data["meta"]["wx_error"] = None
        data["meta"]["wx_source"] = "miniserver" if wx is not None else "open-meteo"
        self._wx_source = data["meta"]["wx_source"]

    def _front_nur_wetter(self, wx: dict | None) -> dict | None:
        """Front aus dem letzten Stand neu bauen, nur mit frischem Wetter.

        So reagiert die Front auf einen Wetter-Push des Miniservers, ohne
        Kalender und Open-Meteo erneut abzufragen. Wie oft der Miniserver
        schickt, bestimmt er selbst. Hing daran ein Kalenderabruf, fragte
        LoxPanel iCloud Durchgang an Durchgang an, und iCloud sperrte das Abo
        mit 503 und Retry-After. Der letzte Stand ist schon durch _front_keep()
        gelaufen; ein zweiter Durchgang wuerde die Uhrzeit des letzten guten
        Kalenderstands verfaelschen.
        """
        if self._front_last is None:
            return None
        data = copy.deepcopy(self._front_last)
        # Liefert der Wetterserver gerade nichts Brauchbares, bleibt der letzte
        # Stand samt seiner Quelle stehen; Open-Meteo kommt im naechsten Takt.
        if wx is not None:
            self._front_wetter(data, wx)
        self._front_meta = data.get("meta", {})
        return self._front_payload(data)

    def _front_keep(self, data: dict) -> dict:
        """Bei einem fehlgeschlagenen Abruf den letzten guten Stand behalten.

        Ohne das loescht ein einzelner Aussetzer die Anzeige: `load_front()`
        faengt den Fehler ab und liefert eine LEERE Liste zurueck, der
        Diff-Vergleich sieht darin eine echte Aenderung und schickt sie los -
        der Kalender ist am Panel bis zu 15 Minuten weg, nur weil iCloud einmal
        503 gesagt hat. Der alte Stand ist in dem Fall die bessere Auskunft als
        gar keiner; die Einstellungsseite nennt den Fehler weiterhin und sagt
        jetzt dazu, von wann die gezeigten Daten sind.

        Die Termine werden JE KALENDER ueberbrueckt: bei mehreren Abos ist die
        Liste auch dann gefuellt, wenn eine Quelle ausfaellt — ein gemeinsamer
        Stand wuerde genau dann ueberschrieben und die Termine der ausgefallenen
        Quelle verschwinden lassen.
        """
        meta = data.get("meta") or {}

        quellen = meta.get("cal_sources") or []
        if quellen:
            frisch: dict = {}
            for e in data.get("events") or []:
                frisch.setdefault(e.get("ck") or "", []).append(e)
            zusammen, stale = [], None
            for q in quellen:
                k = q.get("key") or ""
                gut = self._front_good_cal.get(k)
                if q.get("error") and not frisch.get(k) and gut:
                    zusammen.extend(self._front_cached_events(gut["events"]))
                    q["stale"] = gut["zeit"]
                    stale = gut["zeit"]
                else:
                    ev = frisch.get(k, [])
                    zusammen.extend(ev)
                    if not q.get("error"):
                        self._front_good_cal[k] = {"events": ev, "zeit": time.strftime("%H:%M")}
            # Quellen einzeln sortiert -> zusammengefuehrt neu ordnen.
            zusammen.sort(key=front_info.event_sort_key)
            data["events"] = zusammen
            meta["cal_count"] = len(zusammen)
            if stale:
                meta["events_stale"] = stale
        # Entfernte Kalender nicht ewig im Speicher mitschleppen.
        aktuell = {q.get("key") for q in quellen}
        for k in list(self._front_good_cal):
            if k not in aktuell:
                del self._front_good_cal[k]

        for fehler, feld in (("hol_error", "holidays"),
                             ("wx_error", "weather")):
            if meta.get(fehler) and not data.get(feld) and self._front_good.get(feld):
                data[feld] = self._front_good[feld]
                meta[f"{feld}_stale"] = self._front_good.get("_zeit")
            elif not meta.get(fehler) and data.get(feld):
                self._front_good[feld] = data[feld]
                self._front_good["_zeit"] = time.strftime("%H:%M")
        return data

    async def front_task(self) -> None:
        """Kalender + Wetter periodisch laden und an die Panels schicken. Laeuft nur
        aktiv, wenn mindestens ein iCal-Abo ODER Koordinaten gesetzt sind.

        _front_refresh weckt die Schleife vorzeitig. Nach dem Speichern holt sie
        alles neu; bei neuem Wetter vom Miniserver tauscht sie nur das Wetter und
        laesst den Kalender bis zum naechsten Takt in Ruhe."""
        # Grenze je Host: mehrere Abos liegen oft beim selben Anbieter (iCloud,
        # Google). Acht gleichzeitige Verbindungen dorthin sehen nach einem
        # Ansturm aus — genau das beantwortet iCloud gern mit 503.
        self._front_session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit_per_host=3))
        try:
            while True:
                cfg = dict(self.calendar_cfg or {})
                # Koordinaten automatisch vom Miniserver, wenn keine in der Config.
                if cfg.get("lat") in (None, "") and self.ms_lat is not None:
                    cfg["lat"], cfg["lon"] = self.ms_lat, self.ms_lon
                # Wetter vom Miniserver hat Vorrang; Open-Meteo bleibt Rueckfall
                # fuer Anlagen ohne Loxone-Wetterdienst. Liefert der Wetterserver
                # Wetter, braucht es weder Koordinaten noch einen zweiten Abruf.
                wx = self._loxone_weather()
                configured = bool(front_info.calendar_sources(cfg)) or wx is not None or (
                    cfg.get("lat") not in (None, "") and cfg.get("lon") not in (None, ""))
                if configured:
                    try:
                        if time.monotonic() < self._front_cal_due:
                            # Geweckt vom Wetter-Push, der Kalender ist noch nicht
                            # wieder faellig: nur das Wetter tauschen.
                            payload = self._front_nur_wetter(wx)
                        else:
                            # Vor dem Abruf vormerken: auch ein unerwarteter Fehler
                            # darf keinen Abruf nach dem anderen nach sich ziehen.
                            self._front_cal_due = time.monotonic() + FRONT_INTERVAL
                            data = await front_info.load_front(self._front_session, cfg,
                                                               skip_weather=wx is not None)
                            self._front_wetter(data, wx)
                            data = self._front_keep(data)   # Aussetzer loescht nichts
                            self._front_last = copy.deepcopy(data)
                            self._front_meta = data.get("meta", {})
                            payload = self._front_payload(data)
                    except Exception:
                        log.exception("front_task: Laden fehlgeschlagen")
                        payload = None
                else:
                    self._front_meta = {}
                    self._wx_source = "open-meteo"
                    payload = {"t": "front", "weather": None, "events": [],
                               "holidays": {}, "cals": [], "calColors": True,
                               "svEvents": 3,
                               "calName": (cfg.get("name") or "Family")}
                # Nur bei echter Aenderung senden (spart Broadcasts bei gleichem Stand).
                if payload is not None:
                    key = json.dumps(payload, sort_keys=True, ensure_ascii=False)
                    if key != self._front_key:
                        self._front = payload
                        self._front_key = key
                        self._front_dirty = True
                # Bis der Kalender wieder faellig ist (hoechstens FRONT_INTERVAL) ODER
                # bis ein Speichern oder neues Wetter vom Miniserver weckt. Nach einem
                # Wetter-Push nur die RESTzeit warten, sonst schoebe jeder Push den
                # naechsten Kalenderabruf weiter hinaus.
                warte = FRONT_INTERVAL
                if configured:
                    warte = min(FRONT_INTERVAL, max(1.0, self._front_cal_due - time.monotonic()))
                try:
                    await asyncio.wait_for(self._front_refresh.wait(), timeout=warte)
                except asyncio.TimeoutError:
                    pass
                self._front_refresh.clear()
        finally:
            if self._front_session is not None:
                await self._front_session.close()
                self._front_session = None

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
