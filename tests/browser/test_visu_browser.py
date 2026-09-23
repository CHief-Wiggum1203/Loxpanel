"""Visu in Chromium gegen den echten Server (index, /ws, Broadcaster) und den
Miniserver-Nachbau. Screenshots landen im tmp_path des Tests (in der CI als
Artefakt hochgeladen)."""
import asyncio
from datetime import datetime

import pytest

from lox import Miniserver, W, anlage, neue_app, pv_leistung, v1_bausteine, visu_starten, zaehlerstand

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

PV_GRUPPEN = [{"id": "1", "mode": 10, "dataPoints": [{"title": "Leistung", "format": "0,000kW", "output": "actual"}]},
              {"id": "2", "mode": 11, "accumulated": True,
               "dataPoints": [{"title": "Zählerstand", "format": "0,0kWh", "output": "total"}]}]


def _bausteine(ms: Miniserver) -> dict:
    """V1-Bausteine (Boiler, Stromzaehler, Regen) plus PV (statisticV2) und ein
    Schalter, alle als Favoriten in zwei Raeumen."""
    c = v1_bausteine(ms, datetime.now().replace(second=0, microsecond=0))
    c.pop("X")
    ms.v2 = {("PV", "1", "actual"): (1800, pv_leistung), ("PV", "2", "total"): (3600, zaehlerstand(pv_leistung))}
    c["P"] = {"name": "PV Anlage", "type": "Meter", "uuidAction": "PV", "states": {"actual": "a1", "total": "t1"},
              "details": {"actualFormat": "%.3fkW", "totalFormat": "%.1fkWh"}, "statisticV2": {"groups": PV_GRUPPEN}}
    c["L"] = {"name": "Licht", "type": "Switch", "uuidAction": "LA", "states": {"active": "sl"}}
    for i, v in enumerate(c.values()):
        v.update(room="r1" if i % 2 == 0 else "r2", cat="c1", isFavorite=True)
    return c


class Umgebung:
    """Nachbau + Server + Chromium fuer einen Test; sammelt JS-Fehler."""

    def __init__(self, tmp_path, panel: dict):
        self.tmp_path, self.panel, self.fehler = tmp_path, panel, []

    async def __aenter__(self):
        self.ms = await Miniserver().start()
        self.app = neue_app(self.ms)
        self.controls = _bausteine(self.ms)
        self.app._apply_structure(anlage(self.controls))
        self.app.states = {"sv": 57.3, "sa": 0.6, "st": 10000.0, "sr": 0, "a1": 4.2, "t1": 9100.0, "sl": 0}
        self.app.panels = W.App._sanitize_panels({"test": dict(self.panel, title="Test", tabs=["favoriten"])})
        self.runner, self.port, self.bc = await visu_starten(self.app)
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch()
        return self

    async def seite(self, breite, hoehe):
        pg = await self.browser.new_page(viewport={"width": breite, "height": hoehe})
        pg.on("pageerror", lambda e: self.fehler.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text
              and self.fehler.append(m.text))
        await pg.goto(f"http://127.0.0.1:{self.port}/?panel=test")
        await pg.wait_for_timeout(600)
        await pg.evaluate("wake()")
        await pg.wait_for_timeout(1800)
        return pg

    async def bild(self, pg, name):
        await pg.screenshot(path=str(self.tmp_path / f"{name}.png"))

    async def __aexit__(self, *exc):
        await self.browser.close()
        await self.pw.stop()
        self.bc.cancel()
        await self.app.icon_session.close()
        await self.runner.cleanup()
        await self.ms.stop()


