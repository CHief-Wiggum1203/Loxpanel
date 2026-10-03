"""Gemeinsame Hilfen fuer die Tests: Nachbau des Miniservers, Aufzeichnungen
wie am Miniserver und ein App-Objekt, das mit dem Nachbau spricht.

Der Nachbau nimmt nur das aktuell gueltige Token an (Bearer), so lassen sich
Ablauf und Erneuerung pruefen. Alle Server lauschen auf 127.0.0.1 mit einem
freien Port, damit Tests parallel und neben einem laufenden LoxPanel laufen.
"""
from __future__ import annotations

import asyncio
import json
import math
import struct
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import aiohttp
from aiohttp import web

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "bin") not in sys.path:
    sys.path.insert(0, str(ROOT / "bin"))

import webvisu as W  # noqa: E402

# Wartebedingung fuer Browser-Tests: Konfigurator hat /api/meta geladen. META
# ist bis zur Antwort null; die Bedingung darf dann nicht werfen, sonst bricht
# wait_for_function sofort ab statt weiter zu warten.
KONFIGURATOR_GELADEN = ("typeof META !== 'undefined' && META !== null"
                        " && Array.isArray(META.controls) && META.controls.length > 0")


async def serve(app: web.Application) -> tuple[web.AppRunner, int]:
    """aiohttp-App auf einem freien Port starten -> (runner, port)."""
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    return runner, runner.addresses[0][1]


def monatsdateien(ua: str, zeile, stunden: int, schritt_min: int,
                  jetzt: datetime | None = None) -> dict[str, str]:
    """Aufzeichnung wie am Miniserver: je Monat eine Datei <ua>.<JJJJMM>.xml.

    zeile(t) liefert die Wert-Attribute einer Zeile (z. B. 'V="1.5"'). Die
    Aufteilung nach Monaten haelt die Tests auch am Monatsanfang richtig, wenn
    der Zeitraum in den Vormonat reicht."""
    jetzt = jetzt or datetime.now().replace(second=0, microsecond=0)
    by: dict[str, list] = {}
    t = jetzt - timedelta(hours=stunden)
    while t <= jetzt:
        by.setdefault(t.strftime("%Y%m"), []).append(f'<S T="{t:%Y-%m-%d %H:%M:%S}" {zeile(t)}/>')
        t += timedelta(minutes=schritt_min)
    return {f"{ua}.{ym}.xml": "<Statistics>" + "".join(v) + "</Statistics>" for ym, v in by.items()}


