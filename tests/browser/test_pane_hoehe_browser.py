"""Pane 2 nutzt ihre Flaeche: Wetter, Kalender und Werte passen sich an die
Groesse der zweiten Flaeche an (wetterEinpassen, kalenderEinpassen,
werteEinpassen), quer und hochkant, mit festem Raster und "Automatisch".
Gemessen in Chromium an den Groessen des Tab A9 (893 x 533, 533 x 893) und
eines 10"-Tablets (1280 x 800).

Vorher blieb unter Wetter und Monat bis zu ein Drittel leer, die Termine
standen auf einer zweiten Seite, die niemand fand, und zwei Werte belegten
zwei schmale Zeilen. Mit "Automatisch" quetschte sich die Beschreibung des
Wetters zu einer Spalte, die Vorschau lief seitlich und unten aus dem Rahmen.
Die Kurve war immer 700 x 150 gross gezeichnet und nur verkleinert, ihre
Zahlen schrumpften auf einer schmalen Flaeche auf 6 px. Uhr-Seite und
Wetter-Tab bleiben, wie sie sind."""
import asyncio
from datetime import date, timedelta

import pytest

from lox import W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

QUER, HOCH, GROSS = (893, 533), (533, 893), (1280, 800)
FEST = {"cols": 3, "rows": 3, "fill": True}          # die Einstellung am ersten Geraet
AUTO = {"grid": "auto"}
AUTO_GROSS = {"grid": "auto", "tileSize": "large"}  # hochkant bleibt dem Widget wenig Hoehe
WERTE = {f"V{i}": {"name": f"Vorlauftemperatur Kreis {i}", "type": "InfoOnlyAnalog", "uuidAction": f"VA{i}",
                   "room": "r1", "cat": "c1", "details": {"format": "%.1f°"}, "states": {"value": f"v{i}"}}
         for i in range(W.SV_STATUS_MAX)}
BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "LA", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}},
             "T": {"name": "Außentemperatur", "type": "InfoOnlyAnalog", "uuidAction": "TA", "room": "r1",
                   "cat": "c1", "details": {"format": "%.1f°"}, "states": {"value": "tv"}}, **WERTE}
ZUSTAND = {"sl": 0, "tv": 17.3, **{f"v{i}": 30 + i for i in range(W.SV_STATUS_MAX)}}

# Was eine Pruefung ueber die Seite wissen muss, in einem Zug gemessen
MESSEN = """() => {
  const fp = document.getElementById('frontpane'), s = fp.querySelector(':scope > .fp-page');
  const r = e => { if (!e) return null; const b = e.getBoundingClientRect();
    return {l: b.left, r: b.right, t: b.top, b: b.bottom, w: b.width, h: b.height}; };
  const cs = getComputedStyle(s), innenUnten = s.getBoundingClientRect().bottom - parseFloat(cs.paddingBottom);
  const sichtbar = [...s.children].filter(k => !k.hidden && k.getBoundingClientRect().height > 0);
  const k = s.querySelector('.fp-curve'), svg = k && k.querySelector('svg');
  const zahl = k && k.querySelector('.fpt');
  // Stunden der Kurve: links nach rechts, keine darf die naechste beruehren
  const stunden = k ? [...k.querySelectorAll('.fpx')].map(e => e.getBoundingClientRect()).sort((a, b) => a.left - b.left) : [];
  const stundenUeberlappen = stunden.some((b, i) => i && b.left < stunden[i - 1].right);
  return {
    klassen: s.className.split(' '), pane: r(fp), seite: r(s), seitenzahl: fp.querySelectorAll(':scope > .fp-page:not([hidden])').length,
    leerUnten: innenUnten - Math.max(...sichtbar.map(e => e.getBoundingClientRect().bottom)),
    seiteUeber: s.scrollHeight - s.clientHeight,
    teileUeber: [...s.children].filter(e => !e.hidden && !e.classList.contains('kal-liste')
                                           && e.scrollHeight > e.clientHeight + 1).map(e => e.className),
    paneScrollt: fp.scrollHeight > fp.clientHeight + 2,
    kurve: r(k), viewBox: svg ? svg.getAttribute('viewBox') : null, zahlHoehe: zahl ? zahl.getBoundingClientRect().height : null,
    stundenUeberlappen, stunden: stunden.length,
    now: r(s.querySelector('.fp-now')), temp: r(s.querySelector('.fp-now .t')), meta: r(s.querySelector('.fp-now .meta')),
    heute: (e => e ? getComputedStyle(e).display : null)(s.querySelector('.fp-now .heute')),
    vorschau: (f => f ? {x: getComputedStyle(f).overflowX, breiter: f.scrollWidth > f.clientWidth + 1,
                         tage: f.querySelectorAll('.fp-fc').length,
                         zelle: Math.min(...[...f.querySelectorAll('.fp-fc')].map(c => c.getBoundingClientRect().width))} : null)(s.querySelector('.fp-fore')),
    detailsAufSeite1: !!s.querySelector('.fp-det'), details: fp.querySelectorAll('.fp-det > div').length,
    monat: r(s.querySelector('.kal-monat')), monatUeber: (m => m ? m.scrollHeight - m.clientHeight : null)(s.querySelector('.kal-monat')),
    liste: r(s.querySelector('.kal-liste')),
    zeilen: [...s.querySelectorAll('.sv-st')].map(z => { const nm = z.querySelector('.nm'), vl = z.querySelector('.vl');
      const zr = z.getBoundingClientRect(), nr = nm.getBoundingClientRect(), vr = vl.getBoundingClientRect();
      return {...r(z), wert: parseFloat(getComputedStyle(vl).fontSize), nameGanz: nm.scrollWidth <= nm.clientWidth + 1,
              wertUnten: vr.top >= nr.bottom - 1, wertRechts: zr.right - vr.right <= 30}; }),
  };
}"""


