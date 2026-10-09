"""Seiten-Editor (Punkt 10), Server: eine freie Seite traegt ihre Anordnung
(pickTabs[i].layout [{id, w, h}], Groessen 1x1, 2x1, 2x2) und ob die Visu sie
nach Raum gruppiert (byRoom, Standard an). picks bestimmt, was auf der Seite
steht, das Layout Reihenfolge und Groesse."""
import pytest

from lox import W, anlage


def _schalter(u, raum):
    return {"name": f"Licht {u}", "type": "Switch", "uuidAction": u, "room": raum, "cat": "c1",
            "states": {"active": u.lower()}}


BAUSTEINE = {"A": _schalter("A", "r1"), "B": _schalter("B", "r2"), "C": _schalter("C", "r1"),
             "Z": {"name": "Audio", "type": "AudioZoneV2", "uuidAction": "Z", "room": "r1", "cat": "c1",
                   "states": {"playState": "z"}}}


@pytest.mark.parametrize("wert, erwartet", [
    ([{"id": "A", "w": 2, "h": 2}, {"id": "B"}], [{"id": "A", "w": 2, "h": 2}, {"id": "B", "w": 1, "h": 1}]),
    ([{"id": "A", "w": 1, "h": 2}], [{"id": "A", "w": 2, "h": 2}]),            # hoch ist immer auch breit
    ([{"id": "A", "w": "2", "h": "1"}], [{"id": "A", "w": 2, "h": 1}]),        # Ziffern wie bei tiles[].w
    ([{"id": "A", "w": 3, "h": 0}], [{"id": "A", "w": 1, "h": 1}]),            # ausserhalb: Standard
    ([{"id": "A"}, {"id": "A", "w": 2}], [{"id": "A", "w": 1, "h": 1}]),        # doppelt: der erste zaehlt
    ([{"id": ""}, {"w": 2}, "A", 5, None], []),
    ("A", None), (None, None), ({"id": "A"}, None),
], ids=["voll", "hoch-ist-breit", "ziffern", "ausserhalb", "doppelt", "unbrauchbar", "text", "nichts", "dict"])
def test_layout_pruefer(wert, erwartet):
    assert W._seiten_layout(wert) == erwartet


def test_picks_bestimmt_den_inhalt_das_layout_die_folge():
    lay = [{"id": "C", "w": 2, "h": 2}, {"id": "X", "w": 1, "h": 1}, {"id": "A", "w": 1, "h": 1}]
    picks, layout = W._layout_mit_picks(lay, ["A", "B", "C"])
    assert picks == ["C", "A", "B"], "Layout-Folge, was ohne Eintrag ist, hinten"
    assert layout == [{"id": "C", "w": 2, "h": 2}, {"id": "A", "w": 1, "h": 1}], "X steht nicht mehr in picks"
    assert W._layout_mit_picks(None, ["A", "B"]) == (["A", "B"], None)


def test_sanitizer_export_rundweg():
    roh = {"p": {"title": "P", "tabs": ["auswahl"], "pickTabs": [
        {"name": "Mix", "picks": ["A", "B", "C"], "byRoom": False,
         "layout": [{"id": "B", "w": 2, "h": 2}, {"id": "A"}, {"id": "Q", "w": 2}]}]}}
    sauber = W.App._sanitize_panels(roh)
    seite = sauber["p"]["pickTabs"][0]
    assert seite == {"name": "Mix", "picks": ["B", "A", "C"], "byRoom": False,
                     "layout": [{"id": "B", "w": 2, "h": 2}, {"id": "A", "w": 1, "h": 1}]}, seite
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    exp = app._panel_export(sauber["p"])["pickTabs"][0]
    assert (exp["picks"], exp["layout"], exp["byRoom"]) == (seite["picks"], seite["layout"], False), exp
    assert W.App._sanitize_panels({"p": {**sauber["p"], "pickTabs": [exp]}})["p"]["pickTabs"][0] == seite
    # ohne byRoom: Standard an, nichts gespeichert
    ohne = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["auswahl"], "pickTabs": [{"picks": ["A"]}]}})
    assert "byRoom" not in ohne["p"]["pickTabs"][0] and "layout" not in ohne["p"]["pickTabs"][0]
    assert app._panel_export(ohne["p"])["pickTabs"][0]["byRoom"] is True


def _ansicht(seite: dict) -> list:
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"a": 0, "b": 0, "c": 0, "z": 0}
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["auswahl"], "pickTabs": [seite]}})
    v = app._view_tab("auswahl", app.resolve_profile("p"))
    return [(it["id"], it.get("w", 1), it.get("h", 1)) for it in v["items"]], v.get("catTabs")


def test_ansicht_ohne_gruppierung_in_der_folge_des_layouts():
    items, marken = _ansicht({"name": "Mix", "picks": ["A", "B", "C", "Z"], "byRoom": False,
                              "layout": [{"id": "B", "w": 2, "h": 2}, {"id": "Z", "w": 1}, {"id": "A"}]})
    # Z ist nach Typ breit, das Layout macht ihn schmal; C ohne Eintrag hinten, 1 x 1
    assert items == [("B", 2, 2), ("Z", 1, 1), ("A", 1, 1), ("C", 1, 1)], items
    assert marken == []


def test_ansicht_mit_gruppierung_behaelt_die_groessen():
    items, _ = _ansicht({"name": "Mix", "picks": ["A", "B", "C"],
                         "layout": [{"id": "B", "w": 2, "h": 2}, {"id": "A"}, {"id": "C", "w": 2}]})
    # nach Raum, Raeume in der Folge ihres ersten Bausteins: r2 (B), dann r1 (A, C)
    assert items == [("B", 2, 2), ("A", 1, 1), ("C", 2, 1)], items


def test_rundweg_ohne_fehlalarm():
    """Der Konfigurator schickt zurueck, was der Export lieferte - auch byRoom
    true, das der Server als Standard nicht speichert: kein „verworfen"."""
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    for seite in ({"picks": ["A"]}, {"picks": ["A", "B"], "layout": [{"id": "B", "w": 2, "h": 2}]},
                  {"picks": ["A"], "byRoom": False}):
        gespeichert = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["auswahl"], "pickTabs": [seite]}})
        zurueck = {"p": app._panel_export(gespeichert["p"])}
        assert W.App._panels_verworfen(zurueck, W.App._sanitize_panels(zurueck)) == [], seite
