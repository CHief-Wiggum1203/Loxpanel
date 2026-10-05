"""Tablet im Browser (Chromium): Werte unter dem Kamerabild, Startmessung und
iOS-Web-App.

- Pane 2 "Kamera" mit Werten ("camera:<uuid>|<uuid>,..."): unter dem 4:3-Bild
  stehen die gewaehlten Werte wie in der Werte-Pane, ein Zustandswechsel
  aktualisiert sie, ohne das Video neu zu laden; ohne Werte bleibt die Pane
  wie bisher.
- Startmessung: meldet das Fenster beim Laden 0 x 0 (iOS-Web-App vom
  Home-Bildschirm, mancher Kiosk-Browser), rechnet das automatische Raster
  trotzdem aus der echten Flaeche statt 1 Zeile ueber den Schirm zu legen;
  'pageshow' zieht nach.
- iOS-Web-App: die Meta-Angaben fuer den Vollbildstart stehen im Kopf, der
  Kasten ist so hoch wie die sichtbare Flaeche (dynamische Viewport-Hoehe).
"""
import asyncio
import shutil

import pytest

from lox import ROOT, W, anlage, intercom_baustein, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

TAB_A9 = (893, 533)
_IC, _IC_STATES = intercom_baustein()
STRUKTUR = anlage({
    **{f"S{i}": {"name": f"Licht {i}", "type": "Switch", "uuidAction": f"S{i}", "room": "r1", "cat": "c1",
                 "isFavorite": True, "states": {"active": f"s{i}"}} for i in range(12)},
    "IC": _IC,
    "T": {"name": "Boiler", "type": "InfoOnlyAnalog", "uuidAction": "T", "states": {"value": "st"},
          "details": {"format": "%.1f°C"}, "room": "r1"},
    "P": {"name": "Papier", "type": "InfoOnlyDigital", "uuidAction": "P", "states": {"active": "sp"},
          "details": {"text": {"on": "morgen", "off": "–"}}, "room": "r1"},
})
STATES = {**{f"s{i}": i % 3 == 0 for i in range(12)}, **_IC_STATES, "st": 51.5, "sp": 1}


@pytest.fixture(autouse=True)
def _frische_installation(cfg_ordner):
    shutil.copy(ROOT / "config" / "theme.example.json", cfg_ordner / "theme.example.json")


def _laufen(ui, groesse, schritte, init_script=None):
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(STRUKTUR)
        app.states = dict(STATES)
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"], "ui": ui}})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": groesse[0], "height": groesse[1]})
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                if init_script:
                    await pg.add_init_script(init_script)
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector("#grid .tile[data-id]", state="attached")
                if await pg.locator("#saver:not(.hidden)").count():
                    await pg.click("#saver")
                    await pg.wait_for_selector("#saver.hidden", state="attached")
                await pg.wait_for_timeout(600)
                ergebnis = await schritte(app, pg)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return ergebnis
    return asyncio.run(lauf())


KAMERA_WERTE = """() => { const fp = document.getElementById('frontpane'), r = e => e.getBoundingClientRect();
  // Bild = Live-Video oder, wie beim Test-Intercom ohne videoInfo, der Hinweis "Kein Video"
  const video = fp.querySelector('.campage .video, .campage .status'), w = fp.querySelector('.campage .camwerte');
  const zeilen = w ? [...w.querySelectorAll('.sv-st')] : [];
  return {video: !!video, werte: !!w,
    zeilen: zeilen.map(z => [z.querySelector('.nm').firstChild.textContent, z.querySelector('.vl').textContent, z.classList.contains('on')]),
    unterDemBild: !!(video && w && r(w).top >= r(video).bottom - 1),
    imRahmen: !w || r(w).bottom <= r(fp).bottom + 1,
    videoSrc: video ? (video.querySelector('img') ? video.querySelector('img').getAttribute('src') : video.textContent) : null,
    tasten: fp.querySelectorAll('.campage .brow .btn').length}; }"""


