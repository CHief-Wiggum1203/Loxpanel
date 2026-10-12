"""Verbindungszustand fuer die Panels ({t:"verbindung"}).

Der Server meldet jedem Panel, ob er den Miniserver erreicht, seit wann nicht
und wann er zuletzt von ihm hoerte: bei jeder Aenderung und alle
VERBINDUNG_TAKT s als Lebenszeichen, an dem die Visu einen still
verschwundenen Server erkennt. Ohne Struktur zeigt das Panel die
Einrichtungskarte, dann meldet die Leiste nichts.

Gegenueber steht der Miniserver-Nachbau aus lox.py: WebSocket "an", der nach
ws_trennen_nach s trennt; ws_modus None heisst nicht erreichbar (404 statt
WebSocket). Zeiten klein aus loxpanel.cfg (Fixture cfg_ordner), HTTP statt
HTTPS (Fixture miniserver_http)."""
import asyncio
import json
import time

import aiohttp
import pytest

from lox import Miniserver, W, anlage, neue_app, visu_starten

UUID = "0f1e2d3c-0001-0002-0102030405060708"
AUSSEN = 5.0      # s: Grenze des Tests selbst; greift sie, haengt der Code
STRUKTUR = anlage({"S1": {"name": "Stehlampe", "type": "Switch", "uuidAction": "S1", "room": "r1",
                          "cat": "c1", "isFavorite": True, "states": {"active": UUID}}})


@pytest.fixture
def kurz(cfg_ordner, miniserver_http, monkeypatch):
    (cfg_ordner / "loxpanel.cfg").write_text(json.dumps({"miniserver": {
        "response_timeout": 0.3, "keepalive_interval": 0.2}}), encoding="utf-8")
    monkeypatch.setattr(W, "MS_RETRY", (0.05, 0.1))
    return cfg_ordner


async def _bis(bedingung, frist=AUSSEN):
    ende = time.monotonic() + frist
    while not bedingung():
        assert time.monotonic() < ende, "Bedingung nicht erreicht"
        await asyncio.sleep(0.02)


def test_abriss_und_rueckkehr(kurz, caplog):
    """Trennt der Miniserver und ist danach nicht erreichbar, nennt der Stand
    den Zeitpunkt des Abrisses und die letzte Nachricht davor; neue
    Fehlversuche verschieben den Abriss nicht. Ist er wieder da, gilt er
    sofort nach der Anmeldung als erreichbar."""
    async def lauf():
        ms = Miniserver()
        ms.ws_werte, ms.ws_trennen_nach = {UUID: 1.0}, 0.3
        await ms.start()
        app = neue_app(ms)
        app.user = ms.benutzer
        app._apply_structure(STRUKTUR)

        async def nichts():
            return False
        app._refresh_structure = nichts
        stand = {}
        vorher = time.time()
        task = asyncio.create_task(app.stream_task())
        try:
            await _bis(lambda: ms.ws_verbindungen >= 1 and app._ms_fehler == "" and app.ws is not None)
            stand["verbunden"] = app._verbindung_stand()
            ms.ws_modus = None                       # nach der Trennung nicht mehr erreichbar
            await _bis(lambda: not app._verbindung_stand()[0])
            stand["weg"] = app._verbindung_stand()
            stand["weg_ab"] = time.time()
            await _bis(lambda: caplog.text.count("Miniserver nicht verbunden") >= 3)
            stand["spaeter"] = app._verbindung_stand()
            ms.ws_modus, ms.ws_trennen_nach = "an", None
            await _bis(lambda: app._verbindung_stand()[0])
            stand["zurueck"] = app._verbindung_stand()
            return stand, vorher
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            if app.ws:
                await app.ws.close()
            await app.icon_session.close()
            await ms.stop()
    stand, vorher = asyncio.run(lauf())

    assert stand["verbunden"] == (True, None, None)
    ok, seit, bestaetigt = stand["weg"]
    assert not ok and vorher <= bestaetigt <= seit <= stand["weg_ab"], stand
    assert stand["spaeter"] == stand["weg"], "Fehlversuche verschieben den Abriss nicht"
    assert stand["zurueck"] == (True, None, None)


def test_ohne_struktur_gilt_er_als_erreichbar():
    """Ohne Struktur zeigen die Panels die Einrichtungskarte, es gibt keine
    Werte, die veralten koennten."""
    app = W.App({"host": "", "port": 80})
    app._ms_weg_seit, app._ms_bestaetigt = time.time(), time.time() - 5
    assert app._verbindung_stand() == (True, None, None)
    app._apply_structure(STRUKTUR)
    assert app._verbindung_stand() == (False, app._ms_weg_seit, app._ms_bestaetigt)


def test_texte_nennen_ihre_platzhalter():
    """Die Visu setzt Uhrzeiten an {seit} und {stand} ein."""
    t = W.VERBINDUNG_TEXTE
    assert "{seit}" in t["ms"] and "{seit}" in t["server"] and "{stand}" in t["stand"] and t["gesperrt"]
    assert W.VERBINDUNG_STUMM > 2 * W.VERBINDUNG_TAKT, "ein verspaeteter Takt darf nichts abreissen"


def test_panel_bekommt_zustand_und_lebenszeichen(monkeypatch):
    """Beim Verbinden bekommt das Panel den Stand samt Takt, Fristen und
    Texten, danach im Takt erneut, und jede Aenderung sofort."""
    monkeypatch.setattr(W, "VERBINDUNG_TAKT", 0.4)

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(STRUKTUR)
        app.states = {UUID: 1}
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"]}})
        runner, port, bc = await visu_starten(app)
        meldungen = []

        async def lesen(ws):
            async for m in ws:
                d = json.loads(m.data)
                if d.get("t") == "verbindung":
                    meldungen.append((time.monotonic(), d))
        try:
            async with aiohttp.ClientSession() as s, s.ws_connect(f"http://127.0.0.1:{port}/ws?panel=test") as ws:
                leser = asyncio.create_task(lesen(ws))
                await _bis(lambda: len(meldungen) >= 3)
                weg, bestaetigt = time.time(), time.time() - 5
                app._ms_weg_seit, app._ms_bestaetigt = weg, bestaetigt
                await _bis(lambda: not meldungen[-1][1]["ms"])
                app._ms_weg_seit = None
                await _bis(lambda: meldungen[-1][1]["ms"])
                leser.cancel()
            return meldungen, weg, bestaetigt
        finally:
            bc.cancel()
            await runner.cleanup()
    meldungen, weg, bestaetigt = asyncio.run(lauf())

    erste = meldungen[0][1]
    assert erste == {"t": "verbindung", "ms": True, "seit": None, "stand": None, "takt": 0.4,
                     "stumm": W.VERBINDUNG_STUMM, "hinweis": W.VERBINDUNG_HINWEIS,
                     "texte": W.VERBINDUNG_TEXTE}, erste
    abstaende = [b[0] - a[0] for a, b in zip(meldungen[:3], meldungen[1:3])]
    assert all(0.3 <= x <= 1.0 for x in abstaende), abstaende
    ausfall = next(d for _, d in meldungen if not d["ms"])
    assert ausfall["seit"] == round(weg * 1000) and ausfall["stand"] == round(bestaetigt * 1000), ausfall
