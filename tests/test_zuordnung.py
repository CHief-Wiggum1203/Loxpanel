"""Zuordnung Geraet -> Ansicht (Einrichtung neu, Schritt 2): `devices[name].panel`
in panels.json ist die eine Stelle, die sagt, was ein Geraet zeigt. "Ansicht
wechseln" (/api/device/switch) und "Start" mit Ansicht (/api/agent/command)
schreiben sie; ws_handler zieht ein Geraet beim Verbinden darauf, egal was in
der Start-Adresse (?panel=) oder der kiosk.conf steht; der Agent bekommt sie
mit seiner Meldung; ein Betriebsmodus ueberlagert sie nur. Das Speichern der
Geraete im Konfigurator laesst sie stehen."""
import asyncio
import json

import aiohttp

from lox import W, anlage, visu_starten

BAUSTEINE = {"S": {"name": "Licht", "type": "Switch", "uuidAction": "S", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "s"}}}
PROFILE = {"panels": {"day": {"title": "Tag", "tabs": ["favoriten"], "ui": {"dpmsOff": 300}},
                      "night": {"title": "Nacht", "tabs": ["favoriten"], "ui": {"dpmsOff": 30}}},
           "devices": {"wand": {"auto": True, "modes": {"tag": "day", "nacht": "night"}, "scale": 1.5}}}
ROUTEN = [("POST", "/api/agent/announce", W.api_agent_announce),
          ("POST", "/api/agent/command", W.api_agent_command),
          ("POST", "/api/device/switch", W.api_device_switch),
          ("POST", "/api/devices", W.api_save_devices),
          ("GET", "/api/mode/{mode}", W.api_mode)]


async def _nachricht(ws, art: str, sekunden: float = 5) -> dict:
    async def warten():
        while True:
            m = await ws.receive_json()
            if m.get("t") == art:
                return m
    return await asyncio.wait_for(warten(), sekunden)


class Server:
    def __init__(self, app, s, basis, cfg):
        self.app, self.s, self.basis, self.cfg = app, s, basis, cfg

    async def post(self, pfad: str, daten: dict) -> dict:
        async with self.s.post(self.basis + pfad, json=daten) as r:
            return await r.json()

    async def theme(self, adresse: str) -> dict:
        """Verbinden wie die Visu eines Geraets -> die theme-Nachricht (title = Ansicht)."""
        async with self.s.ws_connect(f"{self.basis}/ws{adresse}") as ws:
            return await _nachricht(ws, "theme")

    def gespeichert(self) -> dict:
        return json.loads((self.cfg / "panels.json").read_text(encoding="utf-8")).get("devices") or {}


def _lauf(cfg_ordner, schritt, panels=PROFILE):
    async def innen():
        (cfg_ordner / "panels.json").write_text(json.dumps(panels), encoding="utf-8")
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"s": 0}
        runner, port, bc = await visu_starten(app, ROUTEN)
        try:
            async with aiohttp.ClientSession() as s:
                return await schritt(Server(app, s, f"http://127.0.0.1:{port}", cfg_ordner))
        finally:
            bc.cancel()
            await runner.cleanup()
    return asyncio.run(innen())


def test_sanitizer_nimmt_die_zuordnung():
    """`panel` bleibt, wenn es die Ansicht gibt; ein Geraet nur mit Zuordnung
    bleibt; eine unbekannte Ansicht faellt weg (und mit ihr ein sonst leeres Geraet)."""
    ids = {"day", "night"}
    clean = W.App._sanitize_devices({"a": {"panel": "night"}, "b": {"panel": " day ", "scale": 1.2},
                                     "c": {"panel": "weg"}, "d": {"panel": "weg", "scale": 1.1}}, ids)
    assert clean == {"a": {"auto": True, "modes": {}, "panel": "night"},
                     "b": {"auto": True, "modes": {}, "panel": "day", "scale": 1.2},
                     "d": {"auto": True, "modes": {}, "scale": 1.1}}
    assert W.App._devices_export(clean)["a"]["panel"] == "night"


