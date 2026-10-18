"""Hausuebersicht (Tab "haus", App._view_haus) im Server: Tab und Route, je
Raum eine Karte mit Hauptwert und Symbolen, "Gerade aktiv" (an UND mit
Aus-Befehl aus HAUS_AUS), die Schnellaktionen (Befehl an den Zentral-Baustein
der Anlage und wie viele seiner Mitglieder an sind), die Hinweise (was
Aufmerksamkeit braucht), der Spieler aus den Bloecken der Detailseite und die
Energie fuer den Kopf. Anlage: lox.haus_anlage()."""
import asyncio
import json
import math
from urllib.parse import quote

import pytest
from aiohttp.test_utils import make_mocked_request

from lox import anlage, EM2, haus, haus_anlage, HAUS_FAVORITEN, konfig, W

from bausteine.gemeinsam import SAUNA_STOERUNG, SAUNA_WASSER  # noqa: E402  # bin/ liegt durch lox auf dem Pfad


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
    assert konfig._is_tab("haus")
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
    assert len(zentral["symbole"]) == haus.HAUS_SYMBOLE and zentral["symbole"][0]["icon"] == "switch"
    assert zentral["an"] == 1


def test_raumfilter_der_ansicht():
    app = _app()
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["haus"], "rooms": ["r5", "r6"]}})
    v = _haus(app, app.resolve_profile("p"))
    assert [r["name"] for r in v["raeume"]] == ["Küche", "Sauna"]
    # ohne Zonen und Licht, das an ist: kein Spieler
    assert v["spieler"] is None and v["aktiv"] == []
    # die Schnellaktionen haengen an den Zentral-Bausteinen der Anlage, nicht
    # am Raumfilter (wie der Tab "Zentral")
    assert [s["art"] for s in v["schnell"]] == ["licht", "audio"]


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


def _schnell(app, prof=None):
    return {s["art"]: s for s in _haus(app, prof)["schnell"]}


def test_schnellaktionen():
    """"Alle Lichter aus" und "Alle Zonen aus" schicken den Befehl der
    Strukturdoku an den Zentral-Baustein (CentralLightController reset,
    CentralAudioZone pause); dazu, wie viele seiner Mitglieder an sind -
    dieselbe Zahl wie auf seiner Kachel, frisch aus den States."""
    app = _app()
    s = _schnell(app)
    assert list(s) == ["licht", "audio"]
    assert s["licht"] == {"art": "licht", "id": "CL", "label": "Alle Lichter aus", "an": 1,
                          "cmd": {"uuid": "CL", "cmd": "reset"}}
    assert s["audio"] == {"art": "audio", "id": "CA", "label": "Alle Zonen aus", "an": 1,
                          "cmd": {"uuid": "CA", "cmd": "pause"}}
    # mehr an: die Zahl steigt, wie auf der Kachel des Zentral-Bausteins
    app.states.update({"lc1": json.dumps([1]), "ab1": 2})
    s = _schnell(app)
    assert (s["licht"]["an"], s["audio"]["an"]) == (2, 2)
    assert app._control_item("CL")["sublabel"] == "In 2 Räumen aktiv"
    assert app._control_item("CA")["sublabel"] == "Spielt in 2 Räumen"
    # alles aus: 0, die Visu zeigt dann keine Zahl
    app.states.update({"lc1": json.dumps([778]), "la1": json.dumps([778]), "ab1": 0, "az1": 0})
    s = _schnell(app)
    assert (s["licht"]["an"], s["audio"]["an"]) == (0, 0)


def test_schnellaktionen_nur_mit_zentral_baustein():
    """Ohne Zentral-Baustein keine Taste - auch wenn die Seite Licht und
    Musik hat. Blendet die Ansicht den Baustein aus, gibt es sie dort auch
    nicht; ein gesicherter (Visu-PIN) fragt in der Visu nach der PIN."""
    struktur, st = haus_anlage()
    del struktur["controls"]["CL"], struktur["controls"]["CA"]
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    app.states = st
    v = _haus(app)
    assert v["schnell"] == [] and v["aktiv"], v["schnell"]
    # nur Audio-Zentral: nur "Alle Zonen aus"
    struktur, st = haus_anlage()
    del struktur["controls"]["CL"]
    app._apply_structure(struktur)
    assert list(_schnell(app)) == ["audio"]
    # in der Ansicht ausgeblendet
    app = _app()
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["haus"], "hide": ["CL"]}})
    assert list(_schnell(app, app.resolve_profile("p"))) == ["audio"]
    # gesichert
    app = _app()
    app.controls["CA"]["isSecured"] = True
    s = _schnell(app)
    assert s["audio"]["secured"] is True and "secured" not in s["licht"]


