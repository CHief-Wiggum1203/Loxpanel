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
            assert await pg.evaluate(UEBERLAUF) <= 1, "Diagramme passen in die Pane (Upstream #60)"
            await u.bild(pg, "split_24h")
            await pg.locator("#frontpane .chip", has_text="7 Tage").dispatch_event("pointerdown")
            await pg.wait_for_timeout(1500)
            assert list(u.app.conn_chart.values()) == [(("P",), "7d")]
            assert await pg.evaluate("stack.length") == 1, "Zeitraum wechselt ohne Navigation"
            await u.bild(pg, "split_7d")
            await pg.close()
            await asyncio.sleep(0.3)
            assert not u.app.conn_chart, "Anmeldung der Pane endet mit der Verbindung"
            assert not u.fehler, u.fehler
    asyncio.run(lauf())


LAGE = """() => { const r = id => { const b = document.getElementById(id).getBoundingClientRect();
    return {l: b.left, t: b.top, r: b.right, b: b.bottom, w: b.width, h: b.height}; };
  const s = document.querySelector('.screen'), sb = s.getBoundingClientRect(),
        kt = document.querySelector('#grid .tile'), k = kt && kt.getBoundingClientRect();   // Detailseite: keine Kacheln
  return {hoch: s.classList.contains('hoch'), split: s.classList.contains('split'),
          screen: {w: sb.width, h: sb.height}, grid: r('grid'), pane: r('frontpane'), tabs: r('tabs'),
          kachel: k ? {w: k.width, h: k.height} : null, fenster: {w: innerWidth, h: innerHeight},
          diagramme: document.querySelectorAll('#frontpane .chart svg').length}; }"""

# Wie weit die Diagramme der Verlaufs-Pane unten aus ihrer Seite ragen (px, 0 = alles
# sichtbar). Seit Upstream #60 teilen sie sich die Hoehe, statt abgeschnitten zu werden.
UEBERLAUF = """() => { const p = document.querySelector('#frontpane .fp-page.cpage'); if (!p) return null;
  const unten = p.getBoundingClientRect().bottom;
  return Math.max(0, ...[...p.querySelectorAll('.chart, .chleg')].map(e => e.getBoundingClientRect().bottom - unten)); }"""


@pytest.mark.parametrize("breite, hoehe, fuellen", [(533, 893, False), (533, 893, True), (480, 800, False),
                                                     (893, 533, False)],
                         ids=["tablet_hoch", "tablet_hoch_fuellen", "schmal_hoch", "tablet_quer"])
def test_split_hochkant_uebereinander(tmp_path, miniserver_http, breite, hoehe, fuellen):
    """Hochkant liegen Visu und Pane 2 uebereinander (Visu oben, Pane darunter,
    Tab-Leiste unten ueber die volle Breite) statt als zwei schmale Streifen
    nebeneinander. Quer bleibt es nebeneinander wie bisher."""
    panel = {"ui": {"panes": {"favoriten": "chart:P"}, "scale": "auto", **({"fill": True} if fuellen else {})}}

    async def lauf():
        async with Umgebung(tmp_path, panel) as u:
            pg = await u.seite(breite, hoehe)
            m = await pg.evaluate(LAGE)
            await u.bild(pg, f"split_{breite}x{hoehe}{'_fuellen' if fuellen else ''}")
            assert m["split"] and m["diagramme"] == 2, m
            assert await pg.evaluate(UEBERLAUF) <= 1, "Diagramme passen in die Pane (Upstream #60)"
            g, p, t = m["grid"], m["pane"], m["tabs"]
            if hoehe > breite:
                assert m["hoch"], m
                assert p["t"] >= g["b"] - 1 and abs(p["l"] - g["l"]) <= 1 and abs(p["w"] - g["w"]) <= 1, m
                assert t["t"] >= p["b"] - 1 and abs(t["w"] - m["screen"]["w"]) <= 1, m
                assert abs(m["screen"]["h"] - hoehe) <= 1, "hochkant nutzt die volle Hoehe"
                if fuellen:
                    assert abs(m["screen"]["w"] - breite) <= 1, "Bildschirm fuellen nutzt die volle Breite"
                # zwei Kacheln je Zeile ueber die volle Breite, nicht gequetscht
                assert m["kachel"]["w"] >= 0.4 * m["screen"]["w"] and m["kachel"]["w"] >= 0.9 * m["kachel"]["h"], m
            else:
                assert not m["hoch"] and p["l"] >= g["r"] - 1, m
            assert not u.fehler, u.fehler
    asyncio.run(lauf())


