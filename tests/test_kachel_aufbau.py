"""Neuer Kachel-Aufbau, Server-Seite: die Panel-Option ui.tileLayout (nur
"classic" wird gespeichert, der neue Aufbau ist der Standard), die Messwerte,
die eine Kachel gross an Stelle des Symbols zeigt (big/bigSub), und die
Kennung fuer Zweitzeilen, die nur beschreiben statt einen Zustand zu nennen
(subInfo), und die Schriftgroessen ohne Einstellung je Aufbau. Dazu: jede
Panel-Option, die das Speichern behaelt, kommt auch beim Konfigurator an -
catFilter und roomCats fehlten dort und gingen beim naechsten Speichern
verloren."""
import json
import shutil

import pytest

from lox import ROOT, W, anlage, raum_anlage

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


# Ein Profil, das jedes Feld belegt, das _sanitize_panels speichert, jedes mit
# einem gueltigen Wert (test_vorlage_belegt_jedes_gespeicherte_feld wacht
# darueber). Bausteine, Raeume und Kategorien aus raum_anlage(), damit rooms,
# cats, hide und picks den Abgleich des Exports mit der Struktur ueberstehen.
# rooms und cats folgen der Reihenfolge der Struktur (raum_anlage: r1 vor r2,
# c1 bis c4): der Export ordnet sie so, eine andere Reihenfolge waere kein
# Verlust, liesse den Fixpunkt aber aus dem falschen Grund scheitern.
OVERLAY_VOLL = {"mode": "border", "fill": 20, "bord": 30, "ibord": 40, "ring": 50, "rtrk": 60,
                "bw": 2, "ibw": 3, "rw": 6}
VOLL = {
    "title": "Sauna", "tabs": ["room:r1", "auswahl"], "rooms": ["r1"], "cats": ["c1", "c2"],
    "roomCats": ["c4", "c2"],          # Klickreihenfolge, nicht die der Struktur
    "hide": ["S1"], "picks": ["S2"], "pickName": "Morgens",
    "pickTabs": [{"name": "Seite", "picks": ["S3"], "icon": "/icon?n=x", "widget": "weather"}],
    "ui": {"iconSize": 30, "nameSize": 20, "subSize": 14, "roomSize": 12, "bigSize": 40, "font": "Inter",
           "nudgeX": 4, "dpmsOff": 60, "reloadHours": 24, "nightDim": 50, "nightWake": 20, "pinMerken": 90,
           "cols": 3, "rows": 3, "fill": True, "split": False, "catFilter": True, "tileLayout": "classic",
           "grid": "auto", "tileSize": "small", "player": "Z1", "panes": {"room:r1": "weather"},
           "svPane": "calendar", "scale": "auto", "textColor": "#ffffff", "baseColor": "#3a6ea5",
           "bold": True, "lang": "en", "overlay": OVERLAY_VOLL},
    "states": {"active": "#00ff00", "good": "#00aa00", "warn": "#ffaa00", "crit": "#ff0000"},
    "tiles": {"S1": {"iconColor": "#111111", "textColor": "#222222", "bg": "#333333", "border": "#444444",
                     "font": "Inter", "bold": True, "italic": True, "overlay": OVERLAY_VOLL,
                     "icon": {"src": "builtin", "id": "lamp"}, "chart": "24h", "chartStyle": "span", "w": 2}},
}
# Zweige, deren Schluessel Daten sind (Tab-Kennung, Baustein-UUID) statt
# Feldnamen: nur die darf _sanitize_panels als Ganzes durchlaufen.
DATEN_ZWEIGE = {("ui", "panes"), ("tiles",)}


def _pfade(wert, pfad: tuple = ()) -> set:
    """Alle Schluesselpfade eines Profils, Listeneintraege als "[]"."""
    if isinstance(wert, dict):
        return {pfad + (k,) for k in wert} | {p for k, v in wert.items() for p in _pfade(v, pfad + (k,))}
    if isinstance(wert, list):
        return {p for v in wert for p in _pfade(v, pfad + ("[]",))}
    return set()


