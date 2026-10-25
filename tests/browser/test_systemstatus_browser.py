"""LoxOS (Fork, docs/VISION.md): Widget "Systemstatus" in Chromium.

Visu: Eine Bento-Seite mit Uhr, einer grossen und einer kleinen
Systemstatus-Zelle auf 2560x720 und 1280x400 - nichts ragt heraus, der Kopf
nennt Miniserver und Verbindung, die Mitteilung steht mit ihrer Stufe da,
Firmware und Auslastung so, wie der Miniserver sie schickt; die kleine Zelle
zeigt nur Kopf und Mitteilung. Getrennt wird der Punkt rot.

Editor: Systemstatus aus der Palette legen (danach ist der Knopf gesperrt,
einmal je Seite), speichern - und die Visu zeigt die Zelle.
"""
import asyncio
import json
import time

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, visu_starten
from test_bento_browser import PRUEFEN, _ablegen

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

SCHALTER = {"name": "Flur Licht", "type": "Switch", "uuidAction": "SW", "room": "r1", "cat": "c1",
            "states": {"active": "sw-a"}}
MITTEILUNG = {"uid": "m1", "type": 10, "title": "Extension offline",
              "message": "Die Tree Extension im Technikraum antwortet seit dem Neustart nicht mehr.",
              "data": {"lvl": 3}}
ANTWORTEN = {"cfg/version": ("200", "15.2.10.6"), "sys/cpu": ("200", "12%"),
             "sys/heap": ("200", "1234/5678 kB"), "sys/numtasks": ("200", "87")}


def _app(zellen=None, cols=6, rows=2) -> W.App:
    struktur = anlage({"SW": SCHALTER})
    struktur.update({"msInfo": {"msName": "Haus", "projectName": "Einfamilienhaus", "miniserverType": 2},
                     "lastModified": "2026-10-20 18:03:11", "globalStates": {"notifications": "g-notif"},
                     "messageCenter": {"states": {"changed": "mc-changed"}}})
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    jetzt = time.time()
    app.states = {"sw-a": 0, "g-notif": json.dumps(dict(MITTEILUNG, ts=jetzt - 60)), "mc-changed": jetzt - 120}
    app._ms_verbunden_seit = jetzt - 3600
    app._system()["antworten"] = dict(ANTWORTEN)
    app._system()["firmware_fuer"] = app._ms_verbunden_seit
    app.panels = W.App._sanitize_panels({"streifen": {
        "title": "Streifen", "tabs": ["auswahl"], "ui": {"tileSet": "edge"},
        "pickTabs": [{"name": "Start", "picks": [], "bento": {"cols": cols, "rows": rows, "cells": zellen or [
            {"x": 0, "y": 0, "w": 1, "h": 2, "widget": "clock"},
            {"x": 1, "y": 0, "w": 3, "h": 2, "widget": "system"}]}}]}})
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
                await pg.wait_for_selector(".bz-system", state="attached")
                await pg.evaluate("wake()")
                await pg.wait_for_timeout(500)
                erg = await aktion(pg)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        return erg, fehler
    return asyncio.run(lauf())


LESEN = """() => [...document.querySelectorAll('.bz-system')].map(s => ({
  name: s.querySelector('.bz-sy-name').textContent,
  verb: s.querySelector('.bz-sy-verb').textContent,
  punkt: getComputedStyle(s.querySelector('.bz-sy-punkt')).backgroundColor,
  stufe: (s.querySelector('.bz-sy-stufe')||{}).textContent||'',
  titel: (s.querySelector('.bz-sy-mtitel')||{}).textContent||'',
  gruppen: getComputedStyle(s.querySelector('.bz-sy-gruppen')).display,
  zeilen: Object.fromEntries([...s.querySelectorAll('.bz-sy-zeile')].map(z =>
    [z.querySelector('.k').textContent, z.querySelector('.v').textContent]))}))"""


@pytest.mark.parametrize("w, h", [(2560, 720), (1280, 400)])
def test_systemstatus_auf_dem_streifen(w, h, tmp_path):
    zellen = [{"x": 0, "y": 0, "w": 1, "h": 2, "widget": "clock"},
              {"x": 1, "y": 0, "w": 3, "h": 2, "widget": "system"}]

    async def aktion(pg):
        name = f"systemstatus-{w}x{h}.png"
        await pg.screenshot(path=str(tmp_path / name))
        _ablegen(tmp_path, name)
        return await pg.evaluate(LESEN), await pg.evaluate(PRUEFEN)
    (zellen_, probleme), fehler = _lauf(_app(zellen), aktion, w, h)
    assert fehler == [] and probleme == [], (fehler, probleme)
    (sy,) = zellen_
    assert sy["name"] == "Haus" and sy["verb"].startswith("Verbunden seit ")
    assert sy["stufe"] == "Systemfehler" and sy["titel"] == "Extension offline"
    assert {k: sy["zeilen"][k] for k in ("Firmware", "CPU-Last", "Speicher (Heap)", "Tasks", "Projekt")} == {
        "Firmware": "15.2.10.6", "CPU-Last": "12%", "Speicher (Heap)": "1234/5678 kB", "Tasks": "87",
        "Projekt": "Einfamilienhaus"}
    assert "Displays verbunden" in sy["zeilen"]


