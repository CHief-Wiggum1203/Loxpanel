"""Werteleiste (Punkt 5): Die Anzeige-Bausteine einer Seite (Messwerte,
Zaehler, Texte, Ein/Aus-Anzeigen, WERTE_LEISTE_TYPEN) stehen als Kette von
Werten in EINER Zeile ueber dem Raster statt als Kacheln, das Raster bleibt
dem Bedienbaren. Je Seite waehlbar: ui.valueBar nennt die Tab-Kennungen
("raeume"/"kategorien" gelten fuer die Raum- und Kategorie-Seiten darunter).
Hier die Server-Seite: Pruefer, Speichern, Export, aufgeloestes Profil und
die Trennung in den Ansichten (view.items / view.leiste)."""
from lox import W

STRUKTUR = {
    "rooms": {"r1": {"name": "Wohnzimmer"}, "r2": {"name": "Küche"}, "r3": {"name": "Keller"}},
    "cats": {"c1": {"name": "Licht"}, "c2": {"name": "Temperaturen"}, "c3": {"name": "Alarm"}},
    "controls": {
        "L1": {"name": "Licht Decke", "type": "Switch", "uuidAction": "L1", "room": "r1", "cat": "c1",
               "isFavorite": True, "states": {"active": "l1"}},
        "T1": {"name": "Temperatur Wohnzimmer", "type": "InfoOnlyAnalog", "uuidAction": "T1", "room": "r1",
               "cat": "c2", "isFavorite": True, "details": {"format": "%.1f°"}, "states": {"value": "t1"}},
        "F": {"name": "Fenster", "type": "InfoOnlyDigital", "uuidAction": "F", "room": "r1", "cat": "c2",
              "details": {"text": {"on": "offen", "off": "zu"}}, "states": {"active": "f"}},
        "H": {"name": "Betriebsstunden", "type": "Hourcounter", "uuidAction": "H", "room": "r1", "cat": "c2",
              "states": {"total": "h", "overdue": "ho"}},
        "P": {"name": "Präsenz", "type": "PresenceDetector", "uuidAction": "P", "room": "r1", "cat": "c2",
              "states": {"active": "p"}},
        "X": {"name": "Heizung", "type": "TextState", "uuidAction": "X", "room": "r1", "cat": "c2",
              "states": {"textAndIcon": "x"}},
        "S": {"name": "Rauchmelder", "type": "SmokeAlarm", "uuidAction": "S", "room": "r1", "cat": "c3",
              "isFavorite": True, "states": {"level": "s"}},
        "L2": {"name": "Licht Küche", "type": "Switch", "uuidAction": "L2", "room": "r2", "cat": "c1",
               "isFavorite": True, "states": {"active": "l2"}},
        "T2": {"name": "Temperatur Küche", "type": "InfoOnlyAnalog", "uuidAction": "T2", "room": "r2",
               "cat": "c2", "isFavorite": True, "details": {"format": "%.1f°"}, "states": {"value": "t2"}},
        "Z": {"name": "Stromzähler", "type": "Meter", "uuidAction": "Z", "room": "r2", "cat": "c2",
              "isFavorite": True, "details": {"actualFormat": "%.1f kW", "totalFormat": "%.0f kWh"},
              "states": {"actual": "za", "total": "zt"}},
        "K1": {"name": "Temperatur Keller", "type": "InfoOnlyAnalog", "uuidAction": "K1", "room": "r3",
               "cat": "c2", "details": {"format": "%.1f°"}, "states": {"value": "k1"}},
        "K2": {"name": "Feuchte Keller", "type": "InfoOnlyDigital", "uuidAction": "K2", "room": "r3",
               "cat": "c2", "states": {"active": "k2"}},
    },
}
ZUSTAND = {"l1": 1, "t1": 21.5, "f": 1, "h": 1234, "ho": 0, "p": 1, "x": "heizt", "s": 0,
           "l2": 0, "t2": 19.0, "za": 0.4, "zt": 5120, "k1": 12.5, "k2": 0}
ALLE_TABS = ["favoriten", "room:r1", "raeume", "auswahl"]
WERTE = ["T1", "F", "H", "P", "X", "T2", "Z", "K1", "K2"]


