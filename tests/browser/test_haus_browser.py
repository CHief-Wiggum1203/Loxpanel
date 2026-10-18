"""Hausuebersicht (Tab "haus") in Chromium: auf dem iPad quer und hochkant und
dem grossen Display, ohne Kachel-Set und in jedem Set. Nichts scrollt
waagerecht (dort blaettert der Wisch die Seiten), jede Taste ist mindestens
44 px gross, keine Karte schneidet ihren Inhalt ab, der Spieler steht quer
als Spalte und hochkant als Leiste. Bedient am Miniserver-Nachbau: Aus-Taste,
"+n weitere" mit Unterseite, Schnellaktionen, Lautstaerke, Zonenwechsel, Raum
oeffnen. Neue Zustaende tauschen nur ihren Block. Die Hinweise als Leiste und
in "Auf einen Blick", mit Unterseite und den Terminen des Tages; die Sender
im Spieler als grosse Cover. Anlage: lox.haus_anlage().
Bilder im tmp_path (CI: Artefakt "screenshots")."""
import asyncio
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from aiohttp import web

from lox import konfig, HAUS_FAVORITEN, Miniserver, W, haus_anlage, neue_app, serve, visu_starten
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
  // In einer Liste, die senkrecht scrollt ("Auf einen Blick"), ist nichts
  // abgeschnitten; die Liste selbst muss in die Karte passen
  const rollt = (k, c) => { for (let e = k.parentElement; e && e !== c; e = e.parentElement)
    if (['auto', 'scroll'].includes(getComputedStyle(e).overflowY)) return true; return false; };
  const ab = [...g.querySelectorAll('.hs-c')].filter(sicht).filter(c => [...c.querySelectorAll('*')]
    .some(k => sicht(k) && r(k).bottom > r(c).bottom + 1 && !rollt(k, c))
    || (c.classList.contains('hs-r') && [...c.children].filter(sicht)
        .some((k, i, l) => (i > 0 && r(k).top < r(l[i - 1]).bottom - 1) || k.scrollHeight > k.clientHeight + 3))).map(c => c.dataset.hb);
  const kopf = [...g.querySelectorAll('.hs-kopf .hs-k')].map(k => k.innerText.split(String.fromCharCode(10)).join(' '));
  return {quer, klein, ab, kopf, spalte: !!g.querySelector('.hs.spalte'), leiste: !!g.querySelector('.hs-sp.leiste'),
          raeume: g.querySelectorAll('.hs-r').length, aktiv: g.querySelectorAll('.hs-aktiv .hs-a.on').length,
          mehr: g.querySelector('.hs-mehr') ? g.querySelector('.hs-mehr').textContent : null,
          schnell: g.querySelectorAll('.hs-schnell [data-hs="schnell"]').length,
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
        assert m["schnell"] == 2, (wo, "Schnellaktionen", m)
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
                # Schnellaktion "Alle Zonen aus"
                await pg.locator('[data-hs="schnell"][data-art="audio"]').click()
                erg["schnell"] = (await _befehle(ms, 2))[1:]
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
                # die Zone Abstellraum hat noch keine Favoriten: der Server fordert
                # sie fuer ihre Sender an (roomfav/get), dazu der Befehl der Taste
                erg["play"] = sorted((await _befehle(ms, 5))[3:])
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
    assert erg["schnell"] == ["sps/io/CA/pause"], erg
    assert erg["laut"] == ["sps/io/AZ/volume/29"], erg
    assert erg["patch"] == [True, False], erg
    # Zonenwechsel ersetzt die Route, statt eine Seite auf den Stapel zu legen
    assert erg["zone_route"] == ["AB", 1], erg
    assert erg["play"] == ["sps/io/AB/play", "sps/io/AB/roomfav/get/0/20"], erg
    assert erg["raum"] == [{"view": "group", "kind": "room", "id": "r5"}, False], erg


# Schnellaktionen: je Knopf Text, Anzahl, Vorlesetext, Hoehe, Radius, Flaeche
# und Farbe der Anzahl; dazu die Werte der Tokens (--tile, --glow, Radius der
# Karten) zum Vergleich und die Folge der Zeilen der Seite
SCHNELL = """() => {
  const g = document.getElementById('grid'), hk = parseFloat(g.style.getPropertyValue('--hk'));
  const probe = st => { const p = document.createElement('span'); Object.assign(p.style, st); g.appendChild(p);
    const s = getComputedStyle(p), w = {farbe: s.color, grund: s.backgroundColor}; p.remove(); return w; };
  return {hk, glow: probe({color: 'var(--glow)'}).farbe, tile: probe({background: 'var(--tile)'}).grund,
    karteRadius: getComputedStyle(g.querySelector('.hs-r')).borderTopLeftRadius,
    folge: [...g.querySelector('.hs-main').children].map(e => e.classList[0]),
    knoepfe: [...g.querySelectorAll('[data-hs="schnell"]')].map(b => { const s = getComputedStyle(b);
      return {art: b.dataset.art, text: b.querySelector('.z').textContent, n: b.querySelector('.n').textContent,
              aria: b.getAttribute('aria-label'), hoehe: b.getBoundingClientRect().height,
              radius: s.borderTopLeftRadius, grund: s.backgroundColor, farbe: getComputedStyle(b.querySelector('.n')).color}; })};
}"""


def _anzahl(art):
    return f"document.querySelector('[data-hs=schnell][data-art={art}] .n').textContent"


def test_schnellaktionen(tmp_path, miniserver_http):
    """"Alle Lichter aus" und "Alle Zonen aus" unter "Gerade aktiv" im Set
    Loxone: so hoch wie im Entwurf (72 px bei --hk 1), Radius und Flaeche der
    Karten des Sets, rechts die Anzahl ("1 an") in --glow. Ein Tipp schickt
    den Befehl an den Zentral-Baustein; meldet der Miniserver die Mitglieder
    aus, verschwindet die Anzahl von selbst (live ueber die States), und
    sie kommt wieder, sobald eine Zone spielt."""
    async def lauf():
        ms = await Miniserver().start()
        app = _app(neue_app(ms), ui={"tileSet": "loxone"})
        runner, port, bc = await visu_starten(app)
        fehler, erg = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _seite(b, port, 1180, 820, fehler)
                erg["vorher"] = await pg.evaluate(SCHNELL)
                await pg.screenshot(path=str(tmp_path / "haus_schnell_vorher.png"))
                await pg.locator('[data-hs="schnell"][data-art="licht"]').click()
                erg["licht"] = await _befehle(ms, 1)
                # der Miniserver meldet die Lichtsteuerung aus, wie nach "reset"
                app._on_value("la1", json.dumps([778]))
                await pg.wait_for_function(_anzahl("licht") + " === ''")
                await pg.locator('[data-hs="schnell"][data-art="audio"]').click()
                erg["audio"] = (await _befehle(ms, 2))[1:]
                app._on_value("az1", 0)
                await pg.wait_for_function(_anzahl("audio") + " === ''")
                erg["nachher"] = await pg.evaluate(SCHNELL)
                await pg.screenshot(path=str(tmp_path / "haus_schnell_nachher.png"))
                # eine Zone spielt wieder: die Anzahl kommt zurueck
                app._on_value("ab1", 2)
                await pg.wait_for_function(_anzahl("audio") + " === '1 an'")
                await b.close()
        finally:
            bc.cancel()
            await app.icon_session.close()
            await runner.cleanup()
            await ms.stop()
        assert not fehler, fehler
        return erg
    erg = asyncio.run(lauf())
    v = erg["vorher"]
    assert v["folge"] == ["hs-kopf", "hs-zeile", "hs-aktiv", "hs-schnell", "hs-raeume"], v["folge"]
    knopf = {k["art"]: k for k in v["knoepfe"]}
    assert list(knopf) == ["licht", "audio"], v
    assert (knopf["licht"]["text"], knopf["licht"]["n"]) == ("Alle Lichter aus", "1 an"), knopf
    assert (knopf["audio"]["text"], knopf["audio"]["n"]) == ("Alle Zonen aus", "1 an"), knopf
    assert knopf["licht"]["aria"] == "Alle Lichter aus, 1 an", knopf
    radius = float(TC.KACHEL_SETS["loxone"]["masse"]["--kachel-radius"].rstrip("px"))
    for k in knopf.values():
        assert abs(k["hoehe"] - max(44, 72 * v["hk"])) < 0.5, (k, v["hk"])
        assert k["radius"] == v["karteRadius"] and abs(float(k["radius"].rstrip("px")) - radius * v["hk"]) < 0.5, k
        assert k["grund"] == v["tile"] and k["farbe"] == v["glow"], (k, v["tile"], v["glow"])
    assert erg["licht"] == ["sps/io/CL/reset"], erg
    assert erg["audio"] == ["sps/io/CA/pause"], erg
    nachher = {k["art"]: k for k in erg["nachher"]["knoepfe"]}
    assert [k["n"] for k in nachher.values()] == ["", ""], nachher
    assert nachher["licht"]["aria"] == "Alle Lichter aus", nachher


def test_musikauswahl_im_spieler(tmp_path):
    """Die drei Punkte rechts oben im Spieler oeffnen wie auf der Detailseite
    der Audio-Zone ihre Musikauswahl (Sender, Favoriten), quer in der Spalte
    und hochkant in der Leiste; zurueck fuehrt zur Hausseite."""
    async def lauf():
        app = _app()
        runner, port, bc = await visu_starten(app)
        fehler, erg = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                for name, (w, h) in (("quer", (1180, 820)), ("hoch", (820, 1180))):
                    pg = await _seite(b, port, w, h, fehler)
                    e = erg[name] = {"lage": await pg.evaluate(LAGE)}
                    knopf = pg.locator('.hs-sp .hs-drei')
                    e["aria"] = await knopf.get_attribute("aria-label")
                    # rechts oben im Spieler: rechter Rand wie der Spieler, oberste Zeile
                    e["ort"] = await pg.evaluate("""() => { const k = document.querySelector('.hs-sp .hs-drei')
                      .getBoundingClientRect(), s = document.querySelector('.hs-sp').getBoundingClientRect();
                      return [Math.round(s.right - k.right), Math.round(k.top - s.top)]; }""")
                    await pg.screenshot(path=str(tmp_path / f"haus_musikauswahl_{name}.png"))
                    await knopf.click()
                    await pg.wait_for_function("view && view.route && view.route.view === 'sources'")
                    e["route"] = await pg.evaluate("view.route")
                    await pg.locator("#tabback").click()
                    await pg.wait_for_selector("#grid.haus .hs-r")
                    e["zurueck"] = await pg.evaluate("view.layout")
                    await pg.close()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return erg
    erg = asyncio.run(lauf())
    for name, e in erg.items():
        assert not e["lage"]["klein"] and not e["lage"]["quer"] and not e["lage"]["ab"], (name, e["lage"])
        assert e["aria"] == "Musikauswahl Essen-Kochen-Wohnen", (name, e)
        assert e["route"] == {"view": "sources", "id": "AZ"} and e["zurueck"] == "haus", (name, e)
    # quer oben in der Spalte (Kopfzeile des Spielers), hochkant in der ersten Zeile der Leiste
    assert all(0 <= v <= 40 for v in erg["quer"]["ort"]), erg["quer"]["ort"]
    assert all(0 <= v <= 40 for v in erg["hoch"]["ort"]), erg["hoch"]["ort"]


def test_ohne_zentral_baustein_kein_knopf(tmp_path):
    """Ohne Zentral-Licht und Audio-Zentral gibt es keine Schnellaktion, auch
    wenn Licht und Musik an sind; "Gerade aktiv" bleibt, nichts ist zu klein
    oder abgeschnitten. Ist dann alles aus, steht dort "Alles ruhig" - die
    Zeile haengt nicht an den Schnellaktionen."""
    struktur, states = haus_anlage()
    del struktur["controls"]["CL"], struktur["controls"]["CA"]

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(struktur)
        app.states = states
        app.panels = W.App._sanitize_panels({"haus": {"title": "Haus", "tabs": ["haus"], "ui": {"grid": "auto"}}})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _seite(b, port, 1180, 820, fehler)
                lage = await pg.evaluate(LAGE)
                lage["zeile"] = await pg.locator(".hs-schnell").count()
                await pg.screenshot(path=str(tmp_path / "haus_ohne_zentral.png"))
                # alles aus: Licht (Stimmung Aus), Dimmer, Schalter, Zone
                app.states.update({"la1": json.dumps([778]), "al": 0, "fs": 0, "az1": 0})
                app._dirty = True
                await pg.wait_for_selector('[data-hb="ruhig"]')
                ruhig = {**await pg.evaluate(LAGE),
                         "text": await pg.locator('[data-hb="ruhig"]').inner_text(),
                         "kopf": await pg.locator('[data-hb="akopf"]').count()}
                await pg.screenshot(path=str(tmp_path / "haus_ohne_zentral_ruhig.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return lage, ruhig
    lage, ruhig = asyncio.run(lauf())
    assert lage["schnell"] == 0 and lage["zeile"] == 0, lage
    assert lage["aktiv"] >= 1 and not lage["klein"] and not lage["ab"] and not lage["quer"], lage
    assert ruhig["kopf"] == 1 and ruhig["text"].split("\n") == ["Alles ruhig", "Kein Licht an, keine Musik"], ruhig
    assert ruhig["aktiv"] == 0 and not ruhig["klein"] and not ruhig["ab"] and not ruhig["quer"], ruhig


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
        app.panels = konfig.load_panels()
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
                app.panels = konfig.load_panels()
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
        app.panels = konfig.load_panels()
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
                # neue Zustaende bei gleicher Lage: updateHaus statt Neuaufbau, das die
                # Masse neu setzt - auch danach ist nichts gequetscht
                ohne_neuaufbau = await pg.evaluate("updateHaus()")
                lage2 = await pg.evaluate(LAGE)
                lage2["ohne_neuaufbau"] = ohne_neuaufbau
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return lage, ring, lage2
    lage, ring, lage2 = asyncio.run(lauf())
    assert lage["raeume"] == 13 and not lage["ab"], lage
    assert lage2["ohne_neuaufbau"] and not lage2["ab"], lage2
    assert not lage["quer"] and not lage["klein"], lage
    assert lage["spalte"] and ring not in ("", "none"), ring


# --hk wie angewandt und wie frisch gerechnet, Schrift des ersten Raumnamens, Signatur
HK = """() => { const g = document.getElementById('grid'), n = g.querySelector('.hs-r .nm');
  return {css: parseFloat(g.style.getPropertyValue('--hk')), frisch: +hausLage(view).hk.toFixed(3),
          schrift: parseFloat(getComputedStyle(n).fontSize), sig: g._hsSig}; }"""


@pytest.mark.parametrize("von, nach", [((1460, 1120), (1500, 1150)), ((1500, 1150), (1460, 1120))],
                         ids=["groesser", "kleiner"])
def test_schrift_folgt_dem_fenster_ohne_neuaufbau(von, nach):
    """Groessenaenderung, bei der die Lage nicht kippt (gleiche Signatur): Die
    Schrift-Skalierung --hk zieht trotzdem nach, ohne die Seite neu aufzubauen."""
    async def lauf():
        app = _app()
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _seite(b, port, *von, fehler)
                vorher = await pg.evaluate(HK)
                await pg.evaluate("document.querySelector('#grid .hs').__alt = true")
                await pg.set_viewport_size({"width": nach[0], "height": nach[1]})
                await pg.wait_for_timeout(300)
                nachher = await pg.evaluate(HK)
                gleich = await pg.evaluate("document.querySelector('#grid .hs').__alt === true")
                await pg.evaluate("renderHaus()")
                neu = await pg.evaluate(HK)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return vorher, nachher, gleich, neu
    vorher, nachher, gleich, neu = asyncio.run(lauf())
    assert vorher["sig"] == nachher["sig"] and gleich, "dieselbe Lage: kein Neuaufbau"
    assert vorher["frisch"] != nachher["frisch"], (vorher, nachher)
    assert nachher["css"] == nachher["frisch"], nachher
    assert nachher["schrift"] == neu["schrift"] != vorher["schrift"], (vorher, nachher, neu)


def test_niedriges_fenster(tmp_path):
    """Breites, niedriges Fenster (Mac, flaches Display) im Set loxone: die
    Leiste nimmt ihre kleinen Masse (raster.js leisteSchmal), keine Raumkarte
    laesst etwas herausragen - auch nicht den Pfeil bei kleinem --hk. Die
    Zonenliste im Spieler scrollt dort selbst und zaehlt nicht."""
    m = TC.KACHEL_SETS["loxone"]["masse"]

    async def lauf():
        app = _app(ui={"tileSet": "loxone"})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _seite(b, port, 920, 460, fehler)
                lage = await pg.evaluate(LAGE)
                lage["leiste"] = await pg.evaluate("document.getElementById('tabs').offsetHeight")
                lage["zonen"] = await pg.evaluate("(z => z && z.scrollHeight > z.clientHeight"
                                                  " && getComputedStyle(z).overflowY)(document.querySelector('.hs-zonen'))")
                await pg.screenshot(path=str(tmp_path / "haus_niedrig_loxone.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return lage
    lage = asyncio.run(lauf())
    assert lage["leiste"] == float(m["--tabs-hoehe-schmal"].rstrip("px")), lage["leiste"]
    assert not lage["quer"] and not lage["klein"], lage
    assert [a for a in lage["ab"] if a != "sp"] == [], lage["ab"]
    assert "sp" not in lage["ab"] or lage["zonen"] == "auto", lage


# Aufbau, den die Visu wirklich zeigt ("spalte" faellt dort, wo sie nicht passt, auf "status")
AUFBAU = """() => { const L = hausLage(view), g = document.getElementById('grid');
  return {aufbau: L.aufbau, links: !!g.querySelector('.hs.links'), tasten: g.querySelectorAll('.hs-r.direkt .hs-t').length,
          blick: g.querySelectorAll('.hs-links .hs-bz').length, schnellLinks: g.querySelectorAll('.hs-links [data-hs=schnell]').length,
          aktiv: !!g.querySelector('.hs-aktiv'), titel: (g.querySelector('[data-hb=rkopf]') || {}).innerText || ''}; }"""


@pytest.mark.parametrize("aufbau", ["raeume", "spalte"])
@pytest.mark.parametrize("kset", SETS)
def test_aufbauten_auf_tablet_und_display(aufbau, kset, tmp_path):
    """Die beiden weiteren Aufbauten in jedem Set auf iPad quer und hochkant
    und dem grossen Display: nichts scrollt waagerecht, keine Taste unter
    44 px, keine Karte schneidet ab. "raeume" hat statt "Gerade aktiv" die
    Titelzeile und die Tasten in den Raumkarten; "spalte" steht quer links
    mit "Auf einen Blick" und den Schnellaktionen. Wo sie nicht passt
    (hochkant, iPad quer neben der Leiste links), zeigt die Seite "Status
    zuerst"."""
    async def lauf():
        app = _app(ui={"hausAufbau": aufbau, **({"tileSet": kset} if kset else {})})
        runner, port, bc = await visu_starten(app)
        erg, fehler = {}, []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                for name, (w, h) in GERAETE.items():
                    pg = await _seite(b, port, w, h, fehler)
                    erg[name] = {**await pg.evaluate(LAGE), **await pg.evaluate(AUFBAU)}
                    await pg.screenshot(path=str(tmp_path / f"haus_{aufbau}_{kset or 'ohne'}_{name}.png"))
                    await pg.close()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return erg
    erg = asyncio.run(lauf())
    for name, m in erg.items():
        wo = (aufbau, kset, name)
        assert not m["quer"], (wo, "scrollt waagerecht", m["quer"])
        assert not m["klein"], (wo, "Taste unter 44 px", m["klein"])
        assert not m["ab"], (wo, "Karte schneidet ab", m["ab"])
        assert m["raeume"] == 7, (wo, m)
        # "spalte" braucht quer Platz fuer sich, zwei Raumspalten und den Spieler:
        # hochkant nie, auf dem iPad quer nicht neben der Leiste links (Kreide)
        erwartet = aufbau
        if aufbau == "spalte" and (name == "ipad_hoch" or (name == "ipad_quer" and kset == "kreide")):
            erwartet = "status"
        assert m["aufbau"] == erwartet, (wo, m)
        if erwartet == "raeume":
            assert m["tasten"] == 8 and not m["aktiv"] and m["titel"].startswith("Räume"), (wo, m)
        if erwartet == "spalte":
            assert m["links"] and m["blick"] == 4 and m["schnellLinks"] == 2 and not m["aktiv"], (wo, m)
        if erwartet == "status":
            assert m["aktiv"] and not m["links"] and m["schnell"] == 2, (wo, m)


def test_raeume_direkt_bedienen(tmp_path, miniserver_http):
    """Aufbau "raeume" am Miniserver-Nachbau: eine Taste schaltet ab, was an
    ist, und ein, was aus ist; die Sauna fragt zuerst nach (erster Tipp ohne
    Befehl, die Frage steht an der Taste), erst der zweite schaltet. Der Pfeil
    oeffnet den Raum."""
    async def lauf():
        ms = await Miniserver().start()
        app = _app(neue_app(ms), ui={"hausAufbau": "raeume"})
        runner, port, bc = await visu_starten(app)
        fehler, erg = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _seite(b, port, 1180, 820, fehler)
                raum = lambda n: pg.locator(".hs-r.direkt", has_text=n)  # noqa: E731
                await raum("Abstellraum").locator(".hs-t").nth(0).click()
                erg["licht"] = await _befehle(ms, 1)
                await raum("Abstellraum").locator(".hs-t").nth(1).click()
                erg["zone"] = (await _befehle(ms, 2))[1:]
                sauna = raum("Sauna").locator(".hs-t").nth(0)
                await sauna.click()
                await pg.wait_for_timeout(300)
                erg["frage"] = [await sauna.locator(".l").inner_text(), await sauna.get_attribute("class"),
                                len(ms.io_roh)]
                await pg.screenshot(path=str(tmp_path / "haus_raeume_frage.png"))
                await raum("Sauna").locator(".hs-t").nth(0).click()
                erg["sauna"] = (await _befehle(ms, 3))[2:]
                erg["nach_frage"] = await raum("Sauna").locator(".hs-t").nth(0).locator(".l").inner_text()
                await raum("Küche").locator('[data-hs="raum"]').click()
                await pg.wait_for_selector("#grid .tile[data-id='IR']")
                erg["raum"] = await pg.evaluate("view.route")
                await b.close()
        finally:
            bc.cancel()
            await app.icon_session.close()
            await runner.cleanup()
            await ms.stop()
        assert not fehler, fehler
        return erg
    erg = asyncio.run(lauf())
    assert erg["licht"] == ["sps/io/LA/changeTo/778"], erg
    assert erg["zone"] == ["sps/io/AB/play"], erg
    assert erg["frage"][0] == "Einschalten?" and "arm" in erg["frage"][1] and erg["frage"][2] == 2, erg
    assert erg["sauna"] == ["sps/io/SA/on"] and erg["nach_frage"] == "Saunasteuerung", erg
    assert erg["raum"] == {"view": "group", "kind": "room", "id": "r6"}, erg


def test_spalte_bedienen(tmp_path, miniserver_http):
    """Aufbau "spalte" am grossen Display: ein Eintrag unter "Auf einen Blick"
    oeffnet seinen Baustein, die Schnellaktion links schickt ihren Befehl an
    den Zentral-Baustein, die Energie oeffnet den Energiefluss."""
    async def lauf():
        ms = await Miniserver().start()
        app = _app(neue_app(ms), ui={"hausAufbau": "spalte"})
        runner, port, bc = await visu_starten(app)
        fehler, erg = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _seite(b, port, 1920, 1080, fehler)
                await pg.screenshot(path=str(tmp_path / "haus_spalte.png"))
                await pg.locator(".hs-links .hs-bz", has_text="Postkasten").click()
                await pg.wait_for_function("view && view.route && view.route.view === 'control'")
                erg["blick"] = await pg.evaluate("view.route")
                await pg.locator("#tabback").click()
                await pg.wait_for_selector("#grid.haus .hs-links")
                await pg.locator('.hs-links [data-hs="schnell"][data-art="licht"]').click()
                erg["schnell"] = await _befehle(ms, 1)
                await pg.locator('.hs-links [data-hs="energie"]').click()
                await pg.wait_for_function("view && view.route && view.route.id === 'F'")
                erg["energie"] = await pg.evaluate("view.route")
                await b.close()
        finally:
            bc.cancel()
            await app.icon_session.close()
            await runner.cleanup()
            await ms.stop()
        assert not fehler, fehler
        return erg
    erg = asyncio.run(lauf())
    assert erg["blick"] == {"view": "control", "id": "MB"}, erg
    assert erg["schnell"] == ["sps/io/CL/reset"], erg
    assert erg["energie"] == {"view": "control", "id": "F"}, erg


def test_aufbau_im_konfigurator(cfg_ordner):
    """Aussehen der Ansicht: die Gruppe "Hausübersicht" waehlt den Aufbau aus
    /api/meta; gespeichert wird nur, was vom Standard abweicht, und die Visu
    zeigt danach den gewaehlten Aufbau."""
    from lox import KONFIGURATOR_GELADEN
    from test_auswahl_seiten_browser import ROUTEN
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"flur": {
        "title": "Flur", "tabs": ["haus"]}}}), encoding="utf-8")

    async def lauf():
        struktur, states = haus_anlage()
        app = W.App({"host": "", "port": 80})
        app._apply_structure(struktur)
        app.states = states
        app.panels = konfig.load_panels()
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
                await pg.locator(".stab[data-sub='aussehen']").click()
                feld = pg.locator("#fHausAufbau")
                erg["optionen"] = await feld.locator("option").evaluate_all("o => o.map(x => [x.value, x.textContent])")
                erg["vorher"] = await feld.input_value()
                for wert in ("raeume", "status"):
                    await feld.select_option(wert)
                    async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
                        await pg.locator("#saveBtn").click()
                    erg[wert] = [(await (await antwort.value).json())["ok"],
                                 json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]["flur"]]
                    if wert == "raeume":
                        app.panels = konfig.load_panels()
                        visu = await b.new_page(viewport={"width": 1180, "height": 820}, locale="de-DE")
                        visu.on("pageerror", lambda e: fehler.append(str(e)))
                        await visu.goto(f"http://127.0.0.1:{port}/?panel=flur")
                        await visu.wait_for_selector("#grid.haus .hs-r.direkt", state="attached")
                        erg["visu"] = await visu.evaluate("view.aufbau")
                        await visu.close()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return erg
    erg = asyncio.run(lauf())
    assert erg["optionen"] == [["status", "Status zuerst"], ["raeume", "Räume direkt"], ["spalte", "Spalte links"]], erg
    assert erg["vorher"] == "status", erg
    assert erg["raeume"][0] and erg["raeume"][1]["ui"]["hausAufbau"] == "raeume", erg["raeume"]
    assert erg["visu"] == "raeume", erg
    assert erg["status"][0] and "hausAufbau" not in (erg["status"][1].get("ui") or {}), erg["status"]