def test_detailseite_diagramme(tmp_path, miniserver_http):
    async def lauf():
        async with Umgebung(tmp_path, {}) as u:
            pg = await u.seite(480, 480)
            for cid in ("T", "Z", "R", "P"):
                await pg.evaluate(f"nav({{view:'control',id:'{cid}'}})")
                await pg.wait_for_timeout(1800)
                info = await pg.evaluate("""() => ({charts: document.querySelectorAll('.chart').length,
                    svgs: document.querySelectorAll('.chart svg').length,
                    msgs: [...document.querySelectorAll('.chmsg')].map(e => e.textContent)})""")
                assert info["charts"] >= 1 and info["svgs"] == info["charts"] and not info["msgs"], (cid, info)
                await u.bild(pg, f"detail_{cid}")
                if cid == "Z":
                    tiefe = await pg.evaluate("stack.length")
                    await pg.locator(".chip", has_text="7 Tage").dispatch_event("pointerdown")
                    await pg.wait_for_timeout(1500)
                    nach = await pg.evaluate("""() => ({tiefe: stack.length, range: stack[stack.length-1].range,
                        an: [...document.querySelectorAll('.chip.on')].map(c => c.textContent)})""")
                    assert nach == {"tiefe": tiefe, "range": "7d", "an": ["7 Tage"]}, nach
                await pg.evaluate("back()")
                await pg.wait_for_timeout(300)
            assert not u.fehler, u.fehler
    asyncio.run(lauf())


def test_split_haelfte_und_kachel(tmp_path, miniserver_http):
    panel = {"ui": {"panes": {"favoriten": "chart:P"}},
             "tiles": {"T": {"chart": "24h"}, "P": {"chart": "7d"}, "R": {"chart": "quatsch"}}}

    async def lauf():
        async with Umgebung(tmp_path, panel) as u:
            pg = await u.seite(960, 480)
            info = await pg.evaluate("""() => ({split: document.querySelector('.screen').classList.contains('split'),
                name: (document.querySelector('#frontpane .cpname') || {}).textContent,
                diagramme: document.querySelectorAll('#frontpane .chart svg').length,
                kacheln: Object.fromEntries([...document.querySelectorAll('.tile')].map(t =>
                    [t.querySelector('.name').textContent, !!t.querySelector('.tspark svg')]))})""")
            assert info["split"] and info["name"] == "PV Anlage" and info["diagramme"] == 2, info
            assert info["kacheln"] == {"Boiler": True, "Stromzähler": False, "Regen": False,
                                       "PV Anlage": True, "Licht": False}, info["kacheln"]
            await u.bild(pg, "split_24h")
            await pg.locator("#frontpane .chip", has_text="7 Tage").dispatch_event("pointerdown")
            await pg.wait_for_timeout(1500)
            assert list(u.app.conn_chart.values()) == [("P", "7d")]
            assert await pg.evaluate("stack.length") == 1, "Zeitraum wechselt ohne Navigation"
            await u.bild(pg, "split_7d")
            await pg.close()
            await asyncio.sleep(0.3)
            assert not u.app.conn_chart, "Anmeldung der Pane endet mit der Verbindung"
            assert not u.fehler, u.fehler
    asyncio.run(lauf())


