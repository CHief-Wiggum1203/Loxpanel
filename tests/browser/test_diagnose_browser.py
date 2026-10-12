"""Diagnosepaket im Konfigurator, in Chromium: Jede Geraetekarte hat im Kopf
den Link "Diagnose" (auch offline), Einstellungen -> Sicherung den fuer den
ganzen Server. Ein Klick laedt das ZIP herunter; geprueft wird, dass es das
Paket des richtigen Geraets ist. Der Inhalt selbst steht in
tests/test_diagnose.py. Der Config-Ordner ist umgeleitet (Fixture cfg_ordner)."""
import asyncio
import json
import zipfile

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}}}
PANELS = {"panels": {"wohnen": {"title": "Wohnen", "tabs": ["favoriten"]}},
          "devices": {"wand": {"auto": True, "modes": {"nacht": "wohnen"}}}}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("GET", "/api/diagnose", W.api_diagnose)]


def test_diagnose_aus_geraetekarte_und_sicherung(cfg_ordner, tmp_path):
    async def lauf():
        (cfg_ordner / "panels.json").write_text(json.dumps(PANELS), encoding="utf-8")
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"sl": 0}
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler, m = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE", accept_downloads=True)
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator(".rub", has_text="Geräte").click()
                link = pg.locator('#geraete .gk[data-gk="wand"] .gk-kopf a[data-diagnose]')
                await link.wait_for()
                m["text"] = await link.text_content()
                m["href"] = await link.get_attribute("href")
                async with pg.expect_download() as dl:
                    await link.click()
                d = await dl.value
                await d.save_as(tmp_path / "geraet.zip")
                m["datei_geraet"] = d.suggested_filename
                async with pg.expect_download() as dl:
                    await pg.evaluate("document.getElementById('dg_dl').click()")
                d = await dl.value
                await d.save_as(tmp_path / "server.zip")
                m["datei_server"] = d.suggested_filename
                await b.close()
            return m, fehler
        finally:
            bc.cancel()
            await runner.cleanup()

    m, fehler = asyncio.run(lauf())
    assert not fehler, fehler
    assert m["text"] == "Diagnose" and m["href"] == "/api/diagnose?device=wand", m
    assert m["datei_geraet"].startswith("loxpanel-diagnose-wand-") and m["datei_server"].startswith(
        "loxpanel-diagnose-server-"), m
    with zipfile.ZipFile(tmp_path / "geraet.zip") as z:
        assert json.loads(z.read("diagnose.json"))["geraet"]["name"] == "wand"
    with zipfile.ZipFile(tmp_path / "server.zip") as z:
        assert [g["name"] for g in json.loads(z.read("diagnose.json"))["geraete"]] == ["wand"]
