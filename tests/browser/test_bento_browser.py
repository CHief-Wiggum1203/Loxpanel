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
import base64
import shutil

import aiohttp
from pathlib import Path

import pytest
from aiohttp import web

from lox import EFM, HAUS_FAVORITEN, W, anlage, haus_anlage, raum_anlage, serve, visu_starten
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


@pytest.mark.parametrize("format_", ["2560x720", "1920x480"])
def test_automatisches_raster_laesst_den_bento_faktor(format_):
    """Ansicht mit automatischem Raster (ui.grid "auto"): der Kachelfaktor der
    Bento-Seite kommt aus ihrer Einheitszelle, nicht aus der Rasterrechnung der
    Kachelseiten - sonst bleiben Symbol und Schrift einer grossen Zelle klein
    (Befund am Wohnzimmer-Streifen, Luftdruck in einer 1x1-Zelle)."""
    app = _app("https://drucker.invalid/")
    app.panels["streifen"]["ui"]["grid"] = "auto"

    async def aktion(pg):
        await pg.evaluate("onScreenResize()")   # wie der ResizeObserver des Kastens
        return await pg.evaluate("""() => { const br=bentoMessen(el('grid'));
          return {soll: LoxRaster.kachelFaktorFuer(br.zw, br.zh),
                  ist: parseFloat(getComputedStyle(document.querySelector('.screen')).getPropertyValue('--ks'))}; }""")
    erg, fehler = asyncio.run(_lauf_mit(app, aktion, *FORMATE[format_]))
    assert fehler == [] and abs(erg["ist"] - erg["soll"]) < 0.01, erg


# ---- Wischen zwischen Bento-Seiten (docs/VISION.md "Wischen zwischen Bento-Seiten") ----
# Leiste: Bento-Seite A, eine normale Seite, Bento-Seite B. A traegt einen
# Spieler (Tasten), eine kleine und eine grosse Kachel, B eine Uhr und eine Kachel.
STREIFEN = ["2560x720", "1920x480"]
SEITE_A = [{"x": 0, "y": 0, "w": 1, "h": 2, "widget": "clock"},
           {"x": 1, "y": 0, "w": 2, "h": 1, "widget": "player:Z1"},
           {"x": 1, "y": 1, "w": 1, "h": 1, "ids": ["S1"]},
           {"x": 3, "y": 0, "w": 3, "h": 2, "ids": ["S3"]}]
SEITE_B = [{"x": 0, "y": 0, "w": 2, "h": 2, "widget": "clock"},
           {"x": 2, "y": 0, "w": 1, "h": 1, "ids": ["S2"]}]
ZONE = {"name": "Musik", "type": "AudioZone", "uuidAction": "Z1", "room": "r1", "cat": "c1",
        "states": {"playState": "z-ps"}}


def _spieler(zone):
    """Bloecke des Spielers wie player_blocks: Titel und die drei Tasten."""
    return [{"k": "title", "text": "Lied", "sub": "Band"},
            {"k": "row", "cells": [{"icon": "prev", "label": "Zurück", "cmd": {"uuid": zone, "cmd": "prev"}},
                                   {"icon": "play", "label": "Wiedergabe", "big": True,
                                    "cmd": {"uuid": zone, "cmd": "play"}},
                                   {"icon": "next", "label": "Weiter", "cmd": {"uuid": zone, "cmd": "next"}}]}]


def _zwei_seiten(monkeypatch, befehle: list, ui=None) -> W.App:
    struktur, states = raum_anlage()
    struktur["controls"]["Z1"] = ZONE
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    app.states = {**states, "z-ps": 0}
    app.panels = W.App._sanitize_panels({"streifen": {
        "title": "Streifen", "tabs": ["auswahl", "favoriten", "auswahl2"], "ui": {"tileSet": "edge", **(ui or {})},
        "pickTabs": [{"name": "A", "picks": ["S1", "S3", "Z1"], "bento": {"cols": 6, "rows": 2, "cells": SEITE_A}},
                     {"name": "B", "picks": ["S2"], "bento": {"cols": 6, "rows": 2, "cells": SEITE_B}}]}})
    monkeypatch.setattr(app, "player_blocks", _spieler)

    async def command(uuid, cmd, pin=None):
        befehle.append((uuid, cmd))
        return "200"
    app.command = command
    return app


