"""2 x 2-Kacheln aus dem Seiten-Editor (Punkt 10) in Chromium: rasterLage()
(raster.js) setzt eine hohe Kachel in zwei Zeilen derselben Seite - steht sie
in der letzten Zeile einer Seite, rueckt sie auf die naechste, und die Luecke
fuellt die naechste kleine Kachel. Die Visu setzt dann jede Kachel an ihre
Stelle (der Fluss des Browsers kennt keine Seitengrenze), senkrecht auf dem
4"-Panel wie waagerecht auf dem Tablet, und der Abgleich ohne Neuaufbau
(updateGrid) behaelt sie."""
import asyncio

import pytest

from lox import W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

KACHELN = {f"S{i}": {"name": f"Licht {i}", "type": "Switch", "uuidAction": f"S{i}", "room": "r1", "cat": "c1",
                     "states": {"active": f"s{i}"}} for i in range(16)}

# Lage, Zeile, Spalte je Kachel: was die Rechnung sagt, und wo die Kachel steht
MESSEN = """() => { const g = document.getElementById('grid'), quer = g.classList.contains('hpages');
  const ks = [...g.querySelectorAll('.tile[data-id]')], lage = rasterLage(ks.map(n => kachelGroesse(n._it)), gridCols, gridRows);
  const t = ks.find(n => !n.classList.contains('w2')).getBoundingClientRect(), gap = parseFloat(getComputedStyle(g).getPropertyValue('--gap'));
  const stelle = n => { const box = (quer ? n.closest('.page') : g).getBoundingClientRect(), r = n.getBoundingClientRect();
    const seite = quer ? [...g.querySelectorAll('.page')].indexOf(n.closest('.page')) : 0;
    const zeile = Math.round((r.top - box.top - parseFloat(getComputedStyle(g).getPropertyValue('--pad')) + (quer ? 0 : g.scrollTop)) / (t.height + gap));
    return {seite: seite, zeile: quer ? seite * gridRows + zeile : zeile,
            spalte: Math.round((r.left - box.left - parseFloat(getComputedStyle(g).getPropertyValue('--pad'))) / (t.width + gap)),
            breit: Math.round((r.width + gap) / (t.width + gap)), hoch: Math.round((r.height + gap) / (t.height + gap))}; };
  return {raster: [gridCols, gridRows], quer: quer, lage: {zeile: lage.zeile, spalte: lage.spalte, seiten: lage.seiten, hoch: lage.hoch},
          ids: ks.map(n => n.dataset.id), ist: ks.map(stelle), seiten: quer ? g.querySelectorAll('.page').length : null}; }"""


def _layout(picks, hoch):
    """Layout in der Folge von picks, die Kachel hoch als 2 x 2 (das Layout bestimmt die Reihenfolge)."""
    return [{"id": u, **({"w": 2, "h": 2} if u == hoch else {})} for u in picks]


def _lauf(ui, breite, hoehe, picks, layout, schritte=MESSEN, wachsen=None, monkeypatch=None, tiles=None):
    if wachsen is not None:
        monkeypatch.setattr(W, "KACHEL_WACHSEN", wachsen)

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(KACHELN))
        app.states = {f"s{i}": 0 for i in range(16)}
        app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["auswahl"], "ui": ui, "tiles": tiles or {},
                                                   "pickTabs": [{"name": "Mix", "picks": picks, "layout": layout,
                                                                 "byRoom": False}]}})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": breite, "height": hoehe})
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=p")
                await pg.wait_for_selector("#grid .tile[data-id]", state="attached")
                if await pg.locator("#saver:not(.hidden)").count():
                    await pg.click("#saver")
                await pg.wait_for_timeout(400)
                ergebnis = await (pg.evaluate(schritte) if isinstance(schritte, str) else schritte(pg))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return ergebnis
    return asyncio.run(lauf())


def test_rasterlage_mit_hohen_kacheln():
    """Die reine Rechnung: eine hohe Kachel belegt zwei Zeilen und zwei Spalten,
    die letzte Zeile einer Seite nimmt sie nicht; bei einer Zeile wird sie
    flach, bei einer Spalte klein. Zahlen (nur Breite) wie bisher."""
    def lauf_js(pg):
        return pg.evaluate("""() => { const l = (g, c, r) => { const x = LoxRaster.rasterLage(g, c, r);
            return {zeile: x.zeile, spalte: x.spalte, seiten: x.seiten, hoch: x.hoch}; };
          const H = {w: 2, h: 2};
          return {oben: l([H, 1, 1, 1, 1], 4, 2), grenze: l([1, 1, 1, 1, H], 2, 3), flach: l([H, 1], 4, 1),
                  schmal: l([H, 1], 1, 3), zahlen: l([2, 1, 2, 1], 3, 2)}; }""")
    r = _lauf({"cols": 2, "rows": 2}, 480, 480, ["S0"], [], schritte=lauf_js)
    assert r["oben"] == {"zeile": [0, 0, 0, 1, 1], "spalte": [0, 2, 3, 2, 3], "seiten": 1, "hoch": True}, r
    assert r["grenze"] == {"zeile": [0, 0, 1, 1, 3], "spalte": [0, 1, 0, 1, 0], "seiten": 2, "hoch": True}, r
    assert r["flach"] == {"zeile": [0, 0], "spalte": [0, 2], "seiten": 1, "hoch": False}, r
    assert r["schmal"] == {"zeile": [0, 1], "spalte": [0, 0], "seiten": 1, "hoch": False}, r
    assert r["zahlen"] == {"zeile": [0, 0, 1, 1], "spalte": [0, 2, 0, 2], "seiten": 1, "hoch": False}, r


