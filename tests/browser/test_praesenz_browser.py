"""Praesenzmelder in Chromium: am Panel schaltet die Leerlaufzeit das Display
nicht ab, solange der Melder jemanden meldet; wird der Raum leer, geht es aus,
kommt jemand, wieder an. Die Kiosk-App (Fully Kiosk mit JavaScript-
Schnittstelle) ist nachgebaut und protokolliert jeden Schaltbefehl. Dazu die
Auswahl im Konfigurator (Displays); die Datei schreibt ein Stellvertreter."""
import asyncio
import json

import pytest

from aiohttp import web

from lox import KONFIGURATOR_GELADEN, W, anlage, serve, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {
    "PM": {"name": "Präsenz Küche", "type": "PresenceDetector", "uuidAction": "PM", "room": "r1", "cat": "c1",
           "states": {"active": "pm_a", "infoText": "pm_t"}},
    "L": {"name": "Licht", "type": "Switch", "uuidAction": "LA", "room": "r1", "cat": "c1", "isFavorite": True,
          "states": {"active": "sl"}},
}
# Fully Kiosk Browser mit eingeschalteter JavaScript-Schnittstelle, nachgebaut:
# jeder Schaltbefehl landet in window.__fully.
FULLY_JS = """window.__fully = []; window.fully = { _an: true,
  turnScreenOff() { this._an = false; window.__fully.push('aus'); },
  turnScreenOn() { this._an = true; window.__fully.push('an'); },
  isScreenOn() { return this._an; } };"""


def _app(devices: dict, ui: dict | None = None):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"pm_a": 1.0, "sl": 0}              # jemand ist im Raum
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"], "ui": ui or {}}})
    app.devices = W.App._sanitize_devices(devices, set(app.panels))
    app._presence_rebuild()
    app._pending_presence.clear()
    return app


def test_leerlauf_wartet_solange_jemand_da_ist(tmp_path):
    async def lauf():
        app = _app({"kueche": {"presence": "PM"}}, ui={"dpmsOff": 1})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()

                async def panel(geraet):
                    ctx = await b.new_context(viewport={"width": 480, "height": 480})
                    await ctx.add_init_script(FULLY_JS)
                    pg = await ctx.new_page()
                    pg.on("pageerror", lambda e: fehler.append(str(e)))
                    await pg.goto(f"http://127.0.0.1:{port}/?panel=test&device={geraet}")
                    return pg

                kueche, flur = await panel("kueche"), await panel("flur")
                await kueche.wait_for_timeout(2500)          # mehr als die Leerlaufzeit (1 s)
                assert await flur.evaluate("__fully") == ["aus"], "ohne Melder schaltet der Leerlauf ab"
                assert await kueche.evaluate("__fully") == [], "jemand da: das Display bleibt an"
                app._on_value("pm_a", 0.0)                    # Raum leer
                await kueche.wait_for_timeout(800)
                assert await kueche.evaluate("__fully") == ["aus"]
                app._on_value("pm_a", 1.0)                    # jemand kommt
                await kueche.wait_for_timeout(2500)
                assert await kueche.evaluate("__fully") == ["aus", "an"], "wieder an und gehalten"
                await kueche.screenshot(path=str(tmp_path / "praesenz_panel.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


def test_konfigurator_waehlt_und_speichert_den_melder(tmp_path):
    async def lauf():
        app = _app({"kueche": {"presence": "PM"}, "flur": {"scale": "auto"}})
        gespeichert = []
        app._persist_panels_file = lambda panels, devices: gespeichert.append(json.loads(json.dumps(devices)))
        ui = web.Application()
        ui["app"] = app
        for pfad, h in (("/config", W.config_index), ("/api/meta", W.api_meta), ("/api/backup", W.api_backup),
                        ("/api/settings", W.api_settings), ("/api/devices", W.api_devices_get),
                        ("/i18n.js", W.i18n_js), ("/raster.js", W.raster_js)):
            ui.router.add_get(pfad, h)
        ui.router.add_post("/api/devices", W.api_save_devices)
        runner, port = await serve(ui)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.evaluate("async () => { await loadPanelIds(); renderDevices(); await pollDevices(); }")
                kueche = pg.locator('#dev_list .dev[data-name="kueche"]')
                assert await kueche.locator(".dp_presence").input_value() == "PM"
                assert await kueche.locator(".dp_state").text_content() == "gerade: jemand da"
                assert await kueche.locator(".dp_presence option").all_text_contents() == [
                    "— keiner (Display nach der Leerlaufzeit aus) —",
                    "Zentral · Licht (Switch)", "Zentral · Präsenz Küche (PresenceDetector)"]
                assert await pg.locator('#dev_list .dev[data-name="flur"] .dp_state').text_content() == ""
                # Melder vom einen Geraet aufs andere legen und speichern
                await pg.evaluate("""() => { const w = n => document.querySelector(
                        '#dev_list .dev[data-name="' + n + '"] .dp_presence');
                    w('kueche').value = ''; w('flur').value = 'PM'; }""")
                async with pg.expect_response(lambda r: r.url.endswith("/api/devices")
                                              and r.request.method == "POST") as antwort:
                    await pg.evaluate("document.getElementById('dev_save').click()")
                assert (await (await antwort.value).json())["ok"]
                assert gespeichert[-1] == {"flur": {"auto": True, "modes": {}, "scale": "auto", "presence": "PM"}}
                assert app.presence_map == {"pm_a": ["flur"]}
                await pg.screenshot(path=str(tmp_path / "praesenz_konfigurator.png"), full_page=True)
                await b.close()
        finally:
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
