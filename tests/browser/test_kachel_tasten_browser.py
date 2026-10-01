"""Tasten auf der Kachel (Mini-Player ◀ ⏯ ▶ der AudioZone) und Favoriten der
Musikauswahl in Chromium mit Touch-Display: Tippen sendet den Befehl genau
einmal; ein Wischer, der auf einer Taste beginnt, scrollt das Raster und sendet
nichts. Mit der Maus wie bisher. Befehle schreibt ein Stellvertreter fuer
app.command mit."""
import asyncio
import json

import pytest

from lox import W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

# Genug Zonen, dass das Raster bei 480x480 scrollt
ZONEN = {f"Z{i}": {"name": f"Zone {i}", "type": "AudioZone", "uuidAction": f"Z{i}", "room": "r1",
                   "cat": "c1", "isFavorite": True, "states": {"playState": f"ps{i}"}}
         for i in range(12)}
ZONEN["Z0"]["states"]["sourceList"] = "sl0"
# Favoriten der Zone 0, wie sie der Miniserver in sourceList legt: genug fuer
# mehrere Reihen, damit die Musikauswahl scrollt
SENDER = json.dumps({"items": [{"slot": i, "name": f"Sender {i}"} for i in range(1, 31)]})


def _app(befehle: list):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(ZONEN))
    app.states = {**{f"ps{i}": 0 for i in range(12)}, "sl0": SENDER}
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"]}})

    async def command(uuid, cmd, pin=None):
        befehle.append((uuid, cmd))
        return "200"
    app.command = command
    return app


async def _taste(pg):
    """Mitte der Zurueck-Taste (◀) auf der ersten Kachel."""
    box = await pg.locator(".tile[data-id] .tctrls .tb").first.bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


async def _wischen(cdp, x, y, dy, schritte=20):
    """Finger bei (x, y) aufsetzen, in Schritten um dy verschieben, loslassen -
    so, wie ein Touchscreen meldet (synthetische Scroll-Gesten greifen in
    einem verschachtelten Scroller mit Rastpunkten nicht)."""
    await cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
    for i in range(1, schritte + 1):
        await cdp.send("Input.dispatchTouchEvent",
                       {"type": "touchMove", "touchPoints": [{"x": x, "y": y + dy * i / schritte}]})
        await asyncio.sleep(0.016)
    await cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})


# Hoechste Scroll-Position des Rasters waehrend eines Wischers. Danach rastet es
# seitenweise ein (scroll-snap) und kann ohne Schwung - auf einem ausgelasteten
# Rechner kommen die Touch-Ereignisse langsamer - auf die erste Seite
# zurueckspringen; ob der Wischer gescrollt hat, zeigt nur der Verlauf.
SCROLL_BEOBACHTEN = """window.__scrollMax = 0;
  el('grid').addEventListener('scroll', () => {
    window.__scrollMax = Math.max(window.__scrollMax, el('grid').scrollTop); });"""


async def _warten(befehle, n, pg):
    """Bis n Befehle da sind (hoechstens 3 s), dann noch kurz, ob mehr kommen."""
    for _ in range(60):
        if len(befehle) >= n:
            break
        await asyncio.sleep(0.05)
    await pg.wait_for_timeout(400)


