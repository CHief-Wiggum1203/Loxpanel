"""Lichtsteuerung (LightControllerV2) nach der Loxone-Strukturdoku: frueher
nur die Liste der Stimmungen. Jetzt die Lieblingsstimmungen zuerst
(favoriteMoods), die weiteren darunter (additionalMoods), vorige/naechste
Stimmung (minus, plus), die Master-Helligkeit (details.masterValue) und jeder
Lichtkreis: Dimmer und Farblicht als Regler mit Namen, Schaltkreis als
Zelle. Befehle gehen an den Lichtkreis selbst. Baustein:
lichtsteuerung_baustein() in tests/lox.py."""
from lox import W, anlage, bloecke, lichtsteuerung_baustein


def _seite(**kw) -> dict:
    control, states = lichtsteuerung_baustein(**kw)
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"LV": control}))
    app.states = states
    return app.render({"view": "control", "id": "LV"})


def _reihen(v) -> list:
    return [[(z.get("label") or z.get("icon"), (z.get("cmd") or {}).get("cmd"), z.get("on"))
             for z in r["cells"]] for r in bloecke(v, "row")]


def test_stimmungen_favoriten_zuerst():
    v = _seite()
    reihen = _reihen(v)
    assert reihen[0] == [("Abend", "changeTo/2", True), ("Hell", "changeTo/1", False), ("Aus", "changeTo/778", False)]
    assert reihen[1] == [("prev", "minus", None), ("next", "plus", None)]
    assert reihen[2] == [("Putzen", "changeTo/4", False), ("Kino", "changeTo/3", False)]
    assert [b["text"] for b in bloecke(v, "head")] == ["Weitere Stimmungen", "Lichtkreise"]
    assert bloecke(v, "status")[0]["text"] == "Abend"


def test_ohne_favoriten_alle_stimmungen():
    reihen = _reihen(_seite(favoriten=False))
    assert [z[0] for z in reihen[0]] == ["Hell", "Abend", "Kino", "Putzen", "Aus"]
    assert "Weitere Stimmungen" not in [b["text"] for b in bloecke(_seite(favoriten=False), "head")]


def test_helligkeit_und_lichtkreise():
    regler = bloecke(_seite(), "slider")
    assert [(r["label"], r["value"], r["cmd"]) for r in regler] == [
        ("Helligkeit", 70, {"uuid": "LV-M", "tmpl": "{v}"}),
        ("Esstisch", 40, {"uuid": "LV-1", "tmpl": "{v}"}),
        ("Stripe", 55, {"uuid": "LV-2", "tmpl": "temp({v},3000)"})]


def test_farblicht_rgb_behaelt_farbe():
    regler = bloecke(_seite(**{"lv-2c": "hsv(120,80,30)"}), "slider")
    assert regler[-1]["value"] == 30 and regler[-1]["cmd"]["tmpl"] == "hsv(120,80,{v})"


def test_schaltkreis():
    assert _reihen(_seite())[-1] == [("Steckdose", "on", False)]
    assert _reihen(_seite(**{"lv-3a": 1}))[-1] == [("Steckdose", "off", True)]