class Miniserver:
    """Nachbau der HTTP-Seite des Miniservers.

    files   Statistik-Monatsdateien (Name -> XML) fuer /stats/<name>
    v2      (uuidAction, Gruppe, Ausgang) -> (Periode s, fn(unix) -> Wert)
    token   das derzeit gueltige Token; alles andere -> 401
    reject  sps/io-Befehle mit LL-Code 500 ablehnen
    deny    Pfad-Anfaenge, die trotz gueltigem Token 401 bekommen
    bilder  (uuidAction, Zeitstempel) -> JPEG fuer camimage (Klingel-Bilder)
    """

    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.v2: dict[tuple, tuple] = {}
        self.token = "T1"
        self.reject = False
        self.deny: set[str] = set()
        self.stat_hits: list[str] = []
        self.v2_paths: list[str] = []
        self.io: list[str] = []
        self.io_roh: list[str] = []          # dieselben Befehle so kodiert, wie sie ankamen
        self.bilder: dict[tuple[str, str], bytes] = {}
        self.bild_abrufe: list[str] = []
        self.live = self.peak = 0
        self.runner: web.AppRunner | None = None
        self.port = 0

    def _ok(self, r: web.Request, pfad: str) -> bool:
        return (r.headers.get("Authorization") == "Bearer " + self.token
                and not any(pfad.startswith(d) for d in self.deny))

    async def _stats(self, r: web.Request) -> web.Response:
        name = r.match_info["f"]
        self.stat_hits.append(name)
        if not self._ok(r, "stats/" + name):
            return web.Response(status=401)
        if name in self.files:
            return web.Response(text=self.files[name], content_type="text/xml")
        return web.Response(status=404)

    async def _camimage(self, r: web.Request) -> web.Response:
        ua, ts = r.match_info["ua"], r.match_info["ts"]
        self.bild_abrufe.append(f"{ua}/{ts}")
        if not self._ok(r, f"camimage/{ua}/{ts}"):
            return web.Response(status=401)
        bild = self.bilder.get((ua, ts))
        if bild is None:
            return web.Response(status=404)
        return web.Response(body=bild, content_type="image/png" if bild.startswith(b"\x89PNG") else "image/jpeg")

    async def _jdev(self, r: web.Request) -> web.Response:
        tail = r.match_info["tail"]
        if not self._ok(r, tail):
            return web.Response(status=401, text="Unauthorized")
        if tail.startswith("sps/getStatistic/"):
            return await self._getstatistic(tail)
        if tail.startswith("sys/getvisusalt/"):
            return web.json_response({"LL": {"control": tail, "Code": "200",
                                             "value": {"key": "abcd", "salt": "s1", "hashAlg": "SHA256"}}})
        self.io.append(tail)
        self.io_roh.append(r.raw_path.split("/jdev/", 1)[1])
        return web.json_response({"LL": {"control": tail, "value": "1",
                                         "Code": "500" if self.reject else "200"}})

    async def _getstatistic(self, tail: str) -> web.Response:
        _, _, ua, kind, frm, to, allw, gid, out = tail.split("/")
        self.v2_paths.append(tail)
        assert kind == "raw" and allw == "all"
        self.live += 1
        self.peak = max(self.peak, self.live)
        await asyncio.sleep(0.1)
        self.live -= 1
        reihe = self.v2.get((ua, gid, out))
        if reihe is None:
            return web.Response(body=b"", content_type="application/octet-stream")
        periode, fn = reihe
        t, body = int(frm) - int(frm) % periode + periode, b""
        while t <= int(to):
            body += struct.pack("<Id", t, fn(t))
            t += periode
        return web.Response(body=body, content_type="application/octet-stream")

    async def start(self) -> "Miniserver":
        app = web.Application()
        app.router.add_get("/stats/{f}", self._stats)
        app.router.add_get("/jdev/{tail:.*}", self._jdev)
        app.router.add_get("/camimage/{ua}/{ts}", self._camimage)
        self.runner, self.port = await serve(app)
        return self

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()
            self.runner = None


class Anmeldung:
    """Ersatz fuer LoxoneClient.authenticate(): jede Anmeldung stellt am
    Nachbau ein neues gueltiges Token aus. fehler=True: Anmeldung scheitert."""

    def __init__(self, ms: Miniserver, fehler: bool = False) -> None:
        self.ms, self.fehler, self.n = ms, fehler, 0

    async def authenticate(self) -> str:
        self.n += 1
        if self.fehler:
            raise RuntimeError("Anmeldung abgelehnt")
        self.ms.token = f"T{self.n + 1}"
        return self.ms.token

    async def close(self) -> None:
        pass


def neue_app(ms: Miniserver) -> W.App:
    """App-Objekt, das mit dem Nachbau spricht (angemeldet, HTTP statt HTTPS).
    Aufrufer schliesst app.icon_session am Ende."""
    app = W.App({"host": "127.0.0.1", "port": 80})
    app.host, app.port = "127.0.0.1", ms.port
    app.client = Anmeldung(ms)
    app.icon_session = aiohttp.ClientSession()
    app._set_token(ms.token)
    return app


def bloecke(view: dict, art: str) -> list:
    return [b for b in view.get("blocks") or [] if b.get("k") == art]


async def visu_starten(app: W.App, routen=()) -> tuple[web.AppRunner, int, asyncio.Task]:
    """Panel-Seite und /ws wie im Betrieb, dazu der Broadcaster.
    routen: weitere (Methode, Pfad, Handler), etwa die des Reiters Displays.
    -> (runner, port, broadcaster); Aufrufer bricht den Broadcaster ab und
    raeumt den runner auf."""
    ui = web.Application()
    ui["app"] = app
    ui.router.add_get("/", W.index)
    ui.router.add_get("/ws", W.ws_handler)
    ui.router.add_get("/config", W.config_index)
    ui.router.add_get("/api/meta", W.api_meta)
    ui.router.add_get("/api/settings", W.api_settings)
    ui.router.add_get("/i18n.js", W.i18n_js)
    for methode, pfad, h in routen:
        ui.router.add_route(methode, pfad, h)
    runner, port = await serve(ui)
    return runner, port, asyncio.create_task(app.broadcaster())


def anlage(controls: dict) -> dict:
    """Minimale Struktur (LoxAPP3) mit zwei Raeumen und einer Kategorie."""
    return {"rooms": {"r1": {"name": "Zentral"}, "r2": {"name": "Technikraum"}},
            "cats": {"c1": {"name": "Energie"}}, "controls": controls}