def _streifen_lauf(app, format_, aktion):
    """Visu mit Touch-Display im Format starten, aktion(pg, cdp) -> (Ergebnis, Skriptfehler)."""
    w, h = FORMATE[format_]

    async def lauf():
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": w, "height": h}, has_touch=True, locale="de-DE")
                pg = await ctx.new_page()
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=streifen")
                await pg.wait_for_selector("#grid.bento > .bz", state="attached")
                await pg.evaluate("wake()")
                await pg.wait_for_timeout(900)
                cdp = await ctx.new_cdp_session(pg)
                erg = await aktion(pg, cdp)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        return erg, fehler
    return asyncio.run(lauf())


async def _mitte(pg, selektor):
    box = await pg.locator(selektor).first.bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


async def _wisch(cdp, x, y, dx, schritte=12):
    """Ein Finger bei (x, y) aufsetzen, waagerecht um dx ziehen, loslassen."""
    await cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
    for i in range(1, schritte + 1):
        await cdp.send("Input.dispatchTouchEvent",
                       {"type": "touchMove", "touchPoints": [{"x": x + dx * i / schritte, "y": y}]})
        await asyncio.sleep(0.016)
    await cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})


async def _tipp(cdp, x, y):
    await cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
    await cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})


async def _auf_seite(pg, tab):
    """Bis die Seite steht und der Uebergang vorbei ist."""
    await pg.wait_for_function(f"view && view.tab==={tab!r} && !document.documentElement.dataset.bentoRichtung"
                               " && !!document.querySelector('#grid.bento > .bz')", timeout=5000)


async def _bleibt(pg, tab):
    """Laenger als ein Uebergang warten: bleibt die Seite stehen?"""
    await pg.wait_for_timeout(await pg.evaluate("BENTO_WECHSEL_MS") + 400)
    return await pg.evaluate("[view.tab, stack[0].tab]") == [tab, tab]


@pytest.mark.parametrize("format_", STREIFEN)
def test_wisch_wechselt_zur_naechsten_bento_seite(format_, monkeypatch):
    app = _zwei_seiten(monkeypatch, [])
    w = FORMATE[format_][0]

    async def aktion(pg, cdp):
        x, y = await _mitte(pg, '.tile[data-id="S3"]')
        await _wisch(cdp, x, y, -0.2 * w)            # nach links: naechste Bento-Seite, favoriten uebersprungen
        await _auf_seite(pg, "auswahl2")
        x, y = await _mitte(pg, '.bz[data-widget="clock"]')
        await _wisch(cdp, x, y, 0.2 * w)             # nach rechts: zurueck
        await _auf_seite(pg, "auswahl")
        x, y = await _mitte(pg, '.tile[data-id="S3"]')
        await _wisch(cdp, x, y, 0.2 * w)             # nach rechts auf der ersten: kein Rundlauf
        return await _bleibt(pg, "auswahl")
    bleibt, fehler = _streifen_lauf(app, format_, aktion)
    assert fehler == [] and bleibt, fehler


@pytest.mark.parametrize("format_", STREIFEN)
def test_tipp_in_die_leiste_gleitet(format_, monkeypatch):
    app = _zwei_seiten(monkeypatch, [])

    async def aktion(pg, cdp):
        # wann der Uebergang endet: mit der Antwort, nicht erst an der Grenze
        richtung = await pg.evaluate("""() => { const h=document.documentElement, t0=performance.now();
          new MutationObserver((l, o)=>{ if(!h.dataset.bentoRichtung){ window.__ende=performance.now()-t0; o.disconnect(); } })
            .observe(h, {attributes:true, attributeFilter:['data-bento-richtung']});
          document.querySelector('#tabs .tab[data-tab="auswahl2"]').click();
          return h.dataset.bentoRichtung || ''; }""")
        await pg.wait_for_timeout(await pg.evaluate("BENTO_WECHSEL_GRENZE_MS"))
        nach = await pg.evaluate("[document.documentElement.dataset.bentoRichtung || '', view.tab]")
        ende = await pg.evaluate("[window.__ende, BENTO_WECHSEL_MS, BENTO_WECHSEL_GRENZE_MS]")
        # zur normalen Seite wie bisher: ohne Uebergang
        normal = await pg.evaluate("""() => { document.querySelector('#tabs .tab[data-tab="favoriten"]').click();
          return document.documentElement.dataset.bentoRichtung || ''; }""")
        await pg.wait_for_function("view && view.tab==='favoriten'", timeout=5000)
        return richtung, nach, normal, ende
    (richtung, nach, normal, (ende, dauer, grenze)), fehler = _streifen_lauf(app, format_, aktion)
    assert fehler == [], fehler
    assert richtung == "vor" and nach == ["", "auswahl2"] and normal == "", (richtung, nach, normal)
    assert dauer <= ende < grenze, (ende, dauer, grenze)


