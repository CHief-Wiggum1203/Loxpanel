"""Automatisches Raster fuer Tablets, Server-Seite: die Panel-Option ui.grid
("auto") und die Kachelgroesse ui.tileSize in Stufen (small/large; mittel ist
der Standard und wird nicht gespeichert), was die theme-Nachricht daraus macht
(gridAuto = Zielgroesse einer Kachel in px, 0 = festes Raster) und das Raster,
das ein Panel mit seiner Bildschirmgroesse meldet (rc/rr)."""
import pytest

from lox import W, anlage

STRUKTUR = anlage({"S": {"name": "Licht", "type": "Switch", "uuidAction": "S", "room": "r1", "cat": "c1",
                         "states": {"active": "s"}}})


def _panels(ui: dict) -> dict:
    return {"p": {"title": "P", "tabs": ["favoriten"], "ui": ui}}


@pytest.mark.parametrize("ui, gespeichert", [
    ({"grid": "auto"}, {"grid": "auto"}),
    ({"grid": "auto", "tileSize": "small"}, {"grid": "auto", "tileSize": "small"}),
    ({"grid": "auto", "tileSize": "large"}, {"grid": "auto", "tileSize": "large"}),
    ({"grid": "auto", "tileSize": "medium"}, {"grid": "auto"}),
    ({"grid": "auto", "tileSize": "riesig"}, {"grid": "auto"}),
    ({"grid": "auto", "tileSize": 170}, {"grid": "auto"}),
    ({"grid": "Auto"}, {}), ({"grid": True}, {}), ({"grid": "3x3"}, {}),
], ids=["auto", "klein", "gross", "mittel", "unbekannt", "zahl", "gross-geschrieben", "wahr", "fest"])
def test_nur_auto_und_die_stufen_werden_gespeichert(ui, gespeichert):
    ui_neu = W.App._sanitize_panels(_panels(ui))["p"].get("ui") or {}
    assert {k: v for k, v in ui_neu.items() if k in ("grid", "tileSize")} == gespeichert


def test_mittel_ist_der_standard_und_kein_verlust():
    """Mittel wird bewusst nicht gespeichert (PANEL_STANDARD): der Konfigurator
    meldet es nicht als verworfen. Eine unbekannte Stufe schon."""
    roh = _panels({"grid": "auto", "tileSize": "medium"})
    assert W.App._panels_verworfen(roh, W.App._sanitize_panels(roh), {}) == []
    roh = _panels({"grid": "auto", "tileSize": "riesig"})
    assert W.App._panels_verworfen(roh, W.App._sanitize_panels(roh), {}) == ["P: ui.tileSize"]


@pytest.mark.parametrize("ui, stufe", [
    ({}, None), ({"cols": 3, "rows": 3}, None), ({"tileSize": "large"}, None),
    ({"grid": "auto"}, "medium"), ({"grid": "auto", "tileSize": "small"}, "small"),
    ({"grid": "auto", "tileSize": "large"}, "large"),
], ids=["ohne", "fest-3x3", "stufe-ohne-auto", "auto", "auto-klein", "auto-gross"])
def test_profil_meldet_die_zielgroesse(ui, stufe):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    app.panels = W.App._sanitize_panels(_panels(ui))
    assert app.resolve_profile("p")["gridAuto"] == (W.KACHEL_ZIEL[stufe] if stufe else 0)


def test_stufen_werden_groesser():
    assert W.KACHEL_ZIEL["small"] < W.KACHEL_ZIEL["medium"] < W.KACHEL_ZIEL["large"]


def test_bildschirmmeldung_traegt_das_raster():
    assert W._clean_screen({"vw": 893, "vh": 533, "rc": 5, "rr": 3}) == {"vw": 893, "vh": 533, "rc": 5, "rr": 3}
    unsinn = W._clean_screen({"rc": "5", "rr": 999, "k": True})
    assert "rc" not in unsinn and unsinn["rr"] == 50 and "k" not in unsinn
