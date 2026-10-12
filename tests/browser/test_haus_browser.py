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
  // ragt etwas unten heraus, oder sind die Zeilen einer Raumkarte gequetscht (liegen
  // uebereinander oder ihr Text laeuft aus dem Kasten; 3 px Rundung von Pfeil und Name)?
  const ab = [...g.querySelectorAll('.hs-c')].filter(sicht).filter(c => [...c.querySelectorAll('*')]
    .some(k => sicht(k) && r(k).bottom > r(c).bottom + 1)
    || (c.classList.contains('hs-r') && [...c.children].filter(sicht)
        .some((k, i, l) => (i > 0 && r(k).top < r(l[i - 1]).bottom - 1) || k.scrollHeight > k.clientHeight + 3))).map(c => c.dataset.hb);
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


def test_hausseite_aus_dem_seiten_editor(cfg_ordner, tmp_path):
    """Eigene Auswahl: im Seiten-Editor legt "＋ Haus" eine Seite mit der
    Hausuebersicht an (danach gibt es die Taste nicht mehr), sie wird
    gespeichert, und die Visu zeigt sie als Hausseite mit dem Haus in der
    Leiste. Wer die Ansicht nicht auf "Klassisch" stellt, findet sie so."""
    import json
    from lox import KONFIGURATOR_GELADEN
    from test_auswahl_seiten_browser import ROUTEN
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"flur": {
        "title": "Flur", "tabs": ["auswahl"], "pickTabs": [{"name": "Licht", "picks": ["LA"]}]}}}),
        encoding="utf-8")

    async def lauf():
        struktur, states = haus_anlage()
        app = W.App({"host": "", "port": 80})
        app._apply_structure(struktur)
        app.states = states
        app.panels = W.load_panels()
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler, erg = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator("#plist .pitem", has_text="Flur").click()
                await pg.locator(".stab[data-sub='seiten']").click()
                await pg.locator("#seHost [data-se-neu-haus]").click()
                erg["inhalt"] = await pg.locator("#seHost [data-se-inhalt]").input_value()
                erg["taste_weg"] = await pg.locator("#seHost [data-se-neu-haus]").count()
                await pg.screenshot(path=str(tmp_path / "seiten_editor_haus.png"), full_page=True)
                async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
                    await pg.locator("#saveBtn").click()
                erg["antwort"] = await (await antwort.value).json()
                erg["flur"] = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]["flur"]
                app.panels = W.load_panels()
                visu = await b.new_page(viewport={"width": 820, "height": 1180}, locale="de-DE")
                visu.on("pageerror", lambda e: fehler.append(str(e)))
                await visu.goto(f"http://127.0.0.1:{port}/?panel=flur")
                await visu.wait_for_selector("#tabs .tab[data-tab='auswahl2']", state="attached")
                await visu.evaluate("wake()")
                await visu.locator("#tabs .tab[data-tab='auswahl2']").click()
                await visu.wait_for_selector("#grid.haus .hs-r")
                erg["visu"] = await visu.evaluate("""() => [view.layout, view.title,
                  document.querySelector("#tabs .tab[data-tab='auswahl2'] svg").innerHTML.includes('M10 20v-6h4v6')]""")
                await visu.screenshot(path=str(tmp_path / "haus_als_freie_seite.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return erg
    erg = asyncio.run(lauf())
    assert erg["inhalt"] == "haus" and erg["taste_weg"] == 0, erg
    assert erg["antwort"]["ok"] and erg["antwort"]["verworfen"] == [], erg["antwort"]
    assert erg["flur"]["tabs"] == ["auswahl", "auswahl2"], erg["flur"]
    assert erg["flur"]["pickTabs"][1] == {"name": "Haus", "picks": [], "widget": "haus"}, erg["flur"]
    assert erg["visu"] == ["haus", "Haus", True], erg


def test_haus_taste_in_der_klassischen_leiste(cfg_ordner):
    """Steht die Ansicht auf "Klassisch", zeigte die Visu eine freie Seite
    nicht: "＋ Haus" setzt dann den Tab "haus" in die Leiste, danach ist die
    Taste weg."""
    import json
    from lox import KONFIGURATOR_GELADEN
    from test_auswahl_seiten_browser import ROUTEN
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"flur": {
        "title": "Flur", "tabs": ["favoriten", "raeume"]}}}), encoding="utf-8")

    async def lauf():
        struktur, states = haus_anlage()
        app = W.App({"host": "", "port": 80})
        app._apply_structure(struktur)
        app.states = states
        app.panels = W.load_panels()
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler, erg = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator("#plist .pitem", has_text="Flur").click()
                await pg.locator(".stab[data-sub='seiten']").click()
                await pg.locator("#seHost [data-se-neu-haus]").click()
                erg["taste_weg"] = await pg.locator("#seHost [data-se-neu-haus]").count()
                async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
                    await pg.locator("#saveBtn").click()
                erg["antwort"] = await (await antwort.value).json()
                erg["flur"] = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]["flur"]
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return erg
    erg = asyncio.run(lauf())
    assert erg["taste_weg"] == 0 and erg["antwort"]["ok"], erg
    assert erg["flur"]["tabs"] == ["favoriten", "raeume", "haus"], erg["flur"]
    assert "pickTabs" not in erg["flur"] or not any(s.get("widget") == "haus" for s in erg["flur"]["pickTabs"]), erg


def test_lange_raumnamen_schneiden_nichts_ab(tmp_path):
    """Viele Raeume mit langen Namen (zwei Zeilen) und Raumregelung, Set
    Kreide in einem Fenster wie am Mac: keine Raumkarte schneidet ihre
    Zeilen ab, die Liste scrollt dafuer senkrecht; die gewaehlte Zone ist
    auch dort zu erkennen, wo --kachel-an der Kachel gleicht (Ring)."""
    struktur, states = haus_anlage()
    for i, name in enumerate(["Essen-Kochen-Wohnen Ost", "Gang Vorzimmer Nord", "Gästezimmer Dachgeschoss",
                              "Hauswirtschaftsraum", "Kinderzimmer Anna", "Schlafzimmer Eltern"]):
        ru = f"x{i}"
        struktur["rooms"][ru] = {"name": name}
        struktur["controls"][f"R{i}"] = {"name": "Raumregelung", "type": "IRoomControllerV2", "uuidAction": f"R{i}",
                                         "room": ru, "cat": "c1",
                                         "states": {"tempActual": f"r{i}a", "tempTarget": f"r{i}t", "prepareState": f"r{i}p"}}
        struktur["controls"][f"S{i}"] = {"name": "Licht", "type": "Switch", "uuidAction": f"S{i}", "room": ru,
                                         "cat": "c1", "states": {"active": f"s{i}"}}
        states.update({f"r{i}a": 23.2, f"r{i}t": 23.0, f"r{i}p": 0, f"s{i}": 0})

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(struktur)
        app.states = states
        app.panels = W.App._sanitize_panels({"haus": {"title": "Haus", "tabs": ["haus"],
                                                      "ui": {"grid": "auto", "tileSet": "kreide"}}})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _seite(b, port, 1440, 820, fehler)
                lage = await pg.evaluate(LAGE)
                ring = await pg.evaluate("getComputedStyle(document.querySelector('.hs-zone.akt')).boxShadow")
                await pg.screenshot(path=str(tmp_path / "haus_kreide_lange_namen.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return lage, ring
    lage, ring = asyncio.run(lauf())
    assert lage["raeume"] == 13 and not lage["ab"], lage
    assert not lage["quer"] and not lage["klein"], lage
    assert lage["spalte"] and ring not in ("", "none"), ring
