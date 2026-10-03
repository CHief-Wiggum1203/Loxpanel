"""Die vier frueher nur teilweise bedienbaren Bausteine in Chromium (480x480):
Kachel antippen, Detailseite bedienen, die Befehle kommen beim
Miniserver-Nachbau an - so kodiert, wie die Loxone-Strukturdoku sie verlangt.
Die Bausteine kommen aus tests/lox.py."""
import asyncio
import base64
import json

import pytest

from lox import (BETRIEBSARTEN, KLINGELN, Miniserver, W, anlage, aufab_baustein, bewaesserung_baustein,
                 intercom_baustein, neue_app, visu_starten, wecker_baustein)

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

# Ein Pixel PNG: ein Bild, das der Browser wirklich dekodiert
PIXEL = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


async def _visu(tmp_path, bausteine, schritt, routen=()):
    """Visu mit den Bausteinen (je (Control, States)) als Favoriten, der
    Nachbau nimmt die Befehle an. schritt(pg, ms, app) bedient."""
    ms = await Miniserver().start()
    app = neue_app(ms)
    controls, states = {}, {}
    for control, st in bausteine:
        controls[control["uuidAction"]] = {**control, "isFavorite": True}
        states.update(st)
    struktur = anlage(controls)
    struktur["operatingModes"] = BETRIEBSARTEN
    app._apply_structure(struktur)
    app.states = states
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"]}})
    runner, port, bc = await visu_starten(app, routen)
    fehler = []
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch()
            pg = await b.new_page(viewport={"width": 480, "height": 480})
            pg.on("pageerror", lambda e: fehler.append(str(e)))
            await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
            await pg.wait_for_timeout(600)
            await pg.evaluate("wake()")
            await pg.wait_for_timeout(800)
            await schritt(pg, ms, app)
            await b.close()
    finally:
        bc.cancel()
        await app.icon_session.close()
        await runner.cleanup()
        await ms.stop()
    assert not fehler, fehler


async def _befehle(ms, anzahl, warten=3.0) -> list[str]:
    """Wartet, bis anzahl Befehle beim Nachbau sind -> die Befehle (kodiert)."""
    for _ in range(int(warten / 0.05)):
        if len(ms.io_roh) >= anzahl:
            break
        await asyncio.sleep(0.05)
    return list(ms.io_roh)


async def _kachel(pg, name):
    await pg.locator(".tile", has_text=name).first.click()
    await pg.wait_for_timeout(700)


def _knopf(pg, text):
    return pg.locator(".brow .btn", has_text=text).first


def test_auf_ab_wert(tmp_path, miniserver_http):
    """-/+ schalten um step weiter und senden den Wert; bei max ist Schluss."""
    async def schritt(pg, ms, app):
        await _kachel(pg, "Lamelle waagrecht")
        await pg.screenshot(path=str(tmp_path / "aufab.png"))
        plus = pg.locator('.srow .sbtn[data-sd="up"]')
        for erwartet in ("sps/io/UDA/2", "sps/io/UDA/3"):
            await plus.click()
            assert (await _befehle(ms, len(ms.io_roh) + 1))[-1] == erwartet
        await plus.click()
        await pg.wait_for_timeout(500)
        assert len(ms.io_roh) == 2, ms.io_roh
        await pg.locator('.srow .sbtn[data-sd="dn"]').click()
        assert (await _befehle(ms, 3))[-1] == "sps/io/UDA/2"
    asyncio.run(_visu(tmp_path, [aufab_baustein()], schritt))


def test_auf_ab_wert_halbe_schritte(tmp_path, miniserver_http):
    """step 0,5: + ergibt 20,5 statt (wie frueher gerundet) 21."""
    async def schritt(pg, ms, app):
        await _kachel(pg, "Lamelle waagrecht")
        await pg.locator('.srow .sbtn[data-sd="up"]').click()
        assert await _befehle(ms, 1) == ["sps/io/UDA/20.5"]
    asyncio.run(_visu(tmp_path, [aufab_baustein(wert=20, format="%.1f", min=0, max=30, step=0.5)], schritt))


