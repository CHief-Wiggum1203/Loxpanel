"""Werteleiste (ui.valueBar) in Chromium: die Anzeige-Bausteine einer Seite
stehen als Kette von Werten in EINER Zeile ueber dem Kachelraster statt als
Kacheln, das Raster bleibt dem Bedienbaren. Das automatische Raster rechnet
die Zeile ab, das feste teilt sich die Hoehe. Was nicht in die Zeile passt,
scrollt waagerecht. Ein Tipp oeffnet die Wertseite, neue Werte ziehen die
Chips nach, ohne die Zeile neu zu bauen. Dazu Kopfzeile und Widget daneben
und der Konfigurator (Kaestchen je Tab)."""
import asyncio

import pytest

from lox import W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

QUER, HOCH, VIERZOLL = (893, 533), (533, 893), (480, 480)
SCHALTER, WERTE = 10, 5
BAUSTEINE = {**{f"S{i}": {"name": f"Licht {i}", "type": "Switch", "uuidAction": f"S{i}", "room": "r1", "cat": "c1",
                          "isFavorite": True, "states": {"active": f"s{i}"}} for i in range(SCHALTER)},
             **{f"T{i}": {"name": f"Temperatur {i}", "type": "InfoOnlyAnalog", "uuidAction": f"TA{i}", "room": "r1",
                          "cat": "c1", "isFavorite": True, "details": {"format": "%.1f°"}, "states": {"value": f"t{i}"}}
                for i in range(WERTE)},
             "R": {"name": "Regen", "type": "InfoOnlyDigital", "uuidAction": "RA", "room": "r2", "cat": "c1",
                   "isFavorite": True, "states": {"active": "r"}},
             "Z": {"name": "Stromzähler", "type": "Meter", "uuidAction": "ZA", "room": "r2", "cat": "c1",
                   "isFavorite": True, "details": {"actualFormat": "%.1f kW", "totalFormat": "%.0f kWh"},
                   "states": {"actual": "za", "total": "zt"}}}
ZUSTAND = {**{f"s{i}": i % 2 for i in range(SCHALTER)}, **{f"t{i}": 20 + i for i in range(WERTE)},
           "r": 0, "za": 0.4, "zt": 512}
LEISTE_IDS = [f"T{i}" for i in range(WERTE)] + ["R", "Z"]
KACHEL_IDS = [f"S{i}" for i in range(SCHALTER)]

MESSEN = """() => {
  const sc = document.querySelector('.screen'), lz = document.getElementById('werteleiste');
  const kz = document.getElementById('kopfzeile'), g = document.getElementById('grid');
  const tabs = document.getElementById('tabs'), fp = document.getElementById('frontpane');
  const r = e => { const b = e.getBoundingClientRect(); return {l: b.left, r: b.right, t: b.top, b: b.bottom, w: b.width, h: b.height}; };
  const da = e => !e.hidden && getComputedStyle(e).display !== 'none';
  const kacheln = [...g.querySelectorAll('.tile[data-id]')], gr = r(g), t = kacheln[0];
  return {
    klassen: [...sc.classList], sichtbarLeiste: da(lz), leiste: r(lz), grid: gr, tabs: r(tabs), screen: r(sc),
    kopf: da(kz) ? r(kz) : null, pane: da(fp) ? r(fp) : null,
    chips: [...lz.querySelectorAll('.kz-w')].map(w => ({id: w.dataset.id, wert: w.querySelector('.vl').textContent,
      name: w.querySelector('.nm').textContent, an: w.classList.contains('on'), box: r(w), weg: w.hidden})),
    kacheln: kacheln.map(x => x.dataset.id),
    raster: [gridCols, gridRows], kachel: t ? [Math.round(r(t).w), Math.round(r(t).h)] : null,
    ks: parseFloat(getComputedStyle(sc).getPropertyValue('--ks')) || 1,
    leisteH: parseFloat(getComputedStyle(sc).getPropertyValue('--leiste-h')) || 0,
    scrollBreite: lz.scrollWidth, innenBreite: lz.clientWidth, scrollLinks: lz.scrollLeft,
    sichtbar: kacheln.filter(x => { const b = r(x); return b.t >= gr.t - 1 && b.b <= gr.b + 1; }).length,
    route: view && view.route, stapel: stack.length,
  };
}"""


