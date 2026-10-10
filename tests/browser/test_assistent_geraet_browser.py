"""Assistent Schritt 1 aus dem Geraet (Punkt 9) in Chromium: Visu und
Konfigurator rechnen das Raster mit derselben raster.js. Die Masse, mit denen
der Konfigurator ein Geraet vorrechnet (LoxRaster.VISU_MASSE), sind die, die
die Visu misst; die Vorrechnung im Assistenten ergibt auf den Standardgeraeten
das Raster, das die Visu dort baut. Der Assistent bietet Geraete mit
gemeldeter Groesse, diesen Browser und den Katalog des Servers an, zeigt nur
passende Anzeigen, jede vorgerechnet, und schaltet zum Schluss das Geraet um
und merkt sich dort die Zielkachel. Dazu der Fehler, den das aufgedeckt hat:
die Zielkachel je Geraet unter Displays ging beim Speichern verloren."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

KACHELN = {f"S{i}": {"name": f"Licht {i}", "type": "Switch", "uuidAction": f"S{i}", "room": "r2", "cat": "c1",
                     "isFavorite": True, "states": {"active": f"s{i}"}} for i in range(12)}
STATES = {f"s{i}": 0 for i in range(12)}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/devices", W.api_save_devices),
          ("POST", "/api/panels", W.api_save_panels), ("POST", "/api/theme", W.api_save_theme),
          ("POST", "/api/device/switch", W.api_device_switch)]
# Standardgeraete der Messreihe; die Profile: automatisch mit 1 und mit 2
# Panes (Widget je Tab), fest 3 x 3 mit Split und 2 x 2 ohne
GERAETE = {"taba9-quer": (893, 533), "taba9-hoch": (533, 893), "zehn-quer": (1280, 800),
           "ipad-quer": (1024, 768), "4zoll": (480, 480)}
PROFILE = {"auto1": ({"grid": "auto", "split": False}, "1", "auto"),
           "auto2": ({"grid": "auto", "panes": {"favoriten": "weather"}}, "2", "auto"),
           "fest33": ({"cols": 3, "rows": 3}, "2", "3x3"),
           "fest22": ({"cols": 2, "rows": 2, "split": False}, "1", "2x2")}
MESSEN = """() => { const g = document.getElementById('grid'), cs = getComputedStyle(g);
  return {raster: [gridCols, gridRows], kachel: Math.round(g.querySelector('.tile[data-id]').getBoundingClientRect().width),
          masse: {gap: parseFloat(cs.getPropertyValue('--gap')), pad: parseFloat(cs.getPropertyValue('--pad')),
                  punkteH: parseFloat(cs.getPropertyValue('--punkte-h')), tabsH: document.getElementById('tabs').offsetHeight},
          vorgabe: LoxRaster.VISU_MASSE}; }"""


async def _bis(bedingung, was, sekunden=10):
    for _ in range(int(sekunden * 20)):
        if bedingung():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"nicht erreicht: {was}")


def _app(cfg_ordner, panels, devices=None):
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": panels, **({"devices": devices} if devices else {})}),
                                            encoding="utf-8")
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(KACHELN))
    app.states = dict(STATES)
    app.panels = W.load_panels()
    return app


def test_vorrechnung_wie_die_visu(cfg_ordner, monkeypatch):
    """Ohne Wachsen und Schrumpfen (KACHEL_WACHSEN 1, die Vorrechnung kennt die
    Kacheln der Seite noch nicht) baut die Visu auf jedem Standardgeraet und
    in jedem Profil genau das Raster, das der Assistent fuer dieses Geraet
    vorrechnet; im automatischen Raster auch die Kachelbreite. Die Masse der
    Visu sind die von raster.js."""
    monkeypatch.setattr(W, "KACHEL_WACHSEN", 1)
    app = _app(cfg_ordner, {pid: {"title": pid, "tabs": ["favoriten"], "ui": ui} for pid, (ui, _, _) in PROFILE.items()})

    async def lauf():
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler, ungleich = [], []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                konf = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                konf.on("pageerror", lambda e: fehler.append(str(e)))
                await konf.goto(f"http://127.0.0.1:{port}/config")
                await konf.wait_for_function(KONFIGURATOR_GELADEN)
                for geraet, (w, h) in GERAETE.items():
                    v = await b.new_page(viewport={"width": w, "height": h})
                    v.on("pageerror", lambda e: fehler.append(str(e)))
                    for pid, (_, panes, grid) in PROFILE.items():
                        await v.goto(f"http://127.0.0.1:{port}/?panel={pid}")
                        await v.wait_for_selector("#grid .tile[data-id]", state="attached")
                        if await v.locator("#saver:not(.hidden)").count():
                            await v.click("#saver")
                        await v.wait_for_timeout(300)
                        ist = await v.evaluate(MESSEN)
                        assert ist["masse"] == ist["vorgabe"], (geraet, pid, ist)
                        vor = await konf.evaluate(f"""() => {{ WZ.device = ''; WZ.groesse = {{quelle: 'katalog', name: 'x', vw: {w}, vh: {h}}};
                            return wzVorrechnung('{panes}', '{grid}'); }}""")
                        soll = vor["mit"] if vor.get("mit") else [vor["cols"], vor["rows"]]
                        # Kachelbreite: die Vorrechnung nennt die der Seite ohne Widget (neben einem
                        # zieht dessen Trennlinie 1 bis 2 px ab), verglichen wird sie dort
                        if ist["raster"] != soll or (vor.get("auto") and not vor.get("widget") and abs(ist["kachel"] - vor["px"]) > 1):
                            ungleich.append((geraet, pid, ist["raster"], ist["kachel"], vor))
                    await v.close()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        assert not ungleich, ungleich
    asyncio.run(lauf())


STAND = """() => ({schritt: wzFlow()[WZ.step], panes: WZ.panes, grid: WZ.grid, device: WZ.device,
  groesse: WZ.groesse && [WZ.groesse.quelle, WZ.groesse.vw, WZ.groesse.vh],
  geraete: [...document.querySelectorAll('#wzBody [data-wgr]')].map(n => n.innerText.replace(/\\s+/g, ' ').trim()),
  panesAngebot: [...document.querySelectorAll('#wzBody [data-wk="panes"]')].map(n => n.dataset.wo),
  raster: Object.fromEntries([...document.querySelectorAll('#wzBody [data-wg]')].map(n =>
    [n.dataset.wg, (n.querySelector('.wzv') || {}).textContent || ''])),
  katalog: [...document.querySelectorAll('#wzKatalog option')].slice(1).map(o => o.textContent)})"""


def test_assistent_aus_dem_geraet(cfg_ordner, tmp_path):
    app = _app(cfg_ordner, {})

    async def lauf():
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                tablet = await b.new_page(viewport={"width": 893, "height": 533})
                wand = await b.new_page(viewport={"width": 480, "height": 480})
                for v, name in ((tablet, "tablet"), (wand, "wand")):
                    v.on("pageerror", lambda e: fehler.append(str(e)))
                    await v.goto(f"http://127.0.0.1:{port}/?device={name}")
                await _bis(lambda: len(app.conn_info) == 2 and all(i.get("screen") for i in app.conn_info.values()),
                           "zwei Geraete mit gemeldeter Groesse")
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.wait_for_function("KNOWN_NAMES.length >= 2 && DEVICE_SCREENS.tablet && DEVICE_SCREENS.wand")
                await pg.locator("#addBtn").click()
                await pg.wait_for_selector("#wzOv:not([hidden])")

                # Ohne Geraet: alles angeboten, nichts vorgerechnet; dazu Geraete, Browser, Katalog
                st = await pg.evaluate(STAND)
                assert st["geraete"] == ["tablet 893 × 533 · gemeldet", "wand 480 × 480 · gemeldet", "Dieser Browser 1280 × 900"], st
                assert st["katalog"] == [f"{k['name']} · {k['vw']} × {k['vh']}" for k in W.GERAETE_KATALOG], st
                assert st["panesAngebot"] == ["1", "2"] and set(st["raster"]) == {"2x2", "3x2", "2x3", "3x3", "auto"} \
                    and not any(st["raster"].values()), st

                # Das 4"-Wandpanel: quadratisch, also nur 1 Pane; vorgerechnet, 2 x 2 vorgeschlagen
                await pg.locator('#wzBody [data-wgr="geraet"][data-wgn="wand"]').click()
                st = await pg.evaluate(STAND)
                assert (st["device"], st["groesse"], st["panesAngebot"], st["panes"], st["grid"]) == (
                    "wand", ["geraet", 480, 480], ["1"], "1", "2x2"), st
                assert st["raster"]["2x2"] == "2 × 2" and st["raster"]["3x3"] == "3 × 3", st

                # 10"-Tablet aus dem Katalog: mit 2 Panes passen nur 3 x 3 (6 x 3 Kacheln) und "Automatisch"
                await pg.locator("#wzKatalog").select_option(label="10″-Tablet quer · 1280 × 800")
                st = await pg.evaluate(STAND)
                assert (st["device"], st["groesse"], st["panes"], st["grid"]) == ("", ["katalog", 1280, 800], "2", "auto"), st
                assert st["raster"] == {"3x3": "6 × 3", "auto": st["raster"]["auto"]}, st
                await pg.screenshot(path=str(tmp_path / "assistent_geraet_katalog.png"))

                # Das Tablet: 2 Panes, automatisch 5 x 3 zu 167 px, Widget 2 Spalten
                await pg.locator('#wzBody [data-wgr="geraet"][data-wgn="tablet"]').click()
                st = await pg.evaluate(STAND)
                assert (st["device"], st["panes"], st["grid"]) == ("tablet", "2", "auto"), st
                assert st["raster"]["auto"] == "5 × 3 · 167 px + Widget 2 Spalten", st

                # Im Schritt Name: umschalten und Zielkachel merken, dann sofort anlegen
                await pg.evaluate("WZ.content = 'classic'; WZ.step = wzFlow().indexOf('name'); wzRender()")
                assert await pg.locator("#wzUmschalten").is_checked() and await pg.locator("#wzZielMerken").is_checked()
                await pg.locator("#wzTitleI").fill("Flur")
                await pg.locator("#wzFertig").click()
                await _bis(lambda: any((app.conn_prof.get(ws) or {}).get("id") == "flur" for ws, i in app.conn_info.items()
                                       if i.get("dev") == "tablet"), "das Tablet zeigt das neue Panel", sekunden=20)
                assert "flur" in tablet.url, tablet.url
                datei = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))
                assert datei["panels"]["flur"]["device"] == {"name": "tablet", "vw": 893, "vh": 533}, datei["panels"]["flur"]
                assert datei["devices"]["tablet"]["tileTarget"] == W.KACHEL_ZIEL_STANDARD, datei.get("devices")
                await pg.screenshot(path=str(tmp_path / "assistent_geraet_fertig.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


def test_zielkachel_unter_displays_bleibt_beim_speichern(cfg_ordner):
    """Displays, Feld Zielkachel je Geraet: Speichern behaelt sie (vorher fiel
    sie aus der Nutzlast und ein Geraet nur mit Zielkachel verschwand), ein
    neuer Wert landet in der Datei."""
    app = _app(cfg_ordner, {"p": {"title": "P", "tabs": ["favoriten"]}},
               {"flur": {"auto": True, "modes": {}, "tileTarget": 200}})

    async def lauf():
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
                await pg.locator("summary", has_text="Betriebsmodus-Automatik").click()
                feld = pg.locator('#dev_list .dev[data-name="flur"] .dt_ziel')
                assert await feld.input_value() == "200"

                async def speichern():
                    # Speichern ohne Aenderung gibt die Leiste nicht frei: den Bereich offen melden
                    await pg.evaluate("bereichOffen('geraete')")
                    async with pg.expect_response(lambda r: r.url.endswith("/api/devices") and r.request.method == "POST") as a:
                        await pg.locator("#saveBtn").click()
                    assert (await (await a.value).json())["ok"]
                    return json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8")).get("devices", {})
                assert (await speichern()).get("flur", {}).get("tileTarget") == 200, "unveraendert gespeichert: bleibt"
                await feld.fill("250")
                assert (await speichern())["flur"]["tileTarget"] == 250
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
