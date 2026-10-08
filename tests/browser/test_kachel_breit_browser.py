"""Breite Kacheln (2 x 1) in Chromium: Audio, Raumregelung und Energiefluss
belegen zwei Spalten (Klasse w2, grid-column: span 2), das Raster fliesst
dicht (eine Luecke vor einer breiten Kachel fuellt die naechste schmale), und
die Visu rechnet die Lage nach (rasterLage: Zeile je Kachel, Seiten,
Rastpunkte), damit Seiten-Snapping, Sprung zur Seite und das Wachsen der
Automatik mit breiten Kacheln stimmen. Der Kachelfaktor misst sich an einer
schmalen Kachel. Der Kachel-Editor stellt die Breite je Kachel ein."""
import asyncio
import math

import pytest

from lox import W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser


def _schalter(n: int) -> dict:
    return {f"S{i}": {"name": f"Licht {i}", "type": "Switch", "uuidAction": f"S{i}", "room": "r1", "cat": "c1",
                      "isFavorite": True, "states": {"active": f"s{i}"}} for i in range(n)}


BREIT = {
    "AZ": {"name": "Küche", "type": "AudioZoneV2", "uuidAction": "AZ", "room": "r1", "cat": "c1",
           "isFavorite": True, "states": {"playState": "az1", "songName": "az2"}},
    "RC": {"name": "Wohnen", "type": "IRoomControllerV2", "uuidAction": "RC", "room": "r1", "cat": "c1",
           "isFavorite": True, "states": {"tempActual": "rc1", "tempTarget": "rc2", "operatingMode": "rc3",
                                          "activeMode": "rc4", "prepareState": "rc5"}},
}
STATES = {"az1": 0, "az2": "", "rc1": 21.5, "rc2": 22.0, "rc3": 0, "rc4": 0, "rc5": 0}

MESSEN = """() => { const g = document.getElementById('grid'), sc = document.querySelector('.screen');
  const gap = parseFloat(getComputedStyle(g).getPropertyValue('--gap')) || 0;
  const r = e => e.getBoundingClientRect();
  const tiles = [...g.querySelectorAll('.tile[data-id]')].map(t => { const b = r(t);
    const pg = t.closest('.page'), seite = pg ? [...g.querySelectorAll('.page')].indexOf(pg) : 0;
    return {id: t.dataset.id, w2: t.classList.contains('w2'), snap: t.classList.contains('snap'), seite,
            top: Math.round(b.top), left: Math.round(b.left), breite: Math.round(b.width), hoehe: Math.round(b.height)}; });
  // blaettert: senkrecht eingerastet (.snapy, 4"-Panel) oder waagerechte Seiten mit Punkten (Tablet)
  return {tiles, gap, zeile: g._zeile || null, snapy: g.classList.contains('snapy'),
    blaettert: g.classList.contains('snapy') || g.classList.contains('punkte'), raster: [gridCols, gridRows],
    ks: parseFloat(getComputedStyle(sc).getPropertyValue('--ks')) || 1, scrollTop: g.scrollTop,
    gridTop: Math.round(r(g).top), gridBottom: Math.round(r(g).bottom)}; }"""


def _lage(breiten, cols, rows):
    """rasterLage() aus panel.html, in Python nachgebaut: Zeile je Kachel wie
    CSS grid-auto-flow: row dense sie setzt."""
    belegt, zeile = [], []
    for b in breiten:
        w = min(2 if b == 2 else 1, max(1, cols))
        r, c = 0, -1
        while c < 0:
            for cc in range(0, cols - w + 1):
                if all(not (r < len(belegt) and belegt[r][cc + k]) for k in range(w)):
                    c = cc
                    break
            if c < 0:
                r += 1
        while len(belegt) <= r:
            belegt.append([False] * cols)
        for k in range(w):
            belegt[r][c + k] = True
        zeile.append(r)
    return zeile, max(1, math.ceil(len(belegt) / max(1, rows)))


def _laufen(ui, breite, hoehe, bausteine, schritte=MESSEN, tiles=None):
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(bausteine))
        app.states = {**STATES, **{f"s{i}": i % 2 for i in range(60)}}
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"], "ui": ui,
                                                      **({"tiles": tiles} if tiles else {})}})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": breite, "height": hoehe})
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector("#grid .tile[data-id]", state="attached")
                if await pg.locator("#saver:not(.hidden)").count():
                    await pg.click("#saver")
                    await pg.wait_for_selector("#saver.hidden", state="attached")
                await pg.wait_for_timeout(500)
                ergebnis = await (pg.evaluate(schritte) if isinstance(schritte, str) else schritte(app, pg))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return ergebnis
    return asyncio.run(lauf())


