"""Gesperrte Bausteine (jLocked), Server-Seite.

Laut Strukturdoku ("Locking and Unlocking Controls") haelt der Text-State
jLocked bei einer Sperre ein JSON {locked, reason}: 1 = ueber die
Visualisierung, 2 = durch die Logik, leerer Text = nicht gesperrt. Ein
gesperrter Baustein nimmt keine Befehle an.

- Die Kachel nennt "Gesperrt", schaltet nicht und oeffnet die Detailseite.
- Jede Seite des Bausteins traegt gesperrt (wer und warum) und zeigt es oben.
- Ein Befehl an ihn (auch an einen Unterbaustein) geht nicht zum Miniserver,
  die Visu bekommt den Grund als Meldung; mit PIN fragt sie nicht erneut.
- Gesten schicken ihm nichts und zaehlen ihn als nicht ausgefuehrt.
"""
import asyncio
import json

import aiohttp
import pytest

from lox import anlage, Miniserver, neue_app, visu_starten, W, wecker_baustein
from bausteine import gemeinsam

GRUND = "Wartung"
LOGIK = json.dumps({"locked": 2, "reason": GRUND})
DIMMER = {"name": "Flur Dimmer", "type": "Dimmer", "uuidAction": "DIM", "room": "r1", "cat": "c1",
          "details": {"jLockable": True}, "links": ["SW"],
          "states": {"position": "dim-p", "min": "dim-mn", "max": "dim-mx", "step": "dim-st",
                     "jLocked": "dim-lock"}}
SCHALTER = {"name": "Flur Licht", "type": "Switch", "uuidAction": "SW", "room": "r1", "cat": "c1",
            "details": {"jLockable": True}, "states": {"active": "sw-a", "jLocked": "sw-lock"}}
# Lichtsteuerung mit Unterbaustein: der Dimmer im Inneren hat keinen eigenen
# jLocked und folgt der Lichtsteuerung, der Schalter hat einen eigenen
LICHT = {"name": "Licht Wohnen", "type": "LightControllerV2", "uuidAction": "LC", "room": "r1", "cat": "c1",
         "details": {"jLockable": True},
         "states": {"activeMoods": "lc-am", "moodList": "lc-ml", "jLocked": "lc-lock"},
         "subControls": {
             "LC/D1": {"name": "Decke", "type": "Dimmer", "uuidAction": "LC/D1", "states": {"position": "d1-p"}},
             "LC/S1": {"name": "Stehlampe", "type": "Switch", "uuidAction": "LC/S1",
                       "states": {"active": "s1-a", "jLocked": "s1-lock"}}}}


def _app(sperren: dict | None = None, ms=None):
    app = neue_app(ms) if ms else W.App({"host": "", "port": 80})
    controls = {u: {**c, "isFavorite": True} for u, c in (("DIM", DIMMER), ("SW", SCHALTER), ("LC", LICHT))}
    app._apply_structure(anlage(controls))
    app.states = {"dim-p": 40, "dim-mn": 0, "dim-mx": 100, "dim-st": 1, "sw-a": 1, "d1-p": 30, "s1-a": 0,
                  "lc-am": "[778]", "lc-ml": json.dumps([{"id": 778, "name": "Aus"}]),
                  "dim-lock": "", "sw-lock": "", "lc-lock": "", "s1-lock": "", **(sperren or {})}
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"]}})
    return app


@pytest.mark.parametrize("text, erwartet", [
    ("", None), ('{"locked": 0, "reason": "x"}', None), ('{"locked": 1, "reason": " Party "}', (1, "Party")),
    ('{"locked": 2}', (2, "")), ('{"locked": true}', (1, "")), ("kaputt", None), ("[1]", None),
    ('{"locked": "1"}', None)])
def test_sperre_lesen(text, erwartet):
    assert gemeinsam._sperre_lesen(text) == erwartet


@pytest.mark.parametrize("roh, text", [
    (json.dumps({"locked": 1, "reason": "Party"}), "Gesperrt über die Visualisierung: Party"),
    (json.dumps({"locked": 2}), "Gesperrt durch die Logik"),
    (json.dumps({"locked": 3, "reason": "neu"}), "Gesperrt: neu"),
    ("%7B%22locked%22%3A2%2C%22reason%22%3A%22Wartung%22%7D", f"Gesperrt durch die Logik: {GRUND}")])
def test_sperre_text(roh, text):
    assert _app({"dim-lock": roh})._sperre_text("DIM") == text


