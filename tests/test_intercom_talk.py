"""Native Anruf-API: gesicherte Details, Abbruchrennen und Lease ohne Hardware."""
import asyncio

import aiohttp
from aiohttp import web
import pytest

from lox import Miniserver, W, anlage, intercom_baustein, intercom_v2_baustein, neue_app, serve
from intercom_talk import IntercomTalk, TalkBusy

SESSION = "12345678-1234-1234-1234-123456789012"
OTHER = "abcdefab-1234-1234-1234-123456789012"
TOKEN = "test-only-native-token"
SIP = {"host": "192.0.2.20", "user": "tuer", "pass": "bleibt-im-server"}
MEDIA = {"remoteHost": "192.0.2.20", "remotePort": 4000, "codec": "PCMA",
         "payloadType": 8, "sampleRate": 8000, "ptime": 20}


class AudioCall:
    def __init__(self, host, user, password, port):
        self.args = host, user, password, port
        self.state, self.error, self.media = "connecting", "", MEDIA.copy()
        self.release = asyncio.Event()
        self.stops = 0

    async def start(self):
        await self.release.wait()
        self.state = "connected"
        return self.media

    async def stop(self):
        self.stops += 1
        self.state = "idle"


async def _until(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0.01)
    assert predicate(), "Anrufzustand wurde nicht erreicht"


def test_session_abbruch_lease_und_remote_bye():
    async def run():
        async def credentials(uuid):
            return SIP.copy()
        manager = IntercomTalk(credentials, factory=AudioCall, lease=0.1)
        try:
            # Stop kann Start auf einer anderen HTTP-Verbindung ueberholen.
            await manager.stop(SESSION)
            assert (await manager.start(SESSION, "IC", 12345))["state"] == "idle"
            assert manager.call is None
            first = await manager.start(OTHER, "IC", 12345)
            assert first["state"] == "connecting"
            await _until(lambda: manager.call is not None)
            call = manager.call
            assert call.args == (SIP["host"], SIP["user"], SIP["pass"], 12345)
            assert await manager.start(OTHER, "IC", 12345) == first
            with pytest.raises(TalkBusy):
                await manager.start("bbbbbbbbbbbbbbbb", "IC", 12346)
            call.release.set()
            await _until(lambda: manager.state == "connected")
            assert manager.status(OTHER)["media"] == MEDIA
            assert SIP["pass"] not in str(manager.status(OTHER))
            assert manager.status(SESSION)["state"] == "idle"
            # Ein Ende der Gegenstelle muss sofort im Snapshot sichtbar sein.
            call.state = "idle"
            assert manager.status(OTHER)["state"] == "idle"
            await manager.start("cccccccccccccccc", "IC", 12346)
            await _until(lambda: manager.call is not call and manager.call is not None)
            second = manager.call
            await _until(lambda: manager.state == "idle")
            assert second.stops == 1, "Ohne nativen Heartbeat muss die Verbindung enden"
        finally:
            await manager.close()
    asyncio.run(run())


def test_stop_waehrend_gesicherte_details_laden():
    async def run():
        waiting = asyncio.Event()
        created = []

        async def credentials(uuid):
            await waiting.wait()
            return SIP

        def factory(*args):
            created.append(args)
            return AudioCall(*args)
        manager = IntercomTalk(credentials, factory=factory)
        try:
            await manager.start(SESSION, "IC", 12345)
            assert (await manager.stop(SESSION))["state"] == "ending"
            await _until(lambda: manager.state == "idle")
            waiting.set()
            await asyncio.sleep(0)
            assert not created
            assert (await manager.stop(SESSION))["state"] == "idle"
        finally:
            await manager.close()
    asyncio.run(run())


def test_credential_fehler_verhindert_anruf():
    async def run():
        async def credentials(uuid):
            raise ValueError(W.KEIN_SIP)
        manager = IntercomTalk(credentials)
        try:
            await manager.start(SESSION, "IC", 12345)
            await _until(lambda: manager.state == "error")
            assert manager.status(SESSION)["message"] == W.KEIN_SIP
            assert manager.call is None
        finally:
            await manager.close()
    asyncio.run(run())


