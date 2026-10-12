"""Hausuebersicht (Tab "haus", App._view_haus) im Server: Tab und Route, je
Raum eine Karte mit Hauptwert und Symbolen, "Gerade aktiv" (an UND mit
Aus-Befehl aus HAUS_AUS), die Zentral-Tasten mit ihren Befehlen
(haus_aus_befehle, ohne gesicherte Bausteine), der Spieler aus den Bloecken
der Detailseite und die Energie fuer den Kopf. Anlage: lox.haus_anlage()."""
import asyncio
import json
import math

import pytest
from aiohttp.test_utils import make_mocked_request

from lox import EM2, W, anlage, haus_anlage


def _app(**states):
    struktur, st = haus_anlage()
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    app.states = {**st, **states}
    return app


def _haus(app, prof=None, **route):
    return app.render({"view": "tab", "tab": "haus", **route}, prof)


def _raum(v, name):
    return next(r for r in v["raeume"] if r["name"] == name)


def test_haus_ist_ein_tab():
    assert W._is_tab("haus")
    panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["haus", "favoriten"]}})
    assert panels["p"]["tabs"] == ["haus", "favoriten"]
    app = _app()
    r = make_mocked_request("GET", "/api/meta", app={"app": app})
    tabs = [t["tab"] for t in json.loads(asyncio.run(W.api_meta(r)).body)["tabs"]]
    # hinter den Standard-Tabs und der freien Auswahl: defaultTabs() im
    # Konfigurator nimmt die ersten vier, die bleiben so dieselben
    assert tabs[:5] == ["favoriten", "zentral", "raeume", "kategorien", "auswahl"] and "haus" in tabs, tabs
    # beide Wege fuehren zur selben Seite, die Route kommt unveraendert zurueck
    assert app._view_tab("haus")["layout"] == "haus"
    v = _haus(app, zone="AB", liste="aktiv")
    assert v["layout"] == "haus" and v["title"] == "Haus" and v["tab"] == "haus"
    assert v["route"] == {"view": "tab", "tab": "haus", "zone": "AB", "liste": "aktiv"}
    assert v["liste"] == "aktiv" and "liste" not in _haus(app)


def test_raumkarten():
    v = _haus(_app())
    # Folge der Raumliste, nur Raeume mit sichtbaren Bausteinen
    assert [r["name"] for r in v["raeume"]] == ["Abstellraum", "Bad", "Eingang", "Essen-Kochen-Wohnen",
                                                "Küche", "Sauna", "Zentral"]
    kueche, sauna = _raum(v, "Küche"), _raum(v, "Sauna")
    # Raumregelung/Sauna: Ist-Temperatur gross, ihr Baustein nicht noch als Symbol
    assert (kueche["wert"], kueche["sub"]) == ("21,5°", "Soll 22,0° · heizt")
    assert kueche["symbole"] == []
    assert (sauna["wert"], sauna["sub"]) == ("25,4°", "Aus")
    assert [s["icon"] for s in sauna["symbole"]] == ["bulb"]
    # sonst der Zustand des ersten Bausteins, der an ist
    ab = _raum(v, "Abstellraum")
    assert (ab["wert"], ab["sub"], ab["an"]) == ("Hell", "Licht", 1)
    assert [(s["icon"], s["on"]) for s in ab["symbole"]] == [("bulb", True), ("music", False)]
    assert ab["nav"] == {"view": "group", "kind": "room", "id": "r7"} and ab["anzahl"] == 2
    # schaltbare zuerst, hoechstens HAUS_SYMBOLE; die Lueftung laeuft, zaehlt aber nicht als "an"
    zentral = _raum(v, "Zentral")
    assert len(zentral["symbole"]) == W.HAUS_SYMBOLE and zentral["symbole"][0]["icon"] == "switch"
    assert zentral["an"] == 1


def test_raumfilter_der_ansicht():
    app = _app()
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["haus"], "rooms": ["r5", "r6"]}})
    v = _haus(app, app.resolve_profile("p"))
    assert [r["name"] for r in v["raeume"]] == ["Küche", "Sauna"]
    # ohne Zonen und Licht, das an ist: kein Spieler, keine Audio-Taste
    assert v["spieler"] is None and v["aktiv"] == []
    assert [z["art"] for z in v["zentral"]] == ["licht"]


