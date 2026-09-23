"""Kalender und Wetter als eigene Tabs (FRONT_TABS). Die Daten laufen durch die
echte Kette: iCal-Abo und Open-Meteo-Antwort aus einem Nachbau -> load_front ->
_front_payload -> Panel. Gezeigt in Chromium quer (1280 x 800) und quadratisch
(480 x 480)."""
import asyncio
from datetime import date, datetime, timedelta

import aiohttp
import pytest
from aiohttp import web

import front_info
from lox import W, anlage, serve, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

HEUTE = date.today()


def _ics() -> str:
    """Kalender mit Einzelterminen, einem ganztaegigen und einer Serie (fuer eine
    Liste, die scrollen muss)."""
    def ev(uid, titel, tag, zeit=None, extra=""):
        if zeit:
            beginn = f"DTSTART:{tag:%Y%m%d}T{zeit}00\nDTEND:{tag:%Y%m%d}T{zeit}00"
        else:
            beginn = f"DTSTART;VALUE=DATE:{tag:%Y%m%d}\nDTEND;VALUE=DATE:{tag + timedelta(days=1):%Y%m%d}"
        return f"BEGIN:VEVENT\nUID:{uid}\nSUMMARY:{titel}\n{beginn}\n{extra}END:VEVENT\n"
    return ("BEGIN:VCALENDAR\nVERSION:2.0\n"
            + ev("a", "Elternabend", HEUTE, "1800")
            + ev("b", "Müllabfuhr", HEUTE + timedelta(days=1))
            + ev("c", "Zahnarzt", HEUTE + timedelta(days=5), "0930")
            + ev("d", "Hund füttern", HEUTE, "0700", "RRULE:FREQ=DAILY;COUNT=20\n")
            + "END:VCALENDAR\n")


def _open_meteo() -> dict:
    """Antwort im Format von Open-Meteo fuer heute und 7 Tage."""
    jetzt = datetime.now().replace(minute=0, second=0, microsecond=0)
    stunden = [jetzt + timedelta(hours=i) for i in range(-2, 46)]
    tage = [HEUTE + timedelta(days=i) for i in range(7)]
    return {
        "current": {"time": jetzt.strftime("%Y-%m-%dT%H:%M"), "temperature_2m": 17.4, "relative_humidity_2m": 64,
                    "apparent_temperature": 16.2, "is_day": 1, "weather_code": 2, "wind_speed_10m": 12.3,
                    "wind_direction_10m": 250, "pressure_msl": 1016.4},
        "hourly": {"time": [h.strftime("%Y-%m-%dT%H:%M") for h in stunden],
                   "temperature_2m": [12 + 6 * ((h.hour - 4) % 24) / 23 for h in stunden],
                   "precipitation_probability": [10 * (h.hour % 5) for h in stunden],
                   "weather_code": [2 if 7 <= h.hour < 19 else 1 for h in stunden],
                   "apparent_temperature": [11 + 6 * ((h.hour - 4) % 24) / 23 for h in stunden]},
        "daily": {"time": [t.isoformat() for t in tage],
                  "temperature_2m_max": [19, 21, 18, 16, 22, 23, 20], "temperature_2m_min": [9, 11, 10, 8, 12, 13, 11],
                  "weathercode": [2, 0, 61, 3, 0, 1, 95], "precipitation_probability_max": [20, 0, 80, 40, 5, 10, 70],
                  "precipitation_sum": [0.4, 0, 6.2, 1.1, 0, 0, 9.5],
                  "sunrise": [f"{t}T06:58" for t in tage], "sunset": [f"{t}T19:04" for t in tage],
                  "uv_index_max": [4.2, 5, 2, 3, 6, 6, 4]},
    }


async def _front(monkeypatch):
    """Nachbau fuers Netz starten und die Front wie der Server laden."""
    async def ics(_r):
        return web.Response(text=_ics(), content_type="text/calendar")

    async def wetter(_r):
        return web.json_response(_open_meteo())
    netz = web.Application()
    netz.router.add_get("/familie.ics", ics)
    netz.router.add_get("/v1/forecast", wetter)
    runner, port = await serve(netz)
    monkeypatch.setattr(front_info, "OPEN_METEO", f"http://127.0.0.1:{port}/v1/forecast")
    cfg = {"sources": [{"name": "Familie", "url": f"http://127.0.0.1:{port}/familie.ics", "color": "#52b881"}],
           "lat": 47.07, "lon": 15.44, "days": 30, "fore_days": 7}
    async with aiohttp.ClientSession() as s:
        daten = await front_info.load_front(s, cfg)
    await runner.cleanup()
    assert daten["weather"] and len(daten["events"]) >= 22, daten["meta"]
    return daten