def test_gerade_aktiv_und_energie_im_konfigurator(cfg_ordner):
    """Aussehen der Ansicht, Gruppe "Hausübersicht": was unter "Gerade aktiv"
    zaehlt (Haken je Art aus /api/meta) und die Energie im Kopf (automatisch,
    keine, ein Baustein). Gespeichert wird, was nicht zaehlt, und nur eine
    gewaehlte Energie; die Visu zeigt danach ohne Musik die Zone nicht mehr
    unter "Gerade aktiv", ohne Haken keine Zeile (auch keine Zahl in "Räume
    direkt") und mit "Keine" keine Energie im Kopf."""
    from lox import KONFIGURATOR_GELADEN
    from test_auswahl_seiten_browser import ROUTEN
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"flur": {
        "title": "Flur", "tabs": ["haus"]}}}), encoding="utf-8")
    pfad = cfg_ordner / "panels.json"

    async def lauf():
        struktur, states = haus_anlage()
        app = W.App({"host": "", "port": 80})
        app._apply_structure(struktur)
        app.states = states
        app.panels = konfig.load_panels()
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler, erg = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))

                async def speichern():
                    async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
                        await pg.locator("#saveBtn").click()
                    ok = (await (await antwort.value).json())["ok"]
                    app.panels = konfig.load_panels()
                    return ok, json.loads(pfad.read_text(encoding="utf-8"))["panels"]["flur"].get("ui") or {}

                async def visu(warten):
                    s = await b.new_page(viewport={"width": 1180, "height": 820}, locale="de-DE")
                    s.on("pageerror", lambda e: fehler.append(str(e)))
                    await s.goto(f"http://127.0.0.1:{port}/?panel=flur")
                    await s.wait_for_selector(warten, state="attached")
                    w = await s.evaluate("""() => ({aktiv: view.aktiv.map(a => a.id), zeile: view.aktivZeile,
                        kopf: !!document.querySelector('[data-hb="akopf"]'),
                        karten: document.querySelectorAll('.hs-aktiv .hs-a').length,
                        titel: (document.querySelector('[data-hb="rkopf"] .n') || {}).textContent,
                        energie: !!document.querySelector('[data-hs="energie"]')})""")
                    await s.close()
                    return w

                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator("#plist .pitem", has_text="Flur").click()
                await pg.locator(".stab[data-sub='aussehen']").click()
                arten = pg.locator("[data-haus-art]")
                erg["arten"] = await arten.evaluate_all(
                    "l => l.map(x => [x.dataset.hausArt, x.checked, x.parentElement.textContent.trim()])")
                energie = pg.locator("#fHausEnergie")
                erg["energien"] = await energie.locator("option").evaluate_all("o => o.map(x => [x.value, x.textContent])")
                erg["energieVorher"] = await energie.input_value()
                # ohne Musik
                await pg.locator("[data-haus-art='audio']").uncheck()
                erg["ohneMusik"] = await speichern()
                erg["visuOhneMusik"] = await visu("#grid.haus .hs-aktiv .hs-a")
                # nichts zaehlt, Energie "Keine"
                for a in ("licht", "schalter", "sauna"):
                    await pg.locator(f"[data-haus-art='{a}']").uncheck()
                await energie.select_option(konfig.HAUS_ENERGIE_AUS)
                erg["nichts"] = await speichern()
                erg["visuNichts"] = await visu("#grid.haus .hs-r")
                app.panels["flur"]["ui"]["hausAufbau"] = "raeume"
                erg["visuRaeume"] = await visu("#grid.haus .hs-r.direkt")
                # wieder alles, Energie ein bestimmter Baustein, dann automatisch
                for a in konfig.HAUS_AKTIV_ARTEN:
                    await pg.locator(f"[data-haus-art='{a}']").check()
                await energie.select_option("F")
                erg["alles"] = await speichern()
                await energie.select_option("")
                erg["auto"] = await speichern()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return erg
    erg = asyncio.run(lauf())
    assert erg["arten"] == [["licht", True, "Licht"], ["audio", True, "Musik"],
                            ["schalter", True, "Schalter"], ["sauna", True, "Sauna"]], erg["arten"]
    assert erg["energien"] == [["", "Automatisch"], ["aus", "Keine"], ["F", "Zentral · Energieflussmonitor"]], erg
    assert erg["energieVorher"] == "", erg
    assert erg["ohneMusik"] == (True, {"hausAktivOhne": ["audio"]}), erg["ohneMusik"]
    v = erg["visuOhneMusik"]
    assert v["aktiv"] == ["LA", "AL", "FS"] and v["zeile"] and v["kopf"] and v["karten"] == 3 and v["energie"], v
    assert erg["nichts"] == (True, {"hausAktivOhne": list(konfig.HAUS_AKTIV_ARTEN), "hausEnergie": "aus"}), erg
    v = erg["visuNichts"]
    assert v["aktiv"] == [] and v["zeile"] is False and not v["kopf"] and not v["karten"] and not v["energie"], v
    assert erg["visuRaeume"]["titel"] == "" and not erg["visuRaeume"]["energie"], erg["visuRaeume"]
    assert erg["alles"] == (True, {"hausEnergie": "F"}), erg["alles"]
    assert erg["auto"] == (True, {}), erg["auto"]


