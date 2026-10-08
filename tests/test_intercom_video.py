"""Kamera der Intercom (Detailseite, Kamera-Pane, /mjpeg): eine in LoxPanel
eingetragene Adresse hat Vorrang, sonst nimmt LoxPanel die aus den gesicherten
Details des Miniservers (videoInfo: streamUrl, user, pass; Strukturdoku 16.0
und 17.0) und merkt sie bis zur naechsten Struktur. Miniserver (Command
Encryption) und Kamera sind Nachbauten."""
import asyncio

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from lox import Miniserver, W, anlage, bloecke, intercom_baustein, intercom_v2_baustein, neue_app, serve

KAMERA_PASS = "Bild-Kennwort-2"


@pytest.mark.parametrize("details, soll", [
    ({"videoInfo": {"streamUrl": " http://10.0.0.7/mjpg/video.mjpg ", "user": " kamera ", "pass": "x y"}},
     {"url": "http://10.0.0.7/mjpg/video.mjpg", "user": "kamera", "pass": "x y"}),
    # so, wie es in Loxone Config eingetragen wurde: ohne Schema
    ({"videoInfo": {"streamUrl": "192.168.1.99/snap.jpeg"}}, {"url": "http://192.168.1.99/snap.jpeg", "user": "", "pass": ""}),
    ({"videoInfo": {"streamUrl": "https://user@10.0.0.8:8443/live"}},
     {"url": "https://user@10.0.0.8:8443/live", "user": "", "pass": ""}),
    # Platzhalter ohne Miniserver-Adresse: kein Video (der Aufrufer gibt sie immer mit)
    ({"videoInfo": {"streamUrl": "http://cloudDNS:8081/mjpg/video.mjpg"}}, {"grund": W.KEIN_VIDEO}),
    ({"videoInfo": {"streamUrl": "https://remoteConnect/cam/1"}}, {"grund": W.KEIN_VIDEO}),
    ({"videoInfo": {"streamUrl": "", "user": "kamera"}, "audioInfo": {"host": "10.0.0.9"}}, {"grund": W.KEIN_VIDEO}),
    ({"audioInfo": {"host": "10.0.0.9"}}, {"grund": W.KEIN_VIDEO}),
    ({"videoInfo": "kaputt"}, {"grund": W.KEIN_VIDEO}),
    ({"videoInfo": {"streamUrl": "http://[::1/x"}}, {"grund": W.KEIN_VIDEO}),
])
def test_kamera_aus_details(details, soll):
    assert W._kamera_aus_details(details) == soll


@pytest.mark.parametrize("stream, soll", [
    # cloudDNS: Adresse des Miniservers, der Port der Kamera-Adresse bleibt
    ("http://cloudDNS:8081/mjpg/video.mjpg", "http://192.168.1.5:8081/mjpg/video.mjpg"),
    ("cloudDNS/snap.jpeg", "http://192.168.1.5/snap.jpeg"),
    ("http://kamera@CloudDNS:8081/x", "http://kamera@192.168.1.5:8081/x"),
    # remoteConnect: Host UND Port des Miniservers, https Pflicht
    ("https://remoteConnect/cam/1", "https://192.168.1.5:8443/cam/1"),
    ("remoteConnect:443/cam/1", "https://192.168.1.5:8443/cam/1"),
    ("http://remoteconnect:80/cam/1?x=1", "https://192.168.1.5:8443/cam/1?x=1"),
    # echter Host: unveraendert
    ("http://10.0.0.7/mjpg/video.mjpg", "http://10.0.0.7/mjpg/video.mjpg"),
])
def test_platzhalter_werden_zum_miniserver(stream, soll):
    """Strukturdoku 17.0 (Intercom, streamUrl): cloudDNS wird durch die IP des
    Miniservers ersetzt, remoteConnect durch Host und Port des Miniservers mit
    https; der Miniserver leitet das Kamerabild weiter (Codex-Befund an #110)."""
    assert W._kamera_aus_details({"videoInfo": {"streamUrl": stream, "user": "k", "pass": "p"}},
                                 "192.168.1.5", 8443) == {"url": soll, "user": "k", "pass": "p"}
    ipv6 = W._kamera_aus_details({"videoInfo": {"streamUrl": "http://cloudDNS:8081/v"}}, "fd00::7", 443)
    assert ipv6["url"] == "http://[fd00::7]:8081/v"