def test_wahl_wird_zuordnung_und_gilt_beim_verbinden(cfg_ordner):
    """"Ansicht wechseln" speichert die Zuordnung in panels.json; danach zeigt das
    Geraet sie bei jedem Verbinden, auch mit anderem ?panel= in der Adresse.
    Die uebrigen Einstellungen des Geraets bleiben. Leer = Standardansicht."""
    async def lauf(w: Server):
        assert (await w.theme("?panel=day&device=wand"))["title"] == "Tag"
        async with w.s.ws_connect(f"{w.basis}/ws?panel=day&device=wand") as ws:
            await _nachricht(ws, "theme")
            j = await w.post("/api/device/switch", {"device": "wand", "panel": "night"})
            assert j == {"ok": True, "sent": 1, "via": "ws", "agent": ""}, j
            assert (await _nachricht(ws, "switch"))["panel"] == "night"
        assert w.gespeichert()["wand"] == {"auto": True, "modes": {"tag": "day", "nacht": "night"},
                                           "scale": 1.5, "panel": "night"}
        assert w.app.geraet_ansicht("wand") == "night" and w.app.ansicht_fuer_geraet("wand") == "night"
        # die Start-Adresse sagt day, die Zuordnung gewinnt - ohne Neuladen
        assert (await w.theme("?panel=day&device=wand"))["title"] == "Nacht"
        assert (await w.theme("?device=wand"))["title"] == "Nacht"
        geraet = next(d for d in w.app.device_list()["devices"] if d["name"] == "wand")
        assert geraet["zugeordnet"] == "night" and geraet["configured"]
        # ein anderes Geraet ohne Zuordnung folgt weiter seiner Adresse
        assert (await w.theme("?panel=day&device=anderes"))["title"] == "Tag"
        # leer: zurueck auf die Standardansicht, der Schluessel faellt weg
        j = await w.post("/api/device/switch", {"device": "wand", "panel": ""})
        assert j["ok"] and "panel" not in w.gespeichert()["wand"]
        assert (await w.theme("?panel=night&device=wand"))["title"] == "Nacht", "ohne Zuordnung gilt ?panel="
    _lauf(cfg_ordner, lauf)


def test_zuordnung_fuer_ein_geraet_das_nicht_online_ist(cfg_ordner):
    """Ein Geraet, das gerade nicht verbunden ist, bekommt die Zuordnung trotzdem
    (ok, offline) und zeigt sie, sobald es verbindet; ein Geraet ohne andere
    Einstellungen entsteht dabei."""
    async def lauf(w: Server):
        j = await w.post("/api/device/switch", {"device": "tablet", "panel": "night"})
        assert j == {"ok": True, "sent": 0, "via": "", "agent": "", "offline": True}, j
        assert w.gespeichert()["tablet"] == {"auto": True, "modes": {}, "panel": "night"}
        assert (await w.theme("?panel=day&device=tablet"))["title"] == "Nacht"
        j = await w.post("/api/device/switch", {"device": "tablet", "panel": "gibtsnicht"})
        assert not j["ok"]
    _lauf(cfg_ordner, lauf)


def test_speichern_der_geraete_laesst_die_zuordnung_stehen(cfg_ordner):
    """Der Konfigurator schickt beim Speichern alle Geraete ohne `panel`
    (readDevFromDom): die Zuordnung bleibt; nur ein Geraet, das er nicht mehr
    nennt (Entfernen), verliert sie."""
    async def lauf(w: Server):
        await w.post("/api/device/switch", {"device": "wand", "panel": "night"})
        await w.post("/api/device/switch", {"device": "tablet", "panel": "day"})
        j = await w.post("/api/devices", {"devices": {"wand": {"auto": True, "modes": {"tag": "day"}, "scale": 2},
                                                      "tablet": {"auto": True, "modes": {}}}})
        assert j["ok"] and j["devices"]["wand"]["panel"] == "night" and j["devices"]["tablet"]["panel"] == "day"
        assert w.gespeichert()["wand"] == {"auto": True, "modes": {"tag": "day"}, "scale": 2, "panel": "night"}
        j = await w.post("/api/devices", {"devices": {"wand": {"auto": True, "modes": {"tag": "day"}}}})
        assert "tablet" not in j["devices"] and "tablet" not in w.gespeichert()
        assert (await w.theme("?panel=day&device=tablet"))["title"] == "Tag"
    _lauf(cfg_ordner, lauf)


