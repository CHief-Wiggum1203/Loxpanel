"""SIP-Zugang der Intercom (Settings -> SIP): App.secured_details holt die
gesicherten Details ueber einen verschluesselten Befehl, /api/sip listet die
Intercoms ohne Passwort, /api/sip/pruefen prueft die Tuerstation. Miniserver
(mit Command Encryption) und Tuerstation sind die Nachbauten aus tests/lox.py."""
import asyncio
import copy
import json
import re

import aiohttp
import pytest
from aiohttp import web

from lox import Miniserver, SipTuer, W, anlage, intercom_baustein, neue_app, serve

SIP_PASS, BILD_PASS = "Sip-Kennwort-1", "Bild-Kennwort-2"
GESICHERT = {"videoInfo": {"streamUrl": "http://192.168.1.201/cgi-bin/faststream.jpg?stream=full",
                           "user": "kamera", "pass": BILD_PASS},
             "audioInfo": {"host": "192.168.1.201", "user": "tuer", "pass": SIP_PASS}}
# Wie bei einer Intercom ohne eingerichtetes Audio: Kamera ja, SIP nein
OHNE_AUDIO = {"videoInfo": {"streamUrl": "http://10.9.8.7/bild.jpg", "user": "videonutzer",
                            "pass": BILD_PASS, "alertImage": ""}, "audioInfo": {}}
SCHALTER = {"name": "Licht", "type": "Switch", "uuidAction": "S1", "room": "r1", "cat": "c1",
            "states": {"active": "s1"}}


async def _aufbau(gesichert=None, controls=None):
    """Nachbau-Miniserver mit gesicherten Details und eine angemeldete App mit
    der Intercom IC. -> (ms, app); Aufrufer raeumt mit _abbau auf."""
    ms = await Miniserver().start()
    ms.gesichert = copy.deepcopy({"IC": GESICHERT} if gesichert is None else gesichert)
    app = neue_app(ms)
    app.user = ms.benutzer
    control, states = intercom_baustein()
    app._apply_structure(anlage(controls or {"IC": control}))
    app.states = states
    return ms, app


async def _abbau(ms, app):
    await app.icon_session.close()
    await ms.stop()


def test_gesicherte_details(miniserver_http):
    """Der Befehl geht verschluesselt (fenc), die Anmeldung steckt im Befehl;
    den Schluessel des Miniservers holt die App einmal und behaelt ihn."""
    async def lauf():
        ms, app = await _aufbau()
        try:
            assert await app.secured_details("IC") == GESICHERT
            assert await app.secured_details("IC") == GESICHERT
            assert ms.schluessel_abrufe == 1
            assert [c.split("?")[0] for c in ms.fenc] == ["jdev/sps/io/IC/securedDetails"] * 2
            assert all(c.endswith("&user=loxpanel") for c in ms.fenc)
            assert ms.io == [], "kein Befehl im Klartext"
            assert app.client.n == 0, "keine neue Anmeldung noetig"
        finally:
            await _abbau(ms, app)
    asyncio.run(lauf())


def test_neuer_schluessel_nach_neustart(miniserver_http):
    """Nach einem Neustart hat der Miniserver einen neuen Schluessel und lehnt
    den alten mit HTTP 401 ab: einmal neu holen und wiederholen."""
    async def lauf():
        ms, app = await _aufbau()
        try:
            await app.secured_details("IC")
            ms.neuer_schluessel()
            assert await app.secured_details("IC") == GESICHERT
            assert ms.schluessel_abrufe == 2 and len(ms.fenc) == 2
            assert app.client.n == 0
        finally:
            await _abbau(ms, app)
    asyncio.run(lauf())


def test_token_abgelaufen(miniserver_http, monkeypatch):
    """LL-Code 401 im entschluesselten Ergebnis: das Token gilt nicht mehr ->
    neu anmelden und mit dem neuen Token wiederholen."""
    monkeypatch.setattr(W, "TOKEN_RENEW_MIN", 0)

    async def lauf():
        ms, app = await _aufbau()
        try:
            ms.token = "neu"                       # das Token der App gilt nicht mehr
            assert await app.secured_details("IC") == GESICHERT
            assert app.client.n == 1 and app.jwt == ms.token
            assert len(ms.fenc) == 2
        finally:
            await _abbau(ms, app)
    asyncio.run(lauf())


def test_token_abgelehnt_kurz_nach_anmeldung(miniserver_http):
    """Kurz nach der letzten Anmeldung meldet sich die App nicht schon wieder an
    (TOKEN_RENEW_MIN): dann liegt es nicht am Token, der Fehler sagt es."""
    async def lauf():
        ms, app = await _aufbau()
        try:
            ms.token = "neu"
            with pytest.raises(W.ZugangFehler, match=re.escape("lehnt die Anmeldung von LoxPanel ab (Code 401)")):
                await app.secured_details("IC")
            assert app.client.n == 0 and len(ms.fenc) == 1
        finally:
            await _abbau(ms, app)
    asyncio.run(lauf())


