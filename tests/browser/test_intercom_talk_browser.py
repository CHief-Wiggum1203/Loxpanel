"""Natives Gegensprechen in der echten Visu (Chromium).

Die LoxKiosk-Bruecke liefert den Gespraechsstatus; Detailseite und Kamera-Pane
zeigen dieselbe Bedienung. Ohne vollstaendige Bruecke und fuer IntercomV2
bleibt sie verborgen. Status-Polling darf das Kamerabild nicht neu laden;
Tuer- und Klingelbefehle gehen unveraendert zum Miniserver aus tests/lox.py.
"""
import asyncio
import base64

import pytest
from aiohttp import web

from lox import Miniserver, W, anlage, intercom_baustein, intercom_v2_baustein, neue_app, serve, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright, expect  # noqa: E402

pytestmark = pytest.mark.browser

# Die bisherigen Kiosk-Methoden einer alten App ohne Gegensprechen.
KIOSK_JS = """window.LoxKiosk = {
  setDisplayOff() {}, turnScreenOff() {}, turnScreenOn() {}, isScreenOn() { return true; }
};"""
FULLY_JS = """window.fully = {
  turnScreenOff() {}, turnScreenOn() {}, isScreenOn() { return true; }
};"""
# Vertrag der nativen Bruecke: Boolean fuer Auftraege, JSON-String fuer Status.
TALK_JS = KIOSK_JS + """
window.__talkCalls = []; window.__talkPolls = 0;
window.__talkStatus = { state: 'idle', uuid: '', message: '' };
Object.assign(window.LoxKiosk, {
  startIntercom(uuid) {
    window.__talkCalls.push(['start', uuid]);
    window.__talkStatus = { state: 'connecting', uuid, message: '' };
    return true;
  },
  stopIntercom() {
    window.__talkCalls.push(['stop']);
    window.__talkStatus = { state: 'ending', uuid: window.__talkStatus.uuid, message: '' };
    return true;
  },
  intercomStatus() { window.__talkPolls++; return JSON.stringify(window.__talkStatus); }
});"""

# Dekodierbares Bild fuer den Kamerapfad; Requests werden mitgezaehlt.
PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


async def _visu(schritt, *, bridge=TALK_JS, kamera=False, device_type=1, typ="Intercom", kamera_aus_ms=False):
    ms = await Miniserver().start()
    app = neue_app(ms)
    app.user = ms.benutzer
    ic, states = (intercom_v2_baustein(geraet=device_type, gesichert=True)
                  if typ == "IntercomV2" else intercom_baustein(klingeln=()))
    ic = dict(ic, isFavorite=True, details=dict(ic["details"], deviceType=device_type))
    uuid = ic["uuidAction"]
    app._apply_structure(anlage({uuid: ic}))
    app.states = states
    fehler, bilder = [], []
    cam_runner = None
    if kamera_aus_ms:
        # Keine Browser-Abkuerzung: echte securedDetails und /mjpeg-Relais.
        async def kamerabild(request):
            assert request.headers.get("Authorization") == "Basic " + base64.b64encode(b"kamera:bild-pass").decode()
            bilder.append(request.path)
            return web.Response(body=PIXEL, content_type="image/png")

        camera = web.Application()
        camera.router.add_get("/stream", kamerabild)
        cam_runner, cam_port = await serve(camera)
        ms.gesichert = {uuid: {"videoInfo": {"streamUrl": f"http://127.0.0.1:{cam_port}/stream",
                                           "user": "kamera", "pass": "bild-pass"},
                                "audioInfo": {"host": "192.0.2.20", "user": "tuer", "pass": "sip-pass"}}}
        app.intercom_cfg = {}
    else:
        app.intercom_cfg = {uuid: {"url": "http://kamera.invalid/stream"}}
    ui = {"panes": {"favoriten": f"camera:{uuid}"}} if kamera else {"split": False}
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"], "ui": ui}})
    runner, port, bc = await visu_starten(app, [("GET", "/mjpeg", W.mjpeg_handler)] if kamera_aus_ms else ())
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch()
            ctx = await b.new_context(viewport={"width": 1000, "height": 800}, locale="de-DE")
            if bridge:
                await ctx.add_init_script(bridge)
            pg = await ctx.new_page()
            pg.on("pageerror", lambda e: fehler.append(str(e)))

            async def bild(route):
                bilder.append(route.request.url)
                await route.fulfill(status=200, content_type="image/png", body=PIXEL)

            if not kamera_aus_ms:
                await pg.route("**/mjpeg?*", bild)
            await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
            await pg.wait_for_function("booted && view && view.route.view === 'tab'")
            await pg.evaluate("wake()")
            await expect(pg.locator(".tile", has_text=ic["name"])).to_be_visible()
            await schritt(pg, ms, app, bilder)
            await b.close()
    finally:
        bc.cancel()
        await runner.cleanup()
        await app.close()
        await ms.stop()
        if cam_runner is not None:
            await cam_runner.cleanup()
    assert not fehler, fehler


