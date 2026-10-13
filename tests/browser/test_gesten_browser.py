"""Gesten wie auf den Loxone-Tastern (docs/TODO.md §9) in Chromium: zwei
Finger auf der echten Visu, die Befehle am Miniserver-Nachbau.

Playwright selbst kennt nur einen Finger; die Beruehrungen kommen ueber das
DevTools-Protokoll (Input.dispatchTouchEvent), so wie ein Touchscreen sie
meldet. Geprueft: Mitte hoch/runter dimmt anteilig, Tipp Mitte schaltet die
Stimmung weiter, links hoch faehrt die Beschattung, Doppeltipp verlaesst den
Raum; ein Finger scrollt und tippt wie bisher, eine Zwei-Finger-Geste ueber
einer Kachel oeffnet sie nicht, und ausgeschaltete Gesten tun nichts.
Anlage: lox.gesten_anlage()."""
import asyncio
import json

import pytest

from lox import Miniserver, W, gesten_anlage, neue_app, visu_starten

import theme_colors as TC

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("miniserver_http")]

BREITE, HOEHE = 893, 533


async def _finger(cdp, art, punkte):
    await cdp.send("Input.dispatchTouchEvent", {
        "type": art, "touchPoints": [{"x": x, "y": y, "id": i} for i, (x, y) in enumerate(punkte)]})


async def zwei_finger(cdp, x, y0, y1, schritte=8, abstand=60, nacheinander=False):
    """Zwei Finger nebeneinander bei x, von y0 nach y1 (y0 == y1: Tipp)."""
    a, b = x - abstand / 2, x + abstand / 2
    if nacheinander:     # wie am Geraet: der zweite Finger kommt kurz nach dem ersten
        await _finger(cdp, "touchStart", [(a, y0)])
    await _finger(cdp, "touchStart", [(a, y0), (b, y0)])
    for i in range(1, schritte + 1):
        y = y0 + (y1 - y0) * i / schritte
        await _finger(cdp, "touchMove", [(a, y), (b, y)])
        await asyncio.sleep(0.03)
    await _finger(cdp, "touchEnd", [])


async def ein_finger(cdp, x, y0, y1, schritte=8):
    await _finger(cdp, "touchStart", [(x, y0)])
    for i in range(1, schritte + 1):
        await _finger(cdp, "touchMove", [(x, y0 + (y1 - y0) * i / schritte)])
        await asyncio.sleep(0.03)
    await _finger(cdp, "touchEnd", [])


async def _warten(ms, anzahl, sekunden=3.0):
    for _ in range(int(sekunden / 0.05)):
        if len(ms.io) >= anzahl:
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.3)        # was danach noch kaeme, soll auffallen
    return list(ms.io)


def _laufen(schritte, ui=None, uhr=False, nacht=False, init=None, front=None):
    """uhr: die Uhr-Seite (Bildschirmschoner) stehen lassen; nacht: Nacht ist
    schon beim Verbinden (theme); init: Skript vor der Seite (Kiosk-Bruecke);
    front: Wetter und Termine wie vom Server geladen (dann ist die Uhr-Seite
    quer in zwei Spalten geteilt)."""
    async def lauf():
        ms = Miniserver()
        await ms.start()
        app = neue_app(ms)
        struktur, states = gesten_anlage()
        app._apply_structure(struktur)
        app.states = states
        if front:
            app._front = app._front_payload(front)
        if nacht:
            app._night_now = lambda: True
            app._night_on = True
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["room:r1"],
                                                      "ui": {"grid": "auto", "gesten": True, **(ui or {})}}})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": BREITE, "height": HOEHE}, has_touch=True)
                if init:
                    await ctx.add_init_script(init)
                pg = await ctx.new_page()
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector("#grid .tile[data-id]", state="attached")
                if uhr:
                    await pg.evaluate("showSaver()")
                    await pg.wait_for_selector("#saver:not(.hidden)", state="attached")
                elif await pg.locator("#saver:not(.hidden)").count():
                    await pg.evaluate("hideSaver()")
                    await pg.wait_for_selector("#saver.hidden", state="attached")
                await pg.wait_for_timeout(500)
                cdp = await ctx.new_cdp_session(pg)
                ergebnis = await schritte(ms, pg, cdp)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
            await app.icon_session.close()
            await ms.stop()
        assert not fehler, fehler
        return ergebnis
    return asyncio.run(lauf())


