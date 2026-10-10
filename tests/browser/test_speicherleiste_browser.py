"""Eine Speicherleiste fuer den ganzen Konfigurator (Konzept "Konfigurator neu
ordnen", Schritt 2), in Chromium bedient wie von Hand: Aenderungen unter
Ansichten, Geraete und Einstellungen sammeln sich in der Leiste unten, die nennt,
was offen ist, und speichert alles in einem Zug. Dabei ueberschreibt kein
Nachladen eine noch offene Eingabe eines anderen Bereichs. "Ansicht loeschen"
gilt nach der Rueckfrage sofort und nimmt andere offene Aenderungen nicht mit.
Neuladen oder Schliessen der Seite fragt nach, solange etwas offen ist. Der
Config-Ordner ist umgeleitet (Fixture cfg_ordner)."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}}}
PANELS = {"panels": {"wohnen": {"title": "Wohnen", "tabs": ["favoriten"]},
                     "kueche": {"title": "Küche", "tabs": ["favoriten"]}},
          "devices": {"flur": {"auto": True, "modes": {"nacht": "kueche"}}}}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/devices", W.api_save_devices),
          ("POST", "/api/panels", W.api_save_panels), ("POST", "/api/theme", W.api_save_theme),
          ("POST", "/api/settings/calendar", W.api_settings_calendar),
          ("POST", "/api/settings/audiometa", W.api_settings_audiometa),
          ("POST", "/api/settings/night", W.api_settings_night)]
# Seite wuerde beim Neuladen nachfragen (beforeunload abgebrochen)?
FRAGT = "() => { const e = new Event('beforeunload', {cancelable: true}); dispatchEvent(e); return e.defaultPrevented; }"


def _app(cfg_ordner):
    (cfg_ordner / "panels.json").write_text(json.dumps(PANELS), encoding="utf-8")
    app = W.App({"host": "", "port": 80})       # liest Ansichten und Geraete aus panels.json
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"sl": 0}
    return app


def _datei(cfg_ordner, name):
    return json.loads((cfg_ordner / name).read_text(encoding="utf-8"))


async def _konfigurator(b, port, fehler):
    pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
    pg.on("pageerror", lambda e: fehler.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{port}/config")
    await pg.wait_for_function(KONFIGURATOR_GELADEN)
    return pg


async def _titel_aendern(pg, ansicht, titel):
    await pg.locator(".rub", has_text="Ansichten").click()
    await pg.locator("#plist .pitem", has_text=ansicht).click()
    await pg.locator("#subtabs .stab", has_text="Allgemein").click()
    await pg.locator("#fTitle").fill(titel)


async def _offen(pg):
    return await pg.locator("#offenTxt").text_content()


def test_eine_leiste_speichert_alles(cfg_ordner, tmp_path):
    """Ansicht, Geraet und Kalender geaendert: die Leiste nennt alle drei, ein
    Klick speichert alle drei. Das Speichern der Ansichten laedt die Geraeteliste
    neu; die noch offene Eingabe unter Geraete geht dabei nicht verloren."""
    async def lauf():
        app = _app(cfg_ordner)
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _konfigurator(b, port, fehler)
                await pg.locator(".rub", has_text="Ansichten").click()
                assert await _offen(pg) == "Alles gespeichert"
                assert await pg.locator("#saveBtn").is_disabled(), "nichts offen, nichts zu speichern"
                assert not await pg.evaluate(FRAGT)

                await _titel_aendern(pg, "Wohnen", "Wohnzimmer")
                await pg.locator(".rub", has_text="Geräte").click()
                assert await pg.locator("#savebar").is_visible(), "die Leiste steht auch unter Geräte"
                await pg.locator("#displaysHost summary", has_text="Betriebsmodus-Automatik").click()
                await pg.locator('#dev_list .dev[data-name="flur"] .dev_auto').uncheck()
                await pg.locator(".rub", has_text="Einstellungen").click()
                await pg.locator("#subtabs .stab", has_text="Kalender & Wetter").click()
                await pg.locator("#cal_name").fill("Familie")
                assert await _offen(pg) == "Nicht gespeichert: Ansicht Wohnzimmer, Geräte, Kalender & Wetter"
                assert await pg.evaluate(FRAGT), "Neuladen fragt nach"
                await pg.screenshot(path=str(tmp_path / "speicherleiste_offen.png"))

                await pg.locator("#saveBtn").click()
                await pg.wait_for_function("document.querySelector('#offenTxt').textContent === 'Alles gespeichert'")
                meldung = await pg.locator("#toast").text_content()
                assert meldung.startswith("✓ Gespeichert (3 Ansichten)"), meldung   # mit „default“, die der Konfigurator anlegt
                assert "✓ Gespeichert: Geräte" in meldung and "✓ Gespeichert: Kalender & Wetter" in meldung, meldung
                doc = _datei(cfg_ordner, "panels.json")
                assert doc["panels"]["wohnen"]["title"] == "Wohnzimmer"
                assert doc["devices"]["flur"]["auto"] is False, "Geräte-Eingabe überlebt das Neuladen der Ansichten"
                assert _datei(cfg_ordner, "loxpanel.cfg")["calendar"]["name"] == "Familie"
                assert await pg.locator("#saveBtn").is_disabled()
                assert not await pg.evaluate(FRAGT)

                # Nach dem Nachladen der Einstellungen steht das Gespeicherte in den Feldern
                await pg.wait_for_timeout(1800)
                assert await pg.locator("#cal_name").input_value() == "Familie"
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


def test_nachladen_ueberschreibt_keine_offene_eingabe(cfg_ordner):
    """loadSettings() laeuft nach jedem Speichern und nach "Verbinden &
    Speichern" des Miniservers. Offene Eingaben (Audio, Kalender) bleiben dabei
    stehen; nur ein gespeicherter Bereich holt den Stand des Servers."""
    async def lauf():
        app = _app(cfg_ordner)
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _konfigurator(b, port, fehler)
                await pg.locator(".rub", has_text="Einstellungen").click()
                await pg.locator("#subtabs .stab", has_text="Audio").click()
                vorher = await pg.locator("#am_enabled").is_checked()
                await pg.locator("#am_enabled").set_checked(not vorher)
                await pg.locator("#subtabs .stab", has_text="Kalender & Wetter").click()
                await pg.locator("#cal_add").click()
                await pg.locator("#cal_list .cal_n").fill("Müll")
                await pg.locator("#cal_days").fill("21")
                assert await _offen(pg) == "Nicht gespeichert: Audio, Kalender & Wetter"

                await pg.evaluate("loadSettings()")
                assert await pg.locator("#am_enabled").is_checked() is (not vorher)
                assert await pg.locator("#cal_list .cal_n").input_value() == "Müll"
                assert await pg.locator("#cal_days").input_value() == "21"
                assert await _offen(pg) == "Nicht gespeichert: Audio, Kalender & Wetter"
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


def test_ansicht_loeschen_gilt_sofort(cfg_ordner):
    """"Ansicht löschen" schreibt nach der Rueckfrage sofort, ohne "Speichern".
    Eine offene Aenderung an einer anderen Ansicht geht dabei nicht mit: Der
    Server behaelt deren alten Stand, die Leiste nennt sie weiter."""
    async def lauf():
        app = _app(cfg_ordner)
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler, fragen = [], []

        async def dialog(d):
            fragen.append(d.message)
            await d.accept()
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _konfigurator(b, port, fehler)
                pg.on("dialog", dialog)
                await _titel_aendern(pg, "Küche", "Kochen")
                await pg.locator("#plist .pitem", has_text="Wohnen").click()
                async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
                    await pg.locator("#delBtn").click()
                assert (await (await antwort.value).json())["ok"]
                assert fragen and "wohnen" in fragen[0] and "sofort" in fragen[0], fragen
                await pg.wait_for_function("document.querySelector('#toast').textContent === '✓ Gelöscht: wohnen'")

                doc = _datei(cfg_ordner, "panels.json")
                assert sorted(doc["panels"]) == ["kueche"], doc["panels"]
                assert doc["panels"]["kueche"]["title"] == "Küche", "die offene Änderung ging nicht mit"
                assert await pg.locator("#plist .pitem", has_text="Wohnen").count() == 0
                assert await _offen(pg) == "Nicht gespeichert: Ansicht Kochen"

                # Eine nie gespeicherte Ansicht verschwindet ohne Anfrage an den Server
                await pg.evaluate("PANELS.neu = {title: 'Neu', tabs: ['favoriten']}; cur = 'neu'; markDirty(); setRubric('pconf')")
                anfragen = []
                pg.on("request", lambda r: anfragen.append(r.url) if r.url.endswith("/api/panels") else None)
                await pg.locator("#delBtn").click()
                await pg.wait_for_function("document.querySelector('#toast').textContent === '✓ Gelöscht: neu'")
                assert anfragen == []
                assert await _offen(pg) == "Nicht gespeichert: Ansicht Kochen"

                await pg.locator("#saveBtn").click()
                await pg.wait_for_function("document.querySelector('#offenTxt').textContent === 'Alles gespeichert'")
                assert _datei(cfg_ordner, "panels.json")["panels"]["kueche"]["title"] == "Kochen"
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


def test_geraet_entfernen_nimmt_offene_aenderungen_nicht_mit(cfg_ordner):
    """"Entfernen" unter Geraete gilt sofort; offene Eingaben an einem anderen
    Geraet bleiben offen und erst "Speichern" schreibt sie."""
    async def lauf():
        (cfg_ordner / "panels.json").write_text(json.dumps(
            {**PANELS, "devices": {**PANELS["devices"], "tablet": {"auto": True, "modes": {"gaeste": "wohnen"}}}}),
            encoding="utf-8")
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"sl": 0}
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _konfigurator(b, port, fehler)
                pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
                await pg.locator(".rub", has_text="Geräte").click()
                await pg.locator("#displaysHost summary", has_text="Betriebsmodus-Automatik").click()
                await pg.locator('#dev_list .dev[data-name="tablet"] .dev_auto').uncheck()
                assert await _offen(pg) == "Nicht gespeichert: Geräte"
                await pg.locator('#ag_list .ag[data-name="flur"] [data-act="entfernen"]').click()
                await pg.wait_for_function("document.querySelector('#ag_toast').textContent === '✓ Entfernt: flur'")
                doc = _datei(cfg_ordner, "panels.json")
                assert sorted(doc["devices"]) == ["tablet"]
                assert doc["devices"]["tablet"]["auto"] is True, "die offene Eingabe ging nicht mit"
                assert await _offen(pg) == "Nicht gespeichert: Geräte"
                assert not await pg.locator('#dev_list .dev[data-name="tablet"] .dev_auto').is_checked()

                await pg.locator("#saveBtn").click()
                await pg.wait_for_function("document.querySelector('#offenTxt').textContent === 'Alles gespeichert'")
                doc = _datei(cfg_ordner, "panels.json")
                assert sorted(doc["devices"]) == ["tablet"] and doc["devices"]["tablet"]["auto"] is False, doc
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


def test_geraete_warten_auf_die_ansichten(cfg_ordner):
    """Scheitert das Speichern der Ansichten, bleiben die Geraete offen: Ihre
    Betriebsmodi koennen auf eine Ansicht zeigen, die der Server noch nicht
    kennt und darum verwerfen wuerde. Die Leiste nennt beides weiter."""
    async def lauf():
        app = _app(cfg_ordner)
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler, geraete_post = [], []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _konfigurator(b, port, fehler)
                await pg.route("**/api/panels", lambda r: r.fulfill(
                    status=500, content_type="application/json", body=json.dumps({"ok": False, "error": "Platte voll"})))
                pg.on("request", lambda r: geraete_post.append(r.url)
                      if r.url.endswith("/api/devices") and r.method == "POST" else None)
                await _titel_aendern(pg, "Wohnen", "Wohnzimmer")
                await pg.locator(".rub", has_text="Geräte").click()
                await pg.locator("#displaysHost summary", has_text="Betriebsmodus-Automatik").click()
                await pg.locator('#dev_list .dev[data-name="flur"] .dev_auto').uncheck()
                await pg.locator("#saveBtn").click()
                await pg.wait_for_function("document.querySelector('#toast').textContent.includes('Platte voll')")
                assert geraete_post == []
                assert await _offen(pg) == "Nicht gespeichert: Ansicht Wohnzimmer, Geräte"
                assert "err" in await pg.locator("#toast").get_attribute("class")
                assert _datei(cfg_ordner, "panels.json")["devices"]["flur"]["auto"] is True

                await pg.unroute("**/api/panels")
                await pg.locator("#saveBtn").click()
                await pg.wait_for_function("document.querySelector('#offenTxt').textContent === 'Alles gespeichert'")
                doc = _datei(cfg_ordner, "panels.json")
                assert doc["panels"]["wohnen"]["title"] == "Wohnzimmer" and doc["devices"]["flur"]["auto"] is False
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
