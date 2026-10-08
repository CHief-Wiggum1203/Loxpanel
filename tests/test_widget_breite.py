"""Widget-Breite im automatischen Raster, Server-Seite: ui.paneCols nennt,
wie viele Kachelspalten (hochkant Kachelzeilen) das Widget belegt, 1 bis
PANE_SPALTEN_MAX; 0 oder nichts = Automatik mit dem Anteil PANE_ANTEIL. Der
Prüfer, was der Sanitizer speichert und als verworfen meldet, der Export für
den Konfigurator, das Profil und die Angaben in /api/meta."""
import pytest

from lox import W, anlage

STRUKTUR = anlage({"S": {"name": "Licht", "type": "Switch", "uuidAction": "S", "room": "r1", "cat": "c1",
                         "states": {"active": "s"}}})


def _panels(ui: dict) -> dict:
    return {"p": {"title": "P", "tabs": ["favoriten"], "ui": ui}}


@pytest.mark.parametrize("wert, erwartet", [
    (1, 1), (2, 2), (3, 3), ("2", 2), (" 3 ", 3), (2.0, 2), (2.7, 2),
    (W.PANE_SPALTEN_MAX + 1, W.PANE_SPALTEN_MAX), (99, W.PANE_SPALTEN_MAX),
    (0, None), (-1, None), ("0", None), ("", None), ("zwei", None), ("2px", None),
    (None, None), (True, None), (False, None), (float("nan"), None), ([2], None),
], ids=["eins", "zwei", "drei", "ziffer", "ziffer-rand", "zwei-float", "abgerundet", "zu-gross", "viel-zu-gross",
        "null", "negativ", "null-ziffer", "leer", "wort", "einheit", "nichts", "wahr", "falsch", "nan", "liste"])
def test_pruefer_der_widget_breite(wert, erwartet):
    assert W._clean_pane_spalten(wert) == erwartet


def test_grenzen_vom_server():
    assert 0 < W.PANE_ANTEIL < 1 and W.PANE_SPALTEN_MAX >= 1


@pytest.mark.parametrize("ui, gespeichert", [
    ({"grid": "auto", "paneCols": 2}, {"grid": "auto", "paneCols": 2}),
    ({"grid": "auto", "paneCols": "3"}, {"grid": "auto", "paneCols": 3}),
    ({"grid": "auto", "paneCols": 0}, {"grid": "auto"}),
    ({"grid": "auto", "paneCols": 7}, {"grid": "auto", "paneCols": W.PANE_SPALTEN_MAX}),
    ({"grid": "auto", "paneCols": "breit"}, {"grid": "auto"}),
    ({"paneCols": 2}, {"paneCols": 2}),   # ohne "auto" gespeichert, wirkt erst mit dem automatischen Raster
], ids=["zwei", "ziffer", "automatik", "begrenzt", "unbekannt", "ohne-auto"])
def test_sanitizer_speichert_die_spaltenzahl(ui, gespeichert):
    ui_neu = W.App._sanitize_panels(_panels(ui))["p"].get("ui") or {}
    assert {k: v for k, v in ui_neu.items() if k in ("grid", "paneCols")} == gespeichert


def test_automatik_ist_standard_und_kein_verlust():
    """0 = Automatik wird nicht gespeichert (PANEL_STANDARD) und nicht als
    verworfen gemeldet; ein unbrauchbarer Wert schon."""
    roh = _panels({"grid": "auto", "paneCols": 0})
    assert W.App._panels_verworfen(roh, W.App._sanitize_panels(roh), {}) == []
    roh = _panels({"grid": "auto", "paneCols": "breit"})
    assert W.App._panels_verworfen(roh, W.App._sanitize_panels(roh), {}) == ["P: ui.paneCols"]


def test_export_und_profil():
    """Rundweg: der Konfigurator bekommt den Wert, was er zurueckschickt kommt
    an, und das Profil nennt ihn als paneCols (0 = Automatik)."""
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    roh = {"title": "P", "tabs": ["favoriten"], "ui": {"grid": "auto", "paneCols": 2}}
    exp = app._panel_export(roh)
    assert exp["ui"]["paneCols"] == 2
    assert W.App._sanitize_panels({"p": exp})["p"]["ui"]["paneCols"] == 2
    app.panels = W.App._sanitize_panels({"p": roh, "q": {"title": "Q", "tabs": ["favoriten"], "ui": {"grid": "auto"}}})
    assert app.resolve_profile("p")["paneCols"] == 2
    assert app.resolve_profile("q")["paneCols"] == 0
    assert app.resolve_profile(None)["paneCols"] == 0


def test_meta_nennt_grenze_und_anteil():
    """Der Konfigurator baut den Regler aus /api/meta, nicht aus eigenen Zahlen."""
    import asyncio

    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(STRUKTUR)
        ui = web.Application()
        ui["app"] = app
        ui.router.add_get("/api/meta", W.api_meta)
        async with TestClient(TestServer(ui)) as cl:
            r = await cl.get("/api/meta")
            return (await r.json())["paneCols"]
    assert asyncio.run(lauf()) == {"max": W.PANE_SPALTEN_MAX, "anteil": W.PANE_ANTEIL}