@pytest.mark.parametrize("format_", STREIFEN)
def test_wisch_auf_taste_blaettert_nicht(format_, monkeypatch):
    befehle = []
    app = _zwei_seiten(monkeypatch, befehle)
    w = FORMATE[format_][0]

    async def aktion(pg, cdp):
        tasten = await pg.locator('.bz[data-widget="player"] .bz-trans .btn').count()
        x, y = await _mitte(pg, '.bz[data-widget="player"] .bz-trans .btn')
        await _wisch(cdp, x, y, -0.2 * w)
        auf_taste = await _bleibt(pg, "auswahl")
        # Seiten-Wisch am Rand (kein Ziel), gleich danach ein Tipp auf eine Kachel: gesperrt
        sx, sy = await _mitte(pg, '.tile[data-id="S3"]')
        await _wisch(cdp, sx, sy, 0.2 * w)
        kx, ky = await _mitte(pg, '.tile[data-id="S1"]')
        await _tipp(cdp, kx, ky)
        await pg.wait_for_timeout(300)
        direkt = [b for b in befehle if b[0] == "S1"]
        # nach der Sperre wirkt der Tipp wieder
        await pg.wait_for_timeout(await pg.evaluate("BENTO_KLICKSPERRE_MS"))
        await _tipp(cdp, kx, ky)
        await pg.wait_for_timeout(400)
        spaeter = [b for b in befehle if b[0] == "S1"]
        # und von der grossen Kachel aus blaettert derselbe Wisch
        await _wisch(cdp, sx, sy, -0.2 * w)
        await _auf_seite(pg, "auswahl2")
        return tasten, auf_taste, direkt, spaeter
    (tasten, auf_taste, direkt, spaeter), fehler = _streifen_lauf(app, format_, aktion)
    assert fehler == [], fehler
    assert tasten == 3 and auf_taste, (tasten, auf_taste)
    assert direkt == [] and len(spaeter) == 1, (direkt, spaeter)


@pytest.mark.parametrize("format_", STREIFEN)
def test_verlorener_wisch_blaettert_spaeter_nicht(format_, monkeypatch):
    """Erreicht das Ende eines Fingers #grid nicht (die Kachel unter ihm fiel
    weg), darf sein Anfang keinen spaeteren Wisch auf einer Taste zum
    Blaettern machen."""
    app = _zwei_seiten(monkeypatch, [])
    w = FORMATE[format_][0]

    async def aktion(pg, cdp):
        x, y = await _mitte(pg, '.tile[data-id="S3"]')
        await cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        # die Kachel unter dem Finger faellt weg: ihr touchend erreicht #grid nicht
        await pg.evaluate("""() => document.querySelector('.tile[data-id="S3"]').remove()""")
        await cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        tx, ty = await _mitte(pg, '.bz[data-widget="player"] .bz-trans .btn')
        await _wisch(cdp, tx, ty, -0.2 * w)
        return await _bleibt(pg, "auswahl")
    bleibt, fehler = _streifen_lauf(app, format_, aktion)
    assert fehler == [] and bleibt, fehler


@pytest.mark.parametrize("format_", STREIFEN)
def test_zwei_finger_blaettern_nicht(format_, monkeypatch):
    from test_gesten_browser import zwei_finger_quer
    app = _zwei_seiten(monkeypatch, [], ui={"gesten": True})
    gesten = []

    async def geste(ws, data):
        gesten.append(data)
        return None
    app.geste = geste
    w = FORMATE[format_][0]

    async def aktion(pg, cdp):
        x, y = await _mitte(pg, '.tile[data-id="S3"]')
        await zwei_finger_quer(cdp, y, x, x - 0.2 * w)
        return await _bleibt(pg, "auswahl")
    bleibt, fehler = _streifen_lauf(app, format_, aktion)
    assert fehler == [] and bleibt, fehler
    assert gesten and all(g.get("t") == "geste" for g in gesten), gesten