def test_native_api_mit_gesicherten_details(miniserver_http, monkeypatch):
    monkeypatch.setenv("LOXPANEL_INTERCOM_TOKEN", TOKEN)

    async def run():
        ms = await Miniserver().start()
        ms.gesichert = {"IC": {"audioInfo": SIP.copy()}, "IC2V": {"audioInfo": SIP.copy()}}
        app = neue_app(ms)
        app.user = ms.benutzer
        ic, _ = intercom_baustein()
        v2, _ = intercom_v2_baustein(gesichert=True)
        app._apply_structure(anlage({"IC": ic, "IC2V": v2}))
        app.intercom_talk.factory = AudioCall
        ui = web.Application()
        ui["app"] = app
        ui.router.add_post("/api/intercom/talk/start", W.api_intercom_talk_start)
        ui.router.add_get("/api/intercom/talk/status", W.api_intercom_talk_status)
        ui.router.add_post("/api/intercom/talk/stop", W.api_intercom_talk_stop)
        runner, port = await serve(ui)
        base = f"http://127.0.0.1:{port}/api/intercom/talk/"
        headers = {"X-LoxPanel-Intercom": TOKEN}
        body = {"session": SESSION, "uuid": "IC", "rtpPort": 12345}
        try:
            async with aiohttp.ClientSession() as client:
                async with client.post(base + "start", json=body) as r:
                    assert r.status == 403
                async with client.post(base + "start", json=body, headers={"X-LoxPanel-Intercom": "wrong"}) as r:
                    assert r.status == 403
                for changes in ({"uuid": "IC2V"}, {"rtpPort": True}, {"rtpPort": 506}, {"session": "short"}):
                    async with client.post(base + "start", json={**body, **changes}, headers=headers) as r:
                        assert r.status == 400
                assert ms.fenc == [], "Gen-2 wird vor dem Lesen seiner SIP-Daten abgelehnt"
                async with client.post(base + "start", json=body, headers=headers) as r:
                    assert r.status == 200
                    assert (await r.json())["state"] == "connecting"
                await _until(lambda: app.intercom_talk.call is not None)
                call = app.intercom_talk.call
                assert call.args == (SIP["host"], SIP["user"], SIP["pass"], 12345)
                call.release.set()
                await _until(lambda: app.intercom_talk.state == "connected")
                async with client.get(base + "status", params={"session": SESSION}, headers=headers) as r:
                    data = await r.json()
                    assert data["media"] == MEDIA
                    assert SIP["pass"] not in str(data)
                async with client.post(base + "stop", json={"session": SESSION}, headers=headers) as r:
                    assert r.status == 200
                await _until(lambda: app.intercom_talk.state == "idle")
                assert call.stops == 1
                # Auch im lokalen Browser ohne Android-Token gibt es keine API.
                monkeypatch.delenv("LOXPANEL_INTERCOM_TOKEN")
                async with client.post(base + "start", json=body, headers=headers) as r:
                    assert r.status == 403
                assert ms.io == [], "Anrufstart sendet keinen Tuer-/Klingelbefehl"
        finally:
            await runner.cleanup()
            await app.close()
            await ms.stop()
    asyncio.run(run())