# Raum mit vier Kategorien fuer die Sprungmarken der unteren Leiste: 3 + 2 + 4 + 3
# Schalter in "Sauna" (r1), dazu 2 Schalter im "Technikraum" (r2) fuer die freie
# Auswahl ueber zwei Raeume. Bei 2x2 beginnt "Heizung" unten rechts auf Seite 1,
# bei 2x3 "Lüftung" - genau dort, wo ein Sprung frueher auf die Folgeseite rutschte.
RAUM_KATS = {"c1": ("Beleuchtung", 3), "c2": ("Heizung", 2), "c3": ("Lüftung", 4), "c4": ("Sonstiges", 3)}


def raum_anlage() -> tuple[dict, dict]:
    """-> (Struktur, States) fuer ein Raum-Panel mit vier Kategorien."""
    controls, states, n = {}, {}, 0
    for cat, (name, anzahl) in RAUM_KATS.items():
        for i in range(anzahl):
            n += 1
            controls[f"S{n}"] = {"name": f"{name} {i + 1}", "type": "Switch", "uuidAction": f"S{n}",
                                 "room": "r1", "cat": cat, "states": {"active": f"s{n}"}}
            states[f"s{n}"] = 0
    for i in (1, 2):
        controls[f"T{i}"] = {"name": f"Technik {i}", "type": "Switch", "uuidAction": f"T{i}",
                             "room": "r2", "cat": "c1", "states": {"active": f"t{i}"}}
        states[f"t{i}"] = 0
    return ({"rooms": {"r1": {"name": "Sauna"}, "r2": {"name": "Technikraum"}},
             "cats": {c: {"name": v[0]} for c, v in RAUM_KATS.items()}, "controls": controls}, states)


# Alte Raumregelung (IRoomController, v1) in der Form, die ein echter Miniserver
# liefert (Struktur aus ioBroker.loxone#22): "temperatures" ist in states eine
# Liste mit einer UUID je Temperatur-Nummer 0..6, details.temperatures sagt je
# Nummer, ob der Wert absolut ist oder von Komfort abhaengt.
IRC1_ABSOLUT = {"0": False, "1": True, "2": True, "3": True, "4": True, "5": False, "6": False}
IRC1_STATES = ("tempTarget", "tempActual", "error", "mode", "serviceMode", "currHeatTempIx",
               "currCoolTempIx", "override", "isPreparing", "valveHeat", "valveCool", "openWindow",
               "overrideTotal", "movement", "manualMode")


def irc1_baustein(**werte) -> tuple[dict, dict]:
    """-> (Control, States) einer alten Raumregelung im Autopilot Heizen mit
    Komfort Heizen aktiv. werte ueberschreibt States nach Namen; "temperatures"
    ist die Liste der Werte je Nummer (Eco, Erhoehte Waerme, Party relativ)."""
    states = {n: f"irc-{n}" for n in IRC1_STATES}
    states["temperatures"] = [f"irc-t{i}" for i in range(len(IRC1_ABSOLUT))]
    control = {"name": "Wohnzimmer Heizung", "type": "IRoomController", "uuidAction": "IRC",
               "room": "r1", "cat": "c1",
               "details": {"restrictedToMode": 0, "format": "%.1f°",
                           "temperatures": {k: {"isAbsolute": v} for k, v in IRC1_ABSOLUT.items()}},
               "states": states}
    w = {"tempTarget": 22.0, "tempActual": 20.5, "error": 0, "mode": 3, "serviceMode": 0,
         "currHeatTempIx": 1, "currCoolTempIx": 2, "override": 0, "isPreparing": 0, "valveHeat": 0,
         "valveCool": 0, "openWindow": 0, "overrideTotal": 0, "movement": 0, "manualMode": 0,
         "temperatures": [2.0, 22.0, 24.0, 12.0, 30.0, 1.0, 0.5], **werte}
    werte_uuid = {states[n]: w[n] for n in IRC1_STATES}
    werte_uuid.update(zip(states["temperatures"], w["temperatures"]))
    return control, werte_uuid