def _aufbau(aufbau, **states):
    app = _app(**states)
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["haus"], "ui": {"hausAufbau": aufbau}}})
    return app, _haus(app, app.resolve_profile("p"))


def test_aufbau_je_ansicht():
    """ui.hausAufbau: "raeume" und "spalte" bleiben beim Speichern und im
    Export, der Standard ("status") und Unbekanntes werden nicht gespeichert;
    ohne Einstellung gilt der Standard. /api/meta nennt Auswahl und Standard."""
    p = W.App._sanitize_panels({"a": {"title": "A", "ui": {"hausAufbau": "raeume"}},
                                "b": {"title": "B", "ui": {"hausAufbau": "spalte"}},
                                "c": {"title": "C", "ui": {"hausAufbau": "status"}},
                                "d": {"title": "D", "ui": {"hausAufbau": "quer"}}})
    assert [(p[k].get("ui") or {}).get("hausAufbau") for k in "abcd"] == ["raeume", "spalte", None, None]
    assert konfig.PANEL_STANDARD[("ui", "hausAufbau")] == konfig.HAUS_AUFBAU_STANDARD == "status"
    app = _app()
    app.panels = p
    assert app._panel_export(p["a"])["ui"]["hausAufbau"] == "raeume"
    assert [app.resolve_profile(k)["hausAufbau"] for k in "abcd"] == ["raeume", "spalte", "status", "status"]
    assert _haus(app)["aufbau"] == "status" and "blick" not in _haus(app)
    r = make_mocked_request("GET", "/api/meta", app={"app": app})
    meta = json.loads(asyncio.run(W.api_meta(r)).body)
    assert [a["key"] for a in meta["hausAufbauten"]] == ["status", "raeume", "spalte"]
    assert meta["hausAufbauStandard"] == "status"


def test_raeume_direkt():
    """Aufbau "raeume": je Raumkarte bis zu HAUS_TASTEN Tasten fuer Bausteine,
    die sich ab- und einschalten lassen, mit dem Befehl, der ihren Zustand
    umkehrt (Strukturdoku): Licht an -> Aus-Stimmung, Licht aus -> erste
    Stimmung, Zone -> play/pause, Treppenlicht -> pulse, Sauna -> on mit
    Rueckfrage. Raeume ohne schaltbaren Baustein haben keine Tasten."""
    _app_, v = _aufbau("raeume")
    assert v["aufbau"] == "raeume" and "blick" not in v
    t = {r["name"]: [(x["id"], x["an"], x["cmd"], x.get("frage")) for x in r["tasten"]] for r in v["raeume"]}
    assert t["Abstellraum"] == [("LA", True, {"uuid": "LA", "cmd": "changeTo/778"}, None),
                                ("AB", False, {"uuid": "AB", "cmd": "play"}, None)]
    assert t["Bad"] == [("TS", False, {"uuid": "TS", "cmd": "pulse"}, None)]
    assert t["Sauna"] == [("SA", False, {"uuid": "SA", "cmd": "on"}, "Einschalten?"),
                          ("LC", False, {"uuid": "LC", "cmd": "changeTo/1"}, None)]
    assert t["Küche"] == [] and t["Zentral"] == [("FS", True, {"uuid": "FS", "cmd": "off"}, None)]
    eingang = next(r for r in v["raeume"] if r["name"] == "Eingang")["tasten"]
    assert eingang[0]["secured"] is True and eingang[0]["name"] == "Außenlicht"
    # an: keine Rueckfrage, der Befehl schaltet ab
    _app_, v = _aufbau("raeume", sa1=1)
    sauna = next(r for r in v["raeume"] if r["name"] == "Sauna")["tasten"][0]
    assert sauna["cmd"] == {"uuid": "SA", "cmd": "off"} and "frage" not in sauna
    # hoechstens HAUS_TASTEN
    struktur, st = haus_anlage()
    for i in range(5):
        struktur["controls"][f"S{i}"] = {"name": f"Steckdose {i}", "type": "Switch", "uuidAction": f"S{i}",
                                         "room": "r6", "cat": "c1", "states": {"active": f"s{i}"}}
        st[f"s{i}"] = 0
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    app.states = st
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["haus"], "ui": {"hausAufbau": "raeume"}}})
    kueche = next(r for r in _haus(app, app.resolve_profile("p"))["raeume"] if r["name"] == "Küche")
    assert [x["id"] for x in kueche["tasten"]] == ["S0", "S1", "S2"] == [f"S{i}" for i in range(haus.HAUS_TASTEN)]


