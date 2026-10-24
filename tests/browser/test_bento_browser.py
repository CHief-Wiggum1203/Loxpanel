"""LoxOS (Fork, docs/VISION.md): Bento-Seiten in Chromium.

Eine 6x2-Seite mit jeder Zellart (Uhr, Wetter, Kalender, Energiefluss, Werte,
Kacheln, Webseite) im Kachel-Set "edge" auf den drei Streifen-Formaten. Die
Daten laufen durch die echte Kette (Struktur, States, Front aus dem Nachbau
in test_front_tabs_browser, Webseite von einem eigenen Testserver). Geprueft:
nichts ragt ueber seine Zelle oder den Schirm, kein Text wird hart
abgeschnitten, ohne weitere Seiten keine Tab-Leiste, keine Skriptfehler.
Screenshots liegen im tmp_path (CI-Artefakt).
"""
import asyncio
import shutil

import aiohttp
from pathlib import Path

import pytest
from aiohttp import web

from lox import EFM, W, raum_anlage, serve, visu_starten
from test_front_tabs_browser import _front

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

FORMATE = {"2560x720": (2560, 720), "1920x480": (1920, 480), "1280x400": (1280, 400)}

# Screenshots zusaetzlich hierhin, wenn gesetzt (zum Ansehen ausserhalb von pytest)
SCREENSHOTS = Path(__file__).resolve().parent.parent.parent / "test-screenshots"

TESTSEITE = "<!doctype html><html><body style='margin:0;font:16px sans-serif'><h1>Drucker</h1></body></html>"


def _zellen(url: str) -> list:
    return [{"x": 0, "y": 0, "w": 1, "h": 2, "widget": "clock"},
            {"x": 1, "y": 0, "w": 2, "h": 1, "widget": "weather"},
            {"x": 3, "y": 0, "w": 2, "h": 1, "widget": "energy:F"},
            {"x": 5, "y": 0, "w": 1, "h": 1, "widget": "status:S1,S2,T1"},
            {"x": 1, "y": 1, "w": 1, "h": 1, "ids": ["S1", "S2"]},
            {"x": 2, "y": 1, "w": 1, "h": 1, "ids": ["S3"]},
            {"x": 3, "y": 1, "w": 2, "h": 1, "widget": "calendar"},
            {"x": 5, "y": 1, "w": 1, "h": 1, "widget": "iframe", "url": url, "name": "Drucker"}]


def _app(url: str, tabs=("auswahl",)) -> W.App:
    struktur, states = raum_anlage()
    struktur["controls"]["F"] = EFM
    states.update({"f-a0": 0.8, "f-a1": 3.2, "f-a2": -0.6, "f-a3": 1.2, "s1": 1})
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    app.states = states
    app.panels = W.App._sanitize_panels({"streifen": {
        "title": "Streifen", "tabs": list(tabs), "ui": {"tileSet": "edge"},
        "pickTabs": [{"name": "Streifen", "picks": ["S1", "S2", "S3", "T1"],
                      "bento": {"cols": 6, "rows": 2, "cells": _zellen(url)}}]}})
    return app