def _einblendung(pg):
    return pg.evaluate("""() => { const n = document.getElementById('geste');
      return n && !n.classList.contains('hidden') ? [n.querySelector('.gs-titel').textContent,
        n.querySelector('.gs-wert').textContent] : null; }""")


@pytest.mark.parametrize("nacheinander", [False, True], ids=["zugleich", "nacheinander"])
def test_mitte_dimmt_anteilig(nacheinander):
    """Zwei Finger in der Mitte nach unten: die leuchtenden Kreise der
    Lichtsteuerung Kochen werden dunkler, im Verhaeltnis 4:3 wie vorher;
    die Einblendung nennt Licht, Raum und Prozent. Keine Seite wechselt."""
    async def schritte(ms, pg, cdp):
        stapel = await pg.evaluate("stack.length")
        await zwei_finger(cdp, BREITE / 2, HOEHE * 0.3, HOEHE * 0.6, nacheinander=nacheinander)
        io = await _warten(ms, 2)
        return io, await _einblendung(pg), await pg.evaluate("stack.length") - stapel
    io, einblendung, neu = _laufen(schritte)
    assert io and all(c.split("/")[2] in ("LK-1", "LK-2") for c in io), io
    letzte = {c.split("/")[2]: int(c.split("/")[3]) for c in io}
    assert 0 < letzte["LK-1"] < 80 and abs(letzte["LK-2"] - letzte["LK-1"] * 0.75) <= 1, letzte
    assert einblendung[0] == "Licht · Essen-Kochen-Wohnen" and einblendung[1].endswith("%"), einblendung
    assert neu == 0


def test_tipp_mitte_schaltet_die_stimmung_weiter():
    async def schritte(ms, pg, cdp):
        await zwei_finger(cdp, BREITE / 2, HOEHE / 2, HOEHE / 2, schritte=1)
        io = await _warten(ms, 1)
        await pg.wait_for_function("document.querySelector('#geste .gs-wert').textContent === 'Putzen'")
        return io
    assert _laufen(schritte) == ["sps/io/LK/changeTo/2"]


def test_links_hoch_faehrt_die_beschattung_auf():
    async def schritte(ms, pg, cdp):
        await zwei_finger(cdp, BREITE * 0.15, HOEHE * 0.7, HOEHE * 0.35)
        return await _warten(ms, 2)
    assert _laufen(schritte) == ["sps/io/J1/FullUp", "sps/io/J2/FullUp"]


def test_doppeltipp_verlaesst_den_raum():
    """Ohne Taster aus Loxone: aus, was an ist (Lichtsteuerung Kochen, Musik)."""
    async def schritte(ms, pg, cdp):
        for _ in range(2):
            await zwei_finger(cdp, BREITE / 2, HOEHE / 2, HOEHE / 2, schritte=1)
            await asyncio.sleep(0.1)
        return await _warten(ms, 2)
    assert sorted(_laufen(schritte)) == ["sps/io/AZ/pause", "sps/io/LK/changeTo/778"]


def test_ueber_einer_kachel_keine_detailseite():
    """Ein Zwei-Finger-Tipp mitten auf einer Kachel in der mittleren Spalte:
    die Stimmung schaltet weiter, die Detailseite der Kachel oeffnet nicht."""
    async def schritte(ms, pg, cdp):
        k = await pg.evaluate(f"""() => {{ for (const t of document.querySelectorAll('#grid .tile[data-id]')) {{
            const r = t.getBoundingClientRect(), x = r.left + r.width / 2;
            if (x > {BREITE} / 3 + 20 && x < {BREITE} * 2 / 3 - 20) return [x, r.top + r.height / 2, t.dataset.id]; }}
          return null; }}""")
        assert k, "keine Kachel in der mittleren Spalte"
        stapel = await pg.evaluate("stack.length")
        await zwei_finger(cdp, k[0], k[1], k[1], schritte=1, abstand=20)
        io = await _warten(ms, 1)
        return io, await pg.evaluate("stack.length") - stapel, await pg.evaluate("view.route.view")
    io, neu, seite = _laufen(schritte)
    assert io == ["sps/io/LK/changeTo/2"] and neu == 0 and seite == "tab"


