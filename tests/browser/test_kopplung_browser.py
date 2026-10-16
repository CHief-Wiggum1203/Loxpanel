"""Kopplungscode in Chromium (Punkt 11): Ein Browser ohne Namen und ohne
?panel= zeigt "Dieses Geraet einrichten" mit seinem Code und der Adresse des
Konfigurators, der Code bleibt ueber ein Neuladen, unter Displays steht
dieselbe Zeile "Code ...", "Namen vergeben" dort benennt genau dieses Geraet
(die Karte und der Code verschwinden), ein Browser mit ?panel= bekommt nur den
Code ohne Karte (sie laege sonst ueber der Visu), ein Tipp blendet die Karte
aus, der Betriebsmodus-Assistent nennt den Code ebenfalls. Der Konfigurator meldet ein Geraet ohne Namen oben als Banner, in
jeder Rubrik; "Benennen und einrichten" vergibt den Namen und oeffnet "Geraet
einrichten" mit dem Geraet; "Spaeter" blendet das Banner fuer dieses Geraet aus."""
import asyncio
import json
import re

import pytest

from lox import anlage, geraete, KONFIGURATOR_GELADEN, visu_starten, W

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}}}
PANELS = {"panels": {"wohnen": {"title": "Wohnen", "tabs": ["favoriten"]}}}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/devices", W.api_save_devices),
          ("POST", "/api/device/name", W.api_device_name)]
CODE = re.compile(rf"^[{geraete.KOPPLUNG_ZEICHEN}]{{{geraete.KOPPLUNG_LAENGE}}}$")


async def _bis(bedingung, was, sekunden=10):
    for _ in range(int(sekunden * 20)):
        if bedingung():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"nicht erreicht: {was}")


KARTE = """() => { const k = document.getElementById('kopplung');
  const t = c => { const e = k.querySelector(c); return e ? e.textContent : null; };
  return {sichtbar: !k.classList.contains('hidden'), code: t('.ei-code'), titel: t('.ei-titel'),
          urls: [...k.querySelectorAll('.ei-url')].map(e => e.textContent),
          gemerkt: localStorage.getItem('lp_kopplung'), geraet: localStorage.getItem('lp_device')}; }"""


