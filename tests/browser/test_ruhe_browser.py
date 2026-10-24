"""Ruhemodus in Chromium (LoxOS, docs/VISION.md "Ruhemodus"): Mit
devices[name].ruhe steuert der Praesenzmelder die Uhr-Seite statt der
Leerlaufzeit. Niemand da: die Nacht-Uhr steht, zu jeder Tageszeit, und das
Display bleibt an; jemand kommt: die Seite von vorher steht wieder da. Die
Kiosk-App (Fully Kiosk mit JavaScript-Schnittstelle) ist nachgebaut wie in
test_praesenz_browser.py und protokolliert jeden Schaltbefehl. Dazu das
Kaestchen im Konfigurator (Geraete); die Datei schreibt ein Stellvertreter."""
import asyncio
import json

import pytest

from aiohttp import web

from lox import KONFIGURATOR_GELADEN, W, anlage, serve, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {
    "PM": {"name": "Präsenz Büro", "type": "PresenceDetector", "uuidAction": "PM", "room": "r1", "cat": "c1",
           "states": {"active": "pm_a", "infoText": "pm_t"}},
    "L": {"name": "Licht", "type": "Switch", "uuidAction": "LA", "room": "r1", "cat": "c1", "isFavorite": True,
          "states": {"active": "sl"}},
}
FULLY_JS = """window.__fully = []; window.fully = { _an: true,
  turnScreenOff() { this._an = false; window.__fully.push('aus'); },
  turnScreenOn() { this._an = true; window.__fully.push('an'); },
  isScreenOn() { return this._an; } };"""
TABS = ["favoriten", "zentral"]
# Uhr-Seite sichtbar und als Nacht-Uhr gezeichnet
RUHE_UHR = """() => { const s = document.getElementById('saver');
  return !s.classList.contains('hidden') && s.classList.contains('nacht')
    && !document.getElementById('svNacht').hidden; }"""
UHR_WEG = "() => document.getElementById('saver').classList.contains('hidden')"


def _app(ruhe: bool = True, dpms: int = 1):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"pm_a": 1.0, "sl": 0}              # jemand ist im Raum
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": TABS, "ui": {"dpmsOff": dpms}}})
    geraet = {"presence": "PM", **({"ruhe": True} if ruhe else {})}
    app.devices = W.App._sanitize_devices({"streifen": geraet}, set(app.panels))
    app._presence_rebuild()
    app._pending_presence.clear()
    return app


async def _mit_visu(app, schritte, tmp_path, bild):
    """Visu des Geraets streifen (2560x720) oeffnen, warten, bis sie steht,
    dann schritte(pg) ausfuehren. Seitenfehler scheitern den Test."""
    runner, port, bc = await visu_starten(app)
    fehler = []
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch()
            ctx = await b.new_context(viewport={"width": 2560, "height": 720})
            await ctx.add_init_script(FULLY_JS)
            pg = await ctx.new_page()
            pg.on("pageerror", lambda e: fehler.append(str(e)))
            await pg.goto(f"http://127.0.0.1:{port}/?panel=test&device=streifen")
            await pg.wait_for_function("() => typeof view !== 'undefined' && !!view && !!view.route")
            await schritte(pg)
            await pg.screenshot(path=str(tmp_path / bild))
            await b.close()
    finally:
        bc.cancel()
        await runner.cleanup()
    assert not fehler, fehler


def test_ruhe_uhr_wenn_niemand_da(tmp_path):
    app = _app()

    async def schritte(pg):
        await pg.wait_for_function(UHR_WEG)               # jemand da: keine Uhr-Seite nach dem Laden
        await pg.evaluate("nachRuhe()")                   # Leerlaufzeit abgelaufen
        assert await pg.evaluate(UHR_WEG), "jemand da: der Ruhe-Timer zeigt keine Uhr"
        app._on_value("pm_a", 0.0)                        # Raum leer
        await pg.wait_for_function(RUHE_UHR)
        await pg.wait_for_timeout(1500)                   # laenger als die Leerlaufzeit (1 s)
        assert await pg.evaluate("__fully") == [], "Ruhemodus: das Display bleibt an"
        assert await pg.evaluate(RUHE_UHR)
    asyncio.run(_mit_visu(app, schritte, tmp_path, "ruhe_uhr.png"))


