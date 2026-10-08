"""Seiten waagerecht wischen (Punkt 8) in Chromium: Auf einem Tablet (Split an,
kein quadratischer Schirm) stehen die Kachelseiten nebeneinander, jede Seite
ein Raster aus cols x rows, eingerastet je Seite, mit Punkten darunter, die
dem Scrollen folgen und auf Tipp zur Seite fuehren; das Mausrad blaettert.
Ein Wisch nach rechts blaettert ab Seite 2 zurueck und heisst nur auf der
ersten Seite "zurueck". Das quadratische 4"-Panel und ein Profil mit Split
"aus" blaettern weiter senkrecht. Live-Werte patchen die Kacheln in den
Seiten, die Seite bleibt stehen; Sprungmarken springen zur Seite."""
import asyncio

import pytest

from lox import RAUM_KATS, W, anlage, raum_anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

ANZAHL = 40


def _anlage(n: int):
    return (anlage({f"S{i}": {"name": f"Licht {i}", "type": "Switch", "uuidAction": f"S{i}", "room": "r1",
                              "cat": "c1", "isFavorite": True, "states": {"active": f"s{i}"}} for i in range(n)}),
            {f"s{i}": i % 3 == 0 for i in range(n)})


MESSEN = """() => { const g = document.getElementById('grid'), r = e => e.getBoundingClientRect(), gr = r(g);
  const innen = b => b.top >= gr.top - 1 && b.bottom <= gr.bottom + 1 && b.left >= gr.left - 1 && b.right <= gr.right + 1;
  const kacheln = [...g.querySelectorAll('.tile[data-id]')];
  const pk = g.querySelector('.punkte'), dots = [...g.querySelectorAll('.punkte i')];
  const pr = pk && getComputedStyle(pk).display !== 'none' ? r(pk) : null;
  return {hpages: g.classList.contains('hpages'), punkte: g.classList.contains('punkte'), snapy: g.classList.contains('snapy'),
    raster: [gridCols, gridRows], seiten: [...g.querySelectorAll('.page')].map(p => p.querySelectorAll('.tile[data-id]').length),
    breite: g.clientWidth, scrollW: g.scrollWidth, scrollH: g.scrollHeight, hoehe: g.clientHeight,
    scrollLeft: Math.round(g.scrollLeft), scrollTop: Math.round(g.scrollTop),
    sichtbar: kacheln.map((t, i) => innen(r(t)) ? i : -1).filter(i => i >= 0),
    dots: dots.length, an: dots.findIndex(d => d.classList.contains('on')),
    dotsLage: pr ? [Math.round(pr.left), Math.round(pr.top), Math.round(pr.width)] : null,
    dotsOben: dots.length ? Math.round(r(dots[0]).top) : null,
    kachelUnten: Math.max(...kacheln.filter(t => innen(r(t))).map(t => r(t).bottom)),
    stack: stack.length}; }"""


def _laufen(ui, breite, hoehe, schritte=MESSEN, anzahl=ANZAHL, touch=False, struktur=None, tabs=("favoriten",)):
    async def lauf():
        app = W.App({"host": "", "port": 80})
        if struktur is None:
            s, states = _anlage(anzahl)
        else:
            s, states = struktur
        app._apply_structure(s)
        app.states = dict(states)
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": list(tabs), "ui": ui}})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": breite, "height": hoehe}, has_touch=touch)
                pg = await ctx.new_page()
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector("#grid .tile[data-id]", state="attached")
                if await pg.locator("#saver:not(.hidden)").count():
                    await pg.evaluate("hideSaver()")
                    await pg.wait_for_selector("#saver.hidden", state="attached")
                await pg.wait_for_timeout(500)
                ergebnis = await pg.evaluate(schritte) if isinstance(schritte, str) else await schritte(app, pg, ctx)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return ergebnis
    return asyncio.run(lauf())


@pytest.mark.parametrize("ui, breite, hoehe", [({"grid": "auto"}, 893, 533), ({"grid": "auto"}, 533, 893),
                                               ({"cols": 3, "rows": 2}, 893, 533)],
                         ids=["tablet-quer", "tablet-hoch", "festes-raster-quer"])