def test_split_dreht_mit(tmp_path, miniserver_http):
    """Drehen im Betrieb stellt die Haelften um, auch auf einer Detailseite; die
    Anmeldung der Verlaufs-Pane beim Server bleibt dabei bestehen."""
    async def lauf():
        async with Umgebung(tmp_path, {"ui": {"panes": {"favoriten": "chart:P"}}}) as u:
            pg = await u.seite(533, 893)
            for b, h in [(893, 533), (533, 893)]:
                await pg.set_viewport_size({"width": b, "height": h})
                await pg.wait_for_timeout(400)
                m = await pg.evaluate(LAGE)
                assert m["hoch"] == (h > b), m
                assert (m["pane"]["t"] >= m["grid"]["b"] - 1) == (h > b), m
            await pg.locator("#grid .tile").first.click()
            await pg.wait_for_timeout(600)
            assert await pg.evaluate("stack.length") == 2
            await pg.set_viewport_size({"width": 893, "height": 533})
            await pg.wait_for_timeout(400)
            assert not (await pg.evaluate(LAGE))["hoch"]
            await pg.set_viewport_size({"width": 533, "height": 893})
            await pg.wait_for_timeout(400)
            m = await pg.evaluate(LAGE)
            assert m["hoch"] and m["pane"]["t"] >= m["grid"]["b"] - 1, m
            assert await pg.evaluate("stack.length") == 2, "Drehen navigiert nicht"
            assert list(u.app.conn_chart.values()) == [(("P",), "24h")]
            await u.bild(pg, "split_detail_hoch")
            assert not u.fehler, u.fehler
    asyncio.run(lauf())


RASTER = """() => { const s = document.querySelector('.screen').getBoundingClientRect(),
    k = document.querySelector('#grid .tile').getBoundingClientRect(), cs = getComputedStyle(document.documentElement);
  return {raster: cs.getPropertyValue('--cols').trim() + 'x' + cs.getPropertyValue('--rows').trim(),
          screen: {w: s.width, h: s.height}, kachel: {w: k.width, h: k.height}}; }"""


@pytest.mark.parametrize("breite, hoehe, ui, raster", [
    (533, 893, {}, "2x4"), (533, 893, {"fill": True}, "2x4"), (533, 893, {"cols": 3}, "3x4"),
    (533, 893, {"rows": 3}, "2x3"), (533, 893, {"split": False}, "2x2"),
    (480, 480, {}, "2x2"), (893, 533, {}, "4x2")],
    ids=["hoch_2x2", "hoch_2x2_fuellen", "hoch_3x2", "hoch_2x3_bleibt", "hoch_split_aus", "quadrat", "quer"])
def test_screen_fuellen_hochkant_nach_unten(tmp_path, miniserver_http, breite, hoehe, ui, raster):
    """Tab ohne Pane 2 ("Screen fuellen"): quer werden die Spalten verdoppelt,
    hochkant die Zeilen - aber nur, wenn das Raster dadurch besser zur
    Fensterform passt (2x3 ist schon ein Hochformat-Raster). Das 4"-Panel und
    Split "Aus" bleiben beim Profilraster."""
    async def lauf():
        async with Umgebung(tmp_path, {"ui": dict({"scale": "auto"}, **ui)}) as u:
            pg = await u.seite(breite, hoehe)
            m = await pg.evaluate(RASTER)
            await u.bild(pg, f"fuellen_{breite}x{hoehe}_{raster}")
            assert m["raster"] == raster, m
            if raster == "2x4":
                # kein leerer Streifen mehr ueber und unter einem 2x2-Quadrat, keine gestreckten Kacheln
                assert abs(m["screen"]["h"] - hoehe) <= 1, m
                assert 0.9 <= m["kachel"]["w"] / m["kachel"]["h"] <= 1.4, m
                if ui.get("fill"):
                    assert abs(m["screen"]["w"] - breite) <= 1, m
            assert not u.fehler, u.fehler
    asyncio.run(lauf())


