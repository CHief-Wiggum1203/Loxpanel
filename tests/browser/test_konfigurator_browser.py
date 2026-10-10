"""Konfigurator (config.html) in Chromium: Verlauf als Split-Haelfte und als
Mini-Verlauf der Kachel einstellen; was der Server beim Speichern behaelt."""
import asyncio
import json
import zipfile

import pytest

from aiohttp import web

from lox import KONFIGURATOR_GELADEN, W, anlage, raum_anlage, serve

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


def _im_konfigurator(skript: str, struktur: dict | None = None, panels: dict | None = None):
    """config.html laden, skript darin ausfuehren -> Ergebnis. skript ist eine
    async JS-Funktion als Text oder eine async Python-Funktion(page). Ohne
    struktur/panels: BAUSTEINE und ein klassisches Panel "test"."""
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(struktur or anlage(BAUSTEINE))
        app.panels = W.App._sanitize_panels(panels or {"test": {"title": "Test", "tabs": ["favoriten", "raeume"]}})
        ui = web.Application()
        ui["app"] = app
        for pfad, h in (("/config", W.config_index), ("/api/meta", W.api_meta), ("/api/backup", W.api_backup),
                        ("/api/settings", W.api_settings), ("/i18n.js", W.i18n_js), ("/raster.js", W.raster_js)):
            ui.router.add_get(pfad, h)
        runner, port = await serve(ui)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                res = await skript(pg) if callable(skript) else await pg.evaluate(skript)
                await b.close()
        finally:
            await runner.cleanup()
        assert not fehler, fehler
        return res
    return asyncio.run(lauf())


def test_verlauf_als_split_haelfte():
    """Verlauf als Pane 2: ein oder mehrere Bausteine mit Aufzeichnung (seit
    Lenardos #77 gestapelt), gewaehlt wie bei den Werten. Die Art waehlt den
    ersten Baustein mit Aufzeichnung vor, weitere kommen ueber "hinzufuegen"
    dazu, ein Tipp auf den Chip nimmt einen heraus."""
    res = _im_konfigurator("""async () => {
        cur = 'test'; const p = PANELS[cur]; p.ui = p.ui || {};
        document.body.insertAdjacentHTML('beforeend', '<div id="paneField"><div id="panePerTab"></div></div>');
        renderPanes(p);
        const sel = document.querySelector('select[data-pane="favoriten"]');
        const arten = [...sel.options].map(o => o.value);
        sel.value = 'chart'; sel.onchange();
        const erst = JSON.parse(JSON.stringify(p.ui.panes));
        const dazu = () => document.querySelector('.pchart-add[data-pk="favoriten"]');
        const auswahl = [...dazu().options].map(o => o.textContent);
        dazu().value = 'R'; dazu().onchange();
        const zwei = JSON.parse(JSON.stringify(p.ui.panes));
        const chips = [...document.querySelectorAll('.chip[data-cu][data-pk="favoriten"]')].map(c => c.dataset.cu);
        document.querySelector('.chip[data-cu="P"][data-pk="favoriten"]').onclick();
        return {arten, erst, auswahl, zwei, chips, panes: JSON.parse(JSON.stringify(p.ui.panes))}; }""")
    assert "chart" in res["arten"]
    assert res["erst"] == {"favoriten": "chart:P"}
    # nur Bausteine mit Aufzeichnung, sortiert nach Raum, dann Name
    assert res["auswahl"] == ["＋ hinzufügen …", "PV Anlage (Technikraum)", "Stromzähler (Technikraum)",
                              "Regen (Zentral)", "Temp. Boiler (Zentral)"]
    assert res["zwei"] == {"favoriten": "chart:P,R"} and res["chips"] == ["P", "R"]
    assert res["panes"] == {"favoriten": "chart:R"}
    gespeichert = W.App._sanitize_panels({"t": {"title": "T", "tabs": ["favoriten"], "ui": {"panes": res["zwei"]}}})
    assert gespeichert["t"]["ui"]["panes"] == {"favoriten": "chart:P,R"}


