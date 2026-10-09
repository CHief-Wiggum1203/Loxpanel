"""Versionszeile in der Seitenleiste des Konfigurators (Chromium): Version,
Commit kurz (ganz im Tooltip) und Bauzeit in der Ortszeit des Browsers; ohne
bekannte Version steht das da. Quelle ist /api/settings (bin/version_info.py)."""
import asyncio

import pytest
from aiohttp import web

from lox import KONFIGURATOR_GELADEN, W, anlage, serve

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

COMMIT = "abcdef0123456789abcdef0123456789abcdef01"
SCHALTER = {"S1": {"name": "Licht", "type": "Switch", "uuidAction": "S1", "room": "r1", "cat": "c1",
                   "states": {"active": "s1"}}}


def test_versionszeile(cfg_ordner, monkeypatch, tmp_path):
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(SCHALTER))
        ui = web.Application()
        ui["app"] = app
        for pfad, h in (("/config", W.config_index), ("/api/meta", W.api_meta), ("/api/settings", W.api_settings),
                        ("/api/devices", W.api_devices_get), ("/i18n.js", W.i18n_js), ("/raster.js", W.raster_js)):
            ui.router.add_get(pfad, h)
        runner, port = await serve(ui)
        fehler, res = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(locale="de-DE", timezone_id="Europe/Berlin")
                pg.on("pageerror", lambda e: fehler.append(str(e)))

                async def zeile():
                    await pg.goto(f"http://127.0.0.1:{port}/config")
                    await pg.wait_for_function(KONFIGURATOR_GELADEN)
                    await pg.wait_for_function("document.querySelector('#lpver').textContent !== ''")
                    el = pg.locator("#lpver")
                    return await el.inner_text(), await el.get_attribute("title")

                monkeypatch.setattr(W, "VERSION", {"version": "9.8.7", "commit": COMMIT,
                                                   "gebaut": "2026-10-03T12:15:00Z"})
                res["de"] = await zeile()
                await pg.screenshot(path=str(tmp_path / "version.png"))
                await pg.evaluate("localStorage.setItem('lp_ui_lang', 'en')")
                res["en"] = await zeile()
                monkeypatch.setattr(W, "VERSION", {"version": "", "commit": "", "gebaut": ""})
                res["unbekannt"] = await zeile()
                await b.close()
        finally:
            await runner.cleanup()
        assert not fehler, fehler
        return res
    res = asyncio.run(lauf())

    assert res["de"] == ("LoxPanel 9.8.7 · abcdef0 · gebaut 03.10.2026, 14:15", COMMIT)
    assert res["en"] == ("LoxPanel 9.8.7 · abcdef0 · built 03.10.2026, 14:15", COMMIT)
    assert res["unbekannt"] == ("Version unknown", "")