def test_ein_finger_bleibt_wie_er_war():
    """Ein Finger wischt und tippt ohne Geste: kein Befehl, keine Einblendung."""
    async def schritte(ms, pg, cdp):
        await ein_finger(cdp, BREITE / 2, HOEHE * 0.6, HOEHE * 0.3)
        await asyncio.sleep(0.6)
        return list(ms.io), await _einblendung(pg)
    assert _laufen(schritte) == ([], None)


def test_im_grundriss_zoomen_zwei_finger():
    """Steht der Grundriss (Anlagenschema), gehoeren zwei Finger dem Zoom:
    keine Geste, kein Befehl."""
    async def schritte(ms, pg, cdp):
        await pg.evaluate("document.getElementById('grid').classList.add('scheme')")
        await zwei_finger(cdp, BREITE / 2, HOEHE / 2, HOEHE / 2, schritte=1)
        await zwei_finger(cdp, BREITE / 2, HOEHE * 0.3, HOEHE * 0.6)
        await asyncio.sleep(0.8)
        return list(ms.io), await _einblendung(pg)
    assert _laufen(schritte) == ([], None)


def test_ausgeschaltet_tun_zwei_finger_nichts():
    async def schritte(ms, pg, cdp):
        await zwei_finger(cdp, BREITE / 2, HOEHE / 2, HOEHE / 2, schritte=1)
        await zwei_finger(cdp, BREITE / 2, HOEHE * 0.3, HOEHE * 0.6)
        await asyncio.sleep(0.8)
        return list(ms.io), await _einblendung(pg)
    assert _laufen(schritte, ui={"gesten": False}) == ([], None)


def test_konfigurator_speichert_die_gesten(cfg_ordner, tmp_path):
    """Geraete: Stimmung beim Einschalten aus den Stimmungen der Anlage.
    Vorgaben -> Verhalten: Gesten an, Taster fuer Haus aus und je Raum fuer
    Raum verlassen - zur Auswahl nur Taster ohne Visu-Passwort. Ansicht ->
    Verhalten: Gesten und Raum ausserhalb von Raumseiten. Ein Speichern
    schreibt alles in panels.json bzw. theme.json."""
    from lox import KONFIGURATOR_GELADEN, karte_auf
    from test_kachel_set_browser import ROUTEN, OFFEN

    async def lauf():
        (cfg_ordner / "panels.json").write_text(json.dumps({
            "panels": {"test": {"title": "Test", "tabs": ["room:r1"]}},
            "devices": {"kueche": {"auto": True, "modes": {"nacht": "test"}}}}), encoding="utf-8")
        app = W.App({"host": "", "port": 80})
        struktur, states = gesten_anlage()
        app._apply_structure(struktur)
        app.states = states
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)

                await pg.locator(".rub", has_text="Geräte").click()
                await karte_auf(pg, "kueche")
                start = pg.locator('#geraete .gk[data-gk="kueche"] .dl_start')
                gruppen = await start.evaluate("s => [...s.querySelectorAll('optgroup')].map(g => g.label)")
                await start.select_option("LW|4")

                await pg.locator(".rub", has_text="Vorgaben").click()
                await pg.locator(".stab[data-sub='verhalten']").click()
                taster = await pg.eval_on_selector_all("#gHausAus option", "l => l.map(o => o.value)")
                await pg.locator("#gGesten").select_option("an")
                await pg.locator("#gHausAus").select_option("TH")
                await pg.locator("[data-gv-raum='r1']").select_option("TV")
                await pg.screenshot(path=str(tmp_path / "gesten_vorgaben.png"), full_page=True)

                await pg.locator("#plist .pitem", has_text="?panel=test").click()
                await pg.locator(".stab[data-sub='verhalten']").click()
                erbt = await pg.locator(".erbt[data-erbt='gesten']").text_content()
                await pg.locator("#fGestenRaum").select_option("r3")

                await pg.locator("#saveBtn").click()
                await pg.wait_for_function(f"{OFFEN} === 'Alles gespeichert'")
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return gruppen, taster, erbt
    gruppen, taster, erbt = asyncio.run(lauf())
    assert gruppen == ["Abstellraum · Licht Abstellraum", "Essen-Kochen-Wohnen · Licht Kochen",
                       "Essen-Kochen-Wohnen · Licht Wohnen"], gruppen
    assert taster == ["", "TV", "TH"], "nur Taster, ohne Visu-Passwort"
    assert "An" in erbt and "Vorgaben" in erbt, erbt
    datei = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))
    assert datei["devices"]["kueche"]["lichtStart"] == {"lc": "LW", "mood": 4}
    assert datei["panels"]["test"]["ui"] == {"gestenRaum": "r3"}
    theme = json.loads((cfg_ordner / "theme.json").read_text(encoding="utf-8"))["ui"]
    assert (theme["gesten"], theme["hausAus"], theme["raumVerlassen"]) == (True, "TH", {"r1": "TV"})


