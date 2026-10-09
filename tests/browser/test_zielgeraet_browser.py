"""Zielgeraet eines Profils (Punkt 15) in Chromium: Der Reiter Titel bietet
die bekannten Geraete an und speichert Name und gemeldete Groesse; Displays
warnt in der Geraeteliste, wenn ein Geraet ein Profil nutzt, das fuer ein
anderes Geraet oder eine deutlich andere Groesse gemacht ist."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}}}
# wohnen ist fuer "wand" bei 1024x600 gemacht, kueche fuer "flur" (nur Name)
PANELS = {"panels": {"wohnen": {"title": "Wohnen", "tabs": ["favoriten"], "device": {"name": "wand", "vw": 1024, "vh": 600}},
                     "kueche": {"title": "Küche", "tabs": ["favoriten"], "device": {"name": "flur"}}},
          "devices": {"flur": {"auto": True, "modes": {}}}}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/panels", W.api_save_panels)]


async def _bis(bedingung, was, sekunden=10):
    for _ in range(int(sekunden * 20)):
        if bedingung():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"nicht erreicht: {was}")


def test_zielgeraet_waehlen_und_warnung(cfg_ordner, tmp_path):
    (cfg_ordner / "panels.json").write_text(json.dumps(PANELS), encoding="utf-8")

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
                for adresse, groesse in (("?panel=wohnen&device=tablet", (1024, 600)),
                                          ("?panel=wohnen&device=wand", (893, 533)),
                                          ("?panel=kueche&device=kind", (800, 1280))):
                    v = await b.new_page(viewport={"width": groesse[0], "height": groesse[1]})
                    v.on("pageerror", lambda e: fehler.append(str(e)))
                    await v.goto(f"http://127.0.0.1:{port}/{adresse}")
                await _bis(lambda: len(app.conn_info) == 3 and all(i.get("screen") for i in app.conn_info.values()),
                           "drei Visus mit gemeldeter Groesse")
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator(".rub", has_text="Displays").click()
                liste = pg.locator("#ag_list")
                await liste.locator('.ag[data-name="wand"]').wait_for()
                warn = {}
                for name in ("flur", "kind", "tablet", "wand"):
                    w = liste.locator(f'.ag[data-name="{name}"] .tag.warn')
                    warn[name] = (await w.text_content()) if await w.count() else ""
                # tablet: anderes Geraet als im Profil; wand: richtiges Geraet, aber deutlich
                # andere Groesse; kind: Profil fuer flur; flur: offline, nichts zu warnen
                assert warn == {"flur": "", "tablet": "⚠ Profil ist für wand gemacht",
                                "wand": "⚠ Profil ist für 1024×600 gemacht, hier 893×533",
                                "kind": "⚠ Profil ist für flur gemacht"}, warn
                await pg.screenshot(path=str(tmp_path / "zielgeraet_displays.png"), full_page=True)

                # Reiter Titel: Zielgeraet waehlen, gemeldete Groesse kommt mit
                await pg.locator(".rub", has_text="Panel Configuration").click()
                await pg.locator("#plist .pitem", has_text="Wohnen").click()
                await pg.locator('.stab[data-sub="title"]').click()
                ziel = pg.locator("#fZiel")
                assert await ziel.input_value() == "wand"
                assert await ziel.locator("option").all_text_contents() == ["(keines)", "flur", "kind", "tablet", "wand"]
                assert (await pg.locator("#fZielHint").text_content()).startswith("wand · 1024×600 – ")
                # Ein viertes Geraet meldet sich, waehrend der Reiter offen ist: die naechste
                # Abfrage der Geraeteliste nimmt es in die Auswahl auf, die Wahl bleibt
                v = await b.new_page(viewport={"width": 480, "height": 480})
                v.on("pageerror", lambda e: fehler.append(str(e)))
                await v.goto(f"http://127.0.0.1:{port}/?panel=kueche&device=neu")
                await _bis(lambda: len(app.conn_info) == 4, "vierte Visu verbunden")
                await pg.evaluate("pollDevices()")
                await pg.wait_for_function("document.querySelectorAll('#fZiel option').length === 6")
                assert await ziel.locator("option").all_text_contents() == ["(keines)", "flur", "kind", "neu", "tablet", "wand"]
                assert await ziel.input_value() == "wand"
                await ziel.select_option("tablet")   # gemeldete Groesse des Tablets kommt mit
                assert (await pg.locator("#fZielHint").text_content()).startswith("tablet · 1024×600 – ")

                async def speichern():
                    async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
                        await pg.locator("#saveBtn").click()
                    j = await (await antwort.value).json()
                    assert j["ok"] and j["verworfen"] == [], j
                    return json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]["wohnen"]
                assert (await speichern())["device"] == {"name": "tablet", "vw": 1024, "vh": 600}
                await pg.locator(".rub", has_text="Displays").click()
                await pg.wait_for_function("""() => { const w = document.querySelector('#ag_list .ag[data-name="wand"] .tag.warn');
                    const t = document.querySelector('#ag_list .ag[data-name="tablet"] .tag.warn'); return !!w && !t; }""")
                assert (await liste.locator('.ag[data-name="wand"] .tag.warn').text_content()
                        == "⚠ Profil ist für tablet gemacht")
                await pg.locator(".rub", has_text="Panel Configuration").click()
                await pg.locator("#plist .pitem", has_text="Wohnen").click()
                await pg.locator('.stab[data-sub="title"]').click()
                await pg.locator("#fZiel").select_option("")
                assert "device" not in await speichern()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