def test_kachel_verlauf_stil_und_zeitraum():
    res = _im_konfigurator("""async () => {
        cur = 'test'; const p = PANELS[cur];
        document.body.insertAdjacentHTML('beforeend', '<div id="tileEditor"></div>');
        const opts = id => { const s = document.getElementById(id); return s ? [...s.options].map(o => o.value) : null; };
        const wahl = (id, v) => { const s = document.getElementById(id); s.value = v; s.onchange(); };
        const stand = () => JSON.parse(JSON.stringify((p.tiles || {})[tileSel] || null));
        const out = {stile: {}, schritte: {}};
        for (const u of ['T', 'Z', 'R', 'P', 'X']) { tileSel = u; renderTileEditor(); out.stile[u] = opts('tChartStyle'); }
        out.hinweise = {};
        for (const u of ['T', 'Z', 'R']) {
            tileSel = u; renderTileEditor(); wahl('tChartStyle', 'trend');
            const art = (META.controls.find(c => c.uuid === u) || {}).statKind;
            out.hinweise[u] = [art, document.querySelector('#tileEditor .hint').textContent];
            wahl('tChartStyle', ''); }
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
    # der Hinweis zum Trend sagt, was die Kachel bei dieser Art zeichnet
    trend = {"line": "Kurve mit Tief, Hoch und Änderung", "counter": "Verbrauch als Balken, dazu die Summe",
             "digital": "Ein/Aus als Stufen, dazu die Einschaltdauer"}
    assert {a for a, _ in res["hinweise"].values()} == set(trend), res["hinweise"]
    assert all(h == trend[a] for a, h in res["hinweise"].values()), res["hinweise"]
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
        await pg.locator(".rub", has_text="Einstellungen").click()
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


def test_sprungmarken_springen_oder_filtern():
    """Die Wahl Springen/Filtern gibt es nur bei einer Leiste aus Sprungmarken
    (Raum-Panel, eine freie Seite). Editor und Assistent speichern sie als
    ui.catFilter, der Server behaelt sie."""
    res = _im_konfigurator("""async () => {
        cur = 'test'; const p = PANELS[cur]; p.tabs = ['room:r1']; renderEditor();
        const sel = document.getElementById('fCatFilter');
        const feld = !!sel;
        sel.value = '1'; sel.onchange({target: sel});
        const an = !!(p.ui && p.ui.catFilter);
        sel.value = ''; sel.onchange({target: sel});
        const aus = !(p.ui && 'catFilter' in p.ui);
        p.tabs = ['favoriten', 'raeume']; renderEditor();
        const klassisch = !!document.getElementById('fCatFilter');
        p.tabs = ['room:r1']; p.ui.catFilter = true; renderEditor();
        const bleibt = document.getElementById('fCatFilter').value === '1';
        wzOpen(); WZ.panes = '1'; WZ.content = 'room'; WZ.title = 'Sauna'; WZ.id = 'sauna'; wzInitSetup();
        WZ.step = wzFlow().indexOf('inhalt'); wzRender();
        const knopf = document.querySelector('#wzBody [data-wk="catMode"][data-wo="filter"]');
        const wahl = !!knopf; knopf.click();
        WZ.step = wzFlow().indexOf('pruefen'); wzRender();
        const zusammenfassung = document.getElementById('wzBody').innerText.includes('Filtern');
        wzBuild();
        return {feld, an, aus, klassisch, bleibt, wahl, zusammenfassung,
                panel: JSON.parse(JSON.stringify(PANELS['sauna']))}; }""")
    panel = res.pop("panel")
    assert res == {"feld": True, "an": True, "aus": True, "klassisch": False, "bleibt": True,
                   "wahl": True, "zusammenfassung": True}, res
    assert panel["ui"]["catFilter"] is True and len(panel["tabs"]) == 1 and panel["tabs"][0].startswith("room:")
    assert W.App._sanitize_panels({"sauna": panel})["sauna"]["ui"]["catFilter"] is True


def test_raum_panel_kategorie_tabs_im_editor():
    """Die gewaehlten Kategorie-Tabs eines Raum-Panels (roomCats) kommen im
    Editor an: ihre Chips sind an, "Automatisch" ist zu sehen - vorher zeigte
    er die ersten vier und das naechste Speichern loeschte die Wahl. Sie gilt
    nur im Raum-Modus: ein Moduswechsel setzt sie zurueck wie ein Raumwechsel,
    sonst bliebe sie unsichtbar stehen und ordnete einen Raum-Tab der
    klassischen Leiste."""
    struktur, _ = raum_anlage()
    res = _im_konfigurator("""async () => {
        cur = 'sauna'; renderEditor(); const p = PANELS.sauna;
        const geladen = p.roomCats ?? null;
        const chips = [...document.querySelectorAll('#tabRoomCats .chip.on')].map(n => n.dataset.rc);
        const automatisch = document.getElementById('tabRoomAuto').style.visibility;
        document.querySelector('#tabMode button[data-mode="classic"]').click();
        return {geladen, chips, automatisch, klassisch: p.roomCats ?? null, tabs: p.tabs}; }""",
        struktur, {"sauna": {"title": "Sauna", "tabs": ["room:r1"], "roomCats": ["c4", "c2"]}})
    tabs = res.pop("tabs")
    assert res == {"geladen": ["c4", "c2"], "chips": ["c2", "c4"], "automatisch": "visible", "klassisch": None}
    assert tabs and not any(t.startswith("room:") for t in tabs), "Wechsel auf die klassische Leiste"


def test_betriebsmodus_assistent_ausweg_und_benennen():
    """Der Betriebsmodus-Assistent laesst sich per ✕ und Esc schliessen - vorher
    nur per Klick neben das Fenster, und in Schritt 1 waren Zurueck und (ohne
    bekanntes Geraet) Weiter gesperrt. Ein verbundenes Geraet ohne Namen wird im
    Assistenten benannt und ist danach gewaehlt. Dasselbe ✕/Esc fuer den
    Assistenten "Neues Panel"."""
    async def ablauf(pg):
        stand = {"name": None, "leer": False}

        async def geraete(route):
            name = stand["name"]
            devs = [{"name": name, "type": "browser", "online": True, "connections": 1, "ip": "192.168.1.148"}] if name else []
            anon = [] if name or stand["leer"] else [{"ip": "192.168.1.148", "kiosk": "", "profile": "test"}]
            await route.fulfill(json={"devices": devs, "anonymous": anon, "profiles": ["test"]})

        async def benennen(route):
            stand["name"] = json.loads(route.request.post_data)["name"]
            await route.fulfill(json={"ok": True})
        await pg.route("**/api/devices", geraete)
        await pg.route("**/api/device/name", benennen)
        offen = """() => !document.getElementById('mzOv').hidden"""
        await pg.locator('.rub[data-rub="displays"]').click()
        await pg.evaluate("pollDevices()")
        await pg.wait_for_timeout(200)
        await pg.locator("#mzOpenBtn").click()
        assert await pg.evaluate(offen)
        assert await pg.locator("#mzBody [data-mzanon]").count() == 1
        assert "Noch kein Gerät bekannt" not in await pg.locator("#mzBody").inner_text()
        await pg.keyboard.press("Escape")
        assert not await pg.evaluate(offen)
        await pg.locator("#mzOpenBtn").click()
        await pg.locator("#mzX").click()
        assert not await pg.evaluate(offen)
        await pg.locator("#mzOpenBtn").click()
        assert await pg.evaluate("document.getElementById('mzNext').disabled")
        await pg.locator("#mzBody .mzname").fill("Sauna")
        await pg.locator("#mzBody [data-mzname]").click()
        await pg.wait_for_timeout(3300)                    # nameDevice fragt nach 2,5 s neu ab
        chips = await pg.evaluate("""() => [...document.querySelectorAll('#mzBody [data-mzdev]')]
            .map(c => c.textContent + (c.classList.contains('on') ? '*' : ''))""")
        assert chips == ["Sauna*"], chips
        assert not await pg.evaluate("document.getElementById('mzNext').disabled")
        await pg.keyboard.press("Escape")
        # Ohne jedes Geraet: der Hinweis nennt ?device=<name> woertlich
        stand.update(name=None, leer=True)
        await pg.evaluate("KNOWN_NAMES=[]; DEV={}; pollDevices()")
        await pg.wait_for_timeout(200)
        await pg.locator("#mzOpenBtn").click()
        assert "?device=<name>" in await pg.locator("#mzBody").inner_text()
        await pg.locator("#mzX").click()
        # Neues Panel: ✕ und Esc
        wz = """() => !document.getElementById('wzOv').hidden"""
        await pg.locator("#addBtn").click()
        assert await pg.evaluate(wz)
        await pg.locator("#wzX").click()
        assert not await pg.evaluate(wz)
        await pg.locator("#addBtn").click()
        await pg.keyboard.press("Escape")
        assert not await pg.evaluate(wz)
    _im_konfigurator(ablauf)