def test_aufwachen_zeigt_die_seite_von_vorher(tmp_path):
    app = _app()

    async def schritte(pg):
        await pg.wait_for_function(UHR_WEG)
        await pg.evaluate("goTab('zentral')")
        await pg.wait_for_function("() => view.route.tab === 'zentral'")
        app._on_value("pm_a", 0.0)
        await pg.wait_for_function(RUHE_UHR)
        app._on_value("pm_a", 1.0)                        # jemand kommt
        await pg.wait_for_function(UHR_WEG)
        await pg.wait_for_timeout(300)
        assert await pg.evaluate("view.route.tab") == "zentral", "die Seite von vorher, nicht die erste"
        assert await pg.evaluate("document.getElementById('saver').classList.contains('nacht')") is False
    asyncio.run(_mit_visu(app, schritte, tmp_path, "ruhe_aufgewacht.png"))


def test_tipp_weckt_und_ruhe_kehrt_zurueck(tmp_path):
    app = _app()

    async def schritte(pg):
        await pg.wait_for_function(UHR_WEG)
        await pg.evaluate("goTab('zentral')")
        await pg.wait_for_function("() => view.route.tab === 'zentral'")
        app._on_value("pm_a", 0.0)
        await pg.wait_for_function(RUHE_UHR)
        await pg.mouse.click(1280, 360)                   # Tipp auf die Uhr-Seite
        await pg.wait_for_function(UHR_WEG)
        await pg.wait_for_timeout(1500)                   # Leerlaufzeit (1 s) schaltet nichts ab
        assert await pg.evaluate("__fully") == []
        await pg.evaluate("nachRuhe()")                   # SAVER_IDLE_MS ohne Beruehrung
        await pg.wait_for_function(RUHE_UHR)
        assert await pg.evaluate("view.route.tab") == "zentral", "Ruhe wechselt die Seite nicht"
    asyncio.run(_mit_visu(app, schritte, tmp_path, "ruhe_tipp.png"))


def test_melder_flackert(tmp_path):
    app = _app()

    async def schritte(pg):
        await pg.wait_for_function(UHR_WEG)
        for wert in (0.0, 1.0, 0.0, 1.0):
            app._on_value("pm_a", wert)
            await pg.wait_for_timeout(60)
        await pg.wait_for_timeout(800)
        assert await pg.evaluate(UHR_WEG), "zuletzt jemand da: keine Uhr"
        for wert in (0.0, 1.0, 0.0):
            app._on_value("pm_a", wert)
            await pg.wait_for_timeout(60)
        await pg.wait_for_function(RUHE_UHR)
        assert await pg.evaluate("__fully") == []
    asyncio.run(_mit_visu(app, schritte, tmp_path, "ruhe_flackern.png"))


def test_ohne_ruhe_wie_bisher(tmp_path):
    app = _app(ruhe=False, dpms=0)

    async def schritte(pg):
        await pg.wait_for_timeout(500)
        assert await pg.evaluate("RUHE") is False
        app._on_value("pm_a", 0.0)
        await pg.wait_for_function("() => __fully.includes('aus')")
        assert await pg.evaluate("nachtUhrAn()") is False
    asyncio.run(_mit_visu(app, schritte, tmp_path, "ohne_ruhe.png"))


