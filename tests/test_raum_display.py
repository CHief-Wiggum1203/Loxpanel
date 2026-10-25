"""LoxOS (Fork, docs/VISION.md): Raum-Display-Zelle einer Bento-Seite.

Eine Zelle "ansicht:<Kennung>" zeigt eine ganze gespeicherte Ansicht als
eigene, eingebettete Visu (?panel=<Kennung>&eingebettet=1). Geprueft: Format
und Sanitizer, was _view_bento fuer die Zelle liefert (Name, Format des
Zielgeraets), und am echten Server, dass die eingebettete Visu kein Geraet
ist - kein Name, kein Kopplungscode, nicht in der Geraeteliste, keine
Klingel, kein Wecker, keine Nacht, keine Pushes an Ansicht oder Geraet ausser
dem Neuladen, Masse wie das Zielgeraet ihrer Ansicht.
"""
from __future__ import annotations

import asyncio
import json

import aiohttp

import konfig
from bento_format import bento_ansicht_widget
from lox import W, anlage, intercom_baustein, raum_anlage, visu_starten, wecker_baustein

ZIEL = {"name": "kueche-panel", "vw": 480, "vh": 480}


def zelle(x, y, w=1, h=1, **inhalt):
    return {"x": x, "y": y, "w": w, "h": h, **inhalt}


def _profile(zellen, kueche=None):
    """Streifen mit einer Bento-Seite, dazu die Raum-Ansicht kueche."""
    return {"streifen": {"title": "Streifen", "tabs": ["auswahl"],
                         "pickTabs": [{"name": "Start", "picks": [], "bento": {"cols": 6, "rows": 2, "cells": zellen}}]},
            "kueche": {"title": "Küche", "tabs": ["favoriten"], **(kueche if kueche is not None else {"device": ZIEL})}}


def _app(panels, struktur=None, states=None):
    if struktur is None:
        struktur, states = raum_anlage()
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    app.states = dict(states or {})
    app.panels = W.App._sanitize_panels(panels)
    return app


def _zellen(app, pid="streifen"):
    return app._view_tab("auswahl", app.resolve_profile(pid))["cells"]


# ---- Format und Sanitizer ------------------------------------------------------

def test_widget_kennung():
    assert bento_ansicht_widget("ansicht:kueche") == "ansicht:kueche"
    assert bento_ansicht_widget("ansicht:wohn-zimmer-2") == "ansicht:wohn-zimmer-2"
    for falsch in ("ansicht:", "ansicht:_global", "ansicht:a b", "ansicht:a\tb", "ansicht:a\x00",
                   "kueche", "Ansicht:kueche", None, 3, ["ansicht:kueche"]):
        assert bento_ansicht_widget(falsch) == "", falsch


def test_sanitizer_behaelt_die_zelle_und_jede_ansicht_nur_einmal():
    """Wie jedes Widget mit Quelle: dieselbe Ansicht steht je Seite einmal,
    verschiedene nebeneinander (drei Raeume auf einem Streifen)."""
    panels = W.App._sanitize_panels(_profile([zelle(0, 0, 2, 2, widget="ansicht:kueche"),
                                              zelle(2, 0, 2, 2, widget="ansicht:kueche"),
                                              zelle(4, 0, 2, 2, widget="ansicht:bad"),
                                              zelle(0, 0, 1, 1, widget="ansicht:_x")]))
    zellen = panels["streifen"]["pickTabs"][0]["bento"]["cells"]
    assert [c["widget"] for c in zellen] == ["ansicht:kueche", "ansicht:bad"]
    assert konfig._bento_widget("ansicht:kueche") == "ansicht:kueche"


# ---- Rendern ------------------------------------------------------------------

def test_zelle_traegt_kennung_namen_und_format_des_zielgeraets():
    app = _app(_profile([zelle(0, 0, 2, 2, widget="ansicht:kueche")]))
    (z,) = _zellen(app)
    assert z["widget"] == "ansicht:kueche"
    assert z["ansicht"] == {"id": "kueche", "name": "Küche", "format": {"vw": 480, "vh": 480}}


def test_ohne_zielgeraet_mit_groesse_kein_format():
    for kueche in ({}, {"device": {"name": "kueche-panel"}}):
        app = _app(_profile([zelle(0, 0, 2, 2, widget="ansicht:kueche")], kueche=kueche))
        (z,) = _zellen(app)
        assert z["ansicht"] == {"id": "kueche", "name": "Küche"}, kueche


def test_unbekannte_ansicht_und_die_eigene():
    app = _app(_profile([zelle(0, 0, 2, 2, widget="ansicht:geloescht"),
                         zelle(2, 0, 2, 2, widget="ansicht:streifen")]))
    weg, selbst = _zellen(app)
    assert "ansicht" not in weg and weg["widget"] == "ansicht:geloescht"
    assert selbst["ansicht"]["selbst"] is True


# ---- Am echten Server: die eingebettete Visu ist kein Geraet --------------------

def _klingel_app():
    ic, ic_st = intercom_baustein()
    wk, wk_st = wecker_baustein()
    app = _app(_profile([zelle(0, 0, 2, 2, widget="ansicht:kueche")]), anlage({"IC": ic, "WK": wk}),
               {**ic_st, **wk_st})
    app.devices = W.App._sanitize_devices({"kueche-panel": {"scale": 1.5, "tileTarget": 180},
                                           "streifen": {"panel": "streifen"}}, set(app.panels))
    return app


async def _alle(ws, frist: float) -> list:
    """Alles, was binnen frist ankommt."""
    loop = asyncio.get_running_loop()
    ende, raus = loop.time() + frist, []
    while (rest := ende - loop.time()) > 0:
        try:
            raus.append(await asyncio.wait_for(ws.receive_json(), rest))
        except asyncio.TimeoutError:
            break
    return raus


