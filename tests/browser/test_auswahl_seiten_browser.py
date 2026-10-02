"""Freie Auswahl mit vier Seiten im Konfigurator (Chromium), bedient wie von
Hand: je Seite Name, Icon und Inhalt (Kacheln in Klickreihenfolge oder ein
Widget), speichern, Konfigurator neu laden, weiter bearbeiten und wieder
speichern. Genau dort gingen frueher die Seiten 2-4 verloren (#47): /api/meta
lieferte pickTabs nicht mit, nach dem Neuladen kannte der Editor nur eine
Seite und kuerzte beim naechsten Speichern die Leiste. Am Ende zeigt die Visu
alle vier Seiten mit Namen, Icon und Inhalt. Der Config-Ordner ist
umgeleitet (Fixture cfg_ordner)."""
import asyncio
import json
from urllib.parse import quote

import pytest

from lox import KONFIGURATOR_GELADEN, W, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser


def _schalter(uuid, name, raum):
    return {"name": name, "type": "Switch", "uuidAction": uuid, "room": raum, "cat": "c1",
            "states": {"active": "s" + uuid}}


STRUKTUR = {
    "rooms": {"r1": {"name": "Küche", "image": "IconsFilled/kueche.svg"},
              "r2": {"name": "Wohnzimmer", "image": "IconsFilled/sofa.svg"}},
    "cats": {"c1": {"name": "Beleuchtung", "image": "IconsFilled/licht.svg"}},
    "controls": {u: _schalter(u, n, r) for u, n, r in (
        ("K1", "Licht Küche", "r1"), ("K2", "Kaffeemaschine", "r1"),
        ("W1", "Licht Wohnen", "r2"), ("W2", "Leselampe", "r2"), ("A1", "Alarmanlage", "r2"))},
}
NAME_UUID = {c["name"]: u for u, c in STRUKTUR["controls"].items()}
# Vier Seiten: Name, Icon (Loxone-Pfad aus der Struktur, None = keins),
# Bausteine in Klickreihenfolge, Widget. Seite 2 weicht von der Listen-
# reihenfolge ab, Seite 3 greift ueber zwei Raeume und teilt einen Baustein
# mit Seite 1, Seite 4 ist ein Widget statt Kacheln.
SEITEN = [("Morgens", "IconsFilled/kueche.svg", ["Licht Küche", "Kaffeemaschine"], ""),
          ("Abends", "IconsFilled/sofa.svg", ["Leselampe", "Licht Wohnen"], ""),
          ("Urlaub", None, ["Alarmanlage", "Licht Küche"], ""),
          ("Wetter", "IconsFilled/licht.svg", [], "weather")]
TABS = ["auswahl", "auswahl2", "auswahl3", "auswahl4"]
ROUTEN = [("POST", "/api/panels", W.api_save_panels), ("POST", "/api/theme", W.api_save_theme),
          ("GET", "/api/loxicons", W.loxicons_handler)]

# Name und Icon der Seiten in der Leiste ueber dem Editor
LEISTE = """l => l.map(b => { const i = b.querySelector('.loxi');
  return [Array.from(b.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent).join(''),
          i ? i.getAttribute('style') : '']; })"""
TEXT = "l => l.map(c => Array.from(c.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent).join(''))"
KACHELN = "() => Array.from(document.querySelectorAll('#grid .tile .name')).map(n => n.textContent)"


def _icon_url(icon):
    return "/icon?p=" + quote(icon, safe="") if icon else ""


def _erwartet(name1):
    """pickTabs, wie sie in panels.json stehen sollen (Seite 1 heisst name1)."""
    seiten = []
    for i, (name, icon, bausteine, widget) in enumerate(SEITEN):
        e = {"name": name1 if i == 0 else name, "picks": [NAME_UUID[n] for n in bausteine]}
        if icon:
            e["icon"] = _icon_url(icon)
        if widget:
            e["widget"] = widget
        seiten.append(e)
    return seiten


async def _konfigurator(pg, port):
    """Konfigurator (neu) laden und das Panel Flur oeffnen (Reiter Tabs)."""
    await pg.goto(f"http://127.0.0.1:{port}/config")
    await pg.wait_for_function(KONFIGURATOR_GELADEN)
    await pg.locator("#plist .pitem", has_text="Flur").click()


async def _speichern(pg, cfg_ordner):
    async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
        await pg.locator("#saveBtn").click()
    j = await (await antwort.value).json()
    assert j["ok"] and j["verworfen"] == [], j
    await pg.wait_for_function("document.querySelector('#toast').textContent.startsWith('✓ Gespeichert')")
    return json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]["flur"]


async def _seite_fuellen(pg, name, icon, bausteine, widget):
    await pg.locator("#pickName").fill(name)
    if icon:
        await pg.locator(f'#tabPick .picogrid .pgi[title="{icon}"]').click()
    for n in bausteine:
        await pg.locator("#pickList .trow", has_text=n).click()
    if widget:
        await pg.locator("#pickContent").select_option(widget)


