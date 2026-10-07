"""Kopfzeile (Widget "header") in Chromium: Uhr, Wetter in Kurzform und nach
Wahl Werte stehen in EINER Zeile ueber dem Kachelraster, statt einer Pane
daneben. Der Kasten bleibt ungeteilt, das automatische Raster rechnet die
Zeile von der freien Hoehe ab, das feste Raster teilt sich die Hoehe. Was
rechts nicht mehr in die Zeile passt, bleibt weg. Dazu der Konfigurator: die
Kopfzeile steht im Auswahlfeld je Tab, Werte kommen wie bei "Werte" dazu."""
import asyncio

import pytest

from lox import W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

QUER, HOCH, GROSS, VIERZOLL = (893, 533), (533, 893), (1280, 800), (480, 480)
ANZAHL = 14
WERTE = {f"V{i}": {"name": f"Vorlauftemperatur Kreis {i}", "type": "InfoOnlyAnalog", "uuidAction": f"VA{i}",
                   "room": "r1", "cat": "c1", "details": {"format": "%.1f°"}, "states": {"value": f"v{i}"}}
         for i in range(W.SV_STATUS_MAX)}
BAUSTEINE = {**{f"S{i}": {"name": f"Licht {i}", "type": "Switch", "uuidAction": f"S{i}", "room": "r1", "cat": "c1",
                          "isFavorite": True, "states": {"active": f"s{i}"}} for i in range(ANZAHL)},
             "T": {"name": "Außentemperatur", "type": "InfoOnlyAnalog", "uuidAction": "TA", "room": "r1",
                   "cat": "c1", "details": {"format": "%.1f°"}, "states": {"value": "tv"}}, **WERTE}
ZUSTAND = {**{f"s{i}": i % 2 for i in range(ANZAHL)}, "tv": 17.3,
           **{f"v{i}": 30 + i for i in range(W.SV_STATUS_MAX)}}

MESSEN = """() => {
  const sc = document.querySelector('.screen'), kz = document.getElementById('kopfzeile');
  const g = document.getElementById('grid'), tabs = document.getElementById('tabs');
  const r = e => { const b = e.getBoundingClientRect(); return {l: b.left, r: b.right, t: b.top, b: b.bottom, w: b.width, h: b.height}; };
  const kacheln = [...g.querySelectorAll('.tile[data-id]')], gr = r(g), t = kacheln[0];
  const txt = q => { const e = kz.querySelector(q); return e ? e.textContent : null; };
  const box = kz.querySelector('.kz-werte');
  return {
    klassen: [...sc.classList], sichtbarKopf: !kz.hidden && getComputedStyle(kz).display !== 'none',
    kopf: r(kz), grid: gr, tabs: r(tabs), screen: r(sc),
    uhr: txt('#kzTime'), datum: txt('#kzDate'), wetter: txt('.kz-wx .t'), lage: txt('.kz-wx .c'),
    werte: [...kz.querySelectorAll('.kz-w')].map(w => ({wert: w.querySelector('.vl').textContent,
      name: w.querySelector('.nm').textContent, weg: w.hidden || getComputedStyle(w).display === 'none', rechts: r(w).r})),
    werteBox: box ? r(box) : null,
    raster: [gridCols, gridRows], kachel: t ? [Math.round(r(t).w), Math.round(r(t).h)] : null,
    ks: parseFloat(getComputedStyle(sc).getPropertyValue('--ks')) || 1,
    kopfH: parseFloat(getComputedStyle(sc).getPropertyValue('--kopf-h')) || 0,
    sichtbar: kacheln.filter(x => { const b = r(x); return b.t >= gr.t - 1 && b.b <= gr.b + 1; }).length,
    angemeldet: typeof curSvStatus === 'string' ? curSvStatus : null,
  };
}"""


def _app(ui: dict):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = dict(ZUSTAND)
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"], "ui": ui}})
    return app


