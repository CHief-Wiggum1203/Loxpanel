"""Stiller Verlust beim Speichern: was _sanitize_panels nicht uebernimmt,
meldet der Server (Antwort "verworfen", Konfigurator zeigt es an). Gemeldet
wird nur, was einen Inhalt hatte - leere Werte, Standardwerte und bloss
begrenzte Werte nicht."""
import asyncio
import json

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from lox import ROOT, W, anlage


def _meldung(panels: dict, namen: dict | None = None) -> list[str]:
    return W.App._panels_verworfen(panels, W.App._sanitize_panels(panels), namen)


def test_unbekannt_und_ungueltig_wird_gemeldet():
    roh = {"wz": {"title": "Wohnzimmer", "tabs": ["favoriten", "quatsch"],
                  "ui": {"cols": "3", "neuOption": 5, "iconSize": 30},
                  "tiles": {"U1": {"bg": "#123456", "blinken": True}},
                  "pickTabs": [{"name": "Seite", "picks": ["U1"], "icon": "https://fremd.example/bild"}],
                  "zusatz": {"a": 1}}}
    assert sorted(_meldung(roh, {"U1": "Licht Küche"})) == sorted([
        "Wohnzimmer: tabs: quatsch",
        "Wohnzimmer: ui.cols",
        "Wohnzimmer: ui.neuOption",
        "Wohnzimmer: tiles.Licht Küche.blinken",
        "Wohnzimmer: pickTabs.1.icon",
        "Wohnzimmer: zusatz.a"])


def test_panel_mit_ungueltiger_id():
    assert _meldung({"_intern": {"tabs": ["favoriten"]}, "ok": {"tabs": ["favoriten"]}}) == ["Panel „_intern“"]


def test_leer_standard_und_begrenzt_ist_kein_verlust():
    roh = {"p": {"title": "  ", "tabs": ["favoriten"], "rooms": [], "hide": [], "picks": [],
                 "pickName": "", "roomCats": [], "states": {}, "tiles": {"U1": {"chartStyle": "trend"}},
                 "ui": {"split": True, "catFilter": False, "fill": False, "bold": False,
                        "iconSize": 200, "nudgeX": -99, "font": "x" * 300, "overlay": {}}}}
    assert _meldung(roh) == []


def test_beispielkonfiguration_und_zweiter_durchlauf():
    doc = json.loads((ROOT / "config" / "panels.json.example").read_text(encoding="utf-8"))
    roh = {k: v for k, v in (doc.get("panels") or doc).items() if not k.startswith("_")}
    assert roh and _meldung(roh) == []
    sauber = W.App._sanitize_panels(roh)
    assert _meldung(sauber) == []


def test_speichern_antwortet_mit_verworfen():
    """/api/panels speichert das Uebernommene und nennt den Rest; die Datei
    schreibt hier ein Stellvertreter (kein Test darf config/ veraendern)."""
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage({"U1": {"name": "Licht Küche", "type": "Switch", "uuidAction": "U1",
                                            "room": "r1", "cat": "c1", "states": {"active": "s1"}}}))
        geschrieben = []
        app._write_panels = geschrieben.append
        ui = web.Application()
        ui["app"] = app
        ui.router.add_post("/api/panels", W.api_save_panels)
        async with TestClient(TestServer(ui)) as cl:
            r = await cl.post("/api/panels", json={"panels": {
                "wz": {"title": "Wohnzimmer", "tabs": ["favoriten"], "ui": {"neuOption": 1},
                       "tiles": {"U1": {"bold": True, "blinken": True}}}}})
            j = await r.json()
        assert j["ok"] is True and j["count"] == 1
        assert j["verworfen"] == ["Wohnzimmer: ui.neuOption", "Wohnzimmer: tiles.Licht Küche.blinken"]
        assert geschrieben == [{"wz": {"title": "Wohnzimmer", "tabs": ["favoriten"], "rooms": [], "cats": [],
                                       "tiles": {"U1": {"bold": True}}}}]
    asyncio.run(lauf())