def _app(ui: dict, tabs=("favoriten",), pick_tabs=None):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = dict(ZUSTAND)
    panel = {"title": "Test", "tabs": list(tabs), "ui": ui}
    if pick_tabs:
        panel["pickTabs"] = pick_tabs
    app.panels = W.App._sanitize_panels({"test": panel})
    return app


def _ansehen(monkeypatch, groesse, schritt, ui=None, tabs=("favoriten",), pick_tabs=None, zwei_kalender=False):
    """Visu mit Kalender und Wetter aus dem Nachbau (wie test_front_tabs_browser)
    in der Groesse `groesse` laden, Uhr-Seite weg, dann schritt(pg).
    zwei_kalender: ein zweiter Kalender, damit es eine Legende gibt."""
    from test_front_tabs_browser import _front

    async def lauf():
        daten = await _front(monkeypatch)
        if zwei_kalender:
            daten = dict(daten, cals=list(daten["cals"]) + [{"key": "arbeit", "name": "Arbeit", "color": "#e2695f"}])
        app = _app(ui or {}, tabs, pick_tabs)
        app._front = app._front_payload(daten)
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": groesse[0], "height": groesse[1]}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_timeout(600)
                await pg.evaluate("wake()")
                await pg.wait_for_timeout(700)
                await schritt(pg)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


def _pane(widget, raster):
    return {**raster, "panes": {"favoriten": widget}}


def _passt(m):
    """Nichts ragt aus der Seite oder aus seinem Feld."""
    assert m["seiteUeber"] <= 0, m["seiteUeber"]
    assert not m["teileUeber"], m["teileUeber"]


def _kurve_in_ihrer_groesse(m, min_hoehe):
    k = m["kurve"]
    assert k["h"] >= min_hoehe, k
    assert m["viewBox"] == f"0 0 {round(k['w'])} {round(k['h'])}", (m["viewBox"], k)
    assert m["zahlHoehe"] >= 10, f"Zahlen der Kurve {m['zahlHoehe']:.1f} px hoch"
    assert m["stunden"] >= 4 and not m["stundenUeberlappen"], "Stunden unter der Kurve lesbar"


def test_wetter_fuellt_die_flaeche(monkeypatch):
    """Tab A9 quer mit 3 x 3 und "Bildschirm fuellen": Vorher blieben unter der
    Vorschau 59 px leer, die Kurve war 84 px hoch."""
    async def schritt(pg):
        m = await pg.evaluate(MESSEN)
        _passt(m)
        assert m["leerUnten"] <= 2, m["leerUnten"]
        _kurve_in_ihrer_groesse(m, 120)
        assert "breit" not in m["klassen"] and "schmal" not in m["klassen"]
        # Die Details passen nicht mit darauf: sie stehen auf Seite 2, einmal
        assert not m["detailsAufSeite1"] and m["seitenzahl"] == 2 and m["details"] == 6, m
    _ansehen(monkeypatch, QUER, schritt, _pane("weather", FEST))


