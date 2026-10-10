"""Rubrik Vorgaben im Konfigurator (Konzept "Konfigurator neu ordnen", Schritt 5),
in Chromium: Die Vorgaben stehen nicht mehr in der Liste der Ansichten, sondern
als eigene Rubrik mit Darstellung, Kategorie-Farben und Verhalten. Unter Verhalten
steht der Nacht-Ausloeser (vorher unter Geraete) und die Abdunkelung fuer alle
Ansichten, dazu Display aus und Auto-Neustart; die
Ansicht zeigt unter Verhalten grau, was sie davon erbt. Ein Rubrikwechsel verliert
nichts und fuehrt zur vorher gewaehlten Ansicht zurueck. Der Config-Ordner ist
umgeleitet (Fixture cfg_ordner)."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}},
             "N": {"name": "Nachtschalter", "type": "Switch", "uuidAction": "N", "room": "r2", "cat": "c1",
                   "states": {"active": "sn"}}}
PANELS = {"panels": {"flur": {"title": "Flur", "tabs": ["favoriten"]},
                     "kueche": {"title": "Küche", "tabs": ["favoriten"], "ui": {"nightDim": 10}}}}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/panels", W.api_save_panels),
          ("POST", "/api/theme", W.api_save_theme), ("POST", "/api/settings/night", W.api_settings_night)]
OFFEN = "document.querySelector('#offenTxt').textContent"


def test_vorgaben_als_rubrik(cfg_ordner, tmp_path):
    async def lauf():
        (cfg_ordner / "panels.json").write_text(json.dumps(PANELS), encoding="utf-8")
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"sl": 0, "sn": 0}
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                rubriken = await pg.eval_on_selector_all(".rub", "l => l.map(b => b.dataset.rub)")
                assert rubriken == ["overview", "assistant", "pconf", "vorgaben", "displays", "settings"], rubriken
                eintraege = await pg.eval_on_selector_all("#plist .pitem .pid", "l => l.map(e => e.textContent)")
                assert sorted(eintraege) == ["?panel=default", "?panel=flur", "?panel=kueche"], "Vorgaben nicht in der Liste"

                await pg.locator("#plist .pitem", has_text="?panel=flur").click()
                await pg.locator(".rub", has_text="Vorgaben").click()
                reiter = await pg.eval_on_selector_all("#subtabs .stab", "l => l.map(b => [b.dataset.sub, b.textContent])")
                assert reiter == [["appearance", "Darstellung"], ["catcolors", "Kategorie-Farben"], ["verhalten", "Verhalten"]], reiter
                assert await pg.locator("#plist .pitem.active").count() == 0, "keine Ansicht gewaehlt"
                assert await pg.locator("#fBaseCustom").is_visible(), "Darstellung zuerst"

                # Verhalten: Nacht-Ausloeser und Abdunkelung fuer alle Ansichten
                await pg.locator(".stab[data-sub='verhalten']").click()
                sel = pg.locator("#nt_control")
                await pg.wait_for_function("document.querySelectorAll('#nt_control option').length > 1")
                assert await sel.input_value() == ""
                dim = pg.locator("#pconfHost [data-ui='nightDim']")
                assert await dim.get_attribute("placeholder") == "0 = aus", "Standard des Servers (NACHT_STANDARD)"
                assert not await pg.locator("#nightWakeField").is_visible(), "ohne Abdunkelung kein Aufhellen"
                await sel.select_option("N")
                assert await pg.evaluate(OFFEN) == "Nicht gespeichert: Nachtmodus"
                await dim.fill("40")
                assert await pg.locator("#nightWakeField").is_visible()
                assert await pg.locator("#pconfHost [data-ui='nightWake']").get_attribute("placeholder") == \
                    str(W.NACHT_STANDARD["nightWake"])
                assert await pg.evaluate(OFFEN) == "Nicht gespeichert: Vorgaben, Nachtmodus"
                await pg.screenshot(path=str(tmp_path / "vorgaben_nacht.png"), full_page=True)

                # Unter Geraete steht der Ausloeser nicht mehr; der Wechsel verliert nichts
                await pg.locator(".rub", has_text="Geräte").click()
                assert await pg.locator("#displaysHost #nt_control").count() == 0
                await pg.locator(".rub", has_text="Vorgaben").click()
                assert await pg.locator(".stab.active").get_attribute("data-sub") == "verhalten", "Reiter gemerkt"
                assert await sel.input_value() == "N" and await dim.input_value() == "40"

                # Zurueck zur Ansicht Flur: sie erbt die Abdunkelung und zeigt sie grau
                await pg.locator(".rub", has_text="Ansichten").click()
                assert "?panel=flur" in await pg.locator("#plist .pitem.active").text_content()
                await pg.locator(".stab[data-sub='verhalten']").click()
                assert await dim.input_value() == "" and await dim.get_attribute("placeholder") == "40"
                assert await pg.locator("#nightWakeField").is_visible(), "geerbte Abdunkelung zaehlt"

                await pg.locator("#saveBtn").click()
                await pg.wait_for_function(OFFEN + " === 'Alles gespeichert'")
                theme = json.loads((cfg_ordner / "theme.json").read_text(encoding="utf-8"))
                assert theme["ui"]["nightDim"] == 40, theme
                assert W._load_cfg()["night"]["control"] == "N"
                assert app.panel_night("flur")["dim"] == 40, "Vorgabe gilt"
                assert app.panel_night("kueche")["dim"] == 10, "die Ansicht ueberschreibt sie"

                # Die Uebersicht fuehrt direkt zu Vorgaben -> Verhalten
                await pg.locator(".rub", has_text="Übersicht").click()
                await pg.locator('#overviewHost .ovbox[data-goto="vorgaben:verhalten"]').click()
                assert await sel.is_visible() and await sel.input_value() == "N"
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())



def test_rubriken_ohne_waagerechten_ueberlauf(cfg_ordner):
    """Sechs Rubriken passen bei 1024 px neben die Seitenleiste; schmaler brechen
    sie um, statt die Seite waagerecht scrollen zu lassen."""
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"sl": 0, "sn": 0}
        runner, port, bc = await visu_starten(app, ROUTEN)
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                for breite, zeilen in ((1280, 1), (1024, 1), (800, None), (390, None)):
                    pg = await b.new_page(viewport={"width": breite, "height": 800}, locale="de-DE")
                    await pg.goto(f"http://127.0.0.1:{port}/config")
                    await pg.wait_for_function(KONFIGURATOR_GELADEN)
                    m = await pg.evaluate("""(() => { const r = document.querySelector('.rubrics');
                        const tops = new Set([...r.querySelectorAll('.rub')].map(b => b.offsetTop));
                        return {seite: document.documentElement.scrollWidth, fenster: innerWidth,
                                leiste: r.scrollWidth - r.clientWidth, zeilen: tops.size}; })()""")
                    assert m["seite"] <= m["fenster"] and m["leiste"] == 0, (breite, m)
                    if zeilen:
                        assert m["zeilen"] == zeilen, (breite, m)
                    await pg.close()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
    asyncio.run(lauf())
