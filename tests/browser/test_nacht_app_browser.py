"""Nachtmodus mit der LoxPanel-App (JS-Bruecke LoxKiosk) in Chromium. Die App
senkt nachts die echte Helligkeit (setDisplayBrightness) statt der dunklen
Auflage der Visu; bei automatischer Helligkeit lehnt sie ab, dann dunkelt wie
bisher die Auflage. Die Bruecke ist nachgebaut und protokolliert jeden
Aufruf."""
import asyncio

import pytest

from lox import W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "LA", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}}}
# Bruecke der App: __auto = automatische Helligkeit am Geraet (die App lehnt ab)
APP_JS = """window.__hell = []; window.__auto = %s; window.LoxKiosk = { _an: true,
  setDisplayOff(s) {}, turnScreenOff() { this._an = false; }, turnScreenOn() { this._an = true; },
  isScreenOn() { return this._an; },
  setDisplayBrightness(p) { window.__hell.push(p); return !window.__auto; } };"""
# App-Stand vor diesem Beitrag: ohne setDisplayBrightness
ALTE_APP_JS = """window.LoxKiosk = { _an: true, setDisplayOff(s) {},
  turnScreenOff() { this._an = false; }, turnScreenOn() { this._an = true; },
  isScreenOn() { return this._an; } };"""


def _app(nacht: list):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"sl": 0}
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"],
                                                  "ui": {"nightDim": 70, "nightWake": 1}}})
    app._night_now = lambda: nacht[0]
    app._night_on = nacht[0]          # schon beim Verbinden Nacht (theme), kein Wechsel im Takt
    return app


def test_app_senkt_die_echte_helligkeit(tmp_path):
    async def lauf():
        nacht = [True]
        app = _app(nacht)
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()

                async def panel(skript):
                    ctx = await b.new_context(viewport={"width": 480, "height": 480})
                    if skript:
                        await ctx.add_init_script(skript)
                    pg = await ctx.new_page()
                    pg.on("pageerror", lambda e: fehler.append(str(e)))
                    await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                    await pg.wait_for_function("document.getElementById('nightdim')")
                    return pg

                async def auflage(pg):
                    return await pg.evaluate("document.getElementById('nightdim').style.opacity")

                app_pg = await panel(APP_JS % "false")
                auto_pg = await panel(APP_JS % "true")
                alt_pg = await panel(ALTE_APP_JS)
                browser_pg = await panel(None)
                await app_pg.wait_for_timeout(500)
                stand = {"nacht": (await app_pg.evaluate("__hell"), await auflage(app_pg)),
                         "auto": (await auto_pg.evaluate("__hell"), await auflage(auto_pg)),
                         "alt": await auflage(alt_pg), "browser": await auflage(browser_pg)}
                await app_pg.screenshot(path=str(tmp_path / "nacht_app.png"))
                await auto_pg.screenshot(path=str(tmp_path / "nacht_auto.png"))

                # Beruehrung: kurz Systemhelligkeit, nach nightWake (1 s) wieder gedimmt
                await app_pg.evaluate("document.dispatchEvent(new PointerEvent('pointerdown'))")
                await app_pg.wait_for_timeout(300)
                stand["beruehrt"] = await app_pg.evaluate("__hell.slice()")
                await app_pg.wait_for_timeout(1200)
                stand["danach"] = await app_pg.evaluate("__hell.slice()")

                # Tag: Systemhelligkeit, keine Auflage
                nacht[0] = False
                await app_pg.wait_for_timeout(800)
                stand["tag"] = (await app_pg.evaluate("__hell"), await auflage(app_pg),
                                await auflage(browser_pg))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return stand
    stand = asyncio.run(lauf())

    assert stand["nacht"] == ([7], "0"), "70 % abdunkeln: 7 % Helligkeit in der App, keine Auflage"
    assert stand["auto"] == ([7], "0.7"), "automatische Helligkeit: App lehnt ab, Auflage wie bisher"
    assert stand["alt"] == "0.7" and stand["browser"] == "0.7", "aeltere App und Browser wie bisher"
    assert stand["beruehrt"] == [7, 100], "Beruehrung: kurz die Systemhelligkeit"
    assert stand["danach"] == [7, 100, 7], "nach der Aufhellzeit wieder gedimmt"
    assert stand["tag"] == ([7, 100, 7, 100], "0", "0"), "Tag: Systemhelligkeit, keine Auflage"


@pytest.mark.parametrize("abdunkeln, prozent", [(10, 79), (30, 46), (50, 22), (70, 7), (90, 1)])
def test_gleiche_leuchtdichte_wie_die_auflage(abdunkeln, prozent):
    """Die Auflage wirkt auf die Farbwerte (sRGB): Leuchtdichte (1 - a)^2,2. Die
    App bekommt denselben Anteil, mindestens 1 %."""
    async def lauf():
        app = _app([True])
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"],
                                                      "ui": {"nightDim": abdunkeln}}})
        runner, port, bc = await visu_starten(app)
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": 480, "height": 480})
                await ctx.add_init_script(APP_JS % "false")
                pg = await ctx.new_page()
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_function("__hell.length > 0")
                hell = await pg.evaluate("__hell")
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        return hell
    assert asyncio.run(lauf()) == [prozent]
    assert prozent == max(1, round(100 * (1 - abdunkeln / 100) ** 2.2))
