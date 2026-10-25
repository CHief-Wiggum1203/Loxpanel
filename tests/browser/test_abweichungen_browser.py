"""Uebersicht "Was ist eingestellt?" (LoxOS, docs/VISION.md, Stufe 2.5) in
Chromium: Oben im Reiter Allgemein einer Ansicht (in den Vorgaben oben in
Darstellung, sie haben keinen Reiter Allgemein) steht jede ui-Einstellung, die
sie selbst setzt, mit Wert, was ohne sie gaelte, Sprung zum Reiter und
"× zurücksetzen". "Alles auf Standard" fragt in der Seite nach (kein
Browser-Dialog), laesst Widgets, Kachel-Set und Farbton stehen und nennt in den
Vorgaben, fuer wie viele Ansichten die Werte gelten. Wirksam erst mit
"Speichern". Der Config-Ordner ist umgeleitet (Fixture cfg_ordner)."""
import asyncio
import json

import pytest

from lox import anlage, konfig, KONFIGURATOR_GELADEN, visu_starten, W

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}}}
ROUTEN = [("POST", "/api/panels", W.api_save_panels), ("POST", "/api/theme", W.api_save_theme)]
OFFEN = "document.querySelector('#offenTxt').textContent"
KARTE = "#pconfHost #abwKarte"
ICON_STD = konfig.GROESSEN_STANDARD["neu"]["iconSize"]


def _laufen(cfg_ordner, panels, theme, schritte):
    """Konfigurator mit panels/theme starten, schritte(pg) ausfuehren; kein
    Browser-Dialog, kein Skriptfehler."""
    async def lauf():
        (cfg_ordner / "panels.json").write_text(json.dumps({"panels": panels}), encoding="utf-8")
        (cfg_ordner / "theme.json").write_text(json.dumps({"ui": theme}), encoding="utf-8")
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"sl": 0}
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler, dialoge = [], []

        async def dialog(d):
            dialoge.append(d.message)
            await d.dismiss()
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                pg.on("dialog", dialog)
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await schritte(pg)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        assert dialoge == [], "Bestaetigung in der Seite, kein Browser-Dialog"
    asyncio.run(lauf())


async def _ansicht(pg, kennung):
    await pg.locator("#plist .pitem", has_text=f"?panel={kennung}").click()
    await pg.locator(".stab[data-sub='allgemein']").click()


def _zeile(pg, k):
    return pg.locator(f"{KARTE} [data-abw='{k}']")


async def _speichern(pg, cfg_ordner, datei):
    await pg.locator("#saveBtn").click()
    await pg.wait_for_function(OFFEN + " === 'Alles gespeichert'")
    return json.loads((cfg_ordner / datei).read_text(encoding="utf-8"))


def test_liste_zeigt_was_gesetzt_ist(cfg_ordner, tmp_path):
    async def schritte(pg):
        await _ansicht(pg, "flur")
        assert await pg.locator(f"{KARTE} [data-abw]").count() == 2
        icon = _zeile(pg, "iconSize")
        assert await icon.locator(".abw-name").text_content() == "Icon-Größe"
        assert await icon.locator(".abw-wert").text_content() == "44 px"
        assert await icon.locator(".abw-ohne").text_content() == f"sonst gilt: {ICON_STD} px · Standard"
        uhr = _zeile(pg, "nightClock")
        assert await uhr.locator(".abw-name").text_content() == "Nacht-Uhr"
        assert await uhr.locator(".abw-wert").text_content() == "An"
        assert await uhr.locator(".abw-ohne").text_content() == "sonst gilt: Aus · Standard"
        await pg.screenshot(path=str(tmp_path / "abweichungen_ansicht.png"), full_page=True)
        # Sprung zum Reiter, in dem die Einstellung steht
        await icon.locator("[data-abw-reiter]").click()
        assert await pg.locator(".stab.active").get_attribute("data-sub") == "aussehen"
        assert await pg.locator("#pconfHost .spane[data-sub='aussehen']").is_visible()
        # Eine Aenderung in einem anderen Reiter steht danach in der Liste
        await pg.locator("#pconfHost input[data-ui='nameSize']").fill("21")
        await pg.locator(".stab[data-sub='allgemein']").click()
        assert await _zeile(pg, "nameSize").locator(".abw-wert").text_content() == "21 px"
    _laufen(cfg_ordner, {"flur": {"title": "Flur", "tabs": ["favoriten"], "ui": {"iconSize": 44, "nightClock": True}}},
            {}, schritte)


