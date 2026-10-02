"""Zustandszeilen der Kacheln: Zentral-Bausteine zaehlen Raeume in Einzahl und
Mehrzahl ("Spielt in 1 Raum", nicht "in 1 Raeumen"), und die Kachel der
Radiotasten zeigt ohne aktiven Ausgang denselben Text wie ihre Detailseite
(allOff aus der Struktur, etwa "Automatik")."""
import json

import pytest

from lox import W, anlage


def _app(controls: dict, states: dict):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(controls))
    app.states = dict(states)
    return app


def _zone(uuid):
    return {"name": f"Zone {uuid}", "type": "AudioZoneV2", "uuidAction": uuid, "room": "r1", "cat": "c1",
            "states": {"playState": f"{uuid}-ps"}}


def _licht(uuid):
    return {"name": f"Licht {uuid}", "type": "LightControllerV2", "uuidAction": uuid, "room": "r1", "cat": "c1",
            "states": {"activeMoods": f"{uuid}-am", "moodList": f"{uuid}-ml"}}


@pytest.mark.parametrize("an, zeile", [(0, "Aus"), (1, "Spielt in 1 Raum"), (2, "Spielt in 2 Räumen")])
def test_audio_zentral_zaehlt_raeume(an, zeile):
    zonen = {u: _zone(u) for u in ("Z1", "Z2", "Z3")}
    zentral = {"name": "Audio Zentral", "type": "CentralAudioZone", "uuidAction": "CA", "room": "r1", "cat": "c1",
               "states": {}, "details": {"controls": [{"uuid": u} for u in zonen]}}
    states = {f"{u}-ps": (2 if i < an else 0) for i, u in enumerate(zonen)}
    app = _app({**zonen, "CA": zentral}, states)
    assert app._control_item("CA")["sublabel"] == zeile


@pytest.mark.parametrize("an, zeile", [(0, "Aus"), (1, "In 1 Raum aktiv"), (2, "In 2 Räumen aktiv")])
def test_licht_zentral_zaehlt_raeume(an, zeile):
    lichter = {u: _licht(u) for u in ("L1", "L2", "L3")}
    zentral = {"name": "Licht Zentral", "type": "CentralLightController", "uuidAction": "CL", "room": "r1",
               "cat": "c1", "states": {}, "details": {"controls": [{"uuid": u} for u in lichter]}}
    stimmungen = json.dumps([{"id": 778, "name": "Aus"}, {"id": 1, "name": "Hell"}])
    states = {}
    for i, u in enumerate(lichter):
        states[f"{u}-ml"] = stimmungen
        states[f"{u}-am"] = json.dumps([1] if i < an else [778])
    app = _app({**lichter, "CL": zentral}, states)
    assert app._control_item("CL")["sublabel"] == zeile


RADIO_AUSGAENGE = {"1": "Stufe 1", "2": "Stufe 2", "3": "Stufe 3"}


@pytest.mark.parametrize("ruhe, aktiv, zeile", [
    ("Automatik", 0, "Automatik"),
    (None, 0, "–"),
    ("Automatik", 2, "Stufe 2"),
    ("Automatik", 7, "Ausgang 7"),
], ids=["ruhe-mit-text", "ruhe-ohne-text", "ausgang", "unbekannter-ausgang"])
def test_radiotasten_kachel(ruhe, aktiv, zeile):
    details = {"outputs": RADIO_AUSGAENGE, **({"allOff": ruhe} if ruhe else {})}
    radio = {"RA": {"name": "Lüfterstufen", "type": "Radio", "uuidAction": "RA", "room": "r1", "cat": "c1",
                    "states": {"activeOutput": "ra"}, "details": details}}
    app = _app(radio, {"ra": aktiv})
    kachel = app._control_item("RA")
    assert kachel["sublabel"] == zeile
    # Kachel und Detailseite sagen dasselbe: der aktive Eintrag der Detailseite
    # traegt den Text der Kachel (ausser fuer einen Ausgang, den die Struktur
    # nicht kennt, und ohne allOff, dann ist in der Detailseite nichts aktiv)
    aktive = [e["label"] for e in app._view_control_inner("RA")["items"] if e.get("on")]
    if zeile.startswith("Ausgang") or zeile == "–":
        assert aktive == []
    else:
        assert aktive == [zeile]