# Intelligente Raumregelung V2 (IRoomControllerV2): State-Namen wie in der
# openHAB-Loxone-Anbindung, Temperatur-Modi (details.timerModes) wie activeMode
# dort: 0 Eco, 1 Komfort, 2 Gebaeudeschutz.
IRC2_STATES = ("activeMode", "operatingMode", "prepareState", "openWindow", "tempActual",
               "tempTarget", "comfortTemperature", "comfortTemperatureCool", "comfortTolerance",
               "absentMinOffset", "absentMaxOffset", "frostProtectTemperature",
               "heatProtectionTemperature", "comfortTemperatureOffset", "overrideEntries")


def irc2_baustein(**werte) -> tuple[dict, dict]:
    """-> (Control, States) einer Raumregelung V2 in Automatik Heizen & Kuehlen
    mit Komfort aktiv; werte ueberschreibt States nach Namen."""
    states = {n: f"irc2-{n}" for n in IRC2_STATES}
    control = {"name": "Bad Heizung", "type": "IRoomControllerV2", "uuidAction": "IRC2",
               "room": "r1", "cat": "c1",
               "details": {"format": "%.1f°", "timerModes": [
                   {"id": 0, "name": "Eco"}, {"id": 1, "name": "Komfort"},
                   {"id": 2, "name": "Gebäudeschutz"}]},
               "states": states}
    w = {"activeMode": 1, "operatingMode": 0, "prepareState": 0, "openWindow": 0,
         "tempActual": 21.0, "tempTarget": 22.5, "comfortTemperature": 22.5,
         "comfortTemperatureCool": 25.0, "comfortTolerance": 1.0, "absentMinOffset": 2.0,
         "absentMaxOffset": 2.0, "frostProtectTemperature": 5.0, "heatProtectionTemperature": 35.0,
         "comfortTemperatureOffset": 0.0, "overrideEntries": "[]", **werte}
    return control, {states[n]: w[n] for n in IRC2_STATES}


# Energieflussmonitor (EFM) mit eigenen Knoten und Energiemanager (EM2) mit
# Ppwr/Gpwr/Spwr in kW, Vorzeichen aus Sicht des Hauses (positiv = ins Haus).
EFM_NODES = [{"name": "Netz", "nodeType": "Grid"}, {"name": "PV", "nodeType": "Production"},
             {"name": "Batterie", "nodeType": "Storage"}, {"name": "Wärmepumpe", "nodeType": "Load"}]

EFM = {"name": "Energieflussmonitor", "type": "EFM", "uuidAction": "F", "room": "r1", "cat": "c1",
       "details": {"actualFormat": "%.2f kW", "nodes": EFM_NODES},
       "states": {"Ppwr": "f-p", "Gpwr": "f-g", "Spwr": "f-s",
                  **{f"actual{i}": f"f-a{i}" for i in range(len(EFM_NODES))}}}

EM2 = {"name": "Energiemanager", "type": "EnergyManager2", "uuidAction": "M", "room": "r1", "cat": "c1",
       "details": {}, "states": {"Ppwr": "m-p", "Gpwr": "m-g", "Spwr": "m-s", "Ssoc": "m-soc"}}


def _zaehler_zeile(jetzt):
    """Echter Zaehler: 0,8 kWh je Stunde aufsummiert, dazu die Leistung als V2."""
    start = jetzt - timedelta(hours=24 * 31)
    return lambda t: (f'V="{1000 + (t - start).total_seconds() / 3600 * 0.8:.3f}" '
                      f'V2="{0.5 + 0.4 * math.sin(t.hour):.3f}"')


def v1_bausteine(ms: Miniserver, jetzt: datetime) -> dict:
    """Aufzeichnungen (V1, ein Monat) am Nachbau ablegen und die Bausteine dazu:
    T Boiler (Messwert), Z Stromzaehler (Zaehlerstand + Leistung), R Regen
    (Ein/Aus), X ohne Aufzeichnung."""
    ms.files.update(monatsdateien("TEMP", lambda t: f'V="{52 + 7 * math.cos((t.hour - 15) / 24 * 2 * math.pi):.2f}"',
                                  24 * 31, 30, jetzt))
    ms.files.update(monatsdateien("ZAEHL", _zaehler_zeile(jetzt), 24 * 31, 20, jetzt))
    ms.files.update(monatsdateien("REGEN", lambda t: 'V="1"' if t.hour in (6, 7, 16) else 'V="0"',
                                  24 * 31, 30, jetzt))
    return {
        "T": {"name": "Boiler", "type": "InfoOnlyAnalog", "uuidAction": "TEMP", "states": {"value": "sv"},
              "details": {"format": "%.1f°C"},
              "statistic": {"frequency": 6, "outputs": [{"id": 0, "name": "Boiler", "format": "%.1f°C", "visuType": 0}]}},
        "Z": {"name": "Stromzähler", "type": "Meter", "uuidAction": "ZAEHL", "states": {"actual": "sa", "total": "st"},
              "details": {"actualFormat": "%.3fkW", "totalFormat": "%.1fkWh"},
              "statistic": {"frequency": 6, "outputs": [
                  {"id": 0, "name": "Gesamtverbrauch", "format": "%.1fkWh", "visuType": 2},
                  {"id": 1, "name": "Leistung", "format": "%.3fkW", "visuType": 0}]}},
        "R": {"name": "Regen", "type": "InfoOnlyDigital", "uuidAction": "REGEN", "states": {"active": "sr"},
              "statistic": {"frequency": 1, "outputs": [{"id": 0, "name": "Regen", "visuType": 1}]}},
        "X": {"name": "Ohne Aufzeichnung", "type": "InfoOnlyAnalog", "uuidAction": "X", "states": {"value": "sx"}},
    }


