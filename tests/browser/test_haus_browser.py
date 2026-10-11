"""Hausuebersicht (Tab "haus") in Chromium: auf dem iPad quer und hochkant und
dem grossen Display, ohne Kachel-Set und in jedem Set. Nichts scrollt
waagerecht (dort blaettert der Wisch die Seiten), jede Taste ist mindestens
44 px gross, keine Karte schneidet ihren Inhalt ab, der Spieler steht quer
als Spalte und hochkant als Leiste. Bedient am Miniserver-Nachbau: Aus-Taste,
"+n weitere" mit Unterseite, Zentral-Taste, Lautstaerke, Zonenwechsel, Raum
oeffnen. Neue Zustaende tauschen nur ihren Block. Anlage: lox.haus_anlage().
Bilder im tmp_path (CI: Artefakt "screenshots")."""
import asyncio

import pytest

from lox import Miniserver, W, haus_anlage, neue_app, visu_starten
from test_front_tabs_browser import _front

import theme_colors as TC

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

GERAETE = {"ipad_quer": (1180, 820), "ipad_hoch": (820, 1180), "display": (1920, 1080)}
SETS = [""] + list(TC.KACHEL_SETS)

# Lage der Seite: was waagerecht scrollt, zu kleine Tasten, Karten, deren
# Inhalt unten herausragt, und wo der Spieler steht
LAGE = """() => {
  const g = document.getElementById('grid'), r = e => e.getBoundingClientRect();
  const sicht = e => e.offsetParent !== null && r(e).width > 0;
  const quer = [g, ...g.querySelectorAll('*')].filter(e => sicht(e) && e.scrollWidth > e.clientWidth + 1
    && !['hidden', 'clip'].includes(getComputedStyle(e).overflowX)).map(e => e.className);
  const klein = [...g.querySelectorAll('button')].filter(sicht).filter(b => r(b).width < 44 || r(b).height < 44)
    .map(b => b.className + ' ' + Math.round(r(b).width) + 'x' + Math.round(r(b).height));
  const ab = [...g.querySelectorAll('.hs-c')].filter(sicht).filter(c => [...c.querySelectorAll('*')]
    .some(k => sicht(k) && r(k).bottom > r(c).bottom + 1)).map(c => c.dataset.hb);
  const kopf = [...g.querySelectorAll('.hs-kopf .hs-k')].map(k => k.innerText.split(String.fromCharCode(10)).join(' '));
  return {quer, klein, ab, kopf, spalte: !!g.querySelector('.hs.spalte'), leiste: !!g.querySelector('.hs-sp.leiste'),
          raeume: g.querySelectorAll('.hs-r').length, aktiv: g.querySelectorAll('.hs-aktiv .hs-a.on').length,
          mehr: g.querySelector('.hs-mehr') ? g.querySelector('.hs-mehr').textContent : null,
          spalten: getComputedStyle(g).getPropertyValue('--hs-sp').trim()};
}"""


def _app(app=None, ui=None):
    struktur, states = haus_anlage()
    app = app or W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    app.states = states
    app.panels = W.App._sanitize_panels({"haus": {"title": "Haus", "tabs": ["haus", "favoriten"],
                                                  "ui": {"grid": "auto", **(ui or {})}}})
    return app


