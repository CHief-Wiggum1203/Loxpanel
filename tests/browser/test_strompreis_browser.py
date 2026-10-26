"""Strompreis-Optimierer in Chromium: Kachel mit Preis, Detailseite mit den
Diagrammen der Prognose (Preis, eingeplante Zeiten), einen Zyklus mit anderem
Bedarf starten und ihn abbrechen. Bedarf und Zeitraum sind Stepper eines
Formulars (name statt cmd): sie zaehlen in der Visu, gehen erst mit "Zyklus
starten" an den Miniserver-Nachbau und behalten den getippten Wert, auch wenn
der Server die Seite inzwischen neu schickt."""
import asyncio
import json

import pytest

from bausteine.gemeinsam import LOX_EPOCH_UTC
from lox import Miniserver, W, anlage, neue_app, visu_starten
from test_strompreis_optimierer import GET_FORECASTS, PROGNOSE, STUNDE, _baustein

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser


async def _befehle(ms, anzahl, warten=3.0) -> list[str]:
    for _ in range(int(warten / 0.05)):
        if len(ms.io_roh) >= anzahl:
            break
        await asyncio.sleep(0.05)
    return list(ms.io_roh)


def test_zyklus_starten_und_abbrechen(tmp_path, miniserver_http):
    async def lauf():
        ms = await Miniserver().start()
        ms.system = {GET_FORECASTS: ("200", json.dumps(PROGNOSE))}
        app = neue_app(ms)
        control, states = _baustein()
        app._apply_structure(anlage({"SPO": {**control, "isFavorite": True}}))
        app.states = states
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
                kachel = pg.locator(".tile", has_text="Boiler").first
                await kachel.wait_for()
                assert "0,245 €/kWh" in await kachel.inner_text()
                await kachel.click()
                # Prognose: erst der Hinweis, dann beide Diagramme (nach dem Abruf im Hintergrund)
                await pg.wait_for_function("document.querySelectorAll('.chart svg').length === 2", timeout=5000)
                legende = await pg.locator(".chleg").all_inner_texts()
                assert legende[0].startswith("Preis · min 0,104 · max 0,312 €/kWh"), legende
                assert legende[1] == "Eingeplant · Ein 2 h", legende
                await pg.screenshot(path=str(tmp_path / "strompreis.png"), full_page=True)

                bedarf = pg.locator(".stp", has_text="Bedarf")
                assert await bedarf.locator(".stpv").inner_text() == "4 h"
                for _ in range(2):
                    await bedarf.locator('.sbtn[data-st="1"]').click()
                assert await bedarf.locator(".stpv").inner_text() == "4,5 h"
                await pg.wait_for_timeout(1300)          # laenger als STP_SENDEN_MS: ein Formular-Stepper schickt nichts
                assert ms.io_roh == []
                # der Server schickt die Seite neu (neuer Preis): der getippte Bedarf bleibt
                app._on_value("sp-current", 0.1987)
                await pg.wait_for_function("(document.querySelector('.pbig')||{}).textContent === '0,199 €/kWh'", timeout=5000)
                assert await bedarf.locator(".stpv").inner_text() == "4,5 h"
                await pg.locator(".brow .btn", has_text="Zyklus starten").click()
                assert await _befehle(ms, 1) == ["sps/io/SPO/start/4.5/24"]

                # Zyklus laeuft: abbrechen, mit Rueckfrage
                app._on_value("sp-cycleUntil", STUNDE + 4 * 3600 - LOX_EPOCH_UTC)
                abbrechen = pg.locator(".brow .btn", has_text="Zyklus abbrechen")
                await abbrechen.wait_for(timeout=5000)
                await abbrechen.click()
                assert await pg.locator(".brow .btn.arm").inner_text() == "Zyklus wirklich abbrechen?"
                assert len(ms.io_roh) == 1
                await pg.locator(".brow .btn.arm").click()
                assert (await _befehle(ms, 2))[-1] == "sps/io/SPO/cancel"
                await b.close()
        finally:
            bc.cancel()
            await app.icon_session.close()
            await runner.cleanup()
            await ms.stop()
        assert not fehler, fehler
    asyncio.run(lauf())
