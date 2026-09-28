"""Energiefluss mit Speicher: Loxone zaehlt aus Sicht des Hauses, positiv
fliesst ins Haus. Ein entladender Speicher (Spwr > 0) liefert also wie das Netz
beim Bezug Strom ins Haus, ein ladender (Spwr < 0) nimmt ihn auf. Frueher war
der Speicher genau andersherum gezeichnet und beschriftet (Lenardo1/Loxpanel#14,
im Forum an einer Anlage mit Speicher bestaetigt). Das Netz stimmte schon und
laeuft hier als Gegenprobe mit."""
import pytest

from lox import EFM, EFM_NODES, EM2, W, anlage, bloecke

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


# --- Hausverbrauch (Fusszeile "Erzeugung · Verbrauch") ---
# Frueher stand beim Energiemanager immer "Verbrauch 0 W". Jetzt aus der Bilanz
# des Hauses: was hereinkommt (PV, Netzbezug, Speicher entlaedt), wird verbraucht.

@pytest.mark.parametrize("pv, netz, speicher, verbrauch", [
    (3.2, 0.3, 2.0, 5500.0),      # PV + Bezug + Speicher entlaedt
    (3.2, -0.4, -1.5, 1300.0),    # Einspeisung und Speicher laedt
    (0.0, 0.8, 0.0, 800.0),       # nachts: nur Netz
    (3.2, -3.5, 0.0, 0.0),        # Messversatz: Einspeisung > Erzeugung -> 0, nicht negativ
], ids=["bezug_entladen", "einspeisen_laden", "nur_netz", "nicht_negativ"])
def test_energiemanager_verbrauch_aus_bilanz(pv, netz, speicher, verbrauch):
    app = _app({"m-p": pv, "m-g": netz, "m-s": speicher, "m-soc": 50})
    assert app.energy_blocks("M")["totals"]["cons"] == pytest.approx(verbrauch)


def test_verbrauch_unbekannt_statt_null():
    """Ohne Netzwert, oder mit angelegtem Speicher ohne Wert: unbekannt (None),
    die Fusszeile laesst "Verbrauch" dann weg."""
    assert _app({"m-p": 3.2, "m-s": 1.0}).energy_blocks("M")["totals"]["cons"] is None
    assert _app({"m-p": 3.2, "m-g": 0.3}).energy_blocks("M")["totals"]["cons"] is None


def test_verbrauch_ohne_speicher():
    """Kein Speicher-State (bzw. HasSpwr false): Bilanz aus PV und Netz."""
    em = dict(EM2, states={k: v for k, v in EM2["states"].items() if k not in ("Spwr", "Ssoc")})
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"M": em}))
    app.states = {"m-p": 3.2, "m-g": 0.3}
    assert app.energy_blocks("M")["totals"]["cons"] == pytest.approx(3500.0)
    em = dict(EM2, details={"HasSpwr": False})
    app._apply_structure(anlage({"M": em}))
    app.states = {"m-p": 3.2, "m-g": 0.3, "m-s": 9.9}
    assert app.energy_blocks("M")["totals"]["cons"] == pytest.approx(3500.0)


def test_efm_verbrauch_knoten_oder_bilanz():
    """Energieflussmonitor mit Verbraucher-Knoten: deren Summe wie bisher;
    ohne Verbraucher-Knoten: die Bilanz aus Ppwr/Gpwr/Spwr."""
    app = _app({"f-a0": 0.8, "f-a1": 3.2, "f-a2": 2.0, "f-a3": 1.2})
    assert app.energy_blocks("F")["totals"]["cons"] == pytest.approx(1200.0)
    efm = dict(EFM, details={"actualFormat": "%.2f kW", "nodes": EFM_NODES[:3]})
    app._apply_structure(anlage({"F": efm}))
    app.states = {"f-p": 3.2, "f-g": 0.3, "f-s": 2.0, "f-a0": 0.3, "f-a1": 3.2, "f-a2": 2.0}
    assert app.energy_blocks("F")["totals"]["cons"] == pytest.approx(5500.0)
