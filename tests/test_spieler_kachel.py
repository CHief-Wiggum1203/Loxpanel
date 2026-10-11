"""Cover und Tasten der breiten Audio-Kachel auf dem Server: _audio_cover() ist
die eine Quelle fuer Detailseite und Kachel (it.cover), /api/meta nennt dem
Seiten-Editor je Baustein die Zahl der Kacheltasten und das Cover. Wie die
Visu beides zeigt, pruefen tests/browser/test_spieler_kachel_browser.py."""
import asyncio
import json
from urllib.parse import quote

from aiohttp.test_utils import make_mocked_request

from lox import W, anlage

LOGO = "http://audioserver/cover/sender.png"
BAUSTEINE = {
    "G1": {"name": "Radio Bad", "type": "AudioZone", "uuidAction": "G1", "room": "r1", "cat": "c1",
           "states": {"playState": "g1p", "cover": "g1c"}},
    "G2": {"name": "Radio Küche", "type": "AudioZoneV2", "uuidAction": "G2", "room": "r1", "cat": "c1",
           "states": {"playState": "g2p", "songName": "g2s", "cover": "g2c"}},
    "L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1", "states": {"active": "l"}},
}


def _app(**states):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"g1p": 2, "g1c": LOGO, "g2p": 2, "g2s": "Hitradio Ö3", "g2c": LOGO, "l": 0, **states}
    return app


def _block(view, art):
    return next((b for b in view["blocks"] if b["k"] == art), None)


def test_ein_cover_fuer_kachel_und_detailseite():
    app = _app()
    erwartet = "/cover?u=" + quote(LOGO, safe="")
    for uuid in ("G1", "G2"):
        assert app._audio_cover(app.controls[uuid]) == erwartet, uuid
        assert app._control_item(uuid)["cover"] == erwartet, uuid
        detail = app.render({"view": "control", "id": uuid}, None)
        assert _block(detail, "cover")["src"] == erwartet, uuid
    assert app._audio_cover(app.controls["L"]) is None and "cover" not in app._control_item("L")


def test_ohne_cover_kein_bild():
    app = _app(g1c="", g2c="")
    for uuid in ("G1", "G2"):
        assert app._audio_cover(app.controls[uuid]) is None and "cover" not in app._control_item(uuid), uuid
    # Gen2 ohne Bild: die Detailseite zeigt das Symbol
    assert _block(app.render({"view": "control", "id": "G2"}, None), "hero")["icon"] == "music"


def test_meta_nennt_tasten_und_cover():
    app = _app()
    r = make_mocked_request("GET", "/api/meta", app={"app": app})
    ctrls = {c["uuid"]: c for c in json.loads(asyncio.run(W.api_meta(r)).body)["controls"]}
    for uuid in ("G1", "G2"):
        assert ctrls[uuid]["tasten"] == len(app._control_item(uuid)["controls"]) == 3, ctrls[uuid]
        assert ctrls[uuid]["cover"] == app._control_item(uuid)["cover"], ctrls[uuid]
    assert ctrls["L"]["tasten"] == 0 and ctrls["L"]["cover"] == "", ctrls["L"]