ROUTEN = (("POST", "/api/device/name", W.api_device_name), ("POST", "/api/notify", W.api_notify),
          ("POST", "/api/reload", W.api_reload), ("POST", "/api/goto", W.api_goto),
          ("POST", "/api/testtone", W.api_testtone))


def test_eingebettete_visu_ist_kein_geraet():
    async def lauf():
        app = _klingel_app()
        app.display_drivers = lambda *a, **k: asyncio.sleep(0, [])
        runner, port, bc = await visu_starten(app, ROUTEN)
        try:
            async with aiohttp.ClientSession() as s:
                # Der localStorage der Visu um die Zelle nennt den Streifen: auch mit
                # device= in der Adresse ist die Zelle kein Geraet
                zelle_ws = await s.ws_connect(
                    f"http://127.0.0.1:{port}/ws?panel=kueche&eingebettet=1&device=streifen")
                start = await _alle(zelle_ws, 1.0)
                info = next(i for i in app.conn_info.values() if i.get("eingebettet"))
                liste = app.device_list()
                await zelle_ws.close()
                return start, info, liste
        finally:
            bc.cancel()
            await runner.cleanup()
    start, info, liste = asyncio.run(lauf())
    arten = [m.get("t") for m in start]
    assert "kopplung" not in arten, "kein Kopplungscode, keine Karte 'Dieses Geraet einrichten'"
    assert info["dev"] == "" and "code" not in info
    assert liste["anonymous"] == [] and "streifen" not in {d["name"] for d in liste["devices"] if d["online"]}
    theme = next(m for m in start if m.get("t") == "theme")
    view = next(m for m in start if m.get("t") == "view")
    assert view["route"]["tab"] == "favoriten", "die Ansicht der Zelle, nicht die des Streifens"
    assert theme["dpmsOff"] == 0 and theme["night"] == {"on": False}
    assert theme["presence"] is False and theme["ruhe"] is False and theme["agent"] is False
    assert theme["scale"] == 1.5 and theme["gridAuto"] == 0, "Skalierung wie am Zielgeraet"


def test_klingel_wecker_nacht_und_pushes_nur_an_die_visu_um_die_zelle():
    async def lauf():
        app = _klingel_app()
        app.display_drivers = lambda *a, **k: asyncio.sleep(0, [])
        runner, port, bc = await visu_starten(app, ROUTEN)
        try:
            async with aiohttp.ClientSession() as s:
                streifen = await s.ws_connect(f"http://127.0.0.1:{port}/ws?panel=streifen&device=streifen")
                zelle_ws = await s.ws_connect(f"http://127.0.0.1:{port}/ws?panel=kueche&eingebettet=1")
                await _alle(streifen, 0.5)
                await _alle(zelle_ws, 0.5)
                app._pending_ring = "IC"
                app._pending_alarm.append({"id": "WK", "on": True})
                app._night_on = not app._night_now()   # der naechste Takt meldet einen Wechsel
                url = f"http://127.0.0.1:{port}/api"
                for pfad, d in (("/notify", {"text": "Hallo"}), ("/goto", {"tab": "zentral"}),
                                ("/testtone", {}), ("/device/name", {"ip": "127.0.0.1", "name": "neu"})):
                    async with s.post(url + pfad, json=d) as r:
                        await r.read()
                bei_streifen = [m.get("t") for m in await _alle(streifen, 1.5)]
                bei_zelle = [m.get("t") for m in await _alle(zelle_ws, 0.5)]
                async with s.post(url + "/reload", json={"panel": "kueche"}) as r:
                    neu_geladen = (await r.json())["reloaded"]
                nach_reload = [m.get("t") for m in await _alle(zelle_ws, 0.5)]
                await streifen.close()
                await zelle_ws.close()
                return bei_streifen, bei_zelle, neu_geladen, nach_reload
        finally:
            bc.cancel()
            await runner.cleanup()
    bei_streifen, bei_zelle, neu_geladen, nach_reload = asyncio.run(lauf())
    for t in ("ring", "alarm", "night", "notify", "goto", "testtone"):
        assert t in bei_streifen, t
        assert t not in bei_zelle, t
    assert "setdevice" not in bei_zelle, "der Name landete im localStorage des Streifens"
    assert neu_geladen == 1 and nach_reload == ["reload"], "Ansicht gespeichert: die Zelle laedt neu"


def test_geraete_speichern_schickt_der_zelle_die_masse_des_zielgeraets(cfg_ordner):
    (cfg_ordner / "panels.json").write_text(json.dumps(
        {"panels": _profile([zelle(0, 0, 2, 2, widget="ansicht:kueche")]),
         "devices": {"kueche-panel": {"scale": 1.5}}}), encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        struktur, states = raum_anlage()
        app._apply_structure(struktur)
        app.states = dict(states)
        runner, port, bc = await visu_starten(app, (("POST", "/api/devices", W.api_save_devices),))
        try:
            async with aiohttp.ClientSession() as s:
                zelle_ws = await s.ws_connect(f"http://127.0.0.1:{port}/ws?panel=kueche&eingebettet=1")
                await _alle(zelle_ws, 0.5)
                async with s.post(f"http://127.0.0.1:{port}/api/devices",
                                  json={"devices": {"kueche-panel": {"scale": 2}}}) as r:
                    assert (await r.json())["ok"]
                m = [x for x in await _alle(zelle_ws, 1.0) if x.get("t") in ("scale", "ruhe")]
                await zelle_ws.close()
                return m
        finally:
            bc.cancel()
            await runner.cleanup()
    m = asyncio.run(lauf())
    assert {"t": "scale", "scale": 2} in m and {"t": "ruhe", "ruhe": False} in m