def test_werte_unter_dem_kamerabild():
    async def schritte(app, pg):
        await pg.wait_for_selector("#frontpane .campage .camwerte .sv-st", state="attached", timeout=5000)
        vorher = await pg.evaluate(KAMERA_WERTE)
        # Zustand wechselt: der Server pusht die Werte neu, das Video bleibt stehen
        app.states["sp"] = 0
        app.states["st"] = 48.0
        for ws, uu in list(app.conn_status.items()):
            await ws.send_json({"t": "svstatus", "items": app.status_blocks(uu)})
        await pg.wait_for_timeout(400)
        nachher = await pg.evaluate(KAMERA_WERTE)
        return vorher, nachher
    vorher, nachher = _laufen({"panes": {"favoriten": "camera:IC|P,T"}, "grid": "auto"}, TAB_A9, schritte)
    assert vorher["video"] and vorher["tasten"] == 1 and vorher["werte"] and vorher["unterDemBild"] and vorher["imRahmen"], vorher
    assert vorher["zeilen"] == [["Papier", "morgen", True], ["Boiler", "51,5 °C", False]], vorher
    assert nachher["zeilen"] == [["Papier", "–", False], ["Boiler", "48,0 °C", False]], nachher
    assert nachher["videoSrc"] == vorher["videoSrc"]


def test_kamera_ohne_werte_wie_bisher():
    async def schritte(app, pg):
        await pg.wait_for_selector("#frontpane .campage .brow", state="attached", timeout=5000)
        return await pg.evaluate(KAMERA_WERTE)
    erg = _laufen({"panes": {"favoriten": "camera:IC"}, "grid": "auto"}, TAB_A9, schritte)
    assert erg["video"] and erg["tasten"] == 1 and not erg["werte"], erg


RASTER = "() => ({raster: [gridCols, gridRows], vp: vpSize(), inner: [innerWidth, innerHeight]})"
NULL_FENSTER = """Object.defineProperty(window, 'innerWidth', {configurable: true, get: () => 0});
Object.defineProperty(window, 'innerHeight', {configurable: true, get: () => 0});"""


def test_startmessung_null_fenster_rechnet_aus_der_flaeche():
    """iOS-Web-App: innerWidth/innerHeight sind beim Start 0 und es kommt kein
    resize mehr. Das Raster muss trotzdem dem der echten Flaeche entsprechen."""
    async def schritte(app, pg):
        mit_null = await pg.evaluate(RASTER)
        await pg.evaluate("""() => { const de = document.documentElement;   // Fenster meldet nun die echte Flaeche
            Object.defineProperty(window, 'innerWidth', {configurable: true, get: () => de.clientWidth});
            Object.defineProperty(window, 'innerHeight', {configurable: true, get: () => de.clientHeight});
            window.dispatchEvent(new Event('pageshow')); }""")
        await pg.wait_for_timeout(300)
        danach = await pg.evaluate(RASTER)
        return mit_null, danach
    mit_null, danach = _laufen({"grid": "auto"}, TAB_A9, schritte, init_script=NULL_FENSTER)
    normal = _laufen({"grid": "auto"}, TAB_A9, lambda app, pg: pg.evaluate(RASTER))
    assert mit_null["inner"] == [0, 0] and mit_null["vp"] == normal["vp"], (mit_null, normal)
    assert mit_null["raster"] == normal["raster"] == danach["raster"], (mit_null, normal, danach)
    assert normal["raster"][1] > 1


def test_ios_web_app_kopf_und_hoehe():
    async def schritte(app, pg):
        return await pg.evaluate("""() => { const m = n => { const e = document.querySelector('meta[name="' + n + '"]'); return e && e.content; };
          const sc = document.querySelector('.screen').getBoundingClientRect();
          return {webapp: m('apple-mobile-web-app-capable'), bar: m('apple-mobile-web-app-status-bar-style'),
            viewport: m('viewport'), hoehe: Math.round(sc.height), breite: Math.round(sc.width),
            tabsUnten: Math.round(document.getElementById('tabs').getBoundingClientRect().bottom)}; }""")
    erg = _laufen({"grid": "auto"}, TAB_A9, schritte)
    assert erg["webapp"] == "yes" and erg["bar"] == "black-translucent" and "viewport-fit=cover" in erg["viewport"], erg
    assert (erg["breite"], erg["hoehe"]) == TAB_A9 and erg["tabsUnten"] == TAB_A9[1], erg
