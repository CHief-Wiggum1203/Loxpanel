"""Vorschau am Geraet (Punkt 12): Ein Entwurf (Punkt 10, /api/entwurf) laeuft auf
dem echten Geraet. /api/device/switch nimmt dazu {entwurf: <Token>}, schickt ihn
nur an eine verbundene Visu des Geraets und merkt sich, wo es vorher war. Das
Geraet kehrt dorthin zurueck - auf Knopfdruck, nach Ablauf, und Speichern oder
ein Betriebsmodus beenden die Vorschau von selbst."""
import asyncio

import aiohttp

from lox import W, anlage, visu_starten

STRUKTUR = anlage({"S": {"name": "Licht", "type": "Switch", "uuidAction": "S", "room": "r1", "cat": "c1",
                         "isFavorite": True, "states": {"active": "s"}}})
ROUTEN = [("POST", "/api/entwurf", W.api_entwurf), ("POST", "/api/panels", W.api_save_panels),
          ("POST", "/api/device/switch", W.api_device_switch), ("POST", "/api/vorschau/beenden", W.api_vorschau_beenden),
          ("GET", "/api/devices", W.api_devices_get)]
ENTWURF = {"title": "Entwurf", "tabs": ["zentral"]}


def _app() -> W.App:
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    app.states = {"s": 0}
    app.panels = W.App._sanitize_panels({"a": {"title": "Vorher", "tabs": ["favoriten"]},
                                         "b": {"title": "Anderes", "tabs": ["favoriten"]}})
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


def _lauf(schritte, app=None):
    async def lauf():
        a = app or _app()
        runner, port, bc = await visu_starten(a, ROUTEN)
        try:
            async with aiohttp.ClientSession() as s:
                async def post(pfad, daten):
                    async with s.post(f"http://127.0.0.1:{port}{pfad}", json=daten) as r:
                        return r.status, await r.json()
                return await schritte(a, s, f"http://127.0.0.1:{port}", post)
        finally:
            bc.cancel()
            await runner.cleanup()
    return asyncio.run(lauf())


def test_entwurf_ans_geraet_und_zurueck_auf_knopfdruck(cfg_ordner):
    async def schritte(app, s, basis, post):
        _, j = await post("/api/entwurf", {"id": "neu", "panel": ENTWURF})      # ein Profil, das es noch nicht gibt
        token = j["token"]
        # Fehler: kein/unbekannter/fremder Token, kein Geraet verbunden
        st, j = await post("/api/device/switch", {"device": "wand", "panel": "neu", "entwurf": "unbekannt"})
        assert st == 400 and "unbekannt oder abgelaufen" in j["error"], j
        st, j = await post("/api/device/switch", {"device": "wand", "panel": "a", "entwurf": token})
        assert st == 400, "der Token gehoert zu einem anderen Profil"
        st, j = await post("/api/device/switch", {"device": "wand", "panel": "neu", "entwurf": token})
        assert st == 200 and not j["ok"] and "verbundene Visu" in j["error"], j
        assert app.vorschau_geraet == {}

        async with s.ws_connect(f"{basis}/ws?panel=a&device=wand") as wand, \
                s.ws_connect(f"{basis}/ws?panel=a&device=anderes") as anderes:
            await _naechste(wand, "theme")
            await _naechste(anderes, "theme")
            st, j = await post("/api/device/switch", {"device": "wand", "panel": "neu", "entwurf": token})
            assert st == 200 and j["ok"] and j["zurueck"] == "a" and j["agent"] == "", j
            m = await _naechste(wand, "switch")
            assert m == {"t": "switch", "panel": "neu", "entwurf": token}, m
            assert await _naechste(anderes, "switch", 0.5) is None, "nur das gewaehlte Geraet"
            e = app.vorschau_geraet["wand"]
            assert (e["token"], e["id"], e["zurueck"]) == (token, "neu", "a")

        # das Geraet laedt die Adresse mit Entwurf: es zeigt ihn, und die Liste weiss es
        async with s.ws_connect(f"{basis}/ws?panel=neu&device=wand&entwurf={token}") as wand, \
                s.ws_connect(f"{basis}/ws?panel=a&device=anderes") as anderes:
            t = await _naechste(wand, "theme")
            assert (t["entwurf"], t["title"]) == (True, "Entwurf"), t
            await _naechste(anderes, "theme")
            async with s.get(f"{basis}/api/devices") as r:
                dev = {d["name"]: d for d in (await r.json())["devices"]}
            assert dev["wand"]["vorschau"]["id"] == "neu" and dev["anderes"]["vorschau"] is None, dev
            # noch eine Vorschau (der Konfigurator stellt um): "zurueck" bleibt das Profil vor der ersten
            st, j = await post("/api/device/switch", {"device": "wand", "panel": "neu", "entwurf": token})
            assert j["ok"] and j["zurueck"] == "a", j
            assert await _naechste(wand, "switch")

            # beenden: das Geraet geht zu "a" zurueck, ohne Entwurf
            st, j = await post("/api/vorschau/beenden", {"device": "wand"})
            assert j == {"ok": True, "beendet": True}, j
            m = await _naechste(wand, "switch")
            assert m == {"t": "switch", "panel": "a", "entwurf": ""}, m
            assert app.vorschau_geraet == {}
            st, j = await post("/api/vorschau/beenden", {"device": "wand"})
            assert j == {"ok": True, "beendet": False}, "zweimal ist nichts mehr zu beenden"
            st, j = await post("/api/vorschau/beenden", {})
            assert st == 400
    _lauf(schritte)