async def _detail(pg, uuid="IC", name="Eingang Intercom"):
    await pg.locator(".tile", has_text=name).click()
    await pg.wait_for_function("uuid => view && view.route.view === 'control' && view.route.id === uuid", arg=uuid)


async def _zustand(pg, talk, state, text, uuid="IC", message=""):
    await pg.evaluate("s => { window.__talkStatus = s; }", {"state": state, "uuid": uuid, "message": message})
    await expect(talk.locator(".intercom-talk-status")).to_have_text(text)


async def _befehle(ms, anzahl):
    for _ in range(60):
        if len(ms.io_roh) >= anzahl:
            break
        await asyncio.sleep(0.05)
    return list(ms.io_roh)


@pytest.mark.parametrize("bridge", [
    "", FULLY_JS, KIOSK_JS,
    *(TALK_JS + f"delete window.LoxKiosk.{method};" for method in
      ("startIntercom", "stopIntercom", "intercomStatus")),
], ids=["browser", "fully", "alte-app", "ohne-start", "ohne-stop", "ohne-status"])
def test_gegensprechen_braucht_vollstaendige_native_bruecke(bridge, miniserver_http):
    async def schritt(pg, ms, app, bilder):
        await expect(pg.locator("#frontpane .video img")).to_be_visible()
        assert await pg.locator(".intercom-talk").count() == 0
        await _detail(pg)
        await expect(pg.locator("#grid .video img")).to_be_visible()
        assert await pg.locator(".intercom-talk").count() == 0
        assert await pg.get_by_role("button", name="Sprechen", exact=True).count() == 0
        await pg.locator("#grid .brow .btn", has_text="Tür öffnen").click()
        assert await _befehle(ms, 1) == ["sps/io/IC/1/pulse"]
    asyncio.run(_visu(schritt, bridge=bridge, kamera=True))


