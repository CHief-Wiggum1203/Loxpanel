"""Zaehler und Raumregelung V2 nach der Loxone-Strukturdoku: Der Zaehler
zeigt Zaehlerstand und je Zeitraum heute/Woche/Monat/Jahr (totalDay ...),
in beide Richtungen auch die Gegenrichtung (totalNeg...), als Speicher den
Fuellstand. Die Raumregelung V2 hat eine Unterseite Einstellungen
(view=ircset) mit den Temperaturen samt Befehl, gesperrt, wenn die Logik sie
vorgibt (connectedInputs), und auf der Detailseite das Raumklima."""
from lox import W, anlage, bloecke, irc2_baustein, zaehler_baustein


def _app(baustein, **kw) -> tuple[W.App, str]:
    control, states = baustein(**kw)
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({control["uuidAction"]: control}))
    app.states = states
    return app, control["uuidAction"]


def _texte(v, k="status") -> list:
    return [b["text"] for b in bloecke(v, k)]


# ---- Zaehler ---------------------------------------------------------------

def test_zaehler_beide_richtungen():
    app, u = _app(zaehler_baustein)
    v = app.render({"view": "control", "id": u})
    assert bloecke(v, "big")[0]["text"] == "1,25 kW"
    # grosse Werte rechnet _fmt_num in die naechste Einheit um (kWh -> MWh)
    assert _texte(v) == ["Bezug 12,3 MWh", "Lieferung 4,3 MWh",
                         "Heute: Bezug 8,4 kWh · Lieferung 3,2 kWh", "Woche: Bezug 52,1 kWh · Lieferung 20,0 kWh",
                         "Monat: Bezug 210,0 kWh · Lieferung 90,5 kWh", "Jahr: Bezug 2,5 MWh · Lieferung 1,1 MWh"]
    assert _texte(v, "head") == ["Zeiträume"]


def test_zaehler_eine_richtung():
    app, u = _app(zaehler_baustein, art="unidirectional")
    v = app.render({"view": "control", "id": u})
    assert _texte(v) == ["Zählerstand 12,3 MWh", "Heute: 8,4 kWh", "Woche: 52,1 kWh", "Monat: 210,0 kWh",
                         "Jahr: 2,5 MWh"]
    assert _texte(v, "head") == ["Verbrauch"]


def test_zaehler_speicher():
    app, u = _app(zaehler_baustein, art="storage")
    assert "Speicher 7,5 kWh (75 %)" in _texte(app.render({"view": "control", "id": u}))


def test_zaehler_ohne_zeitraeume_wie_bisher():
    """Aelterer Miniserver (vor 13.01): nur actual und total."""
    control = {"name": "Wasser", "type": "Meter", "uuidAction": "W", "room": "r1", "cat": "c1",
               "details": {"actualFormat": "%.1f l/min", "totalFormat": "%.0f l"},
               "states": {"actual": "w1", "total": "w2"}}
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"W": control}))
    app.states = {"w1": 3.0, "w2": 1500}
    v = app.render({"view": "control", "id": "W"})
    assert bloecke(v, "big")[0]["text"] == "3,0 l/min"
    assert _texte(v) == ["Zählerstand 1500 l"] and not bloecke(v, "head")


# ---- Raumregelung V2 -------------------------------------------------------

def _einstellungen(**kw) -> dict:
    app, u = _app(irc2_baustein, **kw)
    return app.render({"view": "ircset", "id": u})


def test_einstellungen_alle_temperaturen():
    st = {b["label"]: b for b in bloecke(_einstellungen(), "stepper")}
    assert {k: (b["value"], b["cmd"]["tmpl"]) for k, b in st.items()} == {
        "Komfort Heizen": (22.5, "setComfortTemperature/{v}"),
        "Komfort Kühlen": (25.0, "setComfortTemperatureCool/{v}"),
        "Komfort-Toleranz (±)": (1.0, "setComfortTolerance/{v}"),
        "Eco nach unten": (2.0, "setAbsentMinTemperature/{v}"),
        "Eco nach oben": (2.0, "setAbsentMaxTemperature/{v}")}
    tol = st["Komfort-Toleranz (±)"]
    assert (tol["min"], tol["max"], tol["step"], tol["unit"]) == (0.5, 3.0, 0.5, "°C")


def test_einstellungen_von_der_logik_vorgegeben():
    control, states = irc2_baustein()
    control["details"]["connectedInputs"] = 0b10001   # Bit 1 Komfort Heizen, Bit 5 Eco unten
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"IRC2": control}))
    app.states = states
    st = {b["label"]: b for b in bloecke(app.render({"view": "ircset", "id": "IRC2"}), "stepper")}
    gesperrt = sorted(k for k, b in st.items() if "cmd" not in b)
    assert gesperrt == ["Eco nach unten", "Komfort Heizen"]
    assert st["Komfort Heizen"]["sub"] == "von der Logik vorgegeben"


def test_einstellungen_eine_komforttemperatur():
    control, states = irc2_baustein()
    control["details"]["SingleComfortTemperature"] = True
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"IRC2": control}))
    app.states = states
    labels = [b["label"] for b in bloecke(app.render({"view": "ircset", "id": "IRC2"}), "stepper")]
    assert labels == ["Komforttemperatur", "Komfort-Toleranz (±)", "Eco-Abweichung (±)"]


def test_einstellungen_beschattung_und_gebaeudeschutz():
    control, states = irc2_baustein()
    control["details"]["possibleCapabilities"] = 0b111   # Heizen, Kuehlen, Beschattung
    control["states"].update(shadingHeatTemp="s-h", shadingCoolTemp="s-c", heatProtectTemperature="s-hp")
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"IRC2": control}))
    app.states = {**states, "s-h": 26.0, "s-c": 24.0, "s-hp": 35.0}
    v = app.render({"view": "ircset", "id": "IRC2"})
    beschatten = [(b["label"], b["cmd"]["tmpl"]) for b in bloecke(v, "stepper") if "Beschatten" in b["label"]]
    assert beschatten == [("Beschatten ab (Heizen)", "setshadingtemperatureheat/{v}"),
                          ("Beschatten ab (Kühlen)", "setshadingtemperaturecool/{v}")]
    assert _texte(v) == ["Gebäudeschutz: Frost 5,0 °C · Hitze 35,0 °C"]
    control["details"]["possibleCapabilities"] = 0b011   # ohne Beschattung
    app._apply_structure(anlage({"IRC2": control}))
    v = app.render({"view": "ircset", "id": "IRC2"})
    assert not [b for b in bloecke(v, "stepper") if "Beschatten" in b["label"]]


def test_detailseite_fuehrt_zu_den_einstellungen_und_zeigt_raumklima():
    control, states = irc2_baustein()
    control["states"].update(actualOutdoorTemp="o", humidityActual="h", co2="c")
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"IRC2": control}))
    app.states = {**states, "o": 8.4, "h": 48, "c": 720}
    v = app.render({"view": "control", "id": "IRC2"})
    assert "Außen 8,4 °C · Feuchte 48 % · CO₂ 720 ppm" in _texte(v)
    assert bloecke(v, "row")[-1]["cells"] == [{"label": "Einstellungen", "nav": {"view": "ircset", "id": "IRC2"}}]
    app.states["o"] = -1000
    assert "Feuchte 48 % · CO₂ 720 ppm" in _texte(app.render({"view": "control", "id": "IRC2"}))


def test_einstellungen_eines_anderen_bausteins():
    app, _ = _app(zaehler_baustein)
    v = app.render({"view": "ircset", "id": "ZM"})
    assert _texte(v) == ["Diesen Baustein gibt es nicht mehr."]
