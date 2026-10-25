"""LoxOS (Fork, docs/VISION.md): Seiten-Editor fuer Bento-Seiten in Chromium.

Der ganze Weg im Konfigurator: Seiteninhalt "Bento", Widgets und einen
Baustein platzieren, eine Webadresse eingeben (ftp abgelehnt, https
angenommen), Tastatur, Kollision, Ziehen, Groesse am Griff, Speichern - und
die gespeicherte Seite in der Visu.
"""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, visu_starten
from test_auswahl_seiten_browser import ROUTEN, STRUKTUR, _speichern
from test_bento_browser import _ablegen

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser


async def _mitte(pg, sel):
    b = await pg.locator(sel).bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


async def _ziehen(pg, von, nach):
    (x0, y0), (x1, y1) = await _mitte(pg, von), await _mitte(pg, nach)
    await pg.mouse.move(x0, y0)
    await pg.mouse.down()
    await pg.mouse.move((x0 + x1) / 2, (y0 + y1) / 2, steps=4)
    await pg.mouse.move(x1, y1, steps=4)
    await pg.mouse.up()


def _zellen_js():
    return "[...document.querySelectorAll('#seHost [data-be-z]')].map(z=>z.querySelector('.be-zn').textContent)"


def test_bento_seite_im_editor_bauen(cfg_ordner, tmp_path):
    uu = list(STRUKTUR["controls"])
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"flur": {
        "title": "Flur", "tabs": ["auswahl"], "device": {"name": "streifen", "vw": 2560, "vh": 720},
        "pickTabs": [{"name": "Streifen", "picks": uu[:2]}]}}}), encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(STRUKTUR)
        app.states = {"s" + u: 0 for u in STRUKTUR["controls"]}
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1400, "height": 1000}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator("#plist .pitem", has_text="Flur").click()
                await pg.locator("#tabMode button[data-mode='pick']").click()
                await pg.locator("#pickZumEditor").click()
                await pg.locator("#seHost [data-se-inhalt]").select_option("bento")
                await pg.locator("#seHost [data-be]").wait_for()
                assert await pg.locator("#seHost .se-spalten").is_hidden()
                assert await pg.input_value("#seHost [data-be-raster=cols]") == "6"

                # Uhr, Wetter, ein Baustein aus "Nicht platziert", eine Webseite
                await pg.locator("#seHost [data-be-neu=clock]").click()
                assert await pg.locator("#seHost [data-be-neu=clock]").is_disabled(), "Uhr einmal je Seite"
                await pg.locator("#seHost [data-be-neu=weather]").click()
                await pg.locator("#seHost [data-be-platz]").first.click()
                await pg.locator("#seHost [data-be-neu=iframe]").click()
                assert await pg.locator("#seHost .be-z.fehlt").count() == 1
                await pg.locator("#seHost [data-be-url]").fill("ftp://drucker.local/")
                await pg.locator("#seHost [data-be-url]").dispatch_event("change")
                assert await pg.locator("#seHost .be-aus .be-warn").count() == 1
                await pg.locator("#seHost [data-be-url]").fill("https://drucker.local/")
                await pg.locator("#seHost [data-be-url]").dispatch_event("change")
                await pg.locator("#seHost [data-be-wname]").fill("Drucker")
                await pg.locator("#seHost [data-be-wname]").dispatch_event("change")
                assert await pg.locator("#seHost .be-z.fehlt").count() == 0

                # Tastatur: Uhr nach unten wachsen lassen; nach rechts ist besetzt
                await pg.locator("#seHost [data-be-z='0']").focus()
                await pg.keyboard.press("Shift+ArrowDown")
                await pg.keyboard.press("ArrowRight")

                # Ziehen: Baustein-Zelle nach unten rechts, dann Wetter am Griff breiter
                await _ziehen(pg, "#seHost [data-be-z='2']", "#seHost [data-be-feld='4,1']")
                await pg.locator("#seHost [data-be-z='1']").click()
                await _ziehen(pg, "#seHost [data-be-griff='1']", "#seHost [data-be-feld='2,0']")
                await pg.locator("#seHost [data-be]").screenshot(path=str(tmp_path / "bento_editor.png"))
                _ablegen(tmp_path, "bento_editor.png")
                namen = await pg.evaluate(_zellen_js())

                flur = await _speichern(pg, cfg_ordner)

                visu = await b.new_page(viewport={"width": 2560, "height": 720}, locale="de-DE")
                visu.on("pageerror", lambda e: fehler.append(str(e)))
                await visu.goto(f"http://127.0.0.1:{port}/?panel=flur")
                await visu.wait_for_selector("#grid.bento > .bz", state="attached")
                anzahl = await visu.locator("#grid.bento > .bz").count()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        return flur, namen, anzahl, fehler

    flur, namen, anzahl, fehler = asyncio.run(lauf())
    assert fehler == [], fehler
    assert namen[0] == "Uhr" and namen[1] == "Wetter" and namen[3] == "Webseite · Drucker", namen
    bento = flur["pickTabs"][0]["bento"]
    assert bento["cols"] == 6 and bento["rows"] == 2 and bento["format"] == {"vw": 2560, "vh": 720}
    assert bento["cells"] == [
        {"x": 0, "y": 0, "w": 1, "h": 2, "widget": "clock"},
        {"x": 1, "y": 0, "w": 2, "h": 1, "widget": "weather"},
        {"x": 4, "y": 1, "w": 1, "h": 1, "ids": [uu[0]]},
        {"x": 3, "y": 0, "w": 1, "h": 1, "widget": "iframe", "url": "https://drucker.local/", "name": "Drucker"},
    ], bento["cells"]
    assert "widget" not in flur["pickTabs"][0]
    assert anzahl == 4


