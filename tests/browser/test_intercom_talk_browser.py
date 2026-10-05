"""Natives Gegensprechen in der echten Visu (Chromium).

Die LoxKiosk-Bruecke liefert den Gespraechsstatus; Detailseite und Kamera-Pane
zeigen dieselbe Bedienung. Ohne vollstaendige Bruecke und fuer IntercomV2
bleibt sie verborgen. Status-Polling darf das Kamerabild nicht neu laden;
Tuer- und Klingelbefehle gehen unveraendert zum Miniserver aus tests/lox.py.
"""
import asyncio
import base64

import pytest

from lox import Miniserver, W, anlage, intercom_baustein, neue_app, visu_starten

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


async def _visu(schritt, *, bridge=TALK_JS, kamera=False, device_type=1, typ="Intercom"):
    ms = await Miniserver().start()
    app = neue_app(ms)
    ic, states = intercom_baustein(klingeln=())
    ic = dict(ic, type=typ, isFavorite=True, details=dict(ic["details"], deviceType=device_type))
    app._apply_structure(anlage({"IC": ic}))
    app.states = states
    app.intercom_cfg = {"IC": {"url": "http://kamera.invalid/stream"}}
    ui = {"panes": {"favoriten": "camera:IC"}} if kamera else {"split": False}
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"], "ui": ui}})
    runner, port, bc = await visu_starten(app)
    fehler, bilder = [], []
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

            await pg.route("**/mjpeg?*", bild)
            await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
            await pg.wait_for_function("booted && view && view.route.view === 'tab'")
            await pg.evaluate("wake()")
            await expect(pg.locator(".tile", has_text="Eingang Intercom")).to_be_visible()
            await schritt(pg, ms, app, bilder)
            await b.close()
    finally:
        bc.cancel()
        await runner.cleanup()
        await app.icon_session.close()
        await ms.stop()
    assert not fehler, fehler


async def _detail(pg):
    await pg.locator(".tile", has_text="Eingang Intercom").click()
    await pg.wait_for_function("view && view.route.view === 'control' && view.route.id === 'IC'")


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


def test_gen2_hat_auch_mit_nativer_bruecke_keine_sprechbedienung(miniserver_http):
    async def schritt(pg, ms, app, bilder):
        # Der bisher nicht unterstuetzte Gen2-Baustein hat keinen Kachel-Link;
        # die echte Detailroute bleibt auch direkt ohne nativen Sprechblock.
        await pg.evaluate("nav({view:'control', id:'IC'})")
        await pg.wait_for_function("view && view.route.view === 'control' && view.route.id === 'IC'")
        assert await pg.locator(".intercom-talk").count() == 0
        assert await pg.get_by_role("button", name="Sprechen", exact=True).count() == 0
        assert await pg.evaluate("__talkCalls") == []
        assert await pg.evaluate("__talkPolls") == 0
        assert ms.io_roh == []
    asyncio.run(_visu(schritt, typ="IntercomV2", kamera=True))


def test_kamera_status_und_buttons_erhalten_bildknoten(miniserver_http, tmp_path):
    async def schritt(pg, ms, app, bilder):
        talk = pg.locator('#frontpane .intercom-talk[data-intercom="IC"]')
        await expect(talk.get_by_role("button", name="Sprechen", exact=True)).to_be_enabled()
        await pg.wait_for_function("document.querySelector('#frontpane .video img').naturalWidth > 0")
        await pg.evaluate("window.__talkVideo = document.querySelector('#frontpane .video img')")
        bild_url = await pg.locator("#frontpane .video img").get_attribute("src")
        assert len(bilder) == 1

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
        await pg.screenshot(path=str(tmp_path / "intercom_talk_kamera.png"))

        await talk.get_by_role("button", name="Auflegen", exact=True).click()
        await expect(talk.locator(".intercom-talk-status")).to_have_text("Gespräch wird beendet …")
        await bild_unveraendert()
        await _zustand(pg, talk, "idle", "", uuid="")
        await bild_unveraendert()
        assert await pg.evaluate("__talkCalls") == [["start", "IC"], ["stop"]]
        assert await pg.evaluate("__talkPolls") >= 3
    asyncio.run(_visu(schritt, kamera=True))


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
