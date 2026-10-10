"""Vorschau am Geraet (Punkt 12) in Chromium: Das "Geraet" ist eine zweite Seite
mit ?device=wand, die Visu zeigt. Der Konfigurator schaltet sie auf einen
Entwurf um - aus dem Panel-Editor ("Am Geraet ansehen") und aus dem letzten
Schritt des Assistenten, wo das Panel noch gar nicht existiert. Das Geraet zeigt
genau die Kacheln des Seiten-Editors, zieht Aenderungen nach und kehrt zur vorigen
Ansicht zurueck, wenn die Vorschau beendet wird; Speichern beendet sie ebenfalls."""
import asyncio

import pytest

from lox import KONFIGURATOR_GELADEN, W, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser


def _schalter(u, name, raum):
    return {"name": name, "type": "Switch", "uuidAction": u, "room": raum, "cat": "c1", "states": {"active": "s" + u}}


STRUKTUR = {
    "rooms": {"r1": {"name": "Wohnzimmer"}, "r2": {"name": "Küche"}},
    "cats": {"c1": {"name": "Beleuchtung"}},
    "controls": {u: _schalter(u, n, r) for u, n, r in (
        ("A", "Deckenlicht", "r1"), ("B", "Stehlampe", "r1"), ("C", "Dimmer Küche", "r2"), ("D", "Leselampe", "r1"))},
}
ROUTEN = [("POST", "/api/panels", W.api_save_panels), ("POST", "/api/entwurf", W.api_entwurf),
          ("POST", "/api/device/switch", W.api_device_switch), ("POST", "/api/vorschau/beenden", W.api_vorschau_beenden),
          ("GET", "/api/devices", W.api_devices_get)]
VISU = "() => [...document.querySelectorAll('#grid .tile[data-id]')].map(n => n.dataset.id)"
EDITOR = "() => document.querySelector('#seHost')._seLage.a.raster.map(e => e.id)"
MARKE = "() => { const m = document.getElementById('entwurfMarke'); return m.classList.contains('hidden') ? '' : m.textContent; }"


async def _bis(pg, ausdruck, erwartet, was, sekunden=10):
    """Warten, bis der Ausdruck `erwartet` liefert; waehrend einer Navigation gibt es keinen Kontext."""
    letzter = None
    for _ in range(int(sekunden * 10)):
        try:
            letzter = await pg.evaluate(ausdruck)
        except Exception as fehler:   # Playwright: "Execution context was destroyed"
            letzter = fehler
        else:
            if letzter == erwartet:
                return
        await asyncio.sleep(0.1)
    assert letzter == erwartet, was


def _app():
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    app.states = {"s" + u: 0 for u in "ABCD"}
    app.panels = W.App._sanitize_panels({
        "a": {"title": "Vorher", "tabs": ["auswahl"], "pickTabs": [{"name": "V", "picks": ["D"]}]},
        "flur": {"title": "Flur", "tabs": ["auswahl"], "ui": {"grid": "auto"},
                 "pickTabs": [{"name": "Wohnen", "picks": ["A", "C"], "byRoom": False}]}})
    return app


async def _geraet(b, port):
    """Das 'Wandpanel': eine Visu mit Geraetekennung, zeigt das Profil a."""
    wand = await b.new_page(viewport={"width": 893, "height": 533})
    await wand.goto(f"http://127.0.0.1:{port}/?panel=a&device=wand")
    await wand.wait_for_selector("#grid .tile[data-id]", state="attached")
    if await wand.locator("#saver:not(.hidden)").count():
        await wand.click("#saver")
    return wand


