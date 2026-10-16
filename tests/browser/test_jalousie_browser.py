"""Jalousie in Chromium: Position und Lamellen per Schieberegler kommen als
manualPosition bzw. manualLamelle beim Miniserver-Nachbau an, die Automatik
schaltet mit NoAuto ab; die Zentral-Jalousie faehrt alle mit FullDown."""
import asyncio

import pytest

from lox import Miniserver, W, anlage, jalousie_baustein, neue_app, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

SCHIEBEN = """([i, w]) => { const s = document.querySelectorAll('#grid .sld')[i]; s.value = w;
  s.dispatchEvent(new Event('input')); s.dispatchEvent(new Event('change')); }"""


def test_jalousie_regler_und_automatik(tmp_path, miniserver_http):
    async def lauf():
        ms = await Miniserver().start()
        app = neue_app(ms)
        ja, st = jalousie_baustein()
        zentral = {"name": "Alle Jalousien", "type": "CentralJalousie", "uuidAction": "ZJ", "room": "r1",
                   "cat": "c1", "states": {}, "details": {"controls": [{"uuid": "JA", "id": 1}]}}
        for c in (ja, zentral):
            c["isFavorite"] = True
        app._apply_structure(anlage({"JA": ja, "ZJ": zentral}))
        app.states = st
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"]}})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 480, "height": 800})
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_timeout(600)
                await pg.evaluate("wake()")
                await pg.wait_for_timeout(1200)

                await pg.evaluate("nav({view: 'control', id: 'JA'})")
                await pg.wait_for_selector("#grid .sld")
                await pg.screenshot(path=str(tmp_path / "jalousie.png"))
                assert await pg.locator("#grid .sld").count() == 2
                await pg.evaluate(SCHIEBEN, [0, 70])
                await pg.wait_for_timeout(400)
                await pg.evaluate(SCHIEBEN, [1, 20])
                await pg.wait_for_timeout(400)
                await pg.locator(".btn", has_text="Automatik").click()
                await pg.wait_for_timeout(500)
                assert ms.io == ["sps/io/JA/manualPosition/70", "sps/io/JA/manualLamelle/20", "sps/io/JA/NoAuto"]
                await pg.evaluate("back()")
                await pg.wait_for_timeout(600)

                await pg.evaluate("nav({view: 'control', id: 'ZJ'})")
                await pg.wait_for_selector(".btn:has-text('Ganz Ab')")
                await pg.screenshot(path=str(tmp_path / "zentral_jalousie.png"))
                await pg.locator(".btn", has_text="Ganz Ab").click()
                await pg.wait_for_timeout(500)
                assert ms.io[-1] == "sps/io/ZJ/FullDown", ms.io
                await b.close()
        finally:
            bc.cancel()
            await app.icon_session.close()
            await runner.cleanup()
            await ms.stop()
        assert not fehler, fehler
    asyncio.run(lauf())