def test_screen_fuellen_dreht_mit(tmp_path, miniserver_http):
    """Drehen stellt die Verdopplung um: hochkant 2x4, quer 4x2, quadratisch 2x2."""
    async def lauf():
        async with Umgebung(tmp_path, {}) as u:
            pg = await u.seite(533, 893)
            for b, h, raster in [(533, 893, "2x4"), (893, 533, "4x2"), (533, 893, "2x4"), (480, 480, "2x2"),
                                 (533, 893, "2x4")]:
                await pg.set_viewport_size({"width": b, "height": h})
                await pg.wait_for_timeout(400)
                assert (await pg.evaluate(RASTER))["raster"] == raster, (b, h)
            assert not u.fehler, u.fehler
    asyncio.run(lauf())


UHRSEITE = """() => { const r = e => { if (!e || e.hidden) return null; const b = e.getBoundingClientRect();
    return {t: b.top, b: b.bottom, l: b.left, w: b.width, h: b.height}; };
  const s = el('saver');
  return {klassen: s.className, saver: r(s), clock: r(s.querySelector('.sv-clock')), wx: r(el('svWx')),
          cal: r(el('svCal')), box: r(el('svBox')), termine: document.querySelectorAll('#svCal .sv-ev').length,
          diagramme: document.querySelectorAll('#svBox .chart svg').length,
          svgs: [...document.querySelectorAll('#svBox .chart svg')].map(e => { const b = e.getBoundingClientRect();
            return [b.width, b.height]; })}; }"""


@pytest.mark.parametrize("svpane", ["", "chart:P", "off"], ids=["automatik", "verlauf", "aus"])
def test_uhrseite_hochkant_zweite_flaeche_unten(tmp_path, miniserver_http, monkeypatch, svpane):
    """Uhr-Seite hochkant: die gewaehlte zweite Flaeche steht unter Uhr und
    Wetter (vorher wurde sie hochkant ignoriert und der halbe Schirm blieb
    leer). 4"-Panel und quer bleiben wie bisher."""
    from test_front_tabs_browser import _front

    async def lauf():
        daten = await _front(monkeypatch)
        async with Umgebung(tmp_path, {"ui": {"svPane": svpane}}) as u:
            u.app._front = u.app._front_payload(daten)
            for b, h in [(533, 893), (480, 480), (960, 480)]:
                pg = await u.seite(b, h)
                await pg.evaluate("showSaver()")
                await pg.wait_for_timeout(1200)
                m = await pg.evaluate(UHRSEITE)
                await u.bild(pg, f"uhrseite_{svpane or 'automatik'}_{b}x{h}".replace(":", "-"))
                k = m["klassen"].split()
                if (b, h) == (480, 480):
                    assert "split" not in k and m["termine"] == 3, m   # unveraendert einspaltig
                elif b > h:
                    assert "split" in k and "hoch" not in k, m
                else:
                    assert "split" in k and "hoch" in k, m
                    assert m["clock"]["b"] <= m["wx"]["t"] + 1, m          # Uhr ueber dem Wetter
                    unten = m["box"] if svpane == "chart:P" else m["cal"]
                    if svpane == "off":
                        assert m["box"] is None and m["cal"] is None, m
                    else:
                        assert unten and unten["t"] >= m["wx"]["b"] - 1, m      # zweite Flaeche darunter
                        assert unten["b"] <= m["saver"]["b"] + 1, m
                        assert abs(unten["w"] - m["wx"]["w"]) <= 1, m           # volle Breite
                    if svpane == "chart:P":
                        assert m["diagramme"] == 2 and m["box"]["h"] >= 300, m
                        # Box so hoch wie ihr Inhalt, der Block mittig: gleich viel Rand oben und unten
                        oben, rest = m["clock"]["t"] - m["saver"]["t"], m["saver"]["b"] - m["box"]["b"]
                        assert abs(oben - rest) <= 12, m
                    if svpane == "":
                        assert m["termine"] == 3, m
                if svpane == "chart:P" and (b, h) != (480, 480):
                    # quer und hochkant im Seitenverhaeltnis der Zeichnung (440:150): die
                    # Hoehe teilen sich die Diagramme nur in der Split-Pane (Upstream #60),
                    # hier fielen sie hochkant sonst auf 0 px zusammen
                    assert len(m["svgs"]) == 2, m
                    assert all(sh > 0 and abs(sw / sh - 440 / 150) < 0.1 for sw, sh in m["svgs"]), m["svgs"]
                await pg.close()
            # Start ohne Antippen: die Uhr-Seite steht, bevor die erste Ansicht das
            # Raster verdoppelt - sie muss danach trotzdem hochkant geteilt sein.
            pg = await u.browser.new_page(viewport={"width": 533, "height": 893})
            pg.on("pageerror", lambda e: u.fehler.append(str(e)))
            await pg.goto(f"http://127.0.0.1:{u.port}/?panel=test")
            await pg.wait_for_timeout(1500)
            assert "hoch" in (await pg.evaluate(UHRSEITE))["klassen"].split()
            assert not u.fehler, u.fehler
    asyncio.run(lauf())