async def _seite(b, port, w, h, fehler):
    pg = await b.new_page(viewport={"width": w, "height": h}, locale="de-DE")
    pg.on("pageerror", lambda e: fehler.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{port}/?panel=haus")
    await pg.wait_for_selector("#grid.haus .hs-r", state="attached")
    await pg.evaluate("wake()")
    await pg.wait_for_timeout(500)
    return pg


@pytest.mark.parametrize("kset", SETS)
def test_lage_auf_tablet_und_display(kset, tmp_path, monkeypatch):
    async def lauf():
        app = _app(ui={"tileSet": kset} if kset else {})
        # Kopf mit Wetter (Vorschau morgen) und naechstem Termin aus der Front
        app._front = app._front_payload(await _front(monkeypatch))
        runner, port, bc = await visu_starten(app)
        erg, fehler = {}, []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                for name, (w, h) in GERAETE.items():
                    pg = await _seite(b, port, w, h, fehler)
                    erg[name] = await pg.evaluate(LAGE)
                    await pg.screenshot(path=str(tmp_path / f"haus_{kset or 'ohne'}_{name}.png"))
                    await pg.close()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return erg
    erg = asyncio.run(lauf())
    for name, m in erg.items():
        wo = (kset, name)
        assert not m["quer"], (wo, "scrollt waagerecht", m["quer"])
        assert not m["klein"], (wo, "Taste unter 44 px", m["klein"])
        assert not m["ab"], (wo, "Karte schneidet ab", m["ab"])
        assert m["raeume"] == 7, (wo, m)
        # vier Geraete an: so viele Karten wie Spalten, die letzte Stelle "+n weitere"
        sp = int(m["spalten"])
        assert m["aktiv"] == min(4, sp - 1 if sp < 4 else 4), (wo, m)
        assert (m["mehr"] is not None) == (sp < 4), (wo, m)
        if m["mehr"] is not None:
            assert m["mehr"].startswith(f"+{4 - m['aktiv']} weitere"), (wo, m)
    assert erg["ipad_quer"]["spalte"] and erg["display"]["spalte"], erg
    # Kopf: Wetter mit Vorschau, Termin, Energie (Verbrauch gross, Erzeugung klein)
    kopf = erg["ipad_quer"]["kopf"]
    assert len(kopf) == 3 and "°" in kopf[0] and "Morgen" in kopf[0], kopf
    assert kopf[2] == "100 W Verbrauch · PV 100 W", kopf
    assert erg["ipad_hoch"]["leiste"] and not erg["ipad_hoch"]["spalte"], erg


async def _befehle(ms, anzahl, warten=3.0):
    for _ in range(int(warten / 0.05)):
        if len(ms.io_roh) >= anzahl:
            break
        await asyncio.sleep(0.05)
    return list(ms.io_roh)


def test_bedienen(tmp_path, miniserver_http):
    async def lauf():
        ms = await Miniserver().start()
        app = _app(neue_app(ms))
        runner, port, bc = await visu_starten(app)
        fehler, erg = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _seite(b, port, 820, 1180, fehler)
                await pg.screenshot(path=str(tmp_path / "haus_hoch.png"))
                # Aus-Taste der ersten Karte (Licht Abstellraum)
                await pg.locator(".hs-aktiv .hs-a.on").first.locator("button").click()
                erg["aus"] = await _befehle(ms, 1)
                # "+n weitere" -> Unterseite mit allen, ohne waagerechtes Scrollen, zurueck
                await pg.locator(".hs-mehr").click()
                await pg.wait_for_selector("#grid .hs-liste")
                erg["liste"] = await pg.locator(".hs-liste .hs-a").count()
                erg["liste_lage"] = await pg.evaluate(LAGE)
                erg["liste_route"] = await pg.evaluate("view.route")
                await pg.screenshot(path=str(tmp_path / "haus_liste.png"))
                await pg.locator('[data-hs="zurueck"]').click()
                await pg.wait_for_selector("#grid .hs-raeume")
                # Zentral-Taste
                await pg.locator('[data-hs="zentral"][data-art="audio"]').click()
                erg["zentral"] = (await _befehle(ms, 2))[1:]
                # Lautstaerke +, dann meldet der Miniserver den neuen Wert: nur der
                # Spieler-Block wird getauscht, der Kopf bleibt dasselbe Element
                await pg.locator('[data-hs="laut"][data-d="1"]').click()
                erg["laut"] = (await _befehle(ms, 3))[2:]
                await pg.evaluate("window.__kopf = document.querySelector('[data-hb=kopf]');"
                                  "window.__sp = document.querySelector('[data-hb=sp]')")
                app.states["az3"] = 29
                app._dirty = True
                await pg.wait_for_function("document.querySelector('.hs-laut .v span').textContent === '29'")
                erg["patch"] = await pg.evaluate("[window.__kopf === document.querySelector('[data-hb=kopf]'),"
                                                 " window.__sp === document.querySelector('[data-hb=sp]')]")
                # Zone wechseln (Leiste: eine Taste schaltet weiter), dann Wiedergabe
                await pg.locator('.hs-sp [data-hs="zone"]').click()
                await pg.wait_for_function("view.spieler && view.spieler.zone === 'AB'")
                erg["zone_route"] = await pg.evaluate("[view.route.zone, stack.length]")
                await pg.locator('.hs-sp [data-hs="sp"][aria-label="Wiedergabe"]').click()
                erg["play"] = (await _befehle(ms, 4))[3:]
                # Raum oeffnen: die Raumseite des Servers, zurueck zur Hausseite
                await pg.locator(".hs-r", has_text="Sauna").click()
                await pg.wait_for_selector("#grid .tile[data-id='SA']")
                erg["raum"] = await pg.evaluate("[view.route, document.getElementById('grid').classList.contains('haus')]")
                await pg.locator("#tabback").click()
                await pg.wait_for_selector("#grid.haus .hs-r")
                await b.close()
        finally:
            bc.cancel()
            await app.icon_session.close()
            await runner.cleanup()
            await ms.stop()
        assert not fehler, fehler
        return erg
    erg = asyncio.run(lauf())
    assert erg["aus"] == ["sps/io/LA/changeTo/778"], erg
    assert erg["liste"] == 4 and erg["liste_route"] == {"view": "tab", "tab": "haus", "liste": "aktiv"}, erg
    assert not erg["liste_lage"]["quer"] and not erg["liste_lage"]["klein"], erg["liste_lage"]
    assert erg["zentral"] == ["sps/io/AZ/pause"], erg
    assert erg["laut"] == ["sps/io/AZ/volume/29"], erg
    assert erg["patch"] == [True, False], erg
    # Zonenwechsel ersetzt die Route, statt eine Seite auf den Stapel zu legen
    assert erg["zone_route"] == ["AB", 1], erg
    assert erg["play"] == ["sps/io/AB/play"], erg
    assert erg["raum"] == [{"view": "group", "kind": "room", "id": "r5"}, False], erg