@pytest.mark.parametrize("cols, rows, stufe", [(6, 2, "mittel"), (12, 4, "klein")])
def test_kleine_zellen(cols, rows, stufe):
    """Eine 1x1-Zelle auf 1280x400: mittel scrollt, was nicht passt (nichts
    ragt heraus), klein zeigt nur Kopf und Mitteilung."""
    zellen = [{"x": 0, "y": 0, "w": 1, "h": 1, "widget": "system"}]

    async def aktion(pg):
        return await pg.evaluate(LESEN), await pg.evaluate(PRUEFEN), \
            await pg.evaluate("document.querySelector('#grid.bento > .bz').dataset.stufe")
    (zellen_, probleme, ist), fehler = _lauf(_app(zellen, cols, rows), aktion, 1280, 400)
    assert fehler == [] and probleme == [], (fehler, probleme)
    assert ist == stufe and zellen_[0]["titel"] == "Extension offline"
    assert (zellen_[0]["gruppen"] == "none") == (stufe == "klein")


def test_getrennt_wird_der_punkt_rot():
    app = _app()
    app._ms_verbunden_seit = None
    app._ms_weg_seit = time.time() - 300

    async def aktion(pg):
        # --crit so aufgeloest, wie getComputedStyle es fuer den Punkt meldet
        crit = await pg.evaluate("""() => { const e=document.createElement('i'); e.style.color='var(--crit)';
            document.querySelector('.bz-system').append(e); const c=getComputedStyle(e).color; e.remove(); return c; }""")
        return await pg.evaluate(LESEN), crit
    (zellen_, crit), fehler = _lauf(app, aktion)
    assert fehler == []
    assert zellen_[0]["verb"].startswith("Getrennt seit ") and "Firmware" not in zellen_[0]["zeilen"]
    assert zellen_[0]["punkt"] == crit


def test_systemstatus_im_editor(cfg_ordner, tmp_path):
    app = _app()
    app.panels = W.App._sanitize_panels({"flur": {
        "title": "Flur", "tabs": ["auswahl"], "device": {"name": "streifen", "vw": 2560, "vh": 720},
        "pickTabs": [{"name": "Streifen", "picks": []}]}})
    routen = [("POST", "/api/panels", W.api_save_panels)]

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
                knopf = pg.locator("#seHost [data-be-neu=system]")
                beschriftung = await knopf.text_content()
                await knopf.click()
                gesperrt = await pg.locator("#seHost [data-be-neu=system]").is_disabled()
                hinweis = await pg.locator("#seHost .be-aus .hint").first.text_content()
                await pg.locator("#seHost [data-be]").screenshot(path=str(tmp_path / "systemstatus-editor.png"))
                _ablegen(tmp_path, "systemstatus-editor.png")
                async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
                    await pg.locator("#saveBtn").click()
                j = await (await antwort.value).json()
                flur = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]["flur"]

                visu = await b.new_page(viewport={"width": 2560, "height": 720}, locale="de-DE")
                visu.on("pageerror", lambda e: fehler.append(str(e)))
                await visu.goto(f"http://127.0.0.1:{port}/?panel=flur")
                await visu.wait_for_selector(".bz-system .bz-sy-name", state="attached")
                name = await visu.locator(".bz-system .bz-sy-name").text_content()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        return beschriftung, gesperrt, hinweis, j, flur, name, fehler
    beschriftung, gesperrt, hinweis, j, flur, name, fehler = asyncio.run(lauf())
    assert fehler == [], fehler
    assert beschriftung == "Systemstatus" and gesperrt, "einmal je Seite"
    assert hinweis.startswith("Zeigt, was der Miniserver über sich meldet")
    assert j["ok"] and j["verworfen"] == [], j
    (zelle,) = flur["pickTabs"][0]["bento"]["cells"]
    assert zelle["widget"] == "system" and set(zelle) == {"x", "y", "w", "h", "widget"}
    assert name == "Haus"


def test_neue_werte_behalten_die_scrollposition():
    """In einer kleinen Zelle gescrollt: kommt eine neue CPU-Last, zeichnet die
    Visu die Zelle neu und bleibt an derselben Stelle."""
    app = _app([{"x": 0, "y": 0, "w": 1, "h": 1, "widget": "system"}])

    async def aktion(pg):
        await pg.evaluate("document.querySelector('.bz-system').scrollTop=80")
        vorher = await pg.evaluate("document.querySelector('.bz-system').scrollTop")
        app._system()["antworten"]["sys/cpu"] = ("200", "55%")
        app._mark_dirty()
        await pg.wait_for_function("[...document.querySelectorAll('.bz-sy-zeile .v')].some(v => v.textContent === '55%')")
        return vorher, await pg.evaluate("document.querySelector('.bz-system').scrollTop")
    (vorher, danach), fehler = _lauf(app, aktion, 1280, 400)
    assert fehler == [] and vorher == 80 and danach == vorher
