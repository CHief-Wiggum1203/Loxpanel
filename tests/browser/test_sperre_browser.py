"""Gesperrte Bausteine (jLocked) in Chromium gegen den Miniserver-Nachbau.

Die Kachel nennt "Gesperrt" und oeffnet die Detailseite statt zu schalten.
Dort steht oben, wer gesperrt hat und warum; Regler und Tasten des Bausteins
sind gedimmt und ohne Wirkung, ein echter Klick erreicht den Miniserver nicht.
Die verlinkten Objekte (andere Bausteine) bleiben bedienbar. Hebt die Logik
die Sperre auf, ist die Seite sofort wieder bedienbar."""
import asyncio
import json

import pytest

from lox import anlage, Miniserver, neue_app, visu_starten, W

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

TEXT = "Gesperrt durch die Logik: Wartung"
DIMMER = {"name": "Flur Dimmer", "type": "Dimmer", "uuidAction": "DIM", "room": "r1", "cat": "c1",
          "isFavorite": True, "details": {"jLockable": True}, "links": ["SW"],
          "states": {"position": "dim-p", "min": "dim-mn", "max": "dim-mx", "step": "dim-st",
                     "jLocked": "dim-lock"}}
SCHALTER = {"name": "Flur Licht", "type": "Switch", "uuidAction": "SW", "room": "r1", "cat": "c1",
            "states": {"active": "sw-a"}}


async def _warten(bedingung, sekunden=3.0):
    for _ in range(int(sekunden / 0.05)):
        if bedingung():
            return True
        await asyncio.sleep(0.05)
    return bedingung()


async def _stil(pg, sel):
    return await pg.evaluate("""s => { const e=document.querySelector(s); if(!e) return null;
        const c=getComputedStyle(e); return {opacity: c.opacity, pe: c.pointerEvents}; }""", sel)


def test_gesperrter_baustein_in_der_visu(tmp_path, miniserver_http):
    async def lauf():
        ms = Miniserver()
        await ms.start()
        app = neue_app(ms)
        app._apply_structure(anlage({"DIM": DIMMER, "SW": SCHALTER}))
        app.states = {"dim-p": 40, "dim-mn": 0, "dim-mx": 100, "dim-st": 1, "sw-a": 1,
                      "dim-lock": json.dumps({"locked": 2, "reason": "Wartung"})}
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"]}})
        runner, port, bc = await visu_starten(app)
        fehler, erg = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 480, "height": 480})
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector('#grid .tile[data-id="DIM"]')
                await pg.evaluate("wake()")
                await pg.wait_for_timeout(400)
                erg["kachel"] = await pg.locator('#grid .tile[data-id="DIM"] .sub').inner_text()
                await pg.screenshot(path=str(tmp_path / "sperre_kachel.png"))
                await pg.locator('#grid .tile[data-id="DIM"]').click()
                await pg.wait_for_selector("#grid.panel .srow")
                erg["route"] = await pg.evaluate("view.route")
                erg["klasse"] = await pg.evaluate("el('grid').classList.contains('gesperrt')")
                erg["status"] = await pg.locator("#grid .status").all_inner_texts()
                erg["regler"] = await _stil(pg, "#grid .srow")
                await pg.screenshot(path=str(tmp_path / "sperre_detail.png"))
                erg["link"] = await _stil(pg, '#grid .brow[data-rowid="links:DIM"] .btn')
                # echter Mausklick auf "+": geht durch den gedimmten Regler hindurch
                box = await pg.locator('#grid .srow .sbtn[data-sd="up"]').bounding_box()
                await pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                await pg.wait_for_timeout(600)
                erg["nach_klick"] = list(ms.io)
                # an der Visu vorbei geschickt: der Server lehnt ab und sagt warum
                await pg.evaluate("send({t:'cmd', uuid:'DIM', cmd:'100'})")
                await pg.wait_for_selector("text=" + TEXT, timeout=3000)
                await pg.locator('#grid .brow[data-rowid="links:DIM"] .btn').click()
                erg["link_io"] = await _warten(lambda: "sps/io/SW/off" in ms.io)
                # Sperre aufgehoben: die Seite ist sofort wieder bedienbar
                app.states["dim-lock"] = ""
                app._dirty = True
                await pg.wait_for_function("!el('grid').classList.contains('gesperrt')", timeout=3000)
                erg["status_frei"] = await pg.locator("#grid .status").all_inner_texts()
                erg["regler_frei"] = await _stil(pg, "#grid .srow")
                await b.close()
        finally:
            bc.cancel()
            await app.icon_session.close()
            await runner.cleanup()
            await ms.stop()
        return fehler, erg, list(ms.io)
    fehler, erg, io = asyncio.run(lauf())
    assert not fehler, fehler
    assert erg["kachel"] == "Gesperrt"
    assert erg["route"] == {"view": "control", "id": "DIM"} and erg["klasse"] is True
    assert TEXT in erg["status"]
    assert erg["regler"] == {"opacity": "0.4", "pe": "none"}
    assert erg["link"]["pe"] == "auto" and erg["link"]["opacity"] == "1"
    assert not [x for x in erg["nach_klick"] if "/DIM/" in x], erg["nach_klick"]
    assert erg["link_io"] and not [x for x in io if "/DIM/" in x], io
    assert TEXT not in erg["status_frei"] and erg["regler_frei"] == {"opacity": "1", "pe": "auto"}
