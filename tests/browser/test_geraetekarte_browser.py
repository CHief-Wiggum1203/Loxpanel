"""Rubrik Geraete im Konfigurator, in Chromium: eine Karte je Geraet mit fuenf
Zeilen (Einrichtung neu, Schritt 4): Zeigt, Display, Betriebsmodi, Technik,
Entfernen. Der Kopf (Zustand, Typ, Steuerung) und die Zeile Zeigt folgen der
Abfrage der Geraeteliste; "Aendern" klappt den Editor einer Zeile auf, ein
offener Editor und eine Eingabe darin ueberstehen jede Abfrage; Wert und Herkunft
der Zeilen folgen den Eingaben. "Display aus nach" steht am Geraet (vor Ansicht
und Vorgaben). Die Wahl der Ansicht in Zeigt schaltet live, ist keine offene
Aenderung und ordnet auch ein Geraet zu, das nicht verbunden ist. Der
Config-Ordner ist umgeleitet (Fixture cfg_ordner)."""
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
                     "kueche": {"title": "Küche", "tabs": ["favoriten"], "ui": {"grid": "auto"}}},
          "devices": {"wand": {"auto": True, "modes": {"nacht": "kueche"}},
                      "flur": {"auto": True, "modes": {}, "scale": 1.2}}}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/devices", W.api_save_devices),
          ("POST", "/api/panels", W.api_save_panels), ("POST", "/api/device/switch", W.api_device_switch)]
ZEILEN = """k => [...k.querySelectorAll('.gz')].map(z => [z.dataset.gz, z.querySelector('.gz-wert').innerText.replace(/\\s+/g, ' ').trim(),
                                                        z.querySelector('.gz-woher').textContent])"""


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
                assert await flur.locator(".gk-kopf .agsel").count() == 0, "die Ansicht steht in der Zeile Zeigt"
                zeilen = await flur.evaluate(ZEILEN)
                assert [z[0] for z in zeilen] == ["zeigt", "display", "modi", "technik", "entfernen"], zeilen
                werte = {z[0]: (z[1], z[2]) for z in zeilen}
                assert werte["zeigt"][1] == "noch nicht gemeldet", werte
                assert werte["display"] == ("Linux-Agent nach seiner kiosk.conf, sonst nie", "Standard · kein Präsenzmelder"), werte
                assert werte["modi"][0] == "Keine", werte
                assert werte["technik"] == ("Browser · kein Display-Treiber", "Skalierung 120 % (am Gerät) · Zielkachel nur bei Raster „Automatisch“"), werte
                assert werte["entfernen"][0] == "Gerät aus der Liste nehmen" and await flur.locator('[data-act="entfernen"]').count() == 1
                assert await flur.locator(".gz-editor:not([hidden])").count() == 0, "alle Editoren zu"
                wand = {z[0]: z[1] for z in await pg.locator('#geraete .gk[data-gk="wand"]').evaluate(ZEILEN)}
                assert wand["modi"] == "nacht → Küche", wand

                # Editoren auf: Wert und Herkunft folgen den Eingaben, "Display aus" steht am Geraet
                await karte_auf(pg, "flur")
                assert await flur.locator(".gz-editor:not([hidden])").count() == 4
                assert await flur.locator(".ds_scale").input_value() == "1.2"
                await flur.locator(".dm_mode").fill("gaeste")
                assert await pg.locator("#offenTxt").text_content() == "Nicht gespeichert: Geräte"
                await flur.locator(".dd_dpms").fill("120")
                werte = {z[0]: (z[1], z[2]) for z in await flur.evaluate(ZEILEN)}
                assert werte["display"] == ("Aus nach 120 s", "am Gerät · kein Präsenzmelder"), werte
                await pg.screenshot(path=str(tmp_path / "geraetekarte.png"), full_page=True)

                # Die Abfrage zeichnet Kopf und Zeigt neu; Editoren und Eingaben bleiben
                await pg.evaluate("pollDevices()")
                await pg.wait_for_timeout(300)
                assert await flur.locator(".gz-editor:not([hidden])").count() == 4
                assert await flur.locator(".dm_mode").input_value() == "gaeste"
                assert await flur.locator(".dd_dpms").input_value() == "120"
                assert await pg.locator('#geraete .gk[data-gk="wand"] .gz-editor:not([hidden])').count() == 0

                await pg.locator("#saveBtn").click()
                await pg.wait_for_function("document.querySelector('#offenTxt').textContent === 'Alles gespeichert'")
                datei = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["devices"]["flur"]
                assert datei["modes"] == {} and datei["dpmsOff"] == 120 and datei["scale"] == 1.2, datei
                assert app.panel_dpms("wohnen", dev="flur") == 120 and app.panel_dpms("wohnen", dev="wand") is None

                # Ansicht in Zeigt waehlen ist keine offene Aenderung; "Ansicht wechseln" ordnet
                # auch ein Geraet zu, das nicht verbunden ist (Schritt 2), die Zeile sagt es
                await flur.locator(".agsel").select_option("kueche")
                assert await pg.locator("#offenTxt").text_content() == "Alles gespeichert"
                await flur.get_by_role("button", name="Ansicht wechseln").click()
                await pg.wait_for_function("document.querySelector('#ag_toast').textContent.startsWith('✓ zugeordnet')")
                assert json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["devices"]["flur"]["panel"] == "kueche"
                await pg.evaluate("pollDevices()")
                await pg.wait_for_function("""document.querySelector('#geraete .gk[data-gk="flur"] .gz[data-gz="zeigt"] .gz-woher')
                    .textContent.startsWith('Ansicht „kueche“ · Raster automatisch')""")
                werte = {z[0]: (z[1], z[2]) for z in await flur.evaluate(ZEILEN)}
                assert werte["technik"][1].startswith("Skalierung 120 % (am Gerät) · Zielkachel "), werte
                assert "Ansicht „Küche“ bleibt bestehen" in werte["entfernen"][1], werte
                await flur.locator(".gz-fein").click()
                assert await pg.evaluate("[cur, rubric]") == ["kueche", "pconf"]
                assert await pg.locator("#pconfHost [data-ui='dpmsOff']").count() == 0, "Display aus steht nicht mehr in der Ansicht"

                # Erprobte Hardware unter Geraete; "Neues Geraet verbinden" lebt im ausfuehrlichen Assistenten
                await pg.locator(".rub", has_text="Geräte").click()
                assert await pg.locator("#displaysHost #erprobteHardware .devcat").count() >= 1
                assert not await pg.locator("#nk_gen").is_visible()
                await pg.evaluate("wzOpen()")
                await pg.locator("#wzBody #neuesGeraet summary").click()
                assert await pg.locator("#wzBody #neuesGeraet #nk_gen").is_visible()
                await pg.evaluate("wzClose()")
                assert await pg.locator("#wzHeim #neuesGeraet").count() == 1, "zurueck an seinem Platz"
                await pg.locator(".rub", has_text="Übersicht").click()
                await pg.locator('#overviewHost .ovbox[data-goto="wizard"]').click()
                assert await pg.locator("#geOv:not([hidden])").count() == 1, "Gerät einrichten (Schritt 3), ein Bildschirm"
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
