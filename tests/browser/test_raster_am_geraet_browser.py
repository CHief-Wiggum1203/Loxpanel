"""Raster am Geraet (Einrichtung neu) in Chromium: Visu und Konfigurator rechnen
das Raster mit derselben raster.js. Die Masse, mit denen der Seiten-Editor ein
Geraet vorrechnet (LoxRaster.VISU_MASSE), sind die, die die Visu misst; fuer
jedes Geraet des Katalogs zeigt der Editor unter Ansichten -> Seiten das
Raster, das die Visu auf diesem Geraet baut. Dazu die Zielkachel je Geraet
(Geraetekarte, Zeile Technik), die beim Speichern bleibt - der Fehler, den die
Vorrechnung des frueheren Assistenten aufgedeckt hatte."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, karte_auf, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

KACHELN = {f"S{i}": {"name": f"Licht {i}", "type": "Switch", "uuidAction": f"S{i}", "room": "r2", "cat": "c1",
                     "isFavorite": True, "states": {"active": f"s{i}"}} for i in range(12)}
STATES = {f"s{i}": 0 for i in range(12)}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/devices", W.api_save_devices),
          ("POST", "/api/panels", W.api_save_panels), ("POST", "/api/theme", W.api_save_theme)]
# Standardgeraete der Messreihe, wie sie der Katalog des Servers nennt
GERAETE = {"Galaxy Tab A9 quer": (893, 533), "Galaxy Tab A9 hochkant": (533, 893), "10″-Tablet quer": (1280, 800),
           "iPad quer": (1024, 768), "4″-Wandpanel": (480, 480)}
# Die Profile, je eine freie Seite mit allen Kacheln: automatisch ohne und mit
# Widget, fest 3 x 3 mit Split und 2 x 2 ohne
PROFILE = {"auto1": {"grid": "auto", "split": False},
           "auto2": {"grid": "auto", "panes": {"auswahl": "weather"}},
           "fest33": {"cols": 3, "rows": 3},
           "fest22": {"cols": 2, "rows": 2, "split": False}}
MESSEN = """() => { const g = document.getElementById('grid'), cs = getComputedStyle(g);
  return {raster: [gridCols, gridRows], kachel: Math.round(g.querySelector('.tile[data-id]').getBoundingClientRect().width),
          masse: {gap: parseFloat(cs.getPropertyValue('--gap')), pad: parseFloat(cs.getPropertyValue('--pad')),
                  punkteH: parseFloat(cs.getPropertyValue('--punkte-h')), hinweisH: parseFloat(cs.getPropertyValue('--hinweis-h')),
                  tabsH: document.getElementById('tabs').offsetHeight},
          vorgabe: LoxRaster.VISU_MASSE}; }"""
# Das Raster, das der Seiten-Editor fuer das gewaehlte Vorschaugeraet gezeichnet hat
EDITOR = """() => { const r = document.querySelector('#seHost')._seLage.r;
  return {raster: [r.cols, r.rows], kachel: Math.round(r.kb || 0), auto: !!r.auto, widget: !!r.widget}; }"""


def _app(cfg_ordner, panels, devices=None):
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": panels, **({"devices": devices} if devices else {})}),
                                            encoding="utf-8")
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(KACHELN))
    app.states = dict(STATES)
    app.panels = W.load_panels()
    return app


async def _vorschaugeraet(pg, name):
    opts = await pg.eval_on_selector_all("#seHost [data-se-geraet] option", "l => l.map(o => o.textContent)")
    await pg.select_option("#seHost [data-se-geraet]", str(next(i for i, o in enumerate(opts) if o.startswith(name + " ·"))))


def test_seiten_editor_rechnet_wie_die_visu(cfg_ordner, monkeypatch):
    """Ohne Wachsen und Schrumpfen (KACHEL_WACHSEN 1) baut die Visu auf jedem
    Standardgeraet und in jedem Profil genau das Raster, das der Seiten-Editor
    fuer dieses Geraet zeichnet; im automatischen Raster auch die Kachelbreite.
    Die Masse der Visu sind die von raster.js."""
    monkeypatch.setattr(W, "KACHEL_WACHSEN", 1)
    app = _app(cfg_ordner, {pid: {"title": pid, "tabs": ["auswahl"], "pickTabs": [{"name": "Alle", "picks": list(KACHELN)}],
                                  "ui": ui} for pid, ui in PROFILE.items()})

    async def lauf():
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler, ungleich = [], []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                konf = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                konf.on("pageerror", lambda e: fehler.append(str(e)))
                await konf.goto(f"http://127.0.0.1:{port}/config")
                await konf.wait_for_function(KONFIGURATOR_GELADEN)
                visus = {}
                for geraet, (w, h) in GERAETE.items():
                    visus[geraet] = await b.new_page(viewport={"width": w, "height": h})
                    visus[geraet].on("pageerror", lambda e: fehler.append(str(e)))
                for pid in PROFILE:
                    await konf.locator("#plist .pitem", has_text=f"?panel={pid}").click()
                    await konf.locator(".stab[data-sub='seiten']").click()
                    await konf.wait_for_selector("#seHost [data-se-flaeche]")
                    for geraet, v in visus.items():
                        await v.goto(f"http://127.0.0.1:{port}/?panel={pid}")
                        await v.wait_for_selector("#grid .tile[data-id]", state="attached")
                        if await v.locator("#saver:not(.hidden)").count():
                            await v.click("#saver")
                        await v.wait_for_timeout(300)
                        ist = await v.evaluate(MESSEN)
                        assert ist["masse"] == ist["vorgabe"], (geraet, pid, ist)
                        await _vorschaugeraet(konf, geraet)
                        vor = await konf.evaluate(EDITOR)
                        # Kachelbreite: neben einem Widget zieht dessen Trennlinie 1 bis 2 px ab,
                        # verglichen wird sie ohne Widget
                        if ist["raster"] != vor["raster"] or (vor["auto"] and not vor["widget"] and abs(ist["kachel"] - vor["kachel"]) > 1):
                            ungleich.append((geraet, pid, ist["raster"], ist["kachel"], vor))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        assert not ungleich, ungleich
    asyncio.run(lauf())


def test_zielkachel_am_geraet_bleibt_beim_speichern(cfg_ordner):
    """Geraetekarte, Zeile Technik, Feld Zielkachel: Speichern behaelt sie (vorher
    fiel sie aus der Nutzlast und ein Geraet nur mit Zielkachel verschwand), ein
    neuer Wert landet in der Datei."""
    app = _app(cfg_ordner, {"p": {"title": "P", "tabs": ["favoriten"]}},
               {"flur": {"auto": True, "modes": {}, "tileTarget": 200}})

    async def lauf():
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator(".rub", has_text="Geräte").click()
                await karte_auf(pg, "flur")
                feld = pg.locator('#geraete .dev[data-name="flur"] .dt_ziel')
                assert await feld.input_value() == "200"

                async def speichern():
                    # Speichern ohne Aenderung gibt die Leiste nicht frei: den Bereich offen melden
                    await pg.evaluate("bereichOffen('geraete')")
                    async with pg.expect_response(lambda r: r.url.endswith("/api/devices") and r.request.method == "POST") as a:
                        await pg.locator("#saveBtn").click()
                    assert (await (await a.value).json())["ok"]
                    return json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8")).get("devices", {})
                assert (await speichern()).get("flur", {}).get("tileTarget") == 200, "unveraendert gespeichert: bleibt"
                await feld.fill("250")
                assert (await speichern())["flur"]["tileTarget"] == 250
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
