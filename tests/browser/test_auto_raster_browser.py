"""Automatisches Raster fuer Tablets (Kachel-Layout "Automatisch") in Chromium:
Die Visu rechnet Spalten und Zeilen aus der Bildschirmgroesse und der
Zielgroesse einer Kachel, ein groesserer Schirm zeigt mehr Kacheln statt
groesserer. Ein Widget belegt ganze Kachelspalten (quer) bzw. -zeilen
(hochkant), die Kacheln bleiben dabei gleich gross. Die Zielkachel ist eine
Zahl in px (die alten Stufen bleiben lesbar), beim Drehen rechnet die Visu neu,
geblaettert wird seitenweise wie bisher. Passen alle Kacheln einer Seite auf
den Schirm, wachsen sie bis zum KACHEL_WACHSEN-Fachen; ein Geraet kann unter
Displays eine eigene Zielkachel bekommen, die sofort wirkt. Das feste Raster
(4"-Panel) bleibt, wie es ist, Skalierung wirkt im automatischen Raster nicht.
Der Konfigurator stellt es ein, blendet die dann wirkungslosen Regler aus und
zeigt bei den Geraeten das Raster, das ein Tablet daraus macht; der Assistent
schlaegt es fuer Tablets vor."""
import asyncio
import inspect
import json
import shutil

import aiohttp
import pytest

from lox import KONFIGURATOR_GELADEN, ROOT, W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

ANZAHL = 40


def _anlage(n: int):
    """n Favoriten-Schalter als Struktur, dazu die Zustaende."""
    return (anlage({f"S{i}": {"name": f"Licht {i}", "type": "Switch", "uuidAction": f"S{i}", "room": "r1",
                              "cat": "c1", "isFavorite": True, "states": {"active": f"s{i}"}} for i in range(n)}),
            {f"s{i}": i % 3 == 0 for i in range(n)})


STRUKTUR, STATES = _anlage(ANZAHL)
# Sichtbare Flaeche im Browser (CSS-Pixel): Samsung Galaxy Tab A9, 10"-Tablet,
# iPad-Format und ein flacher Schirm (Tab A9 mit eingeblendeter Navigationsleiste),
# auf dem zwei Zeilen reichen - dort waere der Kasten ohne "fill" niedriger als
# der Schirm (hoechstens Zeilen x 240 px)
GERAETE = {"taba9-quer": (893, 533), "taba9-hoch": (533, 893), "zehn-quer": (1280, 800),
           "zehn-hoch": (800, 1280), "ipad-quer": (1024, 768), "flach": (893, 500)}

MESSEN = """() => { const g = document.getElementById('grid'), sc = document.querySelector('.screen');
  const r = e => e.getBoundingClientRect(), gr = r(g);
  const kacheln = [...g.querySelectorAll('.tile[data-id]')], t = kacheln[0];
  const fp = document.getElementById('frontpane'), punkt = document.getElementById('conn');
  // Punkt (Kreis) gegen Kachel (Rechteck mit abgerundeten Ecken): schneidet,
  // wenn sein Mittelpunkt dem um den Eckradius verkleinerten Rechteck naeher
  // kommt als Eckradius plus Punktradius
  const pr = r(punkt), ueber = (k, p) => { const b = r(k), rr = parseFloat(getComputedStyle(k).borderTopLeftRadius) || 0;
    const cx = p.left + p.width / 2, cy = p.top + p.height / 2;
    const qx = Math.max(b.left + rr, Math.min(cx, b.right - rr)), qy = Math.max(b.top + rr, Math.min(cy, b.bottom - rr));
    return Math.hypot(cx - qx, cy - qy) < rr + p.width / 2; };
  return {raster: [gridCols, gridRows], kachel: [Math.round(r(t).width), Math.round(r(t).height)],
    gap: parseFloat(getComputedStyle(g).getPropertyValue('--gap')),
    grid: [Math.round(gr.width), Math.round(gr.height)], screen: [Math.round(r(sc).width), Math.round(r(sc).height)],
    pane: getComputedStyle(fp).display !== 'none' ? [Math.round(r(fp).width), Math.round(r(fp).height)] : null,
    quer: document.documentElement.scrollWidth > innerWidth, klassen: [...sc.classList],
    skala: sc.style.getPropertyValue('--ui-scale'),
    sichtbar: kacheln.filter(x => { const b = r(x); return b.top >= gr.top - 1 && b.bottom <= gr.bottom + 1; }).length,
    punkt: getComputedStyle(punkt).display !== 'none' && pr.width > 0,
    punktAufKachel: kacheln.some(x => ueber(x, pr))};
}"""