# ---- Gesten im Dunkeln und Nacht-Uhr (Stufe 5) ------------------------------

def _dunkel(pg):
    """Uhr-Seite sichtbar, Nacht-Uhr, Auflage der Nacht (inline gesetzt, ohne
    Uebergang) und ob die Einblendung leise ist."""
    return pg.evaluate("""() => { const n = document.getElementById('geste'), d = document.getElementById('nightdim');
      return {uhr: !document.getElementById('saver').classList.contains('hidden'),
              nacht: document.getElementById('saver').classList.contains('nacht'),
              auflage: d ? +d.style.opacity : null, leise: !!n && n.classList.contains('leise')}; }""")


def test_auf_der_uhr_seite_dimmen_zwei_finger_ohne_zu_wecken():
    """Zwei Finger auf der Uhr-Seite: das Licht wird dunkler, die Uhr bleibt,
    die Einblendung ist leise. Ein Finger weckt danach wie bisher und loest
    nichts aus."""
    async def schritte(ms, pg, cdp):
        await zwei_finger(cdp, BREITE / 2, HOEHE * 0.3, HOEHE * 0.6)
        io = await _warten(ms, 2)
        nach_geste = await _dunkel(pg)
        await _finger(cdp, "touchStart", [(BREITE / 2, HOEHE / 2)])
        await _finger(cdp, "touchEnd", [])
        await asyncio.sleep(0.5)
        return io, nach_geste, await _dunkel(pg), list(ms.io)
    io, nach_geste, nach_tipp, alles = _laufen(schritte, uhr=True)
    assert io and all(c.split("/")[2] in ("LK-1", "LK-2") for c in io), io
    assert nach_geste["uhr"] and nach_geste["leise"], nach_geste
    assert not nach_tipp["uhr"], "ein Finger weckt"
    assert alles == io, "der weckende Finger loest nichts aus"


def test_ein_finger_der_liegen_bleibt_weckt_nach_der_wartezeit():
    async def schritte(ms, pg, cdp):
        await _finger(cdp, "touchStart", [(BREITE / 2, HOEHE / 2)])
        await asyncio.sleep(0.4)            # laenger als GESTE_ZWEITER_FINGER_MS
        noch = await _dunkel(pg)
        await _finger(cdp, "touchEnd", [])
        await asyncio.sleep(0.4)
        return noch, list(ms.io)
    noch, io = _laufen(schritte, uhr=True)
    assert not noch["uhr"] and io == []


