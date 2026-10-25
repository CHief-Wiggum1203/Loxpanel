"""LoxOS (Fork, docs/VISION.md): Raum-Display-Zelle in Chromium.

Ein Streifen (2560x720 bzw. 1280x400) mit einer Bento-Seite, deren Zelle die
Raum-Ansicht "kueche" (Zielgeraet 480x480) als eingebettete Visu zeigt.
Geprueft: Die Zelle laedt die Ansicht in der Groesse ihres Zielgeraets und
passt sie ein, die eingebettete Visu zeigt keine Uhr-Seite, meldet sich ohne
Geraetenamen (auch wenn der localStorage den Streifen nennt), fasst die
Bruecke der Kiosk-App nicht an, und eine Bedienung in ihr haelt die Visu um
sie wach. Eine Raum-Display-Zelle in einer eingebetteten Visu zeigt nur einen
Hinweis. Screenshots liegen im tmp_path (CI-Artefakt).
"""
import asyncio
import shutil
from pathlib import Path

import pytest

from lox import W, raum_anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

SCREENSHOTS = Path(__file__).resolve().parent.parent.parent / "test-screenshots"
ZIEL = {"name": "kueche-panel", "vw": 480, "vh": 480}
ZELLE = {"x": 1, "y": 0, "w": 2, "h": 2, "widget": "ansicht:kueche"}

# Bruecke der LoxPanel-App: ein iframe sieht sie in der App mit (das Init-Skript
# laeuft wie dort in jedem Frame). Jeder Frame schreibt in sein eigenes __lox.
BRUECKE_JS = """window.__lox = []; window.LoxKiosk = { _an: true,
  setDisplayOff(s) { window.__lox.push('dpms:' + s); },
  setSaver(an) { window.__lox.push('saver:' + an); },
  turnScreenOff() { this._an = false; window.__lox.push('aus'); },
  turnScreenOn() { this._an = true; window.__lox.push('an'); },
  isScreenOn() { return this._an; } };"""


def _app(zellen=(ZELLE,)) -> W.App:
    struktur, states = raum_anlage()
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    app.states = states
    app.panels = W.App._sanitize_panels({
        "streifen": {"title": "Streifen", "tabs": ["auswahl"], "ui": {"tileSet": "edge"},
                     "pickTabs": [{"name": "Start", "picks": ["S3"],
                                   "bento": {"cols": 6, "rows": 2, "cells": [
                                       {"x": 0, "y": 0, "w": 1, "h": 2, "widget": "clock"}, *zellen,
                                       {"x": 3, "y": 0, "w": 1, "h": 1, "ids": ["S3"]}]}}]},
        "kueche": {"title": "Küche", "tabs": ["auswahl"], "device": ZIEL,
                   "pickTabs": [{"name": "Küche", "picks": ["S1", "S2"]}]}})
    app.devices = W.App._sanitize_devices({"streifen": {"panel": "streifen"}}, set(app.panels))
    return app


def _lauf(aktion, w=2560, h=720, init_js="", adresse="/?device=streifen", app=None):
    """Visu starten, Streifen oeffnen, aktion(pg, app) -> (Ergebnis, Skriptfehler je Frame)."""
    async def lauf():
        a = app or _app()
        runner, port, bc = await visu_starten(a)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": w, "height": h}, locale="de-DE")
                if init_js:
                    await ctx.add_init_script(init_js)
                pg = await ctx.new_page()
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}{adresse}")
                await pg.wait_for_selector("#grid.bento > .bz", state="attached")
                await pg.evaluate("wake()")
                erg = await aktion(pg, a)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        return erg, fehler
    return asyncio.run(lauf())


async def _zellen_frame(pg):
    """Frame der Raum-Display-Zelle, sobald ihre Visu Kacheln zeigt."""
    await pg.wait_for_selector('.bz[data-widget="ansicht"] iframe', state="attached")
    f = await (await pg.query_selector('.bz[data-widget="ansicht"] iframe')).content_frame()
    await f.wait_for_selector("#grid .tile[data-id]", state="attached")
    await f.wait_for_timeout(400)
    return f


def _ablegen(tmp_path: Path, name: str) -> None:
    if SCREENSHOTS.is_dir():
        shutil.copy(tmp_path / name, SCREENSHOTS / name)