def test_spalte_auf_einen_blick():
    """Aufbau "spalte": "Auf einen Blick" nennt, was einen Zustand meldet,
    sich aber nicht abschalten laesst, in der Folge der Raeume; ohne den
    Energie-Baustein (steht darueber), ohne Raumregelung und Sauna (Hauptwert
    der Raumkarte) und ohne Schaltbares (Gerade aktiv, Schnellaktionen)."""
    _app_, v = _aufbau("spalte")
    assert v["aufbau"] == "spalte" and all("tasten" not in r for r in v["raeume"])
    assert [(b["id"], b["zustand"], b["name"]) for b in v["blick"]] == [
        ("MB", "Leer", "Postkasten · Eingang"), ("LU", "40 %", "Lüftung · Zentral"),
        ("CA", "Spielt in 1 Raum", "Audio · Zentral"), ("CL", "In 1 Raum aktiv", "Licht · Zentral")]
    assert v["blick"][0]["nav"] == {"view": "control", "id": "MB"}
    # Post da: ein Hinweis (steht darueber), nicht noch einmal unter "Status"
    _app_, v = _aufbau("spalte", mb1=1)
    assert [h["id"] for h in v["hinweise"]] == ["MB"] and [b["id"] for b in v["blick"]] == ["LU", "CA", "CL"]


def _hinweise(v):
    return [(h["id"], h["stufe"], h["titel"], h["wo"], h["icon"]) for h in v["hinweise"]]


def test_hinweise():
    """Hinweise der Hausseite: was die Kachel rot (Stoerung, tone crit) oder
    orange (Warnung, tone warn) zeigt, offene Fenster an der Raumregelung und
    Post im Postkasten - nach Stufe, darin in der Folge der Raeume. Der Text
    nennt, was los ist: der Zustand der Kachel oder, wo der es nicht sagt,
    ihr Hinweis (Sauna: dieselben Texte wie ihre Detailseite). Ein Tipp
    oeffnet den Baustein. Nichts los: keine Hinweise."""
    assert _haus(_app())["hinweise"] == []
    v = _haus(_app(ic=1, ir4=1, mb1=1, sa3=1))
    assert _hinweise(v) == [
        ("IC", "dringend", "Es klingelt", "Intercom · Eingang", "cam"),
        ("IR", "dringend", "Fenster offen", "Raumregelung · Küche · heizt", "window"),
        ("SA", "warnung", "Wasser nachfüllen", "Saunasteuerung · Sauna", "thermo"),
        ("MB", "an", "Post da", "Postkasten · Eingang", "mail")]
    assert [h["nav"] for h in v["hinweise"]] == [{"view": "control", "id": u} for u in ("IC", "IR", "SA", "MB")]
    # Fenster offen, ohne dass der Raum heizt oder kuehlt: nur eine Warnung
    assert _hinweise(_haus(_app(ir4=1, ir3=0))) == [("IR", "warnung", "Fenster offen", "Raumregelung · Küche", "window")]
    assert _hinweise(_haus(_app(ir4=1, ir3=-1)))[0][1:4] == ("dringend", "Fenster offen", "Raumregelung · Küche · kühlt")
    # Stoerung der Sauna geht dem Wassermangel vor; Text wie auf der Detailseite
    assert _hinweise(_haus(_app(sa3=1, sa4=1))) == [("SA", "dringend", SAUNA_STOERUNG, "Saunasteuerung · Sauna", "thermo")]
    detail = [b.get("text") for b in _app(sa3=1, sa4=1).render({"view": "control", "id": "SA"}, None)["blocks"]]
    assert SAUNA_WASSER in detail and SAUNA_STOERUNG in detail
    # Wassermangel nur mit Verdampfer
    app = _app(sa3=1)
    app.controls["SA"]["details"] = {}
    assert _haus(app)["hinweise"] == []
    # Paket: der Zustand der Kachel ist der Text
    assert _hinweise(_haus(_app(mb1=1, mb2=1)))[0][2] == "Post da · Paket da"


