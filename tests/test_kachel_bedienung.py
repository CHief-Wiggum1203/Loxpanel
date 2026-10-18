"""Bedienelemente direkt auf der Kachel, Server-Seite: der Schieber oben
rechts an Schalter und Zeitschalter (kopfTaste "schieber"), der runde Knopf am
Taster ("rund") und ‹ › fuer die vorige und naechste Stimmung der
Lichtsteuerung (controls, changeTo laut Strukturdoku). Die Stimmung waehlt
dieselbe Regel wie das Quer-Wischen der Gesten (_lc_schritt): "Aus"
uebersprungen, rundum, aus dem Aus heraus die erste bzw. letzte. Gesperrt
und auf der Uhr-Seite gibt es beides nicht. Dazu --on-glow (Knopf des
Schiebers auf --glow) auch ohne Kachel-Set und zu einer gewaehlten
Zustandsfarbe."""
import json

import pytest

from lox import anlage, W

import theme_colors as TC

STIMMUNGEN = json.dumps([{"id": 778, "name": "Aus"}, {"id": 1, "name": "Hell"},
                         {"id": 2, "name": "Lesen"}, {"id": 3, "name": "Kino"}])


def _b(uuid, typ, states, **extra):
    return {"name": f"{typ} {uuid}", "type": typ, "uuidAction": uuid, "room": "r1", "cat": "c1",
            "isFavorite": True, "states": states, **extra}


BAUSTEINE = {
    "SW": _b("SW", "Switch", {"active": "sw-a", "jLocked": "sw-lock"}, details={"jLockable": True}),
    "TS": _b("TS", "TimedSwitch", {"deactivationDelay": "ts-d"}),
    "PB": _b("PB", "Pushbutton", {"active": "pb-a"}),
    "LC": _b("LC", "LightControllerV2", {"activeMoods": "lc-am", "moodList": "lc-ml", "jLocked": "lc-lock"},
             details={"jLockable": True}),
}


def _app(**states):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"sw-a": 0, "sw-lock": "", "ts-d": 0, "pb-a": 0, "lc-am": "[2]", "lc-ml": STIMMUNGEN,
                  "lc-lock": "", **states}
    return app


def _kachel(app, uuid):
    return app._control_item(uuid, None)


def test_schieber_an_schalter_und_zeitschalter():
    app = _app()
    sw, ts = _kachel(app, "SW"), _kachel(app, "TS")
    assert sw["kopfTaste"] == ts["kopfTaste"] == "schieber"
    # der Schieber hat keinen eigenen Befehl: die Kachel schaltet wie bisher
    assert sw["cmd"] == {"uuid": "SW", "cmd": "on"} and not sw["on"]
    assert ts["cmd"] == {"uuid": "TS", "cmd": "pulse"} and not ts["on"]
    app.states.update({"sw-a": 1, "ts-d": 90})
    sw, ts = _kachel(app, "SW"), _kachel(app, "TS")
    assert sw["on"] and sw["cmd"]["cmd"] == "off" and ts["on"] and ts["cmd"]["cmd"] == "off"
    assert "controls" not in sw and "nav" not in sw


def test_runder_knopf_am_taster():
    pb = _kachel(_app(), "PB")
    assert pb["kopfTaste"] == "rund" and pb["cmd"] == {"uuid": "PB", "cmd": "pulse"}


@pytest.mark.parametrize("aktiv, zurueck, weiter", [
    ("[2]", 1, 3),          # mittendrin
    ("[3]", 2, 1),          # am Ende rundum zur ersten
    ("[1]", 3, 2),          # am Anfang rundum zur letzten
    ("[778]", 3, 1),        # aus: die letzte bzw. die erste, "Aus" uebersprungen
    ("[3, 1]", 2, 1),       # mehrere aktiv: von der ersten aus
], ids=["mitte", "ende", "anfang", "aus", "mehrere"])
def test_stimmung_zurueck_und_weiter(aktiv, zurueck, weiter):
    app = _app(**{"lc-am": aktiv})
    lc = _kachel(app, "LC")
    assert [c["icon"] for c in lc["controls"]] == ["zurueck", "weiter"]
    assert [c["cmd"] for c in lc["controls"]] == [{"uuid": "LC", "cmd": f"changeTo/{zurueck}"},
                                                  {"uuid": "LC", "cmd": f"changeTo/{weiter}"}]
    # der Tipp auf die Kachel oeffnet weiter die Detailseite
    assert lc["nav"] == {"view": "control", "id": "LC"} and "kopfTaste" not in lc
    # dieselbe Regel wie das Quer-Wischen der Gesten
    an = aktiv != "[778]"
    assert (app._lc_schritt("LC", -1, an), app._lc_schritt("LC", 1, an)) == (zurueck, weiter)


@pytest.mark.parametrize("liste", [
    [{"id": 778, "name": "Aus"}, {"id": 1, "name": "Hell"}],
    [{"id": 778, "name": "Aus"}],
    [],
], ids=["eine", "nur-aus", "keine"])
def test_ohne_zweite_stimmung_keine_tasten(liste):
    lc = _kachel(_app(**{"lc-ml": json.dumps(liste), "lc-am": "[778]"}), "LC")
    assert "controls" not in lc and lc["nav"] == {"view": "control", "id": "LC"}


def test_gesperrt_ohne_tasten():
    sperre = json.dumps({"locked": 1, "reason": "Wartung"})
    app = _app(**{"sw-lock": sperre, "lc-lock": sperre})
    sw, lc = _kachel(app, "SW"), _kachel(app, "LC")
    for k in ("cmd", "controls", "kopfTaste"):
        assert k not in sw and k not in lc, k
    assert sw["nav"] == {"view": "control", "id": "SW"}


def test_uhr_seite_ohne_tasten():
    werte = _app().status_blocks(["SW", "PB", "LC"])
    assert [w["id"] for w in werte] == ["SW", "PB", "LC"]
    assert all("kopfTaste" not in w and "controls" not in w for w in werte), werte


def test_on_glow_zu_dem_glow_der_gilt():
    """Knopf des Schiebers auf --glow: ohne Set und Grundfarbe zur
    Standardfarbe der Visu, mit gewaehlter Zustandsfarbe zu dieser, sonst
    wie das Set oder die Grundfarbe es nennt."""
    ohne = W.App._theme_vars({}, {})
    assert ohne["--on-glow"] == TC.schrift_auf(TC.VISU_STANDARD["--glow"])
    rot = W.App._theme_vars({"active": "#d03030"}, {})
    assert rot["--glow"] == "#d03030" and rot["--on-glow"] == TC.schrift_auf("#d03030")
    loxone = W.App._theme_vars({}, {"tileSet": "loxone"})
    assert loxone["--on-glow"] == TC.KACHEL_SETS["loxone"]["farben"]["--on-glow"]
    for v in (ohne, rot, loxone):
        assert TC.kontrast(v["--on-glow"], v.get("--glow") or TC.VISU_STANDARD["--glow"]) >= TC.AA
