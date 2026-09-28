"""Energiefluss mit Speicher: Loxone zaehlt aus Sicht des Hauses, positiv
fliesst ins Haus. Ein entladender Speicher (Spwr > 0) liefert also wie das Netz
beim Bezug Strom ins Haus, ein ladender (Spwr < 0) nimmt ihn auf. Frueher war
der Speicher genau andersherum gezeichnet und beschriftet (Lenardo1/Loxpanel#14,
im Forum an einer Anlage mit Speicher bestaetigt). Das Netz stimmte schon und
laeuft hier als Gegenprobe mit."""
import pytest

from lox import W, anlage, bloecke

EFM_NODES = [{"name": "Netz", "nodeType": "Grid"}, {"name": "PV", "nodeType": "Production"},
             {"name": "Batterie", "nodeType": "Storage"}, {"name": "Wärmepumpe", "nodeType": "Load"}]

EFM = {"name": "Energieflussmonitor", "type": "EFM", "uuidAction": "F", "room": "r1", "cat": "c1",
       "details": {"actualFormat": "%.2f kW", "nodes": EFM_NODES},
       "states": {"Ppwr": "f-p", "Gpwr": "f-g", "Spwr": "f-s",
                  **{f"actual{i}": f"f-a{i}" for i in range(len(EFM_NODES))}}}

EM2 = {"name": "Energiemanager", "type": "EnergyManager2", "uuidAction": "M", "room": "r1", "cat": "c1",
       "details": {}, "states": {"Ppwr": "m-p", "Gpwr": "m-g", "Spwr": "m-s", "Ssoc": "m-soc"}}

# (Spwr in kW, erwartete Flussrichtung, erwartete Rolle/Farbe)
SPEICHER = [(2.0, "in", "prod"), (-1.5, "out", "load"), (0.0, None, "idle")]
SPEICHER_IDS = ["entlaedt", "laedt", "ruht"]


def _app(states: dict) -> W.App:
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"F": EFM, "M": EM2}))
    app.states = states
    return app


def _knoten(eb: dict, name: str) -> dict:
    return next(n for n in eb["nodes"] if n["name"] == name)


@pytest.mark.parametrize("spwr, flow, kind", SPEICHER, ids=SPEICHER_IDS)
def test_efm_speicher_knoten(spwr, flow, kind):
    """Knoten mit nodeType Storage: entladen = zur Mitte (Quelle, gruen),
    laden = nach aussen (Verbraucher, orange)."""
    app = _app({"f-a0": 0.8, "f-a1": 3.2, "f-a2": spwr, "f-a3": 1.2})
    eb = app.energy_blocks("F")
    sp = _knoten(eb, "Batterie")
    assert (sp["flow"], sp["kind"]) == (flow, kind)
    assert sp["w"] == abs(spwr) * 1000
    # Gegenprobe: Netzbezug, PV und Verbraucher bleiben, wie sie waren
    assert (_knoten(eb, "Netz")["flow"], _knoten(eb, "Netz")["kind"]) == ("in", "grid")
    assert (_knoten(eb, "PV")["flow"], _knoten(eb, "PV")["kind"]) == ("in", "prod")
    assert (_knoten(eb, "Wärmepumpe")["flow"], _knoten(eb, "Wärmepumpe")["kind"]) == ("out", "load")


@pytest.mark.parametrize("spwr, flow, kind", SPEICHER, ids=SPEICHER_IDS)
def test_energiemanager_speicher_knoten(spwr, flow, kind):
    """Summen-Knoten aus Spwr (EnergyManager2) mit derselben Richtung."""
    app = _app({"m-p": 3.2, "m-g": -0.5, "m-s": spwr, "m-soc": 64})
    eb = app.energy_blocks("M")
    sp = _knoten(eb, "Speicher")
    assert (sp["flow"], sp["kind"]) == (flow, kind)
    assert sp["soc"] == 64
    # Gegenprobe: Einspeisung geht nach aussen
    assert (_knoten(eb, "Netz")["flow"], _knoten(eb, "Netz")["kind"]) == ("out", "prod")


@pytest.mark.parametrize("spwr, text", [(2.0, "Speicher entlädt 2,00 kW"), (-1.5, "Speicher lädt 1,50 kW"),
                                        (0.0, "Speicher 0,00 kW")], ids=SPEICHER_IDS)
def test_energiemanager_detail_text(spwr, text):
    """Detailseite des Energiemanagers: Text passt zum Pfeil, 0 kW ohne Richtung."""
    app = _app({"m-p": 3.2, "m-g": 0.8, "m-s": spwr, "m-soc": 64})
    texte = [b["text"] for b in bloecke(app.render({"view": "control", "id": "M"}), "status")]
    assert text in texte
    assert "Netzbezug 0,80 kW" in texte
    assert not [t for t in texte if t.startswith("Speicher") and t != text and not t.endswith("%")]


def test_netz_texte_unveraendert():
    """Netz: positiv = Bezug, negativ = Einspeisung, 0 wie bisher als Bezug."""
    app = _app({})
    assert app._flow_text(0.8, "%.2f kW", "Netzbezug", "Einspeisung") == "Netzbezug 0,80 kW"
    assert app._flow_text(-0.5, "%.2f kW", "Netzbezug", "Einspeisung") == "Einspeisung 0,50 kW"
    assert app._flow_text(0, "%.2f kW", "Netzbezug", "Einspeisung") == "Netzbezug 0,00 kW"
    assert app._flow_text(None, "%.2f kW", "Netzbezug", "Einspeisung") == ""
