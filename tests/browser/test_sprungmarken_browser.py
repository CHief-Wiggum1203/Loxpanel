"""Sprungmarken der unteren Leiste in Chromium: Springen zeigt die Zielkachel und
laesst die Gruppe aufleuchten (frueher rutschte der Sprung wegen des
seitenweisen Einrastens eine Seite zu weit); Filtern zeigt nur die Gruppe. Der
Raum kommt aus tests/lox.py (raum_anlage)."""
import asyncio

import pytest

from lox import RAUM_KATS, W, raum_anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

KACHELN = """() => [...document.querySelectorAll('#grid .tile[data-id]')].map(n => n._it && n._it.grp)"""
AKTIV = """() => [...document.querySelectorAll('#tabs .tab.active[data-cat]')].map(n => n.dataset.cat)"""


async def _panel(panel: dict, breite: int, hoehe: int, ablauf):
    struktur, states = raum_anlage()
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    app.states = states
    app.panels = W.App._sanitize_panels({"test": dict(panel, title="Test")})
    runner, port, bc = await visu_starten(app)
    fehler = []
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch()
            pg = await b.new_page(viewport={"width": breite, "height": hoehe})
            pg.on("pageerror", lambda e: fehler.append(str(e)))
            await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
            await pg.wait_for_timeout(600)
            await pg.evaluate("wake()")
            await pg.wait_for_timeout(1000)
            await ablauf(pg, app)
            await b.close()
    finally:
        bc.cancel()
        await runner.cleanup()
    assert not fehler, fehler


@pytest.mark.parametrize("breite, hoehe, ui", [(480, 480, {}), (486, 724, {"rows": 3})], ids=["4zoll_2x2", "hochkant_2x3"])
def test_sprung_zeigt_zielkachel_und_leuchtet(breite, hoehe, ui):
    """Jede Sprungmarke bringt die erste Kachel ihrer Gruppe ins Bild - auch wenn
    sie unten auf einer Seite steht - und laesst die ganze Gruppe aufleuchten."""
    async def ablauf(pg, app):
        for cat, (_, anzahl) in RAUM_KATS.items():
            await pg.locator(f'#tabs .tab[data-cat="{cat}"]').click()
            await pg.wait_for_timeout(150)
            leuchtet = await pg.evaluate("""k => [...document.querySelectorAll('#grid .tile.katleucht')]
                .map(n => n._it.grp)""", cat)
            assert leuchtet == [cat] * anzahl, (cat, leuchtet)
            await pg.wait_for_timeout(800)
            sichtbar = await pg.evaluate("""k => { const g = document.getElementById('grid').getBoundingClientRect(),
                r = document.querySelector('#grid .tile[data-cat="' + k + '"]').getBoundingClientRect();
                return r.top >= g.top - 1 && r.bottom <= g.bottom + 1; }""", cat)
            assert sichtbar, cat
        await pg.wait_for_timeout(1700)
        assert await pg.evaluate("document.querySelectorAll('#grid .tile.katleucht').length") == 0
        assert len(await pg.evaluate(KACHELN)) == sum(n for _, n in RAUM_KATS.values())   # Springen filtert nicht
    asyncio.run(_panel({"tabs": ["room:r1"], "ui": ui}, breite, hoehe, ablauf))


def test_filter_zeigt_nur_die_gruppe(tmp_path):
    """Filter-Modus: ein Tipp zeigt nur die Gruppe und markiert ihre Marke, ein
    zweiter wieder alle. Aus einer Detailseite zurueck in den gefilterten Raum,
    Live-Werte halten den Filter, nach Ruhe ist er weg."""
    alle = [c for c, (_, n) in RAUM_KATS.items() for _ in range(n)]

    async def ablauf(pg, app):
        assert await pg.evaluate(KACHELN) == alle
        await pg.locator('#tabs .tab[data-cat="c3"]').click()
        await pg.wait_for_timeout(300)
        assert await pg.evaluate(KACHELN) == ["c3"] * 4 and await pg.evaluate(AKTIV) == ["c3"]
        await pg.screenshot(path=str(tmp_path / "filter_c3.png"))
        await pg.locator('#tabs .tab[data-cat="c3"]').click()          # zweiter Tipp: wieder alle
        await pg.wait_for_timeout(300)
        assert await pg.evaluate(KACHELN) == alle and await pg.evaluate(AKTIV) == []
        await pg.locator('#tabs .tab[data-cat="c2"]').click()
        await pg.wait_for_timeout(300)
        assert await pg.evaluate(KACHELN) == ["c2"] * 2
        # Live-Wert einer gefilterten Kachel: der Filter bleibt, die Kachel schaltet um
        app.states["s4"] = 1
        app._dirty = True
        await pg.wait_for_timeout(900)
        assert await pg.evaluate(KACHELN) == ["c2"] * 2
        assert await pg.evaluate("document.querySelector('#grid .tile[data-id=\"S4\"]').classList.contains('on')")
        # Detailseite, dann Marke antippen: zurueck in den Raum, gefiltert
        await pg.evaluate("nav({view:'control', id:'S1'})")
        await pg.wait_for_timeout(600)
        assert await pg.evaluate("stack.length") == 2
        await pg.locator('#tabs .tab[data-cat="c4"]').click()
        await pg.wait_for_timeout(700)
        assert await pg.evaluate("stack.length") == 1
        assert await pg.evaluate(KACHELN) == ["c4"] * 3 and await pg.evaluate(AKTIV) == ["c4"]
        # Nach Ruhe (Uhr-Seite) wieder die ganze Startseite
        await pg.evaluate("nachRuhe()")
        await pg.wait_for_timeout(600)
        await pg.evaluate("wake()")
        await pg.wait_for_timeout(300)
        assert await pg.evaluate(KACHELN) == alle and await pg.evaluate(AKTIV) == []
    asyncio.run(_panel({"tabs": ["room:r1"], "ui": {"catFilter": True}}, 480, 480, ablauf))


def test_filter_freie_auswahl_nach_raum():
    """Freie Auswahl ueber zwei Raeume: die Marken sind die Raeume, der Filter
    zeigt nur die Bausteine des gewaehlten Raums."""
    seite = {"name": "Morgens", "picks": ["S1", "T1", "S4", "T2"]}

    async def ablauf(pg, app):
        assert await pg.evaluate(KACHELN) == ["r1", "r1", "r2", "r2"]
        await pg.locator('#tabs .tab[data-cat="r2"]').click()
        await pg.wait_for_timeout(300)
        assert await pg.evaluate("[...document.querySelectorAll('#grid .tile[data-id]')].map(n => n.dataset.id)") \
            == ["T1", "T2"]
    asyncio.run(_panel({"tabs": ["auswahl"], "pickTabs": [seite], "ui": {"catFilter": True}}, 480, 480, ablauf))