def test_tabs_im_server():
    assert W._is_tab("kalender") and W._is_tab("wetter")
    app = W.App({"host": "", "port": 80})
    v = app._view_tab("kalender")
    assert v["front"] == "calendar" and v["title"] == "Kalender" and v["items"] == []
    assert app._view_tab("wetter")["front"] == "weather"
    p = W.App._sanitize_panels({"t": {"title": "T", "tabs": ["favoriten", "kalender", "wetter", "quatsch"]}})["t"]
    assert p["tabs"] == ["favoriten", "kalender", "wetter"]


def test_kalender_und_wetter_tab(tmp_path, monkeypatch):
    async def lauf():
        daten = await _front(monkeypatch)
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage({"L": {"name": "Licht", "type": "Switch", "uuidAction": "LA", "room": "r1",
                                           "cat": "c1", "isFavorite": True, "states": {"active": "sl"}}}))
        app.states = {"sl": 0}
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten", "kalender", "wetter"]}})
        app._front = app._front_payload(daten)
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                for breite, hoehe in ((1280, 800), (480, 480)):
                    pg = await b.new_page(viewport={"width": breite, "height": hoehe}, locale="de-DE")
                    pg.on("pageerror", lambda e: fehler.append(str(e)))
                    await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                    await pg.wait_for_timeout(600)
                    await pg.evaluate("wake()")
                    await pg.wait_for_timeout(800)
                    tabs = await pg.evaluate("[...document.querySelectorAll('#tabs .tab')].map(t => t.dataset.tab)")
                    assert tabs == ["favoriten", "kalender", "wetter"]

                    # Kalender: Monat + alle Termine; ein Tag filtert, "Alle" hebt es auf
                    await pg.locator('#tabs .tab[data-tab="kalender"]').click()
                    await pg.wait_for_timeout(500)
                    k = await pg.evaluate("""() => ({seite: document.getElementById('grid').classList.contains('fronttab'),
                        heute: !!document.querySelector('.ft .fp-mon-c.today'), termine: document.querySelectorAll('.ft-b .fp-ev').length,
                        tage: [...document.querySelectorAll('.ft-b .fp-day')].slice(0, 2).map(e => e.textContent),
                        scrollt: (b => b.scrollHeight > b.clientHeight)(document.querySelector('.ft-b')),
                        seiteScrollt: (g => g.scrollHeight > g.clientHeight)(document.getElementById('grid')),
                        aktiv: document.querySelector('#tabs .tab.active').dataset.tab})""")
                    assert k["seite"] and k["heute"] and k["termine"] == len(daten["events"]), k
                    assert k["tage"] == ["Heute", "Morgen"] and k["aktiv"] == "kalender", k
                    assert k["scrollt"] if breite > hoehe else k["seiteScrollt"], "lange Terminliste muss scrollen"
                    # jeder Tag steht unter seinem Wochentag (ein globales .empty schob frueher
                    # die Leerfelder auf eine eigene Zeile, jeder Monat begann am Montag)
                    falsch = await pg.evaluate("""() => {
                        const kopf = [...document.querySelectorAll('.ft .fp-mon-wd')].map(e => e.getBoundingClientRect());
                        return [...document.querySelectorAll('.ft .fp-mon-c[data-day]')].filter(c => {
                            const wt = (new Date(c.dataset.day + 'T12:00').getDay() + 6) % 7, r = c.getBoundingClientRect();
                            return Math.abs((r.left + r.right) / 2 - (kopf[wt].left + kopf[wt].right) / 2) > 2; })
                          .map(c => c.dataset.day); }""")
                    assert not falsch, f"Tage unter falschem Wochentag: {falsch[:5]}"
                    await pg.screenshot(path=str(tmp_path / f"kalender_{breite}.png"))
                    in5 = HEUTE + timedelta(days=5)
                    if in5.month != HEUTE.month:           # Monatsende: erst weiterblaettern
                        await pg.locator('.ft .fp-mnav[data-mnav="1"]').click()
                        await pg.wait_for_timeout(300)
                    await pg.locator(f'.ft .fp-mon-c[data-day="{in5.isoformat()}"]').click()
                    await pg.wait_for_timeout(300)
                    tag = await pg.evaluate("[...document.querySelectorAll('.ft-b .fp-ev .ttl')].map(e => e.textContent)")
                    assert any("Zahnarzt" in t for t in tag) and any("Hund füttern" in t for t in tag), tag
                    assert len(tag) == 2, "nur die Termine des gewaehlten Tages"
                    await pg.locator(".ft-b [data-calall]").click()
                    await pg.wait_for_timeout(300)
                    assert await pg.locator(".ft-b .fp-ev").count() == len(daten["events"])
                    if in5.month != HEUTE.month:
                        await pg.locator('.ft .fp-mnav[data-mnav="-1"]').click()

                    # Wetter: Lage, Kurve, 7 Tage, Details
                    await pg.locator('#tabs .tab[data-tab="wetter"]').click()
                    await pg.wait_for_timeout(500)
                    w = await pg.evaluate("""() => ({temp: (document.querySelector('.ft-wx .fp-now .t') || {}).textContent,
                        kurve: !!document.querySelector('.ft-wx .fp-curve svg'), tage: document.querySelectorAll('.ft-wx .fp-fc').length,
                        details: [...document.querySelectorAll('.ft-wx .fp-det span')].map(e => e.textContent)})""")
                    assert w["temp"] == "17,4°" and w["kurve"] and w["tage"] == 7, w
                    assert {"Luftfeuchte", "Wind", "Sonne", "UV-Index", "Luftdruck"} <= set(w["details"]), w
                    await pg.screenshot(path=str(tmp_path / f"wetter_{breite}.png"))

                    # Neue Front-Daten zeichnen die offene Seite neu
                    neu = dict(app._front, weather=dict(app._front["weather"], temp=9.8))
                    await W._push(app, neu)
                    await pg.wait_for_timeout(400)
                    assert await pg.locator(".ft-wx .fp-now .t").text_content() == "9,8°"

                    # zurueck zu den Kacheln: nichts von der Front-Seite bleibt haengen
                    await pg.locator('#tabs .tab[data-tab="favoriten"]').click()
                    await pg.wait_for_timeout(500)
                    g = await pg.evaluate("""() => ({front: document.getElementById('grid').classList.contains('fronttab'),
                        kacheln: document.querySelectorAll('.tile').length})""")
                    assert g == {"front": False, "kacheln": 1}, g
                    await pg.close()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


