"""Token-Erneuerung (ARCHITEKTUR.md §3.4): Laeuft das Token ab, waehrend der
WebSocket stabil bleibt, muessen Befehle, Verlaeufe und Icons trotzdem
funktionieren - ohne dass jede Anfrage eine eigene Anmeldung ausloest."""
import asyncio
import time

import aiohttp
from aiohttp import web

from lox import Anmeldung, Miniserver, W, neue_app, serve


def _ablaufen(app, ms):
    """Token am Nachbau ungueltig machen und die Anmeldesperre abgelaufen setzen."""
    ms.token = "ABGELAUFEN"
    app._auth_at -= W.TOKEN_RENEW_MIN


def _lauf(koerper):
    async def lauf():
        ms = await Miniserver().start()
        app = neue_app(ms)
        try:
            await koerper(app, ms)
        finally:
            await app.icon_session.close()
            await ms.stop()
    asyncio.run(lauf())


def test_befehl_nach_ablauf(miniserver_http):
    async def k(app, ms):
        assert await app.command("U1", "on") == "200" and app.client.n == 0
        _ablaufen(app, ms)
        assert await app.command("U1", "off") == "200"
        assert app.client.n == 1 and app.jwt == ms.token
        assert ms.io == ["sps/io/U1/on", "sps/io/U1/off"]
    _lauf(k)


def test_gleichzeitige_befehle_eine_anmeldung(miniserver_http):
    async def k(app, ms):
        _ablaufen(app, ms)
        res = await asyncio.gather(*[app.command(f"U{i}", "pulse") for i in range(10)])
        assert res == ["200"] * 10 and app.client.n == 1
    _lauf(k)


def test_401_aus_anderem_grund_keine_anmeldeflut(miniserver_http):
    async def k(app, ms):
        ms.deny.add("sps/io/NORIGHT")
        app._auth_at -= W.TOKEN_RENEW_MIN
        assert await app.command("NORIGHT", "on") == "401" and app.client.n == 1
        for _ in range(3):
            assert await app.command("NORIGHT", "on") == "401"
        assert app.client.n == 1, f"hoechstens eine Anmeldung je {W.TOKEN_RENEW_MIN} s"
    _lauf(k)


def test_gesicherter_befehl(miniserver_http):
    async def k(app, ms):
        ms.deny.add("sps/ios/")
        app._auth_at -= W.TOKEN_RENEW_MIN
        assert await app.command("S", "on", pin="1234") == "401" and app.client.n == 0   # falsche PIN
        ms.deny.clear()
        assert await app.command("S", "on", pin="1234") == "200"
        _ablaufen(app, ms)
        assert await app.command("S", "on", pin="1234") == "200" and app.client.n == 1  # Erneuerung beim Salt
    _lauf(k)


def test_abgelehnter_befehl_liefert_code(miniserver_http):
    async def k(app, ms):
        ms.reject = True
        assert await app.command("BAD", "x") == "500"
    _lauf(k)


def test_verlauf_nach_ablauf(miniserver_http):
    async def k(app, ms):
        ms.files["SUA.202609.xml"] = '<Statistics><S T="2026-09-01 10:00:00" V="1.5"/></Statistics>'
        _ablaufen(app, ms)
        await app._stat_load("SUA", "202609")
        assert app.stat_cache[("SUA", "202609")][2] and app.client.n == 1
    _lauf(k)


def test_neuanmeldung_scheitert(miniserver_http):
    async def k(app, ms):
        app.client = Anmeldung(ms, fehler=True)
        _ablaufen(app, ms)
        assert await app.command("U1", "on") == "401" and app.client.n == 1
        ms.files["SUB.202609.xml"] = "<Statistics/>"
        await app._stat_load("SUB", "202609")
        assert app.stat_cache[("SUB", "202609")][2] is None and app.client.n == 1, "keine Anmeldeschleife"
    _lauf(k)


def test_miniserver_weg(miniserver_http):
    async def k(app, ms):
        await ms.stop()
        t = time.monotonic()
        assert await app.command("U1", "on") is None and time.monotonic() - t < W.MS_CMD_TIMEOUT
    _lauf(k)


def test_hinweis_im_panel(miniserver_http):
    """Ueber die echte /ws-Route: ein abgelehnter Befehl ergibt einen Hinweis,
    ein angenommener keinen."""
    async def naechster_hinweis(ws, frist):
        try:
            while True:
                m = await asyncio.wait_for(ws.receive_json(), frist)
                if m.get("t") == "notify":
                    return m
        except asyncio.TimeoutError:
            return None

    async def k(app, ms):
        ui = web.Application()
        ui["app"] = app
        ui.router.add_get("/ws", W.ws_handler)
        runner, port = await serve(ui)
        try:
            async with aiohttp.ClientSession() as s, s.ws_connect(f"http://127.0.0.1:{port}/ws") as ws:
                ms.reject = True
                await ws.send_json({"t": "cmd", "uuid": "BAD", "cmd": "x"})
                h = await naechster_hinweis(ws, 3)
                assert h and h["level"] == "warn" and h["text"] == "Befehl nicht ausgeführt (Miniserver meldet 500)"
                ms.reject = False
                await ws.send_json({"t": "cmd", "uuid": "U1", "cmd": "on"})
                assert await naechster_hinweis(ws, 1) is None
                assert ms.io[-1] == "sps/io/U1/on"
        finally:
            await runner.cleanup()
    _lauf(k)
