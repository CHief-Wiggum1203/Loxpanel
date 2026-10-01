"""Praesenzmelder je Geraet (Displays -> Display-Steuerung): solange der
gewaehlte Baustein jemanden meldet, bleibt das Display des Geraets an und die
Leerlaufzeit schaltet es nicht ab; wird der Raum leer, geht es aus. Geprueft
am echten Server (ws_handler, Broadcaster) mit einer WebSocket-Verbindung je
Geraet. Display-Treiber und Datei ersetzt ein Stellvertreter - kein Test darf
config/ veraendern."""
import asyncio
import time

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from lox import W, anlage, visu_starten

BAUSTEINE = {
    "PM": {"name": "Präsenz Küche", "type": "PresenceDetector", "uuidAction": "PM", "room": "r1", "cat": "c1",
           "states": {"active": "pm_a", "infoText": "pm_t"}},
    "L": {"name": "Licht", "type": "Switch", "uuidAction": "LA", "room": "r1", "cat": "c1", "isFavorite": True,
          "states": {"active": "sl"}},
}
FULLY = {"driver": "fully", "host": "127.0.0.1", "port": 2323, "password": ""}


def _app(devices: dict, anwesend: bool = False):
    """Server mit Praesenzmelder "PM"; der Stand beim Start gilt als bekannt
    (nichts zu verteilen). Liefert die App und die Liste der Treiber-Aufrufe."""
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"pm_a": 1.0 if anwesend else 0.0, "sl": 0}
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
    """Naechste Nachricht dieses Typs; None, wenn sie in `frist` Sekunden nicht kommt."""
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


def test_praesenzmelder_in_den_geraete_einstellungen():
    s = W.App._sanitize_devices({
        "kueche": {"presence": " PM "},                  # nur ein Melder: das Geraet bleibt
        "flur": {"presence": 7, "scale": "auto"},        # kein Text: Melder faellt weg, der Rest bleibt
        "bad": {"presence": ""},                         # nichts uebrig: das Geraet faellt weg
        "lang": {"presence": "x" * 80}}, set())
    assert s == {"kueche": {"auto": True, "modes": {}, "presence": "PM"},
                 "flur": {"auto": True, "modes": {}, "scale": "auto"},
                 "lang": {"auto": True, "modes": {}, "presence": "x" * 60}}


def test_nur_ein_echter_wechsel_schaltet():
    app, _ = _app({"kueche": {"presence": "PM"}, "flur": {"presence": "PM"}, "bad": {"scale": "auto"}})
    assert app.presence_map == {"pm_a": ["kueche", "flur"]}
    app._on_value("pm_a", 1.0)
    assert app._pending_presence == [{"dev": "kueche", "on": True, "presence": True},
                                     {"dev": "flur", "on": True, "presence": True}]
    app._pending_presence.clear()
    app._on_value("pm_a", 1.0)             # derselbe Wert, z.B. Neuversand nach einem Reconnect
    assert app._pending_presence == []
    app._on_value("pm_a", 0.0)
    assert app._pending_presence == [{"dev": "kueche", "on": False, "presence": False},
                                     {"dev": "flur", "on": False, "presence": False}]


def test_unbekannter_baustein_koppelt_nichts():
    app, _ = _app({"kueche": {"presence": "GIBTSNICHT"}}, anwesend=True)
    assert app.presence_map == {} and app._presence_on == {}


def test_display_folgt_dem_praesenzmelder():
    """Nur das Geraet mit dem Melder bekommt die Meldungen, sein Display-Treiber
    schaltet mit; beim Verbinden steht der aktuelle Stand in der theme-Nachricht."""
    async def lauf():
        app, geschaltet = _app({"kueche": {"presence": "PM", "display": FULLY}}, anwesend=True)
        runner, port, bc = await visu_starten(app)
        try:
            async with aiohttp.ClientSession() as s, \
                    s.ws_connect(f"http://127.0.0.1:{port}/ws?panel=test&device=kueche") as kueche, \
                    s.ws_connect(f"http://127.0.0.1:{port}/ws?panel=test&device=flur") as flur:
                assert (await _naechste(kueche, "theme", 3))["presence"] is True
                assert (await _naechste(flur, "theme", 3))["presence"] is False
                app._on_value("pm_a", 0.0)                   # Raum leer
                assert await _naechste(kueche, "display", 3) == {"t": "display", "on": False, "presence": False}
                app._on_value("pm_a", 1.0)                   # jemand kommt
                assert await _naechste(kueche, "display", 3) == {"t": "display", "on": True, "presence": True}
                assert await _naechste(flur, "display", 1) is None
                await asyncio.sleep(0.2)                     # Treiber laufen im Hintergrund
                assert geschaltet == [("kueche", False), ("kueche", True)]
        finally:
            bc.cancel()
            await runner.cleanup()
    asyncio.run(lauf())


