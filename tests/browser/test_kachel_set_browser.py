"""Kachel-Sets (ui.tileSet) in Chromium: jedes Set aus theme_colors.KACHEL_SETS
am iPad (1000 x 750, automatisches Raster) und am 4"-Panel (480 x 480, festes
2 x 2 ohne Split). Gemessen wird gegen die Werte des Sets selbst
(theme_colors.kachel_set), keine zweite Farbliste im Test: Flaeche, aktive
Kachel, Symbol, Tab-Leiste je nach Art (pille, oben, links) und Aufbau (lx,
mitte, kreis). Nichts laeuft ueber, das Raster bleibt wie ohne Set - ausser
bei der Seitenleiste links, die Breite nimmt: dort duerfen es weniger
Spalten werden, abgeschnitten wird keine Kachel. Die Leiste "oben" steht in
jeder Zeilen-Variante des Kastens (Kopfzeile, Werteleiste, Split quer und
hochkant) ueber allem anderen, ohne etwas zu verdecken. Dazu der
Konfigurator (Auswahl, Farbton nur bei touch, Speichern) und der Wechsel des
Sets bei einer neuen Verbindung. Die Bilder aller Sets landen im tmp_path
(CI: Artefakt "screenshots")."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, visu_starten
from test_kachel_aufbau_browser import MESSEN, STATES, STRUKTUR, _visu

import theme_colors as TC

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

SETS = list(TC.KACHEL_SETS)
TABS = ["favoriten", "zentral", "raeume", "kategorien"]
# iPad quer mit automatischem Raster, 4"-Panel mit festem 2 x 2 ohne Split
GERAETE = {"ipad": (1000, 750, {"grid": "auto"}), "4zoll": (480, 480, {"split": False})}

# Was die Visu zeigt: Attribute, Farben der Kacheln und der Leiste, Lage von
# Leiste und Raster, Raster und Kachelflaechen
SET_MESSEN = """() => {
  const cs = e => getComputedStyle(e), t = id => document.querySelector('#grid .tile[data-id="' + id + '"]');
  const r = e => e.getBoundingClientRect(), html = document.documentElement;
  const tabs = document.getElementById('tabs'), grid = document.getElementById('grid'), sc = document.querySelector('.screen');
  const tab = [...tabs.querySelectorAll('.tab')], an = tabs.querySelector('.tab.active'), aus = tab.find(x => x !== an);
  const kreis = e => e && e.querySelector('.kreis');
  return {
    attr: [html.getAttribute('data-kachelset'), html.getAttribute('data-kachelset-aufbau'), html.getAttribute('data-kachelset-leiste')],
    aus: cs(t('MB')).backgroundColor, an: cs(t('FS')).backgroundColor,
    symbolAus: cs(t('MB').querySelector('.ico')).color, symbolAn: cs(t('FS').querySelector('.ico')).color,
    textAn: cs(t('FS').querySelector('.name')).color, zweitAn: cs(t('FS').querySelector('.sub')).color,
    kreisAus: kreis(t('MB')) ? cs(kreis(t('MB'))).backgroundColor : null,
    kreisAn: kreis(t('FS')) ? cs(kreis(t('FS'))).backgroundColor : null,
    raumKopf: !!t('MB').querySelector('.head .room'),
    texte: [t('FS').querySelector('.name').textContent, (t('FS').querySelector('.sub') || {}).textContent],
    radius: cs(t('MB')).borderTopLeftRadius, schatten: cs(t('MB')).boxShadow,
    ks: parseFloat(cs(sc).getPropertyValue('--ks')) || 1,
    pille: getComputedStyle(tabs, '::before').backgroundColor, leisteFarbe: cs(tabs).backgroundColor,
    tabAn: an ? cs(an).color : null, tabAus: aus ? cs(aus).color : null,
    namen: tab.map(x => { const n = x.querySelector('.tnm'); return n && cs(n).display !== 'none' ? n.textContent : null; }),
    tabs: r(tabs).toJSON(), grid: r(grid).toJSON(), schirm: r(sc).toJSON(),
    zeilen: cs(sc).getPropertyValue('--rows').trim() || cs(html).getPropertyValue('--rows').trim(),
    spalten: cs(html).getPropertyValue('--cols').trim(),
    railW: cs(sc).getPropertyValue('--rail-w').trim(), schmal: sc.classList.contains('rail-schmal'),
    kacheln: [...grid.querySelectorAll('.tile[data-id]')].filter(k => r(k).width > 0).map(k => r(k).toJSON()),
  };
}"""


def _rgb(hexwert: str) -> str:
    h = hexwert.lstrip("#")
    return "rgb(%d, %d, %d)" % tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _app(ui: dict, tabs=TABS, struktur=STRUKTUR):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    app.states = dict(STATES)
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "ui": ui, "tabs": tabs}})
    return app


def _messen(ui, breite, hoehe, tmp_path=None, bild=None, tabs=TABS, struktur=STRUKTUR):
    async def lauf():
        app = _app(ui, tabs, struktur)
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _visu(b, port, breite, hoehe, fehler)
                werte, kacheln = await pg.evaluate(SET_MESSEN), await pg.evaluate(MESSEN)
                if tmp_path and bild:
                    await pg.screenshot(path=str(tmp_path / f"{bild}.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return werte, kacheln
    return asyncio.run(lauf())


@pytest.mark.parametrize("geraet", list(GERAETE))
@pytest.mark.parametrize("name", SETS)
def test_set_am_geraet(name, geraet, tmp_path):
    breite, hoehe, ui = GERAETE[geraet]
    v = TC.kachel_set(name)
    aufbau, leiste = TC.kachel_set_art(name)
    mit, k = _messen({**ui, "tileSet": name}, breite, hoehe, tmp_path, f"set_{name}_{geraet}")
    ohne, _ = _messen(ui, breite, hoehe, tmp_path, f"set_ohne_{geraet}")

    assert mit["attr"] == [name, aufbau, leiste] and ohne["attr"] == [None, None, None], (mit["attr"], ohne["attr"])
    # Flaechen und Symbole aus dem Set
    assert mit["aus"] == _rgb(v["--tile"]), mit
    assert mit["an"] == _rgb(v["--kachel-an"]), mit
    assert mit["symbolAus"] == _rgb(v["--ink"]), mit
    radius = float(v.get("--kachel-radius", "16px").rstrip("px")) * mit["ks"]
    assert abs(float(mit["radius"].rstrip("px")) - radius) < 0.6, (mit["radius"], radius)
    assert (mit["schatten"] != "none") == ("--kachel-schatten" in v), mit["schatten"]
    if aufbau == "mitte":
        # die aktive Kachel kippt ganz um; Zustand vorn, "Name · Raum" darunter, kein Raum im Kopf
        assert mit["textAn"] == mit["zweitAn"] == mit["symbolAn"] == _rgb(v["--kachel-an-ink"]), mit
        assert mit["texte"] == ["Ein", "Frostsicherung · Zentral"] and not mit["raumKopf"], mit["texte"]
    else:
        assert mit["raumKopf"], "Raum oben rechts im Kopf"
        assert mit["zweitAn"] == _rgb(v.get("--an-text", v["--glow"])), mit
    if aufbau == "kreis":
        assert mit["kreisAus"] == _rgb(v["--taste"]) and mit["kreisAn"] == _rgb(v["--glow"]), mit
        assert mit["symbolAn"] == _rgb(v["--kreis-an-symbol"]), mit
    else:
        assert mit["kreisAus"] is None and mit["kreisAn"] is None
    # Tab-Leiste je nach Art
    s, tb, g = mit["schirm"], mit["tabs"], mit["grid"]
    if leiste == "pille":
        assert mit["pille"] == _rgb(v["--tabbar"]) and abs(tb["bottom"] - s["bottom"]) < 1, mit
    if leiste == "oben":
        assert mit["leisteFarbe"] == _rgb(v["--tabbar"]), mit
        assert mit["tabAn"] == _rgb(v["--tab-an"]) and mit["tabAus"] == _rgb(v["--tab-aus"]), mit
        assert abs(tb["top"] - s["top"]) < 1 and g["top"] >= tb["bottom"] - 0.5, (tb, g)
        assert not any(mit["namen"]), "nur Symbole"
    if leiste == "links":
        assert abs(tb["left"] - s["left"]) < 1 and tb["height"] >= s["height"] - 1, tb
        assert mit["leisteFarbe"] == _rgb(v["--tabbar"]), mit
        assert mit["railW"] == f"{round(tb['width'])}px" and g["left"] >= tb["right"] - 0.5, (mit["railW"], tb, g)
        assert mit["schmal"] == (breite < 600), "schmale Schirme nur mit Symbol"
        assert all(n is None for n in mit["namen"]) == (breite < 600), mit["namen"]
    # Nichts laeuft ueber, keine Kachel abgeschnitten
    assert all(e["ueberlauf"] <= 1 and e["textUnten"] <= 0 for e in k.values()), \
        {i: (e["ueberlauf"], e["textUnten"]) for i, e in k.items()}
    # (waagerechte Seiten: die Kacheln der naechsten Seiten liegen rechts daneben)
    for t in (t for t in mit["kacheln"] if t["left"] < g["right"] - 1):
        assert t["left"] >= g["left"] - 0.5 and t["right"] <= g["right"] + 0.5, (t, g)
    # Raster wie ohne Set; die Seitenleiste darf Spalten kosten
    if leiste == "links":
        assert int(mit["spalten"]) <= int(ohne["spalten"]), (mit["spalten"], ohne["spalten"])
    else:
        assert (mit["spalten"], mit["zeilen"], round(tb["height"])) == \
            (ohne["spalten"], ohne["zeilen"], round(ohne["tabs"]["height"])), (mit, ohne)
        assert abs(g["height"] - ohne["grid"]["height"]) < 1 and abs(g["width"] - ohne["grid"]["width"]) < 1


# Zeilen-Varianten des Kastens fuer die Leiste "oben": Kopfzeile, Werteleiste,
# beides, Split quer und hochkant mit Widget, Split mit Werteleiste.
LF = {"name": "Luftfeuchte", "type": "InfoOnlyAnalog", "uuidAction": "LF", "room": "r1", "cat": "c1",
      "isFavorite": True, "states": {"value": "lf1"}, "details": {"format": "%.0f %%"}}
STRUKTUR_WERTE = {**STRUKTUR, "controls": {**STRUKTUR["controls"], "LF": LF}}
VARIANTEN = {
    "kopf": ({"panes": {"favoriten": "header"}, "grid": "auto"}, (1000, 750), ["kopfzeile"]),
    "leiste": ({"valueBar": ["favoriten"], "grid": "auto"}, (1000, 750), ["werteleiste"]),
    "kopf_leiste": ({"panes": {"favoriten": "header"}, "valueBar": ["favoriten"], "grid": "auto"}, (1000, 750),
                    ["kopfzeile", "werteleiste"]),
    "split": ({"panes": {"favoriten": "weather"}, "grid": "auto"}, (1000, 750), ["frontpane"]),
    "hoch": ({"panes": {"favoriten": "weather"}, "grid": "auto"}, (750, 1000), ["frontpane"]),
    "split_leiste": ({"panes": {"favoriten": "weather"}, "valueBar": ["favoriten"], "grid": "auto"}, (1000, 750),
                     ["werteleiste", "frontpane"]),
    "hoch_leiste": ({"panes": {"favoriten": "weather"}, "valueBar": ["favoriten"], "grid": "auto"}, (750, 1000),
                    ["werteleiste", "frontpane"]),
    "fest_hoch": ({"panes": {"favoriten": "weather"}}, (750, 1000), ["frontpane"]),
}
FLAECHEN = """(teile) => {
  const r = id => { const e = document.getElementById(id) || document.querySelector('.' + id);
    return e && getComputedStyle(e).display !== 'none' ? e.getBoundingClientRect().toJSON() : null; };
  return {schirm: document.querySelector('.screen').getBoundingClientRect().toJSON(), tabs: r('tabs'), grid: r('grid'),
          teile: Object.fromEntries(teile.map(t => [t, r(t)])),
          klassen: [...document.querySelector('.screen').classList]};
}"""


def _ueberlappen(a, b) -> bool:
    return min(a["right"], b["right"]) - max(a["left"], b["left"]) > 1 and \
        min(a["bottom"], b["bottom"]) - max(a["top"], b["top"]) > 1


@pytest.mark.parametrize("variante", list(VARIANTEN))
def test_leiste_oben_in_jeder_zeilen_variante(variante, tmp_path):
    ui, (breite, hoehe), teile = VARIANTEN[variante]
    oben = next(n for n in SETS if TC.kachel_set_art(n)[1] == "oben")

    async def lauf(mit_set):
        app = _app({**ui, **({"tileSet": oben} if mit_set else {})}, struktur=STRUKTUR_WERTE)
        app.states["lf1"] = 54
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _visu(b, port, breite, hoehe, fehler)
                f = await pg.evaluate(FLAECHEN, teile)
                if mit_set:
                    await pg.screenshot(path=str(tmp_path / f"oben_{variante}.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return f
    mit, ohne = asyncio.run(lauf(True)), asyncio.run(lauf(False))

    s, tb = mit["schirm"], mit["tabs"]
    assert abs(tb["top"] - s["top"]) < 1 and abs(tb["width"] - s["width"]) < 1, (variante, tb, s)
    flaechen = {"grid": mit["grid"], **mit["teile"]}
    assert all(flaechen.values()), (variante, flaechen, mit["klassen"])
    for n, f in flaechen.items():
        assert f["top"] >= tb["bottom"] - 0.5 and f["bottom"] <= s["bottom"] + 0.5, (variante, n, f, tb)
    namen = list(flaechen)
    for i, a in enumerate(namen):
        for b in namen[i + 1:]:
            assert not _ueberlappen(flaechen[a], flaechen[b]), (variante, a, b, flaechen[a], flaechen[b])
    # Dieselben Flaechen wie mit der Leiste unten, nur um die Leiste nach unten verschoben
    for n, f in flaechen.items():
        o = ohne["grid"] if n == "grid" else ohne["teile"][n]
        assert abs(f["height"] - o["height"]) < 1 and abs(f["width"] - o["width"]) < 1, (variante, n, f, o)
        assert abs((f["top"] - tb["height"]) - o["top"]) < 1, (variante, n, f, o)


def test_seitenleiste_folgt_der_breite(tmp_path):
    """Leiste "links": unter LEISTE_LINKS.schmalUnter nur Symbole und die
    schmale Breite, darueber Symbol und Name - auch beim Drehen ohne Neuladen."""
    links = next(n for n in SETS if TC.kachel_set_art(n)[1] == "links")

    async def lauf():
        app = _app({"grid": "auto", "tileSet": links})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _visu(b, port, 1000, 750, fehler)
                masse = await pg.evaluate("LoxRaster.LEISTE_LINKS")
                breit = await pg.evaluate(SET_MESSEN)
                await pg.set_viewport_size({"width": masse["schmalUnter"] - 40, "height": 750})
                await pg.wait_for_function("document.querySelector('.screen').classList.contains('rail-schmal')")
                await pg.wait_for_timeout(300)
                schmal = await pg.evaluate(SET_MESSEN)
                await pg.screenshot(path=str(tmp_path / "links_schmal.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return masse, breit, schmal
    masse, breit, schmal = asyncio.run(lauf())
    assert breit["railW"] == f"{masse['breit']}px" and round(breit["tabs"]["width"]) == masse["breit"], breit
    assert all(breit["namen"]) and not breit["schmal"] and schmal["schmal"], (breit, schmal)
    assert schmal["railW"] == f"{masse['schmal']}px" and round(schmal["tabs"]["width"]) == masse["schmal"], schmal
    assert not any(schmal["namen"]), "nur Symbole"
    for t in (t for t in schmal["kacheln"] if t["left"] < schmal["grid"]["right"] - 1):
        assert t["left"] >= schmal["grid"]["left"] - 0.5 and t["right"] <= schmal["grid"]["right"] + 0.5, t


def test_neue_verbindung_mit_anderem_set():
    """Kommt bei einer neuen Verbindung ein anderes Set (oder keins), bleibt
    nichts vom vorigen stehen: weder seine Attribute noch seine Variablen."""
    kreis = next(n for n in SETS if "--an-text" in TC.kachel_set(n))

    async def lauf():
        app = _app({"grid": "auto", "tileSet": kreis})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _visu(b, port, 1000, 750, fehler)
                lesen = """() => [document.documentElement.getAttribute('data-kachelset-aufbau'),
                    document.documentElement.style.getPropertyValue('--an-text'),
                    document.documentElement.style.getPropertyValue('--kachel-radius')]"""
                vorher = await pg.evaluate(lesen)
                app.panels = W.App._sanitize_panels({"test": {"title": "Test", "ui": {"grid": "auto"}, "tabs": TABS}})
                for ws in list(app.conn_prof):
                    await ws.close()
                await pg.wait_for_function("!document.documentElement.hasAttribute('data-kachelset-aufbau')")
                nachher = await pg.evaluate(lesen)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return vorher, nachher
    vorher, nachher = asyncio.run(lauf())
    v = TC.kachel_set(kreis)
    assert vorher == [TC.kachel_set_art(kreis)[0], v["--an-text"], v["--kachel-radius"]], vorher
    assert nachher == [None, "", ""], nachher


ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/devices", W.api_save_devices),
          ("POST", "/api/panels", W.api_save_panels), ("POST", "/api/theme", W.api_save_theme)]
OFFEN = "document.querySelector('#offenTxt').textContent"


def test_kachel_set_im_konfigurator(cfg_ordner, tmp_path):
    """Auswahl aus /api/meta, Farbton und aktive Kachel nur beim Set mit
    Rechnung, Schnellwahl und Regler, der Kachel-Aufbau gilt mit Set nicht.
    Gespeichert wird nur, was vom Standard abweicht."""
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"flur": {"title": "Flur", "tabs": ["favoriten"]}}}),
                                            encoding="utf-8")
    liste = TC.kachel_set_liste()
    satz = next(s for s in liste if "farbton" in s)
    fest = next(s for s in liste if "farbton" not in s)
    wahl = next(f for f in satz["farbton"]["auswahl"] if f["wert"] != satz["farbton"]["standard"])
    anders = next(a["key"] for a in satz["aktiv"]["auswahl"] if a["key"] != satz["aktiv"]["standard"])

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(STRUKTUR)
        app.states = dict(STATES)
        app.panels = W.load_panels()
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler, st = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator("#plist .pitem", has_text="?panel=flur").click()
                await pg.locator(".stab[data-sub='aussehen']").click()
                st["optionen"] = await pg.eval_on_selector_all("#fTileSet option", "l => l.map(o => o.value)")
                st["ohne"] = [await pg.locator("#fKsExtra [data-ks-hue]").count(),
                              await pg.locator("#fTileLayout").is_disabled()]
                await pg.select_option("#fTileSet", fest["key"])
                st["fest"] = [await pg.locator("#fKsExtra [data-ks-hue]").count(),
                              await pg.locator("#fTileLayout").is_disabled(), await pg.locator("#fKsInfo").text_content()]
                await pg.select_option("#fTileSet", satz["key"])
                st["satz"] = [await pg.locator("#fKsExtra [data-ks-hue]").input_value(),
                              await pg.eval_on_selector_all("#fKsExtra [data-ks-ton]", "l => l.map(b => b.textContent)"),
                              await pg.eval_on_selector_all("#fKsExtra [data-ks-aktiv]", "l => l.map(b => b.textContent)")]
                await pg.locator(f"#fKsExtra [data-ks-ton='{wahl['wert']}']").click()
                st["ton"] = [await pg.locator("#fKsExtra [data-ks-hue]").input_value(),
                             await pg.locator("#fKsExtra [data-ks-wert]").text_content(),
                             await pg.locator(f"#fKsExtra [data-ks-ton='{wahl['wert']}']").get_attribute("class")]
                await pg.locator(f"#fKsExtra [data-ks-aktiv='{anders}']").click()
                await pg.screenshot(path=str(tmp_path / "konfigurator_kachel_set.png"), full_page=True)
                await pg.locator("#saveBtn").click()
                await pg.wait_for_function(OFFEN + " === 'Alles gespeichert'")
                st["gespeichert"] = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]["flur"]["ui"]
                # Regler auf den Standard: der Farbton faellt weg
                await pg.eval_on_selector("#fKsExtra [data-ks-hue]", "(r, v) => { r.value = v; r.dispatchEvent(new Event('input')); }",
                                          str(satz["farbton"]["standard"]))
                await pg.locator("#saveBtn").click()
                await pg.wait_for_function(OFFEN + " === 'Alles gespeichert'")
                st["standard"] = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]["flur"]["ui"]
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return st
    st = asyncio.run(lauf())
    assert st["optionen"] == [""] + [s["key"] for s in liste], st["optionen"]
    assert st["ohne"] == [0, False], "ohne Set kein Farbton, Kachel-Aufbau waehlbar"
    assert st["fest"][:2] == [0, True] and st["fest"][2] == fest["info"], st["fest"]
    assert st["satz"] == [str(satz["farbton"]["standard"]), [f["label"] for f in satz["farbton"]["auswahl"]],
                          [a["label"] for a in satz["aktiv"]["auswahl"]]], st["satz"]
    assert st["ton"][:2] == [str(wahl["wert"]), f"{wahl['wert']}°"] and "on" in st["ton"][2], st["ton"]
    assert st["gespeichert"] == {"tileSet": satz["key"], "tileHue": wahl["wert"], "tileActive": anders}, st["gespeichert"]
    assert st["standard"] == {"tileSet": satz["key"], "tileActive": anders}, st["standard"]


def test_assistent_rechnet_die_seitenleiste_mit():
    """Gerät einrichten, Schritt Aussehen: ein Set mit Seitenleiste links nimmt
    dem Raster Breite statt Hoehe, die Vorrechnung zeigt das (raster.js railW)."""
    links = next(n for n in SETS if TC.kachel_set_art(n)[1] == "links")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(STRUKTUR)
        app.states = dict(STATES)
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                erg = await pg.evaluate("""(set) => {
                  WZ.groesse = {name: 'ipad', vw: 1180, vh: 820, quelle: 'katalog'}; WZ.look = {};
                  const ohne = wzVorrechnung('1', 'auto'), festOhne = wzVorrechnung('1', '3x2');
                  WZ.look.tileSet = set;
                  const mit = wzVorrechnung('1', 'auto'), festMit = wzVorrechnung('1', '3x2');
                  const ref = LoxRaster.autoRaster(Object.assign({}, LoxRaster.VISU_MASSE,
                    {w: 1180 - LoxRaster.railBreite(1180), h: 820, tabsH: 0, ziel: wzZiel(), wachsen: kachelZiel().wachsen || 1}));
                  return {ohne, mit, festOhne, festMit, ref: [ref.cols, ref.rows, Math.round(ref.kb)],
                          rail: LoxRaster.railBreite(1180), gap: LoxRaster.VISU_MASSE.gap, tabsH: LoxRaster.VISU_MASSE.tabsH};
                }""", links)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return erg
    e = asyncio.run(lauf())
    assert [e["mit"]["cols"], e["mit"]["rows"], e["mit"]["px"]] == e["ref"], e
    assert e["mit"]["cols"] <= e["ohne"]["cols"], e
    # festes Raster: die Kacheln werden um die Leiste schmaler und um die fehlende Tab-Zeile hoeher
    assert abs(e["festOhne"]["kb"] - e["festMit"]["kb"] - e["rail"] / e["festMit"]["cols"]) < 0.01, e
    assert abs(e["festMit"]["kh"] - e["festOhne"]["kh"] - e["tabsH"] / e["festMit"]["rows"]) < 0.01, e
