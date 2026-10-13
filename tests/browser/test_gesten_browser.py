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

import pytest

from lox import Miniserver, W, gesten_anlage, neue_app, visu_starten

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


def _laufen(schritte, ui=None):
    async def lauf():
        ms = Miniserver()
        await ms.start()
        app = neue_app(ms)
        struktur, states = gesten_anlage()
        app._apply_structure(struktur)
        app.states = states
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["room:r1"],
                                                      "ui": {"grid": "auto", "gesten": True, **(ui or {})}}})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": BREITE, "height": HOEHE}, has_touch=True)
                pg = await ctx.new_page()
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector("#grid .tile[data-id]", state="attached")
                if await pg.locator("#saver:not(.hidden)").count():
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