# Was ueber seine Zelle oder den Schirm ragt; Text, der ohne Auslassungszeichen
# abgeschnitten ist. Inhalte von scrollenden Bereichen und der iframe zaehlen nicht.
PRUEFEN = """() => {
  const raus=[], W=innerWidth, H=innerHeight;
  const g=document.getElementById('grid');
  if(g.scrollWidth>g.clientWidth+1 || g.scrollHeight>g.clientHeight+1) raus.push('Raster laeuft ueber');
  // Ein Scroller zaehlt nur in der Richtung, in die er als Liste scrollt: was in
  // einer waagerechten Wischzeile unten abgeschnitten ist, bleibt ein Fehler.
  const scrollt=(e, achse)=>{ for(let p=e.parentElement; p && !p.classList.contains('bz'); p=p.parentElement){
      const cs=getComputedStyle(p), s=o=>o==='auto'||o==='scroll';
      const y=s(cs.overflowY) && p.scrollHeight>p.clientHeight+1, x=s(cs.overflowX) && p.scrollWidth>p.clientWidth+1;
      if(achse==='y' ? (y && !x) : (x && !y)) return true; } return false; };
  document.querySelectorAll('#grid.bento > .bz').forEach((z, i)=>{
    const r=z.getBoundingClientRect(), wo=(z.dataset.widget||'kacheln')+' '+i;
    if(r.right>W+1 || r.bottom>H+1 || r.left<-1 || r.top<-1) raus.push(wo+': Zelle ausserhalb');
    z.querySelectorAll('*').forEach(e=>{
      const cs=getComputedStyle(e); if(cs.display==='none' || cs.visibility==='hidden' || e.closest('[hidden]')) return;
      const er=e.getBoundingClientRect(); if(er.width<1 || er.height<1) return;
      const senkrecht=(er.bottom>r.bottom+1.5 || er.top<r.top-1.5) && !scrollt(e, 'y');
      const waagerecht=(er.right>r.right+1.5 || er.left<r.left-1.5) && !scrollt(e, 'x');
      if(senkrecht || waagerecht)
        raus.push(wo+': '+e.tagName.toLowerCase()+'.'+[...e.classList].join('.')+' ragt heraus');
      if(e.children.length===0 && e.textContent.trim() && cs.overflow!=='visible' && cs.textOverflow!=='ellipsis'
         && (e.scrollWidth>e.clientWidth+1 || e.scrollHeight>e.clientHeight+2))
        raus.push(wo+': Text abgeschnitten in '+e.tagName.toLowerCase()+'.'+[...e.classList].join('.'));
    });
  });
  return raus;
}"""


