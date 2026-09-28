"""Alte Raumregelung (IRoomController, v1) in Chromium: Kachel antippen,
Detailseite bedienen, die Befehle kommen beim Miniserver-Nachbau an. Die
Struktur kommt aus tests/lox.py (irc1_baustein)."""
import asyncio

import pytest

from lox import Miniserver, W, anlage, irc1_baustein, neue_app, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser


def test_bedienung_kommt_am_miniserver_an(tmp_path, miniserver_http):
    async def lauf():
        ms = await Miniserver().start()
        app = neue_app(ms)
        control, states = irc1_baustein(valveHeat=1)
        control["isFavorite"] = True
        app._apply_structure(anlage({"IRC": control}))
        app.states = states
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
                await pg.wait_for_timeout(1200)
                kachel = pg.locator(".tile", has_text="Wohnzimmer Heizung")
                assert "20,5° → 22,0° · heizt" in await kachel.text_content()
                await pg.screenshot(path=str(tmp_path / "irc1_kachel.png"))
                await kachel.click()
                await pg.wait_for_timeout(800)
                await pg.screenshot(path=str(tmp_path / "irc1_detail.png"))
                for text, befehl in (("+", "settemp/1/22.5"), ("Komfort", "starttimer/1/3600"),
                                     ("Automatik", "stoptimer")):
                    await pg.locator(".brow .btn", has_text=text).first.click()
                    await pg.wait_for_timeout(600)
                    assert ms.io[-1] == f"sps/io/IRC/{befehl}", (text, ms.io)
                assert len(ms.io) == 3
                await b.close()
        finally:
            bc.cancel()
            await app.icon_session.close()
            await runner.cleanup()
            await ms.stop()
        assert not fehler, fehler
    asyncio.run(lauf())
