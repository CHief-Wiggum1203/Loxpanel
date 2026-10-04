"""Display-Kennwoerter (Fully Kiosk Remote Admin) verlassen den Server nicht.
/api/meta und die Antwort von POST /api/devices nennen nur, ob eines
gespeichert ist (hasPass) - wie /api/settings beim Miniserver und der Kamera.
Ein leeres Feld beim Speichern heisst "unveraendert", aber nur beim selben
Ziel (Host und Treiber, _KENNWORT_ZIEL wie beim Einspielen einer Sicherung);
sonst ginge das gespeicherte Kennwort an einen anderen Host. Auch der
Fehlertext eines Display-Treibers (Antwort von /api/display und Log) nennt
es nicht. Alle Tests im umgeleiteten Config-Ordner (Fixture cfg_ordner)."""
import asyncio
import copy
import io
import json
import zipfile

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from lox import W, anlage

GEHEIM = "GEHEIM-FULLY-4711"
GEHEIM_MS = "GEHEIM-MS-0815"
GEHEIM_IC = "GEHEIM-IC-1234"
BAUSTEINE = {
    "PM": {"name": "Präsenz Flur", "type": "PresenceDetector", "uuidAction": "PM", "room": "r1", "cat": "c1",
           "states": {"active": "pm_a"}},
    "IC": {"name": "Haustür", "type": "Intercom", "uuidAction": "IC", "room": "r1", "cat": "c1",
           "states": {"bell": "ic_b"}},
}
FULLY = {"driver": "fully", "host": "Tablet.lan", "port": 2323, "password": GEHEIM}
PANELS = {"panels": {"wohnen": {"title": "Wohnen", "tabs": ["favoriten"]}},
          "devices": {"tablet": {"auto": True, "modes": {"tag": "wohnen"}, "display": FULLY},
                      "flur": {"auto": True, "modes": {},
                               "display": {"driver": "wallpanel", "host": "10.0.0.8", "port": 2971,
                                           "password": ""}}}}
CFG = {"miniserver": {"host": "10.0.0.2", "user": "admin", "pass": GEHEIM_MS, "port": 443},
       "intercom": {"IC": {"url": "http://10.0.0.3/mjpg", "user": "cam", "pass": GEHEIM_IC}}}


def _app(cfg_ordner, panels=PANELS):
    (cfg_ordner / "loxpanel.cfg").write_text(json.dumps(CFG), encoding="utf-8")
    (cfg_ordner / "panels.json").write_text(json.dumps(panels), encoding="utf-8")
    app = W.App({"host": "", "port": 80})        # liest Profile und Geraete aus panels.json
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"pm_a": 0}
    return app


def _kennwort_werte(obj) -> list:
    """Alle Werte unter den Schluesseln pass und password, egal wie tief."""
    if isinstance(obj, dict):
        return [w for k, v in obj.items() for w in ([v] if k in ("pass", "password") else []) + _kennwort_werte(v)]
    if isinstance(obj, list):
        return [w for v in obj for w in _kennwort_werte(v)]
    return []


async def _client(app, *routen) -> TestClient:
    ui = web.Application()
    ui["app"] = app
    for methode, pfad, h in routen:
        ui.router.add_route(methode, pfad, h)
    cl = TestClient(TestServer(ui))
    await cl.start_server()
    return cl


def _gespeichert(cfg_ordner) -> dict:
    return json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["devices"]


def test_meta_nennt_nur_ob_ein_kennwort_da_ist(cfg_ordner):
    async def lauf():
        app = _app(cfg_ordner)
        assert app.devices["tablet"]["display"]["password"] == GEHEIM, "aus panels.json geladen"
        cl = await _client(app, ("GET", "/api/meta", W.api_meta))
        try:
            r = await cl.get("/api/meta")
            text = await r.text()
        finally:
            await cl.close()
        assert r.status == 200
        assert GEHEIM not in text
        geraete = json.loads(text)["devices"]
        assert _kennwort_werte(geraete) == []
        assert geraete["tablet"]["display"] == {"driver": "fully", "host": "Tablet.lan", "port": 2323,
                                                "hasPass": True}
        assert geraete["flur"]["display"]["hasPass"] is False
        assert app.devices["tablet"]["display"]["password"] == GEHEIM, "intern bleibt es"
    asyncio.run(lauf())