def _app(leiste: list | None = ALLE_TABS) -> W.App:
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    app.states = dict(ZUSTAND)
    prof = {"title": "P", "tabs": ALLE_TABS,
            "pickTabs": [{"name": "Seite", "picks": ["L1", "T1", "L2", "Z"]}]}
    if leiste is not None:
        prof["ui"] = {"valueBar": leiste}
    app.panels = W.App._sanitize_panels({"p": prof})
    return app


def _ids(xs) -> list:
    return [it["id"] for it in (xs or [])]


def test_typen_der_leiste():
    assert W.WERTE_LEISTE_TYPEN == {"Meter", "InfoOnlyAnalog", "TextState", "InfoOnlyText",
                                    "InfoOnlyDigital", "PresenceDetector", "Hourcounter"}
    assert "SmokeAlarm" not in W.WERTE_LEISTE_TYPEN and "ClimateControllerUS" not in W.WERTE_LEISTE_TYPEN
    assert W.WERTE_LEISTE_TYPEN < W.STATUS_BIG, "Werte der Leiste sind reine Anzeige-Bausteine"


def test_pruefer():
    assert W._clean_werteleiste(["favoriten", "foo", "favoriten", 3, None, "room:r1", "auswahl2", "cat:c1",
                                 "raeume", "kategorien", "zentral", "kalender"]) == \
        ["favoriten", "room:r1", "auswahl2", "cat:c1", "raeume", "kategorien", "zentral", "kalender"]
    assert W._clean_werteleiste("favoriten") == [] and W._clean_werteleiste(None) == []
    assert W._clean_werteleiste({"favoriten": True}) == [] and W._clean_werteleiste([]) == []


def test_speichern_exportieren_und_aufloesen():
    roh = {"p": {"title": "P", "tabs": ["favoriten", "room:r1"], "ui": {"valueBar": ["room:r1", "favoriten"]}}}
    p = W.App._sanitize_panels(roh)["p"]
    assert p["ui"]["valueBar"] == ["room:r1", "favoriten"]
    assert W.App._panels_verworfen(roh, W.App._sanitize_panels(roh)) == []
    app = W.App({"host": "", "port": 80})
    exp = app._panel_export(p)
    assert exp["ui"]["valueBar"] == ["room:r1", "favoriten"]
    assert W.App._sanitize_panels({"p": exp})["p"] == p, "Rundweg Konfigurator -> Server"
    app.panels = roh
    assert app.resolve_profile("p")["valueBar"] == ["room:r1", "favoriten"]
    # Ohne Option: kein Schluessel beim Speichern und im Export, leere Liste im Profil
    ohne = {"p": {"title": "P", "tabs": ["favoriten"]}}
    assert "valueBar" not in W.App._sanitize_panels(ohne)["p"].get("ui", {})
    assert "valueBar" not in app._panel_export(ohne["p"])["ui"]
    app.panels = ohne
    assert app.resolve_profile("p")["valueBar"] == []


def test_unbekannte_seite_wird_gemeldet():
    roh = {"p": {"title": "P", "tabs": ["favoriten"], "ui": {"valueBar": ["favoriten", "foo"]}}}
    sauber = W.App._sanitize_panels(roh)
    assert sauber["p"]["ui"]["valueBar"] == ["favoriten"]
    assert W.App._panels_verworfen(roh, sauber) == ["P: ui.valueBar: foo"]
    # eine leere oder falsch getypte Angabe faellt still weg (kein Inhalt)
    roh2 = {"p": {"title": "P", "tabs": ["favoriten"], "ui": {"valueBar": []}}}
    assert W.App._panels_verworfen(roh2, W.App._sanitize_panels(roh2)) == []


def test_favoriten_trennen_werte_vom_bedienbaren():
    app = _app()
    v = app.render({"view": "tab", "tab": "favoriten"}, app.resolve_profile("p"))
    assert _ids(v["items"]) == ["L1", "S", "L2"], "Schalter und Rauchmelder bleiben Kacheln"
    assert _ids(v["leiste"]) == ["T1", "T2", "Z"], "Messwerte und Zaehler in der Leiste, in Seitenreihenfolge"
    t1 = v["leiste"][0]
    assert t1["label"] == "Temperatur Wohnzimmer" and t1["sublabel"] == "21,5 °"
    assert t1["nav"] == {"view": "control", "id": "T1"}, "ein Tipp oeffnet die Wertseite wie die Kachel"
    assert t1.get("room") == "Wohnzimmer", "ueber mehrere Raeume traegt auch der Wert seinen Raum"
    assert v["leiste"][2]["sublabel"].startswith("0,4 kW • "), "Zaehler: Leistung und Stand wie auf der Kachel"


