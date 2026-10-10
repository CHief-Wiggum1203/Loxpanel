"""Gerät einrichten (Konzept "Konfigurator neu ordnen", Schritt 7) in Chromium: ein
Weg vom Geraet bis zur fertigen Ansicht, aus Uebersicht, Geraete und "＋ Neue
Ansicht". Sechs Schritte, der erste (Miniserver) ist erledigt; die Rubrik
Einrichtungsassistent gibt es nicht mehr. Im Schritt Ansicht: neu anlegen, eine
vorhandene zuweisen (das Geraet schaltet um, Inhalt und Aussehen entfallen) oder
eine vorhandene mit Raumtausch duplizieren (der Zielraum kommt aus dem
Geraetenamen). Neu: Der Inhalt schlaegt die Raum-Ansicht zum Geraetenamen vor,
"Display aus" steht im Schritt Aussehen und Verhalten. Der Config-Ordner ist
umgeleitet (Fixture cfg_ordner)."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

# anlage(): Raeume r1 "Zentral" und r2 "Technikraum"; je ein "Licht" fuer den Raumtausch
BAUSTEINE = {u: {"name": "Licht", "type": "Switch", "uuidAction": u, "room": r, "cat": "c1",
                 "isFavorite": True, "states": {"active": u.lower()}} for u, r in (("L1", "r1"), ("L2", "r2"))}
PANELS = {"panels": {"zentral": {"title": "Zentral", "tabs": ["auswahl"],
                                 "pickTabs": [{"name": "Zentral", "picks": ["L1"]}]}}}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/devices", W.api_save_devices),
          ("POST", "/api/panels", W.api_save_panels), ("POST", "/api/device/switch", W.api_device_switch)]
LEISTE = """() => [...document.querySelectorAll('#wzBody .wzleiste li')].map(l => [l.textContent.replace(/^\\d/, ''), l.className])"""
SCHRITT = "wzFlow()[WZ.step]"


async def _bis(bedingung, was, sekunden=10):
    for _ in range(int(sekunden * 20)):
        if bedingung():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"nicht erreicht: {was}")


def test_ein_weg_fuer_neu_zuweisen_und_kopie(cfg_ordner, tmp_path):
    (cfg_ordner / "panels.json").write_text(json.dumps(PANELS), encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"l1": 0, "l2": 0}
        app.panels = W.load_panels()
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                tablet = await b.new_page(viewport={"width": 893, "height": 533})
                tablet.on("pageerror", lambda e: fehler.append(str(e)))
                await tablet.goto(f"http://127.0.0.1:{port}/?device=technikraum")
                await _bis(lambda: any(i.get("screen") for i in app.conn_info.values()), "Tablet mit gemeldeter Groesse")
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.wait_for_function("DEVICE_SCREENS.technikraum")
                rubriken = await pg.eval_on_selector_all(".rub", "l => l.map(b => b.dataset.rub)")
                assert "assistant" not in rubriken, rubriken

                # 1) Vorhandene Ansicht zuweisen, aus Geraete heraus
                await pg.locator(".rub", has_text="Geräte").click()
                await pg.locator("#geraetEinrichtenBtn").click()
                assert await pg.evaluate(LEISTE) == [["Miniserver", "erledigt"], ["Gerät", "jetzt"], ["Ansicht", ""],
                                                     ["Inhalt und Seiten", ""], ["Aussehen und Verhalten", ""], ["Prüfen", ""]]
                assert await pg.locator("#wzBody #neuesGeraet").count() == 1, "Neues Gerät verbinden im Schritt Gerät"
                await pg.locator('#wzBody [data-wgr="geraet"][data-wgn="technikraum"]').click()
                await pg.locator("#wzNext").click()
                assert await pg.locator("#wzHeim #neuesGeraet").count() == 1, "zurueck an seinem Platz"
                await pg.locator('#wzBody [data-wk="art"][data-wo="zuweisen"]').click()
                assert await pg.locator("#wzQuelle").input_value() == "zentral"
                leiste = dict(await pg.evaluate(LEISTE))
                assert leiste["Inhalt und Seiten"] == "entfaellt" and leiste["Aussehen und Verhalten"] == "entfaellt", leiste
                await pg.locator("#wzNext").click()
                assert await pg.evaluate(SCHRITT) == "pruefen"
                assert await pg.locator("#wzNext").text_content() == "Zuweisen ✓"
                assert await pg.locator("#wzTitleI").count() == 0, "kein Name beim Zuweisen"
                await pg.screenshot(path=str(tmp_path / "zuweisen_pruefen.png"))
                vorher = (cfg_ordner / "panels.json").stat().st_mtime_ns
                await pg.locator("#wzNext").click()
                await pg.wait_for_selector("#wzOv[hidden]", state="attached")
                await _bis(lambda: any((app.conn_prof.get(ws) or {}).get("id") == "zentral" for ws, i in app.conn_info.items()
                                       if i.get("dev") == "technikraum"), "das Tablet schaltet um", sekunden=15)
                assert await pg.evaluate("rubric") == "displays"
                assert (cfg_ordner / "panels.json").stat().st_mtime_ns == vorher, "Zuweisen speichert keine Ansicht"

                # 2) Vorhandene duplizieren, Zielraum aus dem Geraetenamen
                await pg.locator("#addBtn").click()
                await pg.locator('#wzBody [data-wgr="geraet"][data-wgn="technikraum"]').click()
                await pg.locator("#wzNext").click()
                await pg.locator('#wzBody [data-wk="art"][data-wo="kopie"]').click()
                assert (await pg.locator("#wzVon").input_value(), await pg.locator("#wzNach").input_value()) == ("r1", "r2")
                assert "1 Bausteine aus Zentral werden durch die gleichnamigen in Technikraum ersetzt." in \
                    await pg.locator("#wzBody").inner_text()
                await pg.locator("#wzNext").click()
                assert (await pg.locator("#wzTitleI").input_value(), await pg.locator("#wzId").input_value()) == \
                    ("Technikraum", "technikraum"), "Name aus dem Zielraum"
                await pg.locator("#wzUmschalten").uncheck()
                await pg.locator("#wzNext").click()
                await pg.wait_for_selector("#wzOv[hidden]", state="attached")
                kopie = await pg.evaluate("PANELS.technikraum")
                assert kopie["pickTabs"][0]["picks"] == ["L2"] and kopie["title"] == "Technikraum", kopie
                assert kopie["device"]["name"] == "technikraum", kopie
                assert await pg.evaluate("cur") == "technikraum"

                # 3) Neu aus der Uebersicht: Raum-Ansicht zum Geraetenamen, Display aus im Aussehen
                await pg.evaluate("delete PANELS.technikraum; OFFEN.clear(); renderList()")
                await pg.locator(".rub", has_text="Übersicht").click()
                await pg.locator("#ovGeraetEinrichten").click()
                await pg.locator('#wzBody [data-wgr="geraet"][data-wgn="technikraum"]').click()
                await pg.locator("#wzNext").click()
                await pg.locator("#wzNext").click()          # Neue Ansicht anlegen ist vorgewaehlt
                assert await pg.evaluate("[wzFlow()[WZ.step], WZ.content, WZ.roomTab, WZ.panes]") == \
                    ["inhalt", "room", "room:r2", "2"]
                assert "Vorschlag aus dem Gerätenamen: Raum-Ansicht Technikraum" in await pg.locator("#wzBody").inner_text()
                await pg.locator("#wzNext").click()
                assert await pg.evaluate(SCHRITT) == "aussehen"
                await pg.locator("#wzBody [data-wdpms]").fill("120")
                await pg.screenshot(path=str(tmp_path / "neu_aussehen.png"), full_page=True)
                await pg.locator("#wzNext").click()
                assert await pg.locator("#wzTitleI").input_value() == "Technikraum"
                assert "Display aus nach" in await pg.locator("#wzBody").inner_text()
                entwurf = await pg.evaluate("wzEntwurf()")
                assert entwurf["tabs"] == ["room:r2"] and entwurf["ui"]["dpmsOff"] == 120, entwurf
                await pg.evaluate("wzClose()")
                assert await pg.locator("#wzHeim #neuesGeraet").count() == 1
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