@pytest.mark.parametrize("device_type", [0, 1])
def test_native_gen1_detail_status_und_bisherige_befehle(device_type, miniserver_http, tmp_path):
    async def schritt(pg, ms, app, bilder):
        await _detail(pg)
        talk = pg.locator('#grid .intercom-talk[data-intercom="IC"]')
        await expect(talk.get_by_role("button", name="Sprechen", exact=True)).to_be_enabled()
        await talk.get_by_role("button", name="Sprechen", exact=True).click()
        await expect(talk.locator(".intercom-talk-status")).to_have_text("Verbindung wird aufgebaut …")
        await expect(talk.get_by_role("button", name="Auflegen", exact=True)).to_be_enabled()
        assert await pg.evaluate("__talkCalls") == [["start", "IC"]]

        await _zustand(pg, talk, "connected", "Gespräch verbunden")
        await pg.screenshot(path=str(tmp_path / f"intercom_talk_detail_{device_type}.png"))
        await talk.get_by_role("button", name="Auflegen", exact=True).click()
        await expect(talk.locator(".intercom-talk-status")).to_have_text("Gespräch wird beendet …")
        await expect(talk.get_by_role("button", name="Auflegen", exact=True)).to_be_disabled()
        assert await pg.evaluate("__talkCalls") == [["start", "IC"], ["stop"]]
        assert ms.io_roh == [], "Audioauftraege gehen nur an die native Bruecke"

        await _zustand(pg, talk, "idle", "", uuid="")
        await expect(talk.get_by_role("button", name="Sprechen", exact=True)).to_be_enabled()
        await expect(talk.locator(".intercom-talk-status")).to_be_hidden()
        message = '<img src=x onerror="window.__talkInjected=true"> Audiofehler'
        await _zustand(pg, talk, "error", message, message=message)
        assert await talk.locator(".intercom-talk-status img").count() == 0
        assert await pg.evaluate("!!window.__talkInjected") is False
        await expect(talk.get_by_role("button", name="Sprechen", exact=True)).to_be_enabled()
        await _zustand(pg, talk, "error", "Gegensprechen ist derzeit nicht verfügbar")

        # Dieselben Ausgaenge und answer wie vor der neuen Audiobedienung.
        await pg.locator("#grid .brow .btn", has_text="Tür öffnen").click()
        assert await _befehle(ms, 1) == ["sps/io/IC/1/pulse"]
        app.states["ic-bell"] = 1
        app._dirty = True
        await expect(pg.locator("#grid .brow .btn", has_text="Klingel abstellen")).to_be_visible()
        await pg.locator("#grid .brow .btn", has_text="Klingel abstellen").click()
        assert await _befehle(ms, 2) == ["sps/io/IC/1/pulse", "sps/io/IC/answer"]
        assert await pg.evaluate("__talkCalls") == [["start", "IC"], ["stop"]]
    asyncio.run(_visu(schritt, device_type=device_type))


def test_aktive_andere_tuerstation_blockiert_start(miniserver_http):
    async def schritt(pg, ms, app, bilder):
        await _detail(pg)
        talk = pg.locator('#grid .intercom-talk[data-intercom="IC"]')
        await expect(talk.get_by_role("button", name="Sprechen", exact=True)).to_be_enabled()
        # Der native Status aendert sich zwischen Poll und Tipp: vor dem
        # Auftrag muss die Visu ihn erneut lesen und die andere UUID beachten.
        await pg.evaluate("__talkStatus = {state:'connected', uuid:'ANDERE-TUER', message:''}")
        await talk.get_by_role("button", name="Sprechen", exact=True).dispatch_event("click")
        await expect(talk.get_by_role("button", name="Sprechen", exact=True)).to_be_disabled()
        await expect(talk.locator(".intercom-talk-status")).to_have_text("Gespräch an anderer Türstation")
        assert await pg.evaluate("__talkCalls") == []
        await _zustand(pg, talk, "idle", "", uuid="")
        await expect(talk.get_by_role("button", name="Sprechen", exact=True)).to_be_enabled()
        assert ms.io_roh == []
    asyncio.run(_visu(schritt))