@pytest.mark.parametrize("code, fehler", [
    ("403", "Der Benutzer von LoxPanel darf diese Zugangsdaten nicht lesen (Rechte in Loxone Config)"),
    ("500", "Der Miniserver antwortet mit Code 500"),
])
def test_miniserver_lehnt_ab(miniserver_http, code, fehler):
    async def lauf():
        ms, app = await _aufbau()
        ms.gesichert_code = code
        try:
            with pytest.raises(W.ZugangFehler, match=re.escape(fehler)):
                await app.secured_details("IC")
        finally:
            await _abbau(ms, app)
    asyncio.run(lauf())


def test_ohne_verbindung():
    async def lauf():
        with pytest.raises(W.ZugangFehler, match="Keine Verbindung zum Miniserver"):
            await W.App({"host": "", "port": 80}).secured_details("IC")
    asyncio.run(lauf())


def test_miniserver_weg(miniserver_http):
    async def lauf():
        ms, app = await _aufbau()
        await ms.stop()
        try:
            with pytest.raises(W.ZugangFehler, match="Miniserver nicht erreichbar"):
                await app.secured_details("IC")
        finally:
            await app.icon_session.close()
    asyncio.run(lauf())


@pytest.mark.parametrize("audio, soll", [
    (GESICHERT["audioInfo"], {"host": "192.168.1.201", "user": "tuer", "pass": SIP_PASS}),
    ({"host": " 10.0.0.5:5062 "}, {"host": "10.0.0.5:5062", "user": "", "pass": ""}),    # andere Tuerstation
])
def test_intercom_sip(miniserver_http, audio, soll):
    async def lauf():
        ms, app = await _aufbau({"IC": {"audioInfo": audio}})
        try:
            assert await app.intercom_sip("IC") == soll
        finally:
            await _abbau(ms, app)
    asyncio.run(lauf())


@pytest.mark.parametrize("gesichert, fehler", [
    ({"videoInfo": GESICHERT["videoInfo"], "audioInfo": {}}, "Die Intercom nennt keinen SIP-Zugang"),
    ({"audioInfo": {"host": "  ", "user": "tuer"}}, "Die Intercom nennt keinen SIP-Zugang"),
    ({"audioInfo": "kaputt"}, "Die Intercom nennt keinen SIP-Zugang"),
    ([], "Der Baustein hat keine gesicherten Details"),
])
def test_intercom_ohne_sip(miniserver_http, gesichert, fehler):
    async def lauf():
        ms, app = await _aufbau({"IC": gesichert})
        try:
            with pytest.raises(W.ZugangFehler, match=fehler):
                await app.intercom_sip("IC")
        finally:
            await _abbau(ms, app)
    asyncio.run(lauf())


async def _routen(app):
    ui = web.Application()
    ui["app"] = app
    ui.router.add_get("/api/sip", W.api_sip)
    ui.router.add_post("/api/sip/pruefen", W.api_sip_pruefen)
    return await serve(ui)


def _kennwort_werte(obj) -> list:
    """Alle Werte unter den Schluesseln pass und password, egal wie tief."""
    if isinstance(obj, dict):
        return [w for k, v in obj.items() for w in ([v] if k in ("pass", "password") else []) + _kennwort_werte(v)]
    if isinstance(obj, list):
        return [w for v in obj for w in _kennwort_werte(v)]
    return []


def _intercoms() -> dict:
    ic, _ = intercom_baustein()
    garten = dict(ic, name="Garten Intercom", uuidAction="IC2", room="r2",
                  details=dict(ic["details"], deviceType=0))
    keller = dict(ic, name="Keller Intercom", uuidAction="IC3", room="r2",
                  details=dict(ic["details"], deviceType=0))
    return {"IC": ic, "IC2": garten, "IC3": keller, "S1": SCHALTER}