def test_hinweise_in_jedem_aufbau_und_als_unterseite():
    """Jeder Aufbau hat die Hinweise; die Route liste="hinweise" ist ihre
    Unterseite, eine unbekannte Liste keine. Was die Ansicht ausblendet,
    meldet auch keinen Hinweis."""
    for aufbau in konfig.HAUS_AUFBAUTEN:
        _app_, v = _aufbau(aufbau, ic=1)
        assert [h["id"] for h in v["hinweise"]] == ["IC"], aufbau
    app = _app(ic=1)
    assert _haus(app, liste="hinweise")["liste"] == "hinweise"
    assert "liste" not in _haus(app, liste="quatsch")
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["haus"], "hide": ["IC"]}})
    assert _haus(app, app.resolve_profile("p"))["hinweise"] == []


def test_spieler():
    app = _app()
    sp = _haus(app)["spieler"]
    # ohne Wahl die erste Zone, die spielt; Inhalt wie auf der Detailseite
    assert sp["zone"] == "AZ" and sp["name"] == "Essen-Kochen-Wohnen" and sp["spielt"]
    assert sp["titel"] == "Hitradio Ö3"
    assert [t["icon"] for t in sp["tasten"]] == ["prev", "pause", "next"]
    assert sp["laut"] == {"wert": 24, "cmd": {"uuid": "AZ", "tmpl": "volume/{v}"}, "min": 0, "max": 100,
                          "schritt": haus.PROZENT_SCHRITT}
    assert [(z["id"], z["name"], z["spielt"]) for z in sp["zonen"]] == [
        ("AB", "Abstellraum", False), ("AZ", "Essen-Kochen-Wohnen", True)]
    # ⋮ wie auf der Detailseite: Musikauswahl der Zone; der Split-Spieler bekommt
    # denselben more-Block und zeigt daraus sein ⋮
    assert sp["mehr"] == {"view": "sources", "id": "AZ"}
    assert [b["route"] for b in app.player_blocks("AZ") if b["k"] == "more"] == [{"view": "sources", "id": "AZ"}]
    # gewaehlte Zone aus der Route
    sp = _haus(app, zone="AB")["spieler"]
    assert sp["zone"] == "AB" and not sp["spielt"] and sp["laut"]["wert"] == 10
    assert sp["mehr"] == {"view": "sources", "id": "AB"}
    assert [t["icon"] for t in sp["tasten"]] == ["prev", "play", "next"]
    # unbekannte Zone: wie ohne Wahl
    assert _haus(app, zone="XX")["spieler"]["zone"] == "AZ"


def _sender(app, **route):
    return [(s["name"], s["cmd"]["cmd"], s.get("laeuft", False)) for s in _haus(app, **route)["spieler"]["sender"]]


def test_sender_im_spieler():
    """Die Favoriten der Zone stehen im Spieler, dieselben wie in ihrer
    Musikauswahl (Name, Cover, Befehl roomfav/play). Welcher laeuft, sagt
    der Miniserver nicht: markiert ist der, der genau so heisst wie das, was
    die Zone gerade nennt - nur solange sie spielt. Hoechstens HAUS_SENDER,
    der Rest in der Musikauswahl. Eine Zone ohne Favoriten hat keine."""
    app = _app()
    assert _sender(app) == [(n, f"roomfav/play/{i}", i == 1) for i, n in enumerate(HAUS_FAVORITEN, 1)]
    quelle = next(b for b in app._view_sources("AZ")["blocks"] if b["k"] == "favs")["items"]
    assert [(s["name"], s["cmd"], s["cover"]) for s in _haus(app)["spieler"]["sender"]] == \
        [(f["label"], f["cmd"], f["cover"]) for f in quelle]
    # anderer Titel: keiner markiert; pausiert: keiner, auch wenn er passt
    assert not any(x[2] for x in _sender(_app(az2="Nachrichten")))
    assert not any(x[2] for x in _sender(_app(az1=0)))
    # Gross-/Kleinschreibung und Leerzeichen am Rand zaehlen nicht
    assert _sender(_app(az2="  hitradio ö3 "))[0][2]
    # hoechstens HAUS_SENDER
    viele = json.dumps({"getroomfavs_result": [{"items": [{"slot": i, "name": f"Sender {i}"} for i in range(1, 13)]}]})
    assert len(_sender(_app(az4=viele))) == haus.HAUS_SENDER < 12
    # die Zone Abstellraum hat keine Favoriten (ohne Ereignisschleife fordert
    # der Server auch keine an)
    assert _sender(app, zone="AB") == []