# Vier Hinweise, je Stufe einer: Klingel und Fenster offen, waehrend die Kueche
# heizt (dringend), Wassermangel der Sauna (Warnung), Post (an)
HINWEIS_STATES = {"ic": 1, "ir4": 1, "sa3": 1, "mb1": 1}
HINWEIS_TITEL = ["Es klingelt", "Fenster offen", "Wasser nachfüllen", "Post da"]
HINWEIS_STUFEN = ["dringend", "dringend", "warnung", "an"]

# Hinweise der Seite: Karten der Leiste und in "Auf einen Blick" (Stufe, Text,
# Vorlesetext, Flaeche, Farbe von Schrift und Symbol), die Taste "+n", die
# Zahl, die Zeilen unter "Status", die Folge der Hauptspalte und die Tokens
HINWEISE = """() => {
  const g = document.getElementById('grid');
  const probe = st => { const p = document.createElement('span'); Object.assign(p.style, st); g.appendChild(p);
    const s = getComputedStyle(p), w = {farbe: s.color, grund: s.backgroundColor}; p.remove(); return w; };
  const karte = h => ({stufe: h.classList[1], titel: h.querySelector('.z').textContent,
    wo: (h.querySelector('.w') || {}).textContent || '', aria: h.getAttribute('aria-label'),
    grund: getComputedStyle(h).backgroundColor, schrift: getComputedStyle(h.querySelector('.z')).color,
    symbol: getComputedStyle(h.querySelector('.hs-i')).color});
  const text = q => { const e = g.querySelector(q); return e ? e.textContent : null; };
  return {links: !!g.querySelector('.hs.links'),
    leiste: [...g.querySelectorAll('.hs-hw [data-hs=hinweis]')].map(karte), plus: text('.hs-hplus'),
    blick: [...g.querySelectorAll('.hs-blick [data-hs=hinweis]')].map(karte), zahl: text('.hs-blick .kopf .n'),
    ok: text('.hs-blick .hs-h.ok .z'),
    termine: [...g.querySelectorAll('.hs-blick .hs-h.termin')].map(h => [h.querySelector('.z').textContent,
      h.querySelector('.w').textContent]),
    status: g.querySelectorAll('.hs-blick .hs-bz').length,
    folge: [...g.querySelector('.hs-main').children].map(e => e.classList[0]),
    warn: probe({color: 'var(--warn)'}).farbe, glow: probe({color: 'var(--glow)'}).farbe,
    critFill: probe({background: 'var(--crit-fill)'}).grund, critInk: probe({color: 'var(--crit-ink)'}).farbe};
}"""


