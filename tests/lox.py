"""Gemeinsame Hilfen fuer die Tests: Nachbau des Miniservers, Aufzeichnungen
wie am Miniserver und ein App-Objekt, das mit dem Nachbau spricht.

Der Nachbau nimmt nur das aktuell gueltige Token an (Bearer), so lassen sich
Ablauf und Erneuerung pruefen. Alle Server lauschen auf 127.0.0.1 mit einem
freien Port, damit Tests parallel und neben einem laufenden LoxPanel laufen.
"""
from __future__ import annotations

import asyncio
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


async def visu_starten(app: W.App) -> tuple[web.AppRunner, int, asyncio.Task]:
    """Panel-Seite und /ws wie im Betrieb, dazu der Broadcaster.
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
    runner, port = await serve(ui)
    return runner, port, asyncio.create_task(app.broadcaster())


def anlage(controls: dict) -> dict:
    """Minimale Struktur (LoxAPP3) mit zwei Raeumen und einer Kategorie."""
    return {"rooms": {"r1": {"name": "Zentral"}, "r2": {"name": "Technikraum"}},
            "cats": {"c1": {"name": "Energie"}}, "controls": controls}


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