# Zaehler mit drei Diagrammen (Leistung, Zaehlerstand, Kosten): mehr, als die
# Uhr-Seite quer im Seitenverhaeltnis der Zeichnung unterbringt
NETZ_GRUPPEN = [
    {"id": "1", "mode": 10, "dataPoints": [{"title": "Netzbezug", "format": "0,000kW", "output": "actual"}]},
    {"id": "2", "mode": 11, "accumulated": True,
     "dataPoints": [{"title": "Zählerstand", "format": "0,0kWh", "output": "total"}]},
    {"id": "3", "mode": 11, "accumulated": True, "dataPoints": [{"title": "Kosten", "format": "0,00€", "output": "cost"}]},
]

# Sichtbarkeit der Verlaufs-Diagramme auf der Uhr-Seite: wie weit Diagramme und
# Legenden unten aus ihrer Seite ragen (dort abgeschnitten) und die SVG-Groessen
UHR_VERLAUF = """() => { const p = document.querySelector('#svBox .fp-page.cpage'); if (!p) return null;
  const unten = p.getBoundingClientRect().bottom;
  return {ueberlauf: Math.max(0, ...[...p.querySelectorAll('.chart, .chleg')]
            .map(e => e.getBoundingClientRect().bottom - unten)),
          svgs: [...p.querySelectorAll('.chart svg')].map(e => { const b = e.getBoundingClientRect();
            return [Math.round(b.width), Math.round(b.height)]; })}; }"""