@pytest.mark.parametrize("aufbau", ["status", "raeume", "spalte"])
@pytest.mark.parametrize("kset", SETS)
def test_hinweise_auf_tablet_und_display(kset, aufbau, tmp_path, monkeypatch):
    """Vier Hinweise in jedem Aufbau, Set und Geraet: Mit der Spalte links
    stehen alle oben in "Auf einen Blick" (mit Zahl; die Post nicht noch
    einmal unter "Status"), sonst als Leiste gleich unter dem Kopf - so viele,
    wie nebeneinander passen, der Rest hinter "+n". Folge nach Stufe;
    dringend ist die gefuellte Stoerungsflaeche des Sets, Warnung und "an"
    zeigen es am Symbol (--warn, --glow). Nichts scrollt waagerecht, keine
    Taste unter 44 px, keine Karte schneidet ab."""
    async def lauf():
        app = _app(ui={"hausAufbau": aufbau, **({"tileSet": kset} if kset else {})})
        app.states.update(HINWEIS_STATES)
        app._front = app._front_payload(await _front(monkeypatch))
        runner, port, bc = await visu_starten(app)
        erg, fehler = {}, []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                for name, (w, h) in GERAETE.items():
                    pg = await _seite(b, port, w, h, fehler)
                    erg[name] = (await pg.evaluate(LAGE), await pg.evaluate(HINWEISE))
                    await pg.screenshot(path=str(tmp_path / f"haus_hinweise_{aufbau}_{kset or 'ohne'}_{name}.png"))
                    await pg.close()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return erg
    erg = asyncio.run(lauf())
    for name, (m, h) in erg.items():
        wo = (kset, aufbau, name)
        assert not m["quer"], (wo, "scrollt waagerecht", m["quer"])
        assert not m["klein"], (wo, "Taste unter 44 px", m["klein"])
        assert not m["ab"], (wo, "Karte schneidet ab", m["ab"])
        if h["links"]:
            karten = h["blick"]
            assert [k["titel"] for k in karten] == HINWEIS_TITEL and h["zahl"] == "4 Hinweise", (wo, h)
            assert h["leiste"] == [] and h["plus"] is None and h["ok"] is None, (wo, h)
            assert h["status"] == 3, (wo, "Lueftung und die Zentralen, die Post steht oben", h)
        else:
            karten = h["leiste"]
            n = len(karten)
            assert 2 <= n <= 4 and [k["titel"] for k in karten] == HINWEIS_TITEL[:n], (wo, h)
            assert h["plus"] == (f"+{4 - n}" if n < 4 else None), (wo, h)
            assert h["folge"][:2] == ["hs-kopf", "hs-hw"], (wo, h["folge"])
        assert [k["stufe"] for k in karten] == HINWEIS_STUFEN[:len(karten)], (wo, karten)
        assert karten[0]["aria"] == "Es klingelt, Intercom · Eingang", (wo, karten[0])
        assert karten[1]["wo"] == "Raumregelung · Küche · heizt", (wo, karten[1])
        if kset:
            for k in karten:
                if k["stufe"] == "dringend":
                    assert k["grund"] == h["critFill"] and k["schrift"] == k["symbol"] == h["critInk"], (wo, k, h)
                else:
                    assert k["symbol"] == h["warn" if k["stufe"] == "warnung" else "glow"], (wo, k, h)
    if aufbau == "spalte":
        assert erg["display"][1]["links"], "am grossen Display steht die Spalte"