def test_sender_vom_audioserver():
    """Kommen die Favoriten vom Audioserver-Kanal (Port 7091), nimmt der
    Spieler dessen Abspiel-Index (play) wie die Musikauswahl und erkennt den
    laufenden auch am Namen, den der Kanal meldet."""
    app = _app(az2="")

    class Kanal:
        favs = {1: [{"name": "Radio 7091", "slot": 1, "play": 4, "cover": "http://bild/1.png"},
                    {"name": "FM4", "slot": 2, "play": 5, "cover": ""}]}
        now = {1: {"name": "Radio 7091", "playing": True}}
        paired, authed = False, False
    app._audio_client_for = lambda c: (Kanal(), 1)
    sender = _haus(app)["spieler"]["sender"]
    assert [(s["name"], s["cmd"]["cmd"], s.get("laeuft", False)) for s in sender] == [
        ("Radio 7091", "roomfav/play/4", True), ("FM4", "roomfav/play/5", False)]
    assert sender[0]["cover"] == "/cover?u=" + quote("http://bild/1.png", safe="") and sender[1]["cover"] == ""


def test_sender_anfordern():
    """Hat die Zone noch keine Favoriten, fordert der Server sie an wie beim
    Oeffnen der Musikauswahl (prime_favs) - aber nicht bei jedem Rendern,
    sondern hoechstens alle HAUS_SENDER_NEU_S je Zone."""
    app = _app(az4="")
    gefragt = []

    async def prime(zone):
        gefragt.append(zone)
    app.prime_favs = prime

    async def lauf():
        for _ in range(3):
            assert _haus(app)["spieler"]["sender"] == []
            await asyncio.sleep(0)
        assert gefragt == ["AZ"]
        app._haus_sender_zeit["AZ"] -= haus.HAUS_SENDER_NEU_S
        _haus(app)
        await asyncio.sleep(0)
        assert gefragt == ["AZ", "AZ"]
    asyncio.run(lauf())


def test_energie_im_kopf():
    e = _haus(_app())["energie"]
    assert e["id"] == "F" and e["label"] == "Energieflussmonitor"
    assert e["wert"] == "PV 0,00 kW · Bezug 0,80 kW" and e["nav"] == {"view": "control", "id": "F"}


