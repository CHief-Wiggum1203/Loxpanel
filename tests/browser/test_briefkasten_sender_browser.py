"""Briefkasten und Sender in Chromium: "Post entnommen" auf der Detailseite des
Briefkastens kommt beim Miniserver-Nachbau als confirmMail an, ein
Sender-Cover auf der Detailseite der Audio-Zone spielt ab (roomfav/play) und
laesst die Seite stehen (bleiben), statt zurueckzuspringen wie in der
Musikauswahl. Anlage: lox.haus_anlage() mit dem Briefkasten aus
briefkasten_baustein()."""
import asyncio

import pytest

from lox import Miniserver, W, briefkasten_baustein, haus_anlage, neue_app, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser


def test_briefkasten_und_sender_bedienen(tmp_path, miniserver_http):
    async def lauf():
        ms = await Miniserver().start()
        app = neue_app(ms)
        struktur, states = haus_anlage()
        mb, mb_states = briefkasten_baustein(post=1, eintraege="16.10.2026 08:12 Post eingeworfen")
        struktur["controls"]["MB"] = mb
        for u in ("MB", "AZ"):
            struktur["controls"][u]["isFavorite"] = True
        app._apply_structure(struktur)
        app.states = {**states, **mb_states}
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"]}})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 800, "height": 480})
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_timeout(600)
                await pg.evaluate("wake()")
                await pg.wait_for_timeout(1200)

                await pg.locator(".tile", has_text="Postkasten").click()
                await pg.wait_for_selector(".btn:has-text('Post entnommen')")
                await pg.screenshot(path=str(tmp_path / "briefkasten.png"))
                assert await pg.locator(".btn", has_text="24 h").count() == 1
                await pg.locator(".btn", has_text="Post entnommen").click()
                await pg.wait_for_timeout(600)
                assert ms.io[-1] == "sps/io/MB/confirmMail", ms.io
                await pg.locator(".btn", has_text="Verlauf").click()
                await pg.wait_for_timeout(600)
                assert await pg.evaluate("stack[stack.length-1].view") == "verlauf"
                await pg.screenshot(path=str(tmp_path / "briefkasten_verlauf.png"))
                await pg.evaluate("back()")
                await pg.wait_for_timeout(400)
                await pg.evaluate("back()")
                await pg.wait_for_timeout(600)

                # auf das Symbol tippen: mitten auf der Kachel liegen die Transporttasten
                await pg.locator(".tile", has_text="Essen-Kochen-Wohnen").click(position={"x": 40, "y": 40})
                await pg.wait_for_selector(".favs .fav")
                await pg.screenshot(path=str(tmp_path / "zone_sender.png"))
                tiefe = await pg.evaluate("stack.length")
                await pg.locator(".favs .fav").nth(1).click()
                await pg.wait_for_timeout(800)
                assert ms.io[-1] == "sps/io/AZ/roomfav/play/2", ms.io
                assert await pg.evaluate("stack.length") == tiefe, "Detailseite bleibt nach dem Abspielen offen"
                assert await pg.evaluate("stack[stack.length-1].view") == "control"
                await b.close()
        finally:
            bc.cancel()
            await app.icon_session.close()
            await runner.cleanup()
            await ms.stop()
        assert not fehler, fehler
    asyncio.run(lauf())
