"""Front (Kalender + Wetter): wie oft der Kalender aus dem Netz geholt wird.

Anlass: Jede Wetter-Aenderung des Miniservers lud die Front samt Kalender neu,
und jeder Durchgang fragte iCloud viermal in 38 s an, obwohl iCloud mit 503 und
`Retry-After: 60` um Pause bat. Am Tower waren das 1823 Abrufe in 30 Stunden,
und iCloud hielt die Sperre so lange aufrecht, wie LoxPanel nachfragte.
"""
import asyncio
import contextlib
import time

import aiohttp
import pytest
from aiohttp import web

from lox import W, serve

front_info = W.front_info
QUELLE = {"name": "Familie", "url": "https://kalender.invalid/familie.ics", "color": "#e0a24d"}


def _termin(quelle: dict) -> dict:
    return {"day": "Sa 26.9.", "date": "2099-09-26", "time": "18:00", "title": "Termin",
            "note": "", "allday": False, "cal": quelle["name"], "color": quelle["color"],
            "ck": quelle["key"]}


async def _bis(bedingung, sekunden: float = 3.0) -> None:
    ende = time.monotonic() + sekunden
    while not bedingung():
        if time.monotonic() > ende:
            raise AssertionError("Zustand nicht erreicht")
        await asyncio.sleep(0.005)


@pytest.fixture
def abrufe(monkeypatch) -> list:
    """Kalenderabrufe mitzaehlen statt ins Netz zu gehen."""
    liste = []

    async def abruf(session, url, days, quelle=None):
        liste.append(url)
        return [_termin(quelle)]
    monkeypatch.setattr(front_info, "fetch_events", abruf)
    return liste


@contextlib.asynccontextmanager
async def _front(wetter: dict):
    """App mit einem Kalender-Abo und Wetter vom Loxone-Wetterserver, front_task laeuft."""
    app = W.App({"host": "", "port": 80})
    app.calendar_cfg = {"sources": [dict(QUELLE)]}
    app._loxone_weather = lambda: dict(wetter)
    task = asyncio.create_task(app.front_task())
    try:
        await _bis(lambda: app._front is not None)
        yield app
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def test_wetter_push_ruft_kalender_nicht_ab(abrufe):
    async def lauf():
        wetter = {"temp": 5.0}
        async with _front(wetter) as app:
            assert len(abrufe) == 1 and app._front["events"]
            takt = getattr(app, "_front_cal_due", None)
            for i in range(20):                     # der Miniserver schickt neues Wetter
                wetter["temp"] = 6.0 + i
                app._on_weather("wetter-aktuell", [{"temperature": 6.0 + i}])
                await _bis(lambda: app._front["weather"]["temp"] == wetter["temp"])
            assert len(abrufe) == 1, f"{len(abrufe)} Kalenderabrufe durch Wetter-Pushes"
            assert app._front["events"], "Termine gingen beim Tausch des Wetters verloren"
            assert app._wx_source == "miniserver"
            assert app._front_cal_due == takt, "Wetter-Pushes schieben den Kalendertakt hinaus"

            app._front_cal_due = 0.0                # Takt abgelaufen: jetzt wieder holen
            app._on_weather("wetter-aktuell", [{"temperature": 99.0}])
            await _bis(lambda: len(abrufe) == 2)
    asyncio.run(lauf())


def test_unbrauchbares_wetter_laesst_letzten_stand_stehen(abrufe):
    async def lauf():
        async with _front({"temp": 5.0}) as app:
            app._loxone_weather = lambda: None     # Wetterserver liefert gerade nichts
            app._on_weather("wetter-aktuell", [{"temperature": 1.0}])
            await _bis(lambda: not app._front_refresh.is_set())
            assert app._front["weather"] == {"temp": 5.0}
            assert app._wx_source == "miniserver" and len(abrufe) == 1
    asyncio.run(lauf())


def test_nach_wetter_push_nur_restzeit_warten(abrufe, monkeypatch):
    echt, zeiten = asyncio.wait_for, []

    async def warte(aw, timeout):
        zeiten.append(timeout)
        return await echt(aw, timeout)

    async def lauf():
        async with _front({"temp": 5.0}) as app:
            await _bis(lambda: zeiten)
            assert zeiten[-1] == pytest.approx(W.FRONT_INTERVAL, abs=5)
            app._front_cal_due = time.monotonic() + 30   # Kalender in 30 s wieder faellig
            vorher = len(zeiten)
            app._on_weather("wetter-aktuell", [{"temperature": 7.0}])
            await _bis(lambda: len(zeiten) > vorher)
            assert zeiten[-1] <= 30, f"wartet {zeiten[-1]:.0f} s statt der Restzeit"
            assert len(abrufe) == 1
    monkeypatch.setattr(asyncio, "wait_for", warte)
    asyncio.run(lauf())


def test_speichern_holt_kalender_sofort(abrufe, monkeypatch):
    gespeichert: dict = {}
    monkeypatch.setattr(W, "_load_cfg", lambda: {})
    monkeypatch.setattr(W, "_write_cfg", gespeichert.update)
    monkeypatch.setattr(W, "_calendar_config", lambda: gespeichert.get("calendar", {}))

    async def lauf():
        async with _front({"temp": 5.0}) as app:
            ui = web.Application()
            ui["app"] = app
            ui.router.add_post("/api/settings/calendar", W.api_settings_calendar)
            runner, port = await serve(ui)
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.post(f"http://127.0.0.1:{port}/api/settings/calendar",
                                      json={"sources": [QUELLE], "name": "Family"}) as r:
                        assert (await r.json())["ok"]
                await _bis(lambda: len(abrufe) == 2)
            finally:
                await runner.cleanup()
    asyncio.run(lauf())


@pytest.mark.parametrize("kopf, anfragen_erwartet", [
    ("60", 1),                               # iCloud: 503 mit Retry-After 60
    ("Thu, 01 Oct 2099 07:28:00 GMT", 1),    # Datumsform: ebenfalls laenger
    (None, 4),                               # ohne Angabe: wiederholen wie bisher
    ("0", 4),                                # kuerzer als die eigene Pause
])
def test_retry_after_wird_beachtet(monkeypatch, kopf, anfragen_erwartet):
    monkeypatch.setattr(front_info, "_RETRY_PAUSEN", (0.01, 0.01, 0.01))
    anfragen = []

    async def gesperrt(request):
        anfragen.append(request.path)
        return web.Response(status=503, headers={"Retry-After": kopf} if kopf else {})

    async def lauf():
        ui = web.Application()
        ui.router.add_get("/familie.ics", gesperrt)
        runner, port = await serve(ui)
        try:
            async with aiohttp.ClientSession() as s:
                with pytest.raises(aiohttp.ClientResponseError):
                    await front_info.fetch_events(s, f"http://127.0.0.1:{port}/familie.ics", 14)
        finally:
            await runner.cleanup()
    asyncio.run(lauf())
    assert len(anfragen) == anfragen_erwartet
