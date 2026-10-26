"""Kamerabild in Chromium (wie Android-WebView und LoxOS): Chromium zeigt
einen Teil von multipart/x-mixed-replace erst, wenn der naechste beginnt;
Content-Length wertet es nicht aus. Darum schickt LoxPanel hinter jedem Bild
gleich Grenze und Kopf des naechsten Teils (bin/kamerastrom.py): Das Bild
steht sofort, nicht erst mit dem naechsten der Kamera."""
import asyncio
import time

import pytest
from aiohttp import web

from lox import Kamera, serve, W
from test_bento_browser import BILD

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

SEITE = '<!doctype html><img id="b" alt="" src="/mjpeg?id=A">'
ZEIGT = "() => { const i = document.getElementById('b'); return i.complete && i.naturalWidth > 0; }"


def test_bild_steht_sofort():
    """Eine Kamera, die alle 4 s ein Bild schickt: Der erste Zuschauer sieht
    ihr erstes Bild sofort, ein spaeter dazukommender das letzte, beide lange
    vor dem naechsten Bild der Kamera. Zwei Browser-Kontexte wie zwei Geraete,
    die Kamera sieht einen Abruf."""
    async def lauf():
        cam = await Kamera(inhalt=lambda pfad, n: BILD, typ="image/png", takt=4).start()
        app = W.App({"host": "", "port": 80})
        app.intercom_cfg = {"A": {"url": cam.adresse("/a")}}
        ui = web.Application()
        ui["app"] = app
        async def seite(_r):
            return web.Response(text=SEITE, content_type="text/html")
        ui.router.add_get("/", seite)
        ui.router.add_get("/mjpeg", W.mjpeg_handler)
        runner, port = await serve(ui)
        zeiten = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                for _ in range(2):
                    pg = await (await b.new_context()).new_page()
                    beginn = time.monotonic()
                    await pg.goto(f"http://127.0.0.1:{port}/")
                    await pg.wait_for_function(ZEIGT, timeout=10000)
                    zeiten.append(time.monotonic() - beginn)
                    await asyncio.sleep(0.5)
                await b.close()
        finally:
            await app.close()
            await runner.cleanup()
            await cam.stop()
        return zeiten, list(cam.abrufe)
    zeiten, abrufe = asyncio.run(lauf())
    assert all(z < 2 for z in zeiten), zeiten
    assert abrufe == ["/a"]