def test_nachts_hellt_eine_geste_nicht_auf():
    """Nachts abgedunkelt: zwei Finger schalten die Stimmung, die Auflage
    bleibt; ein Finger hellt wie bisher auf."""
    async def schritte(ms, pg, cdp):
        vorher = await _dunkel(pg)
        await zwei_finger(cdp, BREITE / 2, HOEHE / 2, HOEHE / 2, schritte=1)
        io = await _warten(ms, 1)
        nach_geste = await _dunkel(pg)
        await ein_finger(cdp, BREITE / 2, HOEHE * 0.6, HOEHE * 0.4)
        await asyncio.sleep(0.4)
        return vorher, io, nach_geste, await _dunkel(pg)
    vorher, io, nach_geste, nach_finger = _laufen(schritte, nacht=True, ui={"nightDim": 70, "nightWake": 20})
    assert vorher["auflage"] == 0.7 and io == ["sps/io/LK/changeTo/2"]
    assert nach_geste["auflage"] == 0.7 and nach_geste["leise"], nach_geste
    assert nach_finger["auflage"] == 0, nach_finger


# Bruecke der LoxPanel-App (KioskActivity.KioskBridge), nachgebaut: setSaver meldet
# die Uhr-Seite, die App weckt bei setSaver(false)
APP_JS = """window.__lox = []; window.LoxKiosk = { _an: true, setDisplayOff(s) {},
  setSaver(on) { window.__lox.push('saver:' + on); },
  turnScreenOff() { this._an = false; }, turnScreenOn() { this._an = true; window.__lox.push('an'); },
  isScreenOn() { return this._an; } };"""


def test_in_der_app_bleibt_der_schoner_bei_einer_geste():
    """Mit der LoxPanel-App: Eine Geste auf der Uhr-Seite meldet der App nicht
    setSaver(false) - sonst holte sie das Display aus dem Dunkeln. (Dass die
    App zwei Finger ueberhaupt weiterreicht, prueft SchonerBeruehrungTest.)"""
    async def schritte(ms, pg, cdp):
        await pg.evaluate("window.__lox.length = 0")
        await zwei_finger(cdp, BREITE / 2, HOEHE / 2, HOEHE / 2, schritte=1)
        io = await _warten(ms, 1)
        nach_geste = await pg.evaluate("window.__lox.slice()")
        await _finger(cdp, "touchStart", [(BREITE / 2, HOEHE / 2)])
        await _finger(cdp, "touchEnd", [])
        await asyncio.sleep(0.4)
        return io, nach_geste, await pg.evaluate("window.__lox.slice()")
    io, nach_geste, nach_tipp = _laufen(schritte, uhr=True, init=APP_JS)
    assert io == ["sps/io/LK/changeTo/2"] and nach_geste == [], nach_geste
    assert "saver:false" in nach_tipp, nach_tipp


NACHT_UHR = """() => { const s = document.getElementById('saver'), n = document.getElementById('svNacht');
  const r = s.getBoundingClientRect();
  return {nacht: s.classList.contains('nacht'), sichtbar: !n.hidden,
          klassen: (s.className + ' ' + s.querySelector('.sv-wrap').className).split(' '),
          wrap: getComputedStyle(s.querySelector('.sv-wrap')).display,
          hell: +getComputedStyle(n).opacity, zeit: document.getElementById('nuZeit').textContent,
          farbe: getComputedStyle(n).color,
          zonen: [...document.querySelectorAll('#nuZonen span')].map(e => {
            const b = e.getBoundingClientRect(); return Math.round((b.left + b.width / 2 - r.left) / r.width * 100); }),
          grund: getComputedStyle(s).backgroundColor}; }"""