def _app(ui: dict, bausteine: dict | None = None, zustand: dict | None = None):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(bausteine or BAUSTEINE))
    app.states = dict(zustand or ZUSTAND)
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"], "ui": ui}})
    return app


def _ansehen(groesse, ui, schritt=None, **app_kw):
    """Visu in der Groesse laden, Uhr-Seite weg, dann messen (oder schritt(app, pg))."""
    async def lauf():
        app = _app(ui, **app_kw)
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": groesse[0], "height": groesse[1]}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector("#grid .tile[data-id]", state="attached")
                await pg.wait_for_timeout(600)
                await pg.evaluate("wake()")
                await pg.wait_for_timeout(700)
                ergebnis = await (schritt(app, pg) if schritt else pg.evaluate(MESSEN))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return ergebnis
    return asyncio.run(lauf())


def _leiste_steht(m, breite_wie_kasten=True):
    """Die Leiste liegt ueber dem Raster, das Raster ueber den Tabs, nichts
    ueberlappt; die Werte sind Chips, die Kacheln nur noch die Schalter."""
    assert "leiste" in m["klassen"] and m["sichtbarLeiste"], m["klassen"]
    assert abs(m["leiste"]["h"] - round(48 * m["ks"])) <= 1 and m["leisteH"] == round(48 * m["ks"]), (m["leiste"], m["ks"])
    if breite_wie_kasten:
        assert abs(m["leiste"]["w"] - m["screen"]["w"]) <= 2, "volle Breite"
    assert m["grid"]["t"] >= m["leiste"]["b"] - 1 and m["grid"]["b"] <= m["tabs"]["t"] + 1, (m["leiste"], m["grid"], m["tabs"])
    assert [c["id"] for c in m["chips"]] == LEISTE_IDS and not any(c["weg"] for c in m["chips"]), m["chips"]
    assert m["kacheln"] == KACHEL_IDS, m["kacheln"]


def _startwerte(m):
    """Die Chips zeigen Wert und Name wie die Kachel: Messwert, Ein/Aus, Zaehler."""
    assert m["chips"][0]["wert"] == "20,0 °" and m["chips"][0]["name"] == "Temperatur 0", m["chips"][0]
    assert m["chips"][5]["wert"] == "Aus" and not m["chips"][5]["an"] and m["chips"][6]["wert"].startswith("0,4 kW"), m["chips"]


@pytest.mark.parametrize("groesse", [QUER, HOCH], ids=["quer", "hoch"])
def test_leiste_ueber_dem_automatischen_raster(groesse):
    m = _ansehen(groesse, {"grid": "auto", "valueBar": ["favoriten"]})
    _leiste_steht(m)
    _startwerte(m)
    # Das Raster rechnet die Zeile ab: eine Seite zeigt genau cols x rows ganze
    # Kacheln (oder alle Schalter), die Kacheln bleiben etwa quadratisch
    cols, rows = m["raster"]
    assert m["sichtbar"] == min(cols * rows, SCHALTER), m
    w, h = m["kachel"]
    assert 0.75 <= h / w <= 1.33, m["kachel"]


def test_festes_raster_am_4zoll_panel():
    m = _ansehen(VIERZOLL, {"cols": 2, "rows": 2, "split": False, "valueBar": ["favoriten"]})
    _leiste_steht(m)
    _startwerte(m)
    assert m["raster"] == [2, 2] and m["sichtbar"] == 4, m
    # Die Zeile geht vom festen Kasten ab: Kacheln niedriger, aber ganz zu sehen
    assert 140 <= m["kachel"][1] < 225, m["kachel"]


