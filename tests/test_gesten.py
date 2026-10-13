"""Gesten wie auf den Loxone-Tastern (docs/TODO.md §9), Server-Seite.

- Raum der Geste: der der Seite, sonst der feste Raum der Ansicht.
- Lichtgruppen aus der Struktur: jede Lichtsteuerung mit ihren dimmbaren
  Lichtkreisen (ohne Master-Helligkeit und schaltbare Kreise), jeder einzelne
  Dimmer; Ausblendungen und Visu-PIN der Ansicht gelten.
- Die Befehle je Geste, wie sie am Miniserver-Nachbau ankommen: anteilig
  dimmen, ganz unten aus, alles aus -> Stimmung des Geraets, Stimmung
  weiterschalten, Beschattung, Lautstaerke, Raum verlassen, Haus aus.
- Einstellungen: Vorgaben, Ansicht, Geraet, Auswahl im Konfigurator.
- Der Weg ueber den WebSocket ({t:"geste"}) und das theme.

Anlage: lox.gesten_anlage()."""
import asyncio
import json

import aiohttp
import pytest
from aiohttp.test_utils import make_mocked_request

from lox import Miniserver, W, gesten_anlage, neue_app, visu_starten

pytestmark = pytest.mark.usefixtures("miniserver_http")


def _app(ms=None, ui=None, theme_ui=None, devices=None, states=None):
    app = neue_app(ms) if ms else W.App({"host": "", "port": 80})
    struktur, st = gesten_anlage()
    app._apply_structure(struktur)
    app.states = {**st, **(states or {})}
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["room:r1", "favoriten"],
                                                  "ui": {"gesten": True, **(ui or {})}}})
    app.theme = {**app.theme, "ui": {**{k: v for k, v in (app.theme.get("ui") or {}).items()
                                        if k not in W.THEME_UI_KEYS},
                                     **W.App._sanitize_theme_ui(theme_ui or {})}}
    app.devices = W.App._sanitize_devices(devices or {}, set(app.panels))
    return app


class Sitzung:
    """Eine Verbindung der Visu, ohne WebSocket: dieselben Tabellen, die
    ws_handler fuellt (Profil, Seite, Geraet)."""

    def __init__(self, app, route, dev="", profil="test"):
        self.app = app
        app.conn_prof[self] = app.resolve_profile(profil)
        app.conn_route[self] = route
        app.conn_dev[self] = dev

    async def __call__(self, **data):
        return await self.app.geste(self, {"t": "geste", **data})


RAUM = {"view": "tab", "tab": "room:r1"}
BAD = {"view": "group", "kind": "room", "id": "r2"}


def _mit_nachbau(schritte, **kw):
    """schritte(app) gegen den Miniserver-Nachbau -> (Ergebnis, ms.io)."""
    async def lauf():
        ms = Miniserver()
        await ms.start()
        app = _app(ms=ms, **kw)
        try:
            return await schritte(app), ms.io
        finally:
            await app.icon_session.close()
            await ms.stop()
    return asyncio.run(lauf())


# ---- Raum und Lichtgruppen -------------------------------------------------

def test_raum_der_geste():
    app = _app(ui={"gestenRaum": "r3"})
    prof = app.resolve_profile("test")
    assert app.geste_raum(RAUM, prof) == "r1"
    assert app.geste_raum(BAD, prof) == "r2"              # die Seite schlaegt den festen Raum
    assert app.geste_raum({"view": "tab", "tab": "favoriten"}, prof) == "r3"
    assert app.geste_raum({"view": "tab", "tab": "haus"}, prof) == "r3"
    ohne = _app()
    assert ohne.geste_raum({"view": "tab", "tab": "favoriten"}, ohne.resolve_profile("test")) is None
    # einen Raum, den der Miniserver nicht kennt, gibt es nicht
    fremd = _app(ui={"gestenRaum": "weg"})
    assert fremd.geste_raum({"view": "tab", "tab": "favoriten"}, fremd.resolve_profile("test")) is None
    # eine Raumseite meint ihren Raum: kennt der Miniserver ihn nicht, gilt
    # auch nicht der feste Raum der Ansicht
    assert app.geste_raum({"view": "tab", "tab": "room:weg"}, prof) is None