def test_agent_bekommt_die_zuordnung_mit_der_meldung(cfg_ordner):
    """Startet ein Panel mit altem PANEL in der kiosk.conf, meldet sein Agent die
    alte Ansicht: die Antwort nennt die zugeordnete (und deren Abschaltzeit), ein
    Agent, der das kann, uebernimmt sie ohne Neustart. "Start" mit Ansicht unter
    Geraete ist dieselbe Wahl und schreibt die Zuordnung ebenso."""
    async def lauf(w: Server):
        meldung = {"name": "wand", "panel": "day", "ip": "10.0.0.5", "port": 9, "kiosk": True, "features": ["panel"]}
        r = await w.post("/api/agent/announce", meldung)
        assert "panel" not in r and r["dpmsOff"] == 300
        await w.post("/api/device/switch", {"device": "wand", "panel": "night"})
        r = await w.post("/api/agent/announce", meldung)
        assert (r.get("panel"), r["dpmsOff"]) == ("night", 30)
        r = await w.post("/api/agent/announce", {**meldung, "panel": "night"})   # uebernommen
        assert "panel" not in r and r["dpmsOff"] == 30
        # ein alter Agent ohne das Merkmal bekommt nichts (er koennte es nicht uebernehmen)
        r = await w.post("/api/agent/announce", {**meldung, "ip": "10.0.0.6", "features": []})
        assert "panel" not in r
        # Start mit Ansicht: Befehl an den Agenten scheitert (kein Agent unter 10.0.0.5),
        # die Zuordnung ist trotzdem gesetzt
        j = await w.post("/api/agent/command", {"ip": "10.0.0.5", "action": "start", "panel": "day"})
        assert not j["ok"] and w.gespeichert()["wand"]["panel"] == "day"
        j = await w.post("/api/agent/command", {"ip": "10.0.0.5", "action": "start", "panel": "nix"})
        assert not j["ok"] and j["error"] == "unbekannte Ansicht"
    _lauf(cfg_ordner, lauf)


def test_betriebsmodus_ueberlagert_die_zuordnung(cfg_ordner):
    """Zuordnung night; der Modus tag zieht das Geraet beim Verbinden auf day,
    eine ausdrueckliche Wahl hebt ihn fuer das Geraet auf (und ist die neue
    Zuordnung), der naechste Moduswechsel gilt wieder, danach bleibt die
    Zuordnung fuer die Zeit ohne Modus bestehen."""
    async def lauf(w: Server):
        await w.post("/api/device/switch", {"device": "wand", "panel": "night"})
        async with w.s.get(w.basis + "/api/mode/tag") as r:
            assert (await r.json())["ok"]
        assert w.app.ansicht_fuer_geraet("wand") == "day"
        assert (await w.theme("?panel=night&device=wand"))["title"] == "Tag"
        await w.post("/api/device/switch", {"device": "wand", "panel": "night"})
        assert (await w.theme("?panel=day&device=wand"))["title"] == "Nacht"
        async with w.s.get(w.basis + "/api/mode/tag") as r:
            assert (await r.json())["ok"]
        assert (await w.theme("?panel=night&device=wand"))["title"] == "Tag"
        assert w.gespeichert()["wand"]["panel"] == "night", "der Modus aendert die Zuordnung nicht"
    _lauf(cfg_ordner, lauf)