def pv_leistung(ts):
    """PV-Leistung in kW: Sinusbogen von 6 bis 20 Uhr, Spitze 8 kW."""
    h = time.localtime(ts).tm_hour + time.localtime(ts).tm_min / 60
    return max(0.0, 8.0 * math.sin((h - 6) / 14 * math.pi)) if 6 <= h <= 20 else 0.0


def hauslast(ts):
    """Hausverbrauch in kW: tagsueber 1,1, nachts 0,4."""
    return 1.1 if 7 <= time.localtime(ts).tm_hour < 22 else 0.4


def zaehlerstand(fn, basis=int(time.time()) - 40 * 86400):
    """Zaehlerstand aus einer Leistung fn (kW), aufsummiert ab basis."""
    return lambda ts: 5000 + sum(fn(t) * 0.5 for t in range(basis - basis % 3600, ts - ts % 3600, 1800))


# --- Bausteine nach der Loxone-Strukturdoku (Stand 16.0). State- und
# details-Namen wie an einer echten Anlage (Ausgabe von /api/types), Werte so,
# wie die Doku sie beschreibt.

def aufab_baustein(wert=1, fehler=0, **details) -> tuple[dict, dict]:
    """Auf/Ab-Taster mit Wert (UpDownAnalog, in der Doku "UpDownLeftRight
    analog"): details format/min/max/step, States value und error."""
    control = {"name": "1=kompl AUF 3=Lamelle waagrecht", "type": "UpDownAnalog", "uuidAction": "UDA",
               "room": "r1", "cat": "c1",
               "details": {"format": "%.0f", "min": 1, "max": 3, "step": 1, "jLockable": True, **details},
               "states": {"value": "uda-v", "error": "uda-e", "jLocked": "uda-l"}}
    return control, {"uda-v": wert, "uda-e": fehler, "uda-l": ""}


# Zonen einer Bewaesserung: id ab 0, Laufzeit in Sekunden; die Hecke gibt die
# Logik vor (setByLogic).
BEW_ZONEN = [{"id": 0, "name": "Rasen vorne", "duration": 600, "setByLogic": False},
             {"id": 1, "name": "Beete", "duration": 300, "setByLogic": False},
             {"id": 2, "name": "Hecke", "duration": 900, "setByLogic": True}]
BEW_STATES = ("active", "currentZone", "expectedPrecipitation", "jLocked", "maxExpectedPrecipitation",
              "rainActive", "rainTime", "zones")


def bewaesserung_baustein(**werte) -> tuple[dict, dict]:
    """Bewaesserung (Irrigation): zones als JSON-Text, currentZone -1 = aus,
    0..7 = id der Zone, 8 = alle; rainTime in Sekunden der letzten 24 h."""
    states = {n: f"bew-{n}" for n in BEW_STATES}
    control = {"name": "Bewässerung", "type": "Irrigation", "uuidAction": "BEW", "room": "r1", "cat": "c1",
               "details": {"jLockable": True}, "states": states}
    w = {"active": 0, "currentZone": -1, "expectedPrecipitation": 0.0, "jLocked": "",
         "maxExpectedPrecipitation": 2.0, "rainActive": 0, "rainTime": 0, "zones": json.dumps(BEW_ZONEN),
         **werte}
    return control, {states[n]: w[n] for n in BEW_STATES}