@pytest.mark.parametrize("ui, gesten, zonen", [
    ({"nightClock": True, "nightClockBright": 30}, True, [17, 50, 83]),
    ({"nightClock": True, "nightClockBright": 30}, False, []),
], ids=["mit-gesten", "ohne-gesten"])
def test_nacht_uhr(ui, gesten, zonen, tmp_path):
    """Nachts mit Nacht-Uhr: nur die Uhrzeit auf Schwarz in der eingestellten
    Helligkeit, Wetter und Termine ruhen; mit Gesten oben je Spalte ihr Symbol,
    mittig ueber der Spalte."""
    async def schritte(ms, pg, cdp):
        await pg.screenshot(path=str(tmp_path / f"nacht_uhr_{'gesten' if gesten else 'ohne'}.png"))
        return await pg.evaluate(NACHT_UHR)
    m = _laufen(schritte, ui={**ui, "gesten": gesten}, uhr=True, nacht=True)
    assert m["nacht"] and m["sichtbar"] and m["wrap"] == "none", m
    assert abs(m["hell"] - 0.3) < 0.01 and _hex(m["grund"]) == TC.NACHT_GRUND, m
    assert len(m["zeit"]) == 5 and m["zeit"][2] == ":", m
    assert m["zonen"] == zonen, m


def test_nacht_uhr_ersetzt_auch_die_geteilte_uhr_seite(monkeypatch, tmp_path):
    """Mit Wetter und Terminen teilt sich die Uhr-Seite quer in zwei Spalten
    (Raster aus .saver.split .sv-wrap.rich). Diese Regel war spezifischer als
    die, die nachts den Inhalt ausblendet: die Nacht-Uhr lag dann ueber Uhr,
    Wetter und Terminen, statt sie zu ersetzen."""
    from test_front_tabs_browser import _front
    daten = asyncio.run(_front(monkeypatch))

    async def schritte(ms, pg, cdp):
        await pg.screenshot(path=str(tmp_path / "nacht_uhr_geteilt.png"))
        return await pg.evaluate(NACHT_UHR)
    m = _laufen(schritte, ui={"nightClock": True}, uhr=True, nacht=True, front=daten)
    assert {"split", "rich"} <= set(m["klassen"]), m
    assert m["nacht"] and m["sichtbar"] and m["wrap"] == "none", m
    tags = _laufen(lambda ms, pg, cdp: pg.evaluate(NACHT_UHR), ui={"nightClock": True}, uhr=True, front=daten)
    assert {"split", "rich"} <= set(tags["klassen"]) and tags["wrap"] == "grid" and not tags["sichtbar"], tags


def _hex(rgb: str) -> str:
    return "#%02x%02x%02x" % tuple(int(x) for x in rgb[rgb.index("(") + 1:rgb.index(")")].split(",")[:3])


@pytest.mark.parametrize("tile_set", [None, *TC.KACHEL_SETS])
def test_nacht_uhr_in_jedem_kachel_set_lesbar(tile_set, tmp_path):
    """Grund und Schrift der Nacht-Uhr kommen aus dem Theme. Vorher nahmen die
    Ziffern --ink: in hellen Sets (Kreide, Touch) dunkel auf Schwarz, nur dort
    zu sehen, wo sie ueber helle Flaechen liefen. Gemessen bei voller
    Helligkeit (die eingestellte wirkt als Deckkraft obendrauf)."""
    async def schritte(ms, pg, cdp):
        await pg.screenshot(path=str(tmp_path / f"nacht_uhr_{tile_set or 'ohne_set'}.png"))
        return await pg.evaluate(NACHT_UHR)
    ui = {"nightClock": True, "nightClockBright": 100, **({"tileSet": tile_set} if tile_set else {})}
    m = _laufen(schritte, ui=ui, uhr=True, nacht=True)
    assert m["nacht"] and m["sichtbar"] and _hex(m["grund"]) == TC.NACHT_GRUND, m
    assert TC.kontrast(_hex(m["farbe"]), TC.NACHT_GRUND) >= TC.AAA, (tile_set, m)


def test_nacht_uhr_nur_nachts_und_wenn_eingeschaltet():
    tags = _laufen(lambda ms, pg, cdp: pg.evaluate(NACHT_UHR), ui={"nightClock": True}, uhr=True)
    aus = _laufen(lambda ms, pg, cdp: pg.evaluate(NACHT_UHR), uhr=True, nacht=True)
    assert not tags["nacht"] and not tags["sichtbar"] and tags["wrap"] != "none", tags
    assert not aus["nacht"] and not aus["sichtbar"], aus
