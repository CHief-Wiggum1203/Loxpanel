"""Betriebsart der Raumregelung auf der Detailseite: Aufklapper zwischen - und +.
V2: operatingMode 0..5, setOperatingMode/<Nr> (wie in der openHAB-Loxone-
Anbindung). Alte Raumregelung: mode/<Nr> mit 0, 3..6 laut Loxone-Strukturdoku,
1/2 ("Automatik, heizt/kuehlt gerade") gelten als Automatik; restrictedToMode
blendet Heizen bzw. Kuehlen aus. Manuelle Betriebsart steht in der Statuszeile."""
import pytest

from lox import W, anlage, bloecke, irc1_baustein, irc2_baustein


def _app(baustein, uuid: str, **werte) -> W.App:
    control, states = baustein(**werte)
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({uuid: control}))
    app.states = states
    return app


def _detail(app: W.App, uuid: str) -> dict:
    return app.render({"view": "control", "id": uuid})


def _menue(view: dict) -> list[tuple]:
    """Eintraege des Aufklappers Betriebsart als (Name, Befehl, markiert?)."""
    zelle = next(c for b in bloecke(view, "row") for c in b["cells"] if "menu" in c)
    assert zelle["label"] == "Betriebsart"
    return [(e["label"], e["cmd"]["cmd"], bool(e.get("on"))) for e in zelle["menu"]]


def _reihe(view: dict) -> list[str]:
    return [c["label"] for c in bloecke(view, "row")[0]["cells"]]


def _status(view: dict) -> str:
    return bloecke(view, "status")[0]["text"]


# --- V2 ---

def test_v2_alle_betriebsarten_markiert():
    v = _detail(_app(irc2_baustein, "IRC2", operatingMode=1), "IRC2")
    assert _reihe(v) == ["−", "Betriebsart", "+"]
    assert _menue(v) == [
        ("Automatik Heizen & Kühlen", "setOperatingMode/0", False),
        ("Automatik nur Heizen", "setOperatingMode/1", True),
        ("Automatik nur Kühlen", "setOperatingMode/2", False),
        ("Manuell Heizen & Kühlen", "setOperatingMode/3", False),
        ("Manuell nur Heizen", "setOperatingMode/4", False),
        ("Manuell nur Kühlen", "setOperatingMode/5", False)]
    assert _status(v) == "Soll 22,5 °C · Komfort"          # Automatik: kein Zusatz


def test_v2_manuell_in_der_statuszeile():
    v = _detail(_app(irc2_baustein, "IRC2", operatingMode=4, prepareState=1), "IRC2")
    assert _status(v) == "Soll 22,5 °C · Komfort · Manuell nur Heizen · heizt"
    assert ("Manuell nur Heizen", "setOperatingMode/4", True) in _menue(v)


def test_v2_ohne_komfortwert_kein_plus_minus():
    """Frueher galt ohne Komfortwert das Soll oder 20 °C - das Soll kann Eco
    sein. Jetzt: kein -/+, die Betriebsart bleibt."""
    app = _app(irc2_baustein, "IRC2", comfortTemperature=None)
    assert _reihe(_detail(app, "IRC2")) == ["Betriebsart"]
    befehle = [c["cmd"]["cmd"] for b in bloecke(_detail(app, "IRC2"), "row") for c in b["cells"] if "cmd" in c]
    assert not [b for b in befehle if b.startswith("setComfortTemperature")]


def test_v2_ohne_state_keine_betriebsart():
    control, states = irc2_baustein()
    del control["states"]["operatingMode"]
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"IRC2": control}))
    app.states = states
    assert _reihe(_detail(app, "IRC2")) == ["−", "+"]


# --- alte Raumregelung (v1) ---

@pytest.mark.parametrize("mode, markiert", [(0, "Automatik"), (1, "Automatik"), (2, "Automatik"),
                                            (3, "Automatik Heizen"), (6, "Manuell Kühlen")])
def test_v1_betriebsart_markiert(mode, markiert):
    v = _detail(_app(irc1_baustein, "IRC", mode=mode), "IRC")
    menue = _menue(v)
    assert [(n, b) for n, b, _ in menue] == [
        ("Automatik", "mode/0"), ("Automatik Heizen", "mode/3"), ("Automatik Kühlen", "mode/4"),
        ("Manuell Heizen", "mode/5"), ("Manuell Kühlen", "mode/6")]
    assert [n for n, _, an in menue if an] == [markiert]


@pytest.mark.parametrize("nur, erwartet", [
    (1, ["Automatik", "Automatik Kühlen", "Manuell Kühlen"]),
    (2, ["Automatik", "Automatik Heizen", "Manuell Heizen"])], ids=["nur_kuehlen", "nur_heizen"])
def test_v1_eingeschraenkt(nur, erwartet):
    control, states = irc1_baustein()
    control["details"]["restrictedToMode"] = nur
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"IRC": control}))
    app.states = states
    assert [n for n, _, _ in _menue(_detail(app, "IRC"))] == erwartet


def test_v1_manuell_in_der_statuszeile():
    v = _detail(_app(irc1_baustein, "IRC", mode=5, tempTarget=23.0, currHeatTempIx=7), "IRC")
    assert _status(v) == "Soll 23,0 °C · Manuell Heizen"
    assert _reihe(v) == ["−", "Betriebsart", "+"]
