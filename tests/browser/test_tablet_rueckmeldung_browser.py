"""Rueckmeldung vom Tablet (10.10.2026) in Chromium.

Seiten-Editor: Palette und Arbeitsflaeche liegen zugleich im Bild, sonst geht
das Ziehen nicht. Die Widgets stehen oben in der Palette, die Bausteinliste
scrollt in ihr, die Palette bleibt beim Scrollen der Seite neben der Flaeche
stehen; "Ausgewählt" liegt nie unter ihr. Ist der Editor schmal (Tablet
hochkant), dockt sie unten an.

Kopfzeile: die gewaehlten Werte erscheinen, als Wert der Messwert der Kachel
(big, bei der Raumregelung die Ist-Temperatur), und sie gehen dem Wettertext
vor - am 4"-Panel bleiben vom Wetter Symbol und Temperatur, dafuer passen
beide Werte. Der Config-Ordner ist umgeleitet (Fixture cfg_ordner)."""
import asyncio
import json

import pytest

from lox import konfig, KONFIGURATOR_GELADEN, W, anlage, irc2_baustein, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

LICHTER = {f"L{i}": {"name": f"Licht {i}", "type": "Switch", "uuidAction": f"L{i}", "room": "r1", "cat": "c1",
                     "isFavorite": True, "states": {"active": f"s{i}"}} for i in range(30)}
LAGE = """() => { const r = s => { const b = document.querySelector(s).getBoundingClientRect();
    return {oben: Math.round(b.top), unten: Math.round(b.bottom), links: Math.round(b.left), rechts: Math.round(b.right)}; };
  return {scroll: r('#scroll'), flaeche: r('#seHost [data-se-flaeche]'), pal: r('#seHost .se-pal'),
          widgets: r('#seHost .se-wl'), letzter: r('#seHost .se-liste .se-p:last-child'), feld: r('#seHost .se-feld')}; }"""


def _im_bild(teil, scroll):
    return teil["oben"] >= scroll["oben"] - 1 and teil["unten"] <= scroll["unten"] + 1


def _ueberlappt(a, b):
    return a["links"] < b["rechts"] and b["links"] < a["rechts"] and a["oben"] < b["unten"] and b["oben"] < a["unten"]


@pytest.mark.parametrize("groesse, angedockt", [((1080, 810), False), ((1180, 820), False), ((810, 1080), True)])
def test_palette_und_flaeche_zugleich_im_bild(cfg_ordner, groesse, angedockt):
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"flur": {
        "title": "Flur", "tabs": ["auswahl"], "pickTabs": [{"name": "Wohnen", "picks": ["L1", "L2"]}]}}}), encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(LICHTER))
        app.states = {f"s{i}": 0 for i in range(30)}
        runner, port, bc = await visu_starten(app, [("GET", "/api/devices", W.api_devices_get)])
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": groesse[0], "height": groesse[1]}, locale="de-DE", has_touch=True)
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator(".rub", has_text="Ansichten").click()
                await pg.locator("#plist .pitem", has_text="?panel=flur").click()
                await pg.locator(".stab[data-sub='seiten']").click()
                await pg.wait_for_selector("#seHost [data-se-flaeche]")
                vorher = await pg.evaluate(LAGE)
                assert vorher["widgets"]["oben"] < vorher["pal"]["oben"] + 120, "Widgets oben in der Palette"
                # Flaeche oben, dann ans Ende der Bausteinliste: beides bleibt zu sehen
                await pg.evaluate("document.querySelector('#seHost [data-se-flaeche]').scrollIntoView({block: 'start'})")
                await pg.evaluate("document.querySelector('#seHost .se-pal').scrollTop = 1e6")
                lage = await pg.evaluate(LAGE)
                sc = lage["scroll"]
                if angedockt:
                    assert 0 <= sc["unten"] - lage["pal"]["unten"] <= 30, ("unten angedockt (Innenabstand)", lage)
                    assert lage["flaeche"]["oben"] < lage["pal"]["oben"], lage
                else:
                    assert _im_bild(lage["flaeche"], sc) and _im_bild(lage["pal"], sc), lage
                    assert not _ueberlappt(lage["feld"], lage["pal"]), ("Ausgewählt unter der Palette", lage)
                assert _im_bild(lage["letzter"], sc), ("letzter Baustein erreichbar", lage)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
    asyncio.run(lauf())


@pytest.mark.parametrize("groesse, wettertext", [((1080, 810), True), ((893, 533), True), ((480, 480), False)])
def test_kopfzeile_zeigt_die_gewaehlten_werte(cfg_ordner, monkeypatch, groesse, wettertext):
    from test_front_tabs_browser import _front
    rc, werte = irc2_baustein()
    rc = {**rc, "name": "Abstellraum", "room": "r3"}
    bausteine = {**{k: v for k, v in LICHTER.items() if int(k[1:]) < 6},
                 "LF": {"name": "Luftfeuchte", "type": "InfoOnlyAnalog", "uuidAction": "LF", "room": "r3", "cat": "c1",
                        "details": {"format": "%.0f%%"}, "states": {"value": "lf"}},
                 "IRC2": rc}
    struktur = anlage(bausteine)
    struktur["rooms"]["r3"] = {"name": "Abstellraum"}
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"default": {
        "title": "LoxPanel", "tabs": ["favoriten"], "ui": {"grid": "auto", "panes": {"favoriten": "header:LF,IRC2"}}}}}),
        encoding="utf-8")

    async def lauf():
        daten = await _front(monkeypatch)
        app = W.App({"host": "", "port": 80})
        app._apply_structure(struktur)
        app.panels = konfig.load_panels()
        app._front = app._front_payload(daten)
        app.states = {**{f"s{i}": 0 for i in range(6)}, "lf": 54, **werte}
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": groesse[0], "height": groesse[1]})
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?device=tablet")
                await pg.wait_for_function("typeof saverOn === 'function'")
                await pg.wait_for_timeout(600)
                await pg.mouse.click(groesse[0] // 2, groesse[1] // 2)   # Uhr-Seite weg
                await pg.wait_for_function("document.querySelectorAll('#kopfzeile .kz-w').length === 2")
                res = await pg.evaluate("""() => ({
                    werte: [...document.querySelectorAll('#kopfzeile .kz-w')].map(c => [c.querySelector('.vl').textContent,
                             c.querySelector('.nm').textContent, !c.hidden]),
                    wetter: !!document.querySelector('#kopfzeile .kz-wx .t'),
                    text: !document.querySelector('#kopfzeile .kz-wx .m').hidden})""")
                assert res["werte"] == [["54 %", "Luftfeuchte", True], ["21,0°", "Abstellraum", True]], res
                assert res["wetter"] and res["text"] == wettertext, res
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