def test_hinweise_bedienen(tmp_path):
    """Hochkant: ein Tipp auf einen Hinweis oeffnet seinen Baustein, "+n"
    die Unterseite mit allen. Die Zustaende kommen live: ist ein Hinweis
    erledigt, faellt er weg und die Unterseite zaehlt mit; ist keiner mehr
    da, geht es zurueck zur Uebersicht und die Leiste ist weg - kommt Post,
    ist sie wieder da."""
    async def lauf():
        app = _app()
        app.states.update(HINWEIS_STATES)
        runner, port, bc = await visu_starten(app)
        fehler, erg = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _seite(b, port, 820, 1180, fehler)
                erg["vorher"] = await pg.evaluate(HINWEISE)
                await pg.locator(".hs-hw [data-hs=hinweis]", has_text="Fenster offen").click()
                await pg.wait_for_function("view && view.route && view.route.view === 'control'")
                erg["detail"] = await pg.evaluate("view.route")
                await pg.locator("#tabback").click()
                await pg.wait_for_selector("#grid.haus .hs-hw")
                await pg.locator(".hs-hplus").click()
                await pg.wait_for_selector("#grid .hs-liste [data-hs=hinweis]")
                erg["route"] = await pg.evaluate("view.route")
                erg["liste"] = await pg.locator(".hs-liste [data-hs=hinweis] .z").all_text_contents()
                erg["kopf"] = await pg.locator(".hs-zeile h2, .hs-zeile .n").all_text_contents()
                erg["lage"] = await pg.evaluate(LAGE)
                await pg.screenshot(path=str(tmp_path / "haus_hinweise_liste.png"))
                # die Tuer hat ausgeklingelt, das Fenster ist zu
                app._on_value("ic", 0)
                app._on_value("ir4", 0)
                await pg.wait_for_function("document.querySelectorAll('.hs-liste [data-hs=hinweis]').length === 2")
                erg["liste2"] = await pg.locator(".hs-liste [data-hs=hinweis] .z").all_text_contents()
                erg["kopf2"] = await pg.locator(".hs-zeile .n").text_content()
                # alles erledigt: zurueck, ohne Leiste
                app._on_value("sa3", 0)
                app._on_value("mb1", 0)
                await pg.wait_for_function("view && !view.liste && !!document.querySelector('#grid.haus .hs-raeume')")
                erg["ohne"] = await pg.evaluate("[document.querySelectorAll('.hs-hw').length, stack.length]")
                app._on_value("mb1", 1)
                await pg.wait_for_selector(".hs-hw [data-hs=hinweis]")
                erg["post"] = await pg.locator(".hs-hw [data-hs=hinweis] .z").all_text_contents()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return erg
    erg = asyncio.run(lauf())
    assert [k["titel"] for k in erg["vorher"]["leiste"]] == HINWEIS_TITEL[:2] and erg["vorher"]["plus"] == "+2", erg
    assert erg["detail"] == {"view": "control", "id": "IR"}, erg
    assert erg["route"] == {"view": "tab", "tab": "haus", "liste": "hinweise"}, erg
    assert erg["liste"] == HINWEIS_TITEL and erg["kopf"] == ["Hinweise", "4 Hinweise"], erg
    assert not erg["lage"]["quer"] and not erg["lage"]["klein"], erg["lage"]
    assert erg["liste2"] == ["Wasser nachfüllen", "Post da"] and erg["kopf2"] == "2 Hinweise", erg
    assert erg["ohne"] == [0, 1], erg
    assert erg["post"] == ["Post da"], erg


