"""Sicherung einspielen im Konfigurator (Chromium): herunterladen, am Server
etwas aendern, dieselbe ZIP einspielen -> Rueckfrage, Neuladen, Ergebnis in
der Rubrik Sicherung. Dazu Abbrechen und eine kaputte Datei. Der Config-Ordner
ist umgeleitet (Fixture cfg_ordner), reconnect() ersetzt."""
import asyncio
import json

import pytest

from aiohttp import web

from lox import W, anlage, serve

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {
    "PM": {"name": "Präsenz Küche", "type": "PresenceDetector", "uuidAction": "PM", "room": "r1", "cat": "c1",
           "states": {"active": "pm_a"}},
    "X": {"name": "Licht", "type": "Switch", "uuidAction": "X", "room": "r1", "cat": "c1", "states": {"active": "x"}},
}
CFG = {"miniserver": {"host": "10.0.0.5", "user": "visu", "pass": "GEHEIM", "port": 443, "verify_tls": False},
       "night": {"control": "PM"}}
PANELS = {"panels": {"wohnen": {"title": "Wohnen", "tabs": ["favoriten"]}}}


def _app():
    app = W.App(W._config(), W._audio_config(), W._audiometa_config())
    app._apply_structure(anlage(BAUSTEINE))
    aufrufe = []

    async def reconnect():
        aufrufe.append(1)
        return 0
    app.reconnect = reconnect
    return app, aufrufe


async def _konfigurator(app, schritte):
    """Server mit den Routen des Konfigurators starten, config.html oeffnen,
    zur Rubrik Sicherung gehen und schritte(page) ausfuehren."""
    ui = web.Application()
    ui["app"] = app
    for pfad, h in (("/config", W.config_index), ("/api/meta", W.api_meta), ("/api/backup", W.api_backup),
                    ("/api/settings", W.api_settings), ("/api/devices", W.api_devices_get), ("/i18n.js", W.i18n_js)):
        ui.router.add_get(pfad, h)
    ui.router.add_post("/api/restore", W.api_restore)
    runner, port = await serve(ui)
    fehler = []
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch()
            pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
            pg.on("pageerror", lambda e: fehler.append(str(e)))
            await pg.goto(f"http://127.0.0.1:{port}/config")
            await pg.wait_for_function("typeof META !== 'undefined' && META.controls && META.controls.length")
            await pg.locator(".rub", has_text="Settings").click()
            await pg.locator(".stab", has_text="Sicherung").click()
            res = await schritte(pg)
            await b.close()
    finally:
        await runner.cleanup()
    assert not fehler, fehler
    return res


def test_herunterladen_und_wieder_einspielen(cfg_ordner, tmp_path):
    for name, doc in (("loxpanel.cfg", CFG), ("panels.json", PANELS)):
        (cfg_ordner / name).write_text(json.dumps(doc), encoding="utf-8")

    async def lauf():
        app, aufrufe = _app()
        dialoge = []

        async def schritte(pg):
            async with pg.expect_download() as dl:
                await pg.locator("#bk_dl").click()
            zip_datei = tmp_path / "sicherung.zip"
            await (await dl.value).save_as(zip_datei)
            # am Server aendert sich etwas, das die Sicherung zurueckholt
            (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"anders": {"title": "Anders"}}}),
                                                    encoding="utf-8")
            app.panels = W.load_panels()

            async def ja(d):
                dialoge.append(d.message)
                await d.accept()
            pg.once("dialog", ja)
            async with pg.expect_navigation():    # nach dem Einspielen laedt die Seite neu
                await pg.locator("#rs_file").set_input_files(str(zip_datei))
            await pg.wait_for_function("(document.querySelector('#rs_result')||{}).textContent"
                                       "&& document.querySelector('#rs_result').textContent.includes('Eingespielt')")
            await pg.screenshot(path=str(tmp_path / "eingespielt.png"))
            return {"text": await pg.locator("#rs_result").inner_text(),
                    "rubrik": await pg.evaluate("document.querySelector('.spane.active').dataset.sub"),
                    "profile": await pg.evaluate("Object.keys(META.panels).sort()")}
        res = await _konfigurator(app, schritte)
        return res, dialoge, app, aufrufe
    res, dialoge, app, aufrufe = asyncio.run(lauf())

    assert len(dialoge) == 1 and "ersetzt die Einstellungen dieses Servers" in dialoge[0]
    assert res["rubrik"] == "backup", "nach dem Neuladen steht die Rubrik Sicherung offen"
    assert res["profile"] == ["wohnen"], "der Konfigurator zeigt den eingespielten Stand"
    text = res["text"]
    assert "✓ Eingespielt: loxpanel.cfg, panels.json" in text, text
    assert "Miniserver: Zugang unverändert" in text and "Kennwort von diesem Server übernommen: Miniserver" in text
    assert "Nicht in der Sicherung, unverändert: theme.json" in text
    assert set(app.panels) == {"wohnen"} and aufrufe == []
    assert json.loads((cfg_ordner / "loxpanel.cfg").read_text(encoding="utf-8"))["miniserver"]["pass"] == "GEHEIM"