def test_jede_geraete_option_kommt_beim_konfigurator_an():
    """Was _sanitize_devices behaelt, gibt der Server an den Konfigurator - der
    schickt beim Speichern zurueck, was er bekam. Einzige Ausnahme: statt des
    Kennworts steht dort hasPass."""
    gespeichert = W.App._sanitize_devices(
        {"tablet": {"auto": False, "modes": {"tag": "wohnen"}, "scale": "auto", "presence": "PM",
                    "display": FULLY}}, {"wohnen"})["tablet"]
    assert set(gespeichert) == {"auto", "modes", "scale", "presence", "display"}, gespeichert
    exportiert = W.App._devices_export({"tablet": gespeichert})["tablet"]
    assert {k: v for k, v in exportiert.items() if k != "display"} == \
        {k: v for k, v in gespeichert.items() if k != "display"}
    ohne = {k: v for k, v in gespeichert["display"].items() if k != "password"}
    assert exportiert["display"] == {**ohne, "hasPass": True}
    assert gespeichert["display"]["password"] == GEHEIM, "der Export aendert die Vorlage nicht"


async def _speichern(cl, geraete) -> dict:
    r = await cl.post("/api/devices", json={"devices": geraete})
    text = await r.text()
    assert r.status == 200, text
    assert GEHEIM not in text, "die Antwort nennt das Kennwort nicht"
    return json.loads(text)


def _mit(display: dict) -> dict:
    """Geraete so, wie der Konfigurator sie zurueckschickt: tablet mit dem
    gegebenen Display, flur unveraendert."""
    geraete = copy.deepcopy(PANELS["devices"])
    geraete["tablet"]["display"] = display
    return geraete


@pytest.mark.parametrize("display", [
    pytest.param({"driver": "fully", "host": "Tablet.lan", "port": 2323, "password": ""}, id="leeres-feld"),
    # so, wie /api/meta es lieferte: kein password, dafuer hasPass
    pytest.param({"driver": "fully", "host": "Tablet.lan", "port": 2323, "hasPass": True}, id="wie-geliefert"),
    # anderer Port: dasselbe Geraet (Ziel = Host und Treiber)
    pytest.param({"driver": "fully", "host": " Tablet.lan ", "port": 2324, "password": ""}, id="anderer-port"),
])
def test_leeres_feld_behaelt_kennwort_beim_selben_ziel(cfg_ordner, display):
    async def lauf():
        app = _app(cfg_ordner)
        cl = await _client(app, ("POST", "/api/devices", W.api_save_devices))
        try:
            j = await _speichern(cl, _mit(display))
        finally:
            await cl.close()
        assert j["ok"]
        assert _gespeichert(cfg_ordner)["tablet"]["display"]["password"] == GEHEIM
        assert app.devices["tablet"]["display"]["password"] == GEHEIM
        assert app.devices["tablet"]["display"]["port"] == display["port"]
        assert _kennwort_werte(j["devices"]) == []
        assert j["devices"]["tablet"]["display"]["hasPass"] is True
        assert j["kennwortVerworfen"] == []
    asyncio.run(lauf())


@pytest.mark.parametrize("display", [
    pytest.param({"driver": "fully", "host": "10.0.0.10", "port": 2323, "password": ""}, id="anderer-host"),
    # Verglichen wird wie beim Einspielen genau: auch Gross-/Kleinschreibung zaehlt
    pytest.param({"driver": "fully", "host": "tablet.lan", "port": 2323, "password": ""}, id="andere-schreibweise"),
    pytest.param({"driver": "wallpanel", "host": "Tablet.lan", "port": 2323, "password": ""}, id="anderer-treiber"),
    # hasPass vom Client setzt nichts: der Server entscheidet am Ziel
    pytest.param({"driver": "fully", "host": "10.0.0.10", "port": 2323, "hasPass": True}, id="hasPass-vom-client"),
])
def test_anderes_ziel_uebernimmt_kein_kennwort(cfg_ordner, display):
    async def lauf():
        app = _app(cfg_ordner)
        cl = await _client(app, ("POST", "/api/devices", W.api_save_devices))
        try:
            j = await _speichern(cl, _mit(display))
        finally:
            await cl.close()
        assert j["ok"]
        assert _gespeichert(cfg_ordner)["tablet"]["display"]["password"] == ""
        assert app.devices["tablet"]["display"]["password"] == ""
        assert j["devices"]["tablet"]["display"]["hasPass"] is False
        assert j["kennwortVerworfen"] == ["tablet"], "der Konfigurator warnt"
    asyncio.run(lauf())


def test_neues_kennwort_ersetzt_das_alte(cfg_ordner):
    async def lauf():
        app = _app(cfg_ordner)
        cl = await _client(app, ("POST", "/api/devices", W.api_save_devices))
        try:
            # auch an einem neuen Ziel: wer das Kennwort eintippt, gibt es dafuer frei
            j = await _speichern(cl, _mit({"driver": "fully", "host": "10.0.0.10", "port": 2323,
                                          "password": "NEU-1234"}))
        finally:
            await cl.close()
        assert j["ok"]
        assert _gespeichert(cfg_ordner)["tablet"]["display"]["password"] == "NEU-1234"
        assert app.devices["tablet"]["display"]["password"] == "NEU-1234"
        assert "NEU-1234" not in json.dumps(j)
        assert j["devices"]["tablet"]["display"]["hasPass"] is True
        assert j["kennwortVerworfen"] == []
    asyncio.run(lauf())