def test_ablauf_speichern_und_umschalten_beenden_die_vorschau(cfg_ordner, monkeypatch):
    monkeypatch.setattr(W, "VORSCHAU_GERAET_DAUER", 0.5)

    async def schritte(app, s, basis, post):
        _, j = await post("/api/entwurf", {"id": "a", "panel": ENTWURF})
        token = j["token"]
        async with s.ws_connect(f"{basis}/ws?panel=b&device=wand&entwurf=nix") as wand:
            await _naechste(wand, "theme")
            await post("/api/device/switch", {"device": "wand", "panel": "a", "entwurf": token})
            assert await _naechste(wand, "switch")
        # die Seite des Geraets laedt mit dem Entwurf: so zeigt sie ihn (Stand: ?panel=a&entwurf=)
        async with s.ws_connect(f"{basis}/ws?panel=a&device=wand&entwurf={token}") as wand:
            await _naechste(wand, "theme")
            # 1. der Konfigurator arbeitet weiter (api_entwurf frischt auf): nach 0,5 s noch dabei
            await asyncio.sleep(0.35)
            await post("/api/entwurf", {"id": "a", "panel": ENTWURF, "token": token})
            await asyncio.sleep(0.35)
            assert "wand" in app.vorschau_geraet, "aufgefrischt: noch nicht abgelaufen"
            # 2. danach laeuft sie ab: das Geraet geht von selbst zurueck
            m = await _naechste(wand, "switch", 3)
            assert m == {"t": "switch", "panel": "b", "entwurf": ""}, m
            assert app.vorschau_geraet == {}

        # Speichern beendet sie: das Geraet zeigt das gespeicherte Profil (entwurfEnde), nichts mehr zu tun
        monkeypatch.setattr(W, "VORSCHAU_GERAET_DAUER", 60)
        _, j = await post("/api/entwurf", {"id": "a", "panel": ENTWURF})
        token = j["token"]
        async with s.ws_connect(f"{basis}/ws?panel=a&device=wand&entwurf={token}") as wand:
            await _naechste(wand, "theme")
            await post("/api/device/switch", {"device": "wand", "panel": "a", "entwurf": token})
            await _naechste(wand, "switch")
            assert "wand" in app.vorschau_geraet
            _, j = await post("/api/panels", {"panels": {"a": {"title": "Gespeichert", "tabs": ["favoriten"]},
                                                         "b": {"title": "Anderes", "tabs": ["favoriten"]}}})
            assert j["ok"] and app.vorschau_geraet == {}
            assert await _naechste(wand, "entwurfEnde")

        # eine ausdrueckliche Wahl unter Displays beendet sie ebenfalls
        _, j = await post("/api/entwurf", {"id": "a", "panel": ENTWURF})
        token = j["token"]
        async with s.ws_connect(f"{basis}/ws?panel=b&device=wand") as wand:
            await _naechste(wand, "theme")
            await post("/api/device/switch", {"device": "wand", "panel": "a", "entwurf": token})
            assert "wand" in app.vorschau_geraet
            st, j = await post("/api/device/switch", {"device": "wand", "panel": "b"})
            assert j["ok"] and app.vorschau_geraet == {}
    _lauf(schritte)


def test_betriebsmodus_beendet_die_vorschau_des_geraets(cfg_ordner):
    async def schritte(app, s, basis, post):
        app.devices = {"wand": {"auto": True, "modes": {"abend": "b"}}}
        _, j = await post("/api/entwurf", {"id": "a", "panel": ENTWURF})
        async with s.ws_connect(f"{basis}/ws?panel=a&device=wand&entwurf={j['token']}") as wand:
            await _naechste(wand, "theme")
            app.vorschau_geraet["wand"] = {"token": j["token"], "id": "a", "zurueck": "b", "bis": 1e12}
            await app.switch_mode("abend")
            assert "wand" not in app.vorschau_geraet, "der Modus schaltet das Geraet um"
            m = await _naechste(wand, "switch")
            assert m["panel"] == "b" and "entwurf" not in m, m
    _lauf(schritte)