async def _konfigurator(b, port):
    pg = await b.new_page(viewport={"width": 1400, "height": 1000}, locale="de-DE")
    pg._fehler = []
    pg.on("pageerror", lambda e: pg._fehler.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{port}/config")
    await pg.wait_for_function(KONFIGURATOR_GELADEN)
    # die Geraeteliste kennt das Geraet samt gemeldeter Groesse erst nach einer Abfrage danach
    # (vorher ist screen ein leeres Objekt)
    await pg.wait_for_function("DEVICE_CONN['wand'] > 0 && DEVICE_SCREENS['wand'] && DEVICE_SCREENS['wand'].vw "
                               "&& KNOWN_NAMES.includes('wand')")
    return pg


def _lauf(schritte):
    async def lauf():
        app = _app()
        runner, port, bc = await visu_starten(app, ROUTEN)
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                ergebnis = await schritte(app, b, port)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        return ergebnis
    return asyncio.run(lauf())


def test_editor_schaltet_das_geraet_auf_den_entwurf_und_zurueck(cfg_ordner):
    async def schritte(app, b, port):
        wand = await _geraet(b, port)
        fehler = []
        wand.on("pageerror", lambda e: fehler.append(str(e)))
        assert await wand.evaluate(VISU) == ["D"]
        pg = await _konfigurator(b, port)
        await pg.locator("#plist .pitem", has_text="?panel=flur").click()
        await pg.locator(".stab[data-sub='seiten']").click()
        await pg.wait_for_selector("#seHost [data-se-flaeche]")
        opts = await pg.eval_on_selector_all("#seHost [data-se-geraet] option", "l => l.map(o => o.textContent)")
        await pg.select_option("#seHost [data-se-geraet]", str(next(i for i, o in enumerate(opts) if o.startswith("wand ·"))))
        assert await pg.locator("#vorGerBtn").text_content() == "Am Gerät ansehen"

        # ungespeicherte Aenderung, dann aufs Geraet
        await pg.locator("#seHost .se-p", has_text="Stehlampe").click()
        editor = await pg.evaluate(EDITOR)
        assert editor == ["A", "C", "B"], editor
        await pg.locator("#vorGerBtn").click()
        await _bis(wand, "location.search.includes('entwurf=')", True, "das Geraet schaltet auf den Entwurf")
        await wand.wait_for_selector("#grid .tile[data-id]", state="attached")
        assert "panel=flur" in await wand.evaluate("location.search")
        await _bis(wand, VISU, editor, "das Geraet zeigt, was der Editor zeigt")
        assert await wand.evaluate(MARKE) == "Entwurf – nicht gespeichert"
        assert not (cfg_ordner / "panels.json").exists(), "nichts gespeichert"
        assert await pg.locator("#vorGerBtn").text_content() == "Am Gerät beenden"
        assert app.vorschau_geraet["wand"]["zurueck"] == "a"

        # weiter aendern: das Geraet zieht nach
        await pg.locator("#seHost .se-p", has_text="Leselampe").click()
        neu = await pg.evaluate(EDITOR)
        assert neu == ["A", "C", "B", "D"], neu
        await _bis(wand, VISU, neu, "die Vorschau am Geraet zieht nach")

        # beenden: das Geraet kehrt zu a zurueck
        await pg.locator("#vorGerBtn").click()
        await _bis(wand, "location.search", "?panel=a&device=wand", "zurueck zur vorigen Ansicht")
        await _bis(wand, VISU, ["D"], "und zeigt wieder das Profil a")
        assert await wand.evaluate(MARKE) == ""
        assert await pg.locator("#vorGerBtn").text_content() == "Am Gerät ansehen"
        assert app.vorschau_geraet == {}
        assert not fehler and not pg._fehler, (fehler, pg._fehler)
    _lauf(schritte)


def test_ohne_verbundenes_geraet_sagt_der_knopf_warum(cfg_ordner):
    async def schritte(app, b, port):
        wand = await _geraet(b, port)
        pg = await _konfigurator(b, port)
        await pg.locator("#plist .pitem", has_text="?panel=flur").click()
        await pg.locator(".stab[data-sub='seiten']").click()
        await pg.wait_for_selector("#seHost [data-se-flaeche]")
        # ein Katalog-Eintrag ist kein Geraet: die Vorschau braucht ein verbundenes
        opts = await pg.eval_on_selector_all("#seHost [data-se-geraet] option", "l => l.map(o => o.textContent)")
        await pg.select_option("#seHost [data-se-geraet]", str(next(i for i, o in enumerate(opts) if o.startswith("iPad quer ·"))))
        await pg.locator("#vorGerBtn").click()
        await pg.wait_for_function("document.querySelector('#toast').textContent.includes('Gerät wählen')")
        # ein Geraet ohne Visu (nur dem Server bekannt): auch das nennt den Grund
        await pg.evaluate("DEVICE_CONN['wand'] = 0")
        await pg.select_option("#seHost [data-se-geraet]", str(next(i for i, o in enumerate(opts) if o.startswith("wand ·"))))
        await pg.locator("#vorGerBtn").click()
        await pg.wait_for_function("document.querySelector('#toast').textContent.includes('keine verbundene Visu')")
        assert app.vorschau_geraet == {} and "entwurf" not in await wand.evaluate("location.search")
    _lauf(schritte)


def test_assistent_zeigt_ein_panel_das_es_noch_nicht_gibt(cfg_ordner):
    """Letzter Schritt des Assistenten: das Panel ist noch nicht angelegt, die Vorschau
    am Geraet zeigt es trotzdem. Schliesst man den Assistenten ohne Anlegen, kehrt das
    Geraet gleich zurueck; Speichern beendet die Vorschau ebenfalls."""
    async def schritte(app, b, port):
        wand = await _geraet(b, port)
        pg = await _konfigurator(b, port)
        await pg.evaluate("""() => { wzOpen(); wzGroesseSetzen({quelle: 'geraet', name: 'wand', vw: 893, vh: 533});
            WZ.content = 'classic'; WZ.title = 'Neu'; WZ.id = 'neu'; wzInitSetup();
            WZ.step = wzFlow().indexOf('pruefen'); wzRender(); }""")
        assert await pg.locator("#wzVorschau").is_enabled()
        await pg.locator("#wzVorschau").click()
        await _bis(wand, "location.search.includes('panel=neu')", True, "das Geraet zeigt das neue Panel")
        await _bis(wand, MARKE, "Entwurf – nicht gespeichert", "mit Etikett")
        assert "neu" not in app.panels and not (cfg_ordner / "panels.json").exists()
        assert await pg.locator("#wzVorschauEnde").count() == 1

        # Assistent zu, nichts angelegt: zurueck zur vorigen Ansicht
        await pg.evaluate("wzClose()")
        await _bis(wand, "location.search", "?panel=a&device=wand", "das Geraet kehrt zurueck")
        assert app.vorschau_geraet == {}

        # nochmal, diesmal anlegen und speichern: das Geraet zeigt danach das gespeicherte Panel
        await pg.evaluate("""() => { wzOpen(); wzGroesseSetzen({quelle: 'geraet', name: 'wand', vw: 893, vh: 533});
            WZ.content = 'classic'; WZ.title = 'Neu'; WZ.id = 'neu'; WZ.umschalten = false; wzInitSetup();
            WZ.step = wzFlow().indexOf('pruefen'); wzRender(); }""")
        await pg.locator("#wzVorschau").click()
        await _bis(wand, "location.search.includes('panel=neu')", True, "das Geraet zeigt es wieder")
        await pg.evaluate("wzBuild()")
        await pg.locator("#saveBtn").click()
        await _bis(wand, "location.search", "?panel=neu&device=wand", "gespeichert: dasselbe Panel ohne Entwurf")
        assert "neu" in app.panels and app.vorschau_geraet == {}
        assert not pg._fehler, pg._fehler
    _lauf(schritte)