# Stellvertreter fuer eine Antwort, die nie kommt: die Visu verwirft die
# view-Nachricht der Seite B, bevor sie sie zeichnet
VIEW_B_VERWERFEN = """() => { const echt=ws.onmessage;
  ws.onmessage=e=>{ let m=null; try{ m=JSON.parse(e.data); }catch(x){}
    if(m && m.t==='view' && m.tab==='auswahl2') return; echt.call(ws, e); }; }"""


@pytest.mark.parametrize("format_", STREIFEN)
def test_uebergang_haengt_nicht(format_, monkeypatch):
    befehle = []
    app = _zwei_seiten(monkeypatch, befehle)

    async def aktion(pg, cdp):
        await pg.evaluate(VIEW_B_VERWERFEN)
        richtung = await pg.evaluate("""() => { document.querySelector('#tabs .tab[data-tab="auswahl2"]').click();
          return document.documentElement.dataset.bentoRichtung || ''; }""")
        await pg.wait_for_timeout(await pg.evaluate("BENTO_WECHSEL_GRENZE_MS") + 100)
        nach = await pg.evaluate("document.documentElement.dataset.bentoRichtung || ''")
        kx, ky = await _mitte(pg, '.tile[data-id="S1"]')
        await _tipp(cdp, kx, ky)
        await pg.wait_for_timeout(400)
        return richtung, nach
    (richtung, nach), fehler = _streifen_lauf(app, format_, aktion)
    assert fehler == [], fehler
    assert richtung == "vor" and nach == "", (richtung, nach)
    assert [b for b in befehle if b[0] == "S1"], befehle


# ---- Audio-Zelle mit Raum und Raumfavoriten (docs/VISION.md) --------------------
# Zone Essen-Kochen-Wohnen aus haus_anlage() mit fuenf Favoriten, umbenannt,
# damit Raum und Zonenname sich unterscheiden.

def _audio_app(befehle: list, zelle: dict, zeilen: int = 2) -> W.App:
    struktur, states = haus_anlage()
    struktur["controls"]["AZ"]["name"] = "Musik"
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    app.states = states
    app.panels = W.App._sanitize_panels({"streifen": {
        "title": "Streifen", "tabs": ["auswahl"], "ui": {"tileSet": "edge"},
        "pickTabs": [{"name": "Streifen", "picks": [],
                      "bento": {"cols": 6, "rows": zeilen, "cells": [zelle]}}]}})

    async def command(uuid, cmd, pin=None):
        befehle.append((uuid, cmd))
        return "200"
    app.command = command
    return app


# Pruefung (PRUEFEN) nur fuer die Audio-Zelle
PRUEFEN_AUDIO = "() => (" + PRUEFEN + ")().filter(p => p.startsWith('player'))"


def test_audio_zelle_zeigt_raum_und_favoriten():
    befehle = []
    app = _audio_app(befehle, {"x": 0, "y": 0, "w": 2, "h": 2, "widget": "player:AZ"})

    async def aktion(pg):
        lage = await pg.evaluate("""() => { const z=document.querySelector('.bz[data-widget="player"]'),
            r=z.querySelector('.bz-raum'), f=z.querySelector('.bz-favs');
          f._mark=1;
          return {raum: r.textContent, gross: getComputedStyle(r).textTransform,
                  favs: z.querySelectorAll('.bz-favs .fav').length,
                  namen: [...z.querySelectorAll('.bz-favs .favn')].map(n=>n.textContent),
                  sichtbar: f.getBoundingClientRect().height>0}; }""")
        probleme = await pg.evaluate(PRUEFEN_AUDIO)
        # Lautstaerke aendert sich: die Reihe bleibt derselbe Knoten (Scrollstand, Cover)
        app.states["az3"] = 40
        app._mark_dirty()
        await pg.wait_for_function("document.querySelector('.bz[data-widget=\"player\"] .sld').value==='40'",
                                   timeout=5000)
        bleibt = await pg.evaluate("document.querySelector('.bz-favs')._mark===1")
        await pg.click('.bz-favs .fav[data-f="1"]')
        await pg.wait_for_timeout(400)
        await pg.click('.bz-raum')
        await pg.wait_for_function("view && view.route && view.route.view==='sources'", timeout=5000)
        ziel = await pg.evaluate("view.route")
        return lage, probleme, bleibt, ziel
    (lage, probleme, bleibt, ziel), fehler = asyncio.run(_lauf_mit(app, aktion, *FORMATE["2560x720"]))
    assert fehler == [], fehler
    assert lage["raum"] == "Essen-Kochen-Wohnen" and lage["gross"] == "uppercase", lage
    assert lage["favs"] == len(HAUS_FAVORITEN) and lage["namen"] == HAUS_FAVORITEN and lage["sichtbar"], lage
    assert probleme == [], probleme
    assert bleibt
    assert ("AZ", "roomfav/play/2") in befehle, befehle
    assert ziel == {"view": "sources", "id": "AZ"}, ziel