@pytest.mark.parametrize("device_type", [0, 1])
def test_gen2_hat_auch_mit_nativer_bruecke_keine_sprechbedienung(device_type, miniserver_http):
    async def schritt(pg, ms, app, bilder):
        async def ohne_audio():
            assert await pg.locator(".intercom-talk").count() == 0
            assert await pg.get_by_role("button", name="Sprechen", exact=True).count() == 0
            assert await pg.evaluate("__talkCalls") == []
            assert await pg.evaluate("__talkPolls") == 0

        # Die echte Gen-2-Kachel, Kamera-Pane und Befehle aus PR #110 bleiben.
        await expect(pg.locator("#frontpane .video img")).to_be_visible()
        await pg.wait_for_function("document.querySelector('#frontpane .video img').naturalWidth > 0")
        await pg.evaluate("window.__gen2PaneVideo = document.querySelector('#frontpane .video img')")
        await ohne_audio()
        await pg.locator("#frontpane .brow .btn", has_text="Tür öffnen").click()
        assert await _befehle(ms, 1) == ["sps/io/IC2V/1/pulse"]
        await _detail(pg, "IC2V", "Haustür Intercom")
        await expect(pg.locator("#grid .video img")).to_be_visible()
        await pg.wait_for_function("document.querySelector('#grid .video img').naturalWidth > 0")
        await pg.evaluate("window.__gen2DetailVideo = document.querySelector('#grid .video img')")
        bildabrufe = len(bilder)
        assert bildabrufe >= 1
        await ohne_audio()
        await pg.locator("#grid .brow .btn", has_text="Bitte das Paket").click()
        assert (await _befehle(ms, 2))[1] == "sps/io/IC2V/playTts/1"
        stumm = pg.locator("#grid .brow .btn", has_text="Stumm")
        await stumm.click()
        assert (await _befehle(ms, 3))[2] == "sps/io/IC2V/mute/1"
        app.states["ic2-muted"] = 1
        app._dirty = True
        await expect(stumm).to_have_class("btn on")
        await stumm.click()
        assert (await _befehle(ms, 4))[3] == "sps/io/IC2V/mute/0"
        assert await pg.evaluate("document.querySelector('#grid .video img') === window.__gen2DetailVideo")
        bildquelle = await pg.locator("#grid .video img").get_attribute("src")
        app.states["ic2-bell"] = 1
        app._dirty = True
        await expect(pg.locator("#frontpane .cambell")).to_have_text("Es klingelt")
        await pg.locator("#grid .brow .btn", has_text="Klingel abstellen").click()
        assert await _befehle(ms, 5) == ["sps/io/IC2V/1/pulse", "sps/io/IC2V/playTts/1",
                                       "sps/io/IC2V/mute/1", "sps/io/IC2V/mute/0", "sps/io/IC2V/answer"]
        await ohne_audio()
        assert await pg.evaluate("document.querySelector('#frontpane .video img') === window.__gen2PaneVideo")
        # Der neue Klingelblock baut die Detailseite wie vor Gegensprechen neu.
        await expect(pg.locator("#grid .video img")).to_be_visible()
        assert await pg.locator("#grid .video img").get_attribute("src") == bildquelle
        # Chromium kann dieselbe Bildadresse fuer beide Knoten gemeinsam laden.
        assert len(bilder) == bildabrufe, "Gen-2-Zustandsaenderungen erhalten Kamera-Pane und Detailbild"
    asyncio.run(_visu(schritt, typ="IntercomV2", device_type=device_type, kamera=True))


@pytest.mark.parametrize("kamera_aus_ms", [False, True], ids=["cfg-kamera", "miniserver-kamera"])
def test_kamera_status_und_buttons_erhalten_bildknoten(kamera_aus_ms, miniserver_http, tmp_path):
    async def schritt(pg, ms, app, bilder):
        talk = pg.locator('#frontpane .intercom-talk[data-intercom="IC"]')
        await expect(talk.get_by_role("button", name="Sprechen", exact=True)).to_be_enabled()
        await pg.wait_for_function("document.querySelector('#frontpane .video img').naturalWidth > 0")
        await pg.evaluate("window.__talkVideo = document.querySelector('#frontpane .video img')")
        bild_url = await pg.locator("#frontpane .video img").get_attribute("src")
        assert len(bilder) == 1
        if kamera_aus_ms:
            assert app.intercom_cfg == {}
            assert app.ms_video["IC"]["user"] == "kamera"
            assert len(ms.fenc) == 1, "Kamera wurde ueber die echten gesicherten Details geladen"

        async def bild_unveraendert():
            assert await pg.evaluate("document.querySelector('#frontpane .video img') === window.__talkVideo")
            assert await pg.locator("#frontpane .video img").get_attribute("src") == bild_url
            assert len(bilder) == 1, "Sprechstatus darf den Kamerapfad nicht erneut laden"

        await talk.get_by_role("button", name="Sprechen", exact=True).click()
        await expect(talk.locator(".intercom-talk-status")).to_have_text("Verbindung wird aufgebaut …")
        await bild_unveraendert()
        await _zustand(pg, talk, "connected", "Gespräch verbunden")
        await bild_unveraendert()

        # Ein regulaerer Server-Push aktualisiert Klingel und Ausgaenge,
        # waehrend das native Gespraech und das Kamerabild weiterlaufen.
        app.states["ic-bell"] = 1
        app._dirty = True
        await expect(pg.locator("#frontpane .cambell")).to_have_text("Es klingelt")
        await pg.locator("#frontpane .brow .btn", has_text="Tür öffnen").click()
        assert await _befehle(ms, 1) == ["sps/io/IC/1/pulse"]
        await bild_unveraendert()
        await pg.screenshot(path=str(tmp_path / f"intercom_talk_kamera_{kamera_aus_ms}.png"))

        await talk.get_by_role("button", name="Auflegen", exact=True).click()
        await expect(talk.locator(".intercom-talk-status")).to_have_text("Gespräch wird beendet …")
        await bild_unveraendert()
        await _zustand(pg, talk, "idle", "", uuid="")
        await bild_unveraendert()
        assert await pg.evaluate("__talkCalls") == [["start", "IC"], ["stop"]]
        assert await pg.evaluate("__talkPolls") >= 3
        if kamera_aus_ms:
            assert len(ms.fenc) == 1, "Nativer Status laedt die Kamerazugangsdaten nicht erneut"
    asyncio.run(_visu(schritt, kamera=True, kamera_aus_ms=kamera_aus_ms))