def test_uhrseite_verlauf_schrumpft_statt_abzuschneiden(tmp_path, miniserver_http, monkeypatch):
    """Verlauf auf der Uhr-Seite: Passen die Diagramme nicht im Seitenverhaeltnis
    in den Kasten (drei Diagramme eines Zaehlers; zwei in einem niedrigen
    Fenster; seit Lenardos #77 auch mehrere Bausteine untereinander), schrumpfen
    sie, statt unten abgeschnitten zu werden - quer und hochkant. Mit genug
    Platz bleibt es beim Seitenverhaeltnis 440:150."""
    from test_front_tabs_browser import _front

    async def lauf():
        daten = await _front(monkeypatch)
        ergebnis = {}
        for cid, groessen in (("N", [(960, 480), (800, 480), (533, 893), (480, 800)]),
                              ("P", [(960, 400), (960, 480)]),
                              ("N,P", [(960, 480), (480, 800)])):
            async with Umgebung(tmp_path, {"ui": {"svPane": "chart:" + cid}}) as u:
                u.ms.v2.update({("NETZ", "1", "actual"): (1800, pv_leistung),
                                ("NETZ", "2", "total"): (3600, zaehlerstand(pv_leistung)),
                                ("NETZ", "3", "cost"): (3600, zaehlerstand(lambda t: pv_leistung(t) * 0.3))})
                u.controls["N"] = {"name": "Netz", "type": "Meter", "uuidAction": "NETZ",
                                   "states": {"actual": "a1", "total": "t1"},
                                   "details": {"actualFormat": "%.3fkW", "totalFormat": "%.1fkWh"},
                                   "statisticV2": {"groups": NETZ_GRUPPEN},
                                   "room": "r1", "cat": "c1", "isFavorite": True}
                u.app._apply_structure(anlage(u.controls))
                u.app._front = u.app._front_payload(daten)
                anzahl = {"N": 3, "P": 2, "N,P": 5}[cid]
                for b, h in groessen:
                    pg = await u.seite(b, h)
                    await pg.evaluate("showSaver()")
                    await pg.wait_for_function(
                        f"document.querySelectorAll('#svBox .chart svg').length === {anzahl}", timeout=15000)
                    await pg.wait_for_timeout(400)
                    ergebnis[(cid, b, h)] = await pg.evaluate(UHR_VERLAUF)
                    await u.bild(pg, f"uhrseite_verlauf_{cid.replace(',', '+')}_{b}x{h}")
                    await pg.close()
                assert not u.fehler, u.fehler
        return ergebnis
    ergebnis = asyncio.run(lauf())

    for (cid, b, h), m in ergebnis.items():
        assert m["ueberlauf"] <= 1, ((cid, b, h), m)                      # nichts abgeschnitten
        assert all(sh > 0 for _, sh in m["svgs"]), ((cid, b, h), m)        # keins zusammengefallen
    assert all(abs(sw / sh - 440 / 150) < 0.1 for sw, sh in ergebnis[("P", 960, 480)]["svgs"]), \
        "mit genug Platz im Seitenverhaeltnis der Zeichnung"


STAPEL_JS = """() => { const p = document.querySelector('#frontpane .fp-page.cpage'); if (!p) return null;
  const k = p.querySelector('.cpbody');
  return {stapel: p.classList.contains('stack'),
          namen: [...p.querySelectorAll('.cpsec .cpname')].map(e => e.textContent),
          leisten: p.querySelectorAll('.chrng').length,
          an: [...p.querySelectorAll('.cpr .chip.on')].map(c => c.textContent),
          svgs: p.querySelectorAll('.cpsec .chart svg').length,
          scrollt: k.scrollHeight > k.clientHeight,
          leiste_oben: p.querySelector('.cpr').getBoundingClientRect().bottom <= k.getBoundingClientRect().top + 1}; }"""


def test_verlauf_pane_stapelt_mehrere_bausteine(tmp_path, miniserver_http):
    """Verlauf als Pane 2 mit mehreren Bausteinen (Lenardos #77): je Baustein
    ein Kopf mit Name und Wert, die Diagramme untereinander. Die Bausteine
    scrollen, die Zeitraum-Leiste steht einmal fest darueber und gilt fuer
    alle. Mit einem Baustein bleibt die Pane eingepasst wie bisher."""
    async def lauf():
        async with Umgebung(tmp_path, {"ui": {"panes": {"favoriten": "chart:T,R,P"}}}) as u:
            pg = await u.seite(960, 480)
            await pg.wait_for_function(
                "document.querySelectorAll('#frontpane .cpsec .chart svg').length >= 3", timeout=15000)
            await pg.wait_for_timeout(400)
            info = await pg.evaluate(STAPEL_JS)
            await u.bild(pg, "verlauf_gestapelt")
            assert info["stapel"] and info["namen"] == ["Boiler", "Regen", "PV Anlage"], info
            assert info["leisten"] == 1 and info["an"] == ["24 h"] and info["leiste_oben"], info
            assert info["scrollt"], "drei Bausteine passen nicht in die halbe Hoehe: die Pane scrollt"
            await pg.locator("#frontpane .cpr .chip", has_text="7 Tage").dispatch_event("pointerdown")
            await pg.wait_for_function("""() => { const c = document.querySelector('#frontpane .cpr .chip.on');
                return c && c.textContent === '7 Tage'
                       && document.querySelectorAll('#frontpane .cpsec .chart svg').length >= 3; }""",
                                       timeout=15000)
            assert await pg.evaluate("chartData.range") == "7d"
            assert await pg.evaluate("chartData.controls") == ["T", "R", "P"]
            u.app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"],
                                                            "ui": {"panes": {"favoriten": "chart:T"}}}})
            pg2 = await u.seite(960, 480)
            await pg2.wait_for_function("document.querySelectorAll('#frontpane .cpsec .chart svg').length === 1",
                                        timeout=15000)
            await pg2.wait_for_timeout(400)
            einzeln = await pg2.evaluate(STAPEL_JS)
            await u.bild(pg2, "verlauf_einzeln")
            assert not einzeln["stapel"] and einzeln["namen"] == ["Boiler"] and not einzeln["scrollt"], einzeln
        assert not u.fehler, u.fehler
    asyncio.run(lauf())


