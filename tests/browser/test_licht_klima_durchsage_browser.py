"""Neue Seiten in Chromium, jeweils bis zum Befehl am Miniserver-Nachbau:
Lichtsteuerung (beschrifteter Regler eines Lichtkreises, Lieblingsstimmung,
naechste Stimmung), Einstellungen der Raumregelung (Komfort Heizen um
0,5 °C hoeher) und die Durchsage einer Audio-Zone (Text URL-kodiert gesendet)."""
import asyncio

import pytest

from lox import (Miniserver, W, anlage, haus_anlage, irc2_baustein, lichtsteuerung_baustein, neue_app,
                 visu_starten)

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

SCHIEBEN = """([i, w]) => { const s = document.querySelectorAll('#grid .sld')[i]; s.value = w;
  s.dispatchEvent(new Event('input')); s.dispatchEvent(new Event('change')); }"""


def test_licht_einstellungen_durchsage(tmp_path, miniserver_http):
    async def lauf():
        ms = await Miniserver().start()
        app = neue_app(ms)
        lv, lv_st = lichtsteuerung_baustein()
        irc, irc_st = irc2_baustein()
        struktur, haus_st = haus_anlage()
        app._apply_structure(anlage({"LV": lv, "IRC2": irc, "AZ": struktur["controls"]["AZ"]}))
        app.states = {**lv_st, **irc_st, **haus_st}
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"]}})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 480, "height": 900})
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_timeout(600)
                await pg.evaluate("wake()")
                await pg.wait_for_timeout(1200)

                await pg.evaluate("nav({view: 'control', id: 'LV'})")
                await pg.wait_for_selector("#grid .slbl")
                await pg.screenshot(path=str(tmp_path / "lichtsteuerung.png"))
                assert await pg.locator("#grid .slbl").all_text_contents() == ["Helligkeit", "Esstisch", "Stripe"]
                await pg.evaluate(SCHIEBEN, [1, 80])
                await pg.wait_for_timeout(400)
                await pg.locator(".btn", has_text="Hell").click()
                await pg.wait_for_timeout(400)
                assert ms.io == ["sps/io/LV-1/80", "sps/io/LV/changeTo/1"], ms.io
                await pg.evaluate("back()")
                await pg.wait_for_timeout(500)

                await pg.evaluate("nav({view: 'ircset', id: 'IRC2'})")
                await pg.wait_for_selector(".stp")
                await pg.screenshot(path=str(tmp_path / "raumregelung_einstellungen.png"))
                stp = pg.locator(".stp", has_text="Komfort Heizen")
                await stp.locator(".sbtn[data-st='1']").click()
                assert (await stp.locator(".stpv").text_content()) == "23 °C"
                await pg.wait_for_timeout(1500)
                assert ms.io[-1] == "sps/io/IRC2/setComfortTemperature/23", ms.io
                await pg.evaluate("back()")
                await pg.wait_for_timeout(500)

                await pg.evaluate("nav({view: 'durchsage', id: 'AZ'})")
                await pg.wait_for_selector(".fld input")
                await pg.locator(".fld input").fill("Essen ist fertig")
                await pg.locator(".btn", has_text="Sprechen").click()
                await pg.wait_for_timeout(600)
                # die Visu kodiert den Text, der Miniserver(-Nachbau) dekodiert den Pfad
                assert ms.io[-1] == "sps/io/AZ/tts/Essen ist fertig", ms.io
                await b.close()
        finally:
            bc.cancel()
            await app.icon_session.close()
            await runner.cleanup()
            await ms.stop()
        assert not fehler, fehler
    asyncio.run(lauf())