@pytest.mark.parametrize("zeilen, hstufe", [(3, "klein"), (2, "mittel")])
def test_kleine_audio_zelle_ohne_favoriten(zeilen, hstufe):
    """Hoehenstufe klein: keine Reihe (Spec). Eine 1x1-Zelle mittlerer Hoehe hat
    unter Tasten und Lautstaerke auch keinen Platz (bento.js bentoFavsLage)."""
    app = _audio_app([], {"x": 0, "y": 0, "w": 1, "h": 1, "widget": "player:AZ"}, zeilen=zeilen)

    async def aktion(pg):
        lage = await pg.evaluate("""() => { const z=document.querySelector('.bz[data-widget="player"]'),
            f=z.querySelector('.bz-favs'), r=z.querySelector('.bz-raum');
          return {hstufe: z.dataset.hstufe, favs: !!f && f.getBoundingClientRect().height>0,
                  raum: !!r && r.getBoundingClientRect().height>0}; }""")
        return lage, await pg.evaluate(PRUEFEN_AUDIO)
    (lage, probleme), fehler = asyncio.run(_lauf_mit(app, aktion, *FORMATE["1280x400"]))
    assert fehler == [], fehler
    assert lage == {"hstufe": hstufe, "favs": False, "raum": True}, lage
    assert probleme == [], probleme


@pytest.mark.parametrize("format_", list(FORMATE))
def test_breite_audio_zelle_stellt_favoriten_daneben(format_):
    """2x1 auf dem Streifen ist breit, aber flach: die Reihe steht rechts neben
    dem Spieler und nichts ragt heraus."""
    app = _audio_app([], {"x": 0, "y": 0, "w": 2, "h": 1, "widget": "player:AZ"})

    async def aktion(pg):
        lage = await pg.evaluate("""() => { const z=document.querySelector('.bz[data-widget="player"]');
          return {favs: z.dataset.favs, sichtbar: z.querySelector('.bz-favs').getBoundingClientRect().height>0}; }""")
        return lage, await pg.evaluate(PRUEFEN_AUDIO)
    (lage, probleme), fehler = asyncio.run(_lauf_mit(app, aktion, *FORMATE[format_]))
    assert fehler == [], fehler
    assert lage == {"favs": "rechts", "sichtbar": True}, lage
    assert probleme == [], probleme


# Bild eines MJPEG-Stroms (multipart/x-mixed-replace): 16x12 Pixel, also 4:3 wie
# eine Tuerstation, oben rot, unten blau - schneidet die Zelle ab, fehlt das Blau
BILD = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAABAAAAAMCAIAAADkharWAAAAGUlEQVR42mM4YGBAEmIYkRoMAg6QhEakBgAFPeQBx5WAEwAAAABJRU5ErkJggg==")
KAMERAS = {f"K{i}": {"name": f"Kamera {i}", "type": "Intercom", "uuidAction": f"K{i}", "room": "r1", "cat": "c1",
                     "details": {}, "states": {"bell": f"k{i}-bell"}} for i in (1, 2)}
# Kamera-Zellen: Quelle und Hoehe des Bildes, Hoehe der Zelle
BILDER = """() => [...document.querySelectorAll('#grid.bento > .bz')].map(z => {
  const i=z.querySelector('.video img');
  const r=e=>{ const b=e.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.top), Math.round(b.right), Math.round(b.bottom)]; };
  return {src: i ? i.getAttribute('src') : null, zelle: Math.round(z.getBoundingClientRect().height),
          bild: i ? Math.round(i.getBoundingClientRect().height) : 0,
          imgKasten: i ? r(i) : null, feld: i ? r(i.parentElement) : null}; })"""