def _ansehen(monkeypatch, groesse, ui, schritt=None):
    """Visu mit Wetter aus dem Nachbau (wie test_front_tabs_browser) in der
    Groesse `groesse` laden, Uhr-Seite weg, dann messen (oder schritt(app, pg))."""
    from test_front_tabs_browser import _front

    async def lauf():
        daten = await _front(monkeypatch)
        app = _app(ui)
        app._front = app._front_payload(daten)
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


def _zeile_steht(m):
    """Die Kopfzeile liegt ueber dem Raster, das Raster ueber der Leiste,
    nichts ueberlappt, kein Split."""
    assert "kopf" in m["klassen"] and "split" not in m["klassen"], m["klassen"]
    # Die Zeile ist KOPF_H (64 px) mal Kachelfaktor hoch: 0,85 bis 1,4 (Kacheln,
    # die im automatischen Raster wachsen, weil alle auf eine Seite passen)
    assert m["sichtbarKopf"] and 54 <= m["kopf"]["h"] <= 90 and abs(m["kopf"]["h"] - round(64 * m["ks"])) <= 1, (m["kopf"], m["ks"])
    assert abs(m["kopf"]["w"] - m["screen"]["w"]) <= 2, "volle Breite"
    assert m["grid"]["t"] >= m["kopf"]["b"] - 1 and m["grid"]["b"] <= m["tabs"]["t"] + 1, (m["kopf"], m["grid"], m["tabs"])
    assert m["uhr"] and len(m["uhr"]) == 5 and m["uhr"][2] == ":", m["uhr"]
    assert m["datum"], "Datum in Kurzform"
    assert m["wetter"] and m["wetter"].endswith("°") and m["lage"], (m["wetter"], m["lage"])


@pytest.mark.parametrize("groesse", [QUER, HOCH, GROSS], ids=["quer", "hoch", "gross"])
def test_kopfzeile_ueber_dem_automatischen_raster(monkeypatch, groesse):
    m = _ansehen(monkeypatch, groesse, {"grid": "auto", "panes": {"favoriten": "header:T"}})
    _zeile_steht(m)
    # Der Wert kommt per svstatus wie bei "Werte": Zahl und Name
    assert [(w["wert"], w["name"], w["weg"]) for w in m["werte"]] == [("17,3 °", "Außentemperatur", False)], m["werte"]
    assert m["angemeldet"] == "T"
    # Das Raster rechnet die Zeile ab: eine Seite zeigt genau cols x rows ganze
    # Kacheln (oder alle, wenn weniger da sind), die Kacheln bleiben etwa
    # quadratisch statt gestaucht
    cols, rows = m["raster"]
    assert m["sichtbar"] == min(cols * rows, ANZAHL), m
    w, h = m["kachel"]
    assert 0.75 <= h / w <= 1.33, m["kachel"]


def test_kopfzeile_mit_festem_raster_am_4zoll_panel(monkeypatch):
    """Split "Aus" ist die Einstellung des 4"-Panels: keine Pane daneben - die
    Kopfzeile ist keine Pane und gilt trotzdem (Codex-Befund: sie haengt
    nicht an themeSplit)."""
    m = _ansehen(monkeypatch, VIERZOLL, {"cols": 2, "rows": 2, "split": False, "panes": {"favoriten": "header"}})
    _zeile_steht(m)
    assert m["raster"] == [2, 2] and m["sichtbar"] == 4, m
    # Ohne Werte nur Uhr und Wetter, und der Server bekommt keine Anmeldung
    assert m["werte"] == [] and m["werteBox"] is None and m["angemeldet"] == ""
    # Die Zeile geht vom festen Kasten ab: Kacheln niedriger, aber ganz zu sehen
    assert 120 <= m["kachel"][1] < 198, m["kachel"]


