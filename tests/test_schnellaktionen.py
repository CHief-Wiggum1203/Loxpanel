"""LoxOS (Fork, docs/VISION.md): Widget "Schnellaktionen" einer Bento-Seite.

Eine Zelle {"widget": "schnell", "knoepfe": [...]} traegt Knoepfe mit Symbol.
Je Knopf ein Baustein und eine Aktion: eine Taste seiner Detailseite (ueber
ihre Beschriftung, der Befehl kommt beim Rendern aus der Seite) oder - ohne
Aktion - wie ein Tipp auf seine Kachel. Geprueft: Sanitizer, was die Zelle
liefert (Name, Zusatz, Symbol, on, Befehl, Rueckfrage, gesperrt, fehlt), dass
sie ihre States ueber die Lesespur liest, und /api/bento/aktionen fuer den
Editor. Bausteine aus dem Miniserver-Nachbau (tests/lox.py).
"""
from __future__ import annotations

import asyncio
import json

import aiohttp

import konfig
from bento_format import BENTO_AKTION_MAX, BENTO_KNOEPFE_MAX, BENTO_NAME_MAX
from lox import (W, alarmanlage_baustein, anlage, jalousie_baustein, lichtsteuerung_baustein,
                 rauchmelder_baustein, visu_starten)
from verteilung import _Lesespur

SCHALTER = {"name": "Flur Licht", "type": "Switch", "uuidAction": "SW", "room": "r1", "cat": "c1",
            "details": {"jLockable": True}, "states": {"active": "sw-a", "jLocked": "sw-lock"}}


def zelle(x, y, w=1, h=1, **inhalt):
    return {"x": x, "y": y, "w": w, "h": h, **inhalt}


def _app():
    controls, states = {}, {"sw-a": 0, "sw-lock": ""}
    for f in (jalousie_baustein, lichtsteuerung_baustein, alarmanlage_baustein, rauchmelder_baustein):
        c, st = f()
        controls[c["uuidAction"]] = c
        states.update(st)
    controls["SW"] = SCHALTER
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(controls))
    app.states = states
    return app


def _knoepfe(app, knoepfe, **profil):
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["auswahl"], **profil, "pickTabs": [
        {"name": "Streifen", "picks": [], "bento": {"cells": [zelle(0, 0, 2, 1, widget="schnell", knoepfe=knoepfe)]}}]}})
    return app._view_tab("auswahl", app.resolve_profile("p"))["cells"][0]["knoepfe"]


# ---- Sanitizer -----------------------------------------------------------------

def test_sanitizer_prueft_jeden_knopf():
    roh = [{"id": "JA", "aktion": "  Ganz Ab ", "name": "  Rollo  ", "icon": "/loxlib?n=blinds.svg", "fremd": 1},
           {"id": "LV", "aktion": "x" * (BENTO_AKTION_MAX + 5), "name": "n" * (BENTO_NAME_MAX + 5)},
           {"id": "SW", "icon": "https://fremd.example/x.png"},
           {"id": "SW", "icon": "//fremd.example/x.png", "aktion": "", "name": "   "},
           {"aktion": "Auf"}, {"id": ""}, {"id": "a b"}, "JA", None]
    seite = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["auswahl"], "pickTabs": [{"name": "S", "picks": [],
        "bento": {"cells": [zelle(0, 0, widget="schnell", knoepfe=roh)]}}]}})["p"]["pickTabs"][0]["bento"]
    assert seite["cells"][0]["knoepfe"] == [
        {"id": "JA", "aktion": "Ganz Ab", "name": "Rollo", "icon": "/loxlib?n=blinds.svg"},
        {"id": "LV", "aktion": "x" * BENTO_AKTION_MAX, "name": "n" * BENTO_NAME_MAX},
        {"id": "SW"}, {"id": "SW"}]


def test_hoechstens_so_viele_knoepfe_und_beliebig_viele_zellen():
    """Anders als die anderen Widgets ohne Quelle (Uhr, Wetter) darf eine
    Seite mehrere Schnellaktionen haben; eine leere Zelle bleibt (der Editor
    legt sie an, bevor der erste Knopf dazukommt)."""
    viele = [{"id": f"K{i}"} for i in range(BENTO_KNOEPFE_MAX + 3)]
    zellen = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["auswahl"], "pickTabs": [{"name": "S", "picks": [],
        "bento": {"cells": [zelle(0, 0, widget="schnell", knoepfe=viele), zelle(1, 0, widget="schnell", knoepfe=[]),
                            zelle(2, 0, widget="schnell")]}}]}})["p"]["pickTabs"][0]["bento"]["cells"]
    assert [len(c["knoepfe"]) for c in zellen] == [BENTO_KNOEPFE_MAX, 0, 0]
    assert konfig._bento_widget("schnell") == "schnell"


# ---- Rendern -------------------------------------------------------------------

def test_aktion_der_detailseite_mit_kachel_name_und_symbol():
    app = _app()
    (k,) = _knoepfe(app, [{"id": "JA", "aktion": "Ganz Ab"}])
    kachel = app._control_item("JA")
    assert k["name"] == "Raffstore Süd" and k["zusatz"] == "Ganz Ab"
    assert k["cmd"] == {"uuid": "JA", "cmd": "FullDown"} and k["on"] is False
    assert k.get("icon") == kachel.get("icon") and k.get("iconUrl") == kachel.get("iconUrl")


def test_eigener_name_und_symbol():
    app = _app()
    lib, lox = _knoepfe(app, [{"id": "JA", "aktion": "Ganz Ab", "name": "Rollo zu", "icon": "/loxlib?n=blinds.svg"},
                              {"id": "JA", "aktion": "Auf", "icon": "IconsFilled/blinds.svg"}])
    assert lib["name"] == "Rollo zu" and "zusatz" not in lib, "der eigene Name sagt die Aktion schon"
    assert lib["iconUrl"] == "/loxlib?n=blinds.svg" and "icon" not in lib
    assert lox["iconUrl"] == app._icon_url("IconsFilled/blinds.svg")


