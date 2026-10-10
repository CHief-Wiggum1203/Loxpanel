"""Kopplungscode in Chromium (Punkt 11): Ein Browser ohne Kennung und ohne
?panel= zeigt "Dieses Geraet einrichten" mit seinem Code und der Adresse des
Konfigurators, der Code bleibt ueber ein Neuladen, unter Displays steht
dieselbe Zeile "Code ...", "Namen vergeben" dort benennt genau dieses Geraet
(die Karte und der Code verschwinden), ein Browser mit ?panel= bekommt nur den
Code ohne Karte, ein Tipp blendet die Karte aus, der Betriebsmodus-Assistent
nennt den Code ebenfalls."""
import asyncio
import json
import re

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}}}
PANELS = {"panels": {"wohnen": {"title": "Wohnen", "tabs": ["favoriten"]}}}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/devices", W.api_save_devices),
          ("POST", "/api/device/name", W.api_device_name)]
CODE = re.compile(rf"^[{W.KOPPLUNG_ZEICHEN}]{{{W.KOPPLUNG_LAENGE}}}$")


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

                neu = await visu("")                                   # ohne Kennung, ohne Profil
                await neu.wait_for_selector("#kopplung:not(.hidden)")
                k1 = await neu.evaluate(KARTE)
                assert k1["sichtbar"] and CODE.match(k1["code"]) and k1["titel"] == "Dieses Gerät einrichten", k1
                # Ueber 127.0.0.1 geladen (die App auf dem Panel selbst) nennt die Karte
                # wie der Einrichtungshinweis die Adresse des Servers im Netz
                assert k1["urls"] == [f"http://{a}:{port}/config" for a in W._lan_adressen()], k1
                assert k1["gemerkt"] == k1["code"], k1
                await neu.screenshot(path=str(tmp_path / "kopplung_karte.png"))
                code = k1["code"]
                await neu.reload()
                await neu.wait_for_selector("#kopplung:not(.hidden)")
                k2 = await neu.evaluate(KARTE)
                assert k2["code"] == code, "nach dem Neuladen derselbe Code"

                mit_profil = await visu("?panel=wohnen")               # ohne Kennung, aber mit Profil
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
                liste = pg.locator("#ag_list")
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
                           "nur noch ein Geraet ohne Kennung")

                # Ein Tipp auf die Karte blendet sie bis zum naechsten Laden aus
                dritte = await visu("")
                await dritte.wait_for_selector("#kopplung:not(.hidden)")
                await dritte.locator("#kopplung").click()
                assert not (await dritte.evaluate(KARTE))["sichtbar"]

                # Betriebsmodus-Assistent offen, ein Browser ohne Kennung wird durch einen
                # anderen hinter derselben IP ersetzt: die Liste zeigt den neuen Code, nicht
                # den alten (Codex an #131: die Signatur kannte nur IPs)
                code3 = (await dritte.evaluate(KARTE))["gemerkt"]
                # erst, wenn die Geraeteliste des Konfigurators (alle 6 s) beide kennt
                await pg.wait_for_function("""erw => [...document.querySelectorAll('#ag_list .ag[data-anon]')]
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
