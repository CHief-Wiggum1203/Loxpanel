"""Lesbarkeit der Kachel-Sets in Chromium: Jeder sichtbare Text jeder Ansicht
(Raster, Uhr-Seite mit Wetter und Terminen, Kalender- und Wetter-Tab, Front
und Player neben den Kacheln, Detailseite, Liste mit aktiver Zeile, PIN,
Hausuebersicht, Verbindungsleiste) wird gegen die Flaeche gemessen, auf der er
wirklich steht - Schriftfarbe, Deckkraft und alle Hintergruende darunter, wie
der Browser sie rechnet. Text muss AA (4,5:1)
tragen, grosse Schrift (ab 24 px oder 18,66 px fett) 3:1, wie WCAG 1.4.3.
Das Set "touch" laeuft dazu ueber die Farbtoene der Schnellwahl und beide
Arten der aktiven Kachel: seine Farben sind gerechnet, nicht ausgesucht, und
ein Fehler steckt dann in der Rechnung, nicht in einer Farbe."""
import asyncio

import pytest

from lox import W, visu_starten
from test_front_tabs_browser import _front
from test_kachel_aufbau_browser import STATES, STRUKTUR

import theme_colors as TC

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

AA, GROSS = 4.5, 3.0

# Jeder sichtbare Text: Schriftfarbe mit der Deckkraft seiner Vorfahren, die
# Hintergruende von innen nach aussen bis zur ersten deckenden Flaeche, so
# uebereinandergelegt, wie der Browser sie malt. Ein Hintergrundbild (Verlauf,
# Kamerabild) laesst sich nicht nachrechnen, solcher Text bleibt aussen vor.
TEXTE = """(wurzel) => {
  const rgba = s => { const m = s.match(/[\\d.]+/g) || [0, 0, 0, 0];
    return {r: +m[0], g: +m[1], b: +m[2], a: m.length > 3 ? +m[3] : 1}; };
  const auf = (o, u) => { const a = o.a + u.a * (1 - o.a);
    return a ? {r: (o.r * o.a + u.r * u.a * (1 - o.a)) / a, g: (o.g * o.a + u.g * u.a * (1 - o.a)) / a,
                b: (o.b * o.a + u.b * u.a * (1 - o.a)) / a, a} : o; };
  const lum = c => [c.r, c.g, c.b].map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; })
    .reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
  const kontrast = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const hex = c => '#' + [c.r, c.g, c.b].map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
  const raus = [];
  const vw = innerWidth, vh = innerHeight;
  for (const e of (wurzel ? document.querySelector(wurzel) : document.body).querySelectorAll('*')) {
    if (e.closest('svg') || ['SCRIPT', 'STYLE', 'INPUT', 'TEXTAREA', 'SELECT', 'OPTION'].includes(e.tagName)) continue;
    const text = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
    if (!text) continue;
    const s = getComputedStyle(e), r = e.getBoundingClientRect();
    if (s.visibility !== 'visible' || r.width < 1 || r.height < 1 || r.right <= 0 || r.bottom <= 0
        || r.left >= vw || r.top >= vh || e.checkVisibility && !e.checkVisibility({opacityProperty: true})) continue;
    // die Stelle muss wirklich sichtbar sein (nicht unter einer Seite darueber)
    const x = Math.min(vw - 1, Math.max(0, r.left + r.width / 2)), y = Math.min(vh - 1, Math.max(0, r.top + r.height / 2));
    const oben = document.elementFromPoint(x, y);
    if (!oben || !(oben === e || e.contains(oben) || oben.contains(e))) continue;
    let schrift = rgba(s.color), deckung = 1, bild = false, lagen = [];
    for (let p = e; p; p = p.parentElement) {
      const ps = getComputedStyle(p), bg = rgba(ps.backgroundColor);
      if (ps.backgroundImage !== 'none') { bild = true; break; }
      if (bg.a > 0) lagen.push(bg);
      if (bg.a >= 1) break;
      deckung *= parseFloat(ps.opacity);
    }
    if (bild) continue;
    let grund = {r: 255, g: 255, b: 255, a: 1};
    for (const l of lagen.reverse()) grund = auf(l, grund);
    schrift = auf({...schrift, a: schrift.a * deckung}, grund);
    const px = parseFloat(s.fontSize), fett = parseInt(s.fontWeight) >= 700;
    raus.push({text: text.slice(0, 40), wo: e.tagName.toLowerCase() + (e.id ? '#' + e.id : '')
               + [...e.classList].map(k => '.' + k).join(''), schrift: hex(schrift), grund: hex(grund),
               kontrast: Math.round(kontrast(schrift, grund) * 100) / 100, gross: px >= 24 || (fett && px >= 18.66)});
  }
  return raus;
}"""

