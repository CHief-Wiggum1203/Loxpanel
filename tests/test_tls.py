"""Zertifikat des Miniservers pruefen (verify_tls).

Mit verify_tls=true prueft LoxPanel gegen den Standard-Truststore, und zwar
ueberall: Anmeldung und Struktur (loxone_api), WebSocket (LoxoneWS) und die
icon_session (Statistik, Bilder, gesicherte Details, Cover von aussen). Frueher
luden die Kontexte von WebSocket und icon_session keine einzige
Zertifizierungsstelle: Die Anmeldung gelang, danach scheiterte jede Verbindung,
auch mit einem Zertifikat, dem das System vertraut.

Die Test-CA entsteht zur Laufzeit (lox.Zertifizierungsstelle) und steht als
einzige im Standard-Truststore: OpenSSL liest SSL_CERT_FILE und SSL_CERT_DIR,
wenn ein Kontext die Standard-CAs laedt. Gegenueber steht der Miniserver-Nachbau
aus lox.py, ueber HTTPS/WSS wie ein Gen2 (oder HTTP wie ein Gen1).
"""
from __future__ import annotations

import asyncio
import ssl
import threading

import aiohttp
import pytest
from aiohttp import web

import loxone_ws
from lox import Miniserver, W, Zertifizierungsstelle, anlage, serve
from loxone_ws import LoxoneWS

BILD = b"\xff\xd8\xff\xe0Cover"
NAME = "localhost"   # der Name im Zertifikat; der Nachbau lauscht auf 127.0.0.1


@pytest.fixture
def truststore(tmp_path, monkeypatch) -> Zertifizierungsstelle:
    """Eigene CA als einzige im Standard-Truststore (nur fuer diesen Test)."""
    ca = Zertifizierungsstelle(tmp_path / "vertraut")
    (tmp_path / "leer").mkdir()
    monkeypatch.setenv("SSL_CERT_FILE", str(ca.datei))
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path / "leer"))
    return ca


@pytest.fixture
def fremde_ca(tmp_path) -> Zertifizierungsstelle:
    """CA, die nicht im Truststore steht."""
    return Zertifizierungsstelle(tmp_path / "fremd", "Fremde-CA")


async def _abonniert(ms: Miniserver) -> bool:
    """LoxoneWS schickt enablebinstatusupdate als Letztes und wartet nicht auf
    eine Antwort; am Nachbau kommt es kurz danach an."""
    for _ in range(100):
        if "jdev/sps/enablebinstatusupdate" in ms.ws_befehle:
            return True
        await asyncio.sleep(0.02)
    return False


async def _bildserver(kontext: ssl.SSLContext) -> tuple[web.AppRunner, int]:
    """HTTPS-Server mit einem Cover, wie ihn fetch_cover und die iTunes-Suche
    ausserhalb des Miniservers abfragen."""
    app = web.Application()

    async def cover(_r):
        return web.Response(body=BILD, content_type="image/jpeg")
    app.router.add_get("/cover.jpg", cover)
    return await serve(app, ssl_context=kontext)


async def _miniserver(kontext: ssl.SSLContext | None) -> Miniserver:
    ms = Miniserver()
    ms.struktur = anlage({})
    return await ms.start(ssl_context=kontext)


def _app(ms: Miniserver, host: str, verify_tls: bool) -> W.App:
    return W.App({"host": host, "port": ms.port, "user": ms.benutzer, "pass": ms.kennwort,
                  "verify_tls": verify_tls})


def test_kontexte_laden_den_truststore(truststore):
    """Beide Kontexte von LoxPanel pruefen wie der von loxone_api: Zertifikat und
    Name, gegen die Standard-CAs. Ohne Pruefung bleibt es wie bisher."""
    pruefend = (LoxoneWS(NAME, 443, "u", "jwt", verify_tls=True)._ssl(),
                W.App({"host": NAME, "verify_tls": True})._ssl_ctx())
    for ctx in pruefend:
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True
        assert ctx.cert_store_stats()["x509_ca"] > 0
    offen = (LoxoneWS(NAME, 443, "u", "jwt", verify_tls=False)._ssl(),
             W.App({"host": NAME, "verify_tls": False})._ssl_ctx())
    for ctx in offen:
        assert ctx.verify_mode == ssl.CERT_NONE
        assert ctx.check_hostname is False