def test_zuruecksetzen_je_zeile(cfg_ordner):
    async def schritte(pg):
        await _ansicht(pg, "flur")
        knopf = _zeile(pg, "iconSize").locator("[data-abw-zurueck]")
        assert await knopf.get_attribute("title") == f"Dann gilt: {ICON_STD} px · Standard"
        await knopf.click()
        assert await _zeile(pg, "iconSize").count() == 0
        assert await _zeile(pg, "nightClock").count() == 1
        assert await pg.locator(".stab.active").get_attribute("data-sub") == "allgemein", "Reiter bleibt"
        assert await pg.evaluate(OFFEN) == "Nicht gespeichert: Ansicht Flur", "erst mit Speichern wirksam"
        await pg.locator(".stab[data-sub='aussehen']").click()
        assert await pg.locator("#pconfHost input[data-ui='iconSize']").input_value() == "", "Feld nachgezogen"
        gespeichert = await _speichern(pg, cfg_ordner, "panels.json")
        ui = gespeichert["panels"]["flur"].get("ui", {})
        assert "iconSize" not in ui and ui.get("nightClock") is True, gespeichert
    _laufen(cfg_ordner, {"flur": {"title": "Flur", "tabs": ["favoriten"], "ui": {"iconSize": 44, "nightClock": True}}},
            {}, schritte)


def test_alles_auf_standard_laesst_look(cfg_ordner, tmp_path):
    look = {"tileSet": "edge", "tileHueEdge": 190}

    async def schritte(pg):
        await _ansicht(pg, "flur")
        assert await pg.locator(f"{KARTE} [data-abw]").count() == 4
        frage = pg.locator(f"{KARTE} .abw-frage")
        assert not await frage.is_visible()
        # Abbrechen aendert nichts
        await pg.locator(f"{KARTE} [data-abw-alle]").click()
        assert await frage.is_visible()
        await frage.locator("[data-abw-nein]").click()
        assert not await frage.is_visible()
        assert await pg.locator(f"{KARTE} [data-abw]").count() == 4
        assert await pg.evaluate(OFFEN) == "Alles gespeichert"
        # Die Frage nennt, was zurueckgesetzt wird und was bleibt
        await pg.locator(f"{KARTE} [data-abw-alle]").click()
        weg = await frage.locator("[data-abw-weg] li").all_text_contents()
        assert weg == ["Icon-Größe", "Nacht-Uhr"], weg
        bleibt = await frage.locator("[data-abw-bleibt]").text_content()
        assert "Kachel-Set" in bleibt and "Farbton (Edge)" in bleibt, bleibt
        await pg.screenshot(path=str(tmp_path / "abweichungen_frage.png"), full_page=True)
        await frage.locator("[data-abw-ja]").click()
        assert sorted(await pg.locator(f"{KARTE} [data-abw]").evaluate_all("z => z.map(e => e.dataset.abw)")) == \
            ["tileHueEdge", "tileSet"]
        assert await pg.locator(f"{KARTE} [data-abw-alle]").count() == 0, "nichts mehr fuer Alles auf Standard"
        assert await _zeile(pg, "tileSet").locator("[data-abw-zurueck]").count() == 1, "eigener Knopf bleibt"
        gespeichert = await _speichern(pg, cfg_ordner, "panels.json")
        assert gespeichert["panels"]["flur"]["ui"] == look, gespeichert
    _laufen(cfg_ordner, {"flur": {"title": "Flur", "tabs": ["favoriten"],
                                  "ui": {"iconSize": 44, "nightClock": True, **look}}}, {}, schritte)