def test_leerlauf_schaltet_nicht_ab_solange_jemand_da_ist():
    async def lauf():
        app, geschaltet = _app({"kueche": {"presence": "PM", "display": FULLY}}, anwesend=True)
        runner, port, bc = await visu_starten(app)
        try:
            async with aiohttp.ClientSession() as s, \
                    s.ws_connect(f"http://127.0.0.1:{port}/ws?panel=test&device=kueche") as ws:
                await _naechste(ws, "theme", 3)
                await ws.send_json({"t": "idle"})
                await asyncio.sleep(0.5)
                assert geschaltet == [], "jemand da: das Display bleibt an"
                app._on_value("pm_a", 0.0)
                assert (await _naechste(ws, "display", 3))["on"] is False
                await ws.send_json({"t": "idle"})
                await asyncio.sleep(0.5)
                assert geschaltet == [("kueche", False), ("kueche", False)]
        finally:
            bc.cancel()
            await runner.cleanup()
    asyncio.run(lauf())


def test_speichern_koppelt_und_loest_den_melder():
    """Melder waehlen, waehrend jemand da ist: das Geraet wird geweckt und
    gehalten. Melder entfernen: nur loslassen (Wecken, kein Abschalten) - aus
    schaltet allein der leere Raum."""
    async def lauf():
        app, _ = _app({}, anwesend=True)
        gespeichert = []
        app._persist_panels_file = lambda panels, devices: gespeichert.append(devices)
        ui = web.Application()
        ui["app"] = app
        ui.router.add_post("/api/devices", W.api_save_devices)
        async with TestClient(TestServer(ui)) as cl:
            j = await (await cl.post("/api/devices", json={"devices": {"kueche": {"presence": "PM"}}})).json()
            assert j["ok"] and j["devices"] == {"kueche": {"auto": True, "modes": {}, "presence": "PM"}}
            assert gespeichert[-1] == j["devices"]
            assert app._pending_presence == [{"dev": "kueche", "on": True, "presence": True}]
            app._pending_presence.clear()
            j = await (await cl.post("/api/devices", json={"devices": {}})).json()
            assert j["ok"] and app.presence_map == {}
            assert app._pending_presence == [{"dev": "kueche", "on": True, "presence": False}]
    asyncio.run(lauf())


def test_stand_in_der_geraeteliste_und_auswahl_im_konfigurator():
    async def lauf():
        app, _ = _app({"kueche": {"presence": "PM"}, "flur": {"scale": "auto"}}, anwesend=True)
        ui = web.Application()
        ui["app"] = app
        ui.router.add_get("/api/devices", W.api_devices_get)
        ui.router.add_get("/api/meta", W.api_meta)
        async with TestClient(TestServer(ui)) as cl:
            d = await (await cl.get("/api/devices")).json()
            assert {e["name"]: e["presence"] for e in d["devices"]} == {"kueche": True, "flur": None}
            m = await (await cl.get("/api/meta")).json()
            assert [(o["uuid"], o["type"]) for o in m["activeControls"]] == [("L", "Switch"),
                                                                           ("PM", "PresenceDetector")]
    asyncio.run(lauf())


def test_viele_geraete_am_melder_bleiben_schnell():
    """Ein Melder an 20.000 Geraeten (Sicherung, /api/devices): jeder Wechsel
    gab je Geraet einen Treiber-Aufruf, der alle Geraete durchlief -
    quadratisch, 7 bis 38 s Stillstand. Nur Geraete mit Treiber brauchen einen."""
    async def lauf():
        geraete = {f"g{i}": {"presence": "PM"} for i in range(20_000)}
        app, geschaltet = _app({**geraete, "mit": {"presence": "PM", "display": FULLY}})
        app._on_value("pm_a", 1.0)
        beginn = time.perf_counter()
        await app._broadcast_tick()
        while app.bg_tasks:
            await asyncio.gather(*list(app.bg_tasks))
        return time.perf_counter() - beginn, geschaltet
    dauer, geschaltet = asyncio.run(lauf())
    assert geschaltet == [("mit", True)]
    assert dauer < 2, f"{dauer:.1f} s"
