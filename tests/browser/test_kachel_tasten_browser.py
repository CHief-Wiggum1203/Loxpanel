"""Tasten auf der Kachel (Mini-Player ◀ ⏯ ▶ der AudioZone, Auf/Ab der
Beschattung) und Favoriten der Musikauswahl in Chromium mit Touch-Display:
Tippen sendet den Befehl genau einmal; ein Wischer, der auf einer Taste
beginnt, scrollt das Raster und sendet nichts. Mit der Maus wie bisher.
Befehle schreibt ein Stellvertreter fuer app.command mit."""
import asyncio
import json
from urllib.parse import quote

import pytest

from lox import W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

# Genug Zonen, dass das Raster bei 480x480 scrollt
ZONEN = {f"Z{i}": {"name": f"Zone {i}", "type": "AudioZone", "uuidAction": f"Z{i}", "room": "r1",
                   "cat": "c1", "isFavorite": True, "states": {"playState": f"ps{i}"}}
         for i in range(12)}
ZONEN["Z0"]["states"]["sourceList"] = "sl0"
# Favoriten der Zone 0, wie sie der Miniserver in sourceList legt: genug fuer
# mehrere Reihen, damit die Musikauswahl scrollt
SENDER = json.dumps({"items": [{"slot": i, "name": f"Sender {i}"} for i in range(1, 31)]})


ROLLOS = {f"J{i}": {"name": f"Rollo {i}", "type": "Jalousie", "uuidAction": f"J{i}", "room": "r1",
                    "cat": "c1", "isFavorite": True,
                    "states": {"position": f"jp{i}", "up": f"ju{i}", "down": f"jd{i}"}}
          for i in range(12)}


def _app(befehle: list, bausteine=ZONEN, ui=None):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(bausteine))
    app.states = {**{f"ps{i}": 0 for i in range(12)}, "sl0": SENDER,
                  **{f"{s}{i}": 0 for i in range(12) for s in ("jp", "ju", "jd")}}
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"], "ui": ui or {}}})

    async def command(uuid, cmd, pin=None):
        befehle.append((uuid, cmd))
        return "200"
    app.command = command
    return app


async def _taste(pg):
    """Mitte der Zurueck-Taste (◀) auf der ersten Kachel."""
    box = await pg.locator(".tile[data-id] .tctrls .tb").first.bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


async def _wischen(cdp, x, y, dy, schritte=20):
    """Finger bei (x, y) aufsetzen, in Schritten um dy verschieben, loslassen -
    so, wie ein Touchscreen meldet (synthetische Scroll-Gesten greifen in
    einem verschachtelten Scroller mit Rastpunkten nicht)."""
    await cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
    for i in range(1, schritte + 1):
        await cdp.send("Input.dispatchTouchEvent",
                       {"type": "touchMove", "touchPoints": [{"x": x, "y": y + dy * i / schritte}]})
        await asyncio.sleep(0.016)
    await cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})


# Hoechste Scroll-Position des Rasters waehrend eines Wischers. Danach rastet es
# seitenweise ein (scroll-snap) und kann ohne Schwung - auf einem ausgelasteten
# Rechner kommen die Touch-Ereignisse langsamer - auf die erste Seite
# zurueckspringen; ob der Wischer gescrollt hat, zeigt nur der Verlauf.
SCROLL_BEOBACHTEN = """window.__scrollMax = 0;
  el('grid').addEventListener('scroll', () => {
    window.__scrollMax = Math.max(window.__scrollMax, el('grid').scrollTop); });"""


async def _warten(befehle, n, pg):
    """Bis n Befehle da sind (hoechstens 3 s), dann noch kurz, ob mehr kommen."""
    for _ in range(60):
        if len(befehle) >= n:
            break
        await asyncio.sleep(0.05)
    await pg.wait_for_timeout(400)


