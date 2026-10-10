"""Neu laden gegen Einfrieren in Chromium, mit gestellter Uhr (Playwright clock,
Zeitzone Europe/Berlin). Ohne Eintrag "Auto-Neustart" laedt die Visu einmal je
Nacht ab NEULADEN_STUNDE neu und dann erst in der naechsten Nacht wieder, nur
solange die Uhr-Seite steht - nie unter den Fingern. Eine Zahl laedt so viele
Stunden nach dem Laden neu, 0 und ein Agent nie. In der LoxPanel-App bleibt
ein dunkles Display dabei dunkel: Die neu geladene Seite meldet der App nur
ihre Uhr und die Leerlaufzeit, sie weckt nicht. Der Konfigurator nennt die
Stunde im leeren Feld."""
import asyncio
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BERLIN = ZoneInfo("Europe/Berlin")
ABEND = datetime(2026, 10, 2, 22, 0, tzinfo=BERLIN)      # Freitag 22:00, die Seite wird geladen
BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "LA", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}}}
# Die Seite hat die theme-Nachricht verarbeitet (reloadAt kommt nur von dort)
EINGESTELLT = "DISP.reloadAt !== null"
# JS-Bruecke der LoxPanel-App, nachgebaut: Jeder Aufruf geht an den Test
# (expose_function), auch ueber das Neuladen hinweg. isScreenOn() meldet ein
# dunkles Display, ein Wecken riefe also turnScreenOn() auf.
BRUECKE_JS = """window.LoxKiosk = {
  setDisplayOff(s) { window.__bruecke('dpms:' + s); },
  setSaver(an) { window.__bruecke('saver:' + an); },
  setDisplayBrightness(p) { window.__bruecke('hell:' + p); return true; },
  turnScreenOff() { window.__bruecke('aus'); },
  turnScreenOn() { window.__bruecke('an'); },
  isScreenOn() { return false; } };"""


def _ms(dauer: timedelta) -> int:
    return int(dauer.total_seconds() * 1000)


def _app(ui: dict):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"sl": 0}
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"], "ui": ui}})
    return app


async def _visu(ui: dict, start: datetime, schritt, agent=False, bruecke=None):
    """Visu auf dem Geraet "wand", Uhr ab `start`. schritt(pg, ladungen) prueft;
    ladungen zaehlt jedes Laden der Seite. bruecke: Liste fuer die Aufrufe der
    nachgebauten App-Bruecke, None = ohne App."""
    app = _app(ui)
    if agent:
        app.agents["10.0.0.9"] = {"ip": "10.0.0.9", "name": "wand", "panel": "test", "port": 8130,
                                  "kiosk": True, "ts": time.time()}
    runner, port, bc = await visu_starten(app)
    fehler = []
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch()
            ctx = await b.new_context(viewport={"width": 800, "height": 480}, timezone_id="Europe/Berlin")
            await ctx.clock.install(time=start)
            if bruecke is not None:
                await ctx.expose_function("__bruecke", lambda aufruf: bruecke.append(aufruf))
                await ctx.add_init_script(BRUECKE_JS)
            pg = await ctx.new_page()
            pg.on("pageerror", lambda e: fehler.append(str(e)))
            ladungen = []
            pg.on("load", lambda _: ladungen.append(1))
            await pg.goto(f"http://127.0.0.1:{port}/?panel=test&device=wand")
            await pg.wait_for_function(EINGESTELLT)
            await schritt(pg, ladungen)
            await b.close()
    finally:
        bc.cancel()
        await runner.cleanup()
    assert not fehler, fehler


async def _kein_neuladen(pg, ladungen, dauer: timedelta):
    """Uhr um `dauer` vorstellen (faellige Zeitgeber laufen je einmal): Die
    Seite bleibt dieselbe."""
    vorher = len(ladungen)
    await pg.evaluate("window.__marke = 1")
    await pg.clock.fast_forward(_ms(dauer))
    await pg.wait_for_timeout(400)
    assert len(ladungen) == vorher, f"neu geladen um {await pg.evaluate('new Date().toString()')}"
    assert await pg.evaluate("window.__marke") == 1


async def _neuladen(pg, dauer: timedelta):
    """Uhr um `dauer` vorstellen: Die Seite laedt neu und bekommt wieder ihre
    Einstellungen."""
    async with pg.expect_event("load", timeout=5000):
        await pg.clock.fast_forward(_ms(dauer))
    await pg.wait_for_function(EINGESTELLT)


async def _zeit(pg) -> datetime:
    return datetime.fromtimestamp(await pg.evaluate("Date.now()") / 1000, BERLIN)


def test_ohne_eintrag_einmal_je_nacht():
    async def schritt(pg, ladungen):
        assert await pg.evaluate("DISP.reloadHours") is None
        assert await pg.evaluate("DISP.reloadAt") == W.NEULADEN_STUNDE
        nacht = ABEND.replace(hour=W.NEULADEN_STUNDE) + timedelta(days=1)
        await _kein_neuladen(pg, ladungen, nacht - await _zeit(pg) - timedelta(minutes=1))
        await _neuladen(pg, timedelta(minutes=2))
        assert len(ladungen) == 2
        # Die frische Seite wartet bis zur naechsten Nacht.
        await _kein_neuladen(pg, ladungen, timedelta(hours=23))
        await _neuladen(pg, timedelta(hours=1, minutes=2))
        assert len(ladungen) == 3 and (await _zeit(pg)).day == 4
    asyncio.run(_visu({}, ABEND, schritt))