def test_wetter_schmal(monkeypatch):
    """Tab A9 quer mit "Automatisch": die Flaeche ist 356 px breit."""
    async def schritt(pg):
        m = await pg.evaluate(MESSEN)
        _passt(m)
        assert "schmal" in m["klassen"], m["klassen"]
        assert m["meta"]["t"] >= m["temp"]["b"] - 1, "Beschreibung unter der Temperatur"
        assert m["meta"]["w"] > m["now"]["w"] * 0.8, "die Beschreibung hat die ganze Breite"
        v = m["vorschau"]
        assert v["x"] == "auto" and v["tage"] == 7 and v["zelle"] >= 50, v
        _kurve_in_ihrer_groesse(m, 64)
    _ansehen(monkeypatch, QUER, schritt, _pane("weather", AUTO))


def test_wetter_breit(monkeypatch):
    """Tab A9 hochkant mit "Automatisch": breit und niedrig, Lage und Kurve
    nebeneinander. Vorher wurde die Vorschau unten abgeschnitten."""
    async def schritt(pg):
        m = await pg.evaluate(MESSEN)
        _passt(m)
        assert "breit" in m["klassen"], m["klassen"]
        assert m["kurve"]["l"] >= m["now"]["r"], "Kurve rechts neben der Lage"
        assert m["kurve"]["w"] >= 150, m["kurve"]
        _kurve_in_ihrer_groesse(m, 100)
        assert not m["vorschau"]["breiter"] and m["vorschau"]["tage"] == 7
    _ansehen(monkeypatch, HOCH, schritt, _pane("weather", AUTO))


def test_wetter_eng(monkeypatch):
    """Grosse Kacheln lassen hochkant nur 256 px: Die Lage rueckt zusammen,
    "Heute hoch/tief" (steht in der Vorschau) entfaellt, nichts laeuft ueber."""
    async def schritt(pg):
        m = await pg.evaluate(MESSEN)
        _passt(m)
        assert {"breit", "eng"} <= set(m["klassen"]), m["klassen"]
        assert m["heute"] == "none"
        assert m["kurve"]["h"] >= 64, m["kurve"]
    _ansehen(monkeypatch, HOCH, schritt, _pane("weather", AUTO_GROSS))


def test_wetter_mit_details_auf_einer_seite(monkeypatch):
    """10"-Tablet quer: genug Hoehe fuer alles, keine zweite Seite."""
    async def schritt(pg):
        m = await pg.evaluate(MESSEN)
        _passt(m)
        assert m["detailsAufSeite1"] and m["seitenzahl"] == 1 and m["details"] == 6, m
        assert not m["paneScrollt"]
        _kurve_in_ihrer_groesse(m, 96)
    _ansehen(monkeypatch, GROSS, schritt, _pane("weather", AUTO))


def test_kurve_beschriftung_mit_abstand(monkeypatch):
    """Die Zahlen der Kurve halten mindestens 26 px Abstand, auch schmal
    gezeichnet; die letzte Stunde nur, wenn dafuer Platz ist. In der alten
    Groesse 700 px bleibt es bei jedem dritten Punkt."""
    async def schritt(pg):
        r = await pg.evaluate("""() => { const hh = frontData.weather.hourly;
            return [700, 300, 220, 160, 120].map(w => {
              const d = document.createElement('div'); d.innerHTML = fpCurve(hh, w, 140);
              return {w, n: hh.filter(h => h && h.temp != null).length,
                      xs: [...d.querySelectorAll('.fpt')].map(t => parseFloat(t.getAttribute('x')))}; }); }""")
        for e in r:
            abstaende = [b - a for a, b in zip(e["xs"], e["xs"][1:])]
            assert len(e["xs"]) >= 3 and min(abstaende) >= 26 - 0.05, (e["w"], abstaende)
        alt = r[0]
        dx = (700 - 24) / (alt["n"] - 1)
        assert all(abs(a - 3 * dx) < 0.2 for a in [b - a for a, b in zip(alt["xs"], alt["xs"][1:])][:-1]), alt
        assert abs(alt["xs"][-1] - (700 - 12)) < 0.2, "die letzte Stunde steht bei 700 px"
    _ansehen(monkeypatch, QUER, schritt, _pane("weather", FEST))