def _zeilen_gemessen(m):
    """Zeile je Kachel aus den gemessenen Oberkanten (gleiche Oberkante = gleiche
    Zeile); mit waagerechten Seiten (Tablet) zaehlen die Zeilen seitenweise weiter."""
    rows = m["raster"][1]
    kanten = {s: sorted({t["top"] for t in m["tiles"] if t["seite"] == s}) for s in {t["seite"] for t in m["tiles"]}}
    return [t["seite"] * rows + kanten[t["seite"]].index(t["top"]) for t in m["tiles"]]


def test_zwei_spalten_und_dichter_fluss():
    """Festes 3 x 3 auf 800 x 480 (ohne Split): die breiten Kacheln sind doppelt
    so breit wie die schmalen (plus Abstand), die Lage stimmt mit rasterLage()
    ueberein, und eine schmale Kachel hinter einer breiten, die nicht mehr in
    die Zeile passte, rueckt in die Luecke davor (dense)."""
    m = _laufen({"cols": 3, "rows": 3, "split": False}, 800, 480, {**BREIT, **_schalter(8)})
    cols, rows = m["raster"]
    assert (cols, rows) == (3, 3), m["raster"]
    breit = [t for t in m["tiles"] if t["w2"]]
    schmal = [t for t in m["tiles"] if not t["w2"]]
    assert {t["id"] for t in breit} == {"AZ", "RC"} and len(schmal) == 8, m["tiles"]
    assert all(abs(t["breite"] - (2 * schmal[0]["breite"] + m["gap"])) <= 3 for t in breit), (breit, schmal[0])
    erwartet, seiten = _lage([2 if t["w2"] else 1 for t in m["tiles"]], cols, rows)
    assert m["zeile"] == erwartet, (m["zeile"], erwartet)
    assert _zeilen_gemessen(m) == erwartet, (_zeilen_gemessen(m), erwartet)
    # dense: mindestens eine schmale Kachel steht VOR einer breiten, die im DOM vor ihr kommt
    assert any(erwartet[j] < erwartet[i] for i, ti in enumerate(m["tiles"]) if ti["w2"]
               for j in range(i + 1, len(erwartet))), erwartet
    # Rastpunkt auf der ersten Kachel jeder Seite, Snapping ab zwei Seiten
    starts = []
    for i, z in enumerate(erwartet):
        if z % rows == 0 and z not in [erwartet[j] for j in starts]:
            starts.append(i)
    assert [i for i, t in enumerate(m["tiles"]) if t["snap"]] == starts, (m["tiles"], starts)
    assert m["snapy"] == (seiten > 1) and seiten == 2, (seiten, m["snapy"])


def test_sprung_zur_seite_mit_breiten_kacheln():
    """springeZu() landet auf der ersten Kachel der Seite, auf der die Zielkachel
    steht - mit breiten Kacheln ist das nicht mehr jede 9. Kachel."""
    async def schritte(app, pg):
        m = await pg.evaluate(MESSEN)
        ziel = next(t["id"] for t, z in zip(m["tiles"], m["zeile"]) if z >= m["raster"][1])   # erste Kachel auf Seite 2
        await pg.evaluate('springeZu(document.querySelector(".tile[data-id=\'%s\']"))' % ziel)
        await pg.wait_for_timeout(900)
        n = await pg.evaluate(MESSEN)
        return m, ziel, n
    m, ziel, n = _laufen({"cols": 3, "rows": 3, "split": False}, 800, 480, {**BREIT, **_schalter(12)}, schritte)
    assert n["scrollTop"] > 0, "zur zweiten Seite gescrollt"
    zt = next(t for t in n["tiles"] if t["id"] == ziel)
    assert n["gridTop"] - 1 <= zt["top"] <= n["gridTop"] + n["gap"] + 2, (zt, n["gridTop"])   # Zielkachel steht oben
    erste = [t for t, z in zip(n["tiles"], n["zeile"]) if z == n["raster"][1]]   # alle Kacheln der ersten Zeile von Seite 2
    assert all(abs(t["top"] - zt["top"]) <= 1 for t in erste), erste


