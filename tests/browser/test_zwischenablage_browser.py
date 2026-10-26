"""Kopieren im Konfigurator auch ueber http://<IP> im Heimnetz: "Adresse
kopieren" und "Befehl kopieren" unter Geraet verbinden, "Adressen kopieren" im
Betriebsmodus-Assistenten. Ueber eine Adresse im Heimnetz ist die Seite kein
sicherer Kontext, navigator.clipboard fehlt; frueher brach der Klick dann ohne
Meldung ab (zwischenablage() in config/kern.js kopiert dort ueber ein
Textfeld). Chromium loest hier lp.test auf 127.0.0.1 auf: http://lp.test ist
fuer den Browser so unsicher wie eine IP im Heimnetz, 127.0.0.1 gilt als
sicher. Was in der Zwischenablage steht, liest eine Seite auf 127.0.0.1 zurueck."""
import asyncio

import pytest

from lox import anlage, KONFIGURATOR_GELADEN, visu_starten, W

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}}}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/devices", W.api_save_devices),
          ("POST", "/api/device/name", W.api_device_name)]
UNSICHER = "lp.test"


async def _klick_und_meldung(pg, knopf, meldung: str) -> str:
    """Knopf druecken und auf SEINE Meldung warten. Die vorige steht noch 4 s
    da; ohne Zuruecksetzen kaeme das Warten sofort zurueck, bevor
    navigator.clipboard (asynchron) fertig ist. -> Text der Meldung."""
    await pg.evaluate(f"document.getElementById('{meldung}').classList.remove('show')")
    await knopf.click()
    await pg.wait_for_function(f"document.getElementById('{meldung}').classList.contains('show')", timeout=5000)
    m = pg.locator(f"#{meldung}")
    assert "ok" in (await m.get_attribute("class")).split(), await m.get_attribute("class")
    return await m.text_content()


async def _bis(bedingung, was, sekunden=10):
    for _ in range(int(sekunden * 20)):
        if bedingung():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"nicht erreicht: {was}")


@pytest.mark.parametrize("host", [UNSICHER, "127.0.0.1"])
def test_kopieren_ueber_jede_adresse(cfg_ordner, host):
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"sl": 0}
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler, kopien = [], []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch(args=[f"--host-resolver-rules=MAP {UNSICHER} 127.0.0.1"])
                ctx = await b.new_context(viewport={"width": 1280, "height": 900}, locale="de-DE")
                sicher = f"http://127.0.0.1:{port}"
                await ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=sicher)
                # ein benanntes Geraet, damit der Betriebsmodus-Assistent bis zum Ende geht
                tablet = await ctx.new_page()
                await tablet.goto(f"{sicher}/?device=flur")
                await _bis(lambda: any(i.get("dev") == "flur" for i in app.conn_info.values()), "Geraet flur")
                leser = await ctx.new_page()
                await leser.goto(f"{sicher}/api/meta")

                async def ablage():
                    await leser.bring_to_front()
                    text = await leser.evaluate("navigator.clipboard.readText()")
                    await pg.bring_to_front()
                    return text

                pg = await ctx.new_page()
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://{host}:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                assert await pg.evaluate("window.isSecureContext") is (host != UNSICHER)
                assert await pg.evaluate("typeof navigator.clipboard") == ("undefined" if host == UNSICHER else "object")

                # Geraet verbinden: jede Zeile landet in der Zwischenablage, die Meldung sagt es
                await pg.locator(".rub", has_text="Geräte").click()
                await pg.locator("#geraetVerbindenBtn").click()
                await pg.wait_for_selector("#gvOv:not([hidden])")
                knoepfe = pg.locator("#gvBody [data-gv-copy]")
                for i in range(await knoepfe.count()):
                    soll = await knoepfe.nth(i).get_attribute("data-gv-copy")
                    assert await _klick_und_meldung(pg, knoepfe.nth(i), "gvToast") == "✓ kopiert"
                    kopien.append((soll, await ablage()))
                await pg.locator("#gvZu").click()

                # Betriebsmodus-Assistent: am Ende die Adressen fuer Loxone Config
                await pg.evaluate("pollDevices()")
                await pg.locator("#mzOpenBtn").click()
                await pg.locator('#mzOv [data-mzdev="flur"]').click()
                await pg.locator("#mzNext").click()
                await pg.locator("#mzOv [data-mzmode]").first.click()
                await pg.locator("#mzNext").click()
                await pg.locator("#mzNext").click()
                soll = await pg.locator("#mzLines").text_content()
                assert await _klick_und_meldung(pg, pg.locator("#mzCopy"), "dev_toast") == "✓ kopiert"
                kopien.append((soll, await ablage()))
                assert await pg.evaluate("document.activeElement.id") == "mzCopy", "der Fokus bleibt auf dem Knopf"
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        return fehler, kopien
    fehler, kopien = asyncio.run(lauf())
    assert not fehler, fehler
    assert len(kopien) == 4, kopien             # drei Wege unter Geraet verbinden, dazu der Assistent
    assert all(soll and soll == ist for soll, ist in kopien), kopien
    assert len({soll for soll, _ in kopien}) == 4, "jede Zeile anders: jede Kopie kommt aus ihrem Knopf"