def test_abbrechen_und_kaputte_datei(cfg_ordner, tmp_path):
    (cfg_ordner / "panels.json").write_text(json.dumps(PANELS), encoding="utf-8")
    sicherung = W._backup_zip(cfg_ordner)

    async def lauf():
        app, _ = _app()

        async def schritte(pg):
            anfragen = []
            pg.on("request", lambda r: anfragen.append(r.url) if r.url.endswith("/api/restore") else None)
            await pg.evaluate("window.__ohneNeuladen = 1")
            # Abbrechen: nichts wird hochgeladen
            pg.once("dialog", lambda d: asyncio.ensure_future(d.dismiss()))
            await pg.locator("#rs_file").set_input_files(
                {"name": "sicherung.zip", "mimeType": "application/zip", "buffer": sicherung})
            await pg.wait_for_timeout(500)
            abgebrochen = list(anfragen)
            # kaputte Datei: Meldung bleibt stehen, die Seite laedt nicht neu
            pg.once("dialog", lambda d: asyncio.ensure_future(d.accept()))
            await pg.locator("#rs_file").set_input_files(
                {"name": "urlaub.zip", "mimeType": "application/zip", "buffer": b"kein zip"})
            await pg.wait_for_function("document.querySelector('#rs_result').textContent.includes('ZIP')")
            await pg.screenshot(path=str(tmp_path / "kaputt.png"))
            return {"abgebrochen": abgebrochen, "anfragen": anfragen,
                    "text": await pg.locator("#rs_result").inner_text(),
                    "seite": await pg.evaluate("window.__ohneNeuladen")}
        return await _konfigurator(app, schritte), app
    res, app = asyncio.run(lauf())

    assert res["abgebrochen"] == [], "Abbrechen schickt nichts"
    assert len(res["anfragen"]) == 1 and res["text"] == "Das ist keine ZIP-Datei."
    assert res["seite"] == 1, "bei einem Fehler bleibt die Seite stehen"
    assert set(app.panels) == {"wohnen"}


@pytest.mark.parametrize("sprache, erwartet", [
    ("de-DE", ["✓ Eingespielt: loxpanel.cfg",
               "Miniserver: Für 10.9.9.9 (visu) aus der Sicherung fehlt das Kennwort, der bisherige Zugang bleibt.",
               "Kennwort fehlt, bitte unter Settings eintragen: Kamera „Haustür“, Display-Treiber „Flur“",
               "Nicht übernommen: Darstellung: states.active"]),
    ("en-US", ["✓ Restored: loxpanel.cfg",
               "Miniserver: the password for 10.9.9.9 (visu) from the backup is missing, the current access stays.",
               "Password missing, please enter it under Settings: Camera „Haustür“, Display driver „Flur“",
               "Not kept by the server: Darstellung: states.active"]),
])
def test_ergebnis_texte(cfg_ordner, sprache, erwartet):
    """Die Ergebnisanzeige mit allen Teilen, deutsch und englisch; Namen aus
    der Anlage werden nicht als HTML gelesen."""
    async def lauf():
        app, _ = _app()

        async def schritte(pg):
            return await pg.evaluate("""() => { rsZeigen({ok: true, dateien: ['loxpanel.cfg'],
                miniserver: 'kein_kennwort_behalten', miniserverZiel: {host: '10.9.9.9', user: 'visu'},
                kennwoerter: {behalten: [], fehlen: [{art: 'kamera', name: 'Haustür'},
                                                    {art: 'display', name: 'Flur'},
                                                    {art: 'display', name: '<img src=x onerror=alert(1)>'}]},
                verworfen: ['Darstellung: states.active'], nichtEnthalten: []}, false);
              const el = document.querySelector('#rs_result');
              return {text: el.innerText, bilder: el.querySelectorAll('img').length}; }""")
        return await _konfigurator_mit_sprache(app, schritte, sprache)
    res = asyncio.run(lauf())
    for teil in erwartet:
        assert teil in res["text"], (teil, res["text"])
    assert res["bilder"] == 0 and "<img src=x onerror=alert(1)>" in res["text"], "Namen bleiben Text"


async def _konfigurator_mit_sprache(app, schritte, sprache):
    """Wie _konfigurator, aber mit gewaehlter Oberflaechensprache."""
    ui = web.Application()
    ui["app"] = app
    for pfad, h in (("/config", W.config_index), ("/api/meta", W.api_meta), ("/api/settings", W.api_settings),
                    ("/api/devices", W.api_devices_get), ("/i18n.js", W.i18n_js)):
        ui.router.add_get(pfad, h)
    runner, port = await serve(ui)
    fehler = []
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch()
            pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale=sprache)
            await pg.add_init_script(f"try{{ localStorage.setItem('lp_ui_lang', '{sprache[:2]}'); }}catch(e){{}}")
            pg.on("pageerror", lambda e: fehler.append(str(e)))
            await pg.goto(f"http://127.0.0.1:{port}/config")
            await pg.wait_for_function("typeof META !== 'undefined' && META.controls && META.controls.length")
            res = await schritte(pg)
            await b.close()
    finally:
        await runner.cleanup()
    assert not fehler, fehler
    return res