def test_tippen_sendet_wischen_scrollt(tmp_path):
    async def lauf():
        befehle = []
        app = _app(befehle)
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": 480, "height": 480}, has_touch=True)
                pg = await ctx.new_page()
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector(".tile[data-id] .tctrls .tb")
                await pg.evaluate("hideSaver()")              # Uhr-Startseite weg, das Raster liegt frei
                hoehe = await pg.evaluate("[el('grid').scrollHeight, el('grid').clientHeight]")
                x, y = await _taste(pg)

                # Wischer nach oben, Beginn auf der Taste: das Raster scrollt, kein Befehl
                await pg.evaluate(SCROLL_BEOBACHTEN)
                cdp = await ctx.new_cdp_session(pg)
                await _wischen(cdp, x, y, -150)
                await _warten(befehle, 1, pg)
                gewischt = list(befehle), await pg.evaluate("__scrollMax")

                # Tippen auf die Taste: genau ein Befehl, die Kachel oeffnet nichts
                await pg.evaluate("el('grid').scrollTop = 0")
                await pg.wait_for_timeout(300)
                x, y = await _taste(pg)
                await pg.touchscreen.tap(x, y)
                await _warten(befehle, 1, pg)
                getippt = list(befehle), await pg.evaluate("stack.length")
                await pg.screenshot(path=str(tmp_path / "kachel_tasten.png"))

                # Maus (Browser am PC): Klick wie bisher
                befehle.clear()
                maus = await (await b.new_context(viewport={"width": 480, "height": 480})).new_page()
                maus.on("pageerror", lambda e: fehler.append(str(e)))
                await maus.goto(f"http://127.0.0.1:{port}/?panel=test")
                await maus.wait_for_selector(".tile[data-id] .tctrls .tb")
                await maus.evaluate("hideSaver()")
                x, y = await _taste(maus)
                await maus.mouse.click(x, y)
                await _warten(befehle, 1, maus)
                geklickt = list(befehle), await maus.evaluate("stack.length")
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return hoehe, gewischt, getippt, geklickt
    hoehe, gewischt, getippt, geklickt = asyncio.run(lauf())

    assert hoehe[0] > hoehe[1], f"das Raster muss scrollen koennen: {hoehe}"
    befehle, scroll = gewischt
    assert befehle == [], f"ein Wischer auf der Taste darf nichts senden: {befehle}"
    assert scroll > 0, "der Wischer scrollt das Raster"
    assert getippt == ([("Z0", "queueminus")], 1), "Tippen: ein Befehl, keine Detailseite"
    assert geklickt == ([("Z0", "queueminus")], 1), "Mausklick wie bisher"


