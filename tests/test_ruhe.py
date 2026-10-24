"""Ruhemodus (LoxOS Phase 9): Ein Geraet mit Praesenzmelder und `ruhe` zeigt
bei leerem Raum die Ruhe-Ansicht, statt das Display abzuschalten. Geprueft am
echten Server (ws_handler, Broadcaster); Display-Treiber ersetzt ein
Stellvertreter - kein Test darf config/ veraendern."""
import asyncio

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from lox import anlage, visu_starten, W

BAUSTEINE = {
    "PM": {"name": "Präsenz Küche", "type": "PresenceDetector", "uuidAction": "PM", "room": "r1", "cat": "c1",
           "states": {"active": "pm_a", "infoText": "pm_t"}},
}
FULLY = {"driver": "fully", "host": "127.0.0.1", "port": 2323, "password": ""}


def _app(devices: dict, anwesend: bool = True):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"pm_a": 1.0 if anwesend else 0.0}
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"]}})
    app.devices = W.App._sanitize_devices(devices, set(app.panels))
    app._presence_rebuild()
    app._pending_presence.clear()
    geschaltet = []

    async def treiber(name, disp, on):
        geschaltet.append((name, on))
        return {"device": name, "ok": True}
    app._drive_display = treiber
    return app, geschaltet


async def _naechste(ws, typ: str, frist: float):
    loop = asyncio.get_running_loop()
    ende = loop.time() + frist
    while (rest := ende - loop.time()) > 0:
        try:
            m = await asyncio.wait_for(ws.receive_json(), rest)
        except asyncio.TimeoutError:
            return None
        if m.get("t") == typ:
            return m
    return None


def test_ruhe_wird_gespeichert():
    s = W.App._sanitize_devices({"s": {"presence": "PM", "ruhe": True}}, set())
    assert s == {"s": {"auto": True, "modes": {}, "presence": "PM", "ruhe": True}}
    for unecht in (1, "ja", False):
        s = W.App._sanitize_devices({"s": {"presence": "PM", "ruhe": unecht}}, set())
        assert "ruhe" not in s["s"]


def test_ruhe_ohne_melder_faellt_weg():
    s = W.App._sanitize_devices({"s": {"ruhe": True, "scale": "auto"}}, set())
    assert s == {"s": {"auto": True, "modes": {}, "scale": "auto"}}
    assert W.App._sanitize_devices({"s": {"ruhe": True}}, set()) == {}


def test_theme_traegt_ruhe():
    async def lauf():
        app, _ = _app({"s": {"presence": "PM", "ruhe": True}, "t": {"presence": "PM"}})
        runner, port, bc = await visu_starten(app)
        try:
            async with aiohttp.ClientSession() as sess, \
                    sess.ws_connect(f"http://127.0.0.1:{port}/ws?panel=test&device=s") as s, \
                    sess.ws_connect(f"http://127.0.0.1:{port}/ws?panel=test&device=t") as t, \
                    sess.ws_connect(f"http://127.0.0.1:{port}/ws?panel=test&device=u") as u:
                return [(await _naechste(w, "theme", 3))["ruhe"] for w in (s, t, u)]
        finally:
            bc.cancel()
            await runner.cleanup()
    assert asyncio.run(lauf()) == [True, False, False]


def _raum_leer(ruhe: bool):
    async def lauf():
        app, geschaltet = _app({"s": {"presence": "PM", "display": FULLY, **({"ruhe": True} if ruhe else {})}})
        runner, port, bc = await visu_starten(app)
        try:
            async with aiohttp.ClientSession() as sess, \
                    sess.ws_connect(f"http://127.0.0.1:{port}/ws?panel=test&device=s") as ws:
                await _naechste(ws, "theme", 3)
                app._on_value("pm_a", 0.0)
                msg = await _naechste(ws, "display", 3)
                await asyncio.sleep(0.3)
                return msg, geschaltet
        finally:
            bc.cancel()
            await runner.cleanup()
    return asyncio.run(lauf())


def test_raum_leer_schaltet_mit_ruhe_nicht_ab():
    msg, geschaltet = _raum_leer(True)
    assert msg == {"t": "display", "on": False, "presence": False}
    assert geschaltet == []


def test_raum_leer_schaltet_ohne_ruhe_ab():
    msg, geschaltet = _raum_leer(False)
    assert msg == {"t": "display", "on": False, "presence": False}
    assert geschaltet == [("s", False)]


def test_ruhe_weckt_weiter():
    """Nur das Abschalten entfaellt: kommt jemand, schalten die Treiber ein."""
    async def lauf():
        app, geschaltet = _app({"s": {"presence": "PM", "display": FULLY, "ruhe": True}}, anwesend=False)
        runner, port, bc = await visu_starten(app)
        try:
            async with aiohttp.ClientSession() as sess, \
                    sess.ws_connect(f"http://127.0.0.1:{port}/ws?panel=test&device=s") as ws:
                await _naechste(ws, "theme", 3)
                app._on_value("pm_a", 1.0)
                assert (await _naechste(ws, "display", 3))["on"] is True
                await asyncio.sleep(0.3)
                return geschaltet
        finally:
            bc.cancel()
            await runner.cleanup()
    assert asyncio.run(lauf()) == [("s", True)]


def test_leerlauf_mit_ruhe_schaltet_nicht_ab():
    async def lauf():
        app, geschaltet = _app({"s": {"presence": "PM", "display": FULLY, "ruhe": True}}, anwesend=False)
        runner, port, bc = await visu_starten(app)
        try:
            async with aiohttp.ClientSession() as sess, \
                    sess.ws_connect(f"http://127.0.0.1:{port}/ws?panel=test&device=s") as ws:
                await _naechste(ws, "theme", 3)
                await ws.send_json({"t": "idle"})
                await asyncio.sleep(0.5)
                return geschaltet
        finally:
            bc.cancel()
            await runner.cleanup()
    assert asyncio.run(lauf()) == []


def test_speichern_meldet_ruhe():
    async def lauf():
        app, _ = _app({"s": {"presence": "PM"}})
        app._persist_panels_file = lambda panels, devices: None
        runner, port, bc = await visu_starten(app)
        ui = web.Application()
        ui["app"] = app
        ui.router.add_post("/api/devices", W.api_save_devices)
        try:
            async with aiohttp.ClientSession() as sess, \
                    sess.ws_connect(f"http://127.0.0.1:{port}/ws?panel=test&device=s") as ws, \
                    TestClient(TestServer(ui)) as cl:
                await _naechste(ws, "theme", 3)
                j = await (await cl.post("/api/devices", json={"devices": {"s": {"presence": "PM", "ruhe": True}}})).json()
                assert j["ok"] and j["devices"]["s"]["ruhe"] is True
                an = await _naechste(ws, "ruhe", 3)
                await cl.post("/api/devices", json={"devices": {"s": {"presence": "PM"}}})
                aus = await _naechste(ws, "ruhe", 3)
                return an, aus
        finally:
            bc.cancel()
            await runner.cleanup()
    an, aus = asyncio.run(lauf())
    assert an == {"t": "ruhe", "ruhe": True} and aus == {"t": "ruhe", "ruhe": False}
