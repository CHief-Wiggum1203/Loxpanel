"""Beschattung (Jalousie): Die Kachel traegt Auf/Ab-Tasten mit denselben
Befehlen wie die Detailansicht. Im Stand starten sie die Fahrt, waehrend der
Fahrt halten beide an, und die fahrende Richtung zeigt Stop."""
import pytest

from lox import W, anlage

ROLLO = {"J": {"name": "Rollo Küche", "type": "Jalousie", "uuidAction": "J", "room": "r1", "cat": "c1",
               "states": {"position": "jp", "up": "ju", "down": "jd"}}}


def _app(**werte):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(ROLLO))
    app.states = {"jp": 0.4, "ju": 0, "jd": 0, **werte}
    return app


@pytest.mark.parametrize("werte, symbole, befehle, zeile", [
    ({}, ["triup", "tridown"], ["Up", "Down"], "40% zu"),
    ({"ju": 1}, ["stop", "tridown"], ["Stop", "Stop"], "▲ öffnet · 40% zu"),
    ({"jd": 1}, ["triup", "stop"], ["Stop", "Stop"], "▼ schließt · 40% zu"),
], ids=["stand", "faehrt-auf", "faehrt-ab"])
def test_kachel_wie_detailansicht(werte, symbole, befehle, zeile):
    app = _app(**werte)
    kachel = app._control_item("J")
    tasten = kachel["controls"]
    assert [t["icon"] for t in tasten] == symbole
    assert [t["cmd"] for t in tasten] == [{"uuid": "J", "cmd": b} for b in befehle]
    assert kachel["sublabel"] == zeile and kachel["nav"] == {"view": "control", "id": "J"}
    auf_ab = next(b for b in app._view_control_inner("J")["blocks"] if b.get("k") == "row")
    assert [z["cmd"] for z in auf_ab["cells"]] == [t["cmd"] for t in tasten], \
        "dieselben Befehle wie Auf/Ab in der Detailansicht"