def test_zuordnung_mit_unterbausteinen():
    """Ein Unterbaustein ohne eigenen jLocked folgt seinem Baustein, mit eigenem
    zaehlt seiner. Bausteine ohne jLocked fehlen."""
    app = _app({"lc-lock": LOGIK})
    assert app.sperre_state["LC"] == app.sperre_state["LC/D1"] == "lc-lock"
    assert app.sperre_state["LC/S1"] == "s1-lock"
    assert app._sperre_text("LC/D1") == f"Gesperrt durch die Logik: {GRUND}"
    assert app._sperre_text("LC/S1") is None
    assert app._sperre_text("unbekannt") is None and app._sperre_text(None) is None
    app._apply_structure(anlage({"X": {"name": "X", "type": "Switch", "uuidAction": "X", "states": {"active": "x"}}}))
    assert app.sperre_state == {}


def test_kachel_gesperrt_schaltet_nicht():
    frei, gesperrt = _app()._control_item("SW"), _app({"sw-lock": LOGIK})._control_item("SW")
    assert frei.get("cmd") and frei.get("sublabel") != "Gesperrt"
    assert gesperrt["sublabel"] == "Gesperrt" and "cmd" not in gesperrt and "controls" not in gesperrt
    assert gesperrt["nav"] == {"view": "control", "id": "SW"}
    assert gesperrt["on"] is True, "der Zustand bleibt sichtbar"


def test_jede_seite_eines_gesperrten_bausteins():
    """Detailseite: der Grund steht nach dem Symbol oben; Unterseiten tragen
    gesperrt ebenso. Gruppe und Tab nicht, dort zaehlt die Kachel."""
    app = _app({"dim-lock": LOGIK})
    seite = app.render({"view": "control", "id": "DIM"})
    assert seite["gesperrt"] == f"Gesperrt durch die Logik: {GRUND}"
    ks = [b["k"] for b in seite["blocks"]]
    assert ks[:2] == ["hero", "status"] and seite["blocks"][1]["text"] == seite["gesperrt"]
    frei = _app().render({"view": "control", "id": "DIM"})
    assert "gesperrt" not in frei and [b["k"] for b in frei["blocks"]] == ks[:1] + ks[2:]
    assert "gesperrt" not in app.render({"view": "tab", "tab": "favoriten"})
    w, st = wecker_baustein()
    w = {**w, "states": {**w["states"], "jLocked": "wk-lock"}}
    app._apply_structure(anlage({"WK": w}))
    app.states = {**st, "wk-lock": json.dumps({"locked": 1})}
    assert app.render({"view": "alarmentry", "id": "WK", "entry": ""})["gesperrt"] == \
        "Gesperrt über die Visualisierung"


def test_befehl_an_gesperrten_baustein(miniserver_http):
    """Gesperrt: kein sps/io, die Visu bekommt den Grund; mit PIN zusaetzlich
    cmdresult mit gesperrt (keine neue PIN-Abfrage). Frei: wie immer."""
    async def lauf():
        ms = Miniserver()
        await ms.start()
        app = _app({"lc-lock": LOGIK}, ms=ms)
        runner, port, bc = await visu_starten(app)
        try:
            async with aiohttp.ClientSession() as s, s.ws_connect(f"http://127.0.0.1:{port}/ws?panel=test") as ws:
                async def bis(art):
                    while True:
                        m = await asyncio.wait_for(ws.receive_json(), 3)
                        if m.get("t") == art:
                            return m
                await ws.send_json({"t": "cmd", "uuid": "LC/D1", "cmd": "100"})
                ohne_pin = await bis("notify")
                await ws.send_json({"t": "cmd", "uuid": "LC", "cmd": "plus", "pin": "4711"})
                mit_pin = await bis("cmdresult"), await bis("notify")
                await ws.send_json({"t": "cmd", "uuid": "SW", "cmd": "off"})
                for _ in range(60):
                    if ms.io:
                        break
                    await asyncio.sleep(0.05)
                return ohne_pin, mit_pin, list(ms.io), list(ms.ios)
        finally:
            bc.cancel()
            await app.icon_session.close()
            await runner.cleanup()
            await ms.stop()
    ohne_pin, (ergebnis, meldung), io, ios = asyncio.run(lauf())
    text = f"Gesperrt durch die Logik: {GRUND}"
    assert ohne_pin["text"] == text and meldung["text"] == text
    assert ergebnis == {"t": "cmdresult", "ok": False, "gesperrt": True, "code": None, "uuid": "LC", "cmd": "plus"}
    assert io == ["sps/io/SW/off"] and ios == []


def test_gesten_schicken_gesperrten_nichts():
    app = _app({"dim-lock": LOGIK})
    geschickt = []

    async def command(uuid, cmd, pin=None):
        geschickt.append((uuid, cmd))
        return "200"
    app.command = command
    fehl = asyncio.run(app._geste_befehle([("DIM", "0"), ("SW", "off")]))
    assert fehl == 1 and geschickt == [("SW", "off")]