def test_nicht_unter_den_fingern():
    async def schritt(pg, ladungen):
        nacht = ABEND.replace(hour=W.NEULADEN_STUNDE) + timedelta(days=1)
        await _kein_neuladen(pg, ladungen, nacht - await _zeit(pg) - timedelta(seconds=30))
        assert await pg.evaluate("saverOn()"), "nach einer Minute Ruhe steht die Uhr-Seite"
        await pg.mouse.click(400, 240)                    # jemand tippt: Uhr-Seite weg
        assert not await pg.evaluate("saverOn()")
        await _kein_neuladen(pg, ladungen, timedelta(seconds=40))
        assert await pg.evaluate("neuladenFaellig(Date.now())"), "faellig, aber in Benutzung"
        await pg.evaluate("window.__marke = 1; neuladenPruefen()")
        await pg.wait_for_timeout(400)
        assert len(ladungen) == 1 and await pg.evaluate("window.__marke") == 1
        # Eine Minute ohne Beruehrung: Die Uhr-Seite kommt zurueck, dann laedt sie.
        async with pg.expect_event("load", timeout=5000):
            await pg.clock.run_for(_ms(timedelta(minutes=2)))
    asyncio.run(_visu({}, ABEND, schritt))


def test_zahl_ist_ein_abstand_statt_nachts():
    async def schritt(pg, ladungen):
        await _kein_neuladen(pg, ladungen, timedelta(hours=5, minutes=1))    # 03:01: nicht nachts
        await _kein_neuladen(pg, ladungen, timedelta(hours=6, minutes=58))   # 09:59
        await _neuladen(pg, timedelta(minutes=2))                            # 12 h nach dem Laden
        assert len(ladungen) == 2
        await _kein_neuladen(pg, ladungen, timedelta(hours=11, minutes=58))
        await _neuladen(pg, timedelta(minutes=3))                            # 12 h nach dem Neuladen
    asyncio.run(_visu({"reloadHours": 12}, ABEND, schritt))


def test_null_nie():
    async def schritt(pg, ladungen):
        assert await pg.evaluate("DISP.reloadHours") == 0
        await _kein_neuladen(pg, ladungen, timedelta(hours=5, minutes=1))
        await _kein_neuladen(pg, ladungen, timedelta(days=3))
    asyncio.run(_visu({"reloadHours": 0}, ABEND, schritt))


def test_mit_agent_nie():
    """Der Agent startet den Browser selbst neu (seine kiosk.conf)."""
    async def schritt(pg, ladungen):
        assert await pg.evaluate("DISP.agent") is True
        await _kein_neuladen(pg, ladungen, timedelta(hours=5, minutes=1))
        await _kein_neuladen(pg, ladungen, timedelta(days=1))
    asyncio.run(_visu({}, ABEND, schritt, agent=True))


def test_app_bleibt_dunkel():
    aufrufe = []

    async def schritt(pg, ladungen):
        await pg.wait_for_timeout(300)
        assert "saver:true" in aufrufe and "dpms:60" in aufrufe, aufrufe
        nacht = ABEND.replace(hour=W.NEULADEN_STUNDE) + timedelta(days=1)
        await _kein_neuladen(pg, ladungen, nacht - await _zeit(pg) - timedelta(minutes=1))
        aufrufe.clear()
        await _neuladen(pg, timedelta(minutes=2))
        await pg.wait_for_timeout(300)
        assert "saver:true" in aufrufe and "dpms:60" in aufrufe, aufrufe
        assert "an" not in aufrufe and "saver:false" not in aufrufe, f"Neuladen weckt das Display: {aufrufe}"
    asyncio.run(_visu({"dpmsOff": 60}, ABEND, schritt, bruecke=aufrufe))


@pytest.mark.parametrize("sprache, grau, hinweis", [
    ("de-DE", f"nachts um {W.NEULADEN_STUNDE} Uhr", f"jede Nacht um {W.NEULADEN_STUNDE} Uhr"),
    ("en-US", f"at night at {W.NEULADEN_STUNDE}:00", f"every night at {W.NEULADEN_STUNDE}:00"),
])
def test_konfigurator_nennt_die_stunde(sprache, grau, hinweis):
    async def lauf():
        app = _app({})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale=sprache)
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator("#plist .pitem", has_text="Test").click()
                await pg.locator('.stab[data-sub="verhalten"]').click()
                feld = pg.locator('#pconfHost input[data-ui="reloadHours"]')
                assert await feld.get_attribute("placeholder") == grau
                assert await feld.input_value() == ""
                erklaerung = pg.locator("#pconfHost .hint", has_text=hinweis)
                assert await erklaerung.count() == 1 and await erklaerung.is_visible()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