ROUTEN_GET = [("GET", "/api/meta", W.api_meta), ("GET", "/api/settings", W.api_settings),
              ("GET", "/api/devices", W.api_devices_get), ("GET", "/api/agents", W.api_agents),
              ("GET", "/api/health", W.api_health), ("GET", "/api/types", W.api_types),
              ("GET", "/api/backup", W.api_backup)]


def test_keine_get_route_liefert_kennwoerter(cfg_ordner):
    """Waechter ueber alle lesenden Routen der Einstellungen: kein Kennwort
    (Miniserver, Kamera, Display) in der Antwort, auch nicht in der ZIP."""
    async def lauf():
        app = _app(cfg_ordner)
        cl = await _client(app, *ROUTEN_GET)
        treffer = {}
        try:
            for _, pfad, _h in ROUTEN_GET:
                r = await cl.get(pfad)
                body = await r.read()
                if pfad == "/api/backup":
                    z = zipfile.ZipFile(io.BytesIO(body))
                    text = "".join(z.read(n).decode("utf-8") for n in z.namelist())
                else:
                    text = body.decode("utf-8")
                treffer[pfad] = [g for g in (GEHEIM, GEHEIM_MS, GEHEIM_IC) if g in text]
        finally:
            await cl.close()
        assert treffer == {pfad: [] for _, pfad, _h in ROUTEN_GET}
    asyncio.run(lauf())


# Kennwort mit Zeichen, die quote() und yarl verschieden kodieren ("/" bleibt
# bei yarl stehen, " " wird %20): Es darf in keiner Form im Text stehen. Beide
# Teile kommen in jeder Kodierung unveraendert vor.
KENNWORT_TEILE = ("FULLY-GEHEIM", "zweiterTeil")
KENNWORT = KENNWORT_TEILE[0] + "/:@ " + KENNWORT_TEILE[1]


async def _gegenstelle(antwort):
    """Dienst am Ziel-Port, der kein Fully ist: antwort(anfrage) -> Bytes."""
    async def h(reader, writer):
        try:
            writer.write(antwort(await reader.read(4096)))
            await writer.drain()
        finally:
            writer.close()
    srv = await asyncio.start_server(h, "127.0.0.1", 0)
    return srv, srv.sockets[0].getsockname()[1]


GEGENSTELLEN = {
    # kein HTTP (etwa ein SSH-Port): aiohttp nennt die Adresse im Fehler
    "kein-http": lambda anfrage: b"SSH-2.0-OpenSSH_9.6\r\n",
    # gibt die Anfrage zurueck: steht dann in der Meldung des Parsers
    "echo": lambda anfrage: anfrage,
    # Fehlerseite mit der angefragten Adresse
    "fehlerseite": lambda anfrage: b"HTTP/1.1 404 Not Found\r\nContent-Length: %d\r\n\r\n%s" % (
        len(anfrage), anfrage),
}


@pytest.mark.parametrize("fall", [None, *GEGENSTELLEN], ids=["host-mit-port", *GEGENSTELLEN])
def test_display_fehler_nennt_das_kennwort_nicht(cfg_ordner, caplog, fall):
    async def lauf():
        srv = None
        if fall is None:
            # Host:Port im Host-Feld (_sanitize_display nimmt es an): ungueltige Adresse
            ziel = {"host": "127.0.0.1:2323", "port": 2323}
        else:
            srv, port = await _gegenstelle(GEGENSTELLEN[fall])
            ziel = {"host": "127.0.0.1", "port": port}
        panels = {"panels": PANELS["panels"],
                  "devices": {"tablet": {"display": {"driver": "fully", **ziel, "password": KENNWORT}}}}
        app = _app(cfg_ordner, panels)
        cl = await _client(app, ("GET", "/api/display", W.api_display))
        try:
            with caplog.at_level("WARNING", logger="loxpanel.webvisu"):
                r = await cl.get("/api/display?on=1&device=tablet")
                j = await r.json()
        finally:
            await cl.close()
            await app._drv_session.close()
            if srv:
                srv.close()
        [treiber] = j["drivers"]
        assert treiber["ok"] is False and treiber["error"], treiber
        for teil in KENNWORT_TEILE:
            assert teil not in json.dumps(j), j
            assert teil not in caplog.text, caplog.text
        assert "Display-Treiber tablet" in caplog.text, "der Fehler steht weiter im Log"
    asyncio.run(lauf())
