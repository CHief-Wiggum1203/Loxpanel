"""Rubrik Geraete im Konfigurator (Konzept "Konfigurator neu ordnen", Schritt 4),
in Chromium: eine Karte je Geraet. Der Kopf (Zustand, Ansicht, Steuerung) folgt
der Abfrage der Geraeteliste, aufgeklappt stehen die Einstellungen in vier
Teilen; eine offene Karte und eine Eingabe darin ueberstehen jede Abfrage. Die
Wahl der Ansicht im Kopf schaltet live und ist keine offene Aenderung. "Neues
Gerät einrichten" und "Erprobte Hardware" stehen unter Geraete, nicht mehr unter
Einstellungen bzw. als eigene Rubrik. Der Config-Ordner ist umgeleitet
(Fixture cfg_ordner)."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, karte_auf, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}}}
PANELS = {"panels": {"wohnen": {"title": "Wohnen", "tabs": ["favoriten"]},
                     "kueche": {"title": "Küche", "tabs": ["favoriten"]}},
          "devices": {"wand": {"auto": True, "modes": {"nacht": "kueche"}},
                      "flur": {"auto": True, "modes": {}, "scale": 1.2}}}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/devices", W.api_save_devices),
          ("POST", "/api/panels", W.api_save_panels)]


def test_eine_karte_je_geraet(cfg_ordner, tmp_path):
    async def lauf():
        (cfg_ordner / "panels.json").write_text(json.dumps(PANELS), encoding="utf-8")
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"sl": 0}
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                assert await pg.locator('.rub[data-rub="devices"]').count() == 0, "keine eigene Rubrik mehr"
                await pg.locator(".rub", has_text="Geräte").click()
                await pg.wait_for_selector('#geraete .gk[data-gk="wand"] .gk-kopf .ag')

                karten = await pg.eval_on_selector_all("#geraete > .gk", "l => l.map(k => k.dataset.gk)")
                assert karten == ["flur", "wand"], karten
                flur = pg.locator('#geraete .gk[data-gk="flur"]')
                assert await flur.locator(".gk-kopf .agn").text_content() == "flur"
                assert not await flur.locator(".gk-body").is_visible(), "zugeklappt eine Zeile"

                await karte_auf(pg, "flur")
                teile = await flur.locator(".gk-teil").all_text_contents()
                assert teile == ["Betriebsmodi", "Am Gerät", "Präsenzmelder", "Display-Steuerung"], teile
                assert await flur.locator(".ds_scale").input_value() == "1.2"
                await flur.locator(".dm_mode").fill("gaeste")
                assert await pg.locator("#offenTxt").text_content() == "Nicht gespeichert: Geräte"
                await pg.screenshot(path=str(tmp_path / "geraetekarte.png"), full_page=True)

                # Die Abfrage zeichnet die Koepfe neu; Karte und Eingabe bleiben
                await pg.evaluate("pollDevices()")
                await pg.wait_for_timeout(300)
                assert await flur.locator(".gk-body").is_visible()
                assert await flur.locator(".dm_mode").input_value() == "gaeste"
                assert not await pg.locator('#geraete .gk[data-gk="wand"] .gk-body').is_visible()

                # Ansicht im Kopf waehlen ist keine Einstellung der Karte
                await pg.locator("#saveBtn").click()
                await pg.wait_for_function("document.querySelector('#offenTxt').textContent === 'Alles gespeichert'")
                assert json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["devices"]["flur"]["modes"] == {}, \
                    "ein Modus ohne Ansicht wird nicht gespeichert"
                await flur.locator(".gk-kopf .agsel").select_option("kueche")
                assert await pg.locator("#offenTxt").text_content() == "Alles gespeichert"

                # Erprobte Hardware unter Geraete; ein neues Geraet verbindet seit Schritt 7
                # "Gerät einrichten" (Schritt Gerät), weder Einstellungen noch Geraete selbst
                assert await pg.locator("#displaysHost #erprobteHardware .devcat").count() >= 1
                assert not await pg.locator("#nk_gen").is_visible()
                await pg.locator("#geraetEinrichtenBtn").click()
                await pg.locator("#wzBody #neuesGeraet summary").click()
                assert await pg.locator("#wzBody #neuesGeraet #nk_gen").is_visible()
                await pg.evaluate("wzClose()")
                assert await pg.locator("#wzHeim #neuesGeraet").count() == 1, "zurueck an seinem Platz"
                await pg.locator(".rub", has_text="Einstellungen").click()
                reiter = await pg.eval_on_selector_all("#subtabs .stab", "l => l.map(b => b.dataset.sub)")
                assert "newpanel" not in reiter, reiter
                await pg.locator(".rub", has_text="Übersicht").click()
                await pg.locator('#overviewHost .ovbox[data-goto="wizard"]').click()
                assert await pg.locator("#wzBody #neuesGeraet").count() == 1
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
