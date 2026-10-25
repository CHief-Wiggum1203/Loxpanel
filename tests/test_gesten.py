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
import re
from pathlib import Path

import aiohttp
import pytest
from aiohttp.test_utils import make_mocked_request

from lox import gesten_anlage, konfig, Miniserver, neue_app, visu_starten, W

import gesten  # bin/ liegt durch lox auf dem Pfad
import theme_colors

pytestmark = pytest.mark.usefixtures("miniserver_http")


def _app(ms=None, ui=None, theme_ui=None, devices=None, states=None):
    app = neue_app(ms) if ms else W.App({"host": "", "port": 80})
    struktur, st = gesten_anlage()
    app._apply_structure(struktur)
    app.states = {**st, **(states or {})}
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["room:r1", "favoriten"],
                                                  "ui": {"gesten": True, **(ui or {})}}})
    app.theme = {**app.theme, "ui": {**{k: v for k, v in (app.theme.get("ui") or {}).items()
                                        if k not in konfig.THEME_UI_KEYS},
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


def test_aus_erst_nach_den_kreisen():
    """Jeder Befehl ist eine eigene HTTP-Anfrage, die Kreise gehen gleichzeitig
    raus. "Aus" darf erst danach ankommen: ein spaeterer Kreis stellte die
    Lichtsteuerung sonst wieder auf "Manuell". Nachgestellt mit Kreis-Anfragen,
    die laenger brauchen als die an die Lichtsteuerung."""
    async def lauf():
        app = _app()
        angekommen = []

        async def command(uuid, cmd, pin=None):
            if not cmd.startswith("changeTo/"):
                await asyncio.sleep(0.05)
            angekommen.append(f"{uuid}/{cmd}")
            return "200"
        app.command = command
        s = Sitzung(app, RAUM)
        await s(art="licht", phase="start")
        antwort = await s(art="licht", phase="ende", wert=0)
        return antwort, angekommen
    antwort, angekommen = asyncio.run(lauf())
    assert antwort["text"] == "Aus"
    assert sorted(angekommen[:2]) == ["LK-1/0", "LK-2/0"] and angekommen[2:] == ["LK/changeTo/778"], angekommen


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
    assert "gesten" not in W.App._sanitize_theme_ui({"gesten": konfig.GESTEN_STANDARD})
    p = W.App._sanitize_panels({"p": {"title": "P", "ui": {"gesten": False, "gestenRaum": "r1"}},
                                "q": {"title": "Q", "ui": {"gesten": "ja", "gestenRaum": 5}}})
    assert p["p"]["ui"] == {"gesten": False, "gestenRaum": "r1"}
    assert not p["q"].get("ui")                     # kein Wahrheitswert, keine Kennung: verworfen
    dev = W.App._sanitize_devices({"a": {"lichtStart": {"lc": "LK", "mood": "2"}},
                                   "b": {"lichtStart": {"lc": "LK", "mood": True}},
                                   "c": {"lichtStart": {"lc": "", "mood": 1}}}, set())
    assert dev == {"a": {"auto": True, "modes": {}, "lichtStart": {"lc": "LK", "mood": 2}}}


@pytest.mark.parametrize("vorgabe, ansicht, gilt", [
    (None, None, konfig.GESTEN_STANDARD), (True, None, True), (True, False, False), (None, True, True)])
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
    assert m["gestenStandard"] is konfig.GESTEN_STANDARD and "gesten" in m["themeKeys"]


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


# ---- Nacht-Uhr (Stufe 5) ---------------------------------------------------

def test_nacht_uhr_speichern():
    ui = W.App._sanitize_theme_ui({"nightClock": True, "nightClockBright": 2})
    assert ui == {"nightClock": True, "nightClockBright": konfig.NACHT_UHR_HELL_MIN}
    # der Standard wird nicht gespeichert, ein Wahrheitswert ist keine Helligkeit
    assert W.App._sanitize_theme_ui({"nightClock": konfig.NACHT_STANDARD["nightClock"], "nightClockBright": True}) == {}
    p = W.App._sanitize_panels({"p": {"title": "P", "ui": {"nightClock": False, "nightClockBright": 150}}})
    assert p["p"]["ui"] == {"nightClock": False, "nightClockBright": 100}


@pytest.mark.parametrize("vorgabe, ansicht, uhr, hell", [
    ({}, {}, konfig.NACHT_STANDARD["nightClock"], konfig.NACHT_STANDARD["nightClockBright"]),
    ({"nightClock": True, "nightClockBright": 30}, {}, True, 30),
    ({"nightClock": True, "nightClockBright": 30}, {"nightClock": False, "nightClockBright": 60}, False, 60),
], ids=["standard", "vorgabe", "ansicht-vor-vorgabe"])
def test_nacht_uhr_geht_mit_der_nacht_an_die_visu(vorgabe, ansicht, uhr, hell):
    app = _app(ui=ansicht, theme_ui=vorgabe)
    nacht = app.panel_night("test")
    assert (nacht["uhr"], nacht["uhrHell"]) == (uhr, hell)


def _themes():
    """Jedes Kachel-Set (die Sets mit Rechnung in jedem Farbton der Schnellwahl und jeder Art
    der aktiven Kachel) und Grundfarben ueber Farbkreis und Helligkeit."""
    for name, e in theme_colors.KACHEL_SETS.items():
        if "farbton" not in e:
            yield {"tileSet": name}
            continue
        for wahl in e["farbton"]["auswahl"]:
            for aktiv in (e["aktiv"]["auswahl"] if "aktiv" in e else [None]):
                yield {"tileSet": name, e["farbton"]["schluessel"]: wahl["wert"],
                       **({"tileActive": aktiv["key"]} if aktiv else {})}
    for farbton in range(0, 360, 45):
        for hell in (12, 50, 92):
            yield {"baseColor": theme_colors._aus_hls(farbton / 360, hell / 100, 0.4)}


def test_nacht_uhr_traegt_auf_ihrem_grund_in_jedem_theme():
    """Die Nacht-Uhr steht auf Schwarz. Mit der Schrift des Themes waren ihre
    Ziffern in hellen Sets (Kreide, Touch) dunkel auf Schwarz und unsichtbar.
    Jedes Theme bringt deshalb eine Schrift fuer die Nacht-Uhr mit, die dort AAA
    traegt; dunkle Themes behalten ihre Schrift. Ohne Set und Grundfarbe gelten
    die Standardfarben der Visu (helle Schrift), dann kommt keine eigene mit."""
    tc = theme_colors
    hell_geworden = 0
    for ui in _themes():
        v = W.App._theme_vars(dict(konfig.DEFAULT_THEME["states"]), ui)
        assert v["--nacht-grund"] == tc.NACHT_GRUND, ui
        if "--ink" not in v:            # Grundfarbe ohne tragfaehiges Theme: Standardfarben
            assert "--nacht-ink" not in v, ui
            continue
        assert tc.kontrast(v["--nacht-ink"], tc.NACHT_GRUND) >= tc.AAA, (ui, v["--ink"], v["--nacht-ink"])
        if tc.kontrast(v["--ink"], tc.NACHT_GRUND) >= tc.AAA:
            assert v["--nacht-ink"] == v["--ink"], ui
        else:
            hell_geworden += 1
    assert hell_geworden >= 3, "helle Themes muessen dabei sein, sonst prueft der Test nichts"
    standard = W.App._theme_vars(dict(konfig.DEFAULT_THEME["states"]), {})
    assert standard["--nacht-grund"] == tc.NACHT_GRUND and "--nacht-ink" not in standard


def test_hinweis_symbol_speichern_und_mischen():
    """Hinweis-Symbol der Gesten: in Vorgaben nur gespeichert, was vom Standard
    abweicht, in der Ansicht jeder Wahrheitswert; die Ansicht geht vor."""
    assert W.App._sanitize_theme_ui({"gestenHinweis": not konfig.GESTEN_HINWEIS_STANDARD}) == \
        {"gestenHinweis": not konfig.GESTEN_HINWEIS_STANDARD}
    assert W.App._sanitize_theme_ui({"gestenHinweis": konfig.GESTEN_HINWEIS_STANDARD}) == {}
    assert W.App._sanitize_theme_ui({"gestenHinweis": "ja"}) == {}
    assert "gestenHinweis" in konfig.THEME_UI_KEYS
    p = W.App._sanitize_panels({"p": {"title": "P", "ui": {"gestenHinweis": True}}})
    assert p["p"]["ui"]["gestenHinweis"] is True
    app = _app(ui={"gestenHinweis": False})
    assert app._panel_export(app.panels["test"])["ui"]["gestenHinweis"] is False
    assert app.resolve_profile("test")["gestenHinweis"] is False                # Ansicht
    assert _app(theme_ui={"gestenHinweis": False}).resolve_profile("test")["gestenHinweis"] is False   # Vorgabe
    assert _app().resolve_profile("test")["gestenHinweis"] is konfig.GESTEN_HINWEIS_STANDARD                # Standard


@pytest.mark.parametrize("route, ui, theme_ui, erwartet", [
    ({"view": "tab", "tab": "room:r1"}, {}, {},
     {"raum": "Essen-Kochen-Wohnen", "doppel": "Essen-Kochen-Wohnen verlassen: aus, was an ist und sich abschalten lässt",
      "dreifach": "Haus aus: nicht eingerichtet (Vorgaben → Verhalten)"}),
    ({"view": "tab", "tab": "room:r1"}, {}, {"hausAus": "TH", "raumVerlassen": {"r1": "TV"}},
     {"raum": "Essen-Kochen-Wohnen", "doppel": "Essen-Kochen-Wohnen verlassen: Taster „EKW verlassen“",
      "dreifach": "Haus aus: Taster „Haus aus“"}),
    # gesicherter Taster: die Geste loest ihn nicht aus (keine PIN), also auch kein Name
    ({"view": "group", "kind": "room", "id": "r1"}, {}, {"hausAus": "TA"},
     {"raum": "Essen-Kochen-Wohnen", "doppel": "Essen-Kochen-Wohnen verlassen: aus, was an ist und sich abschalten lässt",
      "dreifach": "Haus aus: Taster nicht gefunden"}),
    ({"view": "tab", "tab": "favoriten"}, {}, {}, None),                      # kein Raum
    ({"view": "tab", "tab": "favoriten"}, {"gestenRaum": "r2"}, {}, {
        "raum": "Bad", "doppel": "Bad verlassen: aus, was an ist und sich abschalten lässt",
        "dreifach": "Haus aus: nicht eingerichtet (Vorgaben → Verhalten)"}),
    ({"view": "tab", "tab": "room:r1"}, {"gestenHinweis": False}, {}, None),  # Hinweis aus
    ({"view": "tab", "tab": "room:r1"}, {"gesten": False}, {}, None),         # Gesten aus
    ({"view": "control", "id": "DL"}, {}, {}, None),                          # Detailseite
], ids=["raum", "mit-tastern", "gesicherter-taster", "favoriten", "fester-raum", "hinweis-aus", "gesten-aus",
        "detailseite"])
def test_hilfe_nur_wo_gesten_wirken(route, ui, theme_ui, erwartet):
    """Die Ansicht bringt, was zwei Finger auf dieser Seite tun (gestenHilfe):
    nur dort, wo Gesten wirken und ihr Hinweis an ist, mit den Tastern aus den
    Vorgaben wie geste() sie ausloest."""
    app = _app(ui=ui, theme_ui=theme_ui)
    assert app.render(route, app.resolve_profile("test")).get("gestenHilfe") == erwartet


# ---- Tipp links/rechts, quer wischen (Stufe 6) -----------------------------

LK_AUS = {"LK-am": json.dumps([778])}
SENDER = ["Hitradio Ö3", "FM4", "Ö1"]


def _mit_sendern(app, laeuft=None, spielt=True):
    """Favoriten an der Audio-Zone (sourceList wie nach roomfav/get) und was
    sie gerade spielt (songName)."""
    st = app.controls["AZ"]["states"]
    st.update(sourceList="az-sl", songName="az-sn")
    app.states.update({"az-sl": json.dumps({"getroomfavs_result": [{"items": [
        {"slot": i, "name": n, "coverurl": ""} for i, n in enumerate(SENDER, 1)]}]}),
        "az-sn": laeuft or "", "az-ps": 2 if spielt else 0})


def test_tipp_links_beschattet():
    async def schritte(app):
        return await Sitzung(app, RAUM)(art="beschatten")
    antwort, io = _mit_nachbau(schritte)
    assert antwort["text"] == "Beschatten" and io == ["sps/io/J1/shade", "sps/io/J2/shade"]


def test_tipp_rechts_wiedergabe():
    async def schritte(app):
        s = Sitzung(app, RAUM)
        pause = await s(art="wiedergabe")
        app.states["az-ps"] = 1
        return pause, await s(art="wiedergabe"), await Sitzung(app, BAD)(art="wiedergabe")
    (pause, spielt, bad), io = _mit_nachbau(schritte)
    assert (pause["text"], spielt["text"], bad["fehler"]) == ("Pause", "Spielt", "Keine Musik in Bad")
    assert io == ["sps/io/AZ/pause", "sps/io/AZ/play"]


@pytest.mark.parametrize("states, richtung, text, befehl", [
    ({}, "vor", "Putzen", "sps/io/LK/changeTo/2"),
    ({"LK-am": json.dumps([2])}, "vor", "Kochen", "sps/io/LK/changeTo/1"),       # am Ende: wieder vorn
    ({}, "zurueck", "Putzen", "sps/io/LK/changeTo/2"),                           # am Anfang: hinten
    (LK_AUS, "vor", "Kochen", "sps/io/LK/changeTo/1"),                              # aus: erste
    (LK_AUS, "zurueck", "Putzen", "sps/io/LK/changeTo/2"),                          # aus: letzte
], ids=["vor", "vor-wieder-vorn", "zurueck", "aus-vor", "aus-zurueck"])
def test_quer_mitte_stimmung(states, richtung, text, befehl):
    async def schritte(app):
        return await Sitzung(app, RAUM)(art="stimmungwechsel", richtung=richtung)
    antwort, io = _mit_nachbau(schritte, states=states)
    assert antwort["text"] == text and io == [befehl]


def test_quer_mitte_ohne_lichtsteuerung():
    async def schritte(app):
        return await Sitzung(app, BAD)(art="stimmungwechsel", richtung="vor")
    antwort, io = _mit_nachbau(schritte)
    assert antwort["fehler"] == "Keine Lichtsteuerung in Bad" and io == []


@pytest.mark.parametrize("laeuft, spielt, richtung, text, befehl", [
    ("FM4", True, "vor", "Ö1", "sps/io/AZ/roomfav/play/3"),
    ("FM4", True, "zurueck", "Hitradio Ö3", "sps/io/AZ/roomfav/play/1"),
    ("Ö1", True, "vor", "Hitradio Ö3", "sps/io/AZ/roomfav/play/1"),                # am Ende: wieder vorn
    ("Ein Lied", True, "vor", "Hitradio Ö3", "sps/io/AZ/roomfav/play/1"),          # kein Favorit laeuft
    ("FM4", False, "zurueck", "Ö1", "sps/io/AZ/roomfav/play/3"),                   # pausiert: von hinten
], ids=["vor", "zurueck", "wieder-vorn", "kein-favorit", "pausiert"])
def test_quer_rechts_sender(laeuft, spielt, richtung, text, befehl):
    async def schritte(app):
        _mit_sendern(app, laeuft, spielt)
        return await Sitzung(app, RAUM)(art="sender", richtung=richtung)
    antwort, io = _mit_nachbau(schritte)
    assert antwort["text"] == text and io == [befehl]


def test_quer_rechts_ohne_sender():
    async def schritte(app):
        return await Sitzung(app, RAUM)(art="sender", richtung="vor")
    antwort, io = _mit_nachbau(schritte)
    assert antwort["fehler"] == "Keine Sender in Essen-Kochen-Wohnen" and io == []


def test_quer_links_lamellen():
    """Nur Raffstores (shadePosition, animation 0); Zwischenwerte schicken
    nichts, erst das Loslassen stellt die Lamellen."""
    async def schritte(app):
        app.controls["J2"]["states"]["shadePosition"] = "j2-sp"
        app.controls["J2"]["details"] = {"animation": 0}
        app.states["j2-sp"] = 0.5
        s = Sitzung(app, RAUM)
        start = await s(art="lamellen", phase="start")
        zwischen = await s(art="lamellen", phase="wert", wert=70)
        ende = await s(art="lamellen", phase="ende", wert=80)
        return start, zwischen, ende
    (start, zwischen, ende), io = _mit_nachbau(schritte)
    assert start["wert"] == 50 and zwischen is None and ende["text"] == "Lamellen 80 %"
    assert io == ["sps/io/J2/manualLamelle/80"]


def test_quer_links_ohne_lamellen():
    async def schritte(app):
        return await Sitzung(app, RAUM)(art="lamellen", phase="start")
    antwort, io = _mit_nachbau(schritte)
    assert antwort["fehler"] == "Keine Lamellen in Essen-Kochen-Wohnen" and io == []


# ---- Hausuebersicht: der Raum der Karte unter den Fingern -------------------

HAUS = {"view": "tab", "tab": "haus"}


def test_raum_der_karte_auf_der_hausuebersicht():
    app = _app(ui={"gestenRaum": "r3"})
    prof = app.resolve_profile("test")
    assert app.geste_raum(HAUS, prof, "r2") == "r2"
    assert app.geste_raum(HAUS, prof, None) == "r3"                       # neben den Karten: fester Raum
    assert app.geste_raum(HAUS, prof, "gibts-nicht") == "r3"
    assert app.geste_raum(RAUM, prof, "r2") == "r1"                       # nur auf der Hausuebersicht
    assert app.geste_raum(HAUS, {**prof, "rooms": ["r1"]}, "r2") == "r3"  # Raum, den die Ansicht nicht zeigt


def test_geste_auf_der_raumkarte():
    async def schritte(app):
        s = Sitzung(app, HAUS)
        return await s(art="stimmung", raum="r1"), await s(art="stimmung")
    (karte, daneben), io = _mit_nachbau(schritte)
    assert karte["raum"] == "Essen-Kochen-Wohnen" and karte["text"] == "Putzen"
    assert daneben["fehler"] == "Kein Raum auf dieser Seite"
    assert io == ["sps/io/LK/changeTo/2"]


# ---- Vollbild: Farben und Fahrt der Jalousie --------------------------------

GESTE_PAARE = (("--geste-licht-ink", "--glow"), ("--geste-musik-ink", "--accent"),
               ("--ink", "--geste-vorhang"), ("--ink", "--geste-lamelle"),
               ("--geste-nacht-ink", "--nacht-grund"), ("--geste-nacht-ink", "--geste-nacht-licht"),
               ("--geste-nacht-ink", "--geste-nacht-musik"), ("--geste-nacht-ink", "--geste-nacht-vorhang"),
               ("--geste-nacht-ink", "--geste-nacht-lamelle"))


def test_vollbild_traegt_in_jedem_theme():
    """Die Einblendung ueber die ganze Flaeche: die Schrift auf der Fuellung
    (Licht, Musik), auf Vorhang und Lamellen der Jalousie und im Dunkeln auf
    Schwarz und den gedaempften Fuellungen traegt AA. Nachts bleibt die
    Fuellung sichtbar, auch in hellen Sets, deren --glow eine dunkle
    Schriftfarbe ist. Ohne Set und Grundfarbe aus den Standardfarben der Visu."""
    tc = theme_colors
    for ui in [{}, *_themes()]:
        v = W.App._theme_vars(dict(konfig.DEFAULT_THEME["states"]), ui)
        f = {**tc.VISU_STANDARD, **v}
        for schrift, flaeche in GESTE_PAARE:
            assert tc.kontrast(f[schrift], f[flaeche]) >= tc.AA, (ui, schrift, flaeche, f[schrift], f[flaeche])
        for fuellung in ("--geste-nacht-licht", "--geste-nacht-musik"):
            assert tc.kontrast(f[fuellung], tc.NACHT_GRUND) >= tc.GESTE_NACHT_SICHTBAR, (ui, fuellung, f[fuellung])


def test_standardfarben_wie_in_der_visu():
    """VISU_STANDARD ist, was grund.css ohne Set und Grundfarbe zeigt."""
    css = (Path(W.__file__).parent.parent / "webfrontend/html/panel/grund.css").read_text(encoding="utf-8")
    for name, wert in theme_colors.VISU_STANDARD.items():
        assert re.search(re.escape(name) + r"\s*:\s*" + re.escape(wert) + r"\s*;", css), (name, wert)


def test_gewaehlte_zustandsfarbe_geht_in_die_einblendung():
    states = {**konfig.DEFAULT_THEME["states"], "active": "#3a6df0", "good": "#c0392b"}
    v = W.App._theme_vars(states, {})
    assert v["--geste-licht-ink"] == theme_colors.schrift_auf("#3a6df0")
    assert v["--geste-musik-ink"] == theme_colors.schrift_auf("#c0392b")


class MitSenden(Sitzung):
    """Sitzung, die mitschreibt, was der Server ihr von sich aus schickt."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.gesendet = []

    async def send_json(self, msg):
        self.gesendet.append(msg)


def test_jalousie_faehrt_live():
    """Links runter: die Antwort nennt die mittlere Stellung (J1 0 %, J2 30 %);
    bis der Miniserver eine Fahrt meldet, schickt der Takt nichts. Dann die
    Stellung, solange sie faehrt, und am Ende "Geschlossen"."""
    async def schritte(app):
        s = MitSenden(app, RAUM)
        antwort = await s(art="beschattung", richtung="ab")
        await app.geste_fahrten()
        vor_der_fahrt = list(s.gesendet)
        app.states.update({"j1-d": 1, "j2-d": 1, "j1-p": 0.4, "j2-p": 0.6})
        await app.geste_fahrten()
        await app.geste_fahrten()                  # nichts geaendert: nichts doppelt
        app.states.update({"j1-d": 0, "j2-d": 0, "j1-p": 1.0, "j2-p": 1.0})
        await app.geste_fahrten()
        return antwort, vor_der_fahrt, s.gesendet, s in app.conn_geste
    (antwort, vorher, gesendet, beobachtet), io = _mit_nachbau(schritte)
    assert (antwort["text"], antwort["wert"]) == ("Beschattung ab", 15) and vorher == []
    assert [(m["phase"], m["wert"], m["text"]) for m in gesendet] == [("wert", 50, "Fährt ab"),
                                                                      ("ende", 100, "Geschlossen")]
    assert all(m["art"] == "beschattung" and m["raum"] == "Essen-Kochen-Wohnen" for m in gesendet)
    assert not beobachtet and io == ["sps/io/J1/FullDown", "sps/io/J2/FullDown"]


def test_jalousie_ohne_fahrt_endet_nach_dem_anlauf():
    """Faehrt keine los (schon in der Endlage), endet die Meldung nach
    GESTEN_FAHRT_ANLAUF_S mit der Stellung."""
    async def schritte(app):
        s = MitSenden(app, RAUM)
        await s(art="beschatten")
        app.conn_geste[s]["start"] -= gesten.GESTEN_FAHRT_ANLAUF_S + 1
        await app.geste_fahrten()
        return s.gesendet, s in app.conn_geste
    (gesendet, beobachtet), io = _mit_nachbau(schritte)
    assert [(m["art"], m["phase"], m["wert"], m["text"]) for m in gesendet] == [
        ("beschatten", "ende", 15, "15 % geschlossen")]
    assert not beobachtet and io == ["sps/io/J1/shade", "sps/io/J2/shade"]


def test_neue_geste_loest_die_fahrt_ab():
    async def schritte(app):
        s = MitSenden(app, RAUM)
        await s(art="beschattung", richtung="auf")
        await s(art="licht", phase="start")
        app.states.update({"j1-u": 1, "j2-p": 0.1})
        await app.geste_fahrten()
        return s.gesendet
    gesendet, _io = _mit_nachbau(schritte)
    assert gesendet == []