def test_tablet_blaettert_waagerecht(ui, breite, hoehe):
    """Seiten nebeneinander in Schirmbreite, jede mit cols x rows Kacheln;
    Punkte darunter, der erste an; ein Scroll um eine Seitenbreite zeigt die
    naechste Seite, die Punkte bleiben an derselben Stelle (sticky) und
    rutschen nie unter die Kacheln; ein Tipp auf den letzten Punkt fuehrt zur
    letzten Seite, das Mausrad eine Seite zurueck."""
    async def schritte(app, pg, ctx):
        m0 = await pg.evaluate(MESSEN)
        await pg.evaluate("const g = document.getElementById('grid'); g.scrollBy(g.clientWidth, 0)")
        await pg.wait_for_timeout(800)
        m1 = await pg.evaluate(MESSEN)
        await pg.locator("#grid .punkte i").last.click()
        await pg.wait_for_timeout(800)
        m2 = await pg.evaluate(MESSEN)
        await pg.mouse.move(breite // 4, hoehe // 3)
        await pg.mouse.wheel(0, 120)       # Rad nach unten am Ende: bleibt
        await pg.wait_for_timeout(700)
        m3 = await pg.evaluate(MESSEN)
        await pg.mouse.wheel(0, -120)      # Rad nach oben: eine Seite zurueck
        await pg.wait_for_timeout(800)
        m4 = await pg.evaluate(MESSEN)
        return m0, m1, m2, m3, m4
    m0, m1, m2, m3, m4 = _laufen(ui, breite, hoehe, schritte)
    cols, rows = m0["raster"]
    je = cols * rows
    seiten = -(-ANZAHL // je)
    assert m0["hpages"] and m0["punkte"] and not m0["snapy"], m0
    assert m0["seiten"] == [je] * (seiten - 1) + [ANZAHL - je * (seiten - 1)], m0
    assert m0["scrollW"] == seiten * m0["breite"] and m0["scrollH"] <= m0["hoehe"] + 1, m0
    assert m0["dots"] == seiten and m0["an"] == 0 and m0["sichtbar"] == list(range(je)), m0
    assert m0["kachelUnten"] <= m0["dotsOben"] + 1, "Punkte liegen unter den Kacheln, nicht darauf"
    assert m1["an"] == 1 and m1["scrollLeft"] == m1["breite"] and m1["sichtbar"] == list(range(je, 2 * je)), m1
    assert m1["dotsLage"] == m0["dotsLage"], "Punkte kleben am Sichtfenster"
    assert m2["an"] == seiten - 1 and m2["sichtbar"] == list(range(je * (seiten - 1), ANZAHL)), m2
    assert m3["an"] == seiten - 1, m3
    assert m4["an"] == seiten - 2 and m4["scrollLeft"] == (seiten - 2) * m4["breite"], m4


@pytest.mark.parametrize("ui, breite, hoehe", [({}, 480, 480), ({"split": False}, 480, 480), ({"split": False}, 893, 533)],
                         ids=["4zoll", "4zoll-split-aus", "split-aus-quer"])
def test_4zoll_panel_blaettert_senkrecht(ui, breite, hoehe):
    m = _laufen(ui, breite, hoehe)
    assert not m["hpages"] and not m["punkte"] and m["snapy"] and m["dots"] == 0, m
    assert m["scrollH"] > m["hoehe"] and m["scrollW"] == m["breite"], m
    assert len(m["sichtbar"]) == m["raster"][0] * m["raster"][1], m


def test_drehen_wechselt_zwischen_quer_und_senkrecht():
    """Ein 4"-Panel-Profil (2 x 2, Split an) auf einem quadratischen Schirm
    blaettert senkrecht; wird das Fenster rechteckig (Tablet), stehen die
    Seiten nebeneinander - und zurueck."""
    async def schritte(app, pg, ctx):
        quadrat = await pg.evaluate(MESSEN)
        await pg.set_viewport_size({"width": 893, "height": 533})
        await pg.wait_for_function("document.getElementById('grid').classList.contains('hpages')")
        await pg.wait_for_timeout(300)
        quer = await pg.evaluate(MESSEN)
        await pg.set_viewport_size({"width": 480, "height": 480})
        await pg.wait_for_function("!document.getElementById('grid').classList.contains('hpages')")
        await pg.wait_for_timeout(300)
        return quadrat, quer, await pg.evaluate(MESSEN)
    quadrat, quer, zurueck = _laufen({}, 480, 480, schritte)
    assert quadrat["snapy"] and not quadrat["hpages"] and zurueck["snapy"] and not zurueck["hpages"], (quadrat, zurueck)
    assert quer["hpages"] and quer["punkte"] and quer["raster"] == [4, 2], quer


def test_quadrat_schwelle_ohne_drehen():
    """Codex an #130: Waechst ein Fenster quer ueber die Quadrat-Schwelle
    (520 x 480 -> 560 x 480, festes 2 x 2 mit Split: beide Male 4 x 2 quer),
    aendern sich weder Lage noch Raster; die Blaetterrichtung muss trotzdem
    sofort umschalten, ohne auf eine andere Aktualisierung zu warten."""
    async def schritte(app, pg, ctx):
        fast_quadrat = await pg.evaluate(MESSEN)
        await pg.set_viewport_size({"width": 560, "height": 480})
        await pg.wait_for_timeout(500)
        breiter = await pg.evaluate(MESSEN)
        await pg.set_viewport_size({"width": 520, "height": 480})
        await pg.wait_for_timeout(500)
        return fast_quadrat, breiter, await pg.evaluate(MESSEN)
    fast_quadrat, breiter, zurueck = _laufen({"cols": 2, "rows": 2}, 520, 480, schritte)
    assert fast_quadrat["raster"] == breiter["raster"] == zurueck["raster"] == [4, 2], (fast_quadrat, breiter, zurueck)
    assert fast_quadrat["snapy"] and not fast_quadrat["hpages"], fast_quadrat
    assert breiter["hpages"] and breiter["punkte"] and not breiter["snapy"], breiter
    assert zurueck["snapy"] and not zurueck["hpages"], zurueck


def test_live_wert_haelt_die_seite():
    """Ein Zustandswechsel patcht die Kachel in ihrer Seite (dieselben Knoten),
    die aufgeblaetterte Seite bleibt stehen."""
    async def schritte(app, pg, ctx):
        await pg.evaluate("const g = document.getElementById('grid'); g.scrollBy(g.clientWidth, 0)")
        await pg.wait_for_timeout(800)
        vorher = await pg.evaluate(MESSEN)
        await pg.evaluate("window.__knoten = document.querySelector('#grid .tile[data-id=\"S16\"]')")
        app.states["s16"] = not app.states["s16"]
        app._dirty = True
        await pg.wait_for_timeout(900)
        nachher = await pg.evaluate(MESSEN)
        gleich = await pg.evaluate("window.__knoten === document.querySelector('#grid .tile[data-id=\"S16\"]')")
        an = await pg.evaluate("document.querySelector('#grid .tile[data-id=\"S16\"]').classList.contains('on')")
        return vorher, nachher, gleich, an
    vorher, nachher, gleich, an = _laufen({"grid": "auto"}, 893, 533, schritte)
    assert vorher["an"] == 1 and nachher["an"] == 1 and nachher["scrollLeft"] == vorher["scrollLeft"], (vorher, nachher)
    assert gleich and an, "in der Seite gepatcht, nicht neu gebaut"


async def _wischen(cdp, x, y, dx, schritte=20):
    await cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
    for i in range(1, schritte + 1):
        await cdp.send("Input.dispatchTouchEvent",
                       {"type": "touchMove", "touchPoints": [{"x": x + dx * i / schritte, "y": y}]})
        await asyncio.sleep(0.016)
    await cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})


