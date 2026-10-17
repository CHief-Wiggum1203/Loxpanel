""""Gerät verbinden" (Einrichtung neu, Schritt 5) in Chromium: ein Bogen mit drei
Wegen, je eine Zeile zum Kopieren - Server-Adresse fuer die LoxPanel-App, die
Start-Adresse ohne Parameter fuer Kiosk-Browser, der Agent-Befehl ohne PANEL und
AGENT_NAME fuer Linux. Die Server-Adresse ist die LAN-Adresse aus /api/meta, auch
wenn der Konfigurator ueber 127.0.0.1 laeuft. Der Fuss wartet auf ein neues Geraet
und fuehrt zum Banner, sobald eines die Visu oeffnet. Erreichbar unter Geraete, aus
der Uebersicht und aus dem ausfuehrlichen Assistenten."""
import asyncio
import json

import pytest

from lox import konfig, anlage, geraete, KONFIGURATOR_GELADEN, visu_starten, W

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}}}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/devices", W.api_save_devices),
          ("POST", "/api/device/name", W.api_device_name)]
WEGE = """() => [...document.querySelectorAll('#gvBody .gv-weg')].map(w => ({
  titel: w.querySelector('b').textContent, zeile: w.querySelector('code').textContent,
  knopf: w.querySelector('[data-gv-copy]').textContent, kopie: w.querySelector('[data-gv-copy]').dataset.gvCopy}))"""
STAND = """() => ({offen: !document.getElementById('gvOv').hidden,
  stand: document.getElementById('gvStand').innerText.replace(/\\s+/g, ' ').trim(),
  server: document.querySelector('#gvBody .gv-server b').textContent,
  weiter: !!document.getElementById('gvWeiter')})"""


async def _bis(bedingung, was, sekunden=10):
    for _ in range(int(sekunden * 20)):
        if bedingung():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"nicht erreicht: {was}")


def test_drei_wege_mit_lan_adresse(cfg_ordner, tmp_path):
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"flur": {"title": "Flur", "tabs": ["favoriten"]}}}),
                                            encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"sl": 0}
        app.panels = konfig.load_panels()
        runner, port, bc = await visu_starten(app, ROUTEN)
        lan = (geraete._lan_adressen() or ["127.0.0.1"])[0]
        host = f"{lan}:{port}"
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)

                # Aus Geraete: drei Wege, die Zeilen tragen die LAN-Adresse, nicht 127.0.0.1
                await pg.locator(".rub", has_text="Geräte").click()
                await pg.locator("#geraetVerbindenBtn").click()
                await pg.wait_for_selector("#gvOv:not([hidden])")
                wege = await pg.evaluate(WEGE)
                assert [w["titel"] for w in wege] == ["LoxPanel-App auf Android", "Fully Kiosk, WallPanel oder ein Browser",
                                                      "Linux-Wandpanel mit Agent"], wege
                assert [w["zeile"] for w in wege] == [host, f"http://{host}/",
                                                      f"curl -fsSL http://{host}/install-agent.sh | SERVER={host} bash"], wege
                assert [w["kopie"] for w in wege] == [w["zeile"] for w in wege]
                assert [w["knopf"] for w in wege] == ["Adresse kopieren", "Adresse kopieren", "Befehl kopieren"], wege
                assert "?panel=" not in wege[1]["zeile"] and "device=" not in wege[1]["zeile"], "Start-Adresse ohne Parameter"
                assert "PANEL" not in wege[2]["zeile"] and "AGENT_NAME" not in wege[2]["zeile"], "Agent-Befehl ohne PANEL und AGENT_NAME"
                st = await pg.evaluate(STAND)
                assert st["server"] == host and st["stand"] == "Warte auf ein neues Gerät …" and not st["weiter"], st
                await pg.screenshot(path=str(tmp_path / "geraet_verbinden.png"))

                # Ein Tablet oeffnet die Start-Adresse: der Fuss meldet es, "Weiter" fuehrt zum Banner
                tablet = await b.new_page(viewport={"width": 1180, "height": 820})
                tablet.on("pageerror", lambda e: fehler.append(str(e)))
                await tablet.goto(f"http://127.0.0.1:{port}/")
                await _bis(lambda: any(i.get("code") and i.get("screen") for i in app.conn_info.values()), "Tablet mit Code und Groesse")
                await pg.evaluate("pollDevices()")
                await pg.wait_for_function("document.getElementById('gvWeiter')", timeout=15000)
                st = await pg.evaluate(STAND)
                assert st["stand"].startswith("Neues Gerät gefunden: Tablet · 1180×820 · Code "), st
                await pg.locator("#gvWeiter").click()
                assert (await pg.evaluate(STAND))["offen"] is False
                assert await pg.locator("#neuGeraet:not([hidden]) .nb-name").count() == 1, "das Banner steht bereit"
                assert await pg.evaluate("document.activeElement === document.querySelector('#neuGeraet .nb-name')")

                # Aus der Uebersicht und per Esc wieder zu
                await pg.locator(".rub", has_text="Übersicht").click()
                await pg.locator('#overviewHost .ovbox[data-goto="verbinden"]').click()
                assert (await pg.evaluate(STAND))["offen"] is True
                await pg.keyboard.press("Escape")
                assert (await pg.evaluate(STAND))["offen"] is False
                assert await pg.locator("#nk_gen, #np_gen, #neuesGeraet").count() == 0, "die alten Generatoren sind weg"
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