def test_hohe_kachel_auf_dem_4zoll_panel():
    """3 x 3 fest, senkrecht: S5 (2 x 2) passt nach fuenf kleinen nicht mehr auf
    Seite 1 (dort bliebe nur die letzte Zeile), rueckt auf Seite 2, die Luecke
    neben S4 fuellt S6. Jede Kachel steht, wo die Rechnung sie hinsetzt."""
    picks = [f"S{i}" for i in range(10)]
    m = _lauf({"cols": 3, "rows": 3, "split": False}, 480, 480, picks, _layout(picks, "S5"))
    assert m["raster"] == [3, 3] and not m["quer"] and m["lage"]["hoch"], m
    i5 = m["ids"].index("S5")
    assert (m["lage"]["zeile"][i5], m["lage"]["spalte"][i5]) == (3, 0), m["lage"]
    assert m["lage"]["zeile"][m["ids"].index("S6")] == 1 and m["lage"]["seiten"] == 2, m["lage"]
    for i, ist in enumerate(m["ist"]):
        soll = {"zeile": m["lage"]["zeile"][i], "spalte": m["lage"]["spalte"][i], "breit": 2 if i == i5 else 1,
                "hoch": 2 if i == i5 else 1}
        assert {k: ist[k] for k in soll} == soll, (m["ids"][i], ist, soll)


def test_hohe_kachel_auf_waagerechten_seiten(monkeypatch):
    """Tablet quer, automatisch 5 x 3 (ohne Wachsen und Schrumpfen): nach zwoelf
    kleinen nimmt S12 (2 x 2) nicht die letzte Zeile, sondern Seite 2; sie
    liegt ganz in deren .page. updateGrid() gleicht ohne Neuaufbau ab und
    behaelt die Stelle."""
    picks = [f"S{i}" for i in range(15)]

    async def schritte(pg):
        vorher = await pg.evaluate(MESSEN)
        knoten = await pg.evaluate("""() => { const n = document.querySelector('#grid .tile[data-id="S12"]'); n._marke = 1;
            return {inplace: updateGrid(view.items), gleich: document.querySelector('#grid .tile[data-id="S12"]')._marke === 1,
                    stil: n.style.gridRow}; }""")
        return vorher, knoten
    m, knoten = _lauf({"grid": "auto"}, 893, 533, picks, _layout(picks, "S12"), schritte=schritte,
                      wachsen=1, monkeypatch=monkeypatch)
    assert m["raster"] == [5, 3] and m["quer"] and m["seiten"] == 2, m
    i12 = m["ids"].index("S12")
    assert (m["ist"][i12]["seite"], m["ist"][i12]["breit"], m["ist"][i12]["hoch"]) == (1, 2, 2), m["ist"][i12]
    for i, ist in enumerate(m["ist"]):
        assert (ist["zeile"], ist["spalte"]) == (m["lage"]["zeile"][i], m["lage"]["spalte"][i]), (m["ids"][i], ist)
    assert knoten == {"inplace": True, "gleich": True, "stil": "1 / span 2"}, knoten


def test_feste_stelle_auch_mit_eigenen_farben():
    """Eine Kachel mit eigener Symbolfarbe oder eigenem Hintergrund traegt
    Stilangaben vor ihrer festen Stelle: beide stehen als eigene Angaben im
    style - sonst schluckte die Farbe grid-row, und die Kachel stuende, wo
    der Fluss des Browsers sie hinsetzt. Gilt fuer den Aufbau (render) wie
    fuer den Abgleich (updateGrid), der den Stil dann nicht neu schreibt."""
    picks = [f"S{i}" for i in range(10)]
    tiles = {"S5": {"iconColor": "#e2695f"}, "S2": {"bg": "#203040"}, "S7": {"iconColor": "#52b881", "bg": "#302010"}}

    async def schritte(pg):
        stil = """() => [...document.querySelectorAll('#grid .tile[data-id]')].map(n => ({id: n.dataset.id,
            zeile: n.style.gridRow, spalte: n.style.gridColumn, ico: n.style.getPropertyValue('--ico').trim(),
            bg: n.style.backgroundColor}))"""
        vorher = await pg.evaluate(stil)
        knoten = await pg.evaluate("""() => { const ns = [...document.querySelectorAll('#grid .tile[data-id]')];
            const alt = ns.map(n => n.getAttribute('style')); const ok = updateGrid(view.items);
            return {inplace: ok, gleich: ns.every((n, i) => n.getAttribute('style') === alt[i])}; }""")
        return await pg.evaluate(MESSEN), vorher, knoten
    m, stil, knoten = _lauf({"cols": 3, "rows": 3, "split": False}, 480, 480, picks, _layout(picks, "S5"),
                            schritte=schritte, tiles=tiles)
    zeilen = {s["id"]: s for s in stil}
    for i, u in enumerate(m["ids"]):
        h = 2 if u == "S5" else 1
        assert zeilen[u]["zeile"] == f"{m['lage']['zeile'][i] + 1} / span {h}", (u, zeilen[u])
        assert zeilen[u]["spalte"] == f"{m['lage']['spalte'][i] + 1} / span {h}", (u, zeilen[u])
    assert zeilen["S5"]["ico"] == "#e2695f" and zeilen["S7"]["ico"] == "#52b881", zeilen
    assert zeilen["S2"]["bg"] == "rgb(32, 48, 64)", zeilen["S2"]
    assert knoten == {"inplace": True, "gleich": True}, knoten
