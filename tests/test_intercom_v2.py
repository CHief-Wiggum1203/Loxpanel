"""Neue Intercom (IntercomV2, in Loxone Config der Baustein "Intercom") laut
Strukturdoku 17.0: Klingel, Ausgaenge und answer wie bei der Tuersteuerung
(Intercom), dazu die Antworten (answers, playTts/{idx}), Stumm (muted,
mute/{0/1}) und der Geraetezustand (deviceState). Beide Bausteine kommen aus
tests/lox.py (intercom_baustein, intercom_v2_baustein)."""
import asyncio
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from lox import W, anlage, bloecke, intercom_baustein, intercom_v2_baustein


def _app(**kw) -> W.App:
    control, states = intercom_v2_baustein(**kw)
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"IC2V": control}))
    app.states = states
    return app


def _kachel(**kw) -> dict:
    it = _app(**kw)._control_item("IC2V")
    return {k: it.get(k) for k in ("icon", "on", "sublabel", "subInfo", "tone", "nav")}


def test_kachel():
    nav = {"view": "control", "id": "IC2V"}
    assert _kachel() == {"icon": "cam", "on": False, "sublabel": "Türsprechanlage", "subInfo": True,
                         "tone": None, "nav": nav}
    assert _kachel(bell=1) == {"icon": "cam", "on": True, "sublabel": "Es klingelt", "subInfo": None,
                               "tone": "crit", "nav": nav}


@pytest.mark.parametrize("werte, zeile", [
    ({"deviceState": 2}, "Startet neu"),
    ({"deviceState": 3}, "Startet"),
    ({"deviceState": "2"}, "Startet neu"),
    ({"muted": 1}, "Stummgeschaltet"),
    ({"muted": 1, "deviceState": 2}, "Startet neu"),
    ({"muted": 1, "bell": 1}, "Es klingelt"),
])
def test_kachel_nennt_zustand(werte, zeile):
    """Neustart und Stumm sind Zustaende: gross statt als Beschreibung."""
    k = _kachel(**werte)
    assert (k["sublabel"], k["subInfo"]) == (zeile, None)


@pytest.mark.parametrize("zustand", [0, 1, None, "kaputt"])
def test_kachel_ohne_hinweis(zustand):
    """StateOk, StateUnknown (sagt nichts Sicheres) und Unsinn: kein Hinweis."""
    assert _kachel(deviceState=zustand)["sublabel"] == "Türsprechanlage"


def _zeilen(view: dict) -> list:
    return [(b.get("id"), [(c["label"], (c.get("cmd") or {}).get("cmd"), c.get("on")) for c in b["cells"]])
            for b in bloecke(view, "row")]


def test_detailseite():
    v = _app().render({"view": "control", "id": "IC2V"})
    assert [b["k"] for b in v["blocks"]] == ["status", "row", "head", "row", "row"]
    assert bloecke(v, "status") == [{"k": "status", "text": "Kein Video eingerichtet"}]
    assert bloecke(v, "head") == [{"k": "head", "id": "antworten", "text": "Antwort abspielen"}]
    assert _zeilen(v) == [
        (None, [("Tür öffnen", "pulse", None)]),
        ("antworten", [("Bin gleich da", "playTts/0", None), ("Bitte das Paket vor die Tür legen", "playTts/1", None)]),
        ("stumm", [("Stumm", "mute/1", False)])]
    assert [c["cmd"]["uuid"] for b in bloecke(v, "row") for c in b["cells"]] == ["IC2V/1", "IC2V", "IC2V", "IC2V"]
    assert bloecke(v, "row")[1]["wrap"] is True


def test_detailseite_klingelt_und_startet_neu():
    v = _app(bell=1, deviceState=2, muted=1).render({"view": "control", "id": "IC2V"})
    assert [b["k"] for b in v["blocks"]] == ["astat", "status", "status", "row", "row", "head", "row", "row"]
    assert bloecke(v, "astat") == [{"k": "astat", "text": "Es klingelt", "tone": "crit"}]
    assert bloecke(v, "status")[0] == {"k": "status", "id": "zustand", "text": "Startet neu"}
    assert _zeilen(v)[1] == ("klingel", [("Klingel abstellen", "answer", None)])
    assert _zeilen(v)[-1] == ("stumm", [("Stumm", "mute/0", True)])