def test_ohne_option_bleiben_die_kacheln():
    m = _ansehen(QUER, {"grid": "auto"})
    assert "leiste" not in m["klassen"] and not m["sichtbarLeiste"] and m["chips"] == []
    assert m["kacheln"] == KACHEL_IDS + LEISTE_IDS


def test_viele_werte_scrollen_waagerecht():
    """Was nicht in die Zeile passt, bleibt nicht weg (die Werte haben keine
    Kachel mehr), sondern scrollt: am Ende der Zeile steht der letzte Chip."""
    viele = {**{k: v for k, v in BAUSTEINE.items() if k.startswith("S")},
             **{f"T{i}": {"name": f"Vorlauftemperatur Heizkreis {i}", "type": "InfoOnlyAnalog", "uuidAction": f"TA{i}",
                          "room": "r1", "cat": "c1", "isFavorite": True, "details": {"format": "%.1f°"},
                          "states": {"value": f"t{i}"}} for i in range(12)}}
    zustand = {**{f"s{i}": 0 for i in range(SCHALTER)}, **{f"t{i}": 30 + i for i in range(12)}}

    async def scrollen(app, pg):
        vorher = await pg.evaluate(MESSEN)
        await pg.evaluate("(() => { const lz = document.getElementById('werteleiste'); lz.scrollLeft = lz.scrollWidth; })()")
        await pg.wait_for_timeout(200)
        return vorher, await pg.evaluate(MESSEN)
    vorher, nachher = _ansehen(QUER, {"grid": "auto", "valueBar": ["favoriten"]}, scrollen, bausteine=viele, zustand=zustand)
    assert len(vorher["chips"]) == 12 and not any(c["weg"] for c in vorher["chips"])
    assert vorher["scrollBreite"] > vorher["innenBreite"] + 40, (vorher["scrollBreite"], vorher["innenBreite"])
    assert vorher["chips"][-1]["box"]["r"] > vorher["leiste"]["r"], "zu Beginn ragt der letzte Chip hinaus"
    assert nachher["scrollLinks"] > 0 and nachher["chips"][-1]["box"]["r"] <= nachher["leiste"]["r"] + 1, nachher["chips"][-1]
    assert nachher["kacheln"] == KACHEL_IDS, "die Kacheln bleiben, wie sie sind"


def test_tipp_oeffnet_die_wertseite():
    async def tippen(app, pg):
        await pg.locator('#werteleiste .kz-w[data-id="T2"]').click()
        await pg.wait_for_timeout(600)
        detail = await pg.evaluate(MESSEN)
        await pg.evaluate("back()")
        await pg.wait_for_timeout(600)
        return detail, await pg.evaluate(MESSEN)
    detail, zurueck = _ansehen(QUER, {"grid": "auto", "valueBar": ["favoriten"]}, tippen)
    assert detail["route"] == {"view": "control", "id": "T2"} and detail["stapel"] == 2, detail["route"]
    assert "leiste" not in detail["klassen"] and not detail["sichtbarLeiste"], "die Wertseite hat keine Leiste"
    _leiste_steht(zurueck)


def test_neue_werte_ziehen_die_chips_nach():
    """Zustandswechsel auf derselben Seite: Text und Zustand der Chips aendern
    sich, die Elemente bleiben dieselben (kein Neuaufbau, Scroll-Lage bleibt)."""
    async def aendern(app, pg):
        await pg.evaluate("document.querySelectorAll('#werteleiste .kz-w').forEach((n, i) => { n._marke = i + 1; })")
        app.states["t0"] = 23.5
        app.states["r"] = 1
        app._dirty = True
        await pg.wait_for_timeout(900)
        m = await pg.evaluate(MESSEN)
        m["marken"] = await pg.evaluate("[...document.querySelectorAll('#werteleiste .kz-w')].map(n => n._marke || 0)")
        return m
    m = _ansehen(QUER, {"grid": "auto", "valueBar": ["favoriten"]}, aendern)
    assert m["chips"][0]["wert"] == "23,5 °" and m["chips"][5]["wert"] == "Ein" and m["chips"][5]["an"], m["chips"]
    assert m["marken"] == list(range(1, len(LEISTE_IDS) + 1)), "dieselben Elemente wie vor dem Wechsel"
    _leiste_steht(m)


