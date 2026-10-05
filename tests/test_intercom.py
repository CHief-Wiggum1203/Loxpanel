"""Tuersprechstelle (Intercom): Bild, Klingel und Tueroeffner gab es schon. Neu
laut Loxone-Strukturdoku: 'answer' stellt die Klingel ab, und lastBellEvents
nennt die Klingeln, auf die niemand reagiert hat (JJJJMMTTHHMMSS, mit |
getrennt). Mit details.lastBellEventImages liefert der Miniserver je Klingel ein
Bild unter camimage/{uuidAction}/{Zeitstempel}; LoxPanel reicht es ueber
/bellimg weiter. Der Baustein kommt aus tests/lox.py (intercom_baustein)."""
import asyncio
from datetime import date

import aiohttp
import pytest
from aiohttp import web

from lox import KLINGELN, Miniserver, W, anlage, bloecke, intercom_baustein, neue_app, serve

NEUESTE_ZUERST = sorted(KLINGELN, reverse=True)


def _app(**kw) -> W.App:
    control, states = intercom_baustein(**kw)
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"IC": control}))
    app.states = states
    return app


def _zeilen(view: dict) -> list[list[str]]:
    return [[c["label"] for c in b["cells"]] for b in bloecke(view, "row")]


def test_verpasste_klingeln():
    v = _app().render({"view": "control", "id": "IC"})
    tuer, klingel = bloecke(v, "row")
    assert [c["label"] for c in tuer["cells"]] == ["Tür öffnen"]
    assert klingel == {"k": "row", "id": "klingel", "cells": [
        {"label": "3 verpasste Klingeln", "nav": {"view": "bells", "id": "IC"}}]}
    assert _zeilen(_app(klingeln=KLINGELN[:1]).render({"view": "control", "id": "IC"}))[1] == [
        "1 verpasste Klingel"]
    assert _zeilen(_app(klingeln=()).render({"view": "control", "id": "IC"})) == [["Tür öffnen"]]


def test_klingel_abstellen():
    v = _app(bell=1).render({"view": "control", "id": "IC"})
    klingel = bloecke(v, "row")[1]
    assert klingel["cells"][0] == {"label": "Klingel abstellen", "cmd": {"uuid": "IC", "cmd": "answer"}}
    assert [c["label"] for c in klingel["cells"]] == ["Klingel abstellen", "3 verpasste Klingeln"]


def test_kamera_pane_ohne_klingelzeile():
    """Die Kamera-Pane zeigt die erste Knopfzeile (Tueroeffner); die Zeile mit
    Klingel und Verlauf gehoert nur auf die Detailseite."""
    rows = [b for b in _app(bell=1).intercom_blocks("IC") if b["k"] == "row"]
    assert [[c["label"] for c in r["cells"]] for r in rows] == [["Tür öffnen"]]


def test_verlauf_mit_bildern():
    v = _app().render({"view": "bells", "id": "IC"})
    gal, = bloecke(v, "gallery")
    assert [i["src"] for i in gal["items"]] == [f"/bellimg?id=IC&ts={ts}" for ts in NEUESTE_ZUERST]
    assert [i["label"] for i in gal["items"]] == [W.App._bell_text(ts) for ts in NEUESTE_ZUERST]


def test_verlauf_ohne_bilder():
    v = _app(bilder=False).render({"view": "bells", "id": "IC"})
    assert not bloecke(v, "gallery")
    assert [b["text"] for b in bloecke(v, "status")] == [W.App._bell_text(ts) for ts in NEUESTE_ZUERST]


def test_verlauf_leer():
    v = _app(klingeln=()).render({"view": "bells", "id": "IC"})
    assert [b["text"] for b in bloecke(v, "status")] == ["Keine verpassten Klingeln"]


def test_unsinn_in_lastbellevents():
    app = _app(klingeln=("20261001074904", "", "x", "2026100107490", "20261001074904", " 20261002181530 "))
    assert app._bell_events(app.controls["IC"]) == ["20261002181530", "20261001074904"]


@pytest.mark.parametrize("ts, text", [
    ("20261003091200", "Heute 09:12"), ("20261002181530", "Gestern 18:15"),
    ("20260928070000", "Mo 07:00"), ("20260926070000", "26.09. 07:00"),
    ("20251231235900", "31.12.2025 23:59"), ("20261399000000", "20261399000000")])
def test_klingel_zeitpunkt(ts, text):
    assert W.App._bell_text(ts, date(2026, 10, 3)) == text      # ein Samstag


def test_bild_vom_miniserver(miniserver_http):
    """/bellimg holt das Bild per camimage mit Token, je Zeitstempel einmal."""
    async def lauf():
        ms = await Miniserver().start()
        ms.bilder[("IC", KLINGELN[0])] = b"\xff\xd8 Bild 1"
        app = neue_app(ms)
        control, states = intercom_baustein()
        app._apply_structure(anlage({"IC": control}))
        app.states = states
        ui = web.Application()
        ui["app"] = app
        ui.router.add_get("/bellimg", W.bellimg_handler)
        runner, port = await serve(ui)
        try:
            async with aiohttp.ClientSession() as s:
                async def hole(query):
                    async with s.get(f"http://127.0.0.1:{port}/bellimg?{query}") as r:
                        return r.status, await r.read(), r.headers.get("Content-Type")
                assert await hole(f"id=IC&ts={KLINGELN[0]}") == (200, b"\xff\xd8 Bild 1", "image/jpeg")
                assert await hole(f"id=IC&ts={KLINGELN[0]}") == (200, b"\xff\xd8 Bild 1", "image/jpeg")
                assert ms.bild_abrufe == [f"IC/{KLINGELN[0]}"]              # das zweite Mal aus dem Speicher
                assert (await hole(f"id=IC&ts={KLINGELN[1]}"))[0] == 404     # der Miniserver hat keins
                assert (await hole("id=IC&ts=../../sps/io/IC/pulse"))[0] == 400
                assert (await hole(f"id=NIX&ts={KLINGELN[0]}"))[0] == 400
                assert ms.io == []                                          # kein Befehl ausgeloest
        finally:
            await runner.cleanup()
            await app.icon_session.close()
            await ms.stop()
    asyncio.run(lauf())


def test_bild_zwischenspeicher_begrenzt(miniserver_http, monkeypatch):
    monkeypatch.setattr(W, "BELL_CACHE_MAX", 2)

    async def lauf():
        ms = await Miniserver().start()
        for ts in KLINGELN:
            ms.bilder[("IC", ts)] = ts.encode()
        app = neue_app(ms)
        try:
            for ts in KLINGELN:
                assert await app.fetch_bell_image("IC", ts) == (ts.encode(), "image/jpeg")
            assert list(app.bell_cache) == [f"camimage/IC/{ts}" for ts in KLINGELN[1:]]
        finally:
            await app.icon_session.close()
            await ms.stop()
    asyncio.run(lauf())


def test_status_teilweise():
    """Im Browser fehlt SIP weiter; die native App ergaenzt es ueber ihre Bruecke."""
    assert {t["type"]: t["status"] for t in _app().types_overview()["types"]}["Intercom"] == "partial"