def test_lichtgruppen_aus_der_struktur():
    app = _app()
    gruppen = {g["uuid"]: g for g in app.licht_gruppen("r1", app.resolve_profile("test"))}
    # die Vitrine hat ein Visu-Passwort: keine PIN mitten in einer Geste
    assert list(gruppen) == ["LK", "LW", "DL"]
    # dimmbare Lichtkreise, ohne Master-Helligkeit und ohne den schaltbaren Unterbau
    assert [k["ziel"] for k in gruppen["LK"]["kreise"]] == ["LK-1", "LK-2"]
    assert [k["wert"] for k in gruppen["LK"]["kreise"]] == [80, 60]
    assert gruppen["LK"]["an"] and not gruppen["LW"]["an"] and not gruppen["DL"]["an"]
    assert gruppen["DL"]["kreise"] == [{"ziel": "DL", "wert": 0, "min": 0.0, "max": 100.0}]
    # Ausblendungen der Ansicht gelten wie auf der Raumseite
    app.panels["test"]["hide"] = ["LW"]
    assert [g["uuid"] for g in app.licht_gruppen("r1", app.resolve_profile("test"))] == ["LK", "DL"]


# ---- Licht: Mitte hoch/runter ----------------------------------------------

def test_dimmt_anteilig_was_leuchtet():
    async def schritte(app):
        s = Sitzung(app, RAUM)
        return [await s(art="licht", phase="start"), await s(art="licht", phase="wert", wert=40),
                await s(art="licht", phase="wert", wert=40), await s(art="licht", phase="ende", wert=50)]
    (start, mitte, gleich, ende), io = _mit_nachbau(schritte)
    assert start == {"t": "geste", "art": "licht", "raum": "Essen-Kochen-Wohnen", "phase": "start", "wert": 80}
    assert mitte is None and gleich is None and ende is None
    # Faktor 40/80 und 50/80: das Verhaeltnis 4:3 bleibt; Licht Wohnen und die
    # Leselampe sind aus und bleiben es; ein gleicher Wert geht nicht noch einmal
    assert io == ["sps/io/LK-1/40", "sps/io/LK-2/30", "sps/io/LK-1/50", "sps/io/LK-2/38"]


def test_ganz_unten_geht_die_lichtsteuerung_aus():
    async def schritte(app):
        s = Sitzung(app, RAUM)
        await s(art="licht", phase="start")
        return await s(art="licht", phase="ende", wert=0)
    antwort, io = _mit_nachbau(schritte)
    assert antwort["text"] == "Aus"
    assert io == ["sps/io/LK-1/0", "sps/io/LK-2/0", "sps/io/LK/changeTo/778"]


AUS = {"LK-am": json.dumps([778]), "LK-1-p": 0, "LK-2-p": 0}


@pytest.mark.parametrize("devices, stimmung, befehl", [
    ({}, "Kochen", "sps/io/LK/changeTo/1"),
    ({"kueche": {"lichtStart": {"lc": "LW", "mood": 4}}}, "Fernsehen", "sps/io/LW/changeTo/4"),
], ids=["erste-stimmung", "stimmung-des-geraets"])
def test_alles_aus_schaltet_die_stimmung_ein(devices, stimmung, befehl):
    """Leuchtet nichts, schaltet die Bewegung nach oben genau einmal die
    Stimmung ein - die des Geraets, sonst die erste der ersten Lichtsteuerung."""
    async def schritte(app):
        s = Sitzung(app, RAUM, dev="kueche")
        return [await s(art="licht", phase="start"), await s(art="licht", phase="wert", wert=0),
                await s(art="licht", phase="wert", wert=20), await s(art="licht", phase="ende", wert=60)]
    (start, null, an, ende), io = _mit_nachbau(schritte, devices=devices, states=AUS)
    assert (start["wert"], start["text"]) == (0, stimmung)
    assert null is None and an["text"] == stimmung and ende is None
    assert io == [befehl]


def test_nur_einzelne_dimmer():
    async def schritte(app):
        s = Sitzung(app, BAD)
        return [await s(art="licht", phase="start"), await s(art="licht", phase="ende", wert=35)]
    (start, ende), io = _mit_nachbau(schritte)
    assert start["wert"] == 0 and "text" not in start and ende is None
    assert io == ["sps/io/DB/35"]


def test_ohne_licht_ein_hinweis():
    async def schritte(app):
        return await Sitzung(app, {"view": "group", "kind": "room", "id": "r3"})(art="licht", phase="start")
    antwort, io = _mit_nachbau(schritte)
    assert antwort["fehler"] == "Kein dimmbares Licht in Zentral" and io == []


# ---- Licht: Tipp in der Mitte ----------------------------------------------

@pytest.mark.parametrize("states, devices, text, befehl", [
    ({}, {}, "Putzen", "sps/io/LK/changeTo/2"),                                  # an: naechste
    ({"LK-am": json.dumps([2])}, {}, "Kochen", "sps/io/LK/changeTo/1"),          # am Ende: wieder vorn
    (AUS, {}, "Kochen", "sps/io/LK/changeTo/1"),                                  # aus: erste
    (AUS, {"kueche": {"lichtStart": {"lc": "LW", "mood": 4}}}, "Fernsehen", "sps/io/LW/changeTo/4"),
], ids=["naechste", "wieder-vorn", "einschalten", "stimmung-des-geraets"])
def test_tipp_schaltet_die_stimmung(states, devices, text, befehl):
    async def schritte(app):
        return await Sitzung(app, RAUM, dev="kueche")(art="stimmung")
    antwort, io = _mit_nachbau(schritte, states=states, devices=devices)
    assert antwort["text"] == text and io == [befehl]