def test_split_haelfte_wetter_und_kalender(tmp_path, monkeypatch):
    """Die rechte Split-Haelfte nutzt dieselben Bausteine: Wetter komplett (Lage,
    Kurve, Vorschau, Details), Kalender mit Tagen unter dem richtigen Wochentag."""
    async def lauf():
        daten = await _front(monkeypatch)
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage({"L": {"name": "Licht", "type": "Switch", "uuidAction": "LA", "room": "r1",
                                           "cat": "c1", "isFavorite": True, "states": {"active": "sl"}}}))
        app.states = {"sl": 0}
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten", "zentral"],
                                                      "ui": {"panes": {"favoriten": "weather", "zentral": "calendar"}}}})
        app._front = app._front_payload(daten)
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 960, "height": 480}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_timeout(600)
                await pg.evaluate("wake()")
                await pg.wait_for_timeout(800)
                w = await pg.evaluate("""() => ({now: !!document.querySelector('#frontpane .fp-now'),
                    kurve: !!document.querySelector('#frontpane .fp-curve svg'),
                    tage: document.querySelectorAll('#frontpane .fp-fc').length,
                    details: document.querySelectorAll('#frontpane .fp-det > div').length})""")
                assert w == {"now": True, "kurve": True, "tage": 7, "details": 6}, w
                await pg.screenshot(path=str(tmp_path / "split_wetter.png"))
                await pg.locator('#tabs .tab[data-tab="zentral"]').click()
                await pg.wait_for_timeout(500)
                falsch = await pg.evaluate("""() => {
                    const kopf = [...document.querySelectorAll('#frontpane .fp-mon-wd')].map(e => e.getBoundingClientRect());
                    const zellen = [...document.querySelectorAll('#frontpane .fp-mon-c[data-day]')];
                    if (!zellen.length) return ['kein Monatsraster'];
                    return zellen.filter(c => {
                        const wt = (new Date(c.dataset.day + 'T12:00').getDay() + 6) % 7, r = c.getBoundingClientRect();
                        return Math.abs((r.left + r.right) / 2 - (kopf[wt].left + kopf[wt].right) / 2) > 2; })
                      .map(c => c.dataset.day); }""")
                assert not falsch, f"Split-Kalender: {falsch[:5]}"
                await pg.screenshot(path=str(tmp_path / "split_kalender.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