def test_gerade_aktiv():
    v = _haus(_app())
    aktiv = {a["id"]: a for a in v["aktiv"]}
    assert list(aktiv) == ["LA", "AL", "AZ", "FS"]
    assert aktiv["LA"]["aus"] == {"uuid": "LA", "cmd": "changeTo/778"} and aktiv["LA"]["taste"] == "Aus"
    assert aktiv["AZ"]["aus"] == {"uuid": "AZ", "cmd": "pause"} and aktiv["AZ"]["taste"] == "Pause"
    assert (aktiv["AZ"]["zustand"], aktiv["AZ"]["raum"]) == ("Hitradio Ö3", "Essen-Kochen-Wohnen")
    assert aktiv["AL"]["secured"] is True and "secured" not in aktiv["FS"]
    # Lueftung laeuft, hat aber keinen Aus-Befehl; was aus ist, steht nicht da
    assert "LU" not in aktiv and "SA" not in aktiv and "AB" not in aktiv
    # Sauna an: steht unter "Gerade aktiv", obwohl ihre Temperatur der Hauptwert ist
    v = _haus(_app(sa1=1))
    sauna = next(a for a in v["aktiv"] if a["id"] == "SA")
    assert sauna["aus"] == {"uuid": "SA", "cmd": "off"} and _raum(v, "Sauna")["an"] == 1


def test_zentral_tasten():
    app = _app()
    # nur was an ist; das gesicherte Aussenlicht (Visu-PIN) bleibt aussen vor
    assert app.haus_aus_befehle("licht", None) == [("LA", "changeTo/778")]
    assert app.haus_aus_befehle("audio", None) == [("AZ", "pause")]
    app.states.update({"lc1": json.dumps([1]), "ab1": 2})
    assert sorted(app.haus_aus_befehle("licht", None)) == [("LA", "changeTo/778"), ("LC", "changeTo/778")]
    assert sorted(app.haus_aus_befehle("audio", None)) == [("AB", "pause"), ("AZ", "pause")]
    assert app.haus_aus_befehle("unbekannt", None) == []


def test_spieler():
    app = _app()
    sp = _haus(app)["spieler"]
    # ohne Wahl die erste Zone, die spielt; Inhalt wie auf der Detailseite
    assert sp["zone"] == "AZ" and sp["name"] == "Essen-Kochen-Wohnen" and sp["spielt"]
    assert sp["titel"] == "Hitradio Ö3"
    assert [t["icon"] for t in sp["tasten"]] == ["prev", "pause", "next"]
    assert sp["laut"] == {"wert": 24, "cmd": {"uuid": "AZ", "tmpl": "volume/{v}"}, "min": 0, "max": 100,
                          "schritt": W.PROZENT_SCHRITT}
    assert [(z["id"], z["name"], z["spielt"]) for z in sp["zonen"]] == [
        ("AB", "Abstellraum", False), ("AZ", "Essen-Kochen-Wohnen", True)]
    # gewaehlte Zone aus der Route
    sp = _haus(app, zone="AB")["spieler"]
    assert sp["zone"] == "AB" and not sp["spielt"] and sp["laut"]["wert"] == 10
    assert [t["icon"] for t in sp["tasten"]] == ["prev", "play", "next"]
    # unbekannte Zone: wie ohne Wahl
    assert _haus(app, zone="XX")["spieler"]["zone"] == "AZ"


def test_energie_im_kopf():
    e = _haus(_app())["energie"]
    assert e["id"] == "F" and e["label"] == "Energieflussmonitor"
    assert e["wert"] == "PV 0,00 kW · Bezug 0,80 kW" and e["nav"] == {"view": "control", "id": "F"}