def test_api_sip_ohne_passwort(miniserver_http):
    """Die Liste nennt Adresse und Benutzer, vom Passwort nur, ob es eines gibt:
    die Routen haben keine Anmeldung. Eine Intercom ohne Zugang nennt den Grund;
    fehlt nur der SIP-Teil, dazu den Aufbau der gesicherten Details ohne Werte."""
    async def lauf():
        ms, app = await _aufbau({"IC": GESICHERT, "IC3": OHNE_AUDIO}, controls=_intercoms())
        runner, port = await _routen(app)
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"http://127.0.0.1:{port}/api/sip") as r:
                    status, text = r.status, await r.text()
            assert status == 200
            assert SIP_PASS not in text and BILD_PASS not in text
            assert _kennwort_werte(json.loads(text)) == [True], "pass nur als Feldname mit gefuellt/leer"
            assert json.loads(text) == {"connected": True, "intercoms": [
                {"uuid": "IC", "name": "Eingang Intercom", "room": "Zentral", "deviceType": 1,
                 "sip": {"host": "192.168.1.201", "user": "tuer", "hasPass": True}},
                {"uuid": "IC2", "name": "Garten Intercom", "room": "Technikraum", "deviceType": 0,
                 "error": "Der Miniserver antwortet mit Code 500"},
                {"uuid": "IC3", "name": "Keller Intercom", "room": "Technikraum", "deviceType": 0,
                 "error": "Die Intercom nennt keinen SIP-Zugang",
                 "felder": {"videoInfo": {"streamUrl": True, "user": True, "pass": True, "alertImage": False},
                            "audioInfo": {}}}]}
            assert "10.9.8.7" not in text and "videonutzer" not in text, "keine Werte, nur Feldnamen"
        finally:
            await runner.cleanup()
            await _abbau(ms, app)
    asyncio.run(lauf())


def test_gesichert_felder():
    assert W._gesichert_felder({"a": "x", "b": "", "c": {"d": 0, "e": [1], "f": None}, "g": []}) == {
        "a": True, "b": False, "c": {"d": False, "e": True, "f": False}, "g": False}


def test_api_sip_ohne_miniserver():
    """Ohne Verbindung (Struktur von frueher) bleibt die Liste, jede Intercom
    nennt den Grund."""
    async def lauf():
        app = W.App({"host": "", "port": 80})
        ic, _ = intercom_baustein()
        app._apply_structure(anlage({"IC": ic}))
        runner, port = await _routen(app)
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"http://127.0.0.1:{port}/api/sip") as r:
                    j = await r.json()
            assert j == {"connected": False, "intercoms": [
                {"uuid": "IC", "name": "Eingang Intercom", "room": "Zentral", "deviceType": 1,
                 "error": "Keine Verbindung zum Miniserver"}]}
        finally:
            await runner.cleanup()
    asyncio.run(lauf())


def test_api_sip_pruefen(miniserver_http):
    """Die Pruefung nimmt Adresse und Zugang vom Miniserver, nie aus der
    Anfrage; das Passwort steht in keiner Antwort."""
    async def lauf():
        tuer = await SipTuer(passwort=SIP_PASS).start()
        gesichert = copy.deepcopy(GESICHERT)
        gesichert["audioInfo"]["host"] = f"127.0.0.1:{tuer.port}"
        ms, app = await _aufbau({"IC": gesichert, "IC2": {"audioInfo": {}}}, controls=_intercoms())
        runner, port = await _routen(app)
        try:
            async with aiohttp.ClientSession() as s:
                async def pruefen(body: str):
                    async with s.post(f"http://127.0.0.1:{port}/api/sip/pruefen", data=body,
                                      headers={"Content-Type": "application/json"}) as r:
                        text = await r.text()
                        assert SIP_PASS not in text
                        return r.status, json.loads(text)

                status, j = await pruefen(json.dumps({"uuid": "IC", "host": "10.9.9.9"}))
                assert status == 200
                assert j == {"ok": True, "ziel": f"sip:tuer@127.0.0.1:{tuer.port}", "erreichbar": True,
                             "ms": j["ms"], "antwort": "200 OK", "anmeldung": "angenommen",
                             "gegenstelle": "Nachbau-Tuer/1.0", "methoden": ["INVITE", "ACK", "CANCEL", "BYE", "OPTIONS"],
                             "codecs": ["PCMU/8000", "PCMA/8000", "telephone-event/8000"]}
                assert len(tuer.anfragen) == 2
                assert await pruefen(json.dumps({"uuid": "IC2"})) == (
                    200, {"ok": False, "error": "Die Intercom nennt keinen SIP-Zugang"})
                for body in (json.dumps({"uuid": "NIX"}), json.dumps({"uuid": "S1"}), json.dumps([1, 2]), "{}"):
                    assert await pruefen(body) == (404, {"ok": False, "error": "Unbekannte Intercom"}), body
                assert await pruefen("kein json") == (400, {"ok": False, "error": "kein gültiges JSON"})
                assert len(tuer.anfragen) == 2, "nur die eine Pruefung erreichte die Tuerstation"
        finally:
            await runner.cleanup()
            await _abbau(ms, app)
            tuer.stop()
    asyncio.run(lauf())
