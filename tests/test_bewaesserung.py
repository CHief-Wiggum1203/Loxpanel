"""Bewaesserung (Irrigation): frueher Start/Stopp nur fuer alle Zonen. Laut
Loxone-Strukturdoku zaehlen die Zonen ab 0 (zones[].id; currentZone 0 = Zone 1,
8 = alle, -1 = aus). select entspricht dem Eingang "Sel" des Bausteins
(Loxone-Wissensdatenbank: 1..8 = Ventil V1..V8, 0 alle aus, 9 alle an), also
select/{id+1}; die Laufzeit setzt setDuration/{id}={Sekunden}. Der Baustein
kommt aus tests/lox.py (bewaesserung_baustein)."""
import json

import pytest

from lox import W, anlage, bewaesserung_baustein, bloecke


def _app(**werte) -> W.App:
    control, states = bewaesserung_baustein(**werte)
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"BEW": control}))
    app.states = states
    return app


def _zone(zone, **werte) -> dict:
    return _app(**werte).render({"view": "irrzone", "id": "BEW", "zone": zone})


def _knoepfe(view: dict) -> list[list[tuple]]:
    return [[(c["label"], c["cmd"]["cmd"]) for c in b["cells"]] for b in bloecke(view, "row")]


@pytest.mark.parametrize("werte, text", [
    ({}, "Bereit"),
    ({"rainActive": 1}, "Regenpause"),
    ({"currentZone": 1, "active": 1}, "Bewässert · Beete"),
    ({"currentZone": 0}, "Bewässert · Rasen vorne"),     # ohne State active: laut Doku laeuft sie
    ({"currentZone": 8, "active": 1}, "Bewässert · Alle Zonen"),
])
def test_kachel(werte, text):
    it = _app(**werte)._control_item("BEW")
    assert it["sublabel"] == text and it["on"] is text.startswith("Bewässert")


def test_detail_zonen_mit_laufzeit():
    v = _app(currentZone=1, active=1, rainTime=1500, expectedPrecipitation=1.2).render(
        {"view": "control", "id": "BEW"})
    assert [b["text"] for b in bloecke(v, "status")] == [
        "Bewässerung", "Aktive Zone: Beete", "Erwarteter Niederschlag 1,2 mm · Grenze 2,0 mm",
        "Regen in den letzten 24 h: 25 min"]
    zonen, start, alle = bloecke(v, "row")
    assert zonen["wrap"] is True
    assert [(c["label"], c["on"], c["nav"]) for c in zonen["cells"]] == [
        ("Rasen vorne · 10 min", False, {"view": "irrzone", "id": "BEW", "zone": 0}),
        ("Beete · 5 min", True, {"view": "irrzone", "id": "BEW", "zone": 1}),
        ("Hecke · 15 min", False, {"view": "irrzone", "id": "BEW", "zone": 2})]
    assert [c["cmd"]["cmd"] for c in start["cells"]] == ["start", "startForce", "stop"]
    assert [c["cmd"]["cmd"] for c in alle["cells"]] == ["select/9", "select/0"]


def test_alle_zonen_aktiv():
    zonen = bloecke(_app(currentZone=8, active=1).render({"view": "control", "id": "BEW"}), "row")[0]
    assert all(c["on"] for c in zonen["cells"])


def test_ohne_regen_kein_regenhinweis():
    v = _app().render({"view": "control", "id": "BEW"})
    assert not any("Regen in" in b["text"] for b in bloecke(v, "status"))


@pytest.mark.parametrize("zone, befehl", [(0, "select/1"), (1, "select/2"), (2, "select/3")])
def test_zone_starten(zone, befehl):
    v = _zone(zone)
    assert [b["text"] for b in bloecke(v, "big")] == ["Aus"]
    assert _knoepfe(v) == [[("Zone starten", befehl)]]


def test_zone_laeuft():
    v = _zone(1, currentZone=1, active=1)
    assert [b["text"] for b in bloecke(v, "big")] == ["Läuft"]
    assert _knoepfe(v) == [[("Zone stoppen", "stop")]]
    assert _knoepfe(_zone(1, currentZone=0, active=1)) == [[("Zone starten", "select/2")]]
    assert _knoepfe(_zone(0, currentZone=8, active=1)) == [[("Alle Zonen stoppen", "stop")]]


def test_laufzeit_einstellen():
    st, = bloecke(_zone(1), "stepper")
    assert st == {"k": "stepper", "label": "Laufzeit", "value": 300, "fmt": "dauer", "step": 60, "min": 0,
                  "cmd": {"uuid": "BEW", "tmpl": "setDuration/1={v}"}}


def test_laufzeit_von_der_logik():
    st, = bloecke(_zone(2), "stepper")
    assert "cmd" not in st and st["sub"] == "von der Logik vorgegeben" and st["value"] == 900


@pytest.mark.parametrize("zone", [7, "x", None])
def test_unbekannte_zone(zone):
    assert [b["text"] for b in bloecke(_zone(zone), "status")] == ["Diese Zone gibt es nicht mehr."]


def test_zonen_ohne_namen_ohne_nummer_und_kaputt():
    app = _app(zones=json.dumps([{"id": 1, "duration": 60}, {"name": "ohne Nummer"}, "quatsch",
                                 {"id": 0, "name": "Erste"}]))
    assert app._irr_zones(app.controls["BEW"]) == [
        {"id": 0, "name": "Erste", "duration": None, "logic": False},
        {"id": 1, "name": "Zone 2", "duration": 60, "logic": False}]
    kaputt = _app(zones="{kaputt")
    assert kaputt._irr_zones(kaputt.controls["BEW"]) == []


def test_status_voll():
    assert {t["type"]: t["status"] for t in _app().types_overview()["types"]}["Irrigation"] == "full"


@pytest.mark.parametrize("sek, text", [(0, "0 min"), (45, "45 s"), (600, "10 min"), (90, "1 min 30 s"),
                                       (5400, "1 h 30 min"), (3600, "1 h"), ("x", "")])
def test_dauer_text(sek, text):
    assert W._dauer_text(sek) == text
