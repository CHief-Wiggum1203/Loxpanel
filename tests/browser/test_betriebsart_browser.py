"""Betriebsart der Raumregelung in Chromium: Aufklapper oeffnen, Betriebsart
waehlen, der Befehl kommt beim Miniserver-Nachbau an - fuer V2
(setOperatingMode/<Nr>) und die alte Raumregelung (mode/<Nr>)."""
import asyncio

import pytest

from lox import Miniserver, W, anlage, irc1_baustein, irc2_baustein, neue_app, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser


def test_betriebsart_waehlen_kommt_am_miniserver_an(tmp_path, miniserver_http):
    async def lauf():
        ms = await Miniserver().start()
        app = neue_app(ms)
        c1, s1 = irc1_baustein()
        c2, s2 = irc2_baustein()
        for c in (c1, c2):
            c["isFavorite"] = True
        app._apply_structure(anlage({"IRC": c1, "IRC2": c2}))
        app.states = {**s1, **s2}
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
                for kachel, eintrag, befehl in (("Bad Heizung", "Manuell nur Heizen", "sps/io/IRC2/setOperatingMode/4"),
                                                ("Wohnzimmer Heizung", "Manuell Heizen", "sps/io/IRC/mode/5")):
                    await pg.locator(".tile", has_text=kachel).click()
                    await pg.wait_for_timeout(800)
                    await pg.locator(".brow .btn.toggler", has_text="Betriebsart").click()
                    await pg.wait_for_timeout(300)
                    await pg.screenshot(path=str(tmp_path / f"betriebsart_{kachel.split()[0]}.png"))
                    await pg.locator(".menuitem", has_text=eintrag).first.click()
                    await pg.wait_for_timeout(600)
                    assert ms.io[-1] == befehl, (kachel, ms.io)
                    assert await pg.locator(".menuov").count() == 0, "Aufklapper schliesst nach der Wahl"
                    await pg.evaluate("back()")
                    await pg.wait_for_timeout(600)
                assert len(ms.io) == 2
                await b.close()
        finally:
            bc.cancel()
            await app.icon_session.close()
            await runner.cleanup()
            await ms.stop()
        assert not fehler, fehler
    asyncio.run(lauf())
