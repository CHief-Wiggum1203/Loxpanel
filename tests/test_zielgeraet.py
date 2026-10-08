"""Zielgeraet eines Profils (Punkt 15, profil.device): Name und die beim
Waehlen gemeldete Groesse. Pruefer, Sanitizer (gespeichert oder verworfen),
Export fuer den Konfigurator."""
import pytest

from lox import W, anlage

STRUKTUR = anlage({"S": {"name": "Licht", "type": "Switch", "uuidAction": "S", "room": "r1", "cat": "c1",
                         "states": {"active": "s"}}})


def _panels(device) -> dict:
    return {"p": {"title": "P", "tabs": ["favoriten"], "device": device}}


@pytest.mark.parametrize("wert, erwartet", [
    ({"name": "tablet", "vw": 1024, "vh": 600}, {"name": "tablet", "vw": 1024, "vh": 600}),
    ({"name": " wand "}, {"name": "wand"}),
    ("flur", {"name": "flur"}),
    ({"name": "x" * 80}, {"name": "x" * 60}),
    ({"name": "t", "vw": 1024.0, "vh": 600.4}, {"name": "t", "vw": 1024, "vh": 600}),
    ({"name": "t", "vw": 1024}, {"name": "t"}),                       # halbe Groesse faellt weg
    ({"name": "t", "vw": "1024", "vh": "600"}, {"name": "t"}),
    ({"name": "t", "vw": 0, "vh": 600}, {"name": "t"}),
    ({"name": "t", "vw": True, "vh": 600}, {"name": "t"}),
    ({"vw": 1024, "vh": 600}, None), ({"name": ""}, None), ("", None), (None, None), (5, None), (["t"], None),
], ids=["voll", "nur-name", "zeichenkette", "gekuerzt", "gerundet", "halb", "ziffern", "null", "wahr",
        "ohne-name", "leer-name", "leer", "nichts", "zahl", "liste"])
def test_pruefer(wert, erwartet):
    assert W._clean_zielgeraet(wert) == erwartet


def test_sanitizer_speichert_und_meldet():
    clean = W.App._sanitize_panels(_panels({"name": "tablet", "vw": 1024, "vh": 600}))
    assert clean["p"]["device"] == {"name": "tablet", "vw": 1024, "vh": 600}
    assert "device" not in W.App._sanitize_panels(_panels(None))["p"]
    roh = _panels({"vw": 1024, "vh": 600})   # ohne Namen: weg, und das wird gemeldet
    sauber = W.App._sanitize_panels(roh)
    assert "device" not in sauber["p"]
    assert W.App._panels_verworfen(roh, sauber, {}) == ["P: device.vw", "P: device.vh"]
    roh = _panels({"name": "tablet", "vw": 1024, "vh": 600})
    assert W.App._panels_verworfen(roh, W.App._sanitize_panels(roh), {}) == []


def test_export_rundweg():
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    roh = {"title": "P", "tabs": ["favoriten"], "device": "wand"}
    exp = app._panel_export(roh)
    assert exp["device"] == {"name": "wand"}
    assert W.App._sanitize_panels({"p": exp})["p"]["device"] == {"name": "wand"}
    assert "device" not in app._panel_export({"title": "P", "tabs": ["favoriten"]})
