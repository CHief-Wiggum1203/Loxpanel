"""Sprungmarken der unteren Leiste (Raum-Panel, freie Auswahl) im Server: jede
Kachel traegt ihre Gruppe (grp), damit das Panel sie aufleuchten laesst und
nach ihr filtern kann; die Panel-Option catFilter ueberlebt das Speichern und
kommt im Profil an."""
from lox import RAUM_KATS, W, raum_anlage


def _app(panels: dict) -> W.App:
    struktur, states = raum_anlage()
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    app.states = states
    app.panels = W.App._sanitize_panels(panels)
    return app


def test_raum_panel_gruppe_an_jeder_kachel():
    app = _app({"sauna": {"title": "Sauna", "tabs": ["room:r1"]}})
    v = app.render({"view": "tab", "tab": "room:r1"}, app.resolve_profile("sauna"))
    gruppen = [it.get("grp") for it in v["items"]]
    # Reihenfolge nach Kategorie, jede Kachel mit ihrer Kategorie
    assert gruppen == [c for c, (_, n) in RAUM_KATS.items() for _ in range(n)]
    # Anker (catKey) weiterhin nur an der ersten Kachel jeder Gruppe
    assert [it.get("catKey") for it in v["items"] if it.get("catKey")] == list(RAUM_KATS)
    assert [t["key"] for t in v["catTabs"]] == list(RAUM_KATS)


def test_freie_auswahl_gruppe_ist_der_raum():
    seite = {"name": "Morgens", "picks": ["S1", "T1", "S4"]}
    app = _app({"m": {"title": "M", "tabs": ["auswahl"], "pickTabs": [seite]}})
    v = app.render({"view": "tab", "tab": "auswahl"}, app.resolve_profile("m"))
    assert [(it["id"], it.get("grp")) for it in v["items"]] == [("S1", "r1"), ("S4", "r1"), ("T1", "r2")]
    # Neben anderen Seiten gibt es keine Sprungmarken - dann auch keine Gruppe
    app = _app({"m": {"title": "M", "tabs": ["auswahl", "favoriten"], "pickTabs": [seite]}})
    v = app.render({"view": "tab", "tab": "auswahl"}, app.resolve_profile("m"))
    assert v["catTabs"] == [] and not any("grp" in it for it in v["items"])


def test_option_filter_bleibt_beim_speichern():
    roh = {"a": {"tabs": ["room:r1"], "ui": {"catFilter": True}},
           "b": {"tabs": ["room:r1"], "ui": {"catFilter": "ja"}},
           "c": {"tabs": ["room:r1"]}}
    p = W.App._sanitize_panels(roh)
    assert p["a"]["ui"]["catFilter"] is True
    assert "catFilter" not in (p["b"].get("ui") or {})   # nur echtes True, keine Zeichenkette
    app = _app(roh)
    assert app.resolve_profile("a")["catFilter"] is True
    assert app.resolve_profile("b")["catFilter"] is False
    assert app.resolve_profile("c")["catFilter"] is False