async def _seite(b, port, w, h, fehler):
    pg = await b.new_page(viewport={"width": w, "height": h}, locale="de-DE")
    pg.on("pageerror", lambda e: fehler.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{port}/?panel=streifen")
    await pg.wait_for_selector("#grid.bento > .bz", state="attached")
    await pg.evaluate("wake()")
    await pg.wait_for_timeout(900)
    return pg


def _ablegen(tmp_path: Path, name: str) -> None:
    if SCREENSHOTS.is_dir():
        shutil.copy(tmp_path / name, SCREENSHOTS / name)


@pytest.mark.parametrize("format_", list(FORMATE))
def test_bento_seite_auf_streifen(format_, tmp_path, monkeypatch):
    w, h = FORMATE[format_]

    async def lauf():
        seite = web.Application()
        seite.router.add_get("/", lambda r: web.Response(text=TESTSEITE, content_type="text/html"))
        srunner, sport = await serve(seite)
        app = _app(f"http://127.0.0.1:{sport}/")
        app._front = app._front_payload(await _front(monkeypatch))
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _seite(b, port, w, h, fehler)
                name = f"bento_{format_}.png"
                await pg.screenshot(path=str(tmp_path / name))
                _ablegen(tmp_path, name)
                probleme = await pg.evaluate(PRUEFEN)
                lage = await pg.evaluate("""() => ({
                  zellen: document.querySelectorAll('#grid.bento > .bz').length,
                  tabs: getComputedStyle(document.getElementById('tabs')).display,
                  voll: document.querySelector('.screen').classList.contains('bentovoll'),
                  breite: document.getElementById('grid').getBoundingClientRect().width,
                  uhr: (document.querySelector('.bz-zeit')||{}).textContent||'',
                  kacheln: [...document.querySelectorAll('#grid.bento .tile[data-id]')].map(t=>t.dataset.id),
                  energie: !!document.querySelector('#grid.bento .bz[data-widget="energy"] .epage'),
                  iframe: (document.querySelector('#grid.bento iframe')||{}).getAttribute
                          ? document.querySelector('#grid.bento iframe').getAttribute('sandbox') : null})""")
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
            await srunner.cleanup()
        return probleme, lage, fehler

    probleme, lage, fehler = asyncio.run(lauf())
    assert fehler == [], fehler
    assert lage["zellen"] == 8 and lage["voll"] and lage["tabs"] == "none", lage
    assert lage["breite"] >= w - 1, "nur eine Seite: volle Breite ohne Leiste"
    assert lage["uhr"] and lage["kacheln"] == ["S1", "S2", "S3"] and lage["energie"], lage
    assert lage["iframe"] == "allow-scripts allow-same-origin allow-forms", lage
    assert probleme == [], probleme


def _lauf_mit(app, aktion, w=1280, h=400, seitenserver=None):
    """Visu starten, Seite oeffnen, aktion(pg) ausfuehren -> (Ergebnis, Skriptfehler)."""
    async def lauf():
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _seite(b, port, w, h, fehler)
                erg = await aktion(pg)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        return erg, fehler
    return lauf()


def test_gleiche_seite_zieht_nur_die_zellen_nach(monkeypatch):
    """Ein Wert aendert sich: die Kachel zeigt ihn, aber Zellen und iframe
    bleiben dieselben Knoten - eine Webseite oder ein Kamerabild laedt sonst
    bei jeder Aenderung im Haus neu."""
    async def lauf():
        seite = web.Application()
        seite.router.add_get("/", lambda r: web.Response(text=TESTSEITE, content_type="text/html"))
        srunner, sport = await serve(seite)
        app = _app(f"http://127.0.0.1:{sport}/")
        app._front = app._front_payload(await _front(monkeypatch))

        async def aktion(pg):
            await pg.evaluate("document.querySelector('#grid.bento iframe')._mark=1;"
                              "document.querySelectorAll('#grid.bento > .bz').forEach(z=>z._mark=1)")
            vorher = await pg.evaluate("document.querySelector('.tile[data-id=S1] .sub').textContent")
            app.states["s1"] = 0
            app._mark_dirty()
            await pg.wait_for_function("document.querySelector('.tile[data-id=S1] .sub').textContent!=="
                                       + repr(vorher), timeout=5000)
            return vorher, await pg.evaluate("""() => ({
              iframe: document.querySelector('#grid.bento iframe')._mark===1,
              zellen: [...document.querySelectorAll('#grid.bento > .bz')].every(z=>z._mark===1),
              nachher: document.querySelector('.tile[data-id=S1] .sub').textContent})""")
        try:
            return await _lauf_mit(app, aktion)
        finally:
            await srunner.cleanup()
    (vorher, erg), fehler = asyncio.run(lauf())
    assert fehler == [] and vorher == "Ein" and erg["nachher"] == "Aus", (vorher, erg, fehler)
    assert erg["iframe"] and erg["zellen"], erg


def test_gesperrte_webseite_zeigt_den_grund(monkeypatch):
    async def lauf():
        seite = web.Application()
        seite.router.add_get("/", lambda r: web.Response(text=TESTSEITE, content_type="text/html",
                                                         headers={"X-Frame-Options": "DENY"}))
        srunner, sport = await serve(seite)
        app = _app(f"http://127.0.0.1:{sport}/")
        async with aiohttp.ClientSession() as s:
            await app._bento_runde(s)          # die Pruefung des Servers, wie bento_task sie macht

        async def aktion(pg):
            return await pg.evaluate("""() => { const z=document.querySelector('.bz[data-widget="iframe"]');
              return {iframe: !!z.querySelector('iframe'), text: z.querySelector('.bz-wfehler').textContent}; }""")
        try:
            return await _lauf_mit(app, aktion)
        finally:
            await srunner.cleanup()
    erg, fehler = asyncio.run(lauf())
    assert fehler == [] and not erg["iframe"], erg
    assert "verbietet Einbetten" in erg["text"], erg


def test_mit_weiteren_seiten_bleibt_die_leiste():
    app = _app("https://drucker.invalid/", tabs=("auswahl", "favoriten"))

    async def aktion(pg):
        return await pg.evaluate("""() => ({voll: document.querySelector('.screen').classList.contains('bentovoll'),
          tabs: document.querySelectorAll('#tabs .tab').length,
          sichtbar: getComputedStyle(document.getElementById('tabs')).display!=='none'})""")
    erg, fehler = asyncio.run(_lauf_mit(app, aktion))
    assert fehler == [] and not erg["voll"] and erg["sichtbar"] and erg["tabs"] == 2, erg
