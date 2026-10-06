"""Automatisches Raster fuer Tablets, Server-Seite: die Panel-Option ui.grid
("auto") und die Zielkachel ui.tileSize als Zahl in CSS-Pixeln (der Standard
wird nicht gespeichert; die alten Stufen small/medium/large bleiben lesbar
und werden als Zahl gespeichert), was die theme-Nachricht daraus macht
(gridAuto = Zielkachel in px, 0 = festes Raster; gridGrow = Wachstum, wenn
alle Kacheln auf eine Seite passen), die Zielkachel je Geraet
(devices[name].tileTarget, Geraet vor Profil), der Vorschlag aus der
Bildschirmmeldung und das Raster, das ein Panel mit seiner Bildschirmgroesse
meldet (rc/rr)."""
import pytest

from lox import W, anlage

STRUKTUR = anlage({"S": {"name": "Licht", "type": "Switch", "uuidAction": "S", "room": "r1", "cat": "c1",
                         "states": {"active": "s"}}})


def _panels(ui: dict) -> dict:
    return {"p": {"title": "P", "tabs": ["favoriten"], "ui": ui}}


@pytest.mark.parametrize("ui, gespeichert", [
    ({"grid": "auto"}, {"grid": "auto"}),
    ({"grid": "auto", "tileSize": 200}, {"grid": "auto", "tileSize": 200}),
    ({"grid": "auto", "tileSize": "240"}, {"grid": "auto", "tileSize": 240}),
    ({"grid": "auto", "tileSize": 150.4}, {"grid": "auto", "tileSize": 150}),
    ({"grid": "auto", "tileSize": "small"}, {"grid": "auto", "tileSize": W.KACHEL_ZIEL["small"]}),
    ({"grid": "auto", "tileSize": "large"}, {"grid": "auto", "tileSize": W.KACHEL_ZIEL["large"]}),
    ({"grid": "auto", "tileSize": "medium"}, {"grid": "auto"}),
    ({"grid": "auto", "tileSize": W.KACHEL_ZIEL_STANDARD}, {"grid": "auto"}),
    ({"grid": "auto", "tileSize": "riesig"}, {"grid": "auto"}),
    ({"grid": "auto", "tileSize": 10}, {"grid": "auto", "tileSize": W.KACHEL_ZIEL_MIN}),
    ({"grid": "auto", "tileSize": 9999}, {"grid": "auto", "tileSize": W.KACHEL_ZIEL_MAX}),
    ({"grid": "auto", "tileSize": True}, {"grid": "auto"}),
    ({"grid": "Auto"}, {}), ({"grid": True}, {}), ({"grid": "3x3"}, {}),
], ids=["auto", "zahl", "ziffern", "gerundet", "klein-alt", "gross-alt", "mittel-alt", "standard", "unbekannt",
        "zu-klein", "zu-gross", "wahr-statt-zahl", "gross-geschrieben", "wahr", "fest"])
def test_zielkachel_wird_als_zahl_gespeichert(ui, gespeichert):
    ui_neu = W.App._sanitize_panels(_panels(ui))["p"].get("ui") or {}
    assert {k: v for k, v in ui_neu.items() if k in ("grid", "tileSize")} == gespeichert


def test_standard_wird_nicht_gespeichert_und_ist_kein_verlust():
    """Der Standard wird bewusst nicht gespeichert (PANEL_STANDARD), in beiden
    Schreibweisen (Zahl und alte Stufe "medium"): der Konfigurator meldet ihn
    nicht als verworfen. Eine unbekannte Stufe schon."""
    for wert in (W.KACHEL_ZIEL_STANDARD, "medium"):
        roh = _panels({"grid": "auto", "tileSize": wert})
        assert W.App._panels_verworfen(roh, W.App._sanitize_panels(roh), {}) == [], wert
    roh = _panels({"grid": "auto", "tileSize": "riesig"})
    assert W.App._panels_verworfen(roh, W.App._sanitize_panels(roh), {}) == ["P: ui.tileSize"]


def test_export_nennt_die_zielkachel_als_zahl():
    """Rundweg: der Konfigurator bekommt eine Zahl, auch aus einer Datei mit
    alter Stufe, und was er zurueckschickt, kommt unveraendert an."""
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    alt = {"title": "P", "tabs": ["favoriten"], "ui": {"grid": "auto", "tileSize": "large"}}
    exp = app._panel_export(alt)
    assert exp["ui"]["tileSize"] == W.KACHEL_ZIEL["large"] and exp["ui"]["grid"] == "auto"
    assert W.App._sanitize_panels({"p": exp})["p"]["ui"]["tileSize"] == W.KACHEL_ZIEL["large"]
    assert "tileSize" not in app._panel_export({"title": "P", "tabs": ["favoriten"], "ui": {"tileSize": "riesig"}})["ui"]


@pytest.mark.parametrize("wert, erwartet", [
    (170, 170), ("170", 170), (" 200 ", 200), (123.6, 124), ("small", W.KACHEL_ZIEL["small"]),
    ("LARGE", W.KACHEL_ZIEL["large"]), (W.KACHEL_ZIEL_MIN - 1, W.KACHEL_ZIEL_MIN),
    (W.KACHEL_ZIEL_MAX + 100, W.KACHEL_ZIEL_MAX), ("12px", None), ("", None), (None, None),
    (True, None), (float("nan"), None), ([170], None),
])
def test_pruefer_der_zielkachel(wert, erwartet):
    assert W._clean_kachelziel(wert) == erwartet