def test_freie_seite_als_hausuebersicht():
    """Eine Seite der eigenen Auswahl kann die Hausuebersicht sein (Seiten-
    Editor, Seiteninhalt "Hausuebersicht"): sie bleibt beim Speichern und im
    Export, ihre Route samt Zone und Unterseite fuehrt zur Hausseite, die
    Leiste zeigt ohne eigenes Symbol das Haus."""
    app = _app()
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["auswahl", "auswahl2"], "pickTabs": [
        {"name": "Licht", "picks": ["LA"]}, {"name": "Unser Haus", "picks": [], "widget": "haus"}]}})
    seiten = app.panels["p"]["pickTabs"]
    assert seiten[1] == {"name": "Unser Haus", "picks": [], "widget": "haus"}
    assert app._panel_export(app.panels["p"])["pickTabs"][1]["widget"] == "haus"
    prof = app.resolve_profile("p")
    v = app.render({"view": "tab", "tab": "auswahl2", "zone": "AB", "liste": "aktiv"}, prof)
    assert (v["layout"], v["title"], v["tab"], v["liste"]) == ("haus", "Unser Haus", "auswahl2", "aktiv")
    assert v["spieler"]["zone"] == "AB" and len(v["aktiv"]) == 4
    assert app._view_tab("auswahl2", prof)["layout"] == "haus"
    # die andere Seite bleibt eine Kachelseite
    assert app.render({"view": "tab", "tab": "auswahl"}, prof).get("layout") is None
    meta = app._tab_meta(["auswahl", "auswahl2"], prof)
    assert meta["auswahl2"]["haus"] is True and "haus" not in meta["auswahl"]


UNENDLICH = [math.nan, math.inf, -math.inf]


@pytest.mark.parametrize("wert", UNENDLICH, ids=["nan", "inf", "-inf"])
@pytest.mark.parametrize("state", ["f-a1", "f-p", "f-a3", "f-g"],
                         ids=["pv-knoten", "ppwr", "verbraucher", "netz"])
def test_energie_nan_und_unendlich(state, wert):
    """Ein Energiewert ist NaN oder unendlich (als Binaer-Double gueltig): Die
    Hausseite zeigt trotzdem alle Raumkarten und Tasten, der Wert gilt als
    unbekannt - keine erfundene Null, kein "nan kW", kein NaN im JSON."""
    app = _app(**{state: wert})
    for v in (_haus(app), app.render({"view": "control", "id": "F"}, None)):
        json.dumps(v, allow_nan=False)
        assert "nan" not in json.dumps(v).lower() and "inf " not in json.dumps(v).lower()
    v = _haus(app)
    assert len(v["raeume"]) == 7 and v["zentral"] and v["spieler"]
    e = v["energie"]
    assert e["id"] == "F" and all(isinstance(e.get(k), (int, type(None))) for k in ("prod", "cons"))
    if state == "f-g":
        assert e["cons"] == 100, "der Verbrauch kommt vom Verbraucher-Knoten, nicht aus der Bilanz"
        assert "Bezug" not in e["wert"] and "Einspeisung" not in e["wert"], e["wert"]
    if state == "f-p":
        assert e["prod"] == 100, "die Erzeugung kommt vom PV-Knoten"
        assert not e["wert"].startswith("PV"), e["wert"]


def test_erzeugung_unbekannt_ist_keine_null():
    """PV-Knoten und Ppwr ohne endlichen Wert: Die Erzeugung fehlt, statt als
    0 W zu erscheinen; der Verbrauch aus den Verbraucher-Knoten bleibt."""
    app = _app(**{"f-a1": math.nan, "f-p": math.inf})
    assert app.energy_blocks("F")["totals"]["prod"] is None
    e = _haus(app)["energie"]
    assert "prod" not in e and e["cons"] == 100, e


@pytest.mark.parametrize("wert", UNENDLICH, ids=["nan", "inf", "-inf"])
def test_energiemanager_nan_und_unendlich(wert):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"M": EM2}))
    app.states = {"m-p": wert, "m-g": 0.5, "m-s": wert, "m-soc": wert}
    eb = app.energy_blocks("M")
    assert eb["totals"]["prod"] is None and eb["totals"]["cons"] is None, eb["totals"]
    assert app._control_item("M", None)["sublabel"] == "Energiemanager"
    for v in (eb, app.render({"view": "control", "id": "M"}, None), app._haus_energie(["M"], None)):
        json.dumps(v, allow_nan=False)
    e = app._haus_energie(["M"], None)
    assert "prod" not in e and "cons" not in e


def test_freie_haus_seite_mit_nan():
    app = _app(**{"f-a1": math.nan, "f-p": math.nan})
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["auswahl"], "pickTabs": [
        {"name": "Unser Haus", "picks": [], "widget": "haus"}]}})
    v = app.render({"view": "tab", "tab": "auswahl"}, app.resolve_profile("p"))
    json.dumps(v, allow_nan=False)
    assert v["layout"] == "haus" and len(v["raeume"]) == 7 and "prod" not in v["energie"]