def test_ohne_option_bleibt_alles_kachel():
    app = _app(None)
    for route in ({"view": "tab", "tab": "favoriten"}, {"view": "tab", "tab": "room:r1"},
                  {"view": "tab", "tab": "auswahl"}, {"view": "group", "kind": "room", "id": "r2"}):
        v = app.render(route, app.resolve_profile("p"))
        assert "leiste" not in v, route
        assert any(i in WERTE for i in _ids(v["items"])), route


def test_option_gilt_je_seite():
    app = _app(["favoriten"])
    prof = app.resolve_profile("p")
    assert "leiste" in app.render({"view": "tab", "tab": "favoriten"}, prof)
    r = app.render({"view": "tab", "tab": "room:r1"}, prof)
    assert "leiste" not in r and "T1" in _ids(r["items"])


def test_raum_seite_anker_und_marken_zu_den_kacheln():
    """Die Trennung laeuft VOR dem Gruppieren: Anker (catKey) sitzt auf der
    ersten Kachel jeder Gruppe im Raster, die Sprungmarken nennen nur
    Kategorien, von denen Kacheln im Raster stehen. Der Raumname faellt auch
    aus den Werten der Leiste (Punkt 4)."""
    app = _app()
    v = app.render({"view": "tab", "tab": "room:r1"}, app.resolve_profile("p"))
    assert _ids(v["items"]) == ["S", "L1"], "Kategorien in Strukturreihenfolge (Alarm, Licht)"
    assert [it.get("catKey") for it in v["items"]] == ["c3", "c1"]
    assert [t["key"] for t in v["catTabs"]] == ["c3", "c1"], "Temperaturen haben keine Kachel mehr, also keine Marke"
    assert _ids(v["leiste"]) == ["T1", "F", "H", "P", "X"]
    assert v["leiste"][0]["label"] == "Temperatur" and "catKey" not in v["leiste"][0]
    assert [it["sublabel"] for it in v["leiste"]] == ["21,5 °", "offen", "1234 h", "Anwesend", "heizt"]


def test_raum_seite_unter_raeume_und_freie_seite():
    app = _app()
    prof = app.resolve_profile("p")
    g = app.render({"view": "group", "kind": "room", "id": "r2"}, prof)
    assert _ids(g["items"]) == ["L2"] and _ids(g["leiste"]) == ["T2", "Z"]
    assert g["leiste"][0]["label"] == "Temperatur", "Raum aus dem Namen (Punkt 4) auch in der Leiste"
    s = app.render({"view": "tab", "tab": "auswahl"}, prof)
    assert _ids(s["items"]) == ["L1", "L2"] and _ids(s["leiste"]) == ["T1", "Z"], "Klickreihenfolge bleibt"


def test_seite_nur_aus_werten_behaelt_ihre_kacheln():
    """Bliebe im Raster nichts, SIND die Werte die Seite: dann keine Leiste,
    sonst staende "nichts hier" unter einer Zeile voller Werte."""
    app = _app()
    prof = app.resolve_profile("p")
    k = app.render({"view": "group", "kind": "room", "id": "r3"}, prof)
    assert "leiste" not in k and _ids(k["items"]) == ["K1", "K2"]
    c = app.render({"view": "group", "kind": "cat", "id": "c2"}, prof)
    assert "leiste" not in c, "Kategorie Temperaturen: nur Werte, bleiben Kacheln"
    assert "kategorien" not in prof["valueBar"], "Vorbedingung: die Kategorie-Seiten haben die Option nicht"
    app2 = _app(ALLE_TABS + ["kategorien"])
    c2 = app2.render({"view": "group", "kind": "cat", "id": "c2"}, app2.resolve_profile("p"))
    assert "leiste" not in c2 and len(c2["items"]) == 9
