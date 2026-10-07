"""Reiter SIP im Konfigurator (Chromium): die Intercoms (Tuersteuerung und
Baustein Intercom) mit dem SIP-Zugang aus den gesicherten Details, ohne
Passwort in der Seite, und "Verbindung prüfen" gegen die nachgebaute
Tuerstation - angenommen, abgelehnt, auf Englisch. Fehlt der SIP-Zugang, zeigt
die Karte den Aufbau der gesicherten Details ohne Werte und sagt, wo er
hingehoert. Miniserver (Command Encryption) und Tuerstation aus tests/lox.py."""
import asyncio

import pytest
from aiohttp import web

from lox import (KONFIGURATOR_GELADEN, Miniserver, SipTuer, W, anlage, intercom_baustein, intercom_v2_baustein,
                 neue_app, serve)

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

SIP_PASS = "Sip-Kennwort-1"
# Kamera ja, Audio nein (wie bei einer Intercom ohne eingerichtetes Audiomodul)
OHNE_AUDIO = {"videoInfo": {"streamUrl": "http://10.9.8.7/bild.jpg", "user": "videonutzer",
                            "pass": "Bild-Kennwort-2", "alertImage": ""}, "audioInfo": {}}


def _bausteine() -> dict:
    ic, _ = intercom_baustein()
    # andere Tuerstation, Name mit HTML-Zeichen: muss als Text erscheinen
    garten = dict(ic, name="Garten & <Tor>", uuidAction="IC2", room="r2", details=dict(ic["details"], deviceType=0))
    keller = dict(ic, name="Keller Intercom", uuidAction="IC3", room="r2", details=dict(ic["details"], deviceType=2))
    # Loxone Intercom am Baustein Intercom: ohne gesicherte Details, keine Anfrage
    v2, _ = intercom_v2_baustein()
    return {"IC": ic, "IC2": garten, "IC3": keller, "IC2V": dict(v2, room="r2"),
            "S1": {"name": "Licht", "type": "Switch", "uuidAction": "S1", "room": "r1", "cat": "c1",
                   "states": {"active": "s1"}}}


async def _karten(pg) -> list[dict]:
    return await pg.evaluate("""[...document.querySelectorAll('#sip_list .sip')].map(k => ({
        uuid: k.dataset.uuid, name: k.querySelector('.icname').firstChild.textContent,
        info: (k.querySelector('.sipgeraet') || {}).textContent || '',
        zugang: [...k.querySelectorAll('.sipzug dd')].map(d => d.textContent),
        knopf: !!k.querySelector('.sip_pruefen'),
        fehler: (k.querySelector('.sipfehl') || {}).textContent || '',
        diag: (k.querySelector('.sipdiag') || {}).textContent || '',
        hinweis: (k.querySelector('.siphinweis') || {}).textContent || ''}))""")


async def _pruefen(pg) -> tuple[str, str]:
    """Knopf der ersten Karte druecken, auf das Ergebnis warten -> (Klasse, Text)."""
    await pg.locator("#sip_list .sip_pruefen").first.click()
    await pg.wait_for_function("(() => { const r = document.querySelector('#sip_list .sipres');"
                               " return r && r.querySelector('b') && !r.querySelector('.laeuft'); })()")
    return (await pg.locator("#sip_list .sipres b").first.get_attribute("class"),
            await pg.locator("#sip_list .sipres").first.inner_text())