def test_unter_der_kopfzeile():
    m = _ansehen(QUER, {"grid": "auto", "panes": {"favoriten": "header"}, "valueBar": ["favoriten"]})
    _leiste_steht(m)
    assert "kopf" in m["klassen"] and m["kopf"], m["klassen"]
    assert m["leiste"]["t"] >= m["kopf"]["b"] - 1, "Kopfzeile oben, Leiste darunter"
    cols, rows = m["raster"]
    assert m["sichtbar"] == min(cols * rows, SCHALTER), m


@pytest.mark.parametrize("groesse", [QUER, HOCH], ids=["quer", "hoch"])
def test_neben_dem_widget(groesse):
    """Split quer: die Leiste liegt nur ueber dem Raster, das Widget daneben
    reicht ueber beide Zeilen. Hochkant: Leiste, Raster, Widget, Tabs."""
    m = _ansehen(groesse, {"grid": "auto", "panes": {"favoriten": "weather"}, "valueBar": ["favoriten"]})
    _leiste_steht(m, breite_wie_kasten=(groesse == HOCH))
    assert "split" in m["klassen"] and m["pane"], m["klassen"]
    if groesse == QUER:
        assert m["leiste"]["r"] <= m["pane"]["l"] + 1 and abs(m["leiste"]["l"] - m["grid"]["l"]) <= 1, (m["leiste"], m["pane"])
        assert m["pane"]["t"] <= m["leiste"]["t"] + 1 and m["pane"]["b"] >= m["grid"]["b"] - 1, "Widget ueber beide Zeilen"
    else:
        assert m["pane"]["t"] >= m["grid"]["b"] - 1 and m["pane"]["b"] <= m["tabs"]["t"] + 1, (m["pane"], m["grid"], m["tabs"])
    cols, rows = m["raster"]
    assert m["sichtbar"] == min(cols * rows, SCHALTER), m


def test_konfigurator_schaltet_die_leiste_je_seite():
    from test_konfigurator_browser import _im_konfigurator
    res = _im_konfigurator("""async () => {
        cur = 'test'; const p = PANELS[cur]; p.ui = p.ui || {};
        document.body.insertAdjacentHTML('beforeend', '<div id="paneField"><div id="panePerTab"></div></div>');
        renderPanes(p);
        const k = tk => document.querySelector('input[data-leiste="' + tk + '"]');
        const felder = [...document.querySelectorAll('input[data-leiste]')].map(c => c.dataset.leiste);
        const vorher = p.ui.valueBar;
        k('favoriten').click();
        const eine = (p.ui.valueBar || []).slice();
        k('raeume').click();
        const zwei = (p.ui.valueBar || []).slice();
        renderPanes(p);
        const gemerkt = [k('favoriten').checked, k('raeume').checked];
        k('favoriten').click(); k('raeume').click();
        return {felder, vorher, eine, zwei, gemerkt, danach: p.ui.valueBar};
    }""")
    assert res["felder"] == ["favoriten", "raeume"] and res["vorher"] is None
    assert res["eine"] == ["favoriten"] and res["zwei"] == ["favoriten", "raeume"] and res["gemerkt"] == [True, True]
    assert res["danach"] is None, "ohne Seite faellt der Schluessel weg"
    assert W._clean_werteleiste(res["zwei"]) == res["zwei"], "was der Konfigurator schreibt, nimmt der Server unveraendert"