def test_tipp_ohne_lichtsteuerung_schaltet_die_dimmer_ein():
    async def schritte(app):
        s = Sitzung(app, BAD)
        erst = await s(art="stimmung")
        app.states["db-p"] = 40
        return erst, await s(art="stimmung")
    (erst, dann), io = _mit_nachbau(schritte)
    assert erst["text"] == "Licht an" and dann["text"] == "Licht ist an"
    assert io == ["sps/io/DB/on"]


# ---- Beschattung und Musik -------------------------------------------------

def test_beschattung():
    async def schritte(app):
        s = Sitzung(app, RAUM)
        auf = await s(art="beschattung", richtung="auf")
        ab = await s(art="beschattung", richtung="ab")
        app.states["j2-d"] = 1                     # Jalousie Kueche faehrt: dieselbe Geste haelt sie an
        stopp = await s(art="beschattung", richtung="ab")
        return auf, ab, stopp
    (auf, ab, stopp), io = _mit_nachbau(schritte)
    assert (auf["text"], ab["text"], stopp["text"]) == ("Beschattung auf", "Beschattung ab", "Beschattung gestoppt")
    assert io == ["sps/io/J1/FullUp", "sps/io/J2/FullUp", "sps/io/J1/FullDown", "sps/io/J2/FullDown",
                  "sps/io/J2/Stop"]


def test_musik():
    async def schritte(app):
        s = Sitzung(app, RAUM)
        return [await s(art="musik", phase="start"), await s(art="musik", phase="ende", wert=45)]
    (start, ende), io = _mit_nachbau(schritte)
    assert start["wert"] == 30 and ende is None
    assert io == ["sps/io/AZ/volume/45"]


def test_ohne_beschattung_und_musik_ein_hinweis():
    async def schritte(app):
        s = Sitzung(app, BAD)
        return await s(art="beschattung", richtung="auf"), await s(art="musik", phase="start")
    (jal, musik), io = _mit_nachbau(schritte)
    assert jal["fehler"] == "Keine Beschattung in Bad" and musik["fehler"] == "Keine Musik in Bad" and io == []


# ---- Raum verlassen und Haus aus -------------------------------------------

def test_raum_verlassen_mit_taster_aus_loxone():
    async def schritte(app):
        return await Sitzung(app, RAUM)(art="verlassen")
    antwort, io = _mit_nachbau(schritte, theme_ui={"raumVerlassen": {"r1": "TV"}})
    assert antwort["text"] == "Essen-Kochen-Wohnen verlassen" and io == ["sps/io/TV/pulse"]


def test_raum_verlassen_ohne_taster():
    """Aus, was im Raum an ist und sich abschalten laesst; die Vitrine hat ein
    Visu-Passwort und bleibt, was aus ist, bekommt keinen Befehl."""
    async def schritte(app):
        return await Sitzung(app, RAUM)(art="verlassen")
    antwort, io = _mit_nachbau(schritte)
    assert antwort["text"] == "Essen-Kochen-Wohnen: 2 aus"
    assert sorted(io) == ["sps/io/AZ/pause", "sps/io/LK/changeTo/778"]


@pytest.mark.parametrize("theme_ui, antwort, io", [
    ({}, {"fehler": "„Haus aus“ ist nicht eingerichtet (Vorgaben → Verhalten)"}, []),
    ({"hausAus": "TH"}, {"text": "Haus aus"}, ["sps/io/TH/pulse"]),
    ({"hausAus": "TA"}, {"fehler": "Taster für „Haus aus“ nicht gefunden"}, []),   # Visu-Passwort
    ({"hausAus": "DB"}, {"fehler": "Taster für „Haus aus“ nicht gefunden"}, []),   # kein Taster
], ids=["nicht-eingerichtet", "taster", "gesichert", "kein-taster"])
def test_haus_aus(theme_ui, antwort, io):
    """Haus aus gilt ueberall, auch ohne Raum auf der Seite."""
    async def schritte(app):
        return await Sitzung(app, {"view": "tab", "tab": "favoriten"})(art="hausaus")
    ergebnis, gesendet = _mit_nachbau(schritte, theme_ui=theme_ui)
    assert ergebnis == {"t": "geste", "art": "hausaus", **antwort} and gesendet == io