@pytest.mark.parametrize("antworten, soll", [
    (json.dumps(["A", "", "  ", "D"]), [("A", "playTts/0"), ("D", "playTts/3")]),   # Index bleibt der der Liste
    (json.dumps([]), []),
    ("", []),
    ("kein json", []),
    (json.dumps({"0": "A"}), []),
    (json.dumps(["A", 5, None, "B"]), [("A", "playTts/0"), ("B", "playTts/3")]),
    ("%5B%22Gleich%20da%22%5D", [("Gleich da", "playTts/0")]),                       # prozentkodiert
])
def test_antworten(antworten, soll):
    v = _app(antworten=(), answers=antworten).render({"view": "control", "id": "IC2V"})
    zeile = [b for b in bloecke(v, "row") if b.get("id") == "antworten"]
    assert [(c["label"], c["cmd"]["cmd"]) for z in zeile for c in z["cells"]] == soll
    assert bool(bloecke(v, "head")) == bool(soll), "Ueberschrift nur mit Antworten"


def test_stumm_nur_mit_state():
    """Ohne den State muted (aeltere Firmware) keine Stumm-Taste."""
    control, states = intercom_v2_baustein()
    del control["states"]["muted"]
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"IC2V": control}))
    app.states = states
    assert "stumm" not in [b.get("id") for b in app.render({"view": "control", "id": "IC2V"})["blocks"]]


def test_kamera_pane():
    """Die Kamera-Pane zeigt Klingel, Video und Ausgaenge; Zustand, Klingel-Zeile,
    Antworten und Stumm gehoeren nur auf die Detailseite."""
    blocks = _app(bell=1, deviceState=2, muted=1).intercom_blocks("IC2V")
    assert [(b["k"], b.get("id")) for b in blocks] == [("astat", None), ("status", None), ("row", None)]
    assert [c["label"] for c in blocks[2]["cells"]] == ["Tür öffnen"]


def test_klingel_meldet_sich():
    """bell 0 -> 1 oeffnet das Klingel-Popup wie bei der Tuersteuerung."""
    app = _app()
    app._on_value("ic2-bell", 0)
    assert app._pending_ring is None
    app._on_value("ic2-bell", 1)
    assert app._pending_ring == "IC2V"


def test_keine_verpassten_klingeln():
    """lastBellEvents gibt es laut Doku nur bei der Tuersteuerung: die v2 hat
    keine Zeile dafuer, und die Seite (etwa noch offen) sagt, dass es keine gibt."""
    app = _app()
    assert [b.get("id") for b in bloecke(app.render({"view": "control", "id": "IC2V"}), "row")].count("klingel") == 0
    assert [b["text"] for b in bloecke(app.render({"view": "bells", "id": "IC2V"}), "status")] == [
        "Keine verpassten Klingeln"]


def test_status_teilweise():
    """Gegensprechen fehlt bei beiden: teilweise unterstuetzt."""
    assert {t["type"]: t["status"] for t in _app().types_overview()["types"]}["IntercomV2"] == "partial"


def test_einstellungen_nennen_beide(cfg_ordner):
    """Settings -> Kamera / Türstation listet beide Bausteine fuer die Video-Adresse."""
    v1, s1 = intercom_baustein()
    v2, s2 = intercom_v2_baustein()

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage({"IC": v1, "IC2V": v2}))
        app.states = {**s1, **s2}
        ui = web.Application()
        ui["app"] = app
        ui.router.add_get("/api/settings", W.api_settings)
        async with TestClient(TestServer(ui)) as cl:
            return (await (await cl.get("/api/settings")).json())["intercoms"]
    assert sorted((e["uuid"], e["name"]) for e in asyncio.run(lauf())) == [
        ("IC", "Eingang Intercom"), ("IC2V", "Haustür Intercom")]