def test_tippen_sendet_wischen_scrollt(tmp_path):
    async def lauf():
        befehle = []
        app = _app(befehle)
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": 480, "height": 480}, has_touch=True)
                pg = await ctx.new_page()
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector(".tile[data-id] .tctrls .tb")
                await pg.evaluate("hideSaver()")              # Uhr-Startseite weg, das Raster liegt frei
                hoehe = await pg.evaluate("[el('grid').scrollHeight, el('grid').clientHeight]")
                x, y = await _taste(pg)

                # Wischer nach oben, Beginn auf der Taste: das Raster scrollt, kein Befehl
                await pg.evaluate(SCROLL_BEOBACHTEN)
                cdp = await ctx.new_cdp_session(pg)
                await _wischen(cdp, x, y, -150)
                await _warten(befehle, 1, pg)
                gewischt = list(befehle), await pg.evaluate("__scrollMax")

                # Tippen auf die Taste: genau ein Befehl, die Kachel oeffnet nichts
                await pg.evaluate("el('grid').scrollTop = 0")
                await pg.wait_for_timeout(300)
                x, y = await _taste(pg)
                await pg.touchscreen.tap(x, y)
                await _warten(befehle, 1, pg)
                getippt = list(befehle), await pg.evaluate("stack.length")
                await pg.screenshot(path=str(tmp_path / "kachel_tasten.png"))

                # Maus (Browser am PC): Klick wie bisher
                befehle.clear()
                maus = await (await b.new_context(viewport={"width": 480, "height": 480})).new_page()
                maus.on("pageerror", lambda e: fehler.append(str(e)))
                await maus.goto(f"http://127.0.0.1:{port}/?panel=test")
                await maus.wait_for_selector(".tile[data-id] .tctrls .tb")
                await maus.evaluate("hideSaver()")
                x, y = await _taste(maus)
                await maus.mouse.click(x, y)
                await _warten(befehle, 1, maus)
                geklickt = list(befehle), await maus.evaluate("stack.length")
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return hoehe, gewischt, getippt, geklickt
    hoehe, gewischt, getippt, geklickt = asyncio.run(lauf())

    assert hoehe[0] > hoehe[1], f"das Raster muss scrollen koennen: {hoehe}"
    befehle, scroll = gewischt
    assert befehle == [], f"ein Wischer auf der Taste darf nichts senden: {befehle}"
    assert scroll > 0, "der Wischer scrollt das Raster"
    assert getippt == ([("Z0", "queueminus")], 1), "Tippen: ein Befehl, keine Detailseite"
    assert geklickt == ([("Z0", "queueminus")], 1), "Mausklick wie bisher"


def test_favoriten_tippen_und_wischen(tmp_path):
    """Musikauswahl: Ein Favorit startet erst beim Tippen (und die Seite geht
    zurueck); ein Wischer durch die Favoriten scrollt und laesst die Seite stehen."""
    async def lauf():
        befehle = []
        app = _app(befehle)
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": 480, "height": 480}, has_touch=True)
                pg = await ctx.new_page()
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector(".tile[data-id] .tctrls .tb")
                await pg.evaluate("hideSaver(); nav({view: 'sources', id: 'Z0'})")
                await pg.wait_for_selector(".favs .fav")
                await pg.screenshot(path=str(tmp_path / "musikauswahl.png"))
                hoehe = await pg.evaluate("[el('grid').scrollHeight, el('grid').clientHeight]")

                def abspielen():
                    return [b for b in befehle if b[1].startswith("roomfav/play/")]

                box = await pg.locator(".favs .fav").first.bounding_box()
                x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                await pg.evaluate(SCROLL_BEOBACHTEN)
                cdp = await ctx.new_cdp_session(pg)
                await _wischen(cdp, x, y, -150)
                await pg.wait_for_timeout(600)
                gewischt = abspielen(), await pg.evaluate("__scrollMax"), \
                    await pg.evaluate("stack.length")

                getippt = None
                if gewischt[2] == 2:      # Musikauswahl noch offen: jetzt Tippen pruefen
                    await pg.evaluate("el('grid').scrollTop = 0")
                    await pg.wait_for_timeout(300)
                    box = await pg.locator(".favs .fav").first.bounding_box()
                    await pg.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    for _ in range(60):
                        if abspielen():
                            break
                        await asyncio.sleep(0.05)
                    await pg.wait_for_timeout(400)
                    getippt = abspielen(), await pg.evaluate("stack.length")
                await pg.screenshot(path=str(tmp_path / "favoriten.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return hoehe, gewischt, getippt
    hoehe, gewischt, getippt = asyncio.run(lauf())

    assert hoehe[0] > hoehe[1], f"die Musikauswahl muss scrollen koennen: {hoehe}"
    gespielt, scroll, tiefe = gewischt
    assert gespielt == [], f"ein Wischer durch die Favoriten darf nichts starten: {gespielt}"
    assert scroll > 0 and tiefe == 2, "der Wischer scrollt, die Musikauswahl bleibt offen"
    assert getippt == ([("Z0", "roomfav/play/1")], 1), "Tippen startet den Sender und geht zurueck"
