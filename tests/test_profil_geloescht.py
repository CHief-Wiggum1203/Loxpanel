"""Ein Panel wird geloescht, waehrend Visus es zeigen. Nach dem Speichern laden
sie neu, behalten aber ?panel=<geloescht> in der Adresse; der Server zeigt
ihnen das Standardprofil. Die Geraeteliste (Displays) nennt dann auch das,
nicht mehr die Ansicht, die es nicht mehr gibt. Ein Entwurf fuer ein noch
nicht angelegtes Panel behaelt seinen Namen."""
import asyncio

import aiohttp

from lox import W, anlage, visu_starten

STRUKTUR = anlage({"S": {"name": "Licht", "type": "Switch", "uuidAction": "S", "room": "r1", "cat": "c1",
                         "isFavorite": True, "states": {"active": "s"}}})
ROUTEN = [("POST", "/api/panels", W.api_save_panels), ("GET", "/api/devices", W.api_devices_get)]


def _app() -> W.App:
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    app.states = {"s": 0}
    app.panels = W.App._sanitize_panels({"default": {"title": "Standard", "tabs": ["favoriten"]},
                                         "test": {"title": "Test", "tabs": ["favoriten"]}})
    return app


async def _naechste(ws, typ: str, frist: float = 3):
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


def test_unbekanntes_profil_heisst_wie_das_gezeigte():
    app = _app()
    assert app.resolve_profile("test")["id"] == "test"
    for pid in ("weg", "", None):
        p = app.resolve_profile(pid)
        assert (p["id"], p["title"]) == ("default", "Standard"), pid
    entwurf = app.resolve_profile("neu", {"title": "Neu", "tabs": ["favoriten"]})
    assert (entwurf["id"], entwurf["title"], entwurf["entwurf"]) == ("neu", "Neu", True)


def test_geloeschtes_panel_verschwindet_aus_der_geraeteliste(cfg_ordner):
    async def lauf():
        app = _app()
        runner, port, bc = await visu_starten(app, ROUTEN)
        basis = f"http://127.0.0.1:{port}"
        try:
            async with aiohttp.ClientSession() as s:
                async def ansichten():
                    async with s.get(f"{basis}/api/devices") as r:
                        j = await r.json()
                    return ({d["name"]: d["profile"] for d in j["devices"]}, [a["profile"] for a in j["anonymous"]])

                async with s.ws_connect(f"{basis}/ws?panel=test&device=tablet") as tablet, \
                        s.ws_connect(f"{basis}/ws?panel=test") as ohne:
                    assert (await _naechste(tablet, "theme"))["title"] == "Test"
                    await _naechste(ohne, "theme")
                    assert await ansichten() == ({"tablet": "test"}, ["test"])
                    async with s.post(f"{basis}/api/panels",
                                      json={"panels": {"default": {"title": "Standard", "tabs": ["favoriten"]}}}) as r:
                        assert (await r.json())["ok"]
                    assert await _naechste(tablet, "reload") and await _naechste(ohne, "reload")
                # die Seiten laden mit derselben Adresse neu
                async with s.ws_connect(f"{basis}/ws?panel=test&device=tablet") as tablet, \
                        s.ws_connect(f"{basis}/ws?panel=test") as ohne:
                    assert (await _naechste(tablet, "theme"))["title"] == "Standard"
                    await _naechste(ohne, "theme")
                    assert await ansichten() == ({"tablet": "default"}, ["default"])
        finally:
            bc.cancel()
            await runner.cleanup()
    asyncio.run(lauf())
