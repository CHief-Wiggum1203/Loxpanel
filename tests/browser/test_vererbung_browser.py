"""Vererbung sichtbar im Konfigurator (Konzept "Konfigurator neu ordnen", Schritt 6),
in Chromium: Jedes Feld mit Vorgabe oder Geraetewert nennt, was gilt und woher
(Geraet vor Ansicht vor Vorgaben vor Standard, wie effective_scale() und
resolve_profile() im Server). Ein gesetztes Feld hat "× zurücksetzen", danach gilt
wieder der geerbte Wert; die Vorgaben zaehlen, fuer wie viele Ansichten ein Wert
gilt; die Ansicht nennt Geraete, die sie ueberstimmen, und die Geraetekarte, was
aus der Ansicht kommt. Der Config-Ordner ist umgeleitet (Fixture cfg_ordner)."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, karte_auf, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}}}
PANELS = {"panels": {"flur": {"title": "Flur", "tabs": ["favoriten"], "device": {"name": "wand"}},
                     "kueche": {"title": "Küche", "tabs": ["favoriten"], "ui": {"nameSize": 22, "scale": 1.1}}},
          "devices": {"wand": {"auto": True, "modes": {}, "scale": 1.25}}}
THEME = {"ui": {"nameSize": 19, "scale": "auto"}}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/devices", W.api_save_devices),
          ("POST", "/api/panels", W.api_save_panels), ("POST", "/api/theme", W.api_save_theme)]
OFFEN = "document.querySelector('#offenTxt').textContent"


def _zeile(pg, k):
    return pg.locator(f"#pconfHost .erbt[data-erbt='{k}']")


def test_herkunft_und_zuruecksetzen(cfg_ordner, tmp_path):
    async def lauf():
        (cfg_ordner / "panels.json").write_text(json.dumps(PANELS), encoding="utf-8")
        (cfg_ordner / "theme.json").write_text(json.dumps(THEME), encoding="utf-8")
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"sl": 0}
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        icon_std = W.GROESSEN_STANDARD["neu"]["iconSize"]
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)

                # Vorgaben: was gilt ohne Eintrag, fuer wie viele Ansichten
                await pg.locator(".rub", has_text="Vorgaben").click()
                name = _zeile(pg, "nameSize")
                assert await name.locator("[data-erbt-zurueck]").count() == 1, "gesetzt: zuruecksetzbar"
                assert await name.locator("span").text_content() == \
                    "gilt für 2 von 3 Ansichten · eigener Wert in Küche"
                assert await _zeile(pg, "iconSize").text_content() == \
                    f"{icon_std} px · Standard · gilt für 3 von 3 Ansichten"
                assert (await _zeile(pg, "font").text_content()).startswith("Standard · gilt"), "nicht doppelt"
                await pg.screenshot(path=str(tmp_path / "vorgaben_herkunft.png"), full_page=True)

                # Ansicht Flur: leer = Vorgabe oder Standard; das Geraet ueberstimmt die Skalierung
                await pg.locator("#plist .pitem", has_text="?panel=flur").click()
                await pg.locator(".stab[data-sub='aussehen']").click()
                assert await _zeile(pg, "nameSize").text_content() == "19 px · aus den Vorgaben"
                assert await _zeile(pg, "iconSize").text_content() == f"{icon_std} px · Standard"
                await pg.locator(".stab[data-sub='raster']").click()
                assert await _zeile(pg, "scale").text_content() == \
                    "Automatisch · aus den Vorgaben · am Gerät wand: 125 %"

                # Ansicht Kueche: gesetzt -> zuruecksetzen, dann gilt die Vorgabe
                await pg.locator("#plist .pitem", has_text="?panel=kueche").click()
                await pg.locator(".stab[data-sub='aussehen']").click()
                knopf = _zeile(pg, "nameSize").locator("[data-erbt-zurueck]")
                assert await knopf.get_attribute("title") == "Dann gilt: 19 px · aus den Vorgaben"
                await knopf.click()
                feld = pg.locator("#pconfHost input[data-ui='nameSize']")
                assert await feld.input_value() == "" and await feld.get_attribute("placeholder") == "19"
                assert await _zeile(pg, "nameSize").text_content() == "19 px · aus den Vorgaben"
                assert await pg.evaluate(OFFEN) == "Nicht gespeichert: Ansicht Küche"
                assert await pg.locator(".stab.active").get_attribute("data-sub") == "aussehen", "Reiter bleibt"
                await pg.locator(".rub", has_text="Vorgaben").click()
                assert await _zeile(pg, "nameSize").locator("span").text_content() == "gilt für 3 von 3 Ansichten"

                # Geraetekarte: eigener Wert zuruecksetzbar, leer gilt die Ansicht
                await pg.locator(".rub", has_text="Geräte").click()
                await karte_auf(pg, "wand")
                skal = pg.locator('#geraete .dev[data-name="wand"] .erbt[data-gerbt="scale"]')
                ziel = pg.locator('#geraete .dev[data-name="wand"] .erbt[data-gerbt="tileTarget"]')
                knopf = skal.locator("[data-gerbt-zurueck]")
                assert await knopf.get_attribute("title") == \
                    "Dann gilt: Automatisch · aus den Vorgaben (Ansicht Flur)"
                assert await ziel.text_content() == "wirkt nur bei Kachel-Layout „Automatisch“ (Ansicht Flur)"
                await knopf.click()
                assert await pg.locator('#geraete .dev[data-name="wand"] .ds_scale').input_value() == ""
                assert await skal.text_content() == "Automatisch · aus den Vorgaben (Ansicht Flur)"
                assert await pg.evaluate(OFFEN) == "Nicht gespeichert: Ansicht Küche, Geräte"
                await pg.screenshot(path=str(tmp_path / "geraet_herkunft.png"), full_page=True)

                # Die Ansicht nennt das Geraet nicht mehr
                await pg.locator("#plist .pitem", has_text="?panel=flur").click()
                await pg.locator(".stab[data-sub='raster']").click()
                assert await _zeile(pg, "scale").text_content() == "Automatisch · aus den Vorgaben"

                await pg.locator("#saveBtn").click()
                await pg.wait_for_function(OFFEN + " === 'Alles gespeichert'")
                gespeichert = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))
                assert "nameSize" not in gespeichert["panels"]["kueche"].get("ui", {}), gespeichert
                assert "scale" not in gespeichert.get("devices", {}).get("wand", {}), gespeichert
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
