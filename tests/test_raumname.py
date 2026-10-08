"""Raumnamen aus Kachelnamen streichen (Punkt 4): Auf einer Raum-Seite (Tab
room:<uuid> oder Raum aus "Räume") nennt der Titel den Raum schon, also faellt
er aus den Kachelnamen ("Jalousie Wohnzimmer Süd" -> "Jalousie Süd"). Nur
ganze Woerter, Reihenfolge bleibt, Trenner am Rand fallen weg; der Name
bleibt, wenn der Raum nicht vorkommt oder nichts uebrig bliebe. Seiten ueber
mehrere Raeume (Favoriten, Kategorie) behalten die vollen Namen."""
import pytest

from lox import W

STRUKTUR = {
    "rooms": {"r1": {"name": "Wohnzimmer"}, "r2": {"name": "Essen-Kochen-Wohnen"}},
    "cats": {"c1": {"name": "Beschattung"}, "c2": {"name": "Licht"}},
    "controls": {
        "J": {"name": "Jalousie Wohnzimmer Süd", "type": "Switch", "uuidAction": "J", "room": "r1", "cat": "c1",
              "isFavorite": True, "states": {"active": "j"}},
        "L": {"name": "Wohnzimmer Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c2",
              "isFavorite": True, "states": {"active": "l"}},
        "D": {"name": "Deckenlicht", "type": "Switch", "uuidAction": "D", "room": "r1", "cat": "c2",
              "states": {"active": "d"}},
        "W": {"name": "Wohnzimmer", "type": "Switch", "uuidAction": "W", "room": "r1", "cat": "c2",
              "states": {"active": "w"}},
        "E": {"name": "Licht Essen-Kochen-Wohnen Decke", "type": "Switch", "uuidAction": "E", "room": "r2",
              "cat": "c2", "isFavorite": True, "states": {"active": "e"}},
    },
}


@pytest.mark.parametrize("name, raum, erwartet", [
    ("Jalousie Wohnzimmer Süd", "Wohnzimmer", "Jalousie Süd"),
    ("Wohnzimmer Licht", "Wohnzimmer", "Licht"),
    ("Licht Wohnzimmer", "Wohnzimmer", "Licht"),
    ("Licht - Wohnzimmer", "Wohnzimmer", "Licht"),
    ("Wohnzimmer: Decke", "Wohnzimmer", "Decke"),
    ("Licht wohnzimmer", "Wohnzimmer", "Licht"),
    ("Licht Essen-Kochen-Wohnen Decke", "Essen-Kochen-Wohnen", "Licht Decke"),
    ("Licht Bad OG", "Bad OG", "Licht"),
    ("Wohnzimmerlampe", "Wohnzimmer", "Wohnzimmerlampe"),      # kein ganzes Wort
    ("Wohnzimmer", "Wohnzimmer", "Wohnzimmer"),                # es bliebe nichts uebrig
    ("Deckenlicht", "Wohnzimmer", "Deckenlicht"),
    ("Licht", "", "Licht"), ("", "Wohnzimmer", ""),
])
def test_raumname_faellt_aus_dem_kachelnamen(name, raum, erwartet):
    assert W._ohne_raum(name, raum) == erwartet


def _app() -> W.App:
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    app.states = {"j": 0, "l": 1, "d": 0, "w": 0, "e": 0}
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["room:r1", "favoriten", "raeume"]}})
    return app


def _labels(view: dict) -> dict:
    return {it["id"]: it["label"] for it in view["items"]}


def test_raum_seite_nennt_den_raum_nur_im_titel():
    app = _app()
    prof = app.resolve_profile("p")
    v = app.render({"view": "tab", "tab": "room:r1"}, prof)
    assert v["title"] == "Wohnzimmer"
    assert _labels(v) == {"J": "Jalousie Süd", "L": "Licht", "D": "Deckenlicht", "W": "Wohnzimmer"}
    g = app.render({"view": "group", "kind": "room", "id": "r2"}, prof)
    assert g["title"] == "Essen-Kochen-Wohnen" and _labels(g) == {"E": "Licht Decke"}


def test_seiten_ueber_mehrere_raeume_behalten_den_namen():
    app = _app()
    prof = app.resolve_profile("p")
    f = app.render({"view": "tab", "tab": "favoriten"}, prof)
    assert _labels(f) == {"J": "Jalousie Wohnzimmer Süd", "L": "Wohnzimmer Licht", "E": "Licht Essen-Kochen-Wohnen Decke"}
    assert all(it.get("room") for it in f["items"]), "Favoriten ueber zwei Raeume tragen den Raum an der Kachel"
    k = app.render({"view": "group", "kind": "cat", "id": "c2"}, prof)
    assert _labels(k)["L"] == "Wohnzimmer Licht"