@pytest.fixture(autouse=True)
def _frische_installation(cfg_ordner):
    """Wie eine frische Installation: nur die Vorlage, kein theme.json."""
    shutil.copy(ROOT / "config" / "theme.example.json", cfg_ordner / "theme.example.json")


def _laufen(ui, breite, hoehe, schritte=MESSEN, tmp_path=None, bild=None, anzahl=ANZAHL, routen=(), geraet=""):
    """Visu mit dem Profil ui oeffnen (anzahl Favoriten, nach Wahl mit
    Geraetekennung ?device=), schritte ausfuehren (JS-Text oder async
    Python-Funktion(app, pg, port)) -> Ergebnis."""
    async def lauf():
        app = W.App({"host": "", "port": 80})
        struktur, states = (STRUKTUR, STATES) if anzahl == ANZAHL else _anlage(anzahl)
        app._apply_structure(struktur)
        app.states = dict(states)
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"], "ui": ui}})
        runner, port, bc = await visu_starten(app, list(routen))
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": breite, "height": hoehe})
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test" + (f"&device={geraet}" if geraet else ""))
                await pg.wait_for_selector("#grid .tile[data-id]", state="attached")
                if await pg.locator("#saver:not(.hidden)").count():
                    await pg.click("#saver")
                    await pg.wait_for_selector("#saver.hidden", state="attached")
                await pg.wait_for_timeout(500)
                if isinstance(schritte, str):
                    ergebnis = await pg.evaluate(schritte)
                else:   # schritte(app, pg) oder, wer den Server selbst anspricht, schritte(app, pg, port)
                    ergebnis = await (schritte(app, pg, port) if len(inspect.signature(schritte).parameters) >= 3
                                      else schritte(app, pg))
                if tmp_path and bild:
                    await pg.screenshot(path=str(tmp_path / f"{bild}.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return ergebnis
    return asyncio.run(lauf())


@pytest.mark.parametrize("geraet", list(GERAETE))
def test_raster_aus_der_bildschirmgroesse(tmp_path, geraet):
    breite, hoehe = GERAETE[geraet]
    m = _laufen({"grid": "auto"}, breite, hoehe, tmp_path=tmp_path, bild=f"auto_{geraet}")
    cols, rows = m["raster"]
    ziel = W.KACHEL_ZIEL["medium"]
    # Der Kasten ist der ganze Schirm, nichts ragt seitlich heraus
    assert m["screen"] == [breite, hoehe] and not m["quer"] and "auto" in m["klassen"], m
    # Kacheln etwa in der Zielgroesse und etwa quadratisch: mehr Flaeche, mehr Kacheln
    w, h = m["kachel"]
    assert 0.8 * ziel <= w <= 1.25 * ziel and 0.75 <= h / w <= 1.33, m
    # Eine Seite zeigt genau cols x rows ganze Kacheln
    assert m["sichtbar"] == cols * rows, m
    if geraet == "taba9-quer":
        assert (cols, rows) == (5, 3), m
    if geraet == "taba9-hoch":
        assert (cols, rows) == (3, 5), m


@pytest.mark.parametrize("geraet", ["taba9-quer", "taba9-hoch", "zehn-quer"])
def test_widget_belegt_ganze_kachelspalten(tmp_path, geraet):
    breite, hoehe = GERAETE[geraet]
    ohne = _laufen({"grid": "auto"}, breite, hoehe)
    mit = _laufen({"grid": "auto", "panes": {"favoriten": "weather"}}, breite, hoehe,
                  tmp_path=tmp_path, bild=f"auto_widget_{geraet}")
    (c0, r0), (c1, r1) = ohne["raster"], mit["raster"]
    # Mit und ohne Widget gleich grosse Kacheln
    assert abs(mit["kachel"][0] - ohne["kachel"][0]) <= 3 and abs(mit["kachel"][1] - ohne["kachel"][1]) <= 3, \
        (ohne, mit)
    if breite > hoehe:
        # quer: das Widget steht rechts auf dem Platz ganzer Kachelspalten
        assert r1 == r0 and 1 <= c0 - c1 < c0, (ohne, mit)
        assert abs(mit["pane"][0] - (c0 - c1) * (ohne["kachel"][0] + ohne["gap"])) <= 12, (ohne, mit)
        anteil = mit["pane"][0] / breite
    else:
        # hochkant: darunter, auf dem Platz ganzer Kachelzeilen
        assert c1 == c0 and 1 <= r0 - r1 < r0, (ohne, mit)
        assert abs(mit["pane"][1] - (r0 - r1) * (ohne["kachel"][1] + ohne["gap"])) <= 12, (ohne, mit)
        anteil = mit["pane"][1] / (mit["pane"][1] + mit["grid"][1])
    assert 0.25 <= anteil <= 0.5, "etwa 40 %, nicht die halbe Flaeche wie im festen Raster"
    assert mit["sichtbar"] == c1 * r1, mit


def test_zielkachel_als_zahl_und_alte_stufe():
    ziele = (W.KACHEL_ZIEL["small"], W.KACHEL_ZIEL_STANDARD, W.KACHEL_ZIEL["large"])
    m = {z: _laufen({"grid": "auto", "tileSize": z}, 893, 533) for z in ziele}
    spalten = [m[z]["raster"][0] for z in ziele]
    breiten = [m[z]["kachel"][0] for z in ziele]
    assert spalten[0] > spalten[1] > spalten[2] and breiten[0] < breiten[1] < breiten[2], m
    # eine bestehende Datei nennt noch die Stufe: dieselbe Zahl, dasselbe Raster
    alt = _laufen({"grid": "auto", "tileSize": "large"}, 893, 533)
    assert alt["raster"] == m[W.KACHEL_ZIEL["large"]]["raster"] and alt["kachel"] == m[W.KACHEL_ZIEL["large"]]["kachel"]


@pytest.mark.parametrize("anzahl, widget", [(5, False), (5, True), (ANZAHL, False)], ids=["fuenf", "fuenf-widget", "vierzig"])
def test_wenige_kacheln_wachsen_bis_zur_grenze(tmp_path, anzahl, widget):
    """Punkt 2: die Automatik kennt die Kachelanzahl der Seite. Passen alle
    auf eine Seite, wachsen die Kacheln, bis die Seite voll ist, hoechstens
    auf KACHEL_WACHSEN x Zielkachel (vom Server, gridGrow); mit mehr Kacheln
    als Zellen bleibt es bei der Zielgroesse und dem Blaettern. Mit Widget
    daneben wachsen sie nicht: es belegt ganze Kachelspalten, und mit weniger
    Spalten liesse sich sein Anteil von rund 40 % nicht halten."""
    ui = {"grid": "auto", **({"panes": {"favoriten": "weather"}} if widget else {})}
    m = _laufen(ui, 1280, 800, anzahl=anzahl, tmp_path=tmp_path, bild=f"auto_wachsen_{anzahl}{'_widget' if widget else ''}")
    ziel, wachsen = W.KACHEL_ZIEL_STANDARD, W.KACHEL_WACHSEN
    cols, rows = m["raster"]
    assert m["sichtbar"] == min(anzahl, cols * rows) and "auto" in m["klassen"], m
    if anzahl < cols * rows and not widget:
        # gewachsen, aber nicht ueber die Grenze; alle auf einer Seite
        assert 1.1 * ziel < m["kachel"][0] <= wachsen * ziel + 1, m
        assert cols * rows >= anzahl, m
    else:
        assert 0.8 * ziel <= m["kachel"][0] <= 1.25 * ziel, m
    assert (m["pane"] is not None) == widget, m


def test_zielkachel_je_geraet_wirkt_sofort(cfg_ordner):
    """devices[name].tileTarget uebersteuert die Zielkachel des Profils (Geraet
    vor Profil). Beim Speichern unter Displays (POST /api/devices) baut die
    offene Visu ihr Raster ohne Neuladen neu ({t:"gridAuto"}); ohne Eintrag
    gilt wieder das Profil."""
    async def schritte(app, pg, port):
        stand = {"profil": await pg.evaluate(MESSEN)}

        async def speichern(devices):
            async with aiohttp.ClientSession() as s:
                async with s.post(f"http://127.0.0.1:{port}/api/devices", json={"devices": devices}) as r:
                    assert (await r.json())["ok"]

        async def bis(ziel):
            for _ in range(100):
                if await pg.evaluate("gridAuto") == ziel:
                    break
                await asyncio.sleep(0.05)
            await pg.wait_for_timeout(400)
            return await pg.evaluate(MESSEN)
        await speichern({"wand": {"tileTarget": 300}})
        stand["geraet"] = await bis(300)
        await speichern({"wand": {"scale": "off"}})   # Zielkachel wieder weg, Geraet bleibt
        stand["zurueck"] = await bis(W.KACHEL_ZIEL_STANDARD)
        return stand
    stand = _laufen({"grid": "auto"}, 1280, 800, schritte, routen=[("POST", "/api/devices", W.api_save_devices)],
                    geraet="wand")
    p, g, z = stand["profil"], stand["geraet"], stand["zurueck"]
    assert g["raster"][0] < p["raster"][0] and g["kachel"][0] > 1.5 * p["kachel"][0], stand
    assert 0.8 * 300 <= g["kachel"][0] <= 1.25 * 300 and g["sichtbar"] == g["raster"][0] * g["raster"][1], stand
    assert z["raster"] == p["raster"] and z["kachel"] == p["kachel"], stand


def test_drehen_rechnet_das_raster_neu():
    async def schritte(app, pg):
        quer = await pg.evaluate(MESSEN)
        await pg.evaluate("window.__ohneNeuladen = true")
        await pg.set_viewport_size({"width": 533, "height": 893})
        await pg.wait_for_function("gridRows > gridCols")
        await pg.wait_for_timeout(300)
        hoch = await pg.evaluate(MESSEN)
        await pg.set_viewport_size({"width": 893, "height": 533})
        await pg.wait_for_function("gridCols > gridRows")
        await pg.wait_for_timeout(300)
        return quer, hoch, await pg.evaluate(MESSEN), await pg.evaluate("window.__ohneNeuladen === true")
    quer, hoch, zurueck, ohne_neuladen = _laufen({"grid": "auto"}, 893, 533, schritte)
    assert ohne_neuladen
    assert quer["raster"] == zurueck["raster"] == [5, 3] and hoch["raster"] == [3, 5], (quer, hoch, zurueck)
    assert hoch["screen"] == [533, 893] and hoch["sichtbar"] == 15, hoch


def test_blaettern_seitenweise_wie_bisher():
    async def schritte(app, pg):
        seiten = await pg.evaluate("[...document.querySelectorAll('#grid .tile[data-id]')]"
                                   ".map((t, i) => t.classList.contains('snap') ? i : -1).filter(i => i >= 0)")
        await pg.evaluate("const g = document.getElementById('grid'); g.scrollBy(0, g.clientHeight)")
        await pg.wait_for_timeout(800)
        erste = await pg.evaluate("""() => { const g = document.getElementById('grid'), gr = g.getBoundingClientRect();
            return [...g.querySelectorAll('.tile[data-id]')].findIndex(t => t.getBoundingClientRect().top >= gr.top - 1); }""")
        return seiten, erste
    seiten, erste = _laufen({"grid": "auto"}, 893, 533, schritte)
    assert seiten == list(range(0, ANZAHL, 15)) and erste == 15, (seiten, erste)


@pytest.mark.parametrize("ui, raster", [({"split": False}, [2, 2]), ({"split": False, "cols": 3, "rows": 3}, [3, 3])],
                         ids=["2x2", "3x3"])
def test_festes_raster_am_4zoll_panel_bleibt(ui, raster):
    m = _laufen(ui, 480, 480)
    assert m["raster"] == raster and m["screen"] == [480, 480] and "auto" not in m["klassen"], m
    assert m["sichtbar"] == raster[0] * raster[1], m


@pytest.mark.parametrize("skalierung", [0.8, 1.5, "auto"])
def test_skalierung_wirkt_im_automatischen_raster_nicht(skalierung):
    """Auch ein fester Faktor unter 1 verkleinert die Visu nicht."""
    m = _laufen({"grid": "auto", "scale": skalierung}, 893, 533)
    assert m["skala"] == "1" and m["screen"] == [893, 533] and m["raster"] == [5, 3], m


def test_online_punkt_liegt_auf_keiner_kachel():
    """5 x 3 hat keine Fuge in der Mitte: der Punkt sitzt in der Ecke."""
    m = _laufen({"grid": "auto"}, 893, 533)
    assert m["punkt"] and not m["punktAufKachel"], m


def test_automatisch_im_konfigurator(cfg_ordner, tmp_path):
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"tablet": {
        "title": "Tablet", "tabs": ["favoriten"], "ui": {"cols": 3, "rows": 3}}}}), encoding="utf-8")
    routen = [("POST", "/api/panels", W.api_save_panels), ("GET", "/api/devices", W.api_devices_get)]

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(STRUKTUR)
        app.states = dict(STATES)
        app.panels = W.load_panels()
        runner, port, bc = await visu_starten(app, routen)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))

                async def oeffnen():
                    await pg.goto(f"http://127.0.0.1:{port}/config")
                    await pg.wait_for_function(KONFIGURATOR_GELADEN)
                    await pg.locator("#plist .pitem", has_text="Tablet").click()
                    await pg.locator('.stab[data-sub="appearance"]').click()

                async def felder():
                    return {f: await pg.locator(f"#{f}").is_visible()
                            for f in ("fTileSizeField", "fFillField", "fScaleField", "fScaleHint")}

                async def speichern():
                    async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
                        await pg.locator("#saveBtn").click()
                    j = await (await antwort.value).json()
                    assert j["ok"] and j["verworfen"] == [], j
                    return json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]["tablet"]

                await oeffnen()
                stand = {"anfang": (await pg.locator("#fLayout").input_value(), await felder())}
                await pg.locator("#fLayout").select_option("auto")
                stand["auto"] = await felder()
                await pg.locator("#fTileSize").fill(str(W.KACHEL_ZIEL["large"]))   # Zielkachel als Zahl
                stand["gespeichert"] = (await speichern())["ui"]
                await pg.screenshot(path=str(tmp_path / "konfigurator_automatisch.png"))

                # Das Tablet meldet, was es daraus macht; die Geraeteliste zeigt es
                tablet = await b.new_page(viewport={"width": 893, "height": 533})
                tablet.on("pageerror", lambda e: fehler.append(str(e)))
                await tablet.goto(f"http://127.0.0.1:{port}/?panel=tablet&device=tab")
                await tablet.wait_for_selector("#grid .tile[data-id]", state="attached")
                stand["tablet"] = await tablet.evaluate("[gridAuto, gridCols, gridRows]")
                for _ in range(100):
                    scr = next((i.get("screen") for i in app.conn_info.values() if i.get("dev") == "tab"), None)
                    if scr and scr.get("rc"):
                        break
                    await asyncio.sleep(0.05)
                await oeffnen()
                stand["nach_neuladen"] = (await pg.locator("#fLayout").input_value(),
                                          await pg.locator("#fTileSize").input_value(), await felder())
                await pg.locator(".rub", has_text="Displays").click()
                stand["geraet"] = await pg.locator('#ag_list .ag[data-name="tab"] .agscr').text_content()
                await pg.locator(".rub", has_text="Panel Configuration").click()
                await pg.locator("#plist .pitem", has_text="Tablet").click()
                await pg.locator('.stab[data-sub="appearance"]').click()
                await pg.locator("#fLayout").select_option("3x3")
                stand["fest"] = await felder()
                stand["zurueck"] = (await speichern())["ui"]

                # Assistent "Neues Panel": fuer ein Tablet (2 Panes) schlaegt er
                # "Automatisch" vor, fuer das 4"-Panel 2 x 2; selbst Gewaehltes bleibt
                stand["assistent"] = await pg.evaluate("""() => {
                    const wahl = (k, v) => document.querySelector('#wzBody [data-wk="' + k + '"][data-wo="' + v + '"]').click();
                    const raster = g => document.querySelector('#wzBody [data-wg="' + g + '"]').click();
                    wzOpen(); WZ.step = wzFlow().indexOf('anzeige'); wzRender();
                    wahl('panes', '2'); const tablet = WZ.grid;
                    const knopf = document.querySelector('#wzBody [data-wg="auto"]');
                    const angezeigt = [knopf.classList.contains('on'), knopf.innerText];
                    wahl('panes', '1'); const panel4 = WZ.grid;
                    wahl('panes', '2'); raster('3x3'); wahl('panes', '1'); const bleibt = WZ.grid;
                    wahl('panes', '2'); raster('auto');
                    WZ.content = 'classic'; WZ.title = 'Flur'; WZ.id = 'flur'; wzInitSetup();
                    WZ.step = wzFlow().indexOf('review'); wzRender();
                    const zusammenfassung = document.getElementById('wzBody').innerText.includes('Automatisch');
                    wzBuild();
                    return {tablet, angezeigt, panel4, bleibt, zusammenfassung,
                            ui: JSON.parse(JSON.stringify(PANELS['flur'].ui))}; }""")
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return stand
    stand = asyncio.run(lauf())

    aus = {"fTileSizeField": False, "fFillField": True, "fScaleField": True, "fScaleHint": True}
    an = {"fTileSizeField": True, "fFillField": False, "fScaleField": False, "fScaleHint": False}
    assert stand["anfang"] == ("3x3", aus), stand
    assert stand["auto"] == an, "Kachelgroesse statt Bildschirm fuellen und Skalierung"
    assert stand["gespeichert"] == {"grid": "auto", "tileSize": W.KACHEL_ZIEL["large"]}, "cols/rows gelten nicht mehr"
    assert stand["tablet"] == [W.KACHEL_ZIEL["large"], 4, 2], stand
    assert stand["nach_neuladen"] == ("auto", str(W.KACHEL_ZIEL["large"]), an), stand
    assert stand["geraet"].startswith("893×533 quer") and "Raster 4 × 2" in stand["geraet"], stand
    assert stand["fest"] == aus and stand["zurueck"] == {"cols": 3, "rows": 3}, stand
    assistent = stand["assistent"]
    assert assistent.pop("ui") == {"grid": "auto"}, stand
    assert assistent == {"tablet": "auto", "angezeigt": [True, "Automatisch"], "panel4": "2x2",
                         "bleibt": "3x3", "zusammenfassung": True}, assistent