def test_favoriten_tippen_und_wischen(tmp_path):
    """Musikauswahl: Ein Favorit startet erst beim Tippen (und die Seite geht
    zurueck); ein Wischer durch die Favoriten scrollt und laesst die Seite stehen."""
    async def lauf():
        befehle = []
        app = _app(befehle)
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": 480, "height": 480}, has_touch=True)
                pg = await ctx.new_page()
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector(".tile[data-id] .tctrls .tb")
                await pg.evaluate("hideSaver(); nav({view: 'sources', id: 'Z0'})")
                await pg.wait_for_selector(".favs .fav")
                await pg.screenshot(path=str(tmp_path / "musikauswahl.png"))
                hoehe = await pg.evaluate("[el('grid').scrollHeight, el('grid').clientHeight]")

                def abspielen():
                    return [b for b in befehle if b[1].startswith("roomfav/play/")]

                box = await pg.locator(".favs .fav").first.bounding_box()
                x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                await pg.evaluate(SCROLL_BEOBACHTEN)
                cdp = await ctx.new_cdp_session(pg)
                await _wischen(cdp, x, y, -150)
                await pg.wait_for_timeout(600)
                gewischt = abspielen(), await pg.evaluate("__scrollMax"), \
                    await pg.evaluate("stack.length")

                getippt = None
                if gewischt[2] == 2:      # Musikauswahl noch offen: jetzt Tippen pruefen
                    await pg.evaluate("el('grid').scrollTop = 0")
                    await pg.wait_for_timeout(300)
                    box = await pg.locator(".favs .fav").first.bounding_box()
                    await pg.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    for _ in range(60):
                        if abspielen():
                            break
                        await asyncio.sleep(0.05)
                    await pg.wait_for_timeout(400)
                    getippt = abspielen(), await pg.evaluate("stack.length")
                await pg.screenshot(path=str(tmp_path / "favoriten.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return hoehe, gewischt, getippt
    hoehe, gewischt, getippt = asyncio.run(lauf())

    assert hoehe[0] > hoehe[1], f"die Musikauswahl muss scrollen koennen: {hoehe}"
    gespielt, scroll, tiefe = gewischt
    assert gespielt == [], f"ein Wischer durch die Favoriten darf nichts starten: {gespielt}"
    assert scroll > 0 and tiefe == 2, "der Wischer scrollt, die Musikauswahl bleibt offen"
    assert getippt == ([("Z0", "roomfav/play/1")], 1), "Tippen startet den Sender und geht zurueck"


# Favoriten als (Abspiel-Index, Name, Cover-Adresse). Der Index ist im
# Miniserver-Weg der slot, im Audioserver-Weg (Port 7091) die Item-id.
GRUND = [(i, f"Sender {i}", "") for i in range(1, 31)]
# Aenderungen, bei denen die Anzahl gleich bleibt
GLEICH_LANG = {
    "ersetzt": GRUND[1:] + [(31, "Neu", "")],                 # Favorit 1 weg, ein neuer dazu
    "umbenannt": [(1, "Neu 1", "")] + GRUND[1:],              # derselbe Platz heisst anders
    "neues_cover": [(1, "Sender 1", "http://audioserver/cover/1.jpg")] + GRUND[1:],
    "nur_befehl": [(n + 30, name, c) for n, name, c in GRUND],  # gleiche Namen, neuer Index
}

# Favoriten der offenen Musikauswahl, wie sie zuletzt vom Server kamen (view)
# bzw. wie die Seite sie zeigt (Name, Cover)
FAVS_ZUGESTELLT = """() => view && view.route && view.route.view === 'sources'
  ? ((view.blocks || []).find(b => b.k === 'favs') || {items: []}).items.map(f => [f.label, f.cover, f.cmd.cmd])
  : null"""
FAVS_GEZEIGT = """() => [...document.querySelectorAll('.favs .fav')].map(n => {
  const i = n.querySelector('.favc img');
  return [n.querySelector('.favn').textContent, i ? i.getAttribute('src') : '']; })"""
# Zaehlt, wie oft eine Ansicht derselben Seite ankommt (updatePanel) und wie
# oft das Raster dabei neu aufgebaut wird; markiert den ersten Favoriten
ZUSTELLUNG_BEOBACHTEN = """() => {
  window.__zustellungen = 0; window.__umbauten = 0;
  const patchen = updatePanel;
  updatePanel = blocks => { window.__zustellungen++; return patchen(blocks); };
  new MutationObserver(l => { window.__umbauten += l.length; }).observe(el('grid'), {childList: true});
  document.querySelector('.favs .fav').__markiert = true; }"""


def _favoriten_setzen(app, weg, liste):
    """Neue Favoriten so einspielen, wie sie im Betrieb ankommen."""
    if weg == "miniserver":      # Ergebnis von roomfav/get im sourceList-State
        app._on_value("sl0", json.dumps({"items": [{"slot": n, "name": name, "coverurl": c}
                                                   for n, name, c in liste]}))
    else:                        # Antwort auf getroomfavs im Ereigniskanal (wie dessen Leser)
        if app.audio_clients["audioserver"]._handle(json.dumps({"getroomfavs_result": [
                {"id": 1, "items": [{"slot": s, "id": n, "name": name, "coverurl": c}
                                    for s, (n, name, c) in enumerate(liste, 1)]}]})):
            app._mark_dirty()


def _so_vom_server(liste):
    """Favoriten-Eintraege, wie _view_sources sie fuer `liste` rendert."""
    return [[name, ("/cover?u=" + quote(c, safe="")) if c else "", f"roomfav/play/{n}"]
            for n, name, c in liste]


@pytest.mark.parametrize("weg", ["miniserver", "audioserver"])
def test_favoriten_folgen_dem_server(tmp_path, weg):
    """Die Musikauswahl ist offen, die Favoriten aendern sich bei gleicher
    Anzahl: ersetzt, umbenannt, neues Cover oder nur der Abspiel-Index. Die
    Seite zeigt danach, was der Server schickt, und ein Tippen spielt den
    Favoriten, der dort steht. Gegenprobe: dieselbe Ansicht noch einmal
    zugestellt baut die Seite nicht neu auf (kein Flackern)."""
    async def lauf():
        befehle = []
        if weg == "miniserver":
            app = _app(befehle)
        else:
            # Zone am Audioserver; der Ereigniskanal ist da, aber ohne Verbindung
            zonen = {**ZONEN, "Z0": {**ZONEN["Z0"], "details": {"server": "as1", "playerid": 1}}}
            app = _app(befehle, zonen)
            app._apply_structure({**anlage(zonen), "mediaServer": {"as1": {"host": "audioserver:7091"}}})
            app.audio_clients["audioserver"] = W.AudioEventClient("audioserver")
            _favoriten_setzen(app, weg, GRUND)
        runner, port, bc = await visu_starten(app)
        fehler, ergebnis = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": 480, "height": 480}, has_touch=True)
                pg = await ctx.new_page()
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector(".tile[data-id] .tctrls .tb")
                await pg.evaluate("hideSaver()")

                async def zugestellt(liste):
                    """Bis die Seite die Favoriten `liste` vom Server hat (hoechstens 3 s)."""
                    for _ in range(60):
                        if await pg.evaluate(FAVS_ZUGESTELLT) == _so_vom_server(liste):
                            return True
                        await asyncio.sleep(0.05)
                    return False

                async def oeffnen():
                    _favoriten_setzen(app, weg, GRUND)
                    await pg.evaluate("nav({view: 'sources', id: 'Z0'})")
                    return await zugestellt(GRUND)

                for fall, liste in GLEICH_LANG.items():
                    geoeffnet = await oeffnen()
                    befehle.clear()
                    _favoriten_setzen(app, weg, liste)      # Musikauswahl ist offen
                    angekommen = await zugestellt(liste)
                    gezeigt = await pg.evaluate(FAVS_GEZEIGT)
                    await pg.screenshot(path=str(tmp_path / f"favoriten_{weg}_{fall}.png"))
                    box = await pg.locator(".favs .fav").first.bounding_box()
                    await pg.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    for _ in range(60):
                        if any(c.startswith("roomfav/play/") for _, c in befehle):
                            break
                        await asyncio.sleep(0.05)
                    await pg.wait_for_timeout(400)
                    ergebnis[fall] = {
                        "zugestellt": geoeffnet and angekommen,
                        "wie vom Server": gezeigt == [e[:2] for e in _so_vom_server(liste)],
                        "erster": gezeigt[:1],
                        "getippt": [x for x in befehle if x[1].startswith("roomfav/play/")],
                        "tiefe": await pg.evaluate("stack.length")}

                # Gegenprobe: dieselbe Ansicht derselben Seite noch einmal zustellen
                geoeffnet = await oeffnen()
                await pg.evaluate(ZUSTELLUNG_BEOBACHTEN)
                await pg.evaluate("send({t: 'nav', route: stack[stack.length - 1]})")
                await pg.wait_for_function("window.__zustellungen > 0", timeout=3000)
                await pg.wait_for_timeout(300)
                ergebnis["gleiche Zustellung"] = {
                    "zugestellt": geoeffnet,
                    "umbauten": await pg.evaluate("window.__umbauten"),
                    "derselbe Favorit": await pg.evaluate("document.querySelector('.favs .fav').__markiert === true")}
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return ergebnis
    ergebnis = asyncio.run(lauf())

    erwartet = {fall: {"zugestellt": True, "wie vom Server": True, "erster": [_so_vom_server(liste)[0][:2]],
                       "getippt": [("Z0", f"roomfav/play/{liste[0][0]}")], "tiefe": 1}
                for fall, liste in GLEICH_LANG.items()}
    erwartet["gleiche Zustellung"] = {"zugestellt": True, "umbauten": 0, "derselbe Favorit": True}
    assert ergebnis == erwartet


async def _tasten_von(pg, kachel):
    """Mitten der Tasten auf der Kachel `kachel`."""
    boxen = [await t.bounding_box() for t in await pg.locator(f'.tile[data-id="{kachel}"] .tctrls .tb').all()]
    return [(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2) for b in boxen]


# Symbole der Tasten einer Kachel als Namen aus ICONS (so gezeichnet wie dort: svgF)
SYMBOLE = """id => {
  const ref = {};
  for (const k of Object.keys(ICONS)) { const d = document.createElement('div');
    d.innerHTML = svgF(ICONS[k]); ref[d.firstChild.innerHTML] = k; }
  return [...document.querySelectorAll('.tile[data-id="' + id + '"] .tctrls .tb svg')]
    .map(s => ref[s.innerHTML] || '?'); }"""


def test_beschattung_auf_ab(tmp_path):
    """Auf/Ab auf der Beschattungs-Kachel: Tippen faehrt los, ein Wischer von
    der Taste aus scrollt nur. Waehrend der Fahrt zeigt die fahrende Richtung
    Stop, und beide Tasten halten an, wie in der Detailansicht."""
    async def lauf():
        befehle = []
        app = _app(befehle, ROLLOS)
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": 480, "height": 480}, has_touch=True)
                pg = await ctx.new_page()
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector('.tile[data-id="J0"] .tctrls .tb')
                await pg.evaluate("hideSaver()")
                stand = await pg.evaluate(SYMBOLE, "J0")
                hoehe = await pg.evaluate("[el('grid').scrollHeight, el('grid').clientHeight]")

                # Wischer nach oben, Beginn auf ▲: das Raster scrollt, kein Befehl
                (ax, ay), _ = await _tasten_von(pg, "J0")
                await pg.evaluate(SCROLL_BEOBACHTEN)
                cdp = await ctx.new_cdp_session(pg)
                await _wischen(cdp, ax, ay, -150)
                await _warten(befehle, 1, pg)
                gewischt = list(befehle), await pg.evaluate("__scrollMax")

                # Tippen auf ▲: genau ein Befehl, keine Detailseite
                await pg.evaluate("el('grid').scrollTop = 0")
                await pg.wait_for_timeout(300)
                (ax, ay), (bx, by) = await _tasten_von(pg, "J0")
                await pg.touchscreen.tap(ax, ay)
                await _warten(befehle, 1, pg)
                getippt = list(befehle), await pg.evaluate("stack.length")

                # Der Miniserver meldet die Fahrt nach oben: ▲ wird zu ■, beide halten an
                befehle.clear()
                app._on_value("ju0", 1.0)
                await pg.wait_for_function(f"({SYMBOLE})('J0')[0] === 'stop'")
                faehrt = await pg.evaluate(SYMBOLE, "J0")
                await pg.screenshot(path=str(tmp_path / "beschattung_faehrt.png"))
                await pg.touchscreen.tap(bx, by)
                await _warten(befehle, 1, pg)
                angehalten = list(befehle)
                app._on_value("ju0", 0.0)
                await pg.wait_for_function(f"({SYMBOLE})('J0')[0] === 'triup'")
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return stand, hoehe, gewischt, getippt, faehrt, angehalten
    stand, hoehe, gewischt, getippt, faehrt, angehalten = asyncio.run(lauf())

    assert stand == ["triup", "tridown"]
    assert hoehe[0] > hoehe[1], f"das Raster muss scrollen koennen: {hoehe}"
    befehle, scroll = gewischt
    assert befehle == [] and scroll > 0, f"ein Wischer von der Taste aus scrollt nur: {befehle}"
    assert getippt == ([("J0", "Up")], 1), "Tippen auf ▲ faehrt los, keine Detailseite"
    assert faehrt == ["stop", "tridown"], "waehrend der Fahrt nach oben zeigt ▲ Stop"
    assert angehalten == [("J0", "Stop")], "auch ▼ haelt die Fahrt an"


@pytest.mark.parametrize("ui", [{}, {"cols": 3}, {"rows": 3}, {"cols": 3, "rows": 3}],
                         ids=["2x2", "3x2", "2x3", "3x3"])
@pytest.mark.parametrize("art", ["rollo", "player"])
def test_tasten_passen_in_die_kachel(tmp_path, ui, art):
    """Die Tasten liegen in jedem Raster ganz in der Kachel und verdecken Name
    und Zustand nicht; nichts wird abgeschnitten. Unter dem Text ist bei drei
    Zeilen kein Platz, dann stehen sie in der Kopfzeile (placeCtrls)."""
    kachel = {"rollo": "J0", "player": "Z0"}[art]

    async def lauf():
        app = _app([], ROLLOS if art == "rollo" else ZONEN, ui)
        app.states.update({"jp0": 0.62, "ps0": 2})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 480, "height": 480})
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector(f'.tile[data-id="{kachel}"] .tctrls .tb')
                await pg.evaluate("hideSaver()")
                raster = f"{ui.get('cols', 2)}x{ui.get('rows', 2)}"
                await pg.screenshot(path=str(tmp_path / f"tasten_{art}_{raster}.png"))
                lage = await pg.evaluate("""id => {
                  const k = document.querySelector('.tile[data-id="' + id + '"]'), r = e => e.getBoundingClientRect();
                  const t = r(k), text = r(k.querySelector('.body'));
                  return {abgeschnitten: k.scrollHeight > k.clientHeight + 1,
                          text: text.bottom <= t.bottom + 1,
                          tasten: [...k.querySelectorAll('.tctrls .tb')].map(e => { const b = r(e);
                            return b.left >= t.left - 1 && b.right <= t.right + 1 && b.top >= t.top - 1
                                && b.bottom <= t.bottom + 1 && b.width >= 30 && b.height >= 30
                                && (b.bottom <= text.top + 1 || b.top >= text.bottom - 1); })}; }""", kachel)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return lage
    lage = asyncio.run(lauf())
    assert lage == {"abgeschnitten": False, "text": True, "tasten": [True] * (2 if art == "rollo" else 3)}, lage
