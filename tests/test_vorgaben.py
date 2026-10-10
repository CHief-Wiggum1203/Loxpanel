"""Vorgaben (theme.json ui) fuer den Nachtmodus: Abdunkelung und Aufhellen gelten
fuer alle Ansichten, die selbst nichts setzen (Konzept "Konfigurator neu ordnen",
Schritt 5). Der Server prueft sie mit denselben Grenzen wie in einer Ansicht,
schreibt sie in theme.json, und panel_night() nimmt sie; der Standard ohne jede
Einstellung steht einmal in NACHT_STANDARD und geht ueber /api/meta an den
Konfigurator. Die Bedienung im Browser prueft tests/browser/test_vorgaben_browser.py."""
import pytest

from lox import W


@pytest.mark.parametrize("ui, erwartet", [
    ({"nightDim": 40, "nightWake": 5}, {"nightDim": 40, "nightWake": 5}),
    ({"nightDim": 120, "nightWake": -3}, {"nightDim": 90, "nightWake": 0}),
    ({"nightDim": "40", "nightWake": None}, {}),
])
def test_vorgaben_nacht_werden_geprueft(ui, erwartet):
    sauber = W.App._sanitize_theme_ui(ui)
    assert {k: sauber[k] for k in ("nightDim", "nightWake") if k in sauber} == erwartet


def test_vorgabe_gilt_wo_die_ansicht_nichts_setzt(cfg_ordner):
    app = W.App({"host": "", "port": 80})
    app.panels = W.App._sanitize_panels({"flur": {"title": "Flur", "tabs": ["favoriten"]},
                                         "kueche": {"title": "Küche", "tabs": ["favoriten"],
                                                    "ui": {"nightDim": 10}}})
    std = W.NACHT_STANDARD
    assert app.panel_night("flur") == {"dim": std["nightDim"], "wake": std["nightWake"]}
    app._write_theme(W.App._sanitize_theme_ui({"nightDim": 40, "nightWake": 5}))
    assert app.theme["ui"]["nightDim"] == 40
    assert app.panel_night("flur") == {"dim": 40, "wake": 5}
    assert app.panel_night("kueche") == {"dim": 10, "wake": 5}
    app._write_theme(W.App._sanitize_theme_ui({}))     # Feld geleert: wieder der Standard
    assert app.panel_night("flur") == {"dim": std["nightDim"], "wake": std["nightWake"]}
    assert set(W.NACHT_STANDARD) <= set(W.THEME_UI_KEYS), "sonst schreibt _write_theme sie nicht"