@pytest.mark.parametrize("ui, ziel", [
    ({}, 0), ({"cols": 3, "rows": 3}, 0), ({"tileSize": 200}, 0),
    ({"grid": "auto"}, W.KACHEL_ZIEL_STANDARD), ({"grid": "auto", "tileSize": 150}, 150),
    ({"grid": "auto", "tileSize": "large"}, W.KACHEL_ZIEL["large"]),
], ids=["ohne", "fest-3x3", "ziel-ohne-auto", "auto", "auto-150", "auto-gross-alt"])
def test_profil_meldet_die_zielkachel(ui, ziel):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    app.panels = W.App._sanitize_panels(_panels(ui))
    assert app.resolve_profile("p")["gridAuto"] == ziel


def test_geraet_vor_profil():
    """devices[name].tileTarget uebersteuert die Zielkachel des Profils - nur
    im Kachel-Layout "Automatisch": ein festes Raster bleibt fest."""
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    app.panels = W.App._sanitize_panels({"auto": {"title": "A", "tabs": ["favoriten"], "ui": {"grid": "auto"}},
                                         "fest": {"title": "F", "tabs": ["favoriten"], "ui": {"cols": 3}}})
    app.devices = W.App._sanitize_devices({"wand": {"tileTarget": 260}, "tab": {"scale": "off"}}, set(app.panels))
    assert app.devices["wand"] == {"auto": True, "modes": {}, "tileTarget": 260}, "ein Geraet nur mit Zielkachel bleibt"
    auto, fest = app.resolve_profile("auto"), app.resolve_profile("fest")
    assert app.effective_grid_auto(auto, "wand") == 260
    assert app.effective_grid_auto(auto, "tab") == W.KACHEL_ZIEL_STANDARD, "ohne Zielkachel am Geraet gilt das Profil"
    assert app.effective_grid_auto(auto, "") == W.KACHEL_ZIEL_STANDARD
    assert app.effective_grid_auto(fest, "wand") == 0, "festes Raster bleibt fest"
    assert app.effective_grid_auto(None, "wand") == 0


@pytest.mark.parametrize("cfg, gespeichert", [
    ({"tileTarget": 300}, 300), ({"tileTarget": "300"}, 300), ({"tileTarget": "large"}, W.KACHEL_ZIEL["large"]),
    ({"tileTarget": 5}, W.KACHEL_ZIEL_MIN), ({"tileTarget": "gross"}, None), ({"tileTarget": None}, None),
])
def test_zielkachel_je_geraet_wird_geprueft(cfg, gespeichert):
    devs = W.App._sanitize_devices({"g": {**cfg, "scale": "off"}}, set())
    assert devs["g"].get("tileTarget") == gespeichert


@pytest.mark.parametrize("screen, vorschlag", [
    ({"vw": 1280, "vh": 800, "dpr": 2}, W.KACHEL_ZIEL_STANDARD),          # 10"-Tablet in der Hand
    ({"vw": 893, "vh": 533, "dpr": 1.5}, W.KACHEL_ZIEL_STANDARD),         # Tab A9
    ({"vw": 1280, "vh": 800, "dpr": 1}, W.KACHEL_ZIEL_STANDARD),          # 10"-Panel ohne Pixeldichte: 160 -> Standard
    ({"vw": 1920, "vh": 1080, "dpr": 1}, 220),                            # FullHD-Monitor
    ({"vw": 1920, "vh": 1080}, 220),                                      # ohne dpr = 1
    ({"vw": 2560, "vh": 1600, "dpr": 1}, 300),                            # Obergrenze
    ({"vw": 3840, "vh": 2160, "dpr": 1}, 300),
    ({"vw": 480, "vh": 480, "dpr": 1}, W.KACHEL_ZIEL_STANDARD),           # 4"-Panel
    ({}, None), ({"dpr": 2}, None), (None, None),
], ids=["tablet", "taba9", "panel10", "fullhd", "ohne-dpr", "wqxga", "4k", "4zoll", "leer", "nur-dpr", "nichts"])
def test_vorschlag_aus_der_bildschirmmeldung(screen, vorschlag):
    assert W._kachel_vorschlag(screen) == vorschlag


def test_geraeteliste_traegt_den_vorschlag():
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    app.conn_info["ws1"] = {"dev": "wand", "kiosk": "", "ip": "10.0.0.5", "ts": 1.0,
                            "screen": W._clean_screen({"vw": 1920, "vh": 1080, "dpr": 1})}
    app.conn_info["ws2"] = {"dev": "neu", "kiosk": "", "ip": "10.0.0.6", "ts": 1.0}
    geraete = {d["name"]: d for d in app.device_list()["devices"]}
    assert geraete["wand"]["tileSuggest"] == 220 and geraete["neu"]["tileSuggest"] is None


def test_wachstum_kommt_vom_server():
    assert 1 < W.KACHEL_WACHSEN <= 2
    assert W.KACHEL_ZIEL_MIN < W.KACHEL_ZIEL["small"] < W.KACHEL_ZIEL_STANDARD < W.KACHEL_ZIEL["large"] < W.KACHEL_ZIEL_MAX


def test_bildschirmmeldung_traegt_das_raster():
    assert W._clean_screen({"vw": 893, "vh": 533, "rc": 5, "rr": 3}) == {"vw": 893, "vh": 533, "rc": 5, "rr": 3}
    unsinn = W._clean_screen({"rc": "5", "rr": 999, "k": True})
    assert "rc" not in unsinn and unsinn["rr"] == 50 and "k" not in unsinn
