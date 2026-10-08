"""Verlinkte Objekte (Structure File "links"): In Loxone Config verlinkte
Bausteine erscheinen unter der Detailseite als tippbare Zeile, wie in der
Loxone-App (Muell-Status -> Abholtermine). Unbekannte Ziele, Dubletten und
der Baustein selbst fallen weg; Seiten ohne Links aendern sich nicht."""
from lox import W, anlage, bloecke


def _app(links, fenster=0):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({
        "M": {"name": "Müll", "type": "TextState", "uuidAction": "M", "states": {"textAndIcon": "sm"},
              "room": "r1", "links": links},
        "P": {"name": "Papier", "type": "InfoOnlyDigital", "uuidAction": "P", "states": {"active": "sp"},
              "details": {"text": {"on": "morgen", "off": "–"}}, "room": "r1"},
        "B": {"name": "Bio", "type": "InfoOnlyDigital", "uuidAction": "B", "states": {"active": "sb"},
              "details": {"text": {"on": "heute", "off": "–"}}, "room": "r1"},
        "S": {"name": "Hoflicht", "type": "Switch", "uuidAction": "S", "states": {"active": "ss"}, "room": "r1"},
        "T": {"name": "Boiler", "type": "InfoOnlyAnalog", "uuidAction": "T", "states": {"value": "st"},
              "details": {"format": "%.1f°C"}},
    }))
    app.states = {"sm": "2 Termine", "sp": 1, "sb": 0, "ss": 1, "st": 51.5}
    return app


def _links(v):
    rows = [b for b in bloecke(v, "row") if str(b.get("id", "")).startswith("links:")]
    return rows[0] if rows else None


def test_zeile_mit_zustand_und_sprung():
    v = _app(["P", "B"]).render({"view": "control", "id": "M"})
    assert [b["text"] for b in bloecke(v, "head")] == ["Verlinkte Objekte"]
    row = _links(v)
    assert row["wrap"] is True and row["id"] == "links:M"
    assert [c["label"] for c in row["cells"]] == ["Papier · morgen", "Bio · –"]
    assert [c["on"] for c in row["cells"]] == [True, False]
    assert all(c["nav"] == {"view": "control", "id": u} for c, u in zip(row["cells"], ["P", "B"]))


def test_schaltende_ziele_schalten():
    """Ein verlinkter Schalter hat keine Detailseite: die Zelle schaltet."""
    row = _links(_app(["S"]).render({"view": "control", "id": "M"}))
    cell = row["cells"][0]
    assert cell["label"].startswith("Hoflicht") and cell["on"] is True
    assert "nav" not in cell and cell["cmd"]["uuid"] == "S"


def test_unbekannt_dublette_und_selbst():
    row = _links(_app(["P", "GIBTSNICHT", "P", "M", "T"]).render({"view": "control", "id": "M"}))
    assert [c["label"] for c in row["cells"]] == ["Papier · morgen", "Boiler · 51,5 °C"]


def test_ohne_links_unveraendert():
    v = _app([]).render({"view": "control", "id": "M"})
    assert _links(v) is None and not bloecke(v, "head")
    v = _app(["GIBTSNICHT"]).render({"view": "control", "id": "M"})
    assert _links(v) is None


def test_versteckte_ziele_bleiben_weg_und_gesicherte_tragen_secured():
    """Codex-Befunde an #120: Ein auf dem Panel ausgeblendetes Ziel (hide)
    erscheint nicht unter den verlinkten Objekten - sonst verriete die Zeile
    Name, Zustand und Befehl. Ein gesichertes Ziel (Visu-PIN) traegt secured
    an der Zelle, damit die Visu vor dem Schalten die PIN abfragt wie auf
    seiner eigenen Seite."""
    app = _app(["P", "B", "S"])
    app.controls["S"]["isSecured"] = True
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["favoriten"], "hide": ["B"]}})
    prof = app.resolve_profile("p")
    row = _links(app.render({"view": "control", "id": "M"}, prof))
    assert [c["label"] for c in row["cells"]] == ["Papier · morgen", "Hoflicht · Ein"]
    assert row["cells"][1]["cmd"]["uuid"] == "S" and row["cells"][1]["secured"] is True
    assert "secured" not in row["cells"][0]
    # ohne Profil wie bisher: alle Ziele
    assert [c["label"] for c in _links(app.render({"view": "control", "id": "M"}))["cells"]] == \
        ["Papier · morgen", "Bio · –", "Hoflicht · Ein"]