def test_ohne_raum_und_ausgeschaltet():
    async def schritte(app):
        fav = await Sitzung(app, {"view": "tab", "tab": "favoriten"})(art="stimmung")
        app.panels["test"]["ui"]["gesten"] = False
        aus = await Sitzung(app, RAUM)(art="verlassen")
        return fav, aus
    (fav, aus), io = _mit_nachbau(schritte)
    assert fav["fehler"] == "Kein Raum auf dieser Seite" and aus is None and io == []


# ---- Einstellungen ---------------------------------------------------------

def test_einstellungen_speichern():
    ui = W.App._sanitize_theme_ui({"gesten": True, "hausAus": " TH ", "raumVerlassen": {"r1": "TV", "r2": "", 3: "x"}})
    assert ui == {"gesten": True, "hausAus": "TH", "raumVerlassen": {"r1": "TV"}}
    # der Standard wird nicht gespeichert
    assert "gesten" not in W.App._sanitize_theme_ui({"gesten": W.GESTEN_STANDARD})
    p = W.App._sanitize_panels({"p": {"title": "P", "ui": {"gesten": False, "gestenRaum": "r1"}},
                                "q": {"title": "Q", "ui": {"gesten": "ja", "gestenRaum": 5}}})
    assert p["p"]["ui"] == {"gesten": False, "gestenRaum": "r1"}
    assert not p["q"].get("ui")                     # kein Wahrheitswert, keine Kennung: verworfen
    dev = W.App._sanitize_devices({"a": {"lichtStart": {"lc": "LK", "mood": "2"}},
                                   "b": {"lichtStart": {"lc": "LK", "mood": True}},
                                   "c": {"lichtStart": {"lc": "", "mood": 1}}}, set())
    assert dev == {"a": {"auto": True, "modes": {}, "lichtStart": {"lc": "LK", "mood": 2}}}


@pytest.mark.parametrize("vorgabe, ansicht, gilt", [
    (None, None, W.GESTEN_STANDARD), (True, None, True), (True, False, False), (None, True, True)])
def test_ansicht_vor_vorgabe(vorgabe, ansicht, gilt):
    app = _app(theme_ui={} if vorgabe is None else {"gesten": vorgabe})
    app.panels["test"]["ui"].pop("gesten")
    if ansicht is not None:
        app.panels["test"]["ui"]["gesten"] = ansicht
    assert app.resolve_profile("test")["gesten"] is gilt


def test_auswahl_im_konfigurator():
    app = _app()
    m = json.loads(asyncio.run(W.api_meta(make_mocked_request("GET", "/api/meta", app={"app": app}))).body)
    # nur Taster (Pushbutton) ohne Visu-Passwort, nach Raum
    assert [(t["room"], t["name"]) for t in m["gestenTaster"]] == [("Essen-Kochen-Wohnen", "EKW verlassen"),
                                                                    ("Zentral", "Haus aus")]
    licht = {e["name"]: [s["name"] for s in e["moods"]] for e in m["lichtStimmungen"]}
    assert licht == {"Licht Abstellraum": ["Hell"], "Licht Kochen": ["Kochen", "Putzen"],
                     "Licht Wohnen": ["Essen", "Fernsehen"]}
    assert m["gestenStandard"] is W.GESTEN_STANDARD and "gesten" in m["themeKeys"]


# ---- Weg ueber den WebSocket -----------------------------------------------

async def _bis(ws, art, sekunden=3.0):
    while True:
        m = await asyncio.wait_for(ws.receive_json(), sekunden)
        if m.get("t") == art:
            return m


def test_ueber_den_websocket():
    """Das theme sagt der Visu, ob Gesten an sind; auf der Raumseite (erster
    Tab) beantwortet der Server {t:"geste"} mit dem Startwert."""
    async def schritte(app):
        runner, port, bc = await visu_starten(app)
        try:
            async with aiohttp.ClientSession() as s, s.ws_connect(f"http://127.0.0.1:{port}/ws?panel=test") as ws:
                theme = await _bis(ws, "theme")
                await ws.send_json({"t": "geste", "art": "licht", "phase": "start"})
                start = await _bis(ws, "geste")
                await ws.send_json({"t": "geste", "art": "licht", "phase": "ende", "wert": 40})
                await ws.send_json({"t": "geste", "art": "beschattung", "richtung": "ab"})
                jal = await _bis(ws, "geste")
                return theme["gesten"], start, jal
        finally:
            bc.cancel()
            await runner.cleanup()
    (an, start, jal), io = _mit_nachbau(schritte)
    assert an is True and start["wert"] == 80 and jal["text"] == "Beschattung ab"
    assert io == ["sps/io/LK-1/40", "sps/io/LK-2/30", "sps/io/J1/FullDown", "sps/io/J2/FullDown"]
