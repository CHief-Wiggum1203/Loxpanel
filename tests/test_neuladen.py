"""Neu laden gegen Einfrieren, Server-Seite. Ohne Eintrag "Auto-Neustart"
(ui.reloadHours) bekommt die Visu in der theme-Nachricht reloadHours = None und
die Stunde des naechtlichen Neuladens (reloadAt = NEULADEN_STUNDE), der
Konfigurator dieselbe Stunde aus /api/meta. Eine Zahl, auch 0 = aus, geht
begrenzt durch. Der Agent eines Linux-Panels bekommt ohne Eintrag weiter None
und nimmt seinen Wert aus der kiosk.conf."""
import asyncio

import aiohttp
import pytest

from lox import W, anlage, visu_starten

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "LA", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}}}
ROUTEN = (("POST", "/api/agent/announce", W.api_agent_announce),)


def _app(ui: dict):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"sl": 0}
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"], "ui": ui}})
    return app


async def _mit_server(ui: dict, schritt):
    app = _app(ui)
    runner, port, bc = await visu_starten(app, ROUTEN)
    try:
        async with aiohttp.ClientSession() as s:
            return await schritt(s, f"http://127.0.0.1:{port}")
    finally:
        bc.cancel()
        await runner.cleanup()


async def _theme(s, basis):
    async with s.ws_connect(f"{basis}/ws?panel=test&device=wand") as ws:
        while True:
            m = await asyncio.wait_for(ws.receive_json(), 3)
            if m.get("t") == "theme":
                return m


@pytest.mark.parametrize("ui, stunden", [
    ({}, None), ({"reloadHours": 0}, 0), ({"reloadHours": 2}, 2), ({"reloadHours": 500}, 168),
    ({"reloadHours": -1}, 0), ({"reloadHours": "3"}, None),
], ids=["leer", "aus", "zwei", "zu-gross", "negativ", "text"])
def test_theme_nachricht(ui, stunden):
    m = asyncio.run(_mit_server(ui, _theme))
    assert m["reloadHours"] == stunden
    assert m["reloadAt"] == W.NEULADEN_STUNDE


def test_konfigurator_bekommt_die_stunde():
    async def meta(s, basis):
        async with s.get(f"{basis}/api/meta") as r:
            return await r.json()
    assert asyncio.run(_mit_server({}, meta))["reloadAt"] == W.NEULADEN_STUNDE


@pytest.mark.parametrize("ui, stunden", [({}, None), ({"reloadHours": 0}, 0), ({"reloadHours": 6}, 6)],
                         ids=["leer", "aus", "sechs"])
def test_agent_behaelt_seinen_wert(ui, stunden):
    """Ohne Eintrag nimmt der Agent RELOAD_HOURS aus seiner kiosk.conf: Das
    naechtliche Neuladen der Visu gilt fuer ihn nicht."""
    async def melden(s, basis):
        async with s.post(f"{basis}/api/agent/announce", json={"name": "wand", "panel": "test"}) as r:
            return await r.json()
    assert asyncio.run(_mit_server(ui, melden))["reloadHours"] == stunden


def test_stunde_ist_eine_uhrzeit():
    assert isinstance(W.NEULADEN_STUNDE, int) and 0 <= W.NEULADEN_STUNDE <= 23