def test_bewaesserung_zone(tmp_path, miniserver_http):
    async def schritt(pg, ms, app):
        await _kachel(pg, "Bewässerung")
        await pg.screenshot(path=str(tmp_path / "bewaesserung.png"))
        zonen = pg.locator(".brow.wraprow .btn")
        assert await zonen.all_inner_texts() == ["Rasen vorne · 10 min", "Beete · 5 min", "Hecke · 15 min"]
        await zonen.nth(1).click()
        await pg.wait_for_timeout(700)
        await pg.screenshot(path=str(tmp_path / "bewaesserung_zone.png"))
        assert await pg.locator(".ptitle").first.inner_text() == "Beete\nBewässerung"
        assert ms.io_roh == [], "Antippen der Zone oeffnet nur ihre Seite"
        plus = pg.locator('.stp .sbtn[data-st="1"]')
        for _ in range(3):
            await plus.click()
        assert await pg.locator(".stpv").inner_text() == "8 min"
        # Waehrenddessen startet die Zone (Seite kommt neu): -/+ behaelt den eigenen Wert
        app.states["bew-currentZone"] = 1
        app._dirty = True
        await pg.wait_for_timeout(500)
        assert await pg.locator(".pbig").inner_text() == "Läuft"
        assert await pg.locator(".stpv").inner_text() == "8 min"
        assert ms.io_roh == [], "erst senden, wenn niemand mehr tippt"
        assert await _befehle(ms, 1) == ["sps/io/BEW/setDuration/1=480"]
        await pg.wait_for_timeout(1200)
        assert len(ms.io_roh) == 1, ms.io_roh
        await _knopf(pg, "Zone stoppen").click()
        assert (await _befehle(ms, 2))[-1] == "sps/io/BEW/stop"
        app.states["bew-currentZone"] = -1
        app._dirty = True
        await pg.wait_for_timeout(600)
        await _knopf(pg, "Zone starten").click()
        assert (await _befehle(ms, 3))[-1] == "sps/io/BEW/select/2"
        await pg.locator("#tabback").click()
        await pg.wait_for_timeout(600)
        await pg.locator(".brow.wraprow .btn", has_text="Hecke").click()
        await pg.wait_for_timeout(600)
        assert await pg.locator(".stp .sbtn").count() == 0                  # Laufzeit gibt die Logik vor
        assert await pg.locator(".stps").inner_text() == "von der Logik vorgegeben"
    asyncio.run(_visu(tmp_path, [bewaesserung_baustein()], schritt))


def test_wecker_schalten_und_bearbeiten(tmp_path, miniserver_http):
    async def schritt(pg, ms, app):
        await _kachel(pg, "Anna Wecker")
        await pg.screenshot(path=str(tmp_path / "wecker.png"))
        # Schalter: schaltet nur, oeffnet nichts
        await pg.locator(".arow", has_text="Arbeit").locator(".asw").click()
        assert await _befehle(ms, 1) == ["sps/io/WK/entryList/put/1/Arbeit/22500/0/3,4,5,6,7"]
        await pg.wait_for_timeout(400)
        assert await pg.locator(".tpk").count() == 0
        # Der Miniserver meldet den Eintrag aus: die Liste folgt (nicht erst beim Neuaufbau)
        eintraege = json.loads(app.states["wk-entryList"])
        eintraege["1"]["isActive"] = False
        app.states["wk-entryList"] = json.dumps(eintraege)
        app._dirty = True
        await pg.wait_for_timeout(900)
        assert "off" in await pg.locator(".arow", has_text="Arbeit").get_attribute("class")
        # Zeile: bearbeiten - Uhrzeit, Tage, Name
        await pg.locator(".arow", has_text="Wochenende").click()
        await pg.wait_for_timeout(700)
        await pg.screenshot(path=str(tmp_path / "wecker_bearbeiten.png"))
        assert await pg.locator(".tpv").all_inner_texts() == ["08", "30"]
        assert await pg.locator(".chp.on").all_inner_texts() == ["Sa", "So", "Feiertag"]
        await pg.locator('.tpc[data-u="h"] .sbtn[data-d="1"]').click()
        await pg.locator('.tpc[data-u="m"] .sbtn[data-d="-1"]').click()
        assert await pg.locator(".tpv").all_inner_texts() == ["09", "29"]
        await pg.locator(".chp", has_text="So").click()
        await pg.locator(".chp", has_text="Fr").click()
        await pg.fill(".fld input", "Wochenende / früh")
        assert len(ms.io_roh) == 1, "vor dem Speichern geht nichts raus"
        await _knopf(pg, "Speichern").click()
        assert (await _befehle(ms, 2))[-1] == (
            "sps/io/WK/entryList/put/2/Wochenende%20%2F%20fr%C3%BCh/34140/0/7,8,0")
        await pg.wait_for_timeout(600)
        assert await pg.locator(".alist").count() == 1, "nach dem Speichern zurueck zur Liste"
    asyncio.run(_visu(tmp_path, [wecker_baustein()], schritt))