@pytest.mark.parametrize("w, h", [(2560, 720), (1280, 400)])
def test_zelle_zeigt_die_ansicht_eingepasst(w, h, tmp_path):
    async def aktion(pg, app):
        f = await _zellen_frame(pg)
        innen = await f.evaluate("""() => ({w: innerWidth, h: innerHeight, adresse: location.search,
            uhr: !document.getElementById('saver').classList.contains('hidden'),
            kacheln: [...document.querySelectorAll('#grid .tile[data-id]')].map(t => t.dataset.id)})""")
        mass = await pg.evaluate("""() => { const z=document.querySelector('.bz[data-widget="ansicht"]'),
            i=z.querySelector('iframe'), zr=z.getBoundingClientRect(), ir=i.getBoundingClientRect();
            return {zelle: [zr.left, zr.top, zr.width, zr.height], iframe: [ir.left, ir.top, ir.width, ir.height]}; }""")
        name = f"raum-display-{w}x{h}.png"
        await pg.screenshot(path=str(tmp_path / name))
        _ablegen(tmp_path, name)
        verb = sorted((i.get("dev", ""), bool(i.get("eingebettet"))) for i in app.conn_info.values())
        return innen, mass, verb
    (innen, mass, verb), fehler = _lauf(aktion, w, h)
    assert fehler == []
    assert (innen["w"], innen["h"]) == (480, 480), "die Ansicht rendert in der Groesse ihres Zielgeraets"
    assert "panel=kueche" in innen["adresse"] and "eingebettet=1" in innen["adresse"]
    assert innen["uhr"] is False, "keine Uhr-Seite in der Zelle"
    assert innen["kacheln"] == ["S1", "S2"]
    zx, zy, zw, zh = mass["zelle"]
    ix, iy, iw, ih = mass["iframe"]
    k = min(zw / 480, zh / 480)
    assert abs(iw - 480 * k) < 1.5 and abs(ih - 480 * k) < 1.5, "eingepasst, ohne Verzerrung"
    assert ix >= zx - 1 and iy >= zy - 1 and ix + iw <= zx + zw + 1 and iy + ih <= zy + zh + 1
    assert abs((ix - zx) - (zx + zw - ix - iw)) < 1.5, "waagerecht mittig"
    assert verb == [("", True), ("streifen", False)], "der Streifen ist ein Geraet, die Zelle nicht"


def test_zelle_fasst_die_bruecke_der_app_nicht_an():
    async def aktion(pg, app):
        f = await _zellen_frame(pg)
        innen = await f.evaluate("() => ({bruecke: typeof window.LoxKiosk, aufrufe: window.__lox})")
        aussen = await pg.evaluate("() => ({bruecke: typeof window.LoxKiosk, aufrufe: window.__lox})")
        return innen, aussen
    (innen, aussen), fehler = _lauf(aktion, init_js=BRUECKE_JS)
    assert fehler == []
    assert innen == {"bruecke": "undefined", "aufrufe": []}, "Schoner und Display gehoeren dem Streifen"
    assert aussen["bruecke"] == "object" and "saver:true" in aussen["aufrufe"]


def test_bedienung_in_der_zelle_haelt_den_streifen_wach():
    async def aktion(pg, app):
        await _zellen_frame(pg)
        await pg.evaluate("""() => { window.__wach=0; const alt=resetIdle;
            resetIdle=function(){ window.__wach++; return alt.apply(this, arguments); }; }""")
        # Eine fremde Nachricht (nicht aus der Zelle) zaehlt nicht
        await pg.evaluate("() => window.postMessage({t: EINGEBETTET_AKTIV}, location.origin)")
        await pg.wait_for_timeout(200)
        fremd = await pg.evaluate("window.__wach")
        box = await (await pg.query_selector('.bz[data-widget="ansicht"]')).bounding_box()
        await pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + 8)
        await pg.wait_for_timeout(300)
        return fremd, await pg.evaluate("window.__wach")
    (fremd, nach_tipp), fehler = _lauf(aktion)
    assert fehler == []
    assert fremd == 0
    assert nach_tipp >= 1, "der Tipp in der Zelle setzt die Leerlaufzeit des Streifens zurueck"


def test_name_des_streifens_bleibt_im_localstorage():
    """Der Streifen hat seinen Namen im localStorage (benannt im Konfigurator);
    die Zelle teilt ihn und meldet sich trotzdem ohne Namen."""
    init = "if (window === top) localStorage.setItem('lp_device', 'streifen');"

    async def aktion(pg, app):
        f = await _zellen_frame(pg)
        verb = sorted((i.get("dev", ""), bool(i.get("eingebettet"))) for i in app.conn_info.values())
        return verb, await f.evaluate("DEVICE_ID"), await pg.evaluate("localStorage.getItem('lp_device')")
    (verb, innen_id, gespeichert), fehler = _lauf(aktion, init_js=init, adresse="/")
    assert fehler == []
    assert verb == [("", True), ("streifen", False)]
    assert innen_id == "" and gespeichert == "streifen"


def test_raum_display_in_einer_eingebetteten_visu_zeigt_nur_einen_hinweis():
    async def aktion(pg, app):
        z = await pg.query_selector('.bz[data-widget="ansicht"]')
        return await z.inner_text(), await z.query_selector("iframe")
    (text, iframe), fehler = _lauf(aktion, adresse="/?panel=streifen&eingebettet=1")
    assert fehler == []
    assert iframe is None and "kein weiteres Raum-Display" in text


def test_eigene_und_unbekannte_ansicht_zeigen_einen_hinweis():
    zellen = ({"x": 1, "y": 0, "w": 1, "h": 2, "widget": "ansicht:streifen"},
              {"x": 2, "y": 0, "w": 1, "h": 2, "widget": "ansicht:geloescht"})

    async def aktion(pg, app):
        return await pg.evaluate("""() => [...document.querySelectorAll('.bz[data-widget="ansicht"]')]
            .map(z => [z.innerText.trim(), !!z.querySelector('iframe')])""")
    hinweise, fehler = _lauf(aktion, app=_app(zellen))
    assert fehler == []
    assert hinweise == [["Diese Ansicht kann sich nicht selbst zeigen", False], ["Ansicht nicht gefunden", False]]