NAMEN_MITSCHREIBEN = """() => { window._namen = []; const fp = document.getElementById('frontpane');
  new MutationObserver(() => fp.querySelectorAll('.cpname').forEach(e => window._namen.push(e.textContent)))
    .observe(fp, {subtree: true, childList: true, characterData: true}); }"""


def test_verlauf_pane_verwirft_fremden_stapel(tmp_path, miniserver_http):
    """Ein Verlaufs-Push, der beim Wechsel der Pane schon unterwegs war, nennt
    Bausteine, die die Pane nicht mehr zeigt: die Visu verwirft ihn, statt das
    fremde Diagramm samt Namen auch nur kurz zu zeigen. Ein Push zum
    angefragten Baustein (hier mit anderem Zeitraum) kommt weiter an."""
    async def lauf():
        async with Umgebung(tmp_path, {"ui": {"panes": {"favoriten": "chart:T"}}}) as u:
            pg = await u.seite(960, 480)
            await pg.wait_for_function("document.querySelectorAll('#frontpane .cpsec .chart svg').length === 1",
                                       timeout=15000)
            await pg.evaluate(NAMEN_MITSCHREIBEN)
            ws, = list(u.app.conn_chart)
            await ws.send_json({"t": "chart", **u.app.chart_stack(("R",), "24h")})
            await ws.send_json({"t": "chart", **u.app.chart_stack(("T",), "7d")})
            await pg.wait_for_function("chartData && chartData.range === '7d'", timeout=15000)
            await pg.wait_for_timeout(200)
            gesehen = await pg.evaluate("window._namen")
            namen = await pg.evaluate("[...document.querySelectorAll('#frontpane .cpsec .cpname')]"
                                      ".map(e => e.textContent)")
            assert "Regen" not in gesehen, gesehen
            assert namen == ["Boiler"] and await pg.evaluate("chartData.controls") == ["T"]
            # Leerzeichen in der Liste (panels.json von Hand) trimmt der Server
            # beim Anfragen weg; die Visu vergleicht genauso
            await pg.evaluate("curChartKey = 'T, R|24h'")
            await ws.send_json({"t": "chart", **u.app.chart_stack(("T", "R"), "24h")})
            await pg.wait_for_function("chartData && chartData.controls.length === 2", timeout=15000)
        assert not u.fehler, u.fehler
    asyncio.run(lauf())


