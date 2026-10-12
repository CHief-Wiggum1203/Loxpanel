"""Nach einem Server-Update in Chromium: Die Visu merkt sich den Stand
(Commit, theme-Nachricht "stand") der ersten Verbindung. Meldet der Server
nach dem Wiederverbinden einen anderen, laedt sie neu - einmal, nicht in
Schleife; derselbe Stand und ein Server ganz ohne Kennung laden nie neu. Ohne
Commit (lokaler Build ohne Git) gilt die Kennung des Inhalts genauso. Der
Konfigurator fragt den Stand ueber /api/devices ab: ohne offene Aenderungen
laedt er neu, mit offenen sagt es die Speicherleiste und er laedt erst nach
dem Speichern. Das Update stellt der Test nach, indem er W.VERSION aendert
und die Verbindungen der Visu vom Server aus schliesst."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, visu_starten
from test_kachel_set_browser import ROUTEN

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "LA", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}}}
OFFEN = "document.querySelector('#offenTxt').textContent"


def _app():
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"sl": 0}
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"]}})
    return app


async def _trennen(app):
    """Verbindungen der Visu vom Server aus schliessen (wie ein Neustart)."""
    for ws in list(app.conn_route):
        await ws.close()


async def _bis(pg, ausdruck, ms=6000):
    await pg.wait_for_function(ausdruck, timeout=ms)


@pytest.mark.parametrize("feld, commit", [("commit", "alt-1234"), ("inhalt", "alt-1234"), ("commit", "")],
                         ids=["commit", "inhalt-ohne-git", "ohne-kennung"])
def test_visu_laedt_nach_update_neu(feld, commit, monkeypatch):
    monkeypatch.setitem(W.VERSION, "commit", "")
    monkeypatch.setitem(W.VERSION, "inhalt", "")
    monkeypatch.setitem(W.VERSION, feld, commit)

    async def lauf():
        app = _app()
        runner, port, bc = await visu_starten(app)
        fehler, ladungen, erg = [], [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 800, "height": 600})
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                pg.on("load", lambda: ladungen.append(1))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector(".tile[data-id]", state="attached")
                await _bis(pg, "serverStand !== null || " + json.dumps(commit == ""))
                erg["erster"] = await pg.evaluate("serverStand")
                await pg.evaluate("window.__alteSeite = true")

                # derselbe Stand: wiederverbinden, nicht neu laden
                await _trennen(app)
                await _bis(pg, "verb.server")
                await pg.wait_for_timeout(2500)
                erg["gleich"] = [await pg.evaluate("window.__alteSeite === true"), len(ladungen)]

                # neuer Stand
                monkeypatch.setitem(W.VERSION, feld, commit and "neu-5678")
                await _trennen(app)
                await pg.wait_for_timeout(3500)
                await pg.wait_for_selector(".tile[data-id]", state="attached")
                erg["neu"] = [await pg.evaluate("window.__alteSeite === true"), len(ladungen),
                              await pg.evaluate("serverStand")]
                # ein weiteres Wiederverbinden mit demselben neuen Stand: kein zweites Neuladen
                await _trennen(app)
                await pg.wait_for_timeout(3000)
                erg["danach"] = len(ladungen)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return erg
    erg = asyncio.run(lauf())
    if commit:
        assert erg["erster"] == commit, erg
        assert erg["gleich"] == [True, 1], erg
        assert erg["neu"] == [False, 2, "neu-5678"], erg
        assert erg["danach"] == 2, erg
    else:
        # ohne Commit kennt der Server keinen Stand: nie neu laden
        assert erg["erster"] is None and erg["gleich"] == [True, 1], erg
        assert erg["neu"][:2] == [True, 1] and erg["danach"] == 1, erg


@pytest.mark.parametrize("feld", ["commit", "inhalt"], ids=["commit", "inhalt-ohne-git"])
def test_konfigurator_laedt_nach_update_neu(cfg_ordner, monkeypatch, feld):
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"flur": {"title": "Flur", "tabs": ["favoriten"]}}}),
                                            encoding="utf-8")
    monkeypatch.setitem(W.VERSION, "commit", "")
    monkeypatch.setitem(W.VERSION, "inhalt", "")
    monkeypatch.setitem(W.VERSION, feld, "alt-1234")

    async def lauf():
        app = _app()
        app.panels = W.load_panels()
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler, ladungen, erg = [], [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                pg.on("load", lambda: ladungen.append(1))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await _bis(pg, "SERVER_STAND === 'alt-1234'")

                # ohne offene Aenderungen: neu laden
                monkeypatch.setitem(W.VERSION, feld, "neu-5678")
                await pg.evaluate("pollDevices()")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await _bis(pg, "SERVER_STAND === 'neu-5678'")
                erg["ohne"] = len(ladungen)

                # mit offener Aenderung: Hinweis statt Neuladen, nach dem Speichern neu laden
                await pg.locator("#plist .pitem", has_text="?panel=flur").click()
                await pg.locator(".stab[data-sub='aussehen']").click()
                await pg.fill("#pconfHost input[data-ui='iconSize']", "40")
                monkeypatch.setitem(W.VERSION, feld, "neu-9999")
                await pg.evaluate("pollDevices()")
                await _bis(pg, "!document.getElementById('standNeu').hidden")
                erg["hinweis"] = [len(ladungen), await pg.locator("#standNeu").inner_text(), await pg.evaluate(OFFEN)]
                await pg.locator("#saveBtn").click()
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await _bis(pg, "SERVER_STAND === 'neu-9999'")
                erg["gespeichert"] = [len(ladungen),
                                      json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))
                                      ["panels"]["flur"]["ui"].get("iconSize")]
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return erg
    erg = asyncio.run(lauf())
    assert erg["ohne"] == 2, erg
    assert erg["hinweis"][0] == 2 and "Neuer Stand auf dem Server" in erg["hinweis"][1], erg
    assert erg["hinweis"][2].startswith("Nicht gespeichert"), erg
    assert erg["gespeichert"] == [3, 40], erg