def test_wecker_loeschen_mit_rueckfrage(tmp_path, miniserver_http):
    async def schritt(pg, ms, app):
        await _kachel(pg, "Anna Wecker")
        await pg.locator(".arow", has_text="Arbeit").click()
        await pg.wait_for_timeout(700)
        loeschen = _knopf(pg, "Löschen")
        await loeschen.click()
        assert await pg.locator(".brow .btn.arm").inner_text() == "Wirklich löschen?"
        await pg.wait_for_timeout(300)
        assert ms.io_roh == []
        await pg.locator(".brow .btn.arm").click()
        assert await _befehle(ms, 1) == ["sps/io/WK/entryList/delete/1"]
        await pg.wait_for_timeout(600)
        assert await pg.locator(".alist").count() == 1
    asyncio.run(_visu(tmp_path, [wecker_baustein()], schritt))


def test_wecker_rueckfrage_verfaellt(tmp_path, miniserver_http):
    async def schritt(pg, ms, app):
        await _kachel(pg, "Anna Wecker")
        await pg.locator(".arow", has_text="Arbeit").click()
        await pg.wait_for_timeout(700)
        await _knopf(pg, "Löschen").click()
        await pg.wait_for_timeout(4500)
        assert await pg.locator(".brow .btn.arm").count() == 0
        await _knopf(pg, "Löschen").click()                        # wieder erst die Rueckfrage
        await pg.wait_for_timeout(300)
        assert ms.io_roh == []
    asyncio.run(_visu(tmp_path, [wecker_baustein()], schritt))


def test_wecker_neue_weckzeit(tmp_path, miniserver_http):
    async def schritt(pg, ms, app):
        await _kachel(pg, "Anna Wecker")
        await _knopf(pg, "Neue Weckzeit").click()
        await pg.wait_for_timeout(700)
        speichern = _knopf(pg, "Speichern")
        assert "dis" in await speichern.get_attribute("class"), "ohne Tag gesperrt"
        await pg.locator(".chp", has_text="Mo").click()
        assert "dis" not in await speichern.get_attribute("class")
        await pg.fill(".fld input", "  ")
        assert "dis" in await speichern.get_attribute("class"), "ohne Namen gesperrt"
        await pg.fill(".fld input", "Früh")
        zeit = await pg.locator(".tpk").get_attribute("data-v")
        await speichern.click()
        assert await _befehle(ms, 1) == [f"sps/io/WK/entryList/put/3/Fr%C3%BCh/{zeit}/1/3"]
    asyncio.run(_visu(tmp_path, [wecker_baustein()], schritt))


def test_wecker_einstellungen(tmp_path, miniserver_http):
    async def schritt(pg, ms, app):
        await _kachel(pg, "Anna Wecker")
        await _knopf(pg, "Einstellungen").click()
        await pg.wait_for_timeout(700)
        await pg.screenshot(path=str(tmp_path / "wecker_einstellungen.png"))
        assert await pg.locator(".stpv").all_inner_texts() == ["9 min", "5 min", "15 min"]
        schlummer = pg.locator(".stp").first
        # Halten zaehlt weiter, bei 30 min (Wissensdatenbank) ist Schluss
        await schlummer.locator('.sbtn[data-st="1"]').hover()
        await pg.mouse.down()
        await pg.wait_for_timeout(3200)
        await pg.mouse.up()
        assert await schlummer.locator(".stpv").inner_text() == "30 min"
        assert await _befehle(ms, 1) == ["sps/io/WK/setSnoozeDuration/1800"]
        await pg.wait_for_timeout(1200)
        assert len(ms.io_roh) == 1, ms.io_roh
    asyncio.run(_visu(tmp_path, [wecker_baustein()], schritt))


