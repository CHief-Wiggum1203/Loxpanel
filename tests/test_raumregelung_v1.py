"""Alte Raumregelung (IRoomController, v1): frueher weder Kachel noch
Detailseite, im Loxone-Forum gemeldet ("can't get the IRC v1 to do anything").
Befehle laut Loxone-Strukturdoku: settemp/<Nr>/<Wert>, starttimer/<Nr>/<Sekunden>,
stoptimer. Die Struktur kommt aus tests/lox.py (irc1_baustein, Form eines
echten Miniservers)."""
import pytest

from lox import W, anlage, bloecke, irc1_baustein


def _app(**werte) -> W.App:
    control, states = irc1_baustein(**werte)
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"IRC": control}))
    app.states = states
    return app


def _zeilen(view: dict) -> list[list[tuple]]:
    """Knopfzeilen als [(Beschriftung, Befehl, an?)]; ein Aufklapper hat den
    Befehl "menu" (Eintraege siehe test_betriebsart.py)."""
    return [[(c["label"], "menu" if "menu" in c else c["cmd"]["cmd"], bool(c.get("on"))) for c in b["cells"]]
            for b in bloecke(view, "row")]


def test_kachel():
    app = _app(valveHeat=0.4, openWindow=1)
    it = app._control_item("IRC")
    assert it["sublabel"] == "20,5° → 22,0° · heizt · Fenster"
    assert it["nav"] == {"view": "control", "id": "IRC"} and it["on"] is True and it["icon"] == "thermo"
    it = _app()._control_item("IRC")
    assert it["sublabel"] == "20,5° → 22,0°" and it["on"] is False
    assert _app(mode=4, valveCool=0.7)._control_item("IRC")["sublabel"] == "20,5° → 22,0° · kühlt"


def test_detail_heizen_komfort():
    """Autopilot Heizen, Komfort aktiv: -/+ auf Komfort Heizen (Nr. 1), Knopf
    Komfort markiert, Timer eine Stunde."""
    v = _app(valveHeat=1).render({"view": "control", "id": "IRC"})
    assert [b["text"] for b in bloecke(v, "big")] == ["20,5 °C"]
    assert [b["text"] for b in bloecke(v, "status")] == ["Soll 22,0 °C · Komfort Heizen · heizt"]
    assert _zeilen(v) == [
        [("−", "settemp/1/21.5", False), ("Betriebsart", "menu", False), ("+", "settemp/1/22.5", False)],
        [("Eco", "starttimer/0/3600", False), ("Komfort", "starttimer/1/3600", True),
         ("Automatik", "stoptimer", False)]]


def test_detail_kuehlen():
    """Autopilot Kuehlen: Komfort Kuehlen (Nr. 2) ist Stellgroesse und Timer."""
    v = _app(mode=4, currCoolTempIx=2, tempTarget=24.0, valveCool=1).render({"view": "control", "id": "IRC"})
    assert [b["text"] for b in bloecke(v, "status")] == ["Soll 24,0 °C · Komfort Kühlen · kühlt"]
    assert _zeilen(v)[0] == [("−", "settemp/2/23.5", False), ("Betriebsart", "menu", False),
                             ("+", "settemp/2/24.5", False)]
    assert ("Komfort", "starttimer/2/3600", True) in _zeilen(v)[1]


@pytest.mark.parametrize("mode", [5, 6], ids=["manuell_heizen", "manuell_kuehlen"])
def test_detail_manuell(mode):
    """Manueller Betrieb: -/+ verstellt die manuelle Temperatur (Nr. 7) ab dem Soll."""
    v = _app(mode=mode, tempTarget=23.0).render({"view": "control", "id": "IRC"})
    assert _zeilen(v)[0] == [("−", "settemp/7/22.5", False), ("Betriebsart", "menu", False),
                             ("+", "settemp/7/23.5", False)]


def test_detail_eco_aktiv():
    """Eco aktiv: Knopf Eco markiert, -/+ bleibt auf Komfort (Eco haengt davon ab)."""
    v = _app(currHeatTempIx=0, tempTarget=20.0).render({"view": "control", "id": "IRC"})
    assert [b["text"] for b in bloecke(v, "status")] == ["Soll 20,0 °C · Eco"]
    assert _zeilen(v)[0][2] == ("+", "settemp/1/22.5", False)
    assert ("Eco", "starttimer/0/3600", True) in _zeilen(v)[1]


def test_ohne_bekannte_komforttemperatur_kein_plus_minus():
    """Kein Wert fuer Komfort (oder als relativ gemeldet): kein -/+, statt einen
    Wert anzunehmen. Betriebsart, Timer und Automatik bleiben."""
    control, states = irc1_baustein()
    control["details"]["temperatures"]["1"]["isAbsolute"] = False
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"IRC": control}))
    app.states = states
    rows = _zeilen(app.render({"view": "control", "id": "IRC"}))
    assert [[lbl for lbl, _, _ in r] for r in rows] == [["Betriebsart"], ["Eco", "Komfort", "Automatik"]]

    control, states = irc1_baustein()
    states.pop("irc-t1")
    app._apply_structure(anlage({"IRC": control}))
    app.states = states
    assert [lbl for lbl, _, _ in _zeilen(app.render({"view": "control", "id": "IRC"}))[0]] == ["Betriebsart"]


def test_diagnose_voll_unterstuetzt():
    app = _app()
    e = next(t for t in app.types_overview()["types"] if t["type"] == "IRoomController")
    assert e["status"] == "full"
    assert "temperatures" in e["states"] and "temperatures" in e["details"]
