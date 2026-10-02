"""Praesenzmelder mit der LoxPanel-App (JS-Bruecke LoxKiosk) in Chromium. Die
App hat einen eigenen Bildschirmschoner (setDisplayOff); solange der Melder
des Geraets jemanden sieht, muss die Visu ihn aussetzen (0), sonst dunkelt die
App trotz Anwesenheit ab. Die Bruecke ist nachgebaut und protokolliert jeden
Aufruf."""
import asyncio

import pytest

from lox import W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {
    "PM": {"name": "Präsenz Küche", "type": "PresenceDetector", "uuidAction": "PM", "room": "r1", "cat": "c1",
           "states": {"active": "pm_a", "infoText": "pm_t"}},
    "L": {"name": "Licht", "type": "Switch", "uuidAction": "LA", "room": "r1", "cat": "c1", "isFavorite": True,
          "states": {"active": "sl"}},
}
# JS-Bruecke der LoxPanel-App (KioskActivity.KioskBridge), nachgebaut
LOXKIOSK_JS = """window.__lox = []; window.LoxKiosk = { _an: true,
  setDisplayOff(s) { window.__lox.push('schoner:' + s); },
  turnScreenOff() { this._an = false; window.__lox.push('aus'); },
  turnScreenOn() { this._an = true; window.__lox.push('an'); },
  isScreenOn() { return this._an; } };"""


def _app():
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"pm_a": 1.0, "sl": 0}              # jemand ist im Raum
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"],
                                                  "ui": {"dpmsOff": 1}}})
    app.devices = W.App._sanitize_devices({"kueche": {"presence": "PM"}}, set(app.panels))
    app._presence_rebuild()
    app._pending_presence.clear()
    return app


def test_app_schoner_folgt_dem_melder(tmp_path):
    async def lauf():
        app = _app()
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()

                async def panel(geraet):
                    ctx = await b.new_context(viewport={"width": 480, "height": 480})
                    await ctx.add_init_script(LOXKIOSK_JS)
                    pg = await ctx.new_page()
                    pg.on("pageerror", lambda e: fehler.append(str(e)))
                    await pg.goto(f"http://127.0.0.1:{port}/?panel=test&device={geraet}")
                    return pg

                kueche, flur = await panel("kueche"), await panel("flur")
                await kueche.wait_for_timeout(2500)          # mehr als die Leerlaufzeit (1 s)
                stand = {"start": await kueche.evaluate("__lox"), "flur": await flur.evaluate("__lox")}
                app._on_value("pm_a", 0.0)                    # Raum leer
                await kueche.wait_for_timeout(800)
                stand["leer"] = await kueche.evaluate("__lox")
                app._on_value("pm_a", 1.0)                    # jemand kommt
                await kueche.wait_for_timeout(800)
                stand["wieder"] = await kueche.evaluate("__lox")
                await kueche.reload()
                await kueche.wait_for_timeout(1500)
                stand["neu_geladen"] = await kueche.evaluate("__lox")
                # Melder im Konfigurator entfernt, waehrend jemand da ist: die
                # Kopplung baut sich im naechsten Takt neu, der Schoner kehrt zurueck
                app.devices = W.App._sanitize_devices({}, set(app.panels))
                await kueche.wait_for_timeout(800)
                stand["entfernt"] = await kueche.evaluate("__lox")
                await kueche.screenshot(path=str(tmp_path / "praesenz_app.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return stand
    stand = asyncio.run(lauf())

    assert stand["flur"] == ["schoner:1"], "ohne Melder: Leerlaufzeit an die App, die Seite schaltet nicht selbst"
    assert stand["start"] == ["schoner:0"], "jemand da: Schoner der App ausgesetzt"
    assert stand["leer"] == ["schoner:0", "schoner:1", "aus"], "Raum leer: Leerlaufzeit zurueck, dunkel"
    assert stand["wieder"] == ["schoner:0", "schoner:1", "aus", "schoner:0", "an"], "jemand kommt: wach, gehalten"
    assert stand["neu_geladen"] == ["schoner:0"], "nach Neuladen gilt die Anwesenheit sofort"
    assert stand["entfernt"] == ["schoner:0", "schoner:1"], "ohne Melder wieder die Leerlaufzeit, kein Abschalten"