def test_stimmung_leuchtet_und_folgt_dem_zustand():
    app = _app()
    abend, kino = _knoepfe(app, [{"id": "LV", "aktion": "Abend"}, {"id": "LV", "aktion": "Kino"}])
    assert (abend["on"], kino["on"]) == (True, False)
    assert kino["cmd"] == {"uuid": "LV", "cmd": "changeTo/3"}
    app.states["lv-am"] = "[3]"
    abend, kino = _knoepfe(app, [{"id": "LV", "aktion": "Abend"}, {"id": "LV", "aktion": "Kino"}])
    assert (abend["on"], kino["on"]) == (False, True)


def test_umschalt_taste_nimmt_den_befehl_der_seite():
    """Die Beschriftung bleibt, der Befehl haengt am Zustand (Automatik an:
    NoAuto, aus: auto) - der Knopf nimmt immer den der Seite."""
    app = _app()
    (an,) = _knoepfe(app, [{"id": "JA", "aktion": "Automatik"}])
    app.states["ja-autoActive"] = 0
    (aus,) = _knoepfe(app, [{"id": "JA", "aktion": "Automatik"}])
    assert (an["cmd"]["cmd"], an["on"]) == ("NoAuto", True)
    assert (aus["cmd"]["cmd"], aus["on"]) == ("auto", False)


def test_ohne_aktion_wie_die_kachel():
    app = _app()
    schalter, licht = _knoepfe(app, [{"id": "SW"}, {"id": "LV"}])
    assert schalter["cmd"] == app._control_item("SW")["cmd"] and "zusatz" not in schalter
    assert licht["nav"] == {"view": "control", "id": "LV"} and licht["on"] is True


def test_rueckfrage_und_pin_wie_auf_der_detailseite():
    app = _app()
    app.controls["SM"]["isSecured"] = True
    (k,) = _knoepfe(app, [{"id": "SM", "aktion": "Probealarm"}])
    assert k["confirm"] == "Alarm auslösen?" and k["secured"] is True
    assert k["cmd"] == {"uuid": "SM", "cmd": "startDrill"}


def test_gesperrt_oeffnet_die_detailseite():
    app = _app()
    app.states["sw-lock"] = json.dumps({"locked": 2, "reason": "Wartung"})
    (k,) = _knoepfe(app, [{"id": "SW"}])
    assert k["gesperrt"] is True and k["nav"] == {"view": "control", "id": "SW"} and "cmd" not in k


def test_fehlt_baustein_aktion_oder_ist_ausgeblendet():
    app = _app()
    weg, ausgeblendet, aktion = _knoepfe(app, [{"id": "GELOESCHT", "name": "Garage"}, {"id": "JA"},
                                               {"id": "LV", "aktion": "Gibt es nicht"}], hide=["JA"])
    assert weg == {"name": "Garage", "fehlt": True}
    assert ausgeblendet["fehlt"] is True
    assert aktion["fehlt"] is True and aktion["zusatz"] == "Gibt es nicht" and "cmd" not in aktion


def test_detailseite_ohne_verlinkte_objekte_halten_und_spruenge():
    """Nur feste Tasten mit Beschriftung: die verlinkten Objekte sind andere
    Bausteine, Halten/Loslassen, Formular, Sprung und Menue braucht die Seite."""
    app = _app()
    app.controls["JA"]["links"] = ["SW"]
    labels = [a["label"] for a in app._detail_aktionen("JA")]
    assert labels == ["Auf", "Ab", "Ganz Auf", "Ganz Ab", "Beschatten", "Automatik"]
    assert [a["label"] for a in app._detail_aktionen("ALM")] == ["Scharf", "Verzögert", "Bewegungsmelder"]


def test_knoepfe_lesen_ueber_die_lesespur():
    app = _app()
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["auswahl"], "pickTabs": [
        {"name": "S", "picks": [], "bento": {"cells": [zelle(0, 0, widget="schnell",
                                                             knoepfe=[{"id": "LV", "aktion": "Kino"}])]}}]}})
    lesen = _Lesespur(app.states)
    app.states = lesen
    try:
        app.render({"view": "tab", "tab": "auswahl"}, app.resolve_profile("p"))
    finally:
        app.states = lesen.quelle
    assert not lesen.alles and "lv-am" in lesen.gelesen


# ---- Editor --------------------------------------------------------------------

def test_api_aktionen():
    async def lauf():
        app = _app()
        runner, port, bc = await visu_starten(app, (("GET", "/api/bento/aktionen", W.api_bento_aktionen),))
        try:
            async with aiohttp.ClientSession() as s:
                raus = {}
                for u in ("JA", "SW", "LV", "GIBTSNICHT"):
                    async with s.get(f"http://127.0.0.1:{port}/api/bento/aktionen", params={"id": u}) as r:
                        raus[u] = (r.status, await r.json())
                return raus
        finally:
            bc.cancel()
            await runner.cleanup()
    raus = asyncio.run(lauf())
    assert raus["JA"] == (200, {"ok": True, "aktionen": ["Auf", "Ab", "Ganz Auf", "Ganz Ab", "Beschatten", "Automatik"],
                                "kachel": "nav"})
    assert raus["SW"][1]["kachel"] == "cmd" and raus["SW"][1]["aktionen"] == []
    assert raus["LV"][1]["aktionen"][:2] == ["Abend", "Hell"]
    assert raus["GIBTSNICHT"][0] == 404
