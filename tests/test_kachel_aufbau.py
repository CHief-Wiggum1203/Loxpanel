"""Neuer Kachel-Aufbau, Server-Seite: die Panel-Option ui.tileLayout (nur
"classic" wird gespeichert, der neue Aufbau ist der Standard), die Messwerte,
die eine Kachel gross an Stelle des Symbols zeigt (big/bigSub), und die
Kennung fuer Zweitzeilen, die nur beschreiben statt einen Zustand zu nennen
(subInfo), und die Schriftgroessen ohne Einstellung je Aufbau. Dazu: jede
Panel-Option, die das Speichern behaelt, kommt auch beim Konfigurator an -
catFilter fehlte dort und ging beim naechsten Speichern verloren."""
import shutil

import pytest

from lox import ROOT, W, anlage

STRUKTUR_PANEL = anlage({"S": {"name": "Licht", "type": "Switch", "uuidAction": "S", "room": "r1", "cat": "c1",
                               "states": {"active": "s"}}})


@pytest.mark.parametrize("wert, gespeichert", [
    ("classic", "classic"), ("neu", None), ("", None), (True, None), (None, None), ("Classic", None),
])
def test_nur_der_klassische_aufbau_wird_gespeichert(wert, gespeichert):
    ui = {"tileLayout": wert} if wert is not None else {}
    e = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["favoriten"], "ui": ui}})["p"]
    assert (e.get("ui") or {}).get("tileLayout") == gespeichert


@pytest.mark.parametrize("ui, erwartet", [({}, ""), ({"tileLayout": "classic"}, "classic")])
def test_profil_meldet_den_aufbau(ui, erwartet):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR_PANEL)
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["favoriten"], "ui": ui}})
    assert app.resolve_profile("p")["tileLayout"] == erwartet


GROESSEN_VARS = {"iconSize": "--ico-size", "nameSize": "--name-size", "subSize": "--sub-size",
                 "roomSize": "--room-size", "bigSize": "--big-size"}


@pytest.mark.parametrize("aufbau", ["neu", "classic"])
def test_groessen_ohne_einstellung_je_aufbau(cfg_ordner, aufbau):
    """Frische Installation (nur die Vorlage): weder load_theme() noch die
    Vorlage legen Groessen fest, es gilt der Standard des Kachel-Aufbaus. Eine
    globale Einstellung schlaegt ihn, die des Panels die globale."""
    shutil.copy(ROOT / "config" / "theme.example.json", cfg_ordner / "theme.example.json")
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR_PANEL)
    ui = {"tileLayout": "classic"} if aufbau == "classic" else {}
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["favoriten"], "ui": ui},
                                         "q": {"title": "Q", "tabs": ["favoriten"], "ui": {**ui, "nameSize": 22}}})
    std = W.GROESSEN_STANDARD[aufbau]

    def groessen(pid):
        v = app.resolve_profile(pid)["vars"]
        return {k: v[var] for k, var in GROESSEN_VARS.items()}
    assert groessen("p") == {k: f"{n}px" for k, n in std.items()}
    app._write_theme({"nameSize": 19})             # Global -> Darstellung, erstes Speichern
    assert groessen("p") == {k: f"{n}px" for k, n in {**std, "nameSize": 19}.items()}
    assert groessen("q")["nameSize"] == "22px"


def test_jede_gespeicherte_option_kommt_beim_konfigurator_an():
    """Was _sanitize_panels behaelt, muss _panel_export an den Konfigurator
    geben: der schickt beim Speichern das Profil zurueck, wie er es bekam."""
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR_PANEL)
    ui = {"iconSize": 30, "nameSize": 20, "subSize": 14, "font": "Inter", "nudgeX": 4, "dpmsOff": 60,
          "reloadHours": 24, "nightDim": 50, "nightWake": 20, "cols": 3, "rows": 3, "fill": True,
          "split": False, "catFilter": True, "tileLayout": "classic", "player": "Z1",
          "panes": {"favoriten": "weather"}, "svPane": "calendar", "scale": "auto",
          "textColor": "#ffffff", "bold": True, "lang": "en"}
    gespeichert = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["favoriten"], "ui": ui}})["p"]
    assert {"catFilter", "tileLayout", "panes", "svPane", "scale"} <= set(gespeichert["ui"]), gespeichert["ui"]
    exportiert = app._panel_export(gespeichert)["ui"]
    fehlt = sorted(set(gespeichert["ui"]) - set(exportiert))
    assert fehlt == [], f"beim Konfigurator fehlen {fehlt}"
    assert exportiert["catFilter"] is True and exportiert["tileLayout"] == "classic"


