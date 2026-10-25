"""LoxOS (Fork, docs/VISION.md): Widget "Schnellaktionen" in Chromium.

Visu: Eine Bento-Seite mit Knoepfen (Jalousie "Ganz Ab", zwei Stimmungen der
Lichtsteuerung, ein Schalter wie seine Kachel, ein Probealarm mit Rueckfrage,
ein fehlender Baustein) auf 2560x720 und 1280x400 - nichts ragt heraus, ein
Tipp schickt den Befehl der Detailseite, die aktive Stimmung leuchtet, die
Rueckfrage kommt vor dem Befehl, der fehlende Knopf ist gesperrt.

Editor: Zelle anlegen, Knopf hinzufuegen, Aktion aus der Detailseite waehlen,
eigener Text und Symbol, speichern - und die Visu zeigt den Knopf.
"""
import asyncio
import json

import pytest

from lox import (KONFIGURATOR_GELADEN, W, anlage, jalousie_baustein, lichtsteuerung_baustein,
                 rauchmelder_baustein, visu_starten)
from test_bento_browser import PRUEFEN, _ablegen

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

SCHALTER = {"name": "Flur Licht", "type": "Switch", "uuidAction": "SW", "room": "r1", "cat": "c1",
            "states": {"active": "sw-a"}}
KNOEPFE = [{"id": "JA", "aktion": "Ganz Ab"}, {"id": "LV", "aktion": "Abend"}, {"id": "LV", "aktion": "Kino"},
           {"id": "SW", "name": "Flur"}, {"id": "SM", "aktion": "Probealarm"}, {"id": "WEG", "name": "Garage"}]


def _app(befehle: list, knoepfe=KNOEPFE) -> W.App:
    controls, states = {"SW": SCHALTER}, {"sw-a": 0}
    for f in (jalousie_baustein, lichtsteuerung_baustein, rauchmelder_baustein):
        c, st = f()
        controls[c["uuidAction"]] = c
        states.update(st)
    struktur = anlage(controls)
    struktur["rooms"]["r1"]["image"] = "IconsFilled/blinds.svg"   # fuer die Symbolauswahl im Editor
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    app.states = states
    app.panels = W.App._sanitize_panels({"streifen": {
        "title": "Streifen", "tabs": ["auswahl"], "ui": {"tileSet": "edge"},
        "pickTabs": [{"name": "Start", "picks": [], "bento": {"cols": 6, "rows": 2, "cells": [
            {"x": 0, "y": 0, "w": 1, "h": 2, "widget": "clock"},
            {"x": 1, "y": 0, "w": 3, "h": 2, "widget": "schnell", "knoepfe": knoepfe}]}}]}})

    async def command(uuid, cmd, pin=None):
        befehle.append((uuid, cmd))
        return "200"
    app.command = command
    return app


def _lauf(app, aktion, w=2560, h=720):
    async def lauf():
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": w, "height": h}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=streifen")
                await pg.wait_for_selector(".bz-schnell .bz-sk", state="attached")
                await pg.evaluate("wake()")
                await pg.wait_for_timeout(500)
                erg = await aktion(pg)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        return erg, fehler
    return asyncio.run(lauf())


def _knopf(pg, i):
    return pg.locator(f".bz-schnell .bz-sk[data-i='{i}']")


@pytest.mark.parametrize("w, h", [(2560, 720), (1280, 400)])
def test_knoepfe_auf_dem_streifen(w, h, tmp_path):
    befehle = []

    async def aktion(pg):
        name = f"schnellaktionen-{w}x{h}.png"
        await pg.screenshot(path=str(tmp_path / name))
        _ablegen(tmp_path, name)
        knoepfe = await pg.evaluate("""() => [...document.querySelectorAll('.bz-sk')].map(b => ({
            name: b.querySelector('.bz-skn').textContent, zusatz: (b.querySelector('.bz-skz')||{}).textContent||'',
            on: b.classList.contains('on'), aus: b.disabled}))""")
        probleme = await pg.evaluate(PRUEFEN)
        await _knopf(pg, 0).click()
        await _knopf(pg, 2).click()
        await _knopf(pg, 3).click()
        await _knopf(pg, 5).click(force=True)
        await pg.wait_for_timeout(300)
        return knoepfe, probleme
    (knoepfe, probleme), fehler = _lauf(_app(befehle), aktion, w, h)
    assert fehler == [] and probleme == [], (fehler, probleme)
    assert [(k["name"], k["zusatz"]) for k in knoepfe] == [
        ("Raffstore Süd", "Ganz Ab"), ("Licht Wohnen", "Abend"), ("Licht Wohnen", "Kino"), ("Flur", ""),
        ("Brandmeldezentrale", "Probealarm"), ("Garage", "")]
    assert [k["on"] for k in knoepfe] == [False, True, False, False, False, False], "die aktive Stimmung leuchtet"
    assert [k["aus"] for k in knoepfe] == [False] * 5 + [True], "der fehlende Baustein ist gesperrt"
    assert befehle == [("JA", "FullDown"), ("LV", "changeTo/3"), ("SW", "on")]