def test_gerade_aktiv_je_ansicht():
    """ui.hausAktivOhne: Was die Ansicht nicht zaehlt, steht nicht unter
    "Gerade aktiv" und nicht in "n an" der Raumkarten; zaehlt sie nichts, gibt
    es die Zeile nicht (aktivZeile). Gespeichert wird nur Bekanntes, einmal und
    in der Folge von HAUS_AKTIV_ARTEN; Unbekanntes meldet das Speichern."""
    alle = list(konfig.HAUS_AKTIV_ARTEN)
    roh = {"a": {"title": "A", "ui": {"hausAktivOhne": ["sauna", "audio", "audio", "garage"]}},
           "b": {"title": "B", "ui": {"hausAktivOhne": alle}},
           "c": {"title": "C", "ui": {"hausAktivOhne": ["garage"]}},
           "d": {"title": "D", "ui": {"hausAktivOhne": "audio"}}}
    p = W.App._sanitize_panels(roh)
    assert p["a"]["ui"]["hausAktivOhne"] == ["audio", "sauna"] and p["b"]["ui"]["hausAktivOhne"] == alle
    assert all("hausAktivOhne" not in (p[k].get("ui") or {}) for k in "cd")
    assert "A: ui.hausAktivOhne: garage" in konfig._panels_verworfen(roh, p)
    app = _app()
    app.panels = p
    assert app._panel_export(p["a"])["ui"]["hausAktivOhne"] == ["audio", "sauna"]
    assert app.resolve_profile("a")["hausAktiv"] == ["licht", "schalter"]
    assert app.resolve_profile("b")["hausAktiv"] == [] and app.resolve_profile("c")["hausAktiv"] == alle
    # ohne Musik: die laufende Zone fehlt unter "Gerade aktiv" und in "n an",
    # bleibt aber Symbol ihrer Raumkarte und im Spieler
    v = _haus(app, app.resolve_profile("a"))
    assert [a["id"] for a in v["aktiv"]] == ["LA", "AL", "FS"]
    ekw = _raum(v, "Essen-Kochen-Wohnen")
    assert ekw["an"] == 0 and any(s["on"] for s in ekw["symbole"]) and v["spieler"]["zone"] == "AZ"
    assert _raum(v, "Abstellraum")["an"] == 1
    assert v["aktivZeile"] is True and v["ruhig"] == "Kein Licht an, kein Schalter an"
    # nichts zaehlt: keine Zeile, keine Zahl; die Tasten von "Räume direkt" bleiben
    v = _haus(app, app.resolve_profile("b"))
    assert v["aktiv"] == [] and v["aktivZeile"] is False and "ruhig" not in v
    assert all(r["an"] == 0 for r in v["raeume"])
    v = _haus(app, {**app.resolve_profile("b"), "hausAufbau": "raeume"})
    assert any(t["an"] for r in v["raeume"] for t in r["tasten"])
    # ohne Einstellung zaehlt alles wie bisher
    v = _haus(app)
    assert [a["id"] for a in v["aktiv"]] == ["LA", "AL", "AZ", "FS"]
    assert v["aktivZeile"] is True and v["ruhig"] == "Kein Licht an, keine Musik"
    r = make_mocked_request("GET", "/api/meta", app={"app": app})
    meta = json.loads(asyncio.run(W.api_meta(r)).body)
    assert [a["key"] for a in meta["hausAktivArten"]] == alle
    assert [a["label"] for a in meta["hausAktivArten"]] == ["Licht", "Musik", "Schalter", "Sauna"]


def test_energie_je_ansicht():
    """ui.hausEnergie: ein bestimmter Energie-Baustein, "aus" (keiner) oder
    leer (automatisch: der erste der Seite, sonst der Anlage). Gibt es den
    gewaehlten nicht (mehr), ist er kein Energie-Baustein oder blendet die
    Ansicht ihn aus, gilt wieder automatisch. /api/meta nennt die
    Energie-Bausteine der Anlage und den Wert fuer "keine"."""
    struktur, st = haus_anlage()
    struktur["controls"]["M"] = dict(EM2)
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    app.states = st
    roh = {"m": {"title": "M", "ui": {"hausEnergie": "M"}},
           "aus": {"title": "Aus", "ui": {"hausEnergie": konfig.HAUS_ENERGIE_AUS}},
           "weg": {"title": "Weg", "ui": {"hausEnergie": "GIBTSNICHT"}},
           "falsch": {"title": "Falsch", "ui": {"hausEnergie": "FS"}},
           "versteckt": {"title": "Versteckt", "ui": {"hausEnergie": "M"}, "hide": ["M"]},
           "auto": {"title": "Auto", "ui": {"hausEnergie": "  "}}}
    p = W.App._sanitize_panels(roh)
    assert p["m"]["ui"]["hausEnergie"] == "M" and p["aus"]["ui"]["hausEnergie"] == "aus"
    assert "hausEnergie" not in (p["auto"].get("ui") or {})
    app.panels = p
    assert app._panel_export(p["m"])["ui"]["hausEnergie"] == "M"

    def energie(k):
        return _haus(app, app.resolve_profile(k))["energie"]
    m = energie("m")
    assert m["id"] == "M" and m["label"] == "Energiemanager" and m["nav"] == {"view": "control", "id": "M"}
    assert energie("aus") is None
    assert [energie(k)["id"] for k in ("weg", "falsch", "versteckt", "auto")] == ["F"] * 4
    r = make_mocked_request("GET", "/api/meta", app={"app": app})
    meta = json.loads(asyncio.run(W.api_meta(r)).body)
    assert {e["uuid"] for e in meta["hausEnergien"]} == {"F", "M"} and meta["hausEnergieAus"] == "aus"
    assert all(e["name"] and e["room"] == "Zentral" for e in meta["hausEnergien"]), meta["hausEnergien"]


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
    assert len(v["raeume"]) == 7 and v["schnell"] and v["spieler"]
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
