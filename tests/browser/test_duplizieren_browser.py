"""Panel duplizieren mit Raumtausch (Punkt 14) in Chromium: Die Kopie eines
Profils ersetzt jeden Baustein aus dem Quellraum durch den gleichnamigen aus
dem Zielraum - in Tabs, Raum-Liste, hide, freien Seiten, Kachel-Einstellungen,
Widgets je Tab, Werteleiste und Uhr-Seite; wer im Zielraum fehlt, faellt weg
und wird genannt, Bausteine ohne Raum bleiben. Der Dialog schlaegt ID und
Titel aus dem Zielraum vor, ohne Zielraum entsteht eine reine Kopie."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser


def _schalter(uuid, name, room, typ="Switch"):
    return {"name": name, "type": typ, "uuidAction": uuid, "room": room, "cat": "c1",
            "states": {"active": uuid.lower()}}


# anlage(): r1 "Zentral", r2 "Technikraum". Licht und Rollo gibt es in beiden,
# Heizung nur in r1, der Zentralschalter hat keinen Raum.
BAUSTEINE = {"L1": _schalter("L1", "Licht", "r1"), "L2": _schalter("L2", "Licht", "r2"),
             "R1": _schalter("R1", "Rollo", "r1", "Jalousie"), "R2": _schalter("R2", "Rollo", "r2", "Jalousie"),
             "H1": _schalter("H1", "Heizung", "r1"), "Z": _schalter("Z", "Zentralschalter", "")}
QUELLE = {"title": "Zentral Panel", "tabs": ["room:r1", "favoriten"], "rooms": ["r1"], "hide": ["H1"],
          "pickTabs": [{"name": "Mix", "picks": ["L1", "R1", "H1", "Z"], "icon": ""}],
          "tiles": {"L1": {"bg": "#112233"}, "Z": {"w": 2}},
          "ui": {"panes": {"room:r1": "status:L1,R1", "favoriten": "camera:L1|R1,Z"}, "valueBar": ["room:r1"],
                 "svPane": "status:H1"}}
# Was die Kopie tragen muss (der Konfigurator bekommt Profile normiert vom
# Server, mit leeren cats/roomCats/states und widget: "" je freier Seite -
# verglichen wird deshalb diese Sicht, nicht das ganze Objekt)
SICHT = """p => ({title: p.title, tabs: p.tabs, rooms: p.rooms, hide: p.hide, picks: (p.pickTabs || []).map(t => t.picks),
  tiles: p.tiles, panes: p.ui.panes, valueBar: p.ui.valueBar, svPane: p.ui.svPane})"""
ERWARTET = {"title": "Technikraum Panel", "tabs": ["room:r2", "favoriten"], "rooms": ["r2"], "hide": [],
            "picks": [["L2", "R2", "Z"]], "tiles": {"L2": {"bg": "#112233"}, "Z": {"w": 2}},
            "panes": {"room:r2": "status:L2,R2", "favoriten": "camera:L2|R2,Z"}, "valueBar": ["room:r2"], "svPane": ""}


def test_duplizieren_mit_raumtausch(cfg_ordner, tmp_path):
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"zentral": QUELLE}}), encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {u.lower(): 0 for u in BAUSTEINE}
        app.panels = W.load_panels()
        runner, port, bc = await visu_starten(app, [("POST", "/api/panels", W.api_save_panels)])
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator("#plist .pitem", has_text="Zentral Panel").click()
                # Die reine Funktion, tabellarisch: alle Felder, Fehlendes, Zaehler
                rein = await pg.evaluate("""() => { const r = profilMitRaumtausch(PANELS.zentral, 'r1', 'r2', META.controls);
                    return {profil: (%s)(r.profil), fehlend: r.fehlend, getauscht: r.getauscht}; }""" % SICHT)
                assert rein["profil"] == {**ERWARTET, "title": "Zentral Panel"}, rein["profil"]
                assert (rein["fehlend"], rein["getauscht"]) == (["Heizung"], 2), rein
                assert await pg.evaluate("profilRaum(PANELS.zentral)") == "r1"
                assert await pg.evaluate("profilRaum({tabs: ['favoriten'], pickTabs: [{picks: ['L2', 'R2', 'Z']}]})") == "r2", \
                    "ohne room:-Tab und Raum-Liste zaehlt der Raum der gewaehlten Bausteine"

                # Der Dialog: Vorschlaege aus dem Zielraum, Hinweis auf den fehlenden Baustein
                await pg.locator("#dupBtn").click()
                await pg.wait_for_selector("#dupOv:not([hidden])")
                stand = {f: await pg.locator(f"#{f}").input_value() for f in ("dupId", "dupTitle", "dupVon", "dupNach")}
                assert stand == {"dupId": "technikraum", "dupTitle": "Technikraum Panel", "dupVon": "r1", "dupNach": "r2"}, stand
                info = await pg.locator("#dupInfo").text_content()
                assert info.startswith("2 Bausteine aus Zentral werden durch die gleichnamigen in Technikraum ersetzt.") \
                    and info.endswith("Ohne Gegenstück dort (fallen weg): Heizung"), info
                await pg.screenshot(path=str(tmp_path / "duplizieren_dialog.png"))
                await pg.locator("#dupGo").click()
                await pg.wait_for_selector("#dupOv[hidden]", state="attached")
                assert await pg.evaluate("cur") == "technikraum"
                assert await pg.evaluate("(%s)(PANELS.technikraum)" % SICHT) == ERWARTET
                assert "Technikraum Panel" in await pg.locator("#plist .pitem .pn").all_text_contents()
                assert "Weggefallen: Heizung" in (await pg.locator("#toast").text_content())

                # Reine Kopie: kein Zielraum, alles bleibt
                await pg.locator("#dupBtn").click()
                await pg.wait_for_selector("#dupOv:not([hidden])")
                await pg.locator("#dupNach").select_option("")
                stand = {f: await pg.locator(f"#{f}").input_value() for f in ("dupId", "dupTitle")}
                assert stand == {"dupId": "technikraum-kopie", "dupTitle": "Technikraum Panel (Kopie)"}, stand
                assert (await pg.locator("#dupInfo").text_content()).startswith("Reine Kopie")
                await pg.locator("#dupGo").click()
                await pg.wait_for_selector("#dupOv[hidden]", state="attached")
                assert await pg.evaluate("(%s)(PANELS['technikraum-kopie'])" % SICHT) == {**ERWARTET, "title": "Technikraum Panel (Kopie)"}

                # Speichern: der Server nimmt beide an, nichts verworfen
                async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
                    await pg.locator("#saveBtn").click()
                j = await (await antwort.value).json()
                assert j["ok"] and j["verworfen"] == [], j
                datei = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]
                assert {"zentral", "technikraum", "technikraum-kopie"} <= set(datei), list(datei)   # dazu "default"
                assert datei["technikraum"]["tabs"] == ["room:r2", "favoriten"] and datei["technikraum"].get("hide", []) == [] \
                    and datei["technikraum"]["pickTabs"][0]["picks"] == ["L2", "R2", "Z"] \
                    and datei["technikraum"]["ui"]["panes"] == {"room:r2": "status:L2,R2", "favoriten": "camera:L2|R2,Z"}, \
                    datei["technikraum"]
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
