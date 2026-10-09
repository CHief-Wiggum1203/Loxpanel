"""Seiten-Editor (Punkt 10, Teil 2) in Chromium: der Reiter „Seiten-Editor"
im Panel-Editor und Schritt 5 des Assistenten.

- Die Arbeitsflaeche zeigt, was die Visu am Geraet baut: dasselbe Raster
  (Spalten x Zeilen), dieselbe Folge und dieselben Groessen wie die echte
  Visu in derselben Fenstergroesse - automatisch mit Widget, Kopfzeile und
  Werteleiste, fest mit Verdopplung durch den Split, mit und ohne
  Raumgruppierung.
- Ziehen aus der Palette, auf der Flaeche und zurueck in die Palette (Maus
  und Finger am Griff), Pfeiltasten und Entf, Groesse 2 x 2, Widget aus der
  Palette; gespeichert stehen picks, layout und byRoom so in panels.json,
  ohne dass der Server etwas verwirft, und die Visu zeigt genau diese Folge.
- Der Assistent uebernimmt Folge, Groessen und Raumgruppierung ins Profil.
- Unter Tabs abgewaehlt oder beim Duplizieren getauscht bleibt das Layout
  stimmig."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser


def _schalter(u, name, raum):
    return {"name": name, "type": "Switch", "uuidAction": u, "room": raum, "cat": "c1", "states": {"active": "s" + u}}


STRUKTUR = {
    "rooms": {"r1": {"name": "Wohnzimmer", "image": "IconsFilled/sofa.svg"},
              "r2": {"name": "Küche", "image": "IconsFilled/kueche.svg"},
              "r3": {"name": "Außen", "image": "IconsFilled/licht.svg"}},
    "cats": {"c1": {"name": "Beleuchtung", "image": "IconsFilled/licht.svg"}},
    "controls": {**{u: _schalter(u, n, r) for u, n, r in (
        ("A", "Deckenlicht", "r1"), ("B", "Stehlampe", "r1"), ("C", "Dimmer Küche", "r2"),
        ("D", "Garagentor", "r3"), ("E", "Außenlicht", "r3"), ("F", "Leselampe", "r1"),
        ("G", "Licht Küche", "r2"), ("H", "Licht Flur", "r1"), ("K", "Licht Bad", "r2"))},
        "Z": {"name": "Audio Wohnzimmer", "type": "AudioZoneV2", "uuidAction": "Z", "room": "r1", "cat": "c1",
              "states": {"playState": "z"}},
        "T": {"name": "Außentemperatur", "type": "InfoOnlyAnalog", "uuidAction": "T", "room": "r3", "cat": "c1",
              "states": {"value": "t"}}},
}
STATES = {"s" + u: 0 for u in "ABCDEFGHK"} | {"z": 0, "t": 21.5}
ROUTEN = [("POST", "/api/panels", W.api_save_panels)]

# Was der Editor zeigt (aus seiner Rechnung) und was die Visu baut
EDITOR = """() => { const h = document.querySelector('#seHost'), L = h._seLage;
  return {raster: [L.r.cols, L.r.rows], ids: L.a.raster.map(e => e.id),
          groessen: L.a.raster.map(e => { const g = LoxRaster.groesse(e, L.r.cols, L.r.rows); return [g.w, g.h]; }),
          info: h.querySelector('[data-se-info]').textContent,
          kacheln: [...h.querySelectorAll('.se-t')].map(n => n.dataset.seT)}; }"""
VISU = """() => { const ks = [...document.querySelectorAll('#grid .tile[data-id]')];
  return {raster: [gridCols, gridRows], ids: ks.map(n => n.dataset.id),
          groessen: ks.map(n => [n.classList.contains('w2') ? 2 : 1, n.classList.contains('h2') ? 2 : 1])}; }"""
SEITE = "() => JSON.parse(JSON.stringify(PANELS[cur].pickTabs[curPickIdx]))"


def _app(panels):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    app.states = dict(STATES)
    app.panels = W.App._sanitize_panels(panels)
    return app


async def _konfigurator(b, port, panel, breite=1400):
    pg = await b.new_page(viewport={"width": breite, "height": 1000}, locale="de-DE")
    pg._fehler = []
    pg.on("pageerror", lambda e: pg._fehler.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{port}/config")
    await pg.wait_for_function(KONFIGURATOR_GELADEN)
    await _panel(pg, panel)
    return pg


async def _panel(pg, panel):
    await pg.locator("#plist .pitem", has_text=f"?panel={panel}").click()
    await pg.locator(".stab[data-sub='seiten']").click()
    await pg.wait_for_selector("#seHost [data-se-flaeche]")


async def _geraet(pg, name):
    """Vorschaugeraet aus der Liste waehlen (Katalog oder dieser Browser)."""
    opts = await pg.eval_on_selector_all("#seHost [data-se-geraet] option", "l => l.map(o => o.textContent)")
    i = next(k for k, o in enumerate(opts) if o.startswith(name + " ·"))
    await pg.select_option("#seHost [data-se-geraet]", str(i))


async def _visu(b, port, panel, breite, hoehe):
    pg = await b.new_page(viewport={"width": breite, "height": hoehe})
    fehler = []
    pg.on("pageerror", lambda e: fehler.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{port}/?panel={panel}")
    await pg.wait_for_selector("#grid .tile[data-id]", state="attached")
    if await pg.locator("#saver:not(.hidden)").count():
        await pg.click("#saver")
    await pg.wait_for_timeout(400)
    m = await pg.evaluate(VISU)
    await pg.close()
    assert not fehler, fehler
    return m


async def _ziehen(pg, von, nach, dx=0.25, dy=0.5):
    """Maus: von der Mitte von `von` zu einem Punkt in `nach` (Anteil der Breite/Hoehe)."""
    a, z = await von.bounding_box(), await nach.bounding_box()
    await pg.mouse.move(a["x"] + a["width"] / 2, a["y"] + a["height"] / 2)
    await pg.mouse.down()
    await pg.mouse.move(a["x"] + a["width"] / 2 + 12, a["y"] + a["height"] / 2 + 12, steps=3)
    await pg.mouse.move(z["x"] + z["width"] * dx, z["y"] + z["height"] * dy, steps=8)
    await pg.mouse.up()


def _lauf(panels, schritte):
    async def lauf():
        app = _app(panels)
        runner, port, bc = await visu_starten(app, ROUTEN)
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                ergebnis = await schritte(b, port)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        return ergebnis
    return asyncio.run(lauf())


# Profile fuer den Vergleich mit der Visu. Zwei Tabs, damit die Leiste die
# gewohnten Symbole traegt (Sprungmarken waeren eine andere Hoehe).
PICKS = ["A", "Z", "C", "D", "B", "E", "T", "F", "G", "H", "K"]
PROFILE = {
    # automatisch, Widget daneben: Wachsen und Schrumpfen gibt es nur ohne
    "widget": {"tabs": ["auswahl", "favoriten"], "ui": {"grid": "auto", "panes": {"auswahl": "weather"}},
               "pickTabs": [{"name": "Wohnen", "picks": PICKS}]},
    # automatisch, Kopfzeile und Werteleiste (T wandert in die Leiste)
    "kopf": {"tabs": ["auswahl", "favoriten"], "ui": {"grid": "auto", "panes": {"auswahl": "header"},
                                                      "valueBar": ["auswahl"]},
             "pickTabs": [{"name": "Wohnen", "picks": PICKS[:7]}]},
    # fest 3 x 3, der Split verdoppelt quer die Spalten
    "fest": {"tabs": ["auswahl", "favoriten"], "ui": {"cols": 3, "rows": 3},
             "pickTabs": [{"name": "Wohnen", "picks": PICKS}]},
    # 4"-Panel: fest 2 x 2 ohne Split, eigene Folge mit 2 x 2, ohne Raumgruppierung
    "klein": {"tabs": ["auswahl", "favoriten"], "ui": {"split": False},
              "pickTabs": [{"name": "Wohnen", "picks": PICKS[:6], "byRoom": False,
                            "layout": [{"id": "C", "w": 2, "h": 2}, {"id": "A"}, {"id": "Z", "w": 1},
                                       {"id": "D"}, {"id": "B"}, {"id": "E"}]}]},
    # automatisch ohne Widget, ohne Gruppierung, mit 2 x 2 mitten auf der Seite
    "auto": {"tabs": ["auswahl", "favoriten"], "ui": {"grid": "auto", "split": False},
             "pickTabs": [{"name": "Wohnen", "picks": PICKS, "byRoom": False,
                           "layout": [{"id": u, **({"w": 2, "h": 2} if u == "B" else {})} for u in PICKS]}]},
}
FAELLE = [("widget", "Galaxy Tab A9 quer", 893, 533), ("widget", "Galaxy Tab A9 hochkant", 533, 893),
          ("widget", "10″-Tablet quer", 1280, 800), ("kopf", "iPad quer", 1024, 768),
          ("fest", "10″-Tablet quer", 1280, 800), ("fest", "iPad hochkant", 768, 1024),
          ("klein", "4″-Wandpanel", 480, 480), ("auto", "Galaxy Tab A9 quer", 893, 533),
          ("auto", "iPad hochkant", 768, 1024)]


def test_flaeche_wie_die_visu():
    panels = {k: {"title": k, **v} for k, v in PROFILE.items()}

    async def schritte(b, port):
        pg = await _konfigurator(b, port, "widget")
        aktuell, out = "widget", []
        for panel, geraet, breite, hoehe in FAELLE:
            if panel != aktuell:
                await _panel(pg, panel)
                aktuell = panel
            await _geraet(pg, geraet)
            editor = await pg.evaluate(EDITOR)
            visu = await _visu(b, port, panel, breite, hoehe)
            out.append((panel, geraet, editor, visu))
        assert not pg._fehler, pg._fehler
        return out
    ergebnis = _lauf(panels, schritte)
    for panel, geraet, editor, visu in ergebnis:
        fall = f"{panel} auf {geraet}"
        assert editor["raster"] == visu["raster"], (fall, editor, visu)
        assert editor["ids"] == visu["ids"], (fall, editor["ids"], visu["ids"])
        assert editor["groessen"] == visu["groessen"], (fall, editor["groessen"], visu["groessen"])
        assert editor["info"].startswith(("Raster am " if PROFILE[panel]["ui"].get("grid") else "Festes Raster am ")
                                         + geraet), (fall, editor["info"])
    # Stichproben, dass die Faelle tragen: mit Widget neben den Kacheln, die
    # Werteleiste nimmt T, die 2 x 2 auf dem 4"-Panel steht vorn
    erg = {(p, g): e for p, g, e, v in ergebnis}
    assert "neben dem Widget" in erg[("widget", "Galaxy Tab A9 quer")]["info"]
    assert "über dem Widget" in erg[("widget", "Galaxy Tab A9 hochkant")]["info"]
    assert "T" not in erg[("kopf", "iPad quer")]["ids"]
    assert erg[("fest", "10″-Tablet quer")]["raster"] == [6, 3]
    assert erg[("klein", "4″-Wandpanel")]["ids"][:2] == ["C", "A"] and erg[("klein", "4″-Wandpanel")]["groessen"][0] == [2, 2]


def test_ziehen_tasten_groesse_und_speichern(cfg_ordner):
    """Maus: Leselampe aus der Palette vor das Dimmer Küche, Garagentor zurueck
    in die Palette; Deckenlicht 2 x 2; Pfeiltaste nach links, Entf; ohne
    Raumgruppierung. Gespeichert ohne Verworfenes, die Visu zeigt die Folge."""
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {}}), encoding="utf-8")
    panels = {"flur": {"title": "Flur", "tabs": ["auswahl"], "ui": {"grid": "auto"},
                       "pickTabs": [{"name": "Wohnen", "picks": ["A", "Z", "C", "D"]}]}}

    async def schritte(b, port):
        pg = await _konfigurator(b, port, "flur")
        await _geraet(pg, "Galaxy Tab A9 quer")
        await pg.locator("#seHost [data-se-raum]").uncheck()
        assert (await pg.evaluate(SEITE))["byRoom"] is False
        # Palette -> vor C (linke Haelfte der Kachel); die Marke zeigt die Stelle
        await _ziehen(pg, pg.locator("#seHost .se-p", has_text="Leselampe"), pg.locator("#seHost .se-t[data-se-t='C']"),
                      dx=0.2)
        assert (await pg.evaluate(EDITOR))["ids"] == ["A", "Z", "F", "C", "D"]
        # Flaeche -> Palette: von der Seite
        await _ziehen(pg, pg.locator("#seHost .se-t[data-se-t='D']"), pg.locator("#seHost .se-liste"))
        assert (await pg.evaluate(EDITOR))["ids"] == ["A", "Z", "F", "C"]
        # Antippen waehlt, 2 x 2 im Feld Ausgewaehlt
        await pg.locator("#seHost .se-t[data-se-t='A']").click()
        await pg.locator("#seHost [data-se-gr='2,2']").click()
        # Pfeiltaste: C eine Stelle nach vorn, dann F mit Entf von der Seite
        await pg.locator("#seHost .se-t[data-se-t='C']").click()
        await pg.keyboard.press("ArrowLeft")
        assert await pg.evaluate("document.activeElement.dataset.seT") == "C", "der Fokus bleibt auf der Kachel"
        assert (await pg.evaluate(EDITOR))["ids"] == ["A", "Z", "C", "F"]
        await pg.locator("#seHost .se-t[data-se-t='F']").focus()
        await pg.keyboard.press("Delete")
        editor = await pg.evaluate(EDITOR)
        assert editor["ids"] == ["A", "Z", "C"] and editor["groessen"][0] == [2, 2], editor
        seite = await pg.evaluate(SEITE)
        assert seite["picks"] == ["A", "Z", "C"], seite
        assert seite["layout"] == [{"id": "A", "w": 2, "h": 2}, {"id": "Z", "w": 2, "h": 1},
                                   {"id": "C", "w": 1, "h": 1}], seite
        async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
            await pg.locator("#saveBtn").click()
        j = await (await antwort.value).json()
        assert j["ok"] and j["verworfen"] == [], j
        gespeichert = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]["flur"]
        visu = await _visu(b, port, "flur", 893, 533)
        assert not pg._fehler, pg._fehler
        return editor, gespeichert, visu
    editor, gespeichert, visu = _lauf(panels, schritte)
    assert gespeichert["pickTabs"][0] == {"name": "Wohnen", "picks": ["A", "Z", "C"], "byRoom": False,
                                          "layout": [{"id": "A", "w": 2, "h": 2}, {"id": "Z", "w": 2, "h": 1},
                                                     {"id": "C", "w": 1, "h": 1}]}, gespeichert
    assert (visu["raster"], visu["ids"], visu["groessen"]) == (editor["raster"], editor["ids"], editor["groessen"])


# Finger: synthetische Pointer-Events (pointerType touch), Ziel in der Mitte
FINGER = """async ({von, nach}) => {
  const q = document.querySelector(von), z = document.querySelector(nach).getBoundingClientRect();
  const r = q.getBoundingClientRect(), x0 = r.left + r.width / 2, y0 = r.top + r.height / 2;
  const x1 = z.left + z.width * 0.2, y1 = z.top + z.height / 2;
  const ev = (t, x, y) => new PointerEvent(t, {pointerType: 'touch', pointerId: 7, isPrimary: true, button: 0,
                                              clientX: x, clientY: y, bubbles: true, cancelable: true});
  q.dispatchEvent(ev('pointerdown', x0, y0));
  for (let i = 1; i <= 8; i++) document.dispatchEvent(ev('pointermove', x0 + (x1 - x0) * i / 8, y0 + (y1 - y0) * i / 8));
  const geist = !!document.querySelector('.se-geist');
  document.dispatchEvent(ev('pointerup', x1, y1));
  return geist; }"""


def test_finger_zieht_in_der_liste_nur_am_griff():
    """Auf dem Tablet scrollt der Finger die Palette - gezogen wird dort nur am
    Griff; Kacheln der Flaeche zieht er direkt."""
    panels = {"flur": {"title": "Flur", "tabs": ["auswahl"], "ui": {"grid": "auto"},
                       "pickTabs": [{"name": "Wohnen", "picks": ["A", "C"], "byRoom": False}]}}

    async def schritte(b, port):
        pg = await _konfigurator(b, port, "flur")
        await _geraet(pg, "Galaxy Tab A9 quer")
        zeile = "#seHost .se-p[data-se-p='B']"
        ohne = await pg.evaluate(FINGER, {"von": zeile + " .se-pn", "nach": "#seHost .se-t[data-se-t='C']"})
        nach_zeile = (await pg.evaluate(EDITOR))["ids"]
        mit = await pg.evaluate(FINGER, {"von": zeile + " .se-grip", "nach": "#seHost .se-t[data-se-t='C']"})
        nach_griff = (await pg.evaluate(EDITOR))["ids"]
        kachel = await pg.evaluate(FINGER, {"von": "#seHost .se-t[data-se-t='C']", "nach": "#seHost .se-t[data-se-t='A']"})
        nach_kachel = (await pg.evaluate(EDITOR))["ids"]
        assert not pg._fehler, pg._fehler
        return ohne, nach_zeile, mit, nach_griff, kachel, nach_kachel
    ohne, nach_zeile, mit, nach_griff, kachel, nach_kachel = _lauf(panels, schritte)
    assert (ohne, nach_zeile) == (False, ["A", "C"]), "Finger auf der Zeile scrollt, zieht nicht"
    assert (mit, nach_griff) == (True, ["A", "B", "C"])
    assert (kachel, nach_kachel) == (True, ["C", "A", "B"])


def test_widget_aus_der_palette():
    """Wetter antippen setzt das Widget neben die Kacheln (ui.panes), das
    Raster rechnet mit; Entfernen nimmt es weg; Kalender auf die Flaeche
    gezogen setzt ihn. Ohne Split nur die Kopfzeile."""
    panels = {"flur": {"title": "Flur", "tabs": ["auswahl"], "ui": {"grid": "auto"},
                       "pickTabs": [{"name": "Wohnen", "picks": ["A", "B", "C"]}]},
              "aus": {"title": "Aus", "tabs": ["auswahl"], "ui": {"split": False},
                      "pickTabs": [{"name": "Wohnen", "picks": ["A"]}]}}

    async def schritte(b, port):
        pg = await _konfigurator(b, port, "flur")
        await _geraet(pg, "Galaxy Tab A9 quer")
        vorher = await pg.evaluate(EDITOR)
        await pg.locator("#seHost .se-w[data-se-w='weather']").click()
        mit = await pg.evaluate(EDITOR)
        pane = await pg.evaluate("(PANELS.flur.ui.panes || {}).auswahl || ''")
        zone = await pg.locator("#seHost .se-pane").text_content()
        await pg.locator("#seHost [data-se-pane-weg]").click()
        weg = await pg.evaluate("(PANELS.flur.ui.panes || {}).auswahl || ''")
        await _ziehen(pg, pg.locator("#seHost .se-w[data-se-w='calendar']"), pg.locator("#seHost [data-se-flaeche]"), dx=0.5)
        kalender = await pg.evaluate("(PANELS.flur.ui.panes || {}).auswahl || ''")
        await _panel(pg, "aus")
        gesperrt = await pg.eval_on_selector_all("#seHost .se-w", "l => l.map(b => [b.dataset.seW, b.disabled])")
        assert not pg._fehler, pg._fehler
        return vorher, mit, pane, zone, weg, kalender, gesperrt
    vorher, mit, pane, zone, weg, kalender, gesperrt = _lauf(panels, schritte)
    assert pane == "weather" and "Wetter" in zone, (pane, zone)
    assert "neben dem Widget" in mit["info"] and "neben dem Widget" not in vorher["info"], (vorher, mit)
    assert mit["raster"][0] < vorher["raster"][0], "das Widget nimmt Spalten"
    assert weg == "" and kalender == "calendar", (weg, kalender)
    # Audio gibt es (Audiozone in der Anlage), Energiefluss, Kamera und Verlauf nicht
    assert dict(gesperrt) == {"weather": True, "calendar": True, "audio": True, "header": False}, gesperrt


def test_assistent_schritt5_mit_dem_editor():
    """Freie Auswahl im Assistenten: Schritt 5 zeigt fuer die Seite den Editor
    (Dialog breit), gerechnet mit dem Geraet aus Schritt 1; Folge, Groesse und
    Raumgruppierung landen im neuen Profil."""
    panels = {"flur": {"title": "Flur", "tabs": ["favoriten"]}}

    async def schritte(b, port):
        pg = await _konfigurator(b, port, "flur")
        await pg.evaluate("""() => { wzOpen(); wzGroesseSetzen(wzKatalog().find(k => k.name === 'Galaxy Tab A9 quer'));
            WZ.content = 'pick'; WZ.title = 'Sauna'; WZ.id = 'sauna'; wzInitSetup();
            WZ.step = wzFlow().indexOf('setup'); wzRender(); }""")
        await pg.locator("#wzBody [data-pgtiles='0']").click()
        breit = await pg.evaluate("document.querySelector('#wzOv .wzbox').classList.contains('breit')")
        info = await pg.text_content("#wzSeHost [data-se-info]")
        for name in ("Deckenlicht", "Dimmer Küche", "Audio Wohnzimmer"):
            await pg.locator("#wzSeHost .se-p", has_text=name).click()
        await _ziehen(pg, pg.locator("#wzSeHost .se-t[data-se-t='C']"), pg.locator("#wzSeHost .se-t[data-se-t='A']"), dx=0.2)
        await pg.locator("#wzSeHost .se-t[data-se-t='Z']").click()
        await pg.locator("#wzSeHost [data-se-gr='1,1']").click()
        await pg.locator("#wzSeHost [data-se-raum]").uncheck()
        await pg.locator("#wzTileBack").click()
        schmal = await pg.evaluate("document.querySelector('#wzOv .wzbox').classList.contains('breit')")
        await pg.evaluate("wzBuild()")
        neu = await pg.evaluate("JSON.parse(JSON.stringify(PANELS.sauna.pickTabs))")
        vorgerechnet = await pg.evaluate("wzVorrechnung(WZ.panes, WZ.grid)")
        assert not pg._fehler, pg._fehler
        return breit, info, schmal, neu, vorgerechnet
    breit, info, schmal, neu, vorgerechnet = _lauf(panels, schritte)
    assert breit and not schmal
    assert info.startswith("Raster am Galaxy Tab A9 quer"), info
    assert neu[0]["picks"] == ["C", "A", "Z"] and neu[0]["byRoom"] is False, neu
    assert neu[0]["layout"] == [{"id": "C", "w": 1, "h": 1}, {"id": "A", "w": 1, "h": 1},
                                {"id": "Z", "w": 1, "h": 1}], neu
    assert vorgerechnet["auto"], vorgerechnet


def test_tabs_und_duplizieren_halten_das_layout_stimmig(cfg_ordner):
    """Unter Tabs abgewaehlt geht der Layout-Eintrag mit (sonst meldete das
    Speichern ihn als verworfen); ohne Raumgruppierung zeigen die Nummern die
    Folge der Seite und es gibt keine Sprungmarken. Der Raumtausch beim
    Duplizieren tauscht die Layout-Eintraege wie picks."""
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {}}), encoding="utf-8")
    panels = {"flur": {"title": "Flur", "tabs": ["auswahl"], "ui": {"grid": "auto"},
                       "pickTabs": [{"name": "Wohnen", "picks": ["A", "C", "B"], "byRoom": False,
                                     "layout": [{"id": "C", "w": 2, "h": 2}, {"id": "A"}, {"id": "B"}]}]}}

    async def schritte(b, port):
        pg = await _konfigurator(b, port, "flur")
        await pg.locator(".stab[data-sub='tabs']").click()
        nummern = await pg.eval_on_selector_all("#picked .chip[data-pu]", "l => l.map(c => c.dataset.pu)")
        marken = await pg.text_content("#pickAnchors")
        await pg.locator("#picked .chip[data-pu='A']").click()      # abwaehlen
        seite = await pg.evaluate(SEITE)
        async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
            await pg.locator("#saveBtn").click()
        j = await (await antwort.value).json()
        tausch = await pg.evaluate("""() => { const p = {tabs: ['auswahl'], pickTabs: [{name: 'W', picks: ['A', 'C'],
              layout: [{id: 'C', w: 2, h: 2}, {id: 'A', w: 1, h: 1}]}]};
            return profilMitRaumtausch(p, 'r2', 'r1', [{uuid: 'C', name: 'Licht', type: 'Switch', room: 'r2'},
              {uuid: 'A', name: 'Licht', type: 'Switch', room: 'r1'}]).profil.pickTabs[0]; }""")
        assert not pg._fehler, pg._fehler
        return nummern, marken, seite, j, tausch
    nummern, marken, seite, j, tausch = _lauf(panels, schritte)
    assert nummern == ["C", "A", "B"], "ohne Gruppierung die Folge des Layouts"
    assert "ohne Sprungmarken" in marken, marken
    assert seite["picks"] == ["C", "B"] and [e["id"] for e in seite["layout"]] == ["C", "B"], seite
    assert j["ok"] and j["verworfen"] == [], j
    # C (Kueche) wird zum gleichnamigen A im Wohnzimmer, das schon auf der Seite steht: die erste zaehlt
    assert tausch["picks"] == ["A"] and tausch["layout"] == [{"id": "A", "w": 2, "h": 2}], tausch