def test_wetter_passt_sich_beim_drehen_an(monkeypatch):
    async def schritt(pg):
        quer = await pg.evaluate(MESSEN)
        assert "schmal" in quer["klassen"]
        await pg.evaluate("window.__dieselbe = 1")
        await pg.set_viewport_size({"width": HOCH[0], "height": HOCH[1]})
        await pg.wait_for_timeout(800)
        hoch = await pg.evaluate(MESSEN)
        assert await pg.evaluate("window.__dieselbe") == 1, "ohne Neuladen"
        assert "breit" in hoch["klassen"] and "schmal" not in hoch["klassen"], hoch["klassen"]
        _passt(hoch)
        _kurve_in_ihrer_groesse(hoch, 100)
    _ansehen(monkeypatch, QUER, schritt, _pane("weather", AUTO))


def test_wetter_passt_sich_ohne_neues_raster_an(monkeypatch):
    """Das Fenster waechst, das Raster bleibt 3 x 3: Nur die Pane wird groesser,
    die Kurve wird in der neuen Groesse gezeichnet."""
    async def schritt(pg):
        vorher = await pg.evaluate(MESSEN)
        await pg.set_viewport_size({"width": 1000, "height": 640})
        await pg.wait_for_timeout(800)
        m = await pg.evaluate(MESSEN)
        assert m["kurve"]["h"] > vorher["kurve"]["h"] + 50, (vorher["kurve"], m["kurve"])
        _passt(m)
        assert m["leerUnten"] <= 2, m["leerUnten"]
        _kurve_in_ihrer_groesse(m, 120)
    _ansehen(monkeypatch, QUER, schritt, _pane("weather", FEST))


def test_kalender_termine_unter_dem_monat(monkeypatch):
    """Eine Seite: unter dem Monat die Termine. Ein Tipp auf einen Tag zeigt
    dessen Termine gleich darunter, ohne zu scrollen."""
    async def schritt(pg):
        m = await pg.evaluate(MESSEN)
        _passt(m)
        assert m["seitenzahl"] == 1 and not m["paneScrollt"], m
        assert m["liste"]["t"] >= m["monat"]["b"], "Termine unter dem Monat"
        assert m["liste"]["h"] >= 160, m["liste"]
        assert m["leerUnten"] <= 2, m["leerUnten"]
        in5 = date.today() + timedelta(days=5)
        if in5.month != date.today().month:
            await pg.locator('#frontpane .fp-mnav[data-mnav="1"]').click()
            await pg.wait_for_timeout(300)
        await pg.locator(f'#frontpane .fp-mon-c[data-day="{in5.isoformat()}"]').click()
        await pg.wait_for_timeout(300)
        tag = await pg.evaluate("""() => { const p = document.getElementById('frontpane').getBoundingClientRect();
            return [...document.querySelectorAll('#frontpane .kal-liste .fp-ev')].map(e => {
              const r = e.getBoundingClientRect();
              return {titel: e.querySelector('.ttl').textContent, sichtbar: r.top >= p.top && r.bottom <= p.bottom}; }); }""")
        assert sorted(t["titel"] for t in tag) == ["Hund füttern", "Zahnarzt"], tag
        assert all(t["sichtbar"] for t in tag), tag
        await pg.locator("#frontpane [data-calall]").click()
        await pg.wait_for_timeout(300)
        assert await pg.locator("#frontpane .kal-liste .fp-ev").count() > 2
        # Die Legende steht einmal, unter dem Monat
        assert await pg.locator("#frontpane .fp-leg").count() == 1
        assert await pg.locator("#frontpane .kal-monat .fp-leg").count() == 1
    _ansehen(monkeypatch, QUER, schritt, _pane("calendar", FEST), zwei_kalender=True)


def test_kalender_nebeneinander(monkeypatch):
    """Tab A9 hochkant: unter dem Monat blieben 37 px fuer Termine. Jetzt
    stehen sie daneben."""
    async def schritt(pg):
        m = await pg.evaluate(MESSEN)
        _passt(m)
        assert "breit" in m["klassen"], m["klassen"]
        assert m["liste"]["l"] >= m["monat"]["r"] and m["liste"]["h"] >= 250, (m["monat"], m["liste"])
    _ansehen(monkeypatch, HOCH, schritt, _pane("calendar", AUTO))