async def _kamera():
    """Kamera mit Anmeldung (Basic) -> (runner, port, Abrufe)."""
    abrufe = []

    async def bild(request):
        abrufe.append(request.path)
        if request.headers.get("Authorization") != aiohttp.BasicAuth("kamera", KAMERA_PASS).encode():
            return web.Response(status=401)
        return web.Response(body=b"--frame " + request.path.encode(), content_type="multipart/x-mixed-replace")
    cam = web.Application()
    cam.router.add_get("/{pfad:.*}", bild)
    runner, port = await serve(cam)
    return runner, port, abrufe


async def _aufbau(gesichert: dict, bausteine=None):
    ms = await Miniserver().start()
    ms.gesichert = gesichert
    app = neue_app(ms)
    app.user = ms.benutzer
    bausteine = bausteine or [intercom_baustein()]
    app._apply_structure(anlage({c["uuidAction"]: c for c, _ in bausteine}))
    app.states = {k: v for _, st in bausteine for k, v in st.items()}
    app.intercom_cfg = {}
    ui = web.Application()
    ui["app"] = app
    ui.router.add_get("/mjpeg", W.mjpeg_handler)
    return ms, app, TestClient(TestServer(ui))


def _video(app, uuid="IC") -> dict:
    """Video- oder Status-Block der Detailseite."""
    v = app.render({"view": "control", "id": uuid})
    return (bloecke(v, "video") or bloecke(v, "status"))[0]


async def _hole(cl, uuid="IC") -> tuple[int, bytes]:
    r = await cl.get("/mjpeg", params={"id": uuid})
    return r.status, await r.read()


def test_video_vom_miniserver(miniserver_http):
    """Ohne eigene Adresse: Kamera vom Miniserver, einmal gefragt und gemerkt,
    auch wenn zwei Panels zugleich laden; nach einer neuen Struktur neu."""
    async def lauf():
        cam_runner, cam_port, abrufe = await _kamera()
        ms, app, cl = await _aufbau({"IC": {"videoInfo": {
            "streamUrl": f"127.0.0.1:{cam_port}/mjpg/video.mjpg", "user": "kamera", "pass": KAMERA_PASS},
            "audioInfo": {"host": "10.0.0.9"}}})
        try:
            async with cl:
                assert _video(app) == {"k": "video", "src": "/mjpeg?id=IC"}, "steht schon da, bevor gefragt ist"
                app._dirty = False
                assert await _hole(cl) == (200, b"--frame /mjpg/video.mjpg")
                assert app._dirty, "Seite neu zeichnen: jetzt ist bekannt, ob es Bild gibt"
                assert await _hole(cl) == (200, b"--frame /mjpg/video.mjpg")
                assert len(ms.fenc) == 1 and len(abrufe) == 2
                assert _video(app) == {"k": "video", "src": "/mjpeg?id=IC"}
                # neue Struktur (in Loxone Config gespeichert): neu fragen, zwei Panels zugleich -> einmal
                app._apply_structure(anlage({"IC": intercom_baustein()[0]}))
                assert app.ms_video == {}
                assert await asyncio.gather(_hole(cl), _hole(cl)) == [(200, b"--frame /mjpg/video.mjpg")] * 2
                assert len(ms.fenc) == 2
        finally:
            await app.icon_session.close()
            await ms.stop()
            await cam_runner.cleanup()
    asyncio.run(lauf())


def test_eigene_adresse_hat_vorrang(miniserver_http):
    async def lauf():
        cam_runner, cam_port, abrufe = await _kamera()
        ms, app, cl = await _aufbau({"IC": {"videoInfo": {"streamUrl": f"127.0.0.1:{cam_port}/vom-miniserver"}}})
        app.intercom_cfg = {"IC": {"url": f" http://127.0.0.1:{cam_port}/eigene ", "user": "kamera",
                                   "pass": KAMERA_PASS}}
        try:
            async with cl:
                assert await _hole(cl) == (200, b"--frame /eigene")
                assert ms.fenc == [] and abrufe == ["/eigene"]
                app.intercom_cfg = {"IC": f"http://127.0.0.1:{cam_port}/alt"}   # altes Format: nur die Adresse
                assert (await _hole(cl))[0] == 502, "ohne Anmeldung lehnt die Kamera ab"
                assert ms.fenc == [] and abrufe[-1] == "/alt"
        finally:
            await app.icon_session.close()
            await ms.stop()
            await cam_runner.cleanup()
    asyncio.run(lauf())


