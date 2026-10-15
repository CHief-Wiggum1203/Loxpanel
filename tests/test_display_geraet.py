""""Display aus nach" am Geraet (Einrichtung neu, Schritt 4): devices[name].dpmsOff
gilt vor einem (aelteren) Eintrag der Ansicht und vor den Vorgaben; der Sanitizer
nimmt die Zahl (0..3600) und haelt ein Geraet, das nur sie traegt; die Visu bekommt
den Wert in der theme-Nachricht, der Agent in der Antwort auf seine Meldung."""
import asyncio
import json

import aiohttp

from lox import W, anlage, visu_starten

BAUSTEINE = {"S": {"name": "Licht", "type": "Switch", "uuidAction": "S", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "s"}}}
ROUTEN = [("POST", "/api/agent/announce", W.api_agent_announce), ("POST", "/api/devices", W.api_save_devices)]


def test_sanitizer_nimmt_display_aus():
    clean = W.App._sanitize_devices({"a": {"dpmsOff": 120}, "b": {"dpmsOff": 9000, "scale": 1.2}, "c": {"dpmsOff": "120"},
                                     "d": {"dpmsOff": True}, "e": {"dpmsOff": 0}}, {"day"})
    assert clean == {"a": {"auto": True, "modes": {}, "dpmsOff": 120},
                     "b": {"auto": True, "modes": {}, "scale": 1.2, "dpmsOff": 3600},
                     "e": {"auto": True, "modes": {}, "dpmsOff": 0}}, clean


def test_geraet_vor_ansicht_vor_vorgaben(cfg_ordner):
    (cfg_ordner / "panels.json").write_text(json.dumps({
        "panels": {"alt": {"title": "Alt", "tabs": ["favoriten"], "ui": {"dpmsOff": 300}},
                   "neu": {"title": "Neu", "tabs": ["favoriten"]}},
        "devices": {"wand": {"auto": True, "modes": {}, "dpmsOff": 45}}}), encoding="utf-8")
    app = W.App({"host": "", "port": 80})
    app.theme["ui"]["dpmsOff"] = 600
    assert app.panel_dpms("neu") == 600, "Vorgabe"
    assert app.panel_dpms("alt") == 300, "ein aelterer Eintrag der Ansicht gilt weiter"
    assert app.panel_dpms("alt", dev="wand") == 45 and app.panel_dpms("neu", dev="wand") == 45, "das Geraet zuerst"
    assert app.panel_dpms("neu", dev="anderes") == 600


def test_visu_und_agent_bekommen_den_wert_des_geraets(cfg_ordner):
    (cfg_ordner / "panels.json").write_text(json.dumps({
        "panels": {"day": {"title": "Tag", "tabs": ["favoriten"], "ui": {"dpmsOff": 300}}},
        "devices": {"wand": {"auto": True, "modes": {}, "dpmsOff": 45}}}), encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"s": 0}
        runner, port, bc = await visu_starten(app, ROUTEN)
        basis = f"http://127.0.0.1:{port}"
        try:
            async with aiohttp.ClientSession() as s:
                async def theme(adresse):
                    async with s.ws_connect(f"{basis}/ws{adresse}") as ws:
                        while True:
                            m = await asyncio.wait_for(ws.receive_json(), 5)
                            if m.get("t") == "theme":
                                return m
                assert (await theme("?panel=day&device=wand"))["dpmsOff"] == 45
                assert (await theme("?panel=day&device=tablet"))["dpmsOff"] == 300
                async with s.post(basis + "/api/agent/announce", json={"name": "wand", "panel": "day", "ip": "10.0.0.5",
                                                                        "port": 9, "kiosk": True}) as r:
                    assert (await r.json())["dpmsOff"] == 45
                # der Konfigurator speichert die Geraete: der Wert bleibt, leer nimmt ihn weg
                async with s.post(basis + "/api/devices", json={"devices": {"wand": {"auto": True, "modes": {}, "dpmsOff": 90}}}) as r:
                    assert (await r.json())["devices"]["wand"]["dpmsOff"] == 90
                assert (await theme("?panel=day&device=wand"))["dpmsOff"] == 90
                async with s.post(basis + "/api/devices", json={"devices": {"wand": {"auto": True, "modes": {}, "scale": 1.2}}}) as r:
                    assert "dpmsOff" not in (await r.json())["devices"]["wand"]
                assert (await theme("?panel=day&device=wand"))["dpmsOff"] == 300
        finally:
            bc.cancel()
            await runner.cleanup()
    asyncio.run(lauf())


def test_nacht_am_geraet(cfg_ordner):
    """Nacht (Abdunkeln %, Aufhellen Sek.) am Geraet: der Sanitizer nimmt die
    Zahlen, panel_night() stellt das Geraet vor einen aelteren Eintrag der
    Ansicht und vor die Vorgaben; die Nacht-Uhr bleibt die der Vorgaben."""
    clean = W.App._sanitize_devices({"a": {"nightDim": 35, "nightWake": 400}, "b": {"nightDim": "35"},
                                     "c": {"nightDim": 0, "nightWake": 0}}, {"day"})
    assert clean == {"a": {"auto": True, "modes": {}, "nightDim": 35, "nightWake": 300},
                     "c": {"auto": True, "modes": {}, "nightDim": 0, "nightWake": 0}}, clean
    (cfg_ordner / "panels.json").write_text(json.dumps({
        "panels": {"alt": {"title": "Alt", "tabs": ["favoriten"], "ui": {"nightDim": 50, "nightClock": True}},
                   "neu": {"title": "Neu", "tabs": ["favoriten"]}},
        "devices": {"wand": {"auto": True, "modes": {}, "nightDim": 20, "nightWake": 5}}}), encoding="utf-8")
    app = W.App({"host": "", "port": 80})
    app.theme["ui"].update(nightDim=70, nightWake=60)
    n = app.panel_night("neu")
    assert (n["dim"], n["wake"], n["uhr"]) == (70, 60, False), "Vorgabe"
    n = app.panel_night("alt")
    assert (n["dim"], n["wake"], n["uhr"]) == (50, 60, True), "ein aelterer Eintrag der Ansicht gilt weiter"
    n = app.panel_night("alt", dev="wand")
    assert (n["dim"], n["wake"], n["uhr"]) == (20, 5, True), "das Geraet zuerst, die Nacht-Uhr aus der Ansicht/Vorgabe"
    n = app.panel_night("neu", dev="anderes")
    assert (n["dim"], n["wake"]) == (70, 60)
