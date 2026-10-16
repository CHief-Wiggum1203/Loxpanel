"""Neue Bedienung in Chromium: Der Revisionsmodus des Rauchmelders fragt
beim ersten Tipp nach und schickt servicemode erst beim zweiten; die
maximale Speicherleistung des Energiemanagers zaehlt in 0,5-kW-Schritten,
zeigt "5,5 kW" und schickt setMaxSpwr/5.5 ohne Rechenrest. Beides kommt beim
Miniserver-Nachbau an."""
import asyncio

import pytest

from lox import Miniserver, W, anlage, energiemanager_baustein, neue_app, rauchmelder_baustein, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser


def test_revisionsmodus_und_speicherleistung(tmp_path, miniserver_http):
    async def lauf():
        ms = await Miniserver().start()
        app = neue_app(ms)
        sm, sm_states = rauchmelder_baustein()
        em, em_states = energiemanager_baustein()
        for c in (sm, em):
            c["isFavorite"] = True
        app._apply_structure(anlage({"SM": sm, "EM": em}))
        app.states = {**sm_states, **em_states}
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"]}})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 800, "height": 800})
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_timeout(600)
                await pg.evaluate("wake()")
                await pg.wait_for_timeout(1200)

                await pg.evaluate("nav({view: 'control', id: 'SM'})")
                await pg.wait_for_selector(".btn:has-text('1 h')")
                await pg.screenshot(path=str(tmp_path / "rauchmelder.png"))
                await pg.locator(".btn", has_text="1 h").click()
                await pg.wait_for_timeout(400)
                assert ms.io == [], "erster Tipp fragt nur nach"
                await pg.locator(".btn", has_text="Melder aussetzen?").click()
                await pg.wait_for_timeout(600)
                assert ms.io == ["sps/io/SM/servicemode/3600"], ms.io
                await pg.evaluate("back()")
                await pg.wait_for_timeout(600)

                await pg.evaluate("nav({view: 'control', id: 'EM'})")
                await pg.wait_for_selector(".stp")
                await pg.screenshot(path=str(tmp_path / "energiemanager.png"))
                stp = pg.locator(".stp", has_text="Max. Speicherleistung")
                assert (await stp.locator(".stpv").text_content()) == "5 kW"
                await stp.locator(".sbtn[data-st='1']").click()
                assert (await stp.locator(".stpv").text_content()) == "5,5 kW"
                await pg.wait_for_timeout(1500)
                assert ms.io[-1] == "sps/io/EM/setMaxSpwr/5.5", ms.io
                await b.close()
        finally:
            bc.cancel()
            await app.icon_session.close()
            await runner.cleanup()
            await ms.stop()
        assert not fehler, fehler
    asyncio.run(lauf())