def test_termine_in_auf_einen_blick(tmp_path):
    """Spalte links ohne Hinweis: "Alles in Ordnung" (ohne Zahl), darunter die
    Termine von heute und morgen, die noch kommen - der von heute frueh
    nicht, der von uebermorgen nicht -, hoechstens so viele, wie die
    Uhr-Seite zeigt (svEvents). Laeuft die Uhr ueber einen Termin, faellt er
    von selbst weg und der naechste rueckt nach. Die Uhr des Browsers steht
    fest, damit es nicht von der Tageszeit abhaengt."""
    jetzt = datetime(2026, 3, 10, 17, 58, tzinfo=ZoneInfo("Europe/Vienna"))
    heute = jetzt.date()

    def termin(tage, titel, zeit=None):
        d = heute + timedelta(days=tage)
        return {"day": W.front_info.day_label(d, heute), "date": d.isoformat(), "time": zeit or "ganztägig",
                "title": titel, "note": "", "allday": zeit is None, "cal": "Familie", "color": "#52b881", "ck": "f"}
    events = [termin(0, "Schulfrei"), termin(0, "Frühstück", "7:00"), termin(0, "Elternabend", "18:00"),
              termin(1, "Müllabfuhr"), termin(1, "Training", "19:00"), termin(2, "Arzt", "9:00")]

    async def lauf():
        app = _app(ui={"hausAufbau": "spalte", "tileSet": "kreide"})
        app._front = app._front_payload({"events": events, "sv_events": 3})
        runner, port, bc = await visu_starten(app)
        fehler, erg = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1920, "height": 1080}, locale="de-DE",
                                      timezone_id="Europe/Vienna")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.clock.install(time=jetzt)
                await pg.goto(f"http://127.0.0.1:{port}/?panel=haus")
                await pg.wait_for_selector("#grid.haus .hs-blick .hs-h.termin", state="attached")
                await pg.evaluate("wake()")
                erg["vorher"] = await pg.evaluate(HINWEISE)
                await pg.screenshot(path=str(tmp_path / "haus_termine.png"))
                await pg.clock.run_for(3 * 60 * 1000)
                await pg.wait_for_function("![...document.querySelectorAll('.hs-blick .hs-h.termin .z')]"
                                           ".some(z => z.textContent === 'Elternabend')")
                erg["nachher"] = await pg.evaluate(HINWEISE)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return erg
    erg = asyncio.run(lauf())
    v = erg["vorher"]
    assert v["links"] and v["ok"] == "Alles in Ordnung" and v["zahl"] is None and v["blick"] == [], v
    assert v["termine"] == [["Schulfrei", "Heute, ganztägig"], ["Elternabend", "Heute, 18:00"],
                            ["Müllabfuhr", "Morgen, ganztägig"]], v["termine"]
    assert erg["nachher"]["termine"] == [["Schulfrei", "Heute, ganztägig"], ["Müllabfuhr", "Morgen, ganztägig"],
                                         ["Training", "Morgen, 19:00"]], erg["nachher"]["termine"]