@pytest.mark.parametrize("aussteller, host, fehler", [
    ("vertraut", NAME, None),
    ("fremd", NAME, "unable to get local issuer certificate"),
    ("vertraut", "127.0.0.1", "IP address mismatch"),       # Zertifikat nennt nur den Namen
], ids=["vertraut", "fremde-ca", "ip-statt-name"])
def test_ws_prueft_zertifikat(truststore, fremde_ca, aussteller, host, fehler):
    """LoxoneWS.connect() direkt, an loxone_api vorbei: verbindet nur mit einem
    Zertifikat einer vertrauten CA, und nur ueber den Namen, den es nennt."""
    ca = truststore if aussteller == "vertraut" else fremde_ca

    async def lauf():
        ms = await _miniserver(ca.server(NAME))
        ws = LoxoneWS(host, ms.port, ms.benutzer, ms.token, hash_alg=ms.hash_alg, verify_tls=True)
        try:
            if fehler is None:
                await ws.connect()
                assert await _abonniert(ms)
            else:
                with pytest.raises(aiohttp.ClientConnectorCertificateError) as ei:
                    await ws.connect()
                assert fehler in ei.value.certificate_error.verify_message
                assert ms.ws_befehle == []
        finally:
            await ws.close()
            await ms.stop()
    asyncio.run(lauf())


@pytest.mark.parametrize("gen", ["Gen2", "Gen1"])
def test_start_mit_pruefung(truststore, fremde_ca, gen, request):
    """App.start() mit verify_tls=true: Anmeldung, WebSocket und icon_session
    stehen, Befehle und Cover einer vertrauten Gegenstelle kommen an, das Cover
    eines Servers mit fremder CA nicht. Gen1 (Port 80) spricht mit dem
    Miniserver HTTP; dort pruefen nur die HTTPS-Abrufe nach aussen."""
    if gen == "Gen1":
        request.getfixturevalue("miniserver_http")

    async def lauf():
        ms = await _miniserver(truststore.server(NAME) if gen == "Gen2" else None)
        vertraut, port_vertraut = await _bildserver(truststore.server(NAME))
        fremd, port_fremd = await _bildserver(fremde_ca.server(NAME))
        app = _app(ms, NAME, True)
        try:
            await app.start()
            assert await _abonniert(ms)
            status, _, _ = await app._ms_http("jdev/sps/io/L/On", 5)
            assert status == 200 and ms.io == ["sps/io/L/On"]
            assert await app.fetch_cover(f"https://{NAME}:{port_vertraut}/cover.jpg") == (BILD, "image/jpeg")
            assert await app.fetch_cover(f"https://{NAME}:{port_fremd}/cover.jpg") is None
        finally:
            await app._close_conn()
            for runner in (vertraut, fremd):
                await runner.cleanup()
            await ms.stop()
    asyncio.run(lauf())


def test_ohne_pruefung_wie_bisher(truststore, fremde_ca):
    """verify_tls=false (Standard): kein Abgleich mit dem Truststore und kein
    Namensvergleich; fremde CA und Zugriff per IP gehen wie bisher."""
    async def lauf():
        ms = await _miniserver(fremde_ca.server(NAME))
        fremd, port_fremd = await _bildserver(fremde_ca.server(NAME))
        app = _app(ms, "127.0.0.1", False)
        try:
            await app.start()
            assert await _abonniert(ms)
            status, _, _ = await app._ms_http("jdev/sps/io/L/On", 5)
            assert status == 200
            assert await app.fetch_cover(f"https://127.0.0.1:{port_fremd}/cover.jpg") == (BILD, "image/jpeg")
        finally:
            await app._close_conn()
            await fremd.cleanup()
            await ms.stop()
    asyncio.run(lauf())


def test_kontext_entsteht_neben_der_ereignisschleife(truststore, cfg_ordner, monkeypatch):
    """Die Standard-CAs zu laden blockiert (auf einem Panel mit ARM-CPU
    spuerbar). start() und reconnect() lassen es darum in einem eigenen Thread
    laufen, wie loxone_api fuer seinen Teil."""
    threads: list[int] = []
    echt = loxone_ws.ms_ssl_kontext

    def mitschreiben(verify_tls):
        threads.append(threading.get_ident())
        return echt(verify_tls)
    monkeypatch.setattr(loxone_ws, "ms_ssl_kontext", mitschreiben)
    monkeypatch.setattr(W, "ms_ssl_kontext", mitschreiben)

    async def lauf() -> int:
        ms = await _miniserver(truststore.server(NAME))
        app = _app(ms, NAME, True)
        zugang = {"host": NAME, "port": ms.port, "user": ms.benutzer, "pass": ms.kennwort, "verify_tls": True}
        try:
            await app.start()
            await app.reconnect(zugang)
        finally:
            await app._close_conn()
            await ms.stop()
        return threading.get_ident()
    schleife = asyncio.run(lauf())
    # start(): WebSocket und icon_session, reconnect(): icon_session
    assert len(threads) == 3
    assert schleife not in threads