def test_zu_viele_werte_bleiben_weg(monkeypatch):
    werte = "header:" + ",".join(f"V{i}" for i in range(W.SV_STATUS_MAX))
    m = _ansehen(monkeypatch, QUER, {"grid": "auto", "panes": {"favoriten": werte}})
    _zeile_steht(m)
    gezeigt = [w for w in m["werte"] if not w["weg"]]
    assert 1 <= len(gezeigt) < W.SV_STATUS_MAX, "auf 893 px passen nicht alle acht, aber mindestens einer"
    assert all(w["rechts"] <= m["werteBox"]["r"] + 1 for w in gezeigt), "kein gezeigter Wert ragt heraus"
    assert all(w["rechts"] <= m["kopf"]["r"] for w in gezeigt)


def test_faktor_haengt_nicht_an_der_seite_davor(monkeypatch):
    """Codex-Befund an #122: Im festen Raster haengt die Kachelhoehe an --kopf-h
    und die am Faktor. Einmal gemessen nahm der Faktor die Kopfzeile mit dem
    Faktor der Seite davor, und kopfEinpassen() lief mit deren Schrift. Jetzt
    misst render() nach, bis der Faktor steht, und setzeFaktor() passt die
    Kopfzeile neu ein: ob die Seite frisch kommt oder nach einer Seite mit
    kleinstem oder groesstem Faktor, Faktor, Kopfhoehe, Kachelhoehe und die
    gezeigten Werte sind dieselben, und kein gezeigter Wert ragt heraus."""
    async def wechsel(app, pg):
        frisch = await pg.evaluate(MESSEN)
        danach = {}
        for start in ("KS_MIN", "KS_MAX"):
            await pg.evaluate(f"setzeFaktor({start}); render()")
            await pg.wait_for_timeout(300)
            danach[start] = await pg.evaluate(MESSEN)
        return frisch, danach
    werte = "header:" + ",".join(f"V{i}" for i in range(W.SV_STATUS_MAX))
    # 800 x 480 mit festem 3x2: die Hoehe begrenzt den Faktor (Kachel etwa 250 x 170),
    # und neben Uhr und Wetter passen Werte in die Zeile
    frisch, danach = _ansehen(monkeypatch, (800, 480), {"cols": 3, "rows": 2, "split": False,
                                                         "panes": {"favoriten": werte}}, wechsel)
    _zeile_steht(frisch)
    assert frisch["kopfH"] == round(64 * frisch["ks"]), frisch
    gezeigt = lambda m: [w["name"] for w in m["werte"] if not w["weg"]]
    assert gezeigt(frisch), "auf 800 px passt mindestens ein Wert"
    assert frisch["kachel"][1] / 150 < frisch["kachel"][0] / 170, "die Hoehe begrenzt den Faktor, sonst prueft der Test nichts"
    for start, m in danach.items():
        _zeile_steht(m)
        assert abs(m["ks"] - frisch["ks"]) < 0.01, (start, m["ks"], frisch["ks"])
        assert m["kopfH"] == frisch["kopfH"] and m["kachel"] == frisch["kachel"], (start, m, frisch)
        assert gezeigt(m) == gezeigt(frisch), (start, gezeigt(m), gezeigt(frisch))
        assert all(w["rechts"] <= m["werteBox"]["r"] + 1 and w["rechts"] <= m["kopf"]["r"]
                   for w in m["werte"] if not w["weg"]), (start, m["werte"])


def test_kopfzeile_beim_drehen(monkeypatch):
    async def drehen(app, pg):
        vorher = await pg.evaluate(MESSEN)
        await pg.set_viewport_size({"width": HOCH[0], "height": HOCH[1]})
        await pg.wait_for_timeout(700)
        return vorher, await pg.evaluate(MESSEN)
    vorher, nachher = _ansehen(monkeypatch, QUER, {"grid": "auto", "panes": {"favoriten": "header:T"}}, drehen)
    _zeile_steht(vorher)
    _zeile_steht(nachher)
    assert nachher["raster"][0] < vorher["raster"][0] and nachher["sichtbar"] == nachher["raster"][0] * nachher["raster"][1]


