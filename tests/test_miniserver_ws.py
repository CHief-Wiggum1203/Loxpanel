"""Live-Verbindung zum Miniserver (WebSocket, bin/loxone_ws.py).

Eine Gegenstelle, die annimmt und dann schweigt, darf die Verbindung nicht
dauerhaft haengen lassen, weder beim Aufbau noch nach der Anmeldung: Ein
still abgerissener Socket (Strom, WLAN, NAT) meldet nichts, und nach der
Anmeldung sendete LoxPanel nie wieder etwas. Jetzt hat jeder Schritt der
Anmeldung die Frist miniserver.response_timeout, im Stream geht alle
miniserver.keepalive_interval Sekunden "keepalive" raus (Antwort: Header der
Kennung 6), und kommt danach binnen der Frist nichts, endet die Verbindung.
stream_task baut sie neu auf; die Pause waechst dabei weiter, solange keine
Verbindung ueber MS_RETRY[-1] hinaus Daten liefert.

Gegenueber steht der Nachbau aus lox.py mit WebSocket (ws_modus). Die Zeiten
kommen klein aus loxpanel.cfg (Fixture cfg_ordner), HTTP statt HTTPS (Fixture
miniserver_http)."""
import asyncio
import json
import logging
import re
import time

import pytest

from lox import Miniserver, W, neue_app

UUID = "0f1e2d3c-0001-0002-0102030405060708"
FRIST, ABSTAND = 0.3, 0.2      # s: response_timeout und keepalive_interval im Test
AUSSEN = 5.0                   # s: Grenze des Tests selbst; greift sie, haengt der Code


@pytest.fixture
def kurz(cfg_ordner, miniserver_http):
    (cfg_ordner / "loxpanel.cfg").write_text(json.dumps({"miniserver": {
        "response_timeout": FRIST, "keepalive_interval": ABSTAND}}), encoding="utf-8")
    return cfg_ordner


async def _nachbau(modus, **attr) -> Miniserver:
    ms = Miniserver()
    ms.ws_modus, ms.ws_werte = modus, {UUID: 21.5}
    for k, v in attr.items():
        setattr(ms, k, v)
    return await ms.start()


def _app(ms):
    app = neue_app(ms)
    app.user = ms.benutzer
    return app


async def _ende(app, ms, *tasks):
    for t in tasks:
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    if app.ws:
        await app.ws.close()
    await app.icon_session.close()
    await ms.stop()


async def _bis(bedingung, frist=AUSSEN):
    ende = time.monotonic() + frist
    while not bedingung():
        assert time.monotonic() < ende, "Bedingung nicht erreicht"
        await asyncio.sleep(0.02)


@pytest.mark.parametrize("modus, schritt", [("upgrade", "den Verbindungsaufbau"),
                                            ("anmeldung", "jdev/sys/getkey")])
def test_stummer_aufbau_bricht_nach_frist_ab(kurz, modus, schritt):
    """Nimmt der Miniserver an und antwortet nicht (Neustart, Ueberlast),
    scheitert der Aufbau nach der Frist, statt ewig zu warten."""
    async def lauf():
        ms = await _nachbau(modus)
        app = _app(ms)
        t0 = time.monotonic()
        try:
            with pytest.raises(ConnectionError) as fehler:
                await asyncio.wait_for(app._connect_ws(), AUSSEN)
            return time.monotonic() - t0, str(fehler.value)
        finally:
            await _ende(app, ms)
    dauer, text = asyncio.run(lauf())

    assert FRIST <= dauer < FRIST + 1.0, dauer
    assert text == f"Miniserver antwortet nicht auf {schritt} (keine Antwort in {FRIST:g} s)"


def test_stille_nach_anmeldung_beendet_verbindung(kurz):
    """Nach der Anmeldung und dem ersten Wert schweigt der Miniserver, auch
    auf keepalive: stream() endet nach Abstand + Frist mit einem Fehler."""
    async def lauf():
        ms = await _nachbau("stream")
        app = _app(ms)
        werte = []
        try:
            await asyncio.wait_for(app._connect_ws(), AUSSEN)
            t0 = time.monotonic()
            with pytest.raises(ConnectionError) as fehler:
                await asyncio.wait_for(app.ws.stream(lambda u, v: werte.append((u, v))), AUSSEN)
            return werte, time.monotonic() - t0, str(fehler.value), app.ws.lebenszeit()
        finally:
            await _ende(app, ms)
    werte, dauer, text, lebte = asyncio.run(lauf())

    assert werte == [(UUID, 21.5)], "die erste Tabelle kam noch an"
    assert ABSTAND + FRIST <= dauer < ABSTAND + FRIST + 1.0, dauer
    assert text == f"Miniserver antwortet nicht mehr (keine Nachricht in {ABSTAND + FRIST:g} s)"
    assert lebte < ABSTAND, "nach der ersten Tabelle kam nichts mehr"


