"""Kachel-Sets (ui.tileSet) in Chromium: jedes Set aus theme_colors.KACHEL_SETS
am iPad (1000 x 750, automatisches Raster) und am 4"-Panel (480 x 480, festes
2 x 2 ohne Split). Gemessen wird gegen die Werte des Sets selbst
(theme_colors.kachel_set) und seine Masse (KACHEL_SETS "masse", schmal oder
nicht), keine zweite Liste im Test: Flaeche, aktive Kachel, Symbol, Kreis,
Tab-Leiste je nach Art (pille, oben, links) und Aufbau (lx, mitte, kreis),
der Zustand vorn auch bei Schaltern. Nichts laeuft ueber, keine Kachel wird
abgeschnitten; Leisten, Rahmen und Seitenleiste nehmen, was der Entwurf
zeichnet, das Raster rechnet es mit. Die Leiste "oben" steht in jeder
Zeilen-Variante des Kastens (Kopfzeile, Werteleiste, Split quer und
hochkant) ueber allem anderen, ohne etwas zu verdecken, das Feld im Rahmen.
Dazu der Konfigurator (Auswahl, Farbton nur bei touch, Nachgerechnet,
Speichern), der Assistent und der Wechsel des Sets bei einer neuen
Verbindung. Die Bilder aller Sets landen im tmp_path (CI: Artefakt
"screenshots")."""
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
SCHMAL_UNTER = 600   # raster.js SCHMAL_UNTER, im Test der Seitenleiste aus der Visu gelesen
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
  const back = document.getElementById('tabback');
  return {
    attr: [html.getAttribute('data-kachelset'), html.getAttribute('data-kachelset-aufbau'), html.getAttribute('data-kachelset-leiste')],
    aus: cs(t('MB')).backgroundColor, an: cs(t('FS')).backgroundColor,
    symbolAus: cs(t('MB').querySelector('.ico')).color, symbolAn: cs(t('FS').querySelector('.ico')).color,
    textAn: cs(t('FS').querySelector('.name')).color, zweitAn: cs(t('FS').querySelector('.sub')).color,
    kreisAus: kreis(t('MB')) ? cs(kreis(t('MB'))).backgroundColor : null,
    kreisAn: kreis(t('FS')) ? cs(kreis(t('FS'))).backgroundColor : null,
    kreisD: kreis(t('MB')) ? r(kreis(t('MB'))).width : null, zv: t('FS').classList.contains('zv'),
    backSymbol: !!(back && back.querySelector('svg')), backLetzter: !!back && tabs.lastElementChild === back,
    pilleH: getComputedStyle(tabs, '::before').height, gridFarbe: cs(grid).backgroundColor, schirmFarbe: cs(sc).backgroundColor,
    rahmen: [cs(sc).paddingLeft, cs(sc).paddingRight, cs(sc).paddingBottom].map(parseFloat),
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
    schmal: sc.classList.contains('schmal'),
    kacheln: [...grid.querySelectorAll('.tile[data-id]')].filter(k => r(k).width > 0).map(k => r(k).toJSON()),
  };
}"""


def _mass(name: str, mass: str, breite: int) -> float | None:
    """Mass eines Sets fuer diese Breite: "-schmal" unter SCHMAL_UNTER, wie
    raster.js setMass(); None, wenn das Set es nicht nennt."""
    m = TC.KACHEL_SETS[name].get("masse") or {}
    wert = m.get(mass + "-schmal") if breite < SCHMAL_UNTER and mass + "-schmal" in m else m.get(mass)
    return float(wert.rstrip("px")) if wert else None


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
        assert mit["textAn"] == mit["symbolAn"] == _rgb(v["--kachel-an-ink"]), mit
        assert mit["zweitAn"] == _rgb(v["--kachel-an-muted"]), mit
        assert mit["texte"] == ["Ein", "Frostsicherung · Zentral"] and not mit["raumKopf"], mit["texte"]
    else:
        # Zustand vorn auch beim Schalter, in der Farbe "an"
        assert mit["raumKopf"] and mit["zv"], "Raum oben rechts im Kopf, Zustand vorn"
        assert mit["texte"] == ["Frostsicherung", "Ein"] and mit["zweitAn"] == _rgb(v.get("--an-text", v["--glow"])), mit
    if aufbau == "kreis":
        assert mit["kreisAus"] == _rgb(v["--taste"]) and mit["kreisAn"] == _rgb(v["--glow"]), mit
        assert mit["symbolAn"] == _rgb(v["--kreis-an-symbol"]), mit
        assert abs(mit["kreisD"] - _mass(name, "--kreis-d", breite)) < 0.6, mit["kreisD"]
    else:
        assert mit["kreisAus"] is None and mit["kreisAn"] is None
    assert mit["backSymbol"], "Zurueck ist ein Symbol wie die Tabs"
    # Tab-Leiste je nach Art
    s, tb, g = mit["schirm"], mit["tabs"], mit["grid"]
    assert mit["schmal"] == (breite < SCHMAL_UNTER), "schmale Schirme nehmen die Masse mit -schmal"
    if leiste in ("pille", "oben"):
        assert abs(tb["height"] - _mass(name, "--tabs-hoehe", breite)) < 0.6, (tb, name)
    if leiste == "pille":
        assert mit["pille"] == _rgb(v["--tabbar"]) and abs(tb["bottom"] - s["bottom"]) < 1, mit
        assert abs(float(mit["pilleH"].rstrip("px")) - _mass(name, "--pille-h", breite)) < 0.6, mit["pilleH"]
    if leiste == "oben":
        # Rahmen (--rahmen) um das Feld der Kacheln (--screen), die Tabs darauf
        assert mit["schirmFarbe"] == _rgb(v["--rahmen"]) and mit["gridFarbe"] == _rgb(v["--screen"]), mit
        assert mit["rahmen"] == [_mass(name, "--rahmen-seite", breite)] * 2 + [_mass(name, "--rahmen-unten", breite)], mit
        assert mit["tabAn"] == _rgb(v["--tab-an"]) and mit["tabAus"] == _rgb(v["--tab-aus"]), mit
        assert abs(tb["top"] - s["top"]) < 1 and g["top"] >= tb["bottom"] - 0.5, (tb, g)
        assert g["bottom"] <= s["bottom"] - mit["rahmen"][2] + 0.5, (g, s)
        assert not any(mit["namen"]), "nur Symbole"
    if leiste == "links":
        assert abs(tb["left"] - s["left"]) < 1 and tb["height"] >= s["height"] - 1, tb
        assert mit["leisteFarbe"] == _rgb(v["--tabbar"]), mit
        assert abs(tb["width"] - _mass(name, "--rail-breite", breite)) < 0.6 and g["left"] >= tb["right"] - 0.5, (tb, g)
        assert all(n is None for n in mit["namen"]) == (breite < SCHMAL_UNTER), mit["namen"]
        assert mit["backLetzter"], "Zurueck steht unten"
    # Nichts laeuft ueber, keine Kachel abgeschnitten
    assert all(e["ueberlauf"] <= 1 and e["textUnten"] <= 0 for e in k.values()), \
        {i: (e["ueberlauf"], e["textUnten"]) for i, e in k.items()}
    # (waagerechte Seiten: die Kacheln der naechsten Seiten liegen rechts daneben)
    for t in (t for t in mit["kacheln"] if t["left"] < g["right"] - 1):
        assert t["left"] >= g["left"] - 0.5 and t["right"] <= g["right"] + 0.5, (t, g)
    # Leiste und Raster liegen im Kasten, ohne sich zu decken; mit weniger
    # Flaeche (Seitenleiste, Rahmen) werden es hoechstens weniger Spalten
    assert g["right"] <= s["right"] + 0.5 and g["bottom"] <= s["bottom"] + 0.5, (g, s)
    if leiste == "links" or "--rahmen-seite" in (TC.KACHEL_SETS[name].get("masse") or {}):
        assert int(mit["spalten"]) <= int(ohne["spalten"]), (mit["spalten"], ohne["spalten"])


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
          kacheln: [...document.querySelectorAll('#grid .tile[data-id]')].map(k => k.getBoundingClientRect().toJSON()),
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
    mit = asyncio.run(lauf(True))

    s, tb = mit["schirm"], mit["tabs"]
    seite, unten = _mass(oben, "--rahmen-seite", breite), _mass(oben, "--rahmen-unten", breite)
    # die Leiste oben im Rahmen, ueber die Breite des Felds
    assert abs(tb["top"] - s["top"]) < 1 and abs(tb["width"] - (s["width"] - 2 * seite)) < 1, (variante, tb, s)
    flaechen = {"grid": mit["grid"], **mit["teile"]}
    assert all(flaechen.values()), (variante, flaechen, mit["klassen"])
    g = mit["grid"]
    for k in (k for k in mit["kacheln"] if k["left"] < g["right"] - 1 and k["top"] < g["bottom"] - 1):
        assert k["right"] <= g["right"] + 0.5, (variante, k, g)
    for n, f in flaechen.items():
        assert f["top"] >= tb["bottom"] - 0.5 and f["bottom"] <= s["bottom"] + 0.5, (variante, n, f, tb)
    namen = list(flaechen)
    for i, a in enumerate(namen):
        for b in namen[i + 1:]:
            assert not _ueberlappen(flaechen[a], flaechen[b]), (variante, a, b, flaechen[a], flaechen[b])
    # Alles innerhalb des Rahmens; die Leiste behaelt die Hoehe aus dem Set
    for n, f in flaechen.items():
        assert f["left"] >= s["left"] + seite - 0.5 and f["right"] <= s["right"] - seite + 0.5, (variante, n, f)
        assert f["bottom"] <= s["bottom"] - unten + 0.5, (variante, n, f)
    assert abs(tb["height"] - _mass(oben, "--tabs-hoehe", breite)) < 0.6, (variante, tb)


def test_seitenleiste_folgt_der_breite(tmp_path):
    """Leiste "links": unter SCHMAL_UNTER nur Symbole und die schmale Breite
    aus dem Set, darueber Symbol und Name - auch beim Drehen ohne Neuladen."""
    links = next(n for n in SETS if TC.kachel_set_art(n)[1] == "links")

    async def lauf():
        app = _app({"grid": "auto", "tileSet": links})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _visu(b, port, 1000, 750, fehler)
                unter = await pg.evaluate("LoxRaster.SCHMAL_UNTER")
                breit = await pg.evaluate(SET_MESSEN)
                await pg.set_viewport_size({"width": unter - 40, "height": 750})
                await pg.wait_for_function("document.querySelector('.screen').classList.contains('schmal')")
                await pg.wait_for_timeout(300)
                schmal = await pg.evaluate(SET_MESSEN)
                await pg.screenshot(path=str(tmp_path / "links_schmal.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return unter, breit, schmal
    unter, breit, schmal = asyncio.run(lauf())
    assert unter == SCHMAL_UNTER
    assert abs(breit["tabs"]["width"] - _mass(links, "--rail-breite", 1000)) < 0.6, breit
    assert all(breit["namen"]) and not breit["schmal"] and schmal["schmal"], (breit, schmal)
    assert abs(schmal["tabs"]["width"] - _mass(links, "--rail-breite", unter - 40)) < 0.6, schmal
    assert not any(schmal["namen"]), "nur Symbole"
    for t in (t for t in schmal["kacheln"] if t["left"] < schmal["grid"]["right"] - 1):
        assert t["left"] >= schmal["grid"]["left"] - 0.5 and t["right"] <= schmal["grid"]["right"] + 0.5, t



@pytest.mark.parametrize("name", [n for n in SETS if TC.kachel_set_art(n)[1] in ("pille", "oben")])
def test_leiste_auf_niedrigem_schirm(name, tmp_path):
    """Breit, aber niedrig (Fenster am Mac, flaches Display): die Tab-Leiste
    nimmt ihre "-schmal"-Masse, sonst nichts - der Schirm bleibt nicht
    schmal. Der Konfigurator rechnet dieselbe Hoehe vor (raster.js leisteMass)."""
    m = TC.KACHEL_SETS[name]["masse"]
    breite, hoehe = 920, SCHMAL_UNTER - 140
    mit, _ = _messen({"grid": "auto", "tileSet": name}, breite, hoehe, tmp_path, f"niedrig_{name}")
    hoch, _ = _messen({"grid": "auto", "tileSet": name}, breite, SCHMAL_UNTER, tmp_path, f"hoch_{name}")

    async def vorrechnung():
        app = _app({"grid": "auto", "tileSet": name})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _visu(b, port, breite, hoehe, fehler)
                werte = await pg.evaluate("([m, w, h]) => ({tabs: LoxRaster.leisteMass(m, '--tabs-hoehe', w, h, 0),"
                                          " rahmen: LoxRaster.leisteMass(m, '--rahmen-seite', w, h, 0),"
                                          " niedrig: document.querySelector('.screen').classList.contains('niedrig')})",
                                          [m, breite, hoehe])
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return werte
    v = asyncio.run(vorrechnung())
    klein = float(m["--tabs-hoehe-schmal"].rstrip("px"))
    assert not mit["schmal"] and v["niedrig"], (mit["schmal"], v)
    assert abs(mit["tabs"]["height"] - klein) < 0.6 and v["tabs"] == klein, (mit["tabs"], v)
    assert abs(hoch["tabs"]["height"] - float(m["--tabs-hoehe"].rstrip("px"))) < 0.6, hoch["tabs"]
    if "--pille-h-schmal" in m:
        assert abs(float(mit["pilleH"].rstrip("px")) - float(m["--pille-h-schmal"].rstrip("px"))) < 0.6, mit["pilleH"]
    if "--rahmen-seite" in m:
        # der Rahmen haengt weiter an der Breite
        assert mit["rahmen"][0] == float(m["--rahmen-seite"].rstrip("px")) == v["rahmen"], (mit["rahmen"], v)
    assert mit["grid"]["bottom"] <= mit["tabs"]["top"] + 0.5 or mit["tabs"]["bottom"] <= mit["grid"]["top"] + 0.5, mit

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
          ("POST", "/api/panels", W.api_save_panels), ("POST", "/api/theme", W.api_save_theme),
          ("GET", "/api/kachelset", W.api_kachelset)]
OFFEN = "document.querySelector('#offenTxt').textContent"


def test_kachel_set_im_konfigurator(cfg_ordner, tmp_path):
    """Auswahl als Karten aus /api/meta (Beschreibung, Vorschau), Farbton und
    aktive Kachel nur beim Set mit Rechnung, Schnellwahl und Regler; mit Set
    weicht die Gruppe Grundfarbe und Kachel-Aufbau einem Hinweis, die
    Vorschau der Karte zieht mit dem Farbton mit. Gespeichert wird nur, was
    vom Standard abweicht."""
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"flur": {"title": "Flur", "tabs": ["favoriten"]}}}),
                                            encoding="utf-8")
    liste = TC.kachel_set_liste()
    satz = next(s for s in liste if "farbton" in s)
    fest = next(s for s in liste if "farbton" not in s)
    wahl = next(f for f in satz["farbton"]["auswahl"] if f["wert"] != satz["farbton"]["standard"])
    anders = next(a["key"] for a in satz["aktiv"]["auswahl"] if a["key"] != satz["aktiv"]["standard"])
    # Nachgerechnet: die Werte des Servers, deutsch mit Komma
    nachgerechnet = [f"{k['wert']:.1f}".replace(".", ",") + " : 1"
                     for k in TC.kachel_set_pruefung(satz["key"], wahl["wert"], anders)]

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

                async def sichtbar():
                    return [await pg.locator("#fAgFarbe").is_visible(), await pg.locator("#fAgAusSet").is_visible()]
                st["optionen"] = await pg.eval_on_selector_all("#pconfHost [data-ks-set]", "l => l.map(o => o.dataset.ksSet)")
                st["ohne"] = [await pg.locator("#fKsExtra [data-ks-hue]").count(),
                              await pg.locator("#fTileLayout").is_disabled(), *await sichtbar()]
                await pg.locator(f"#pconfHost [data-ks-set='{fest['key']}']").click()
                st["fest"] = [await pg.locator("#fKsExtra [data-ks-hue]").count(),
                              await pg.locator("#fTileLayout").is_disabled(), *await sichtbar(),
                              await pg.locator(f"#pconfHost [data-ks-set='{fest['key']}'] .ks-info").text_content(),
                              await pg.locator(f"#pconfHost [data-ks-set='{fest['key']}']").get_attribute("aria-pressed")]
                await pg.locator(f"#pconfHost [data-ks-set='{satz['key']}']").click()
                st["satz"] = [await pg.locator("#fKsExtra [data-ks-hue]").input_value(),
                              await pg.eval_on_selector_all("#fKsExtra [data-ks-ton]", "l => l.map(b => b.textContent)"),
                              await pg.eval_on_selector_all("#fKsExtra [data-ks-aktiv]", "l => l.map(b => b.textContent)")]
                await pg.locator(f"#fKsExtra [data-ks-ton='{wahl['wert']}']").click()
                st["ton"] = [await pg.locator("#fKsExtra [data-ks-hue]").input_value(),
                             await pg.locator("#fKsExtra [data-ks-wert]").text_content(),
                             await pg.locator(f"#fKsExtra [data-ks-ton='{wahl['wert']}']").get_attribute("class")]
                await pg.locator(f"#fKsExtra [data-ks-aktiv='{anders}']").click()
                # auf die Antwort zu genau dieser Wahl warten (die zur Schnellwahl kam vorher)
                await pg.wait_for_function("(soll) => JSON.stringify([...document.querySelectorAll("
                                           "'#fKsExtra [data-ks-paar] b')].map(b => b.textContent)) === soll",
                                           arg=json.dumps(nachgerechnet, ensure_ascii=False, separators=(",", ":")))
                st["pruefung"] = await pg.eval_on_selector_all("#fKsExtra [data-ks-paar] b", "l => l.map(b => b.textContent)")
                st["wert"] = await pg.locator("#fKsExtra [data-ks-wert]").text_content()
                # die Karte zeigt den gewaehlten Farbton (Kachel der Vorschau)
                st["mini"] = await pg.eval_on_selector(f"#pconfHost [data-ks-set='{satz['key']}'] [data-ks-mini] i",
                                                       "i => getComputedStyle(i).backgroundColor")
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
    assert st["ohne"] == [0, False, True, False], "ohne Set kein Farbton, Grundfarbe und Kachel-Aufbau waehlbar"
    assert st["fest"] == [0, True, False, True, fest["info"], "true"], st["fest"]
    assert st["satz"] == [str(satz["farbton"]["standard"]), [f["label"] for f in satz["farbton"]["auswahl"]],
                          [a["label"] for a in satz["aktiv"]["auswahl"]]], st["satz"]
    assert st["ton"][0] == str(wahl["wert"]) and st["ton"][1].startswith(f"{wahl['wert']}°") and "on" in st["ton"][2], st["ton"]
    assert st["pruefung"] == nachgerechnet, st["pruefung"]
    assert st["mini"] == _rgb(TC.kachel_set_vorschau(satz["key"], wahl["wert"], anders)["kachel"]), st["mini"]
    assert st["wert"] == f"{wahl['wert']}° · " + TC.kachel_set_kachel(satz["key"], wahl["wert"], anders), st["wert"]
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
                erg = await pg.evaluate("""([set, rail]) => {
                  WZ.groesse = {name: 'ipad', vw: 1180, vh: 820, quelle: 'katalog'}; WZ.look = {};
                  const ohne = wzVorrechnung('1', 'auto'), festOhne = wzVorrechnung('1', '3x2');
                  WZ.look.tileSet = set;
                  const mit = wzVorrechnung('1', 'auto'), festMit = wzVorrechnung('1', '3x2');
                  const ref = LoxRaster.autoRaster(Object.assign({}, LoxRaster.VISU_MASSE,
                    {w: 1180 - rail, h: 820, tabsH: 0, ziel: wzZiel(), wachsen: kachelZiel().wachsen || 1}));
                  return {ohne, mit, festOhne, festMit, ref: [ref.cols, ref.rows, Math.round(ref.kb)],
                          rail: rail, tabsH: LoxRaster.VISU_MASSE.tabsH};
                }""", [links, _mass(links, "--rail-breite", 1180)])
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
