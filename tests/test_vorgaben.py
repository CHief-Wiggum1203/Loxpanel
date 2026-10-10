"""Vorgaben (theme.json ui) fuer das Verhalten: Nacht-Abdunkelung und Aufhellen
(Schritt 5), Display aus und Auto-Neustart (Schritt 6) gelten fuer alle
Ansichten, die selbst nichts setzen (Konzept "Konfigurator neu ordnen"). Der Server prueft sie mit denselben Grenzen wie in einer Ansicht,
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


@pytest.mark.parametrize("ui, erwartet", [
    ({"dpmsOff": 120, "reloadHours": 12}, {"dpmsOff": 120, "reloadHours": 12}),
    ({"dpmsOff": 9000, "reloadHours": -1}, {"dpmsOff": 3600, "reloadHours": 0}),
    ({"dpmsOff": "120", "reloadHours": None}, {}),
])
def test_vorgaben_display_und_neustart_werden_geprueft(ui, erwartet):
    sauber = W.App._sanitize_theme_ui(ui)
    assert {k: sauber[k] for k in ("dpmsOff", "reloadHours") if k in sauber} == erwartet


def test_display_und_neustart_aus_den_vorgaben(cfg_ordner):
    """Ohne Eintrag nirgends gilt None: der Agent nimmt seine kiosk.conf, die
    Visu laedt nachts neu. Die Vorgabe gilt, wo die Ansicht nichts setzt."""
    app = W.App({"host": "", "port": 80})
    app.panels = W.App._sanitize_panels({"flur": {"title": "Flur", "tabs": ["favoriten"]},
                                         "kueche": {"title": "Küche", "tabs": ["favoriten"],
                                                    "ui": {"dpmsOff": 0, "reloadHours": 24}}})
    assert app.panel_dpms("flur") is None and app.panel_reload("flur") is None
    app._write_theme(W.App._sanitize_theme_ui({"dpmsOff": 120, "reloadHours": 12}))
    assert (app.panel_dpms("flur"), app.panel_reload("flur")) == (120, 12)
    assert (app.panel_dpms("kueche"), app.panel_reload("kueche")) == (0, 24), "die Ansicht ueberschreibt"
