"""LoxOS (Fork, docs/VISION.md): Widget "Systemstatus" einer Bento-Seite.

Eine Zelle {"widget": "system"} zeigt, was der Miniserver ueber sich hergibt
(bin/systemstatus.py): aus der Struktur Name, Typ, Projekt und Programmier-
stand, die letzte Mitteilung (globaler State notifications), wann sich der
Systemstatus geaendert hat (messageCenter), dazu Firmware und Auslastung ueber
die Webservices cfg/version, sys/cpu, sys/heap und sys/numtasks. Wie deren
Antworten aussehen, beschreibt die Loxone-Doku nicht; geprueft wird, dass die
Zelle sie unveraendert zeigt und bei einem anderen Code den Code nennt. Der
Miniserver-Nachbau (tests/lox.py) beantwortet die Webservices.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from urllib.parse import quote

import konfig
import systemstatus
from lox import ROOT, W, Miniserver, anlage, neue_app
from verteilung import _Lesespur

SCHALTER = {"name": "Flur Licht", "type": "Switch", "uuidAction": "SW", "room": "r1", "cat": "c1",
            "states": {"active": "sw-a"}}
MS_INFO = {"msName": "Haus", "projectName": "Einfamilienhaus", "miniserverType": 2}
MITTEILUNG = {"uid": "m1", "ts": 0, "type": 10, "title": "Extension offline",
              "message": "Die Tree Extension\nantwortet nicht.", "data": {"lvl": 3, "uuid": "SW"}}


def zelle(x, y, w=1, h=1, **inhalt):
    return {"x": x, "y": y, "w": w, "h": h, **inhalt}


def _struktur(**extra) -> dict:
    st = anlage({"SW": SCHALTER})
    st.update({"msInfo": MS_INFO, "lastModified": "2026-10-20 18:03:11",
               "globalStates": {"notifications": "g-notif", "sunrise": "g-auf"},
               "messageCenter": {"states": {"changed": "mc-changed"}}}, **extra)
    return st


def _panels(app, *zellen):
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["auswahl"], "pickTabs": [
        {"name": "Streifen", "picks": ["SW"], "bento": {"cols": 6, "rows": 2, "cells": list(zellen)}}]}})


def _app(app=None, verbunden=True, **states):
    app = app or W.App({"host": "", "port": 80})
    app._apply_structure(_struktur())
    app.states = {"sw-a": 0, **states}
    app._ms_verbunden_seit = time.time() - 60 if verbunden else None
    _panels(app, zelle(0, 0, 2, 2, widget="system"))
    return app


def _system(app) -> dict:
    zellen = app._view_tab("auswahl", app.resolve_profile("p"))["cells"]
    return next(c for c in zellen if c.get("widget") == "system")["system"]


def _gruppe(sy: dict, titel: str) -> dict:
    g = next((g for g in sy["gruppen"] if g["titel"] == titel), {"zeilen": []})
    return {r["k"]: r["v"] for r in g["zeilen"]}


# ---- Format ----------------------------------------------------------------------

def test_einmal_je_seite_ohne_quelle():
    assert konfig._bento_widget("system") == "system"
    app = W.App({"host": "", "port": 80})
    _panels(app, zelle(0, 0, widget="system", fremd=1), zelle(1, 0, widget="system"), zelle(2, 0, widget="clock"))
    zellen = app.panels["p"]["pickTabs"][0]["bento"]["cells"]
    assert zellen == [zelle(0, 0, widget="system"), zelle(2, 0, widget="clock")]


# ---- Rendern ---------------------------------------------------------------------

def test_struktur_mitteilung_und_systemstatus():
    """Kopf aus msInfo, Programmierstand aus lastModified, Mitteilung mit Stufe
    und Zeit; der JSON-State kommt prozentkodiert wie andere Text-States."""
    jetzt = time.time()
    geaendert = jetzt - 120
    mitteilung = dict(MITTEILUNG, ts=jetzt - 30)
    app = _app(**{"g-notif": quote(json.dumps(mitteilung)), "mc-changed": geaendert})
    sy = _system(app)
    assert sy["kopf"]["name"] == "Haus" and sy["kopf"]["typ"] == "Miniserver (Gen 2)"
    assert sy["kopf"]["ok"] is True and sy["kopf"]["text"].startswith("Verbunden seit ")
    ms = _gruppe(sy, "Miniserver")
    assert ms["Projekt"] == "Einfamilienhaus"
    assert ms["Programmiert"] == app._zeitpunkt(datetime(2026, 10, 20, 18, 3, 11))
    assert ms["Systemstatus geändert"] == app._zeitpunkt(geaendert)
    assert sy["meldung"] == {"titel": "Extension offline", "text": "Die Tree Extension antwortet nicht.",
                             "stufe": 3, "stufeText": "Systemfehler", "zeit": app._zeitpunkt(jetzt - 30)}


def test_ohne_mitteilung_und_ohne_messagecenter():
    app = W.App({"host": "", "port": 80})
    st = anlage({"SW": SCHALTER})
    st["msInfo"] = {"miniserverType": 99}
    app._apply_structure(st)
    app.states = {"sw-a": 0}
    _panels(app, zelle(0, 0, widget="system"))
    sy = _system(app)
    assert "meldung" not in sy
    assert sy["kopf"] == {"name": "Miniserver", "typ": "99", "ok": False, "text": "Nicht verbunden"}
    assert _gruppe(sy, "Miniserver") == {}
    assert [g["titel"] for g in sy["gruppen"]] == ["LoxPanel"]


def test_mitteilung_unbekannte_stufe_und_leer():
    app = _app(**{"g-notif": json.dumps({"title": "Hinweis", "data": {"lvl": 7}})})
    assert _system(app)["meldung"] == {"titel": "Hinweis", "text": ""}
    app.states["g-notif"] = json.dumps({"title": "", "message": "  "})
    assert "meldung" not in _system(app)


def test_liest_seine_states_ueber_die_lesespur():
    """Mitteilung und Systemstatus-Zeit kommen aus self.states: aendert sich
    einer davon, rendert der Broadcaster die Seite neu (verteilung.py)."""
    app = _app(**{"g-notif": json.dumps(MITTEILUNG), "mc-changed": time.time()})
    spur = _Lesespur(app.states)
    app.states = spur
    try:
        _system(app)
    finally:
        app.states = spur.quelle
    assert {"g-notif", "mc-changed"} <= spur.gelesen and not spur.alles


def test_getrennt_seit():
    app = _app(verbunden=False)
    app._ms_weg_seit = time.time() - 300
    app._system()["antworten"] = {"cfg/version": ("200", "15.2.10.6")}
    sy = _system(app)
    assert sy["kopf"]["ok"] is False and sy["kopf"]["text"] == "Getrennt seit " + app._zeitpunkt(app._ms_weg_seit)
    assert "Firmware" not in _gruppe(sy, "Miniserver")     # ohne Verbindung gilt keine Antwort


def test_loxpanel_displays_und_version(monkeypatch):
    app = _app()
    app.conn_info = {1: {"dev": "Kueche"}, 2: {"dev": "Kueche"}, 3: {"dev": ""}, 4: {"vorschau": True},
                     5: {"eingebettet": True}, 6: {}}
    monkeypatch.setattr(systemstatus, "VERSION", {"version": "0.3.4", "commit": "abcdef0123456789"})
    assert _gruppe(_system(app), "LoxPanel") == {"Displays verbunden": "3", "Version": "0.3.4 (abcdef0)"}
    monkeypatch.setattr(systemstatus, "VERSION", {"version": "", "commit": ""})
    assert _gruppe(_system(app), "LoxPanel") == {"Displays verbunden": "3"}


def test_antworten_unveraendert_und_codes():
    z = {"cfg/version": ("200", "15.2.10.6"), "sys/cpu": ("200", "12%"),
         "sys/heap": ("200", "1234/5678 kB"), "sys/numtasks": ("200", "87")}
    assert systemstatus.Systemstatus._system_zeilen(z) == [
        {"k": "Firmware", "v": "15.2.10.6"}, {"k": "CPU-Last", "v": "12%"},
        {"k": "Speicher (Heap)", "v": "1234/5678 kB"}, {"k": "Tasks", "v": "87"}]
    z = {"cfg/version": ("401", ""), "sys/cpu": ("403", ""), "sys/heap": ("403", ""), "sys/numtasks": ("403", "")}
    assert systemstatus.Systemstatus._system_zeilen(z) == [{"k": "Auslastung", "v": "nicht abrufbar (Antwort 403)"}]
    z = {"sys/cpu": ("", ""), "sys/heap": ("", ""), "sys/numtasks": ("", "")}
    assert systemstatus.Systemstatus._system_zeilen(z) == [{"k": "Auslastung", "v": "keine Antwort"}]
    z = {"sys/cpu": ("403", ""), "sys/heap": ("200", "1234"), "sys/numtasks": ("403", "")}
    assert systemstatus.Systemstatus._system_zeilen(z) == [{"k": "Speicher (Heap)", "v": "1234"}]
    assert systemstatus.Systemstatus._system_zeilen({}) == []


def test_anzeige_eine_zeile_und_begrenzt():
    assert systemstatus._anzeige("a\x00b\r\n  c\t", 60) == "a b c"
    assert systemstatus._anzeige(12.5, 60) == "12.5"
    assert systemstatus._anzeige("x" * 99, 10) == "x" * 10
    assert systemstatus._anzeige(None, 10) == ""


# ---- Abfrage --------------------------------------------------------------------

def test_abfrage_am_nachbau(miniserver_http):
    """Firmware einmal je Verbindung, Auslastung jede Runde; eine geaenderte
    Antwort meldet die Runde (dann _dirty), eine gleiche nicht. Bei 401 meldet
    sich die Abfrage nicht neu an (das macht der Datenstrom)."""
    async def lauf():
        ms = await Miniserver().start()
        ms.system = {"cfg/version": ("200", "15.2.10.6"), "sys/cpu": ("200", "12%"),
                     "sys/heap": ("200", "1234/5678 kB"), "sys/numtasks": ("200", 87)}
        app = _app(neue_app(ms))
        try:
            assert await app._system_runde() is True
            assert await app._system_runde() is False
            ms.system["sys/cpu"] = ("200", "30%")
            assert await app._system_runde() is True
            assert ms.system_abrufe == {"cfg/version": 1, "sys/cpu": 3, "sys/heap": 3, "sys/numtasks": 3}
            ms_zeilen = _gruppe(_system(app), "Miniserver")
            assert (ms_zeilen["Firmware"], ms_zeilen["CPU-Last"], ms_zeilen["Speicher (Heap)"], ms_zeilen["Tasks"]) == \
                ("15.2.10.6", "30%", "1234/5678 kB", "87")
            # neue Verbindung: Firmware neu
            app._ms_verbunden_seit += 1
            await app._system_runde()
            assert ms.system_abrufe["cfg/version"] == 2
            # Token abgelehnt: Code statt Werte, keine neue Anmeldung
            ms.token = "T2"
            assert await app._system_runde() is True
            assert _gruppe(_system(app), "Miniserver")["Auslastung"] == "nicht abrufbar (Antwort 401)"
            assert ms.anmeldungen == []
            # getrennt: keine Antworten mehr
            app._ms_verbunden_seit = None
            assert await app._system_runde() is True
            assert app._system()["antworten"] == {}
        finally:
            await app.icon_session.close()
            await ms.stop()
    asyncio.run(lauf())


def test_fragt_nur_mit_zelle():
    """Ohne Systemstatus-Zelle in einer Ansicht fragt die Schleife nicht; eine
    gerenderte Zelle (auch ein Entwurf im Editor) zaehlt bis zur naechsten Runde."""
    app = _app()
    assert app._system_gebraucht() is True
    _panels(app, zelle(0, 0, widget="clock"))
    app._system()["angefragt"] = False
    assert app._system_gebraucht() is False
    app._system_meldung()
    assert app._system_gebraucht() is False
    app._bento_system()
    assert app._system_gebraucht() is True


def test_schleife_setzt_dirty(miniserver_http, monkeypatch):
    """system_task fragt, setzt _dirty bei neuen Antworten und laeuft weiter
    (/api/health: die Aufgabe endet nie planmaessig); eine gerenderte Zelle
    ohne Firmware weckt sie vorzeitig."""
    monkeypatch.setattr(systemstatus, "SYSTEM_ABFRAGE_S", 30)

    async def lauf():
        ms = await Miniserver().start()
        ms.system = {"cfg/version": ("200", "15.2.10.6"), "sys/cpu": ("200", "12%")}
        app = _app(neue_app(ms))
        app._dirty = False
        task = asyncio.create_task(app.system_task())
        try:
            for _ in range(100):
                if app._dirty:
                    break
                await asyncio.sleep(0.02)
            assert app._dirty and ms.system_abrufe["cfg/version"] == 1
            app._dirty = False
            app._system()["antworten"].pop("cfg/version")
            app._bento_system()                       # weckt die Schleife
            for _ in range(100):
                if ms.system_abrufe["cfg/version"] == 2:
                    break
                await asyncio.sleep(0.02)
            assert ms.system_abrufe["cfg/version"] == 2 and not task.done()
            # Zelle weg: die Antworten gelten nicht mehr
            _panels(app, zelle(0, 0, widget="clock"))
            app._system()["angefragt"] = False
            app._system()["wecken"].set()
            for _ in range(100):
                if not app._system()["antworten"]:
                    break
                await asyncio.sleep(0.02)
            assert app._system()["antworten"] == {} and not task.done()
        finally:
            task.cancel()
            await app.icon_session.close()
            await ms.stop()
    asyncio.run(lauf())


def test_als_aufgabe_eingetragen():
    """Die Schleife steht in den Aufgaben, die /api/health ueberwacht."""
    quelle = (ROOT / "bin" / "webvisu.py").read_text(encoding="utf-8")
    assert '"system": asyncio.create_task(app.system_task())' in quelle