def _app(controls: dict, states: dict):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(controls))
    app.states = dict(states)
    return app


IRC = {"IR": {"name": "Raumregelung Küche", "type": "IRoomControllerV2", "uuidAction": "IR", "room": "r1",
              "cat": "c1", "states": {"tempActual": "ta", "tempTarget": "tt", "prepareState": "pr",
                                      "openWindow": "ow"}}}


def test_raumregelung_zeigt_die_ist_temperatur_gross():
    kachel = _app(IRC, {"ta": 21.5, "tt": 22.0, "pr": 1, "ow": 0})._control_item("IR")
    assert kachel["big"] == "21,5°"
    assert kachel["bigSub"] == "Soll 22,0° · heizt"
    assert kachel["sublabel"] == "21,5° → 22,0° · heizt", "der klassische Aufbau bleibt, wie er war"
    assert not kachel.get("subInfo")
    # Ohne Ist-Temperatur kein Messwert; "Heizung" beschreibt dann nur
    ohne = _app(IRC, {"tt": 22.0, "pr": 0, "ow": 0})._control_item("IR")
    assert "big" not in ohne and ohne["sublabel"] == "Heizung" and ohne["subInfo"] is True


SAUNA = {"SA": {"name": "Saunasteuerung", "type": "Sauna", "uuidAction": "SA", "room": "r1", "cat": "c1",
                "states": {"active": "a", "tempActual": "ta", "tempTarget": "tt", "mode": "m"}}}


@pytest.mark.parametrize("werte, big, big_sub, sub", [
    ({"a": 0, "ta": 25.4}, "25,4°", "Aus", "Aus · 25 °C"),
    ({"a": 1, "ta": 61.2, "tt": 90, "m": 1}, "61,2°", "Ein → 90 °C · Finnisch manuell",
     "Ein · 61 °C → 90 °C · Finnisch manuell"),
], ids=["aus", "heizt"])
def test_sauna_zeigt_die_temperatur_gross(werte, big, big_sub, sub):
    kachel = _app(SAUNA, werte)._control_item("SA")
    assert (kachel["big"], kachel["bigSub"], kachel["sublabel"]) == (big, big_sub, sub)


def test_sauna_ohne_temperatur_ohne_messwert():
    kachel = _app(SAUNA, {"a": 0})._control_item("SA")
    assert "big" not in kachel and kachel["sublabel"] == "Aus"


def _c(uuid, typ, states=None, **extra):
    return {uuid: {"name": f"Baustein {uuid}", "type": typ, "uuidAction": uuid, "room": "r1", "cat": "c1",
                   "states": states or {}, **extra}}


@pytest.mark.parametrize("controls, states, beschreibt", [
    (_c("I", "Intercom", {"bell": "b"}), {"b": 0}, True),
    (_c("I", "Intercom", {"bell": "b"}), {"b": 1}, False),        # "Es klingelt" ist ein Zustand
    (_c("I", "Webpage", details={"url": "http://kamera.local/bild"}), {}, True),
    (_c("I", "UpDownDigital"), {}, True),
    (_c("I", "Fronius", {"prodCurr": "p"}), {}, True),
    (_c("I", "Fronius", {"prodCurr": "p"}), {"p": 2.5}, False),
    (_c("I", "EFM", {"Ppwr": "p"}), {}, True),
    (_c("I", "EFM", {"Ppwr": "p"}), {"p": 0.5}, False),
    (_c("I", "AcControl", {"mode": "m", "targetTemperature": "t"}), {}, True),
    (_c("I", "CentralJalousie", details={"controls": []}), {}, True),
    (_c("I", "CentralAlarm", details={"controls": []}), {}, True),
    (_c("I", "CentralGate", details={"controls": []}), {}, False),  # "Alle geschlossen" ist ein Zustand
    (_c("I", "CentralWeitere", details={"controls": []}), {}, True),
    (_c("I", "Switch", {"active": "a"}), {"a": 1}, False),
], ids=["intercom-ruhe", "intercom-klingelt", "webseite", "auf-ab", "pv-ohne-wert", "pv-mit-wert",
        "energiefluss-ohne-werte", "energiefluss-mit-werten", "klima-ohne-werte", "zentral-beschattung",
        "zentral-alarm", "zentral-tore", "zentral-sonst", "schalter"])
def test_beschreibende_zeilen_sind_markiert(controls, states, beschreibt):
    kachel = _app(controls, states)._control_item("I")
    assert bool(kachel.get("subInfo")) is beschreibt, kachel
