"""Vorschlag statt leerer Seite (Punkt 13) in Chromium: Der Assistent zeigt
je bekanntem Geraet ohne Profil einen Vorschlag - Geraetename passt zu einem
Loxone-Raum: Raum-Panel, sonst Favoriten -, fuellt Anzeige (aus der
gemeldeten Groesse), Inhalt und Name, traegt das Geraet als Zielgeraet ein
und laesst mit "Jetzt anlegen" sofort anlegen; der Rest behaelt Standardwerte.
Ein Geraet, auf das schon ein Profil zeigt, wird nicht mehr vorgeschlagen."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

# anlage(): Raeume r1 "Zentral" und r2 "Technikraum"
BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r2", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}}}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/panels", W.api_save_panels)]
STAND = """() => ({step: WZ.step, schritt: wzFlow()[WZ.step], panes: WZ.panes, grid: WZ.grid, content: WZ.content,
  roomTab: WZ.roomTab, title: WZ.title, id: WZ.id, device: WZ.device,
  fertig: !document.getElementById('wzFertig').hidden,
  titel: (document.getElementById('wzTitleI') || {}).value, idFeld: (document.getElementById('wzId') || {}).value})"""


async def _bis(bedingung, was, sekunden=10):
    for _ in range(int(sekunden * 20)):
        if bedingung():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"nicht erreicht: {was}")


def test_vorschlag_aus_dem_geraet(cfg_ordner, tmp_path):
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {}}), encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"sl": 0}
        app.panels = W.load_panels()
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                for adresse, groesse in (("?device=technikraum", (893, 533)), ("?device=garage", (480, 480))):
                    v = await b.new_page(viewport={"width": groesse[0], "height": groesse[1]})
                    v.on("pageerror", lambda e: fehler.append(str(e)))
                    await v.goto(f"http://127.0.0.1:{port}/{adresse}")
                await _bis(lambda: len(app.conn_info) == 2 and all(i.get("screen") for i in app.conn_info.values()),
                           "beide Geraete mit gemeldeter Groesse")
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.wait_for_function("KNOWN_NAMES.length >= 2")
                await pg.locator("#addBtn").click()
                await pg.wait_for_selector("#wzOv:not([hidden])")
                vorschlaege = pg.locator("#wzBody [data-wv]")
                assert await vorschlaege.evaluate_all("l => l.map(n => [n.dataset.wv, n.innerText.replace(/\\s+/g, ' ').trim()])") == [
                    ["garage", "Favoriten für garage · 480×480"],
                    ["technikraum", "Raum-Panel Technikraum für technikraum · 893×533"]]
                assert not (await pg.evaluate(STAND))["fertig"], "ohne Pflichtschritte kein Sofort-Anlegen"
                await pg.screenshot(path=str(tmp_path / "assistent_vorschlag.png"))

                # Tablet im Technikraum: Raum-Panel, 2 Panes automatisch, Name und ID aus Raum und Geraet
                await vorschlaege.nth(1).click()
                st = await pg.evaluate(STAND)
                assert st == {"step": st["step"], "schritt": "name", "panes": "2", "grid": "auto", "content": "room",
                              "roomTab": "room:r2", "title": "Technikraum", "id": "technikraum", "device": "technikraum",
                              "fertig": True, "titel": "Technikraum", "idFeld": "technikraum"}, st
                await pg.locator("#wzFertig").click()
                await pg.wait_for_selector("#wzOv[hidden]", state="attached")
                tr = await pg.evaluate("PANELS.technikraum")
                assert (tr["title"], tr["tabs"], tr["ui"], tr["device"]) == (
                    "Technikraum", ["room:r2"], {"grid": "auto"}, {"name": "technikraum", "vw": 893, "vh": 533}), tr

                # Quadratisches Geraet ohne passenden Raum: Favoriten (klassische Visu), 1 Pane 2 x 2;
                # das Technikraum-Tablet hat jetzt ein Profil und wird nicht mehr vorgeschlagen
                await pg.locator("#addBtn").click()
                await pg.wait_for_selector("#wzOv:not([hidden])")
                assert await vorschlaege.evaluate_all("l => l.map(n => n.dataset.wv)") == ["garage"]
                await vorschlaege.first.click()
                st = await pg.evaluate(STAND)
                assert (st["panes"], st["grid"], st["content"], st["title"], st["id"], st["device"], st["fertig"]) == (
                    "1", "2x2", "classic", "Garage", "garage", "garage", True), st
                await pg.locator("#wzFertig").click()
                await pg.wait_for_selector("#wzOv[hidden]", state="attached")
                ga = await pg.evaluate("PANELS.garage")
                assert ga["tabs"][0] == "favoriten" and len(ga["tabs"]) == 4 and ga["ui"] == {"split": False} \
                    and ga["device"] == {"name": "garage", "vw": 480, "vh": 480}, ga

                async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
                    await pg.locator("#saveBtn").click()
                j = await (await antwort.value).json()
                assert j["ok"] and j["verworfen"] == [], j
                datei = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]
                assert datei["technikraum"]["device"] == {"name": "technikraum", "vw": 893, "vh": 533}
                assert datei["garage"]["tabs"][0] == "favoriten"
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