def test_ruhe_aus_per_nachricht(tmp_path):
    app = _app()

    async def schritte(pg):
        await pg.wait_for_function(UHR_WEG)
        app._on_value("pm_a", 0.0)
        await pg.wait_for_function(RUHE_UHR)
        for ws in list(app.conn_info):                    # so schickt es POST /api/devices
            await app._send_or_drop(ws, {"t": "ruhe", "ruhe": False})
        await pg.wait_for_function("() => RUHE === false")
        assert await pg.evaluate("nachtUhrAn()") is False, "tagsueber keine Nacht-Uhr mehr"
        assert await pg.evaluate("document.getElementById('saver').classList.contains('nacht')") is False
    asyncio.run(_mit_visu(app, schritte, tmp_path, "ruhe_aus.png"))


def test_display_aus_per_befehl_auch_mit_ruhe(tmp_path):
    """/api/display?on=0 (etwa aus Loxone) ist ein bewusster Befehl: Er
    schaltet auch mit Ruhemodus ab."""
    app = _app()

    async def schritte(pg):
        await pg.wait_for_function(UHR_WEG)
        for ws in list(app.conn_info):                    # so schickt es /api/display?on=0
            await app._send_or_drop(ws, {"t": "display", "on": False})
        await pg.wait_for_function("() => __fully.includes('aus')")
    asyncio.run(_mit_visu(app, schritte, tmp_path, "ruhe_befehl_aus.png"))


def test_konfigurator_kaestchen_nur_mit_melder(tmp_path):
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"pm_a": 1.0, "sl": 0}
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": TABS}})
        app.devices = W.App._sanitize_devices({"streifen": {"presence": "PM"}, "flur": {"scale": "auto"}},
                                              set(app.panels))
        app._presence_rebuild()
        gespeichert = []
        app._persist_panels_file = lambda panels, devices: gespeichert.append(json.loads(json.dumps(devices)))
        ui = web.Application()
        ui["app"] = app
        for pfad, h in (("/config", W.config_index), ("/api/meta", W.api_meta), ("/api/backup", W.api_backup),
                        ("/api/settings", W.api_settings), ("/api/devices", W.api_devices_get),
                        ("/i18n.js", W.i18n_js), ("/raster.js", W.raster_js), ("/config.css", W.config_css),
                        ("/config/{name}", W.config_js)):
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
                streifen = pg.locator('#geraete .dev[data-name="streifen"] .dp_ruhe')
                flur = pg.locator('#geraete .dev[data-name="flur"] .dp_ruhe')
                assert await flur.is_disabled(), "ohne Melder nicht waehlbar"
                assert await streifen.is_enabled() and not await streifen.is_checked()
                label = await pg.locator('#geraete .dev[data-name="streifen"] label:has(.dp_ruhe)').text_content()
                assert label.strip() == "Ruhe-Uhr statt Display aus"
                # Melder am Flur waehlen: das Kaestchen wird waehlbar
                await pg.evaluate("""() => { const w = document.querySelector(
                        '#geraete .dev[data-name="flur"] .dp_presence');
                    w.value = 'PM'; w.dispatchEvent(new Event('change', {bubbles: true})); }""")
                assert await flur.is_enabled()
                await pg.evaluate("""() => { const k = document.querySelector(
                        '#geraete .dev[data-name="streifen"] .dp_ruhe');
                    k.checked = true; k.dispatchEvent(new Event('change', {bubbles: true})); }""")
                async with pg.expect_response(lambda r: r.url.endswith("/api/devices")
                                              and r.request.method == "POST") as antwort:
                    await pg.evaluate("document.getElementById('saveBtn').click()")
                assert (await (await antwort.value).json())["ok"]
                assert gespeichert[-1]["streifen"].get("ruhe") is True
                assert "ruhe" not in gespeichert[-1]["flur"]
                # Gespeichert und neu geladen: das Kaestchen steht
                await pg.evaluate("async () => { await loadPanelIds(); renderDevices(); }")
                assert await streifen.is_checked()
                await pg.screenshot(path=str(tmp_path / "ruhe_konfigurator.png"), full_page=True)
                await b.close()
        finally:
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
