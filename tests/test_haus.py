"""Hausuebersicht (Tab "haus", App._view_haus) im Server: Tab und Route, je
Raum eine Karte mit Hauptwert und Symbolen, "Gerade aktiv" (an UND mit
Aus-Befehl aus HAUS_AUS), die Zentral-Tasten mit ihren Befehlen
(haus_aus_befehle, ohne gesicherte Bausteine), der Spieler aus den Bloecken
der Detailseite und die Energie fuer den Kopf. Anlage: lox.haus_anlage()."""
import asyncio
import json

from aiohttp.test_utils import make_mocked_request

from lox import W, haus_anlage


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
