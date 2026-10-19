"""HTTP oder HTTPS: welches Schema am Port des Miniservers antwortet.

Gen1 spricht nur HTTP, Gen2 HTTP und HTTPS, beide Ports sind in Loxone Config
einstellbar, dazu kommen Weiterleitungen im Router. Frueher galt Port 80 als
HTTP und jeder andere als HTTPS; ein HTTP-Port wie 8006 scheiterte mit
"[SSL: WRONG_VERSION_NUMBER]" (auf den TLS-Gruss kam Klartext), schon beim
Speichern des Zugangs. Jetzt versucht die Anmeldung (getkey2) erst das Schema
nach dem Port und, wenn dabei keine Antwort des Miniservers zustande kommt,
das andere; WebSocket und HTTP-Abrufe folgen dem erkannten Schema.

Gegenueber steht der Nachbau aus lox.py, als HTTP-Server wie ein Gen1 oder mit
TLS wie ein Gen2, immer auf einem freien Port (nie 80). Ohne die Fixture
miniserver_http: Der erste Versuch ist hier also immer TLS, wie im Betrieb.
"""
from __future__ import annotations

import asyncio
import socket
import ssl

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

from lox import Miniserver, W, Zertifizierungsstelle, anlage, ersetzen, miniserver
from test_miniserver_zugang import ABGELEHNT, BAUSTEINE, _datei_ms, _speichern, _ui
from test_tls import _abonniert


@pytest.fixture
def versuche(monkeypatch) -> list[bool]:
    """Schema je Verbindungsversuch in dieser Reihenfolge, True = TLS."""
    liste: list[bool] = []
    echt = miniserver._make_client

    def mitschreiben(host, user, password, port, verify_tls, tls):
        liste.append(tls)
        return echt(host, user, password, port, verify_tls, tls)
    monkeypatch.setattr(miniserver, "_make_client", mitschreiben)
    return liste


async def _ms(kontext: ssl.SSLContext | None = None) -> Miniserver:
    ms = Miniserver()
    ms.struktur = anlage(BAUSTEINE)
    return await ms.start(ssl_context=kontext)


def _zugang(port: int, kennwort: str = "richtig", verify_tls: bool = False) -> dict:
    return {"host": "127.0.0.1", "user": "loxpanel", "pass": kennwort, "port": port, "verify_tls": verify_tls}


async def _befehl_kommt_an(app: W.App, ms: Miniserver) -> None:
    """WebSocket abonniert, ein Befehl ueber _ms_http erreicht den Nachbau."""
    assert await _abonniert(ms)
    status, _, _ = await app._ms_http("jdev/sps/io/L/On", 5)
    assert status == 200 and ms.io == ["sps/io/L/On"]