def test_vorgaben_nennen_die_ansichten(cfg_ordner, tmp_path):
    async def schritte(pg):
        await pg.locator(".rub", has_text="Vorgaben").click()
        assert await pg.locator(".stab.active").get_attribute("data-sub") == "appearance"
        assert await pg.locator("#pconfHost .spane[data-sub='appearance'] #abwKarte").is_visible(), \
            "oben im ersten Reiter (die Vorgaben haben keinen Reiter Allgemein)"
        name = _zeile(pg, "nameSize")
        assert await name.locator(".abw-wert").text_content() == "19 px"
        assert await name.locator(".abw-ohne").text_content() ==             f"sonst gilt: {konfig.GROESSEN_STANDARD['neu']['nameSize']} px · Standard"
        assert await name.locator("[data-abw-reiter]").count() == 0, "kein Sprung in den Reiter, in dem die Karte steht"
        await _zeile(pg, "dpmsOff").locator("[data-abw-reiter]").click()
        assert await pg.locator(".stab.active").get_attribute("data-sub") == "verhalten"
        await pg.locator(".stab[data-sub='appearance']").click()
        await pg.locator(f"{KARTE} [data-abw-alle]").click()
        weg = await pg.locator(f"{KARTE} .abw-frage [data-abw-weg] li").all_text_contents()
        # default legt der Konfigurator selbst an: drei Ansichten, Kueche setzt nameSize selbst
        assert weg == ["Haupttext-Größe · gilt für 2 von 3 Ansichten",
                       "Display aus nach · gilt für 3 von 3 Ansichten"], weg
        await pg.screenshot(path=str(tmp_path / "abweichungen_vorgaben.png"), full_page=True)
        await pg.locator(f"{KARTE} .abw-frage [data-abw-ja]").click()
        assert await pg.locator(f"{KARTE} [data-abw]").count() == 0
        assert await pg.evaluate(OFFEN) == "Nicht gespeichert: Vorgaben"
        theme = await _speichern(pg, cfg_ordner, "theme.json")
        assert "nameSize" not in theme.get("ui", {}) and "dpmsOff" not in theme.get("ui", {}), theme
    _laufen(cfg_ordner, {"flur": {"title": "Flur", "tabs": ["favoriten"]},
                         "kueche": {"title": "Küche", "tabs": ["favoriten"], "ui": {"nameSize": 22}}},
            {"nameSize": 19, "dpmsOff": 60}, schritte)


def test_werte_lesbar(cfg_ordner):
    """Seiten der Werteleiste mit ihrem Namen, Auswahlwerte mit dem Text, den der
    Editor zeigt, nicht mit dem Schluessel."""
    ui = {"valueBar": ["favoriten", "auswahl"], "tileLayout": "classic", "hausAufbau": "raeume",
          "hausAktivOhne": ["licht", "audio"]}

    async def schritte(pg):
        await _ansicht(pg, "flur")
        wert = {k: await _zeile(pg, k).locator(".abw-wert").text_content() for k in ui}
        assert wert == {"valueBar": "Favoriten, Meine Seite", "tileLayout": "Klassisch",
                        "hausAufbau": konfig.HAUS_AUFBAUTEN["raeume"],
                        "hausAktivOhne": ", ".join(konfig.HAUS_AKTIV_ARTEN[a][0] for a in ("licht", "audio"))}, wert
    _laufen(cfg_ordner, {"flur": {"title": "Flur", "tabs": ["favoriten", "auswahl"],
                                  "pickTabs": [{"name": "Meine Seite", "picks": ["L"]}], "ui": ui}}, {}, schritte)


def test_ohne_abweichungen(cfg_ordner):
    async def schritte(pg):
        await _ansicht(pg, "flur")
        assert await pg.locator(f"{KARTE} [data-abw]").count() == 0
        assert (await pg.locator(f"{KARTE} .abw-leer").text_content()).startswith("Alles auf Standard")
        assert await pg.locator(f"{KARTE} [data-abw-alle]").count() == 0
        await pg.locator(".rub", has_text="Vorgaben").click()
        assert await pg.locator(f"{KARTE} [data-abw]").count() == 0
        assert (await pg.locator(f"{KARTE} .abw-leer").text_content()).startswith("Alles auf Standard")
        assert await pg.locator(f"{KARTE} [data-abw-alle]").count() == 0
    _laufen(cfg_ordner, {"flur": {"title": "Flur", "tabs": ["favoriten"]}}, {}, schritte)
