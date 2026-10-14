"""Aussehen im Konfigurator (Chromium, iPad quer und hochkant): Die
Einstellungen stehen in Gruppen mit Ueberschrift - in der Ansicht Kachel-Set,
Farbe und Aufbau, Schrift, Hausuebersicht, Groessen; unter Vorgaben Grundfarbe, Sprache,
Schrift, Groessen. Das Kachel-Set steht vorn als Karten aus /api/meta (Name,
Beschreibung, Vorschau); mit Set weicht die Gruppe Grundfarbe und
Kachel-Aufbau einem Hinweis, weil beides dann aus dem Set kommt. Kein Feld
liegt auf einem anderen, nichts laeuft ueber den Rand, die Erklaerung der
Groessen ist zugeklappt. Der Assistent zeigt dieselben Karten. Bilder im
tmp_path (CI: Artefakt "screenshots")."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, visu_starten
from test_kachel_aufbau_browser import STATES, STRUKTUR
from test_kachel_set_browser import ROUTEN

import theme_colors as TC

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

# iPad quer und hochkant; hoch genug, dass die ganze Karte ins Bild passt
BREITEN = (1000, 768)
SETS = list(TC.KACHEL_SETS)

# Gruppen einer Karte: sichtbare Ueberschriften in Reihenfolge, Felder, die
# einander ueberlappen, und was breiter ist als die Karte
GRUPPEN = """(karte) => {
  const k = document.querySelector(karte), r = e => e.getBoundingClientRect(), kr = r(k);
  const sicht = e => e.offsetParent !== null;
  const gruppen = [...k.querySelectorAll('.agr')].filter(sicht);
  const felder = [...k.querySelectorAll('.agr .field, .agr .ks-karte')].filter(sicht).map(e => r(e));
  const ueber = [];
  felder.forEach((a, i) => felder.slice(i + 1).forEach(b => {
    if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1)
      ueber.push([a.toJSON(), b.toJSON()]); }));
  const breit = [...k.querySelectorAll('*')].filter(sicht).filter(e => r(e).right > kr.right + 1 || r(e).left < kr.left - 1)
    .map(e => e.tagName + '.' + e.className);
  const mehr = k.querySelector('.agr-mehr');
  return {titel: gruppen.map(g => g.querySelector('.grph').textContent), ueber, breit,
          mehrZu: !!mehr && !mehr.open, mehrText: mehr ? mehr.querySelector('summary').textContent : null,
          karten: [...k.querySelectorAll('[data-ks-set]')].map(b => [b.dataset.ksSet, b.querySelector('b').textContent,
                                                                     b.querySelector('.ks-info').textContent, b.getAttribute('aria-pressed')]),
          grundfarbe: !!k.querySelector('.baseSw') && sicht(k.querySelector('.baseSw'))};
}"""


def _laufen(cfg_ordner, tmp_path, ansichten, schritte):
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {
        name: {"title": name, "tabs": ["favoriten"], "ui": ui} for name, ui in ansichten.items()}}), encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(STRUKTUR)
        app.states = dict(STATES)
        app.panels = W.load_panels()
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler, erg = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                for breite in BREITEN:
                    pg = await b.new_page(viewport={"width": breite, "height": 3200}, locale="de-DE")
                    pg.on("pageerror", lambda e: fehler.append(str(e)))
                    await pg.goto(f"http://127.0.0.1:{port}/config")
                    await pg.wait_for_function(KONFIGURATOR_GELADEN)
                    await schritte(pg, breite, erg)
                    await pg.close()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return erg
    return asyncio.run(lauf())


def _ohne_ueberlappung(m, wo):
    assert not m["ueber"], (wo, m["ueber"])
    assert not m["breit"], (wo, m["breit"])


def test_ansicht_in_gruppen(cfg_ordner, tmp_path):
    ansichten = {"ohne": {}, **{n: {"tileSet": n} for n in SETS}}

    async def schritte(pg, breite, erg):
        for name in ansichten:
            await pg.locator("#plist .pitem", has_text=f"?panel={name}").click()
            await pg.locator(".stab[data-sub='aussehen']").click()
            karte = ".spane[data-sub='aussehen'] .card"
            await pg.wait_for_selector(karte + " [data-ks-set]")
            erg[(name, breite)] = await pg.evaluate(GRUPPEN, karte)
            await pg.locator(karte).first.screenshot(path=str(tmp_path / f"aussehen_{name}_{breite}.png"))
        # Umschalten ohne neu zu zeichnen: die Gruppen folgen der Karte
        await pg.locator("#plist .pitem", has_text="?panel=ohne").click()
        await pg.locator(".stab[data-sub='aussehen']").click()
        await pg.locator(f"#pconfHost [data-ks-set='{SETS[0]}']").click()
        erg[("umgeschaltet", breite)] = await pg.evaluate(GRUPPEN, ".spane[data-sub='aussehen'] .card")
        await pg.locator("#pconfHost .agr-mehr summary").click()
        erg[("aufgeklappt", breite)] = await pg.locator("#pconfHost .agr-mehr p").is_visible()
    erg = _laufen(cfg_ordner, tmp_path, ansichten, schritte)

    liste = TC.kachel_set_liste()
    for breite in BREITEN:
        for name in ansichten:
            m, wo = erg[(name, breite)], (name, breite)
            _ohne_ueberlappung(m, wo)
            assert m["titel"] == ["Kachel-Set", "Farbe und Aufbau", "Schrift", "Hausübersicht", "Größen"], (wo, m["titel"])
            # Karten aus /api/meta, die gewaehlte gedrueckt
            assert [k[0] for k in m["karten"]] == [""] + [s["key"] for s in liste], (wo, m["karten"])
            assert [k[1:3] for k in m["karten"][1:]] == [[s["label"], s["info"]] for s in liste], (wo, m["karten"])
            gewaehlt = "" if name == "ohne" else name
            assert [k[0] for k in m["karten"] if k[3] == "true"] == [gewaehlt], (wo, m["karten"])
            # Grundfarbe nur ohne Set
            assert m["grundfarbe"] == (name == "ohne"), wo
            assert m["mehrZu"] and m["mehrText"] == "Was bedeuten die Größen?", wo
        u = erg[("umgeschaltet", breite)]
        assert not u["grundfarbe"] and [k[0] for k in u["karten"] if k[3] == "true"] == [SETS[0]], u
        _ohne_ueberlappung(u, ("umgeschaltet", breite))
        assert erg[("aufgeklappt", breite)]


def test_vorgaben_und_assistent(cfg_ordner, tmp_path):
    async def schritte(pg, breite, erg):
        await pg.locator(".rub", has_text="Vorgaben").click()
        karte = ".spane[data-sub='appearance'] .card"
        await pg.wait_for_selector(karte + " .agr")
        erg[("vorgaben", breite)] = await pg.evaluate(GRUPPEN, karte)
        await pg.locator(karte).screenshot(path=str(tmp_path / f"vorgaben_{breite}.png"))
        # Assistent, Schritt Aussehen: dieselben Karten, mit Set keine Grundfarbe
        await pg.evaluate("() => { setRubric('pconf'); wzOpen(); WZ.art = 'neu'; WZ.step = wzFlow().indexOf('aussehen'); wzRender(); }")
        erg[("assistent", breite)] = await pg.evaluate(
            "() => [[...document.querySelectorAll('#wzBody [data-ks-set]')].map(b => b.dataset.ksSet),"
            " !!document.querySelector('#wzBody [data-wbase]')]")
        await pg.locator(f"#wzBody [data-ks-set='{SETS[0]}']").click()
        erg[("assistent_set", breite)] = await pg.evaluate(
            "() => [WZ.look.tileSet, !!document.querySelector('#wzBody [data-wbase]'),"
            " document.querySelector('#wzBody [data-ks-set].on').dataset.ksSet]")
        await pg.locator("#wzBody").screenshot(path=str(tmp_path / f"assistent_aussehen_{breite}.png"))
    erg = _laufen(cfg_ordner, tmp_path, {"flur": {}}, schritte)

    for breite in BREITEN:
        m = erg[("vorgaben", breite)]
        _ohne_ueberlappung(m, ("vorgaben", breite))
        assert m["titel"] == ["Grundfarbe", "Sprache", "Schrift", "Größen"], m["titel"]
        assert m["grundfarbe"] and m["mehrZu"] and not m["karten"], m
        assert erg[("assistent", breite)] == [[""] + SETS, True], erg[("assistent", breite)]
        assert erg[("assistent_set", breite)] == [SETS[0], False, SETS[0]], erg[("assistent_set", breite)]