async def _tor(ziel_port: int) -> tuple[asyncio.Server, int]:
    """Gegenstelle, die auf einen TLS-Gruss schweigt, wie ein eingebetteter
    HTTP-Server, der auf das Zeilenende wartet, und Klartext an den Nachbau
    weiterreicht."""
    async def verbindung(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        erstes = await r.read(1)
        if erstes == b"\x16":            # TLS-Handshake (Record-Typ 22): schweigen, bis der Client aufgibt
            await r.read()
            w.close()
            return
        zr, zw = await asyncio.open_connection("127.0.0.1", ziel_port)
        zw.write(erstes)

        async def pumpe(von: asyncio.StreamReader, nach: asyncio.StreamWriter) -> None:
            try:
                while daten := await von.read(65536):
                    nach.write(daten)
                    await nach.drain()
            finally:
                nach.close()
        await asyncio.gather(pumpe(r, zw), pumpe(zr, w), return_exceptions=True)
    srv = await asyncio.start_server(verbindung, "127.0.0.1", 0)
    return srv, srv.sockets[0].getsockname()[1]


async def _schweigen(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
    """Nimmt die Verbindung an und antwortet auf nichts, bis der Client geht."""
    await r.read()
    w.close()


@pytest.mark.parametrize("weg", ["speichern", "start"])
def test_http_an_eigenem_port(cfg_ordner, versuche, weg):
    """Der Fall aus der Meldung: Miniserver mit HTTP an einem anderen Port als
    80, Zertifikat pruefen aus. "Verbinden & Speichern" verbindet und speichert,
    ebenso der Start des Servers (stream_task -> start()); WebSocket (ws://),
    Befehle (http://) und das Diagnosepaket folgen dem erkannten Schema."""
    async def lauf():
        ms = await _ms()
        if weg == "speichern":
            app = W.App(W._config())
            async with TestClient(TestServer(_ui(app))) as cl:
                antwort = await _speichern(cl, **_zugang(ms.port))
            await app._connect_ws()             # baut sonst stream_task auf
        else:
            app = W.App(_zugang(ms.port))
            await app.start()
            antwort = None
        try:
            await _befehl_kommt_an(app, ms)
            return antwort, app.ms_tls, app.diagnose_daten()[0]["miniserver"]
        finally:
            await app._close_conn()
            await ms.stop()
    antwort, tls, diagnose = asyncio.run(lauf())

    if weg == "speichern":
        assert antwort == (200, {"ok": True, "connected": True, "nControls": 1})
        assert _datei_ms(cfg_ordner)["port"] != 80
    assert versuche == [True, False], "erst TLS, dann HTTP"
    assert tls is False and diagnose["verschluesselt"] is False


def test_tls_bleibt_beim_ersten_versuch(tmp_path, versuche):
    """Gen2 mit HTTPS an einem anderen Port als 443: verbunden wie bisher, ohne
    zweiten Versuch und ohne Klartext."""
    async def lauf():
        ms = await _ms(Zertifizierungsstelle(tmp_path).server("localhost"))
        app = W.App(_zugang(ms.port))
        try:
            await app.start()
            await _befehl_kommt_an(app, ms)
            return app.ms_tls
        finally:
            await app._close_conn()
            await ms.stop()
    assert asyncio.run(lauf()) is True
    assert versuche == [True]


def test_tls_wo_http_erwartet(tmp_path, versuche, miniserver_http):
    """Andersherum: Der Port legt HTTP nahe (wie Port 80, hier ueber die Fixture),
    dort spricht aber TLS (etwa eine Weiterleitung auf den HTTPS-Port). Der
    Klartext-Abruf scheitert ohne Antwort, also TLS - auch fuer WebSocket und
    Befehle."""
    async def lauf():
        ms = await _ms(Zertifizierungsstelle(tmp_path).server("localhost"))
        app = W.App(_zugang(ms.port))
        try:
            await app.start()
            await _befehl_kommt_an(app, ms)
            return app.ms_tls
        finally:
            await app._close_conn()
            await ms.stop()
    assert asyncio.run(lauf()) is True
    assert versuche == [False, True]


def test_mit_zertifikatspruefung_nie_unverschluesselt(cfg_ordner, versuche):
    """Wer das Zertifikat pruefen laesst, will verschluesselt verbinden: An
    einem HTTP-Port bleibt es beim TLS-Fehler, nichts geht im Klartext raus,
    der Zugang wird nicht gespeichert."""
    async def lauf():
        ms = await _ms()
        app = W.App(W._config())
        try:
            with pytest.raises(ssl.SSLError) as ei:
                await app.reconnect(_zugang(ms.port, verify_tls=True))
            assert not isinstance(ei.value, ssl.SSLCertVerificationError)
            async with TestClient(TestServer(_ui(app))) as cl:
                antwort = await _speichern(cl, **_zugang(ms.port, verify_tls=True))
            return antwort, ms.anmeldungen, app.client
        finally:
            await app._close_conn()
            await ms.stop()
    (status, j), anmeldungen, client = asyncio.run(lauf())

    assert versuche == [True, True], "je Anlauf nur TLS"
    assert anmeldungen == [] and client is None
    assert status == 200 and j["ok"] is False and not j.get("gespeichert") and j["error"] == ABGELEHNT
    assert not (cfg_ordner / "loxpanel.cfg").exists()


def test_falsches_kennwort_am_http_port(cfg_ordner, versuche):
    """Das Kennwort prueft erst die Anmeldung nach getkey2, also schon ueber das
    erkannte Schema: Die Meldung nennt die Ablehnung (401), keinen TLS-Fehler."""
    async def lauf():
        ms = await _ms()
        app = W.App(W._config())
        try:
            async with TestClient(TestServer(_ui(app))) as cl:
                return await _speichern(cl, **_zugang(ms.port, "Tippfehler")), ms.anmeldungen
        finally:
            await app._close_conn()
            await ms.stop()
    (status, j), anmeldungen = asyncio.run(lauf())

    assert status == 200 and j["ok"] is False and j["error"] == ABGELEHNT
    assert "401" in j["fehler"] and "SSL" not in j["fehler"]
    assert versuche == [True, False] and anmeldungen == ["abgelehnt"]


def test_antwort_des_miniservers_wechselt_nicht(tmp_path, versuche):
    """Antwortet der Miniserver ueber TLS, wenn auch mit einem Fehler (hier
    getkey2 ohne Schluessel), spricht er TLS: kein Versuch im Klartext."""
    async def lauf():
        ms = await _ms(Zertifizierungsstelle(tmp_path).server("localhost"))
        ms.getkey = ""
        app = W.App(_zugang(ms.port))
        try:
            with pytest.raises(RuntimeError, match="getkey2"):
                await app.start()
        finally:
            await app._close_conn()
            await ms.stop()
    asyncio.run(lauf())
    assert versuche == [True]


def test_port_zu_nennt_den_ersten_fehler(versuche):
    """Lauscht am Port niemand, scheitert auch das andere Schema sofort; gemeldet
    wird der erste Fehler, und er zaehlt als nicht erreichbar (der Konfigurator
    speichert dann trotzdem, wie bisher)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    async def lauf():
        app = W.App(_zugang(port))
        with pytest.raises(aiohttp.ClientConnectorError) as ei:
            await app.reconnect(_zugang(port))
        return ei.value
    err = asyncio.run(lauf())
    assert versuche == [True, False]
    assert err.port == port and not isinstance(err, aiohttp.ClientSSLError)
    assert miniserver._ms_unerreichbar(err)


def test_stumm_auf_tls(monkeypatch, versuche):
    """Schweigt die Gegenstelle auf den TLS-Gruss, endet der Versuch mit der
    Antwortfrist und HTTP folgt; schweigt sie auf beides, ist der Fehler die
    Frist des ersten Versuchs (nicht erreichbar)."""
    ersetzen(monkeypatch, "_ms_antwortfrist", lambda: 0.5)

    async def lauf():
        ms = await _ms()
        tor, port = await _tor(ms.port)
        stumm = await asyncio.start_server(_schweigen, "127.0.0.1", 0)
        app = W.App(_zugang(port))
        try:
            await app.start()
            await _befehl_kommt_an(app, ms)
            tls = app.ms_tls
            with pytest.raises(TimeoutError, match="keine Antwort innerhalb von 0.5 s") as ei:
                await app.reconnect(_zugang(stumm.sockets[0].getsockname()[1]))
            return tls, ei.value
        finally:
            await app._close_conn()
            await ms.stop()
            for srv in (tor, stumm):
                srv.close()
    tls, err = asyncio.run(lauf())
    assert tls is False and miniserver._ms_unerreichbar(err)
    assert versuche == [True, False, True, False]
