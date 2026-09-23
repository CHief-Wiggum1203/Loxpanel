"""Konfigurator (config.html) in Chromium: Verlauf als Split-Haelfte und als
Mini-Verlauf der Kachel einstellen; was der Server beim Speichern behaelt."""
import asyncio
import zipfile

import pytest

from aiohttp import web

from lox import W, anlage, serve

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

V2 = {"groups": [{"id": "1", "mode": 10, "dataPoints": [{"title": "Leistung", "format": "0,000kW", "output": "actual"}]}]}
BAUSTEINE = {
    "T": {"name": "Temp. Boiler", "type": "InfoOnlyAnalog", "uuidAction": "T", "room": "r1", "cat": "c1",
          "statistic": {"outputs": [{"name": "t", "visuType": 0}]}},
    "Z": {"name": "Stromzähler", "type": "InfoOnlyAnalog", "uuidAction": "Z", "room": "r2", "cat": "c1",
          "statistic": {"outputs": [{"name": "z", "visuType": 2}]}},
    "R": {"name": "Regen", "type": "InfoOnlyDigital", "uuidAction": "R", "room": "r1", "cat": "c1",
          "statistic": {"outputs": [{"name": "r", "visuType": 1}]}},
    "P": {"name": "PV Anlage", "type": "Meter", "uuidAction": "P", "room": "r2", "cat": "c1", "statisticV2": V2},
    "X": {"name": "Licht", "type": "Switch", "uuidAction": "X", "room": "r1", "cat": "c1"},
}


def _im_konfigurator(skript: str):
    """config.html laden, skript darin ausfuehren -> Ergebnis. skript ist eine
    async JS-Funktion als Text oder eine async Python-Funktion(page)."""
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten", "raeume"]}})
        ui = web.Application()
        ui["app"] = app
        for pfad, h in (("/config", W.config_index), ("/api/meta", W.api_meta), ("/api/backup", W.api_backup),
                        ("/api/settings", W.api_settings), ("/i18n.js", W.i18n_js)):
            ui.router.add_get(pfad, h)
        runner, port = await serve(ui)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function("typeof META !== 'undefined' && META.controls && META.controls.length")
                res = await skript(pg) if callable(skript) else await pg.evaluate(skript)
                await b.close()
        finally:
            await runner.cleanup()
        assert not fehler, fehler
        return res
    return asyncio.run(lauf())


def test_verlauf_als_split_haelfte():
    res = _im_konfigurator("""async () => {
        cur = 'test'; const p = PANELS[cur]; p.ui = p.ui || {};
        document.body.insertAdjacentHTML('beforeend', '<div id="paneField"><div id="panePerTab"></div></div>');
        renderPanes(p);
        const sel = document.querySelector('select[data-pane="favoriten"]');
        const arten = [...sel.options].map(o => o.value);
        sel.value = 'chart'; sel.onchange();
        const sub = document.querySelector('select[data-panev="favoriten"]');
        const auswahl = [...sub.options].map(o => o.textContent);
        sub.value = 'P'; sub.onchange();
        return {arten, auswahl, panes: JSON.parse(JSON.stringify(p.ui.panes))}; }""")
    assert "chart" in res["arten"]
    # nur Bausteine mit Aufzeichnung, sortiert nach Raum, dann Name
    assert res["auswahl"] == ["PV Anlage (Technikraum)", "Stromzähler (Technikraum)", "Regen (Zentral)",
                              "Temp. Boiler (Zentral)"]
    assert res["panes"] == {"favoriten": "chart:P"}
    gespeichert = W.App._sanitize_panels({"t": {"title": "T", "tabs": ["favoriten"], "ui": {"panes": res["panes"]}}})
    assert gespeichert["t"]["ui"]["panes"] == {"favoriten": "chart:P"}


def test_kachel_verlauf_stil_und_zeitraum():
    res = _im_konfigurator("""async () => {
        cur = 'test'; const p = PANELS[cur];
        document.body.insertAdjacentHTML('beforeend', '<div id="tileEditor"></div>');
        const opts = id => { const s = document.getElementById(id); return s ? [...s.options].map(o => o.value) : null; };
        const wahl = (id, v) => { const s = document.getElementById(id); s.value = v; s.onchange(); };
        const stand = () => JSON.parse(JSON.stringify((p.tiles || {})[tileSel] || null));
        const out = {stile: {}, schritte: {}};
        for (const u of ['T', 'Z', 'R', 'P', 'X']) { tileSel = u; renderTileEditor(); out.stile[u] = opts('tChartStyle'); }
        tileSel = 'T'; renderTileEditor();
        const schritt = name => out.schritte[name] = {ov: stand(), zeitraum: opts('tChartRange') &&
                                                       document.getElementById('tChartRange').value};
        wahl('tChartStyle', 'trend'); schritt('trend');
        wahl('tChartRange', '7d'); schritt('trend 7d');
        wahl('tChartStyle', 'pattern'); schritt('muster');
        wahl('tChartStyle', 'span'); schritt('spanne');
        wahl('tChartStyle', 'trend'); schritt('zurueck');
        wahl('tChartStyle', ''); schritt('aus');
        tileSel = 'Z'; renderTileEditor(); wahl('tChartStyle', 'pattern');
        out.tiles = JSON.parse(JSON.stringify(p.tiles || {}));
        return out; }""")
    alle = ["", "trend", "pattern", "span"]
    assert res["stile"] == {"T": alle, "P": alle, "Z": alle[:3], "R": alle[:3], "X": None}   # Spanne nur fuer Messwerte
    s = res["schritte"]
    assert s["trend"] == {"ov": {"chart": "24h"}, "zeitraum": "24h"}
    assert s["trend 7d"]["ov"] == {"chart": "7d"}
    assert s["muster"] == {"ov": {"chart": "7d", "chartStyle": "pattern"}, "zeitraum": None}
    assert s["spanne"]["ov"] == {"chart": "7d", "chartStyle": "span"}
    assert s["zurueck"] == {"ov": {"chart": "7d"}, "zeitraum": "7d"}, "Zeitraum bleibt beim Stilwechsel"
    assert s["aus"]["ov"] is None
    gespeichert = W.App._sanitize_panels({"t": {"title": "T", "tabs": ["favoriten"], "tiles": res["tiles"]}})
    assert gespeichert["t"]["tiles"] == res["tiles"] == {"Z": {"chart": "24h", "chartStyle": "pattern"}}


def test_sicherung_herunterladen(tmp_path):
    async def klick(pg):
        await pg.locator(".rub", has_text="Settings").click()
        await pg.locator(".stab", has_text="Sicherung").click()
        await pg.screenshot(path=str(tmp_path / "sicherung.png"))
        async with pg.expect_download() as dl:
            await pg.locator("#bk_dl").click()
        d = await dl.value
        ziel = tmp_path / d.suggested_filename
        await d.save_as(ziel)
        return str(ziel)
    datei = _im_konfigurator(klick)
    assert datei.endswith(".zip") and "loxpanel-einstellungen-" in datei
    with zipfile.ZipFile(datei) as z:
        assert "LIESMICH.txt" in z.namelist()