# Messwerte fuer Werteleiste und Kopfzeile: ihre Chips haben eine eigene Flaeche
# (--tile) auf der Leiste, die Schrift muss zu ihr passen, nicht zur Leiste
WERTE = {"T0": {"name": "Außentemperatur", "type": "InfoOnlyAnalog", "uuidAction": "T0", "room": "r1", "cat": "c1",
                "isFavorite": True, "states": {"value": "t0"}, "details": {"format": "%.1f°C"}},
         "T1": {"name": "Strom", "type": "Meter", "uuidAction": "T1", "room": "r1", "cat": "c1",
                "isFavorite": True, "states": {"actual": "t1", "total": "t2"},
                "details": {"actualFormat": "%.2fkW", "totalFormat": "%.1fkWh"}}}
WERTE_STATES = {"t0": 12.4, "t1": 0.82, "t2": 1234.5}

# Was gemessen wird: Name -> (Tabs der Ansicht, ui, Schritte in der Visu[, mit
# Messwerten]). Am iPad quer mit automatischem Raster, wie test_kachel_set_browser.
TABS = ["favoriten", "kalender", "wetter"]
ANSICHTEN = {
    "raster": (TABS, {}, []),
    "uhr": (TABS, {}, ["showSaver()"]),
    "kalender": (TABS, {}, ["nav({view:'tab', tab:'kalender'})"]),
    "wetter": (TABS, {}, ["nav({view:'tab', tab:'wetter'})"]),
    "front_daneben": (TABS, {"panes": {"favoriten": "calendar"}}, []),
    # Player als Pane 2: seine Seite hatte einen Verlauf, den TEXTE nicht
    # nachrechnen kann - Titel und Sender blieben ungemessen und waren im
    # Set "touch" auf dem dunklen Rahmen unlesbar
    "player_daneben": (TABS, {"panes": {"favoriten": "player:AZ"}}, []),
    # Hilfe zum Hinweis-Symbol der Gesten: Karten ueber abgedunkeltem Grund
    "gesten_hilfe": (["room:r4"] + TABS, {"gesten": True}, ["gestenHilfeZeigen()"]),
    "kopfzeile": (TABS, {"panes": {"favoriten": "header"}}, []),
    "kopfzeile_werte": (TABS, {"panes": {"favoriten": "header:T0,T1"}}, [], True),
    "werteleiste": (TABS, {"valueBar": ["favoriten"]}, [], True),
    "detail": (TABS, {}, ["nav({view:'control', id:'IR'})"]),
    # Liste mit aktiver Zeile (Stimmungen der Lichtsteuerung, "Aus" ist an):
    # die Zeile kippt um wie eine aktive Kachel, ihre Schrift muss mitziehen
    "liste": (TABS, {}, ["nav({view:'control', id:'LC'})"]),
    "pin": (TABS, {}, ["askPin(() => {}, 'PIN')"]),
    # Hausuebersicht: Karten, aktive Geraete und Spieler auf den Flaechen des Sets
    "haus": (TABS + ["haus"], {}, ["goTab('haus')"]),
    # Verbindungsleiste: Miniserver weg, mit den Texten, die der Server schickte
    "verbindung": (TABS, {}, ["verbMiniserver({ms: false, seit: Date.now() - 60000, stand: Date.now() - 61000,"
                              " takt: verb.takt, stumm: verb.stumm, hinweis: 0, texte: verb.texte})"]),
}
# Ansichten, in denen nur ein Teil zaehlt: die Leiste. Die Kacheln darunter
# sind dann gesperrt und absichtlich blass (WCAG 1.4.3 nimmt inaktive
# Bedienelemente aus).
WURZEL = {"verbindung": "#verbindung", "gesten_hilfe": "#gestenHilfe"}


