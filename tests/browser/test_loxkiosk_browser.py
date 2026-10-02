"""LoxPanel-App (JS-Bruecke LoxKiosk) in Chromium: Die Visu meldet die App als
Kiosk-App (?kiosk=loxpanel), der Server fuehrt sie in der Geraeteliste und
schaltet ihr Display (Display an/aus, Notify weckt). Die Leerlaufzeit regelt
die App selbst, die Seite schaltet dort nicht ab. Die Bruecke ist nachgebaut
und protokolliert jeden Aufruf; Fully Kiosk als Gegenprobe wie bisher."""
import asyncio

import aiohttp
import pytest

from lox import W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

# JS-Bruecke der LoxPanel-App (KioskActivity.KioskBridge), nachgebaut
LOXKIOSK_JS = """window.__lox = []; window.LoxKiosk = { _an: true,
  setDisplayOff(s) { window.__lox.push('dpms:' + s); },
  turnScreenOff() { this._an = false; window.__lox.push('aus'); },
  turnScreenOn() { this._an = true; window.__lox.push('an'); },
  isScreenOn() { return this._an; } };"""
FULLY_JS = """window.__fully = []; window.fully = { _an: true,
  turnScreenOff() { this._an = false; window.__fully.push('aus'); },
  turnScreenOn() { this._an = true; window.__fully.push('an'); },
  isScreenOn() { return this._an; } };"""
BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "LA", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}}}
ROUTEN = (("GET", "/api/devices", W.api_devices_get), ("GET", "/api/display", W.api_display),
          ("GET", "/api/notify", W.api_notify))


def _app(dpms: int):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"sl": 0}
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"], "ui": {"dpmsOff": dpms}}})
    return app


def _typ(app, name):
    return next((d["type"] for d in app.device_list()["devices"] if d["name"] == name), None)


def test_app_meldet_sich_und_laesst_sich_schalten(tmp_path):
    async def lauf():
        app = _app(dpms=1)
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p, aiohttp.ClientSession() as s:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": 480, "height": 480})
                await ctx.add_init_script(LOXKIOSK_JS)
                pg = await ctx.new_page()
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test&device=wand")
                await pg.wait_for_timeout(2500)        # laenger als dpmsOff (1 s)
                assert _typ(app, "wand") == "loxpanel", app.device_list()
                lox = await pg.evaluate("__lox")
                assert "dpms:1" in lox, lox
                assert "aus" not in lox, "die App regelt die Leerlaufzeit selbst, die Seite haelt sich raus"

                async def schritt(url):
                    async with s.get(f"http://127.0.0.1:{port}{url}") as r:
                        assert r.status == 200, await r.text()
                    await pg.wait_for_timeout(600)
                    return [x for x in await pg.evaluate("__lox") if not x.startswith("dpms:")]

                assert await schritt("/api/display?on=0&device=wand") == ["aus"]
                assert await schritt("/api/notify?device=wand&text=Klingel") == ["aus", "an"], "Notify weckt"
                assert await schritt("/api/display?on=0&device=wand") == ["aus", "an", "aus"]
                assert await schritt("/api/display?on=1&device=wand") == ["aus", "an", "aus", "an"]
                assert await schritt("/api/display?on=1&device=wand") == ["aus", "an", "aus", "an"], \
                    "schon an: kein zweites turnScreenOn"
                await pg.screenshot(path=str(tmp_path / "loxkiosk.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


def test_fully_wie_bisher():
    async def lauf():
        app = _app(dpms=1)
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": 480, "height": 480})
                await ctx.add_init_script(FULLY_JS)
                pg = await ctx.new_page()
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test&device=flur")
                await pg.wait_for_timeout(2500)
                assert _typ(app, "flur") == "fully"
                assert await pg.evaluate("__fully") == ["aus"], "Fully: die Seite schaltet nach dpmsOff ab"
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


def test_server_nimmt_nur_bekannte_kiosk_apps():
    async def lauf():
        app = _app(dpms=0)
        runner, port, bc = await visu_starten(app, ROUTEN)
        try:
            async with aiohttp.ClientSession() as s:
                verb = []
                for name, kiosk in (("a", "loxpanel"), ("b", "fully"), ("c", "erfunden"), ("d", "")):
                    verb.append(await s.ws_connect(f"http://127.0.0.1:{port}/ws?panel=test&device={name}&kiosk={kiosk}"))
                await asyncio.sleep(0.3)
                assert [_typ(app, n) for n in "abcd"] == ["loxpanel", "fully", "browser", "browser"]
                for w in verb:
                    await w.close()
        finally:
            bc.cancel()
            await runner.cleanup()
    asyncio.run(lauf())


def test_konfigurator_zeigt_die_app():
    async def lauf():
        app = _app(dpms=0)
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page()
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function("typeof deviceRow === 'function' && typeof anonRow === 'function'")
                html = await pg.evaluate("""() => {
                  const d = t => ({name: 'wand', type: t, online: true, connections: 1, profile: '',
                                   ip: '127.0.0.1', agent: null, screen: {}});
                  return { app: deviceRow(d('loxpanel')), fully: deviceRow(d('fully')),
                           browser: deviceRow(d('browser')),
                           anonApp: anonRow({ip: '10.0.0.7', kiosk: 'loxpanel', profile: '', screen: {}}),
                           anonBrowser: anonRow({ip: '10.0.0.8', kiosk: '', profile: '', screen: {}}) };
                }""")
                assert "LoxPanel-App" in html["app"] and 'data-act="dispoff"' in html["app"] \
                    and 'data-act="dispon"' in html["app"], html["app"]
                assert 'data-act="dispoff"' in html["fully"] and "Fully Kiosk" in html["fully"]
                assert 'data-act="dispoff"' not in html["browser"]
                assert "LoxPanel-App" in html["anonApp"] and "Browser" in html["anonBrowser"]
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