# Sender im Spieler: je Kachel Name, ob gedrueckt und mit Ring, ob das Bild
# geladen ist oder das Musik-Symbol steht, die Kantenlaenge des Covers; dazu
# "Alle"/"Mehr" und ob der Spieler als Leiste steht
SENDER = """() => { const g = document.getElementById('grid');
  return {kacheln: [...g.querySelectorAll('.hs-f')].map(k => { const img = k.querySelector('.fc img');
      return {name: k.querySelector('.n').textContent, gedrueckt: k.getAttribute('aria-pressed') === 'true',
              ring: getComputedStyle(k).boxShadow !== 'none', bild: img ? img.naturalWidth > 0 : false,
              cover: Math.round(k.querySelector('.fc').getBoundingClientRect().width)}; }),
    alle: !!g.querySelector('.hs-alle'), mehr: !!g.querySelector('.hs-fmehr'), leiste: !!g.querySelector('.hs-sp.leiste')};
}"""
# ... bis jedes Bild geladen oder (laedt nicht) entfernt ist
BILDER_DA = "[...document.querySelectorAll('.hs-f .fc img')].every(i => i.complete && i.naturalWidth > 0)"


def test_sender_im_spieler(tmp_path, miniserver_http):
    """Die Favoriten der Zone als grosse Cover im Spieler (Entwurf "Variante
    grosse Cover"): quer in der Spalte unter "Favoriten · Alle" drei
    Kacheln, hochkant in der Leiste so viele, wie passen, dahinter "Mehr".
    Die Cover sind mindestens 60 px gross. Der laufende Sender ist markiert
    (Ring, aria-pressed). Ein Tipp spielt den Favoriten (roomfav/play am
    Miniserver-Nachbau); meldet die Zone den neuen Sender, wandert die
    Markierung. Ohne Cover oder wenn es nicht laedt, steht das Musik-Symbol
    statt eines kaputten Bildes; "Alle" und "Mehr" oeffnen die Musikauswahl."""
    async def bild(r):
        return web.Response(text='<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120">'
                                 '<rect width="120" height="120" fill="#0060a8"/></svg>', content_type="image/svg+xml")

    async def lauf():
        netz = web.Application()
        netz.router.add_get("/bild.svg", bild)
        nr, nport = await serve(netz)
        ms = await Miniserver().start()
        app = _app(neue_app(ms))
        # FM4 ohne Cover, Bayern 3 mit einem, das es nicht gibt
        covers = {"FM4": "", "Bayern 3": f"http://127.0.0.1:{nport}/fehlt.svg"}
        app.states["az4"] = json.dumps({"getroomfavs_result": [{"items": [
            {"slot": i, "name": n, "coverurl": covers.get(n, f"http://127.0.0.1:{nport}/bild.svg")}
            for i, n in enumerate(HAUS_FAVORITEN, 1)]}]})
        runner, port, bc = await visu_starten(app, [("GET", "/cover", W.cover_handler)])
        fehler, erg = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _seite(b, port, 1180, 820, fehler)
                await pg.wait_for_function(BILDER_DA)
                erg["quer"] = await pg.evaluate(SENDER)
                erg["quer_lage"] = await pg.evaluate(LAGE)
                await pg.screenshot(path=str(tmp_path / "haus_sender_quer.png"))
                await pg.locator(".hs-alle").click()
                await pg.wait_for_function("view && view.route && view.route.view === 'sources'")
                erg["alle"] = await pg.evaluate("view.route")
                await pg.close()
                pg = await _seite(b, port, 820, 1180, fehler)
                await pg.wait_for_function(BILDER_DA)
                erg["hoch"] = await pg.evaluate(SENDER)
                erg["hoch_lage"] = await pg.evaluate(LAGE)
                await pg.screenshot(path=str(tmp_path / "haus_sender_hoch.png"))
                await pg.locator(".hs-f", has_text="FM4").click()
                # davor: "Alle" oeffnete die Musikauswahl, die die Favoriten frisch anfordert
                erg["befehle"] = await _befehle(ms, 2)
                app._on_value("az2", "FM4")
                await pg.wait_for_function("document.querySelector('.hs-f[aria-pressed=true] .n').textContent === 'FM4'")
                erg["danach"] = await pg.evaluate(SENDER)
                await pg.locator(".hs-fmehr").click()
                await pg.wait_for_function("view && view.route && view.route.view === 'sources'")
                erg["mehr"] = await pg.evaluate("view.route")
                await b.close()
        finally:
            bc.cancel()
            await app.icon_session.close()
            await runner.cleanup()
            await ms.stop()
            await nr.cleanup()
        assert not fehler, fehler
        return erg
    erg = asyncio.run(lauf())
    for name in ("quer", "hoch"):
        lage = erg[name + "_lage"]
        assert not lage["quer"] and not lage["klein"] and not lage["ab"], (name, lage)
    q, h = erg["quer"], erg["hoch"]
    assert not q["leiste"] and q["alle"] and not q["mehr"], q
    assert [k["name"] for k in q["kacheln"]] == HAUS_FAVORITEN[:3], q
    assert h["leiste"] and h["mehr"] and len(h["kacheln"]) >= 4, h
    assert [k["name"] for k in h["kacheln"]] == HAUS_FAVORITEN[:len(h["kacheln"])], h
    for k in q["kacheln"] + h["kacheln"]:
        assert k["cover"] >= 60, ("Cover zu klein", k)
        # nur der laufende markiert; Bild nur, wo es eines gibt und es laedt
        assert k["gedrueckt"] == k["ring"] == (k["name"] == "Hitradio Ö3"), k
        assert k["bild"] == (k["name"] not in ("FM4", "Bayern 3")), k
    assert erg["befehle"] == ["sps/io/AZ/roomfav/get/0/20", "sps/io/AZ/roomfav/play/2"], erg
    assert [k["name"] for k in erg["danach"]["kacheln"] if k["gedrueckt"]] == ["FM4"], erg["danach"]
    assert erg["alle"] == erg["mehr"] == {"view": "sources", "id": "AZ"}, erg