# Betriebsarten wie im Abschnitt operatingModes einer Struktur; 3..9 sind laut
# Doku Montag bis Sonntag, 0..2 haben Vorrang vor ihnen.
BETRIEBSARTEN = {"0": "Feiertag", "1": "Urlaub", "3": "Montag", "4": "Dienstag", "5": "Mittwoch",
                 "6": "Donnerstag", "7": "Freitag", "8": "Samstag", "9": "Sonntag", "10": "Arbeitstag"}
# Weckzeiten: ab Version 13.0 hat jeder Wecker einen Eintrag mit nightLight
# (daily statt modes), dazu zwei gewoehnliche.
WECKZEITEN = {
    "0": {"name": "Nachtlicht", "isActive": False, "alarmTime": 25200, "modes": [], "nightLight": True,
          "daily": True},
    "1": {"name": "Arbeit", "isActive": True, "alarmTime": 22500, "modes": [3, 4, 5, 6, 7],
          "nightLight": False, "daily": False},
    "2": {"name": "Wochenende", "isActive": False, "alarmTime": 30600, "modes": [8, 9, 0],
          "nightLight": False, "daily": False},
}
WECKER_STATES = ("confirmationNeeded", "currentEntry", "deviceSettings", "deviceState", "entryList",
                 "isAlarmActive", "isEnabled", "jLocked", "nextEntry", "nextEntryMode", "nextEntryTime",
                 "prepareDuration", "ringDuration", "ringingTime", "snoozeDuration", "snoozeTime",
                 "wakeAlarmSoundSettings")


def wecker_baustein(eintraege=None, **werte) -> tuple[dict, dict]:
    """Wecker (AlarmClock): entryList als JSON-Text {entryID: {name, isActive,
    alarmTime (Sekunden ab Mitternacht), modes, nightLight, daily}}, Dauern in
    Sekunden."""
    states = {n: f"wk-{n}" for n in WECKER_STATES}
    control = {"name": "Anna Wecker", "type": "AlarmClock", "uuidAction": "WK", "room": "r1", "cat": "c1",
               "details": {"hasNightLight": True, "snoozeDurationConnected": False,
                           "brightActiveConnected": False, "brightInactiveConnected": False,
                           "wakeAlarmSoundConnected": False, "wakeAlarmVolumeConnected": False,
                           "wakeAlarmSlopingConnected": False, "wakeAlarmSounds": [], "jLockable": True},
               "states": states}
    w = {"confirmationNeeded": 0, "currentEntry": -1, "deviceSettings": "", "deviceState": 0,
         "entryList": json.dumps(WECKZEITEN if eintraege is None else eintraege), "isAlarmActive": 0,
         "isEnabled": 1, "jLocked": "", "nextEntry": 1, "nextEntryMode": 3, "nextEntryTime": 0,
         "prepareDuration": 900, "ringDuration": 300, "ringingTime": 0, "snoozeDuration": 540,
         "snoozeTime": 0, "wakeAlarmSoundSettings": "", **werte}
    return control, {states[n]: w[n] for n in WECKER_STATES}


# Verpasste Klingeln wie im State lastBellEvents: JJJJMMTTHHMMSS, mit | getrennt
KLINGELN = ("20261001074904", "20261002181530", "20261003091200")


def intercom_baustein(klingeln=KLINGELN, bilder=True, **werte) -> tuple[dict, dict]:
    """Tuersprechstelle (Intercom, "Door Controller"): Klingel bell, verpasste
    Klingeln lastBellEvents; mit details.lastBellEventImages liefert der
    Miniserver je Klingel ein Bild (camimage). Ausgaenge sind
    Pushbutton-Subcontrols (pulse)."""
    names = ("bell", "jLocked", "lastBellEvents", "lastBellTimestamp")
    states = {n: f"ic-{n}" for n in names}
    control = {"name": "Eingang Intercom", "type": "Intercom", "uuidAction": "IC", "room": "r1", "cat": "c1",
               "details": {"deviceType": 1, "videoInfo": {}, "audioInfo": {}, "lastBellEventImages": bilder,
                           "showBellImage": False, "jLockable": True},
               "states": states,
               "subControls": {"IC/1": {"name": "Tür öffnen", "type": "Pushbutton", "uuidAction": "IC/1",
                                        "states": {"active": "ic-o1"}}}}
    w = {"bell": 0, "jLocked": "", "lastBellEvents": "|".join(klingeln), "lastBellTimestamp": "", **werte}
    return control, {states[n]: w[n] for n in names}