async def _kameras() -> tuple:
    """Kameras, die MJPEG senden, bis der Abrufer trennt -> (runner, port,
    offene Stroeme je Pfad, alle Abrufe)."""
    offen, abrufe = {}, []

    async def strom(request):
        abrufe.append(request.path)
        resp = web.StreamResponse(headers={"Content-Type": "multipart/x-mixed-replace; boundary=bild"})
        await resp.prepare(request)
        offen[request.path] = offen.get(request.path, 0) + 1
        try:
            while True:
                await resp.write(b"--bild\r\nContent-Type: image/png\r\nContent-Length: %d\r\n\r\n%s\r\n"
                                 % (len(BILD), BILD))
                await asyncio.sleep(0.2)
        except ConnectionResetError:
            pass
        finally:
            offen[request.path] -= 1
        return resp
    cam = web.Application()
    cam.router.add_get("/{pfad}", strom)
    runner, port = await serve(cam)
    return runner, port, offen, abrufe


def test_zwei_kameras_untereinander(tmp_path):
    """Im Forum gewuenscht: mehrere Kamerabilder untereinander, je in
    waehlbarer Hoehe (Drittel, Haelfte, ganz). Auf einer Bento-Seite ist das je
    eine Zelle, hier oben ein Drittel und darunter zwei Drittel. Beide Bilder
    laufen zugleich, je mit eigenem Strom ueber /mjpeg zur Kamera, und ein
    neuer Stand vom Server laesst beide Bilder und Stroeme stehen."""
    async def lauf():
        crunner, cport, offen, abrufe = await _kameras()
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(KAMERAS))
        app.states = {"k1-bell": 0, "k2-bell": 0}
        app.intercom_cfg = {u: {"url": f"http://127.0.0.1:{cport}/{u.lower()}"} for u in KAMERAS}
        app.panels = W.App._sanitize_panels({"kameras": {
            "title": "Kameras", "tabs": ["auswahl"],
            "pickTabs": [{"name": "Kameras", "picks": [], "bento": {"cols": 1, "rows": 3, "cells": [
                {"x": 0, "y": 0, "w": 1, "h": 1, "widget": "camera:K1"},
                {"x": 0, "y": 1, "w": 1, "h": 2, "widget": "camera:K2"}]}}]}})
        runner, port, bc = await visu_starten(app, [("GET", "/mjpeg", W.mjpeg_handler)])
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 800, "height": 1280}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=kameras")
                await pg.wait_for_selector("#grid.bento > .bz", state="attached")
                await pg.evaluate("wake()")
                await pg.wait_for_function("""() => { const b=[...document.querySelectorAll('#grid.bento .video img')];
                    return b.length===2 && b.every(i => i.complete && i.naturalWidth>0); }""", timeout=8000)
                lage = await pg.evaluate(BILDER)
                probleme = await pg.evaluate(PRUEFEN)
                await pg.screenshot(path=str(tmp_path / "bento_zwei_kameras.png"))
                _ablegen(tmp_path, "bento_zwei_kameras.png")
                stroeme = dict(offen)
                await pg.evaluate("() => document.querySelectorAll('#grid.bento .video img').forEach(i => i._mark=1)")
                app._dirty = True                       # neuer Stand: die Zellen kommen neu
                await pg.wait_for_timeout(1500)
                bleibt = await pg.evaluate(
                    "() => [...document.querySelectorAll('#grid.bento .video img')].map(i => i._mark === 1)")
                danach = (dict(offen), len(abrufe))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
            await crunner.cleanup()
        return lage, probleme, stroeme, bleibt, danach, fehler
    lage, probleme, stroeme, bleibt, danach, fehler = asyncio.run(lauf())
    assert fehler == [], fehler
    assert [z["src"] for z in lage] == ["/mjpeg?id=K1", "/mjpeg?id=K2"], lage
    assert all(z["bild"] > 0 for z in lage), lage
    assert 1.8 < lage[1]["zelle"] / lage[0]["zelle"] < 2.2, lage   # zwei Drittel unter einem Drittel
    # das Bild passt in sein Feld (eingepasst, nicht abgeschnitten), auch in der flachen Zelle
    assert [z["imgKasten"] for z in lage] == [z["feld"] for z in lage], lage
    assert probleme == [], probleme
    assert stroeme == {"/k1": 1, "/k2": 1}, stroeme                 # beide zugleich, je einer
    assert bleibt == [True, True], "die Bilder bleiben dieselben Knoten"
    assert danach == ({"/k1": 1, "/k2": 1}, 2), danach             # kein neuer Abruf, nichts getrennt