@pytest.mark.parametrize("secured, audio", [
    (False, SIP),
    (True, None),
    (True, {}),
    (True, {"user": "tuer", "pass": SIP["pass"]}),
    (True, "unbrauchbar"),
], ids=["ohne-kennzeichen", "ohne-audioInfo", "leeres-audioInfo", "ohne-sip-host", "falscher-audioInfo-typ"])
def test_native_api_ohne_sip_hat_keinen_kamera_fallback(secured, audio, miniserver_http, monkeypatch):
    """Die Kameradaten von PR #110 werden niemals als Audioziel verwendet."""
    monkeypatch.setenv("LOXPANEL_INTERCOM_TOKEN", TOKEN)

    async def run():
        ms = await Miniserver().start()
        details = {"videoInfo": {"streamUrl": "http://192.0.2.29/video", "user": "kamera", "pass": "bild-pass"}}
        if audio is not None:
            details["audioInfo"] = audio
        ms.gesichert = {"IC": details}
        app = neue_app(ms)
        app.user = ms.benutzer
        ic, _ = intercom_baustein()
        if not secured:
            del ic["securedDetails"]
        app._apply_structure(anlage({"IC": ic}))
        app.intercom_cfg = {"IC": {"url": "http://192.0.2.30/eigene-kamera", "user": "eigene", "pass": "eigener-pass"}}
        created = []

        def factory(*args):
            created.append(args)
            return AudioCall(*args)

        app.intercom_talk.factory = factory
        ui = web.Application()
        ui["app"] = app
        ui.router.add_post("/api/intercom/talk/start", W.api_intercom_talk_start)
        ui.router.add_get("/api/intercom/talk/status", W.api_intercom_talk_status)
        runner, port = await serve(ui)
        base = f"http://127.0.0.1:{port}/api/intercom/talk/"
        headers = {"X-LoxPanel-Intercom": TOKEN}
        try:
            async with aiohttp.ClientSession() as client:
                async with client.post(base + "start", json={"session": SESSION, "uuid": "IC", "rtpPort": 12345},
                                       headers=headers) as r:
                    assert r.status == 200
                    assert (await r.json())["state"] == "connecting"
                await _until(lambda: app.intercom_talk.state == "error")
                async with client.get(base + "status", params={"session": SESSION}, headers=headers) as r:
                    assert r.status == 200
                    data = await r.json()
                assert data["state"] == "error"
                assert data["message"] == (W.KEIN_SIP if secured else "Der Baustein hat keine gesicherten Details")
                assert "media" not in data
                assert all(secret not in str(data) for secret in (SIP["pass"], "bild-pass", "eigener-pass"))
                assert created == [] and app.intercom_talk.call is None
                assert len(ms.fenc) == int(secured)
                assert ms.io == [], "Audiofehler duerfen keine Tuer- oder Klingelbefehle ausloesen"
        finally:
            await runner.cleanup()
            await app.close()
            await ms.stop()
    asyncio.run(run())


def test_native_block_gen1_und_ausgaenge_unveraendert():
    app = W.App({"host": ""})
    ic, states = intercom_baustein(bell=1)
    ic["details"]["deviceType"] = 0
    v2, v2_states = intercom_v2_baustein(gesichert=True, bell=1)
    app._apply_structure(anlage({"IC": ic, "IC2V": v2}))
    app.states = {**states, **v2_states}
    detail = app.render({"view": "control", "id": "IC"})["blocks"]
    assert {"k": "intercom-talk", "uuid": "IC", "nativeOnly": True} in detail
    rows = [b for b in detail if b["k"] == "row"]
    assert rows[0]["cells"] == [{"label": "Tür öffnen", "cmd": {"uuid": "IC/1", "cmd": "pulse"}}]
    assert rows[1]["cells"][0]["cmd"] == {"uuid": "IC", "cmd": "answer"}
    assert {"k": "intercom-talk", "uuid": "IC", "nativeOnly": True} in app.intercom_blocks("IC")
    v2_pane = app.intercom_blocks("IC2V")
    assert v2_pane is not None, "Gen-2-Kamera-Panes aus PR #110 bleiben unterstuetzt"
    assert {"k": "video", "src": "/mjpeg?id=IC2V"} in v2_pane
    assert {"label": "Tür öffnen", "cmd": {"uuid": "IC2V/1", "cmd": "pulse"}} in next(
        b["cells"] for b in v2_pane if b["k"] == "row")
    v2_detail = app.render({"view": "control", "id": "IC2V"})["blocks"]
    assert not any(b["k"] == "intercom-talk" for b in v2_pane + v2_detail)
    commands = [cell["cmd"] for b in v2_detail if b["k"] == "row" for cell in b["cells"] if "cmd" in cell]
    assert {"uuid": "IC2V", "cmd": "playTts/1"} in commands
    assert {"uuid": "IC2V", "cmd": "mute/1"} in commands
    assert {"uuid": "IC2V", "cmd": "answer"} in commands