@pytest.mark.parametrize("gesichert, grund", [
    ({"audioInfo": {"host": "10.0.0.9"}}, W.KEIN_VIDEO),
    ({"videoInfo": {"streamUrl": "", "user": "kamera"}}, W.KEIN_VIDEO),
])
def test_ohne_kamera_beim_miniserver(miniserver_http, gesichert, grund):
    """Nennt der Miniserver keine nutzbare Kamera, sagt die Seite warum - auch
    in der Kamera-Pane - und fragt bis zur naechsten Struktur nicht wieder."""
    async def lauf():
        ms, app, cl = await _aufbau({"IC": gesichert})
        try:
            async with cl:
                assert (await _hole(cl))[0] == 404
                assert (await _hole(cl))[0] == 404
                assert len(ms.fenc) == 1
                assert _video(app) == {"k": "status", "text": grund}
                assert [b for b in app.intercom_blocks("IC") if b["k"] in ("video", "status")] == [
                    {"k": "status", "text": grund}]
        finally:
            await app.icon_session.close()
            await ms.stop()
    asyncio.run(lauf())


def test_clouddns_laeuft_ueber_den_miniserver(miniserver_http):
    """Nennt der Miniserver "cloudDNS" als Host, holt /mjpeg das Bild von der
    Adresse des Miniservers mit dem Port aus der streamUrl - im Test ist das
    die Kamera auf 127.0.0.1."""
    async def lauf():
        cam_runner, cam_port, abrufe = await _kamera()
        ms, app, cl = await _aufbau({"IC": {"videoInfo": {"streamUrl": f"http://cloudDNS:{cam_port}/v",
                                                           "user": "kamera", "pass": KAMERA_PASS}}})
        app.host = "127.0.0.1"
        try:
            async with cl:
                assert await _hole(cl) == (200, b"--frame /v")
                assert app.ms_video["IC"]["url"] == f"http://127.0.0.1:{cam_port}/v" and abrufe == ["/v"]
        finally:
            await app.icon_session.close()
            await ms.stop()
            await cam_runner.cleanup()
    asyncio.run(lauf())


def test_fehler_wird_nicht_gemerkt(miniserver_http):
    """Keine Rechte oder Miniserver weg: nichts merken, beim naechsten Mal neu
    fragen; die Seite zeigt das Video weiter an."""
    async def lauf():
        cam_runner, cam_port, _ = await _kamera()
        ms, app, cl = await _aufbau({"IC": {"videoInfo": {"streamUrl": f"http://127.0.0.1:{cam_port}/v",
                                                           "user": "kamera", "pass": KAMERA_PASS}}})
        ms.gesichert_code = "403"
        try:
            async with cl:
                assert (await _hole(cl))[0] == 404
                assert app.ms_video == {} and _video(app)["k"] == "video"
                ms.gesichert_code = "200"
                assert await _hole(cl) == (200, b"--frame /v")
                assert len(ms.fenc) == 2
        finally:
            await app.icon_session.close()
            await ms.stop()
            await cam_runner.cleanup()
    asyncio.run(lauf())


def test_ohne_kennzeichen_keine_anfrage(miniserver_http):
    """Baustein ohne securedDetails (etwa die Loxone Intercom am Baustein
    Intercom): kein Video, keine Anfrage an den Miniserver."""
    async def lauf():
        ms, app, cl = await _aufbau({}, [intercom_v2_baustein()])
        try:
            async with cl:
                assert (await _hole(cl, "IC2V"))[0] == 404
                assert ms.fenc == [] and app.ms_video == {}
                assert _video(app, "IC2V") == {"k": "status", "text": W.KEIN_VIDEO}
        finally:
            await app.icon_session.close()
            await ms.stop()
    asyncio.run(lauf())


def test_v2_mit_gesicherten_details(miniserver_http):
    """Eine andere Tuerstation am Baustein Intercom: nennt der Miniserver eine
    Kamera, zeigt LoxPanel sie wie bei der Tuersteuerung."""
    async def lauf():
        cam_runner, cam_port, _ = await _kamera()
        ms, app, cl = await _aufbau({"IC2V": {"videoInfo": {"streamUrl": f"127.0.0.1:{cam_port}/tor",
                                                             "user": "kamera", "pass": KAMERA_PASS}}},
                                    [intercom_v2_baustein(geraet=0, gesichert=True)])
        try:
            async with cl:
                assert _video(app, "IC2V") == {"k": "video", "src": "/mjpeg?id=IC2V"}
                assert await _hole(cl, "IC2V") == (200, b"--frame /tor")
        finally:
            await app.icon_session.close()
            await ms.stop()
            await cam_runner.cleanup()
    asyncio.run(lauf())
