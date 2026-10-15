"""Freie Seiten loeschen im Konfigurator in Chromium: Die Seiten heissen nach
ihrer Stelle (auswahl, auswahl2 ...). Faellt eine weg, ruecken die folgenden
nach - und mit ihnen alles, was an ihrer Kennung haengt: der Eintrag in der
Leiste, das Widget (ui.panes) und die Werteleiste (ui.valueBar). Was der
geloeschten Seite gehoerte, geht mit ihr; eine spaeter neu angelegte Seite
erbt nichts. Config-Ordner: Fixture cfg_ordner."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {u: {"name": n, "type": "Switch", "uuidAction": u, "room": "r1", "cat": "c1", "states": {"active": "s" + u}}
             for u, n in (("A", "Licht Wohnen"), ("B", "Licht Küche"), ("C", "Licht Bad"))}
ROUTEN = [("POST", "/api/panels", W.api_save_panels), ("POST", "/api/theme", W.api_save_theme)]
SEITEN = [{"name": "Wohnen", "picks": ["A"]}, {"name": "Küche", "picks": ["B"]}, {"name": "Bad", "picks": ["C"]}]
DREI = {"title": "Drei", "tabs": ["auswahl", "auswahl2", "auswahl3"], "pickTabs": SEITEN,
        "ui": {"panes": {"auswahl": "weather", "auswahl2": "calendar", "auswahl3": "header"},
               "valueBar": ["auswahl2", "auswahl3"]}}
# klassische Leiste: Standard-Tabs und einzelne freie Seiten gemischt
KLASSISCH = {"title": "Klassisch", "tabs": ["favoriten", "auswahl", "auswahl2"], "pickTabs": SEITEN[:2],
             "ui": {"panes": {"favoriten": "header", "auswahl": "weather", "auswahl2": "calendar"},
                    "valueBar": ["auswahl2"]}}


def _datei(cfg_ordner):
    return json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]


def _lauf(cfg_ordner, schritte):
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"drei": DREI, "klassisch": KLASSISCH}}),
                                            encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"s" + u: 0 for u in BAUSTEINE}
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await schritte(pg)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


async def _speichern_und_neu_laden(pg):
    await pg.locator("#saveBtn").click()
    await pg.wait_for_function("document.querySelector('#offenTxt').textContent === 'Alles gespeichert'")
    await pg.reload()
    await pg.wait_for_function(KONFIGURATOR_GELADEN)


async def _seite_loeschen(pg, ansicht, i):
    await pg.locator(".rub", has_text="Ansichten").click()
    await pg.locator("#plist .pitem", has_text=f"?panel={ansicht}").click()
    await pg.evaluate(f"pickDelTab(PANELS[{json.dumps(ansicht)}], {i})")


@pytest.mark.parametrize("weg, seiten, panes, leiste", [
    (0, ["Küche", "Bad"], {"auswahl": "calendar", "auswahl2": "header"}, ["auswahl", "auswahl2"]),
    (1, ["Wohnen", "Bad"], {"auswahl": "weather", "auswahl2": "header"}, ["auswahl2"]),
], ids=["erste", "mittlere"])
def test_seite_loeschen_nimmt_widgets_und_werteleiste_mit(cfg_ordner, weg, seiten, panes, leiste):
    async def schritte(pg):
        await _seite_loeschen(pg, "drei", weg)
        await _speichern_und_neu_laden(pg)
        p = _datei(cfg_ordner)["drei"]
        assert [s["name"] for s in p["pickTabs"]] == seiten
        assert p["tabs"] == ["auswahl", "auswahl2"]
        assert p["ui"]["panes"] == panes and p["ui"]["valueBar"] == leiste, p["ui"]
        assert await pg.evaluate("PANELS.drei.ui.panes") == panes

        # eine neue Seite erbt nichts von der geloeschten
        await pg.locator("#plist .pitem", has_text="?panel=drei").click()
        await pg.evaluate("pickAddTab(PANELS.drei)")
        await _speichern_und_neu_laden(pg)
        p = _datei(cfg_ordner)["drei"]
        assert p["tabs"] == ["auswahl", "auswahl2", "auswahl3"]
        assert "auswahl3" not in p["ui"]["panes"] and "auswahl3" not in p["ui"]["valueBar"], p["ui"]
    _lauf(cfg_ordner, schritte)


def test_klassische_leiste_mit_einzelnen_seiten(cfg_ordner):
    async def schritte(pg):
        await _seite_loeschen(pg, "klassisch", 0)
        await _speichern_und_neu_laden(pg)
        p = _datei(cfg_ordner)["klassisch"]
        assert p["tabs"] == ["favoriten", "auswahl"]
        assert [s["name"] for s in p["pickTabs"]] == ["Küche"]
        assert p["ui"]["panes"] == {"favoriten": "header", "auswahl": "calendar"}
        assert p["ui"]["valueBar"] == ["auswahl"]
    _lauf(cfg_ordner, schritte)