def test_raum_display_im_editor(cfg_ordner, tmp_path):
    """Raum-Display: die Palette legt eine Zelle mit der ersten anderen Ansicht
    an, die Auswahl bietet alle Ansichten ausser der bearbeiteten, der Hinweis
    nennt das Format des Zielgeraets. Gespeichert zeigt die Visu die Ansicht."""
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {
        "flur": {"title": "Flur", "tabs": ["auswahl"], "device": {"name": "streifen", "vw": 2560, "vh": 720},
                 "pickTabs": [{"name": "Streifen", "picks": []}]},
        "kueche": {"title": "Küche", "tabs": ["favoriten"], "device": {"name": "kueche-panel", "vw": 480, "vh": 480}},
        "bad": {"title": "Bad", "tabs": ["favoriten"]}}}), encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(STRUKTUR)
        app.states = {"s" + u: 0 for u in STRUKTUR["controls"]}
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1400, "height": 1000}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator("#plist .pitem", has_text="Flur").click()
                await pg.locator("#tabMode button[data-mode='pick']").click()
                await pg.locator("#pickZumEditor").click()
                await pg.locator("#seHost [data-se-inhalt]").select_option("bento")
                await pg.locator("#seHost [data-be]").wait_for()
                await pg.locator("#seHost [data-be-neu=ansicht]").click()
                quelle = pg.locator("#seHost [data-be-quelle]")
                optionen = await quelle.evaluate("s => [...s.options].map(o => o.value)")
                erste = await quelle.input_value()
                hinweis_kueche = await pg.locator("#seHost .be-aus .hint").first.inner_text()
                await quelle.select_option("bad")
                hinweis_bad = await pg.locator("#seHost .be-aus .hint").first.inner_text()
                await pg.locator("#seHost [data-be-neu=ansicht]").click()
                namen = await pg.evaluate(_zellen_js())
                flur = await _speichern(pg, cfg_ordner)

                visu = await b.new_page(viewport={"width": 2560, "height": 720}, locale="de-DE")
                visu.on("pageerror", lambda e: fehler.append(str(e)))
                await visu.goto(f"http://127.0.0.1:{port}/?panel=flur")
                await visu.wait_for_selector('#grid.bento > .bz[data-widget="ansicht"] iframe', state="attached")
                iframes = await visu.locator('#grid.bento > .bz[data-widget="ansicht"] iframe').count()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        return optionen, erste, hinweis_kueche, hinweis_bad, namen, flur, iframes, fehler

    optionen, erste, hinweis_kueche, hinweis_bad, namen, flur, iframes, fehler = asyncio.run(lauf())
    assert fehler == [], fehler
    assert "flur" not in optionen and {"kueche", "bad"} <= set(optionen), optionen
    assert erste == "kueche"
    assert "480 × 480" in hinweis_kueche and "kueche-panel" in hinweis_kueche
    assert "kein Zielgerät" in hinweis_bad
    assert namen == ["Raum-Display · Bad", "Raum-Display · Küche"], namen
    assert [c["widget"] for c in flur["pickTabs"][0]["bento"]["cells"]] == ["ansicht:bad", "ansicht:kueche"]
    assert iframes == 2