def _faelle():
    yield "ohne_set", {}
    for name in TC.KACHEL_SETS:
        e = TC.KACHEL_SETS[name]
        if "farbton" not in e:
            yield name, {"tileSet": name}
            continue
        for wahl in e["farbton"]["auswahl"]:
            for aktiv in e["aktiv"]["auswahl"]:
                yield f"{name}-{wahl['wert']}-{aktiv['key']}", \
                    {"tileSet": name, "tileHue": wahl["wert"], "tileActive": aktiv["key"]}


def _app(ui, tabs, daten, werte=False):
    app = W.App({"host": "", "port": 80})
    app._apply_structure({**STRUKTUR, "controls": {**STRUKTUR["controls"], **WERTE}} if werte else STRUKTUR)
    app.states = {**STATES, **WERTE_STATES} if werte else dict(STATES)
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "ui": {"grid": "auto", **ui}, "tabs": tabs}})
    app._front = app._front_payload(daten)
    return app


def _messen(ui, monkeypatch, tmp_path, bild):
    async def lauf():
        daten = await _front(monkeypatch)
        raus, fehler = {}, []
        async with async_playwright() as p:
            b = await p.chromium.launch()
            for ansicht, (tabs, extra, schritte, *werte) in ANSICHTEN.items():
                runner, port, bc = await visu_starten(_app({**ui, **extra}, tabs, daten, bool(werte and werte[0])))
                try:
                    pg = await b.new_page(viewport={"width": 1000, "height": 750}, locale="de-DE")
                    pg.on("pageerror", lambda e: fehler.append(str(e)))
                    await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                    await pg.wait_for_selector("#grid .tile[data-id]", state="attached")
                    await pg.evaluate("wake()")
                    await pg.wait_for_timeout(500)
                    for s in schritte:
                        await pg.evaluate(s)
                        await pg.wait_for_timeout(500)
                    raus[ansicht] = await pg.evaluate(TEXTE, WURZEL.get(ansicht))
                    await pg.screenshot(path=str(tmp_path / f"{bild}_{ansicht}.png"))
                    await pg.close()
                finally:
                    bc.cancel()
                    await runner.cleanup()
            await b.close()
        assert not fehler, fehler
        return raus
    return asyncio.run(lauf())


@pytest.mark.parametrize("fall,ui", list(_faelle()))
def test_jeder_text_ist_lesbar(fall, ui, monkeypatch, tmp_path):
    raus = _messen(ui, monkeypatch, tmp_path, fall)
    schlecht = {a: [t for t in texte if t["kontrast"] < (GROSS if t["gross"] else AA)]
                for a, texte in raus.items()}
    for a, texte in raus.items():
        assert texte, (fall, a, "kein Text gemessen")
    for a in ("kopfzeile_werte", "werteleiste"):   # die Werte der Chips sind dabei
        assert sum(".vl" in t["wo"] for t in raus[a]) >= 2, (fall, a, raus[a])
    if TC.kachel_set_art(ui.get("tileSet"))[1] == "oben":   # Pane 2 flach auf dem Feld: ihr Text zaehlt mit
        assert any("pptitle" in t["wo"] for t in raus["player_daneben"]), (fall, raus["player_daneben"])
    assert not any(schlecht.values()), (fall, {a: t for a, t in schlecht.items() if t})