class _Lesespur(dict):
    """Profil, das mitschreibt, welche Schluessel gelesen werden (Pfad ab dem
    Profil) und welche Zweige jemand als Ganzes durchlaeuft oder kopiert
    (dict(), {**x}, copy() und json gehen ueber keys()/items())."""

    def __init__(self, d: dict, pfad: tuple, spur: dict):
        super().__init__({k: _lesespur(v, pfad + (k,), spur) for k, v in d.items()})
        self._pfad, self._spur = pfad, spur

    def _lies(self, k):
        self._spur["gelesen"].add(self._pfad + (k,))

    def _ganz(self):
        self._spur["durchlaufen"].add(self._pfad)

    def get(self, k, default=None):
        self._lies(k)
        return super().get(k, default)

    def __getitem__(self, k):
        self._lies(k)
        return super().__getitem__(k)

    def __contains__(self, k):
        self._lies(k)
        return super().__contains__(k)

    def setdefault(self, k, default=None):
        self._lies(k)
        return super().setdefault(k, default)

    def pop(self, k, *default):
        self._lies(k)
        return super().pop(k, *default)

    def __iter__(self):
        self._ganz()
        return super().__iter__()

    def keys(self):
        self._ganz()
        return super().keys()

    def items(self):
        self._ganz()
        return super().items()

    def values(self):
        self._ganz()
        return super().values()


def _lesespur(wert, pfad: tuple, spur: dict):
    if isinstance(wert, dict):
        return _Lesespur(wert, pfad, spur)
    if isinstance(wert, list):
        return [_lesespur(v, pfad + ("[]",), spur) for v in wert]
    return wert


def test_vorlage_belegt_jedes_gespeicherte_feld():
    """VOLL belegt jedes Feld, das _sanitize_panels liest, und nichts davon
    wird verworfen - also steht jedes Feld, das es speichern kann, auch im
    gespeicherten VOLL. Ein neues Feld im Sanitizer, das in VOLL fehlt, faellt
    hier auf. Mitgeschrieben wird beim Lesen statt im Quelltext gesucht: so
    zaehlt jede Schreibweise (get, [], in, Hilfsfunktion), und wer ein Profil
    als Ganzes kopiert oder durchlaeuft, laesst den Test laut scheitern statt
    still weniger zu pruefen."""
    spur = {"gelesen": set(), "durchlaufen": set()}
    W.App._sanitize_panels({"p": _lesespur(VOLL, (), spur)})
    fehlt = sorted(".".join(p) for p in spur["gelesen"] - _pfade(VOLL))
    assert fehlt == [], f"_sanitize_panels liest Felder, die VOLL nicht belegt (VOLL ergaenzen): {fehlt}"
    ganz = sorted(".".join(p) or "<Profil>" for p in spur["durchlaufen"] - DATEN_ZWEIGE)
    assert ganz == [], (f"_sanitize_panels durchlaeuft {ganz} als Ganzes - welche Felder es dort "
                        "speichert, sieht dieser Test nicht; DATEN_ZWEIGE nur fuer Daten-Schluessel erweitern")
    verworfen = W.App._panels_verworfen({"p": VOLL}, W.App._sanitize_panels({"p": VOLL}))
    assert verworfen == [], f"VOLL braucht gueltige Werte, verworfen: {verworfen}"


def test_jede_gespeicherte_option_kommt_beim_konfigurator_an():
    """Was _sanitize_panels behaelt, muss _panel_export an den Konfigurator
    geben: der schickt beim Speichern alle Profile zurueck, wie er sie bekam.
    Laden und unveraendert Speichern laesst ein Profil also gleich (Fixpunkt),
    fuer jedes Feld aus VOLL - oberste Ebene, ui, states, tiles, pickTabs."""
    struktur, _ = raum_anlage()
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    gespeichert = W.App._sanitize_panels({"p": VOLL})["p"]
    exportiert = json.loads(json.dumps(app._panel_export(gespeichert)))     # wie /api/meta
    wieder = W.App._sanitize_panels({"p": exportiert})["p"]
    fehlt = sorted(".".join(p) for p in _pfade(gespeichert) - _pfade(wieder))
    assert fehlt == [], f"beim Konfigurator fehlen {fehlt}"
    assert wieder == gespeichert


@pytest.mark.parametrize("roh, erwartet", [
    (["c4", "c2"], ["c4", "c2"]),
    (["c4", 3, None, "c2"], ["c4", "c2"]),
    (["c1", "c2", "c3", "c4", "c2"], ["c1", "c2", "c3", "c4"]),
    (["alt", "c2"], ["alt", "c2"]),     # nicht gegen die Struktur gefiltert: eine fehlende Kategorie bleibt
    ("c4", []), ({"c4": 1}, []), (None, []),
])
def test_export_gibt_die_kategorie_tabs_des_raum_panels_weiter(roh, erwartet):
    """panels.json wird ungeprueft geladen: eine Zeichenkette oder ein Dict an
    Stelle der Liste ergibt keine Auswahl (= automatisch), keine Buchstaben."""
    struktur, _ = raum_anlage()
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    assert app._panel_export({"title": "Sauna", "tabs": ["room:r1"], "roomCats": roh})["roomCats"] == erwartet


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
