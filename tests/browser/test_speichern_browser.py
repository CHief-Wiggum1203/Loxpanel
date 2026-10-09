"""Speichern im Konfigurator (config.html) in Chromium: was der Server nicht
uebernimmt, zeigt die Meldungsleiste als Warnung an, statt es still zu
verlieren. Ohne Aenderung meldet das Speichern nichts (kein Fehlalarm fuer
das, was der Konfigurator selbst schreibt). Dateien schreibt hier ein
Stellvertreter - kein Test darf config/ veraendern."""
import asyncio

import pytest

from aiohttp import web

from lox import KONFIGURATOR_GELADEN, W, anlage, serve

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {"X": {"name": "Licht", "type": "Switch", "uuidAction": "X", "room": "r1", "cat": "c1",
                   "states": {"active": "sx"}}}


def test_nicht_uebernommenes_wird_gemeldet(tmp_path):
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten", "raeume"],
                                                      "ui": {"cols": 3, "split": False},
                                                      "tiles": {"X": {"bold": True, "chart": "24h"}}}})
        gespeichert = []
        app._write_panels = gespeichert.append
        app._write_theme = lambda *a: None
        ui = web.Application()
        ui["app"] = app
        for pfad, h in (("/config", W.config_index), ("/api/meta", W.api_meta), ("/api/backup", W.api_backup),
                        ("/api/settings", W.api_settings), ("/i18n.js", W.i18n_js), ("/raster.js", W.raster_js)):
            ui.router.add_get(pfad, h)
        ui.router.add_post("/api/panels", W.api_save_panels)
        ui.router.add_post("/api/theme", W.api_save_theme)
        runner, port = await serve(ui)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                toast = pg.locator("#toast")

                async def speichern():
                    async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
                        await pg.evaluate("save()")
                    j = await (await antwort.value).json()
                    await pg.wait_for_timeout(200)
                    return j

                # 1) ohne Aenderung: nichts verworfen, keine Warnung
                j = await speichern()
                assert j["ok"] and j["verworfen"] == []
                assert "warn" not in (await toast.get_attribute("class"))
                assert (await toast.text_content()).startswith("✓ Gespeichert")

                # 2) ein Feld, das der Server nicht kennt: gemeldet, Warnung bleibt stehen
                await pg.evaluate("PANELS.test.ui = Object.assign(PANELS.test.ui || {}, {neuOption: 5}); markDirty()")
                j = await speichern()
                assert j["verworfen"] == ["Test: ui.neuOption"]
                assert "neuOption" not in (gespeichert[-1]["test"].get("ui") or {})
                assert "warn" in (await toast.get_attribute("class"))
                assert "Nicht übernommen: Test: ui.neuOption" in await toast.text_content()
                await pg.screenshot(path=str(tmp_path / "speichern_warnung.png"))
                await pg.wait_for_timeout(4500)
                assert "show" in (await toast.get_attribute("class")), "Warnung bleibt stehen"

                # 3) naechste Aenderung raeumt sie ab
                await pg.evaluate("markDirty()")
                assert await toast.text_content() == ""
                await b.close()
        finally:
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