def test_sip_reiter(cfg_ordner, miniserver_http, tmp_path):
    async def lauf():
        tuer = await SipTuer(passwort=SIP_PASS).start()
        ms = await Miniserver().start()
        ms.gesichert = {"IC": {"audioInfo": {"host": f"127.0.0.1:{tuer.port}", "user": "tuer", "pass": SIP_PASS}},
                        "IC2": {"audioInfo": {"host": "10.0.0.9"}}, "IC3": OHNE_AUDIO}
        app = neue_app(ms)
        app.user = ms.benutzer
        app._apply_structure(anlage(_bausteine()))
        ui = web.Application()
        ui["app"] = app
        for pfad, h in (("/config", W.config_index), ("/api/meta", W.api_meta), ("/api/settings", W.api_settings),
                        ("/api/devices", W.api_devices_get), ("/i18n.js", W.i18n_js), ("/api/sip", W.api_sip)):
            ui.router.add_get(pfad, h)
        ui.router.add_post("/api/sip/pruefen", W.api_sip_pruefen)
        runner, port = await serve(ui)
        fehler, res = [], {"port": tuer.port}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator(".rub", has_text="Settings").click()
                assert ms.fenc == [], "der Reiter laedt erst, wenn er offen ist"
                await pg.locator(".stab", has_text="SIP").click()
                await pg.wait_for_function("document.querySelectorAll('#sip_list .sip').length === 4")
                res["karten"] = await _karten(pg)
                res["abrufe_laden"] = len(ms.fenc)
                inhalt = await pg.content()
                res["seite_mit_werten"] = [w for w in (SIP_PASS, "Bild-Kennwort-2", "videonutzer", "10.9.8.7")
                                           if w in inhalt]
                await pg.evaluate("Promise.all([loadSip(), loadSip()])")
                res["abrufe_doppelt"] = len(ms.fenc) - res["abrufe_laden"]
                res["angenommen"] = await _pruefen(pg)
                res["anfragen"] = len(tuer.anfragen)
                await pg.screenshot(path=str(tmp_path / "sip.png"))
                tuer.passwort = "geaendert"               # die Tuerstation kennt ein anderes Passwort
                res["abgelehnt"] = await _pruefen(pg)
                tuer.passwort = SIP_PASS
                # Englisch
                await pg.evaluate("localStorage.setItem('lp_ui_lang', 'en')")
                await pg.reload()
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator(".rub", has_text="Settings").click()
                await pg.locator(".stab", has_text="SIP").click()
                await pg.wait_for_function("document.querySelectorAll('#sip_list .sip').length === 4")
                res["en_karten"] = await _karten(pg)
                res["en_knopf"] = await pg.locator("#sip_list .sip_pruefen").first.inner_text()
                res["en_angenommen"] = await _pruefen(pg)
                res["en_lead"] = await pg.locator("#setHost .spane.active .lead").inner_text()
                await pg.screenshot(path=str(tmp_path / "sip_en.png"))
                await b.close()
        finally:
            await runner.cleanup()
            await app.icon_session.close()
            await ms.stop()
            tuer.stop()
        assert not fehler, fehler
        return res
    res = asyncio.run(lauf())

    hinweis = ("Ohne SIP-Adresse gibt es nichts zu prüfen. Die Adresse für Audio steht in Loxone Config am Baustein"
               " der Intercom (bei einer benutzerdefinierten Intercom „Host für Audio (intern)“); nach dem Speichern"
               " in den Miniserver diesen Reiter neu öffnen. Steht sie dort und fehlt hier trotzdem, gibt der"
               " Miniserver sie für diesen Baustein nicht heraus.")
    assert res["karten"] == [
        {"uuid": "IC", "name": "Eingang Intercom", "info": "Zentral · Loxone Intercom · Baustein Türsteuerung",
         "zugang": [f"127.0.0.1:{res['port']}", "tuer", "vorhanden"], "knopf": True, "fehler": "", "diag": "",
         "hinweis": ""},
        {"uuid": "IC2", "name": "Garten & <Tor>",
         "info": "Technikraum · Andere oder unbekannte Türstation · Baustein Türsteuerung",
         "zugang": ["10.0.0.9", "–", "keins"], "knopf": True, "fehler": "", "diag": "", "hinweis": ""},
        {"uuid": "IC2V", "name": "Haustür Intercom", "info": "Technikraum · Loxone Intercom · Baustein Intercom",
         "zugang": [], "knopf": False, "fehler": "Der Baustein hat keine gesicherten Details", "diag": "",
         "hinweis": "Für die Loxone Intercom am Baustein Intercom beschreibt die Strukturdoku von Loxone keinen"
                    " SIP-Zugang."},
        {"uuid": "IC3", "name": "Keller Intercom", "info": "Technikraum · Loxone Intercom XL · Baustein Türsteuerung",
         "zugang": [], "knopf": False, "fehler": "Die Intercom nennt keinen SIP-Zugang",
         "diag": "Gesicherte Details vom Miniserver: videoInfo: streamUrl, user, pass, alertImage (leer)"
                 " · audioInfo: leer",
         "hinweis": hinweis}]
    assert res["abrufe_laden"] == 3, "je Intercom mit gesicherten Details eine verschluesselte Anfrage, einmal"
    assert res["seite_mit_werten"] == [], "weder Passwoerter noch Werte aus den gesicherten Details"
    assert res["abrufe_doppelt"] == 3, "zwei Aufrufe zugleich laden nur einmal"
    klasse, text = res["angenommen"]
    assert klasse == "ok" and text.startswith("✓ Die Türstation antwortet und nimmt die Anmeldung an.")
    for teil in ("Antwort: 200 OK", "Gegenstelle: Nachbau-Tuer/1.0",
                 "Codecs: PCMU/8000, PCMA/8000, telephone-event/8000", "Methoden: INVITE, ACK, CANCEL, BYE, OPTIONS"):
        assert teil in text, (teil, text)
    assert res["anfragen"] == 2, "OPTIONS, dann mit Anmeldung"
    klasse, text = res["abgelehnt"]
    assert klasse == "bad" and text.startswith("Die Türstation lehnt die Anmeldung ab.") and "403 Forbidden" in text
    assert [k["info"] for k in res["en_karten"]] == ["Zentral · Loxone Intercom · Door Controller block",
                                                     "Technikraum · Other or unknown door station · Door Controller block",
                                                     "Technikraum · Loxone Intercom · Intercom block",
                                                     "Technikraum · Loxone Intercom XL · Door Controller block"]
    assert [k["zugang"][2] for k in res["en_karten"][:2]] == ["present", "none"]
    assert [k["fehler"] for k in res["en_karten"][2:]] == ["The block has no secured details",
                                                           "The intercom provides no SIP access"]
    assert res["en_karten"][3]["diag"] == ("Secured details from the Miniserver: videoInfo: streamUrl, user, pass,"
                                           " alertImage (empty) · audioInfo: empty")
    assert res["en_karten"][2]["hinweis"].startswith("For the Loxone Intercom on the Intercom block,")
    assert res["en_karten"][3]["hinweis"].startswith("Without a SIP address there is nothing to check.")
    assert [k["hinweis"] for k in res["en_karten"][:2]] == ["", ""]
    assert res["en_knopf"] == "Check connection"
    assert res["en_angenommen"][1].startswith("✓ The door station answers and accepts the login.")
    assert "Response: 200 OK" in res["en_angenommen"][1]
    assert res["en_lead"].startswith("SIP access of the door station(s)")