def test_karte_code_und_benennen(cfg_ordner, tmp_path):
    (cfg_ordner / "panels.json").write_text(json.dumps(PANELS), encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"sl": 0}
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()

                async def visu(adresse, breite=893, hoehe=533):
                    ctx = await b.new_context(viewport={"width": breite, "height": hoehe})   # eigener localStorage
                    pg = await ctx.new_page()
                    pg.on("pageerror", lambda e: fehler.append(str(e)))
                    await pg.goto(f"http://127.0.0.1:{port}/{adresse}")
                    await pg.wait_for_selector("#grid .tile[data-id]", state="attached")
                    return pg

                neu = await visu("")                                   # ohne Namen, ohne Profil
                await neu.wait_for_selector("#kopplung:not(.hidden)")
                k1 = await neu.evaluate(KARTE)
                assert k1["sichtbar"] and CODE.match(k1["code"]) and k1["titel"] == "Dieses Gerät einrichten", k1
                # Ueber 127.0.0.1 geladen (die App auf dem Panel selbst) nennt die Karte
                # wie der Einrichtungshinweis die Adresse des Servers im Netz
                assert k1["urls"] == [f"http://{a}:{port}/config" for a in geraete._lan_adressen()], k1
                assert k1["gemerkt"] == k1["code"], k1
                await neu.screenshot(path=str(tmp_path / "kopplung_karte.png"))
                code = k1["code"]
                await neu.reload()
                await neu.wait_for_selector("#kopplung:not(.hidden)")
                k2 = await neu.evaluate(KARTE)
                assert k2["code"] == code, "nach dem Neuladen derselbe Code"

                mit_profil = await visu("?panel=wohnen")               # ohne Namen, aber mit Profil
                await mit_profil.wait_for_function("localStorage.getItem('lp_kopplung')")
                k3 = await mit_profil.evaluate(KARTE)
                assert not k3["sichtbar"] and CODE.match(k3["gemerkt"]) and k3["gemerkt"] != code, k3
                await _bis(lambda: sorted(a["code"] for a in app.device_list()["anonymous"]) == sorted([code, k3["gemerkt"]]),
                           "beide Codes in der Geraeteliste")

                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator(".rub", has_text="Geräte").click()
                liste = pg.locator("#displaysHost")
                zeile = liste.locator(f'.ag[data-code="{code}"]')
                await zeile.wait_for()
                assert await zeile.locator(".agn").text_content() == f"Code {code}"
                assert await liste.locator(".ag[data-anon]").count() == 2
                # Der Betriebsmodus-Assistent nennt den Code ebenfalls
                await pg.locator("#mzOpenBtn").click()
                assert f"Code {code}" in (await pg.locator(f'#mzOv .mzanon[data-code="{code}"] .agip').text_content())
                await pg.locator("#mzX").click()
                await pg.screenshot(path=str(tmp_path / "kopplung_displays.png"), full_page=True)

                await zeile.locator(".anname").fill("kinderzimmer")
                await zeile.get_by_role("button", name="Namen vergeben").click()
                await pg.wait_for_function("document.querySelector('#ag_toast').textContent === '✓ kinderzimmer'")
                await _bis(lambda: any(i.get("dev") == "kinderzimmer" for i in app.conn_info.values()),
                           "als kinderzimmer neu verbunden")
                await neu.wait_for_selector("#kopplung.hidden", state="attached")
                k4 = await neu.evaluate(KARTE)
                assert k4["geraet"] == "kinderzimmer" and k4["gemerkt"] is None and not k4["sichtbar"], k4
                k5 = await mit_profil.evaluate(KARTE)
                assert k5["geraet"] is None and k5["gemerkt"] == k3["gemerkt"], "der andere Browser bleibt, wie er war"
                await _bis(lambda: [a["code"] for a in app.device_list()["anonymous"]] == [k3["gemerkt"]],
                           "nur noch ein Geraet ohne Namen")

                # Ein Tipp auf die Karte blendet sie bis zum naechsten Laden aus
                dritte = await visu("")
                await dritte.wait_for_selector("#kopplung:not(.hidden)")
                await dritte.locator("#kopplung").click()
                assert not (await dritte.evaluate(KARTE))["sichtbar"]

                # Betriebsmodus-Assistent offen, ein Browser ohne Namen wird durch einen
                # anderen hinter derselben IP ersetzt: die Liste zeigt den neuen Code, nicht
                # den alten (Codex an #131: die Signatur kannte nur IPs)
                code3 = (await dritte.evaluate(KARTE))["gemerkt"]
                # erst, wenn die Geraeteliste des Konfigurators (alle 6 s) beide kennt
                await pg.wait_for_function("""erw => [...document.querySelectorAll('#ag_anon .ag[data-anon]')]
                    .map(n => n.dataset.code).sort().join() === erw""", arg=",".join(sorted([k3["gemerkt"], code3])), timeout=15000)
                await pg.locator("#mzOpenBtn").click()
                await pg.wait_for_selector("#mzOv:not([hidden])")
                codes = lambda: pg.locator("#mzOv .mzanon").evaluate_all("l => l.map(n => n.dataset.code).sort()")
                assert await codes() == sorted([k3["gemerkt"], code3])
                await mit_profil.close()
                vierte = await visu("?panel=wohnen")
                await vierte.wait_for_function("localStorage.getItem('lp_kopplung')")
                code4 = await vierte.evaluate("localStorage.getItem('lp_kopplung')")
                await pg.wait_for_function("""erw => [...document.querySelectorAll('#mzOv .mzanon')]
                    .map(n => n.dataset.code).sort().join() === erw""", arg=",".join(sorted([code3, code4])), timeout=15000)
                await pg.locator("#mzX").click()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


BANNER = """() => { const b = document.getElementById('neuGeraet');
  return {sichtbar: !b.hidden, text: b.innerText.replace(/\\s+/g, ' ').trim(),
          code: (b.querySelector('.nb-code') || {}).textContent || '', rubrik: document.querySelector('.rub.active').dataset.rub}; }"""