@pytest.mark.parametrize("raumzeile", [True, False], ids=["mit_raumzeile", "ohne_raumzeile"])
def test_kachel_stile_je_kachelgroesse(tmp_path, miniserver_http, raumzeile):
    """Der Mini-Verlauf passt sich der Kachel an (Querformat ohne rechte Haelfte
    verdoppelt die Spalten, 3 -> 6):
    mitte   genug Hoehe: Verlauf in der Kachelmitte
    kopf    niedrig, aber breit: Verlauf in der Kopfzeile neben dem Icon
    keiner  niedrig und schmal (18 Kacheln auf 800 x 480): kein Platz fuer einen
            Verlauf, die Angabe bleibt in der Raumzeile lesbar
    Ohne Raumzeile (alle Bausteine in einem Raum, wie in der Raum-Ansicht)
    bekommt die Angabe die Zeile ueber dem Namen, der Verlauf wird dafuer
    niedriger gezeichnet statt abgeschnitten.
    Das ist der klassische Kachel-Aufbau; im neuen steht oben rechts der Raum
    und die Angabe immer als Zeile im Text (test_kachel_aufbau_browser.py)."""
    faelle = [(1280, 800, 3, "mitte"), (800, 480, 2, "mitte"), (1280, 480, 3, "kopf"), (800, 480, 3, "keiner")]
    tiles = {"T": {"chart": "24h", "chartStyle": "span"}, "Z": {"chart": "24h", "chartStyle": "pattern"},
             "R": {"chart": "7d"}, "P": {"chart": "24h"}}

    async def lauf():
        async with Umgebung(tmp_path, {}) as u:
            if not raumzeile:
                for c in u.app.controls.values():
                    c["room"] = "r1"
            for breite, hoehe, zeilen, ort in faelle:
                u.app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"],
                                                                "ui": {"cols": 3, "rows": zeilen,
                                                                       "tileLayout": "classic"},
                                                                "tiles": tiles}})
                pg = await u.seite(breite, hoehe)
                info = await pg.evaluate("""() => [...document.querySelectorAll('.tile')].map(t => ({
                    name: t.querySelector('.name').textContent, svg: !!t.querySelector('.tspark svg'),
                    rects: t.querySelectorAll('.tspark rect').length, eng: t.classList.contains('sparktight'),
                    hoehe: (t.querySelector('.tspark svg') || {}).clientHeight || 0,
                    ueber: (sv => sv ? sv.getBoundingClientRect().bottom
                                       - t.querySelector('.tspark').getBoundingClientRect().bottom : 0)
                           (t.querySelector('.tspark svg')),
                    raum: !!t.querySelector('.room:not(.tsline)'),
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
                fall = f"{breite}x{hoehe}, {zeilen} Zeilen, {'mit' if raumzeile else 'ohne'} Raumzeile"
                assert not k["Licht"]["svg"] and not any(i["abgeschnitten"] for i in info), (fall, info)
                assert all(i["raum"] == raumzeile for i in info), (fall, info)
                assert all(i["ueber"] <= 1 for i in mit), f"{fall}: Verlauf ragt aus seinem Platz {info}"
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


@pytest.mark.parametrize("raumzeile", [True, False], ids=["mit_raum", "ohne_raum"])
def test_mini_verlauf_im_neuen_aufbau(tmp_path, miniserver_http, raumzeile):
    """Der Mini-Verlauf im neuen Kachel-Aufbau, dieselben Kachelgroessen wie im
    klassischen (test_kachel_stile_je_kachelgroesse). Der Raum steht oben
    rechts, die Angabe zum Verlauf als Zeile im Text. Ist die Mitte zu niedrig,
    rueckt der Verlauf in den Kopf; reicht der Text dann noch nicht, weicht die
    Angabe vor dem Namen - der Verlauf bleibt, auch wo der klassische Aufbau
    (18 Kacheln auf 800 x 480) keinen Platz fuer ihn hat."""
    faelle = [(1280, 800, 3, "mitte"), (800, 480, 2, "mitte"), (1280, 480, 3, "kopf"), (800, 480, 3, "kopf")]
    tiles = {"T": {"chart": "24h", "chartStyle": "span"}, "Z": {"chart": "24h", "chartStyle": "pattern"},
             "R": {"chart": "7d"}, "P": {"chart": "24h"}}

    async def lauf():
        async with Umgebung(tmp_path, {}) as u:
            if not raumzeile:
                for c in u.app.controls.values():
                    c["room"] = "r1"
            for breite, hoehe, zeilen, ort in faelle:
                u.app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"],
                                                                "ui": {"cols": 3, "rows": zeilen}, "tiles": tiles}})
                pg = await u.seite(breite, hoehe)
                info = await pg.evaluate("""() => [...document.querySelectorAll('.tile')].map(t => {
                    const sicht = e => !!e && getComputedStyle(e).display !== 'none';
                    const ganz = e => sicht(e) && e.scrollHeight <= e.clientHeight + 1 && e.scrollWidth <= e.clientWidth + 1;
                    const svg = t.querySelector('.tspark svg'), sp = t.querySelector('.tspark'), tl = t.querySelector('.tsline');
                    return {name: t.querySelector('.name').textContent, nameGanz: ganz(t.querySelector('.name')),
                      zustand: sicht(t.querySelector('.sub')), svg: !!svg, hoehe: svg ? svg.clientHeight : 0,
                      imKopf: !!sp && sp.parentNode.classList.contains('head'), eng: t.classList.contains('sparktight'),
                      stufen: [...t.classList].filter(c => /^eng\\d$/.test(c)).join(' '),
                      ueber: svg ? svg.getBoundingClientRect().bottom - sp.getBoundingClientRect().bottom : 0,
                      ueberlauf: t.scrollHeight - t.clientHeight,
                      zeile: sicht(tl) ? tl.textContent : null, kopfAngabe: sicht(t.querySelector('.tsbadge')),
                      raum: sicht(t.querySelector('.head .room')) ? t.querySelector('.head .room').textContent : null,
                      angabe: (t.querySelector('.tsline') || {}).textContent || ''}; })""")
                await u.bild(pg, f"neu_verlauf_{breite}x{hoehe}_{zeilen}zeilen")
                k = {i["name"]: i for i in info}
                mit = [k[n] for n in ("Boiler", "Stromzähler", "Regen", "PV Anlage")]
                fall = f"{breite}x{hoehe}, {zeilen} Zeilen, {'mit' if raumzeile else 'ohne'} Raum"
                assert await pg.evaluate("document.getElementById('grid').classList.contains('lx')"), fall
                assert not k["Licht"]["svg"] and all(i["ueberlauf"] <= 1 for i in info), (fall, info)
                assert all(i["ueber"] <= 1 for i in mit), f"{fall}: Verlauf ragt aus seinem Platz {info}"
                # Name und Zustand bleiben ganz, der Verlauf immer da, nie eine Angabe im Kopf
                assert all(i["nameGanz"] and i["zustand"] for i in mit), (fall, info)
                assert all(i["svg"] and i["hoehe"] >= 30 for i in mit), (fall, info)
                assert not any(i["kopfAngabe"] for i in info), (fall, info)
                assert k["Boiler"]["angabe"] and all(i["angabe"] for i in mit), "der Server liefert die Angabe"
                if ort == "mitte":
                    # Platz genug: Verlauf in der Mitte, Angabe als Zeile, Raum oben rechts
                    assert not any(i["eng"] or i["imKopf"] for i in mit), (fall, info)
                    assert all(i["zeile"] == i["angabe"] for i in mit), (fall, info)
                    assert all((i["raum"] is not None) == raumzeile for i in mit), (fall, info)
                else:
                    # Verlauf im Kopf an Stelle des Raums; die Angabe weicht vor dem Namen
                    assert all(i["eng"] and i["imKopf"] and i["raum"] is None for i in mit), (fall, info)
                    assert all(i["zeile"] is None for i in mit), (fall, info)
                # Live-Aenderung: an Ort und Stelle neu gezeichnet, Darstellung bleibt
                await pg.evaluate("document.querySelectorAll('.tile').forEach(t => t._alt = true)")
                u.app.states["sv"] += 0.8
                u.app.stat_gen += 1
                u.app._dirty = True
                await pg.wait_for_timeout(1500)
                nachher = await pg.evaluate("""() => [...document.querySelectorAll('.tile')].map(t =>
                    [t._alt === true, !!t.querySelector('.tspark svg'), t.classList.contains('sparktight'),
                     [...t.classList].filter(c => /^eng\\d$/.test(c)).join(' ')])""")
                assert all(a for a, _, _, _ in nachher), f"{fall}: neu aufgebaut statt aktualisiert"
                assert [n[1:] for n in nachher] == [[i["svg"], i["eng"], i["stufen"]] for i in info], (fall, nachher)
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