async def _kacheln(visu, erwartet):
    """Warten, bis die Visu genau diese Kacheln zeigt."""
    for _ in range(100):
        if await visu.evaluate(KACHELN) == erwartet:
            return
        await asyncio.sleep(0.05)
    assert await visu.evaluate(KACHELN) == erwartet


def test_vier_seiten_ueberstehen_speichern_und_neuladen(cfg_ordner, tmp_path):
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"flur": {
        "title": "Flur", "tabs": ["favoriten", "zentral", "raeume", "kategorien"]}}}), encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(STRUKTUR)
        app.states = {"s" + u: 0 for u in STRUKTUR["controls"]}
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler, dialoge = [], []

        async def dialog(d):
            dialoge.append(d.message)
            await d.dismiss()
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                pg.on("dialog", dialog)
                await _konfigurator(pg, port)

                # Eigene Auswahl, vier Seiten anlegen; mehr als vier gibt es nicht
                await pg.locator("#tabMode button[data-mode='pick']").click()
                for i, seite in enumerate(SEITEN):
                    if i:
                        await pg.locator("#ptAdd").click()
                    await _seite_fuellen(pg, *seite)
                assert await pg.locator("#ptAdd").count() == 0
                flur = await _speichern(pg, cfg_ordner)
                assert flur["tabs"] == TABS
                assert flur["pickTabs"] == _erwartet("Morgens")

                # Neu laden: alle vier Seiten mit Name, Icon und Inhalt
                await _konfigurator(pg, port)
                assert await pg.locator("#tabMode button.on").get_attribute("data-mode") == "pick"
                leiste = await pg.locator(".picktabbar .ptb").evaluate_all(LEISTE)
                assert [n for n, _ in leiste] == [s[0] for s in SEITEN]
                for (_, stil), (name, icon, _, _) in zip(leiste, SEITEN):
                    assert (_icon_url(icon) in stil) if icon else stil == "", (name, stil)
                for i, (name, icon, bausteine, widget) in enumerate(SEITEN):
                    await pg.locator(".picktabbar .ptb").nth(i).click()
                    assert await pg.locator("#pickName").input_value() == name
                    assert await pg.locator("#tabPick .picogrid .pgi.on").get_attribute("data-pic") == _icon_url(icon)
                    assert await pg.locator("#pickContent").input_value() == widget
                    assert await pg.locator("#picked .chip").evaluate_all(TEXT) == bausteine
                await pg.screenshot(path=str(tmp_path / "auswahl_konfigurator.png"), full_page=True)

                # Weiter bearbeiten und wieder speichern: die Leiste bleibt bei vier Seiten
                await pg.locator(".picktabbar .ptb").nth(0).click()
                await pg.locator("#pickName").fill("Früh")
                flur = await _speichern(pg, cfg_ordner)
                assert flur["tabs"] == TABS
                assert flur["pickTabs"] == _erwartet("Früh")

                # Die Visu zeigt alle vier Seiten mit Name, Icon und Inhalt
                visu = await b.new_page(viewport={"width": 1024, "height": 600})
                visu.on("pageerror", lambda e: fehler.append(str(e)))
                await visu.goto(f"http://127.0.0.1:{port}/?panel=flur")
                reiter = visu.locator("#tabs .tab[data-tab]")
                await reiter.nth(3).wait_for()
                await visu.locator("#saver").click()        # Uhr-Seite wegtippen
                await visu.wait_for_function("document.getElementById('saver').classList.contains('hidden')")
                assert await reiter.evaluate_all("l => l.map(t => [t.dataset.tab, t.title])") == [
                    [t, n] for t, n in zip(TABS, ["Früh"] + [s[0] for s in SEITEN[1:]])]
                stile = await reiter.evaluate_all(
                    "l => l.map(t => { const i = t.querySelector('.tico'); return i ? i.getAttribute('style') : ''; })")
                for stil, (name, icon, _, _) in zip(stile, SEITEN):
                    assert (_icon_url(icon) in stil) if icon else stil == "", (name, stil)
                for i, (_, _, bausteine, widget) in enumerate(SEITEN):
                    await reiter.nth(i).click()
                    if widget:
                        await visu.wait_for_function("document.querySelector('.screen').classList.contains('widgettab')")
                        assert await visu.locator("#frontpane").is_visible()
                        assert await visu.locator("#frontpane").text_content() == "Kein Wetter konfiguriert."
                    else:
                        await _kacheln(visu, bausteine)
                await visu.screenshot(path=str(tmp_path / "auswahl_visu.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        assert dialoge == [], "keine Rueckfrage: die Standardleiste darf kommentarlos weichen"
    asyncio.run(lauf())