def test_kachel_stile_je_kachelgroesse(tmp_path, miniserver_http):
    """Der Mini-Verlauf passt sich der Kachel an (Querformat ohne rechte Haelfte
    verdoppelt die Spalten, 3 -> 6):
    mitte   genug Hoehe: Verlauf in der Kachelmitte
    kopf    niedrig, aber breit: Verlauf in der Kopfzeile neben dem Icon
    keiner  niedrig und schmal (18 Kacheln auf 800 x 480): kein Platz fuer einen
            Verlauf, die Angabe bleibt in der Raumzeile lesbar"""
    faelle = [(1280, 800, 3, "mitte"), (800, 480, 2, "mitte"), (1280, 480, 3, "kopf"), (800, 480, 3, "keiner")]
    tiles = {"T": {"chart": "24h", "chartStyle": "span"}, "Z": {"chart": "24h", "chartStyle": "pattern"},
             "R": {"chart": "7d"}, "P": {"chart": "24h"}}

    async def lauf():
        async with Umgebung(tmp_path, {}) as u:
            for breite, hoehe, zeilen, ort in faelle:
                u.app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"],
                                                                "ui": {"cols": 3, "rows": zeilen}, "tiles": tiles}})
                pg = await u.seite(breite, hoehe)
                info = await pg.evaluate("""() => [...document.querySelectorAll('.tile')].map(t => ({
                    name: t.querySelector('.name').textContent, svg: !!t.querySelector('.tspark svg'),
                    rects: t.querySelectorAll('.tspark rect').length, eng: t.classList.contains('sparktight'),
                    hoehe: (t.querySelector('.tspark svg') || {}).clientHeight || 0,
                    zeile: [...t.querySelectorAll('.room')].filter(e => getComputedStyle(e).display !== 'none')
                             .map(e => e.textContent).join('|'),
                    angabe: (t.querySelector('.tsbadge') || {}).textContent || '',
                    kopf: (b => !!b && getComputedStyle(b).display !== 'none' && b.scrollWidth <= b.clientWidth + 1)
                          (t.querySelector('.tsbadge')),
                    abgeschnitten: t.querySelector('.sub') ? t.querySelector('.sub').getBoundingClientRect().bottom
                                   > t.getBoundingClientRect().bottom - 8 : false}))""")
                await u.bild(pg, f"stile_{breite}x{hoehe}_{zeilen}zeilen")
                k = {i["name"]: i for i in info}
                mit = [k[n] for n in ("Boiler", "Stromzähler", "Regen", "PV Anlage")]
                fall = f"{breite}x{hoehe}, {zeilen} Zeilen"
                assert not k["Licht"]["svg"] and not any(i["abgeschnitten"] for i in info), (fall, info)
                assert all(i["eng"] == (ort != "mitte") for i in mit), (fall, info)
                if ort == "keiner":
                    assert not any(i["svg"] for i in mit), (fall, info)
                else:
                    assert all(i["svg"] and i["hoehe"] >= 30 for i in mit), (fall, info)
                    assert k["Boiler"]["rects"] == 7, "Tagesspanne: 7 Balken"
                    assert k["Stromzähler"]["rects"] >= 168, "Tagesmuster: 7 x 24 Zellen"
                # Angabe immer da: im Kopf nur vollstaendig, sonst in der Raumzeile
                for i in mit:
                    assert i["angabe"] and (i["kopf"] or i["zeile"] == i["angabe"]), (fall, i)
                    assert not (i["eng"] and i["kopf"]), "enge Kachel: der Kopf gehoert dem Verlauf"
                ueberlappt = await pg.evaluate("""() => [...document.querySelectorAll('.tile .tspark svg')].flatMap(svg => {
                    const r = [...svg.querySelectorAll('text')].map(e => [e.textContent, e.getBoundingClientRect()])
                        .sort((a, b) => a[1].left - b[1].left);
                    return r.slice(1).filter((x, i) => Math.abs(x[1].top - r[i][1].top) < 2 && x[1].left < r[i][1].right - 0.5)
                        .map((x, i) => r[i][0] + '/' + x[0]); })""")
                assert not ueberlappt, f"{fall}: Beschriftungen ueberlappen {ueberlappt}"
                # Live-Aenderung: an Ort und Stelle neu gezeichnet, Darstellung bleibt
                u.app.states["sv"] += 0.8
                u.app.stat_gen += 1
                u.app._dirty = True
                await pg.wait_for_timeout(1500)
                nachher = await pg.evaluate("document.querySelectorAll('.tile .tspark svg').length")
                assert nachher == sum(i["svg"] for i in mit), fall
                await pg.close()
            assert not u.fehler, u.fehler
    asyncio.run(lauf())


def test_befehl_bedienung(tmp_path, miniserver_http):
    async def lauf():
        async with Umgebung(tmp_path, {}) as u:
            pg = await u.seite(800, 480)
            await pg.evaluate("ws.onmessage({data:'{kaputt'}); ws.onmessage({data:'null'}); ws.onmessage({data:'42'})")
            licht = pg.locator(".tile", has_text="Licht")
            u.ms.token = "ABGELAUFEN"
            u.app._auth_at -= W.TOKEN_RENEW_MIN
            await licht.click()
            await pg.wait_for_timeout(1000)
            assert u.ms.io == ["sps/io/LA/on"] and u.app.client.n == 1
            assert await pg.locator(".lpnotify").count() == 0, "nach Token-Ablauf geht der Befehl ohne Hinweis durch"
            u.ms.reject = True
            await licht.click()
            await pg.wait_for_timeout(800)
            assert await pg.locator(".lpnotify").text_content() == "Befehl nicht ausgeführt (Miniserver meldet 500)"
            await u.bild(pg, "hinweis")
            assert not u.fehler, u.fehler
    asyncio.run(lauf())