def test_spaet_freigegebene_bruecke_erhaelt_beide_kamerabilder(miniserver_http):
    async def schritt(pg, ms, app, bilder):
        await pg.wait_for_function("document.querySelector('#frontpane .video img').naturalWidth > 0")
        await pg.evaluate("window.__talkPaneVideo = document.querySelector('#frontpane .video img')")
        await _detail(pg)
        await pg.wait_for_function("document.querySelector('#grid .video img').naturalWidth > 0")
        await pg.evaluate("window.__talkDetailVideo = document.querySelector('#grid .video img')")
        assert await pg.locator(".intercom-talk").count() == 0
        anzahl_bilder = len(bilder)

        # onPageFinished stellt in der App die oeffentliche Bruecke bereit.
        # Der bereit-Push ergaenzt nur die Bedienung der schon laufenden Bilder.
        await pg.evaluate("() => {" + TALK_JS + "\nwindow.dispatchEvent(new Event('loxpanel-intercom-ready')); }")
        detail = pg.locator('#grid .intercom-talk[data-intercom="IC"]')
        kamera = pg.locator('#frontpane .intercom-talk[data-intercom="IC"]')
        await expect(detail.get_by_role("button", name="Sprechen", exact=True)).to_be_enabled()
        await expect(kamera.locator(".intercom-talk-button")).to_have_text("Sprechen")
        assert await pg.locator(".intercom-talk").count() == 2

        async def bilder_unveraendert():
            assert await pg.evaluate("document.querySelector('#frontpane .video img') === window.__talkPaneVideo")
            assert await pg.evaluate("document.querySelector('#grid .video img') === window.__talkDetailVideo")
            assert len(bilder) == anzahl_bilder

        await bilder_unveraendert()
        await detail.get_by_role("button", name="Sprechen", exact=True).click()
        for talk in (detail, kamera):
            await expect(talk.locator(".intercom-talk-status")).to_have_text("Verbindung wird aufgebaut …")
        await _zustand(pg, detail, "connected", "Gespräch verbunden")
        await expect(kamera.locator(".intercom-talk-status")).to_have_text("Gespräch verbunden")
        await bilder_unveraendert()

        # Eine erneute Freigabe darf weder Bloecke noch Handler verdoppeln.
        await pg.evaluate("window.dispatchEvent(new Event('loxpanel-intercom-ready'))")
        assert await pg.locator(".intercom-talk").count() == 2
        await detail.get_by_role("button", name="Auflegen", exact=True).click()
        assert await pg.evaluate("__talkCalls") == [["start", "IC"], ["stop"]]
        await bilder_unveraendert()
        assert ms.io_roh == []
    asyncio.run(_visu(schritt, bridge=KIOSK_JS, kamera=True))
