"""Vorschau in der echten Visu (Punkt 10, Teil 3) in Chromium: „Vorschau“ in der
Speicherleiste schickt das Profil samt ungespeicherten Aenderungen als Entwurf
an den Server und oeffnet die Visu damit in einem Fenster. Die Visu zeigt
genau die Kacheln, die der Seiten-Editor am Vorschaugeraet zeigt, kennzeichnet
den Entwurf, und jede weitere Aenderung im Editor zieht im offenen Fenster
nach. panels.json entsteht erst beim Speichern; danach zeigt das Fenster das
gespeicherte Profil ohne Kennzeichnung."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser


def _schalter(u, name, raum):
    return {"name": name, "type": "Switch", "uuidAction": u, "room": raum, "cat": "c1", "states": {"active": "s" + u}}


STRUKTUR = {
    "rooms": {"r1": {"name": "Wohnzimmer"}, "r2": {"name": "Küche"}},
    "cats": {"c1": {"name": "Beleuchtung"}},
    "controls": {u: _schalter(u, n, r) for u, n, r in (
        ("A", "Deckenlicht", "r1"), ("B", "Stehlampe", "r1"), ("C", "Dimmer Küche", "r2"), ("D", "Leselampe", "r1"))},
}
ROUTEN = [("POST", "/api/panels", W.api_save_panels), ("POST", "/api/entwurf", W.api_entwurf)]
# Kacheln der Visu in ihrer Folge, und was der Editor am Vorschaugeraet zeigt
VISU = "() => [...document.querySelectorAll('#grid .tile[data-id]')].map(n => n.dataset.id)"
EDITOR = "() => document.querySelector('#seHost')._seLage.a.raster.map(e => e.id)"
MARKE = "() => { const m = document.getElementById('entwurfMarke'); return m.classList.contains('hidden') ? '' : m.textContent; }"


async def _bis(pg, ausdruck, erwartet, was):
    """Warten, bis der Ausdruck im Fenster `erwartet` liefert; waehrend einer
    Navigation gibt es keinen Kontext zum Auswerten - dann noch einmal."""
    letzter = None
    for _ in range(100):
        try:
            letzter = await pg.evaluate(ausdruck)
        except Exception as fehler:   # Playwright: "Execution context was destroyed"
            letzter = fehler
        else:
            if letzter == erwartet:
                return
        await asyncio.sleep(0.1)
    assert letzter == erwartet, was


def test_vorschau_zeigt_den_entwurf_zieht_nach_und_endet_beim_speichern(cfg_ordner):
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(STRUKTUR)
        app.states = {"s" + u: 0 for u in "ABCD"}
        app.panels = W.App._sanitize_panels({"flur": {"title": "Flur", "tabs": ["auswahl"], "ui": {"grid": "auto"},
                                                      "pickTabs": [{"name": "Wohnen", "picks": ["A", "C"], "byRoom": False}]}})
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1400, "height": 1000}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator("#plist .pitem", has_text="?panel=flur").click()
                await pg.locator(".stab[data-sub='seiten']").click()
                await pg.wait_for_selector("#seHost [data-se-flaeche]")
                opts = await pg.eval_on_selector_all("#seHost [data-se-geraet] option", "l => l.map(o => o.textContent)")
                await pg.select_option("#seHost [data-se-geraet]", str(next(i for i, o in enumerate(opts) if o.startswith("Galaxy Tab A9 quer ·"))))

                # ungespeicherte Aenderung im Editor: Stehlampe auf die Seite, dann Vorschau
                await pg.locator("#seHost .se-p", has_text="Stehlampe").click()
                editor = await pg.evaluate(EDITOR)
                assert editor == ["A", "C", "B"], editor
                async with pg.context.expect_page() as neue:
                    await pg.locator("#vorBtn").click()
                vorschau = await neue.value
                vorschau.on("pageerror", lambda e: fehler.append(str(e)))
                await vorschau.wait_for_selector("#grid .tile[data-id]", state="attached")
                assert "/?panel=flur&entwurf=" in vorschau.url, vorschau.url
                assert await vorschau.evaluate(VISU) == editor, "die echte Visu zeigt, was der Editor zeigt"
                assert await vorschau.evaluate(MARKE) == "Entwurf – nicht gespeichert"
                assert not (cfg_ordner / "panels.json").exists(), "ein Entwurf wird nicht gespeichert"
                gespeichert = W.App._sanitize_panels({"flur": {"title": "Flur", "tabs": ["auswahl"], "pickTabs": [
                    {"name": "Wohnen", "picks": ["A", "C"], "byRoom": False}]}})
                assert app.panels["flur"]["pickTabs"][0]["picks"] == gespeichert["flur"]["pickTabs"][0]["picks"], \
                    "der Server haelt weiter das gespeicherte Profil"
                breite = await vorschau.evaluate("window.innerWidth")
                assert 800 <= breite <= 893 + 20, f"das Fenster hat die Groesse des Vorschaugeraets: {breite}"

                # weitere Aenderung: die offene Vorschau zieht nach (neu geladen, derselbe Entwurf)
                await pg.locator("#seHost .se-p", has_text="Leselampe").click()
                await pg.locator("#seHost .se-t[data-se-t='B']").click()
                await pg.locator("#seHost [data-se-mv='1']").click()
                erwartet = await pg.evaluate(EDITOR)
                assert erwartet == ["A", "C", "D", "B"] or erwartet == ["A", "C", "B", "D"], erwartet
                await _bis(vorschau, VISU, erwartet, "die Vorschau soll die Aenderung zeigen")
                assert await vorschau.evaluate(MARKE) == "Entwurf – nicht gespeichert"
                assert len(app.entwuerfe) == 1, "ein Entwurf, nicht je Aenderung einer"

                # Speichern: panels.json entsteht, die Vorschau zeigt das gespeicherte Profil
                async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
                    await pg.locator("#saveBtn").click()
                assert (await (await antwort.value).json())["verworfen"] == []
                await _bis(vorschau, "location.search", "?panel=flur", "das Fenster verlaesst den Entwurf")
                await vorschau.wait_for_selector("#grid .tile[data-id]", state="attached")
                assert await vorschau.evaluate(MARKE) == "" and app.entwuerfe == {}
                assert await vorschau.evaluate(VISU) == erwartet, "gespeichert zeigt dasselbe"
                datei = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]["flur"]
                assert datei["pickTabs"][0]["picks"] == erwartet, datei
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


def test_abgelaufener_entwurf_sagt_es():
    """Trifft der Token nichts mehr (Server neu gestartet, abgelaufen), zeigt die
    Visu das gespeicherte Profil und kennzeichnet es rot, statt still etwas
    anderes zu zeigen, als der Konfigurator meint."""
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(STRUKTUR)
        app.states = {"s" + u: 0 for u in "ABCD"}
        app.panels = W.App._sanitize_panels({"flur": {"title": "Flur", "tabs": ["auswahl"],
                                                      "pickTabs": [{"name": "W", "picks": ["A"]}]}})
        runner, port, bc = await visu_starten(app, ROUTEN)
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 893, "height": 533})
                await pg.goto(f"http://127.0.0.1:{port}/?panel=flur&entwurf=abgelaufen")
                await pg.wait_for_selector("#grid .tile[data-id]", state="attached")
                assert await pg.evaluate(MARKE) == "Entwurf abgelaufen – gespeichertes Profil"
                assert await pg.evaluate("document.getElementById('entwurfMarke').classList.contains('alt')")
                assert await pg.evaluate(VISU) == ["A"]
                await pg.goto(f"http://127.0.0.1:{port}/?panel=flur")
                await pg.wait_for_selector("#grid .tile[data-id]", state="attached")
                assert await pg.evaluate(MARKE) == "", "ohne ?entwurf= keine Marke"
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
    asyncio.run(lauf())


def test_spaete_antwort_oeffnet_den_entwurf_nach_dem_speichern_nicht_neu(cfg_ordner):
    """Die Aktualisierung nach 600 ms ist schon unterwegs, wenn gespeichert wird.
    Ihre Antwort kommt erst nach dem Speichern und darf das Fenster nicht auf die
    Entwurfs-Adresse zurueckschicken, die der Server gerade beendet hat."""
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(STRUKTUR)
        app.states = {"s" + u: 0 for u in "ABCD"}
        app.panels = W.App._sanitize_panels({"flur": {"title": "Flur", "tabs": ["auswahl"], "ui": {"grid": "auto"},
                                                      "pickTabs": [{"name": "Wohnen", "picks": ["A"]}]}})
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1400, "height": 1000}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator("#plist .pitem", has_text="?panel=flur").click()
                await pg.locator(".stab[data-sub='seiten']").click()
                await pg.wait_for_selector("#seHost [data-se-flaeche]")
                async with pg.context.expect_page() as neue:
                    await pg.locator("#vorBtn").click()
                vorschau = await neue.value
                await vorschau.wait_for_selector("#grid .tile[data-id]", state="attached")

                # die Aktualisierung haengen lassen, sobald sie unterwegs ist
                unterwegs, frei = asyncio.Event(), asyncio.Event()

                async def haelt(route):
                    unterwegs.set()
                    await frei.wait()
                    await route.continue_()
                await pg.route("**/api/entwurf", haelt)
                await pg.locator("#seHost .se-p", has_text="Stehlampe").click()
                await asyncio.wait_for(unterwegs.wait(), 5)

                async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
                    await pg.locator("#saveBtn").click()
                assert (await (await antwort.value).json())["ok"]
                await _bis(vorschau, "location.search", "?panel=flur", "das Fenster verlaesst den Entwurf")
                frei.set()                                   # jetzt kommt die verspaetete Antwort
                await asyncio.sleep(1.5)
                assert await vorschau.evaluate("location.search") == "?panel=flur", "nicht zurueck auf den Entwurf"
                assert await vorschau.evaluate(MARKE) == ""
                assert not fehler, fehler
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
    asyncio.run(lauf())
