"""Breite Kacheln (2 x 1), Server-Seite: Audio, Raumregelung und Energiefluss
belegen von Haus aus zwei Spalten (KACHEL_BREIT_TYPEN), je Kachel laesst sich
das uebersteuern (tiles[uuid].w = 1 | 2). Nur die breite Kachel traegt das
Feld w in der Kachelliste; was beim Speichern nicht 1 oder 2 ist, meldet der
Server als verworfen. Der Konfigurator bekommt die Typen aus /api/meta."""
import pytest

from lox import EFM, W, anlage

BAUSTEINE = {
    "S": {"name": "Licht", "type": "Switch", "uuidAction": "S", "room": "r1", "cat": "c1",
          "isFavorite": True, "states": {"active": "s"}},
    "AZ": {"name": "Küche", "type": "AudioZoneV2", "uuidAction": "AZ", "room": "r1", "cat": "c1",
           "isFavorite": True, "states": {"playState": "az1", "songName": "az2"}},
    "A1": {"name": "Bad", "type": "AudioZone", "uuidAction": "A1", "room": "r1", "cat": "c1",
           "isFavorite": True, "states": {"playState": "a11"}},
    "RC": {"name": "Wohnen", "type": "IRoomControllerV2", "uuidAction": "RC", "room": "r1", "cat": "c1",
           "isFavorite": True, "states": {"tempActual": "rc1", "tempTarget": "rc2", "operatingMode": "rc3",
                                          "activeMode": "rc4", "prepareState": "rc5"}},
    "F": {**EFM, "isFavorite": True},
}
STATES = {"s": 1, "az1": 0, "az2": "", "a11": 0, "rc1": 21.5, "rc2": 22.0, "rc3": 0, "rc4": 0, "rc5": 0}


def _app(tiles: dict | None = None) -> W.App:
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = dict(STATES)
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["favoriten"],
                                               **({"tiles": tiles} if tiles else {})}})
    return app


def _breiten(app: W.App) -> dict:
    prof = app.resolve_profile("p")
    return {u: app._control_item(u, prof).get("w") for u in BAUSTEINE}


def test_breit_nach_typ():
    assert _breiten(_app()) == {"S": None, "AZ": 2, "A1": 2, "RC": 2, "F": 2}
    assert "AudioZone" in W.KACHEL_BREIT_TYPEN and "EFM" in W.KACHEL_BREIT_TYPEN


def test_je_kachel_uebersteuerbar():
    app = _app({"AZ": {"w": 1}, "S": {"w": 2}, "RC": {"w": "2"}})
    assert _breiten(app) == {"S": 2, "AZ": None, "A1": 2, "RC": 2, "F": 2}


@pytest.mark.parametrize("wert, gespeichert", [
    (1, 1), (2, 2), ("1", 1), ("2", 2), (2.0, 2), (3, None), (0, None), (True, None), ("breit", None), (1.5, None),
])
def test_breite_wird_geprueft(wert, gespeichert):
    assert W._kachel_breite(wert) == gespeichert
    e = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["favoriten"], "tiles": {"S": {"w": wert}}}})["p"]
    assert (e.get("tiles") or {}).get("S", {}).get("w") == gespeichert


def test_ungueltige_breite_wird_gemeldet():
    roh = {"p": {"title": "P", "tabs": ["favoriten"], "tiles": {"S": {"w": 3}}}}
    assert W.App._panels_verworfen(roh, W.App._sanitize_panels(roh), {"S": "Licht"}) == ["P: tiles.Licht.w"]
    roh = {"p": {"title": "P", "tabs": ["favoriten"], "tiles": {"S": {"w": 2}}}}
    assert W.App._panels_verworfen(roh, W.App._sanitize_panels(roh), {"S": "Licht"}) == []


def test_export_und_rundweg():
    app = _app({"AZ": {"w": 1}})
    exp = app._panel_export(app.panels["p"])
    assert exp["tiles"]["AZ"]["w"] == 1
    assert W.App._sanitize_panels({"p": exp})["p"]["tiles"]["AZ"]["w"] == 1


def test_meta_nennt_die_breiten_typen():
    assert sorted(W.KACHEL_BREIT_TYPEN) == ["AudioZone", "AudioZoneV2", "EFM", "EnergyManager2",
                                             "IRoomController", "IRoomControllerV2"]
    assert W.KACHEL_BREITEN == (1, 2)