def test_banner_neues_geraet(cfg_ordner, tmp_path):
    """Einrichtung neu, Schritt 1: Ein Tablet oeffnet die Visu ohne Namen. Der
    Konfigurator meldet es oben als Banner mit Klasse, Groesse und Code, in jeder
    Rubrik. "Benennen und einrichten" vergibt den Namen; sobald das Tablet damit
    zurueck ist, oeffnet sich "Geraet einrichten" mit dem Tablet als Geraet.
    "Spaeter" blendet das Banner fuer dieses Geraet aus, auch nach dem Neuladen."""
    (cfg_ordner / "panels.json").write_text(json.dumps(PANELS), encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"sl": 0}
        runner, port, bc = await visu_starten(app, ROUTEN + [("POST", "/api/panels", W.api_save_panels),
                                                             ("POST", "/api/device/switch", W.api_device_switch)])
        fehler, erg = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": 1180, "height": 820})
                tablet = await ctx.new_page()
                tablet.on("pageerror", lambda e: fehler.append(str(e)))
                await tablet.goto(f"http://127.0.0.1:{port}/")
                await tablet.wait_for_selector("#kopplung:not(.hidden)")
                code = (await tablet.evaluate(KARTE))["code"]
                await _bis(lambda: any(i.get("screen") for i in app.conn_info.values()), "Tablet mit gemeldeter Groesse")

                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.wait_for_selector("#neuGeraet:not([hidden])")
                erg["uebersicht"] = await pg.evaluate(BANNER)
                await pg.locator(".rub", has_text="Ansichten").click()
                erg["ansichten"] = await pg.evaluate(BANNER)
                await pg.screenshot(path=str(tmp_path / "banner_neues_geraet.png"))
                await pg.locator("#neuGeraet .nb-name").fill("bad")
                await pg.get_by_role("button", name="Benennen und einrichten").click()
                await _bis(lambda: any(i.get("dev") == "bad" for i in app.conn_info.values()), "als bad neu verbunden")
                await pg.wait_for_selector("#geOv:not([hidden])", timeout=15000)
                await pg.wait_for_function("GE.device === 'bad'")
                erg["ge"] = await pg.evaluate("[GE.device, GE.screen && GE.screen.vw, document.getElementById('geKopf').textContent,"
                                              " document.getElementById('geFertig').textContent]")
                erg["nach_benennen"] = await pg.evaluate(BANNER)
                await pg.screenshot(path=str(tmp_path / "banner_einrichten.png"))
                await pg.locator("#geX").click()
                await pg.wait_for_selector("#geOv", state="hidden")

                # zweites Geraet ohne Namen: "Spaeter" blendet es aus, auch nach dem Neuladen
                ctx2 = await b.new_context(viewport={"width": 480, "height": 480})
                klein = await ctx2.new_page()
                await klein.goto(f"http://127.0.0.1:{port}/")
                await klein.wait_for_selector("#kopplung:not(.hidden)")
                await pg.wait_for_function("!document.getElementById('neuGeraet').hidden", timeout=15000)
                erg["klein"] = await pg.evaluate(BANNER)
                await pg.get_by_role("button", name="Später").click()
                erg["spaeter"] = await pg.evaluate(BANNER)
                await pg.reload()
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.wait_for_function("typeof NEU_SIG === 'string' && document.querySelectorAll('#ag_anon .ag[data-anon]').length === 1", timeout=15000)
                erg["neu_geladen"] = await pg.evaluate(BANNER)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return code, erg
    code, erg = asyncio.run(lauf())
    u = erg["uebersicht"]
    assert u["sichtbar"] and u["code"] == code and u["rubrik"] == "overview", u
    assert u["text"].startswith("Neues Gerät gefunden: Tablet · 1180×820 quer"), u["text"]
    assert erg["ansichten"]["sichtbar"] and erg["ansichten"]["rubrik"] == "pconf", erg["ansichten"]
    assert erg["ge"] == ["bad", 1180, "bad · Tablet · 1180×820 quer", "Fertig – auf bad anzeigen"], erg["ge"]
    assert not erg["nach_benennen"]["sichtbar"], erg["nach_benennen"]
    assert erg["klein"]["sichtbar"] and erg["klein"]["text"].startswith("Neues Gerät gefunden: 4″-Wandpanel · 480×480 quadratisch"), erg["klein"]
    assert not erg["spaeter"]["sichtbar"] and not erg["neu_geladen"]["sichtbar"], erg