def test_rueckfrage_vor_dem_befehl():
    befehle = []

    async def aktion(pg):
        k = _knopf(pg, 4)
        await k.click()
        await pg.wait_for_timeout(300)
        vorher = (list(befehle), await k.locator(".bz-skn").text_content(), await k.get_attribute("class"))
        await k.click()
        await pg.wait_for_timeout(300)
        return vorher, await k.locator(".bz-skn").text_content()
    (vorher, danach), fehler = _lauf(_app(befehle), aktion)
    assert fehler == []
    assert vorher[0] == [] and vorher[1] == "Alarm auslösen?" and "arm" in vorher[2]
    assert befehle == [("SM", "startDrill")] and danach == "Brandmeldezentrale"


def test_knopf_ohne_befehl_oeffnet_die_detailseite():
    async def aktion(pg):
        await _knopf(pg, 0).click()
        await pg.wait_for_function("view && view.route && view.route.view === 'control'")
        return await pg.evaluate("view.route")
    route, fehler = _lauf(_app([], knoepfe=[{"id": "LV"}]), aktion)
    assert fehler == [] and route == {"view": "control", "id": "LV"}


def test_schnellaktionen_im_editor(cfg_ordner, tmp_path):
    befehle = []
    app = _app(befehle, knoepfe=[])
    app.panels = W.App._sanitize_panels({"flur": {
        "title": "Flur", "tabs": ["auswahl"], "device": {"name": "streifen", "vw": 2560, "vh": 720},
        "pickTabs": [{"name": "Streifen", "picks": []}]}})
    routen = [("POST", "/api/panels", W.api_save_panels), ("GET", "/api/loxicons", W.loxicons_handler),
              ("GET", "/api/bento/aktionen", W.api_bento_aktionen)]

    async def lauf():
        runner, port, bc = await visu_starten(app, routen)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1400, "height": 1100}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator("#plist .pitem", has_text="Flur").click()
                await pg.locator("#tabMode button[data-mode='pick']").click()
                await pg.locator("#pickZumEditor").click()
                await pg.locator("#seHost [data-se-inhalt]").select_option("bento")
                await pg.locator("#seHost [data-be]").wait_for()
                await pg.locator("#seHost [data-be-neu=schnell]").click()
                await pg.locator("#seHost [data-be-kneu]").select_option("JA")
                aktion = pg.locator("#seHost [data-be-kaktion='0']")
                await pg.wait_for_function(
                    "[...document.querySelectorAll('#seHost [data-be-kaktion] option')].some(o => o.value === 'Ganz Ab')")
                optionen = await aktion.evaluate("s => [...s.options].map(o => o.textContent)")
                await aktion.select_option("Ganz Ab")
                await pg.locator("#seHost [data-be-kname='0']").fill("Rollo zu")
                await pg.locator("#seHost [data-be-kname='0']").dispatch_event("change")
                await pg.locator("#seHost [data-be-kicon='0'] summary").click()
                await pg.locator("#seHost [data-be-kicons='0'] .pgi[title='IconsFilled/blinds.svg']").click()
                await pg.locator("#seHost [data-be-kneu]").select_option("LV")
                await pg.locator("#seHost [data-be]").screenshot(path=str(tmp_path / "schnellaktionen-editor.png"))
                _ablegen(tmp_path, "schnellaktionen-editor.png")
                async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
                    await pg.locator("#saveBtn").click()
                j = await (await antwort.value).json()
                flur = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]["flur"]

                visu = await b.new_page(viewport={"width": 2560, "height": 720}, locale="de-DE")
                visu.on("pageerror", lambda e: fehler.append(str(e)))
                await visu.goto(f"http://127.0.0.1:{port}/?panel=flur")
                await visu.wait_for_selector(".bz-schnell .bz-sk", state="attached")
                await visu.evaluate("wake()")
                await visu.locator(".bz-sk[data-i='0']").click()
                await visu.wait_for_timeout(300)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        return optionen, j, flur, fehler
    optionen, j, flur, fehler = asyncio.run(lauf())
    assert fehler == [], fehler
    assert optionen[0] == "Detailseite öffnen" and "Ganz Ab" in optionen and "Automatik" in optionen
    assert j["ok"] and j["verworfen"] == [], j
    (zelle,) = flur["pickTabs"][0]["bento"]["cells"]
    assert zelle["widget"] == "schnell" and zelle["knoepfe"] == [
        {"id": "JA", "aktion": "Ganz Ab", "name": "Rollo zu", "icon": "/icon?p=IconsFilled%2Fblinds.svg"},
        {"id": "LV"}]
    assert befehle == [("JA", "FullDown")]