def test_keepalive_haelt_ruhige_verbindung(kurz, caplog):
    """Ohne Wertaenderungen haelt die Verbindung, weil der Miniserver
    keepalive beantwortet. Die Antworten (Header der Kennung 6 ohne
    Nutzdaten) stoeren die Tabellen dazwischen nicht."""
    caplog.set_level(logging.INFO, logger="loxpanel.ws")

    async def lauf():
        ms = await _nachbau("an")
        app = _app(ms)
        werte = []
        await app._connect_ws()
        task = asyncio.create_task(app.ws.stream(lambda u, v: werte.append(v)))
        try:
            await asyncio.sleep(4 * ABSTAND + FRIST)       # laenger als Abstand + Frist
            lebt = not task.done()
            await ms.ws_wert(UUID, 22.5)
            await _bis(lambda: len(werte) == 2 or task.done())
            return lebt, ms.keepalives, werte, app.ws.lebenszeit()
        finally:
            await _ende(app, ms, task)
    lebt, keepalives, werte, lebte = asyncio.run(lauf())

    assert lebt and keepalives >= 3, keepalives
    assert werte == [21.5, 22.5]
    assert lebte >= 3 * ABSTAND, "jede Antwort zaehlt als Lebenszeichen"
    assert caplog.text.count("beantwortet keepalive") == 1, "einmal je Verbindung"


def test_schliessen_von_aussen_endet_still(kurz, caplog):
    """Wie reconnect() beim Speichern eines Zugangs: Die alte Verbindung wird
    geschlossen, waehrend stream() wartet. stream() endet ohne Fehler und
    ohne Warnung, und es geht kein keepalive mehr raus."""
    async def lauf():
        ms = await _nachbau("an")
        app = _app(ms)
        await app._connect_ws()
        ws = app.ws
        task = asyncio.create_task(ws.stream(lambda u, v: None))
        try:
            await asyncio.sleep(2 * ABSTAND)
            await ws.close()
            await asyncio.wait_for(task, AUSSEN)
            gesendet = ms.keepalives
            await asyncio.sleep(2 * ABSTAND)
            offen = [t for t in asyncio.all_tasks() if "_keepalive" in repr(t.get_coro())]
            return gesendet, ms.keepalives, offen
        finally:
            await _ende(app, ms, task)
    gesendet, spaeter, offen = asyncio.run(lauf())

    assert gesendet == spaeter and offen == []
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], caplog.text


def _pausen(caplog) -> list[float]:
    return [float(m) for r in caplog.records
            for m in re.findall(r"neuer Versuch in ([\d.]+)s", r.getMessage())]


@pytest.mark.parametrize("modus, trennen, waechst", [
    ("stream", None, True),     # schweigt nach der Anmeldung, endet erst nach Abstand + Frist
    ("an", 0, True),            # trennt gleich nach der ersten Tabelle
    ("an", 0.8, False),         # beantwortet keepalive ueber MS_RETRY[-1] hinaus, dann getrennt
], ids=["stumm", "trennt-sofort", "lebte"])
def test_pause_nach_abbruch(kurz, monkeypatch, caplog, modus, trennen, waechst):
    """stream_task baut nach Stille neu auf. Die Pause beginnt nur von vorn,
    wenn die Verbindung ueber MS_RETRY[-1] hinaus Daten lieferte - nicht schon,
    weil eine stumme Verbindung so lange offen war (Abstand + Frist ist hier
    wie im Betrieb laenger als MS_RETRY[-1]): Sonst meldete sich LoxPanel bei
    einem dauerhaft stummen Miniserver in kurzem Takt neu an."""
    monkeypatch.setattr(W, "MS_RETRY", (0.05, 0.1, 0.2))
    assert ABSTAND + FRIST > W.MS_RETRY[-1]

    async def lauf():
        ms = await _nachbau(modus, ws_trennen_nach=trennen)
        app = _app(ms)

        async def nichts():
            return False
        app._refresh_structure = nichts
        task = asyncio.create_task(app.stream_task())
        try:
            await _bis(lambda: len(_pausen(caplog)) >= 3, 3 * AUSSEN)
            return ms.ws_verbindungen
        finally:
            await _ende(app, ms, task)
    verbindungen = asyncio.run(lauf())

    assert verbindungen >= 3
    assert _pausen(caplog)[:3] == ([0.05, 0.1, 0.2] if waechst else [0.05, 0.05, 0.05])
    if modus == "stream":
        assert "antwortet nicht mehr" in caplog.text


@pytest.mark.parametrize("wert, erwartet", [(None, None), (30, 30), (0.5, 0.5), (0, None), (-5, None),
                                            ("60", None), (True, None), (float("nan"), None)])
def test_keepalive_abstand_einstellung(cfg_ordner, caplog, wert, erwartet):
    """miniserver.keepalive_interval: Zahl > 0, sonst der Standard (mit Warnung)."""
    ms = {} if wert is None else {"keepalive_interval": wert}
    (cfg_ordner / "loxpanel.cfg").write_text(json.dumps({"miniserver": ms}), encoding="utf-8")
    assert W._ms_keepalive_abstand() == (W.MS_KEEPALIVE if erwartet is None else erwartet)
    warnt = "keepalive_interval" in caplog.text
    assert warnt == (wert is not None and erwartet is None)