def test_konfigurator_bietet_die_kopfzeile_an():
    from test_konfigurator_browser import _im_konfigurator
    res = _im_konfigurator("""async () => {
        cur = 'test'; const p = PANELS[cur]; p.ui = p.ui || {};
        document.body.insertAdjacentHTML('beforeend', '<div id="paneField"><div id="panePerTab"></div></div>');
        renderPanes(p);
        const sel = () => document.querySelector('select[data-pane="favoriten"]');
        const arten = [...sel().options].map(o => o.value);
        sel().value = 'header'; sel().onchange();
        const ohne = p.ui.panes.favoriten;
        const dazu = document.querySelector('.pkopf-add[data-pk="favoriten"]');
        const erste = [...dazu.options].find(o => o.value).value;
        dazu.value = erste; dazu.onchange();
        const mit = p.ui.panes.favoriten;
        const chip = document.querySelector('.chip[data-hu][data-pk="favoriten"]');
        chip.click();
        const wiederOhne = p.ui.panes.favoriten;
        document.querySelector('select[data-pane="favoriten"]').value = 'weather';
        document.querySelector('select[data-pane="favoriten"]').onchange();
        return {arten, ohne, mit, erste, wiederOhne, danach: p.ui.panes.favoriten, assistent: wzP2Real('header'),
                assistentOptionen: wzP2Opts('').indexOf('value="header"') > -1};
    }""")
    assert "header" in res["arten"] and res["ohne"] == "header"
    assert res["mit"] == "header:" + res["erste"] and res["wiederOhne"] == "header"
    assert res["danach"] == "weather"
    assert res["assistent"] == "header" and res["assistentOptionen"]
    # Was der Konfigurator schreibt, nimmt der Server unveraendert
    assert W._clean_tabpane(res["mit"]) == res["mit"]


def test_konfigurator_ohne_split_nur_die_kopfzeile():
    """Split "Aus" (4"-Panel): das Feld bleibt sichtbar, die Widget-Gruppe ist
    gesperrt, die Kopfzeile waehlbar. Der Assistent bietet sie fuer 1 Pane
    ebenfalls an, ohne die Widgets daneben."""
    from test_konfigurator_browser import _im_konfigurator
    res = _im_konfigurator("""async () => {
        cur = 'test'; const p = PANELS[cur]; p.ui = {split: false};
        document.body.insertAdjacentHTML('beforeend', '<div id="paneField"><div id="panePerTab"></div></div>');
        renderPanes(p);
        const feld = document.getElementById('paneField');
        const sel = document.querySelector('select[data-pane="favoriten"]');
        const gesperrt = [...sel.options].filter(o => o.closest('optgroup') && o.closest('optgroup').disabled).map(o => o.value);
        const frei = [...sel.options].filter(o => !(o.closest('optgroup') && o.closest('optgroup').disabled)).map(o => o.value);
        sel.value = 'header'; sel.onchange();
        // Assistent: 1 Pane, klassische Tabs
        wzReset(); WZ.panes = '1'; WZ.content = 'classic';
        WZ.classic = [{key: 'favoriten', label: 'Favoriten', on: true}, {key: 'zentral', label: 'Zentral', on: false}];
        const zeilen = wzPaneRows();
        const tmp = document.createElement('div'); tmp.innerHTML = zeilen;
        const wzOpts = [...tmp.querySelectorAll('select[data-p2k="favoriten"] option')].map(o => o.value);
        return {sichtbar: feld.style.display !== 'none', gesperrt, frei, gewaehlt: p.ui.panes.favoriten,
                wzOpts, wzZeilen: tmp.querySelectorAll('select').length};
    }""")
    assert res["sichtbar"] and res["gewaehlt"] == "header"
    assert "header" in res["frei"] and "" in res["frei"], res
    assert "weather" in res["gesperrt"] and "status" in res["gesperrt"], res
    assert res["wzZeilen"] == 1 and res["wzOpts"] == ["", "header"], res
