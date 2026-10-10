"""Reiter einer Ansicht im Konfigurator (Konzept "Konfigurator neu ordnen",
Schritt 3), in Chromium: sechs Reiter (Allgemein, Inhalt, Seiten, Raster,
Aussehen, Verhalten), jedes Feld steht in genau einem. Widget, Kopfzeile und
Werteleiste einer Standard-Seite stehen unter Inhalt, die einer freien Seite
nur im Seiten-Editor, und dort folgt die Zeile der gewaehlten Seite. Die
Sprache steht unter Allgemein; die Vorgaben behalten sie unter Darstellung.
Der Config-Ordner ist umgeleitet (Fixture cfg_ordner)."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}},
             "T": {"name": "Außentemperatur", "type": "InfoOnlyAnalog", "uuidAction": "T", "room": "r1",
                   "cat": "c1", "states": {"value": "st"}}}
PANELS = {"panels": {"flur": {"title": "Flur", "tabs": ["favoriten", "auswahl"],
                              "pickTabs": [{"name": "Wohnen", "picks": ["L"]}]}}}
ROUTEN = [("POST", "/api/panels", W.api_save_panels), ("POST", "/api/theme", W.api_save_theme),
          ("GET", "/api/devices", W.api_devices_get)]
# Feld (Selektor in #pconfHost) -> Reiter, in dem es steht
FELDER = {
    "allgemein": ["#fTitle", "#fZiel", "#fLang", "#dupBtn", "#delBtn"],
    "inhalt": ["#tabMode", "#tabRoomSel", "#chips", "#rooms", "#cats", "#panePerTab"],
    "seiten": ["#seHost", "#sePaneBox"],
    "raster": ["#fLayout", "#fTileSize", "#fFill", "#fScale", "#fSplit", "#fPaneCols", "[data-ui='nudgeX']"],
    "aussehen": [".baseSw", "#fFontSel", "#fTextColor", "[data-ui='iconSize']", "#fTileLayout", "#tiles", "#ovPrev"],
    "verhalten": ["#svPaneBox", "[data-ui='dpmsOff']", "[data-ui='reloadHours']", "[data-ui='nightDim']",
                  "[data-ui='nightWake']", "[data-ui='pinMerken']"],
}
# Wo steht ein Selektor: Liste der Reiter-Kennungen aller Treffer
WO = """sel => [...document.querySelectorAll('#pconfHost ' + sel)]
          .map(e => (e.closest('section.spane') || {dataset: {}}).dataset.sub)"""


def _app(cfg_ordner):
    (cfg_ordner / "panels.json").write_text(json.dumps(PANELS), encoding="utf-8")
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"sl": 0, "st": 12.5}
    return app


async def _konfigurator(b, port, fehler):
    pg = await b.new_page(viewport={"width": 1400, "height": 1000}, locale="de-DE")
    pg.on("pageerror", lambda e: fehler.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{port}/config")
    await pg.wait_for_function(KONFIGURATOR_GELADEN)
    await pg.locator(".rub", has_text="Ansichten").click()
    await pg.locator("#plist .pitem", has_text="?panel=flur").click()
    return pg


def test_sechs_reiter_jedes_feld_einmal(cfg_ordner, tmp_path):
    async def lauf():
        app = _app(cfg_ordner)
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _konfigurator(b, port, fehler)
                reiter = await pg.eval_on_selector_all("#subtabs .stab", "l => l.map(b => [b.dataset.sub, b.textContent])")
                assert reiter == [["allgemein", "Allgemein"], ["inhalt", "Inhalt"], ["seiten", "Seiten"],
                                  ["raster", "Raster"], ["aussehen", "Aussehen"], ["verhalten", "Verhalten"]], reiter
                for sub, felder in FELDER.items():
                    for sel in felder:
                        wo = await pg.evaluate(WO, sel)
                        assert wo and set(wo) == {sub}, (sel, sub, wo)
                        if sel not in (".baseSw",):                      # Farbfelder gibt es mehrere
                            assert len(wo) == 1, (sel, wo)
                # Ein Reiter zeigt nur sich: Raster offen, Verhalten nicht
                await pg.locator(".stab[data-sub='raster']").click()
                assert await pg.locator("#fLayout").is_visible()
                assert not await pg.locator("[data-ui='dpmsOff']").is_visible()
                await pg.screenshot(path=str(tmp_path / "reiter_raster.png"))
                # Uebersicht fuehrt in jeden der sechs
                await pg.locator(".rub", has_text="Übersicht").click()
                ziele = await pg.eval_on_selector_all("#overviewHost .ovbox[data-goto^='pconf:']",
                                                      "l => l.map(b => b.dataset.goto.slice(6))")
                assert ziele == ["allgemein", "inhalt", "seiten", "raster", "aussehen", "verhalten"], ziele
                await pg.locator("#overviewHost .ovbox[data-goto='pconf:verhalten']").click()
                assert await pg.locator("[data-ui='dpmsOff']").is_visible()
                # Die Vorgaben behalten die Sprache unter Darstellung
                await pg.locator("#plist .pitem", has_text="Vorgaben").click()
                assert await pg.evaluate(WO, "#fLang") == ["appearance"]
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


def test_freie_seite_nur_im_seiten_editor(cfg_ordner):
    """Unter Inhalt steht nur die Standard-Seite (Favoriten). Die freie Seite
    stellt der Seiten-Editor in derselben Zeile ein: Widget samt Wahl,
    Werteleiste; die Flaeche zeigt es, die neue Seite bekommt ihre eigene Zeile."""
    async def lauf():
        app = _app(cfg_ordner)
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _konfigurator(b, port, fehler)
                await pg.locator(".stab[data-sub='inhalt']").click()
                assert await pg.eval_on_selector_all("#panePerTab select[data-pane]", "l => l.map(s => s.dataset.pane)") == ["favoriten"]

                await pg.locator(".stab[data-sub='seiten']").click()
                await pg.wait_for_selector("#seHost [data-se-flaeche]")
                zeile = pg.locator("#sePaneBox")
                assert await zeile.locator("select[data-pane]").evaluate_all("l => l.map(s => s.dataset.pane)") == ["auswahl"]
                assert await zeile.locator(".ccnm").first.text_content() == "Wohnen"
                await zeile.locator("select[data-pane='auswahl']").select_option("status")
                await zeile.locator(".pstat-add").select_option("T")
                await pg.wait_for_selector("#seHost .se-pane")
                await zeile.locator("input[data-leiste='auswahl']").check()
                ui = await pg.evaluate("PANELS.flur.ui")
                assert ui["panes"] == {"auswahl": "status:T"} and ui["valueBar"] == ["auswahl"], ui

                # Zweite Seite: die Zeile gehoert jetzt ihr
                await pg.locator("#seHost [data-se-neu]").click()
                assert await zeile.locator("select[data-pane]").evaluate_all("l => l.map(s => s.dataset.pane)") == ["auswahl2"]
                assert await zeile.locator("select[data-pane='auswahl2']").input_value() == ""

                await pg.locator("#saveBtn").click()
                await pg.wait_for_function("document.querySelector('#offenTxt').textContent === 'Alles gespeichert'")
                flur = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]["flur"]
                assert flur["ui"]["panes"] == {"auswahl": "status:T"} and flur["ui"]["valueBar"] == ["auswahl"], flur
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