def test_wisch_nach_rechts_blaettert_erst_dann_zurueck():
    """Auf einer Detailseite ist der Wisch nach rechts "zurueck" (wie am
    4"-Panel). Auf der Kachelseite blaettert er ab Seite 2 zur vorigen Seite,
    ohne die Ansicht zu verlassen; erst auf Seite 1 verlaesst er sie."""
    async def schritte(app, pg, ctx):
        cdp = await ctx.new_cdp_session(pg)
        x, y = 200, 250
        await pg.evaluate("nav({view:'control', id:'S1'})")
        await pg.wait_for_timeout(600)
        tiefe = await pg.evaluate("stack.length")
        await _wischen(cdp, x, y, 200)
        await pg.wait_for_timeout(700)
        zurueck = await pg.evaluate("stack.length")
        await pg.wait_for_selector("#grid .tile[data-id]", state="attached")
        await pg.evaluate("nav({view:'control', id:'S1'}); back();")   # Verlauf mit einer Seite davor
        await pg.wait_for_timeout(700)
        await pg.evaluate("const g = document.getElementById('grid'); g.scrollBy(g.clientWidth, 0)")
        await pg.wait_for_timeout(800)
        s1 = await pg.evaluate(MESSEN)
        await _wischen(cdp, x, y, 300)
        await pg.wait_for_timeout(900)
        s2 = await pg.evaluate(MESSEN)
        await _wischen(cdp, x, y, 300)
        await pg.wait_for_timeout(900)
        s3 = await pg.evaluate("stack.length")
        return tiefe, zurueck, s1, s2, s3
    tiefe, zurueck, s1, s2, s3 = _laufen({"grid": "auto"}, 893, 533, schritte, touch=True)
    assert (tiefe, zurueck) == (2, 1), "Detailseite: Wisch nach rechts ist zurueck"
    assert s1["an"] == 1 and s1["hpages"], s1
    assert s2["an"] == 0 and s2["stack"] == s1["stack"], "ab Seite 2 blaettert der Wisch"
    assert s3 == s1["stack"] - 1 or s3 == s1["stack"], "Seite 1: zurueck, sofern es eine Ansicht davor gibt"


def test_sprungmarke_springt_zur_seite():
    """Raum-Panel auf dem Tablet: ein Tipp auf eine Marke zeigt die Seite mit
    der ersten Kachel der Gruppe (links wie rechts im Bild), die Punkte folgen."""
    async def schritte(app, pg, ctx):
        stand = {}
        for cat in RAUM_KATS:
            await pg.locator(f'#tabs .tab[data-cat="{cat}"]').click()
            await pg.wait_for_timeout(900)
            m = await pg.evaluate(MESSEN)
            idx = await pg.evaluate("""k => [...document.querySelectorAll('#grid .tile[data-id]')]
                .findIndex(t => t.dataset.cat === k)""", cat)
            stand[cat] = (idx in m["sichtbar"], m["an"], m["seiten"])
        return stand
    stand = _laufen({"cols": 2, "rows": 2}, 893, 533, schritte, struktur=raum_anlage(), tabs=("room:r1",))
    assert all(v[0] for v in stand.values()), stand
    assert len(stand["c1"][2]) > 1 and {v[1] for v in stand.values()} == set(range(len(stand["c1"][2]))), stand
