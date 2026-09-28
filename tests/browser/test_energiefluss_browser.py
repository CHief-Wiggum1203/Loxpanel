"""Energiefluss in Chromium: die Fusszeile unter dem Radial zeigt Erzeugung und
den Hausverbrauch aus der Bilanz; ist der Verbrauch unbekannt (kein Netzwert),
fehlt er, statt "0 W" zu zeigen - auch beim Live-Nachzug."""
import asyncio

import pytest

from lox import EM2, W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser


def test_fusszeile_verbrauch(tmp_path):
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage({"M": dict(EM2, isFavorite=True)}))
        app.states = {"m-p": 3.2, "m-g": 0.3, "m-s": 2.0, "m-soc": 64}
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"]}})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 480, "height": 480})
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_timeout(600)
                await pg.evaluate("wake()")
                await pg.wait_for_timeout(1000)
                await pg.evaluate("nav({view:'control', id:'M'})")
                await pg.wait_for_timeout(1000)
                fuss = pg.locator(".ebot")
                assert await fuss.text_content() == "Erzeugung 3,2 kW · Verbrauch 5,5 kW"
                await pg.screenshot(path=str(tmp_path / "energiefluss_verbrauch.png"))
                app.states["m-g"] = None          # Netzwert weg -> Verbrauch unbekannt
                app._dirty = True
                await pg.wait_for_timeout(1200)
                assert await fuss.text_content() == "Erzeugung 3,2 kW"
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