def test_kachelfaktor_aus_schmaler_kachel():
    """Festes 2 x 2 am 4"-Panel: steht die breite Kachel vorn, misst sich der
    Faktor trotzdem an einer schmalen - derselbe Faktor wie mit schmaler Kachel
    vorn, und die breite spannt die ganze Breite."""
    vorn = _laufen({"cols": 2, "rows": 2, "split": False}, 480, 480, {"AZ": BREIT["AZ"], **_schalter(3)})
    hinten = _laufen({"cols": 2, "rows": 2, "split": False}, 480, 480, {**_schalter(3), "AZ": BREIT["AZ"]})
    assert abs(vorn["ks"] - hinten["ks"]) < 0.01, (vorn["ks"], hinten["ks"])
    az = next(t for t in vorn["tiles"] if t["id"] == "AZ")
    assert az["w2"] and az["breite"] >= 2 * next(t for t in vorn["tiles"] if not t["w2"])["breite"], vorn["tiles"]


@pytest.mark.parametrize("schalter, eine_seite", [(2, True), (30, False)], ids=["wenige", "viele"])
def test_automatik_rechnet_mit_der_breite(schalter, eine_seite):
    """Automatisches Raster: zwei breite und zwei schmale Kacheln passen auf eine
    Seite und wachsen (Punkt 2); mit dreissig schmalen dazu bleibt es bei der
    Zielkachel und dem Blaettern. Die Seitenzahl kommt aus rasterLage()."""
    m = _laufen({"grid": "auto"}, 1280, 800, {**BREIT, **_schalter(schalter)})
    cols, rows = m["raster"]
    erwartet, seiten = _lage([2 if t["w2"] else 1 for t in m["tiles"]], cols, rows)
    assert m["zeile"] == erwartet and _zeilen_gemessen(m) == erwartet, (m["zeile"], erwartet)
    schmal = next(t for t in m["tiles"] if not t["w2"])
    assert (seiten == 1) == eine_seite and m["blaettert"] == (seiten > 1), (seiten, m["blaettert"])
    if eine_seite:
        assert schmal["breite"] > 1.1 * W.KACHEL_ZIEL_STANDARD, schmal
    else:
        assert 0.8 * W.KACHEL_ZIEL_STANDARD <= schmal["breite"] <= 1.25 * W.KACHEL_ZIEL_STANDARD, schmal


def test_breite_im_kachel_editor():
    """Kachel-Editor: "Breite" zeigt den Standard des Typs, 1 und 2 landen als
    w in tiles[uuid], "Standard" nimmt das Feld wieder heraus."""
    from test_konfigurator_browser import _im_konfigurator
    res = _im_konfigurator("""async () => {
        cur = 'test'; PANELS[cur].tiles = PANELS[cur].tiles || {};
        if (!document.getElementById('tileEditor')) document.body.insertAdjacentHTML('beforeend', '<div id="tileEditor"></div>');
        const probe = (uuid) => { tileSel = uuid; renderTileEditor();
          const sel = document.getElementById('tWidth');
          return {standard: sel.options[0].textContent, wert: sel.value}; };
        const az = probe('AZ'), s0 = probe('S0');
        tileSel = 'AZ'; renderTileEditor();
        const sel = () => document.getElementById('tWidth');
        sel().value = '1'; sel().onchange();
        const eins = JSON.parse(JSON.stringify(PANELS[cur].tiles.AZ || null));
        sel().value = '2'; sel().onchange();
        const zwei = JSON.parse(JSON.stringify(PANELS[cur].tiles.AZ || null));
        sel().value = ''; sel().onchange();
        return {az, s0, eins, zwei, danach: PANELS[cur].tiles.AZ || null, breit: META.kachelBreit};
    }""", struktur=anlage({**BREIT, **_schalter(1)}),
        panels={"test": {"title": "Test", "tabs": ["favoriten"]}})
    assert res["az"]["standard"].endswith("(breit)") and res["s0"]["standard"].endswith("(schmal)"), res
    assert res["az"]["wert"] == "" and res["eins"] == {"w": 1} and res["zwei"] == {"w": 2} and res["danach"] is None, res
    assert "AudioZoneV2" in res["breit"] and "Switch" not in res["breit"], res["breit"]