def test_kalender_kurz(monkeypatch):
    """256 px Hoehe: Der Monat rueckt in zwei Stufen zusammen und passt ganz."""
    async def schritt(pg):
        m = await pg.evaluate(MESSEN)
        _passt(m)
        assert {"breit", "eng", "eng2"} <= set(m["klassen"]), m["klassen"]
        assert m["monatUeber"] <= 1, m["monatUeber"]
    _ansehen(monkeypatch, HOCH, schritt, _pane("calendar", AUTO_GROSS))


def test_zwei_werte_fuellen_die_hoehe(monkeypatch):
    """Vorher zwei 45 px hohe Zeilen, darunter 69 % leer."""
    async def schritt(pg):
        m = await pg.evaluate(MESSEN)
        z = m["zeilen"]
        assert len(z) == 2 and "werte" in m["klassen"], m["klassen"]
        assert m["leerUnten"] <= 2, m["leerUnten"]
        assert abs(z[0]["h"] - z[1]["h"]) <= 1 and z[0]["h"] >= 150, z
        assert all(x["wert"] >= 30 for x in z), z
        assert all(x["nameGanz"] for x in z), "Name ganz zu lesen"
        assert all(x["wertUnten"] and x["wertRechts"] for x in z), "Wert gross unter dem Namen, rechts"
        # Zeichnet applyPane neu (Tab-Wechsel, neue Einstellungen), bleibt es so
        await pg.evaluate("applyPane()")
        await pg.wait_for_timeout(300)
        nochmal = await pg.evaluate(MESSEN)
        assert "werte" in nochmal["klassen"] and len(nochmal["zeilen"]) == 2, nochmal["klassen"]
    _ansehen(monkeypatch, QUER, schritt, _pane("status:T,L", FEST))


def test_viele_werte(monkeypatch):
    """Acht Werte auf 334 px: Die Zeilen werden nicht unlesbar klein, die Pane
    scrollt dann wie bisher."""
    async def schritt(pg):
        m = await pg.evaluate(MESSEN)
        z = m["zeilen"]
        assert len(z) == W.SV_STATUS_MAX
        assert min(x["h"] for x in z) >= 40 and min(x["wert"] for x in z) >= 15, z
        assert m["paneScrollt"]
    _ansehen(monkeypatch, HOCH, schritt, _pane("status:" + ",".join(WERTE), AUTO))


def test_uhrseite_und_wetter_tab_wie_bisher(monkeypatch):
    """Die Werte der Uhr-Seite behalten ihre Ueberschrift ohne Rahmen, der
    Wetter-Tab zeichnet die Kurve weiter 700 x 150 und skaliert sie."""
    async def schritt(pg):
        await pg.evaluate("showSaver()")
        await pg.wait_for_timeout(600)
        uhr = await pg.evaluate("""() => { const b = document.getElementById('svBox');
            return {lbl: (b.querySelector(':scope > .lbl') || {}).textContent, zeilen: b.querySelectorAll('.sv-st').length,
                    rahmen: !!b.querySelector('.fp-page.werte')}; }""")
        assert uhr == {"lbl": "Werte", "zeilen": 2, "rahmen": False}, uhr
        await pg.evaluate("wake()")
        await pg.locator('#tabs .tab[data-tab="wetter"]').click()
        await pg.wait_for_timeout(500)
        assert await pg.locator(".ft-wx .fp-curve svg").get_attribute("viewBox") == "0 0 700 150"
    _ansehen(monkeypatch, QUER, schritt, {"svPane": "status:T,L"}, tabs=("favoriten", "wetter"))


def test_widget_seite_ohne_verbindungspunkt(monkeypatch):
    """Auf einer Widget-Seite saesse der Punkt mitten im Wetter."""
    async def schritt(pg):
        assert await pg.evaluate("document.querySelector('.screen').classList.contains('widgettab')")
        assert not await pg.evaluate("document.getElementById('conn').classList.contains('vis')")
        m = await pg.evaluate(MESSEN)
        _passt(m)
        assert m["leerUnten"] <= 2
    _ansehen(monkeypatch, QUER, schritt, {}, tabs=("auswahl",), pick_tabs=[{"name": "Wetter", "widget": "weather"}])