def test_intercom_verpasste_klingeln(tmp_path, miniserver_http):
    async def schritt(pg, ms, app):
        for ts in KLINGELN[1:]:
            ms.bilder[("IC", ts)] = PIXEL
        await _kachel(pg, "Eingang Intercom")
        await _knopf(pg, "3 verpasste Klingeln").click()
        await pg.wait_for_timeout(1000)
        await pg.screenshot(path=str(tmp_path / "klingeln.png"))
        bilder = pg.locator(".gal .gimg")
        assert await bilder.locator("figcaption").all_inner_texts() == [
            W.App._bell_text(ts) for ts in sorted(KLINGELN, reverse=True)]
        geladen = await bilder.locator("img").evaluate_all(
            "l => l.map(i => [i.naturalWidth > 0, getComputedStyle(i).visibility])")
        assert geladen == [[True, "visible"], [True, "visible"], [False, "hidden"]], "das aelteste fehlt"
        await bilder.first.click()
        gross = pg.locator(".galov")
        assert await gross.locator(".gcap").inner_text() == W.App._bell_text(KLINGELN[-1])
        await gross.click()
        assert await pg.locator(".galov").count() == 0
        assert ms.io_roh == []
        # Es klingelt: die Detailseite bietet "Klingel abstellen" (answer)
        await pg.locator("#tabback").click()
        await pg.wait_for_timeout(500)
        app.states["ic-bell"] = 1
        app._dirty = True
        await pg.wait_for_timeout(900)
        await _knopf(pg, "Klingel abstellen").click()
        assert await _befehle(ms, 1) == ["sps/io/IC/answer"]
    asyncio.run(_visu(tmp_path, [intercom_baustein()], schritt, routen=[("GET", "/bellimg", W.bellimg_handler)]))


UEBERLAPPUNG_JS = """() => {
  const top = document.querySelector('.pantop'), bot = document.querySelector('.panbot');
  const ende = Math.max(...[...top.children].filter(c => c.offsetParent).map(c => c.getBoundingClientRect().bottom));
  return ende - bot.getBoundingClientRect().top; }"""


def test_volle_seite_ueberlappt_nicht(tmp_path, miniserver_http):
    """480x480 mit vielen Zeilen: nichts von oben ragt in die Bedienung unten
    (frueher lagen bei der Sauna Statuszeilen unter den Tasten). Erst faellt
    der Deko-Kreis weg (eng), reicht das nicht, scrollt die Seite. Eine Seite,
    die passt, bleibt, wie sie ist."""
    acht = [{"id": i, "name": f"Zone {i + 1}", "duration": 300} for i in range(8)]

    async def schritt(pg, ms, app):
        await _kachel(pg, "Bewässerung")
        await pg.screenshot(path=str(tmp_path / "voll.png"))
        assert await pg.evaluate("el('grid').classList.contains('eng')")
        assert await pg.locator(".hero").count() == 1 and not await pg.locator(".hero").is_visible()
        assert await pg.evaluate(UEBERLAPPUNG_JS) <= 0.5
        app.states["bew-zones"] = json.dumps(acht)       # acht Zonen: zu hoch
        app._dirty = True
        await pg.wait_for_timeout(900)
        assert await pg.evaluate(UEBERLAPPUNG_JS) <= 0.5
        assert await pg.evaluate("el('grid').scrollHeight > el('grid').clientHeight"), "die Seite scrollt"
        await _knopf(pg, "Alles aus").scroll_into_view_if_needed()
        assert await _knopf(pg, "Alles aus").is_visible()
        await pg.screenshot(path=str(tmp_path / "uebervoll.png"))
        await pg.locator("#tabback").click()
        await pg.wait_for_timeout(500)
        await _kachel(pg, "Lamelle waagrecht")
        assert not await pg.evaluate("el('grid').classList.contains('eng')")
        assert await pg.locator(".hero").is_visible()
    asyncio.run(_visu(tmp_path, [bewaesserung_baustein(currentZone=1, active=1, rainTime=1500),
                                 aufab_baustein()], schritt))
