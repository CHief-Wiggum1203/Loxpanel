"""Uhr-Seite wegtippen in Chromium: Der Finger, der sie wegtippt, loest auf der
Kachel darunter nichts aus - auch nicht, wenn er kurz liegen bleibt. Die Uhr
verschwindet schon beim Aufsetzen; Loslassen, click und Langdruck derselben
Beruehrung gingen sonst an die Kachel, die jetzt unter dem Finger liegt (so
macht es Safari auf dem iPad: der click geht an die Stelle des Loslassens).
Die naechste Beruehrung bedient die Kachel wieder ganz normal. Befehle
schreibt ein Stellvertreter fuer app.command mit."""
import asyncio

import pytest

from lox import W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

LICHTER = {f"L{i}": {"name": f"Licht {i}", "type": "Switch", "uuidAction": f"L{i}", "room": "r1",
                     "cat": "c1", "isFavorite": True, "states": {"active": f"sl{i}"}}
           for i in range(4)}
# Safari richtet den click nach dem Loslassen an das Element unter dem Finger;
# Chromium an den gemeinsamen Vorfahren von pointerdown- und pointerup-Ziel.
# Nachgestellt: auf das Aufsetzen folgen pointerup und click an der Kachel,
# die nach dem Wegtippen an dieser Stelle liegt.
SAFARI_LOSLASSEN = """([x, y]) => { const z = document.elementFromPoint(x, y);
  const o = {bubbles: true, cancelable: true, clientX: x, clientY: y};
  z.dispatchEvent(new PointerEvent('pointerup', Object.assign({pointerId: 1, pointerType: 'touch'}, o)));
  z.dispatchEvent(new MouseEvent('click', o));
  return z.closest('.tile') ? z.closest('.tile').dataset.id : z.id; }"""


def _app(befehle: list):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(LICHTER))
    app.states = {f"sl{i}": 0 for i in range(4)}
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"]}})

    async def command(uuid, cmd, pin=None):
        befehle.append((uuid, cmd))
        return "200"
    app.command = command
    return app


async def _mitte(pg):
    """Mitte der ersten Kachel (liegt unter der Uhr-Seite)."""
    box = await pg.locator(".tile[data-id]").first.bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


async def _uhr(pg):
    await pg.evaluate("showSaver()")
    await pg.wait_for_selector("#saver:not(.hidden)")


async def _ruhig(befehle, pg):
    """Kurz warten, ob doch noch ein Befehl kommt."""
    await pg.wait_for_timeout(500)
    return list(befehle)


def test_wegtippen_loest_darunter_nichts_aus(tmp_path):
    async def lauf():
        befehle = []
        runner, port, bc = await visu_starten(_app(befehle))
        fehler, ergebnis = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": 800, "height": 600}, has_touch=True)
                pg = await ctx.new_page()
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector(".tile[data-id]", state="attached")
                await _uhr(pg)
                x, y = await _mitte(pg)
                cdp = await ctx.new_cdp_session(pg)

                # Finger aufsetzen, liegen lassen, loslassen
                await cdp.send("Input.dispatchTouchEvent",
                               {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
                await pg.wait_for_timeout(700)
                await cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                ergebnis["gehalten"] = await _ruhig(befehle, pg), await pg.evaluate("saverOn()")

                # Wie Safari: Loslassen und click gehen an die Kachel darunter
                await _uhr(pg)
                await pg.mouse.move(x, y)
                await pg.mouse.down()
                ziel = await pg.evaluate(SAFARI_LOSLASSEN, [x, y])
                await pg.mouse.up()
                ergebnis["safari"] = ziel, await _ruhig(befehle, pg), await pg.evaluate("saverOn()")

                # Maus gedrueckt halten (Browser am PC)
                await _uhr(pg)
                await pg.mouse.down()
                await pg.wait_for_timeout(700)
                await pg.mouse.up()
                ergebnis["maus"] = await _ruhig(befehle, pg), await pg.evaluate("saverOn()")

                # Die naechste Beruehrung schaltet die Kachel wie immer
                await pg.touchscreen.tap(x, y)
                for _ in range(60):
                    if befehle:
                        break
                    await asyncio.sleep(0.05)
                ergebnis["danach"] = await _ruhig(befehle, pg)
                await pg.screenshot(path=str(tmp_path / "nach_wegtippen.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return ergebnis
    e = asyncio.run(lauf())

    assert e["gehalten"] == ([], False), f"liegen gebliebener Finger: {e['gehalten']}"
    ziel, befehle, uhr = e["safari"]
    assert ziel == "L0", f"der Nachbau muss die Kachel treffen: {ziel}"
    assert (befehle, uhr) == ([], False), f"Safari-Loslassen: {e['safari']}"
    assert e["maus"] == ([], False), f"Maus gehalten: {e['maus']}"
    assert len(e["danach"]) == 1 and e["danach"][0][0] == "L0", f"naechstes Tippen: {e['danach']}"
