"""Breite Kachel mit Tasten (Audio) in Chromium: Im neuen Aufbau ist ihre
rechte Haelfte die Spieler-Spalte - oben Sender-Logo bzw. Cover, darunter die
Tasten (zurueck, Play/Pause, vor); Kopf und Text bleiben links. So stehen die
Tasten auch auf der flachen 2x1-Kachel am 4"-Panel, wo sie unter dem Text
keinen Platz haetten. Das Cover kommt ueber /cover vom Server (dieselbe
Quelle wie auf der Detailseite) und faellt weg, wenn es kleiner wuerde als
SPIELER_COVER_MIN; ohne Cover stehen die Tasten mittig. Gilt fuer jeden
Aufbau des neuen Kachel-Layouts (ohne Set, "mitte", "kreis"), der klassische
bleibt, wie er ist. Ein Tipp auf die Taste schaltet, der Rest der Kachel
oeffnet die Detailseite. Bilder im tmp_path (CI: Artefakt "screenshots")."""
import asyncio

import pytest

from lox import W, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

COVER_URL = "http://audioserver/cover/sender.png"
# Sender-Logo, wie es der Audioserver liefert: fetch_cover() gibt Bytes und Typ
LOGO = (b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
        b'<rect width="64" height="64" fill="#c8611c"/></svg>', "image/svg+xml")


def _c(uuid, name, typ, states, **extra):
    return {"name": name, "type": typ, "uuidAction": uuid, "room": "r1", "cat": "c1",
            "isFavorite": True, "states": states, **extra}


STRUKTUR = {
    "rooms": {"r1": {"name": "Küche"}}, "cats": {"c1": {"name": "Allgemein"}},
    "controls": {
        "AZ": _c("AZ", "Radio Küche", "AudioZoneV2", {"playState": "az1", "songName": "az2", "cover": "az3"}),
        "L1": _c("L1", "Licht Decke", "Switch", {"active": "l1"}),
        "L2": _c("L2", "Licht Insel", "Switch", {"active": "l2"}),
    },
}
STATES = {"az1": 2, "az2": "Hitradio Ö3", "az3": COVER_URL, "l1": 0, "l2": 1}

AUFBAUTEN = {"neu": {}, "mitte": {"tileSet": "touch"}, "kreis": {"tileSet": "kreide"}}
GERAETE = {"4zoll": (480, 480, {"split": False}), "ipad": (1000, 750, {"grid": "auto"})}

MESSEN = """() => {
  const t = document.querySelector('#grid .tile[data-id="AZ"]'), r = e => e ? e.getBoundingClientRect().toJSON() : null;
  const tc = t.querySelector('.tctrls'), cv = t.querySelector('.tcover');
  const sicht = e => !!e && e.offsetParent !== null && getComputedStyle(e).display !== 'none';
  return {klassen: [...t.classList], kachel: r(t), kopf: r(t.querySelector('.head')), text: r(t.querySelector('.body')),
          tasten: sicht(tc) ? [...tc.querySelectorAll('.tb')].map(b => r(b)) : [],
          cover: sicht(cv) ? r(cv) : null, coverGeladen: !!cv && cv.complete && cv.naturalWidth > 0,
          spalte: r(t.querySelector('.tplay')), ks: parseFloat(getComputedStyle(document.querySelector('.screen')).getPropertyValue('--ks')) || 1,
          pad: parseFloat(getComputedStyle(t).paddingTop), gap: parseFloat(getComputedStyle(t).getPropertyValue('--spgap')) || 0};
}"""


def _app(ui, states=STATES):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    app.states = dict(states)
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"], "ui": ui,
                                                  "tiles": {"AZ": {"w": 2}}}})
    befehle = []

    async def command(uuid, cmd, pin=None):
        befehle.append((uuid, cmd))
        return "200"

    async def fetch_cover(url):
        return LOGO if url == COVER_URL else None
    app.command = command
    app.fetch_cover = fetch_cover
    return app, befehle


def _laufen(ui, breite, hoehe, tmp_path=None, bild=None, states=STATES, klicken=False):
    async def lauf():
        app, befehle = _app(ui, states)
        runner, port, bc = await visu_starten(app, [("GET", "/cover", W.cover_handler)])
        fehler, erg = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": breite, "height": hoehe})
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector('#grid .tile[data-id="AZ"]', state="attached")
                await pg.evaluate("wake()")
                await pg.wait_for_timeout(800)
                erg = await pg.evaluate(MESSEN)
                if tmp_path:
                    await pg.screenshot(path=str(tmp_path / f"{bild}.png"))
                if klicken:
                    await pg.locator('#grid .tile[data-id="AZ"] .tb[data-c="1"]').click()
                    await pg.wait_for_timeout(400)
                    erg["route"] = await pg.evaluate("JSON.stringify(stack[stack.length-1])")
                    erg["befehle"] = list(befehle)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return erg
    return asyncio.run(lauf())


def _pruefe_spalte(m, wo):
    k, sp = m["kachel"], m["spalte"]
    mitte = k["left"] + k["width"] / 2
    assert "spieler" in m["klassen"], (wo, m["klassen"])
    # Die Spalte ist die rechte Haelfte - breiter nur, wenn die Tasten dort
    # nicht in Mindestgroesse passten (.spbreit); Kopf und Text enden vor ihr
    if "spbreit" in m["klassen"]:
        assert sp["left"] < mitte, (wo, sp, mitte)
    else:
        assert abs(sp["left"] - mitte) < 1, (wo, sp, mitte)
    assert sp["right"] <= k["right"] + 0.5, (wo, sp, k)
    for teil in ("kopf", "text"):
        assert m[teil]["right"] <= sp["left"] + 0.5, (wo, teil, m[teil], sp)
    # drei Tasten nebeneinander in der Spalte, innerhalb der Kachel, nie unter
    # der Mindestgroesse eines Touch-Ziels
    assert len(m["tasten"]) == 3, (wo, m)
    for t in m["tasten"]:
        assert t["left"] >= sp["left"] - 0.5 and t["right"] <= sp["right"] + 0.5, (wo, t, sp)
        assert t["top"] >= k["top"] - 0.5 and t["bottom"] <= k["bottom"] + 0.5, (wo, t, k)
        assert min(t["width"], t["height"]) >= 34 - 0.5, (wo, t)
    assert len({round(t["top"]) for t in m["tasten"]}) == 1, (wo, m["tasten"])


@pytest.mark.parametrize("geraet", list(GERAETE))
@pytest.mark.parametrize("aufbau", list(AUFBAUTEN))
def test_cover_und_tasten_in_der_breiten_kachel(aufbau, geraet, tmp_path):
    breite, hoehe, ui = GERAETE[geraet]
    m = _laufen({**ui, **AUFBAUTEN[aufbau]}, breite, hoehe, tmp_path, f"spieler_{aufbau}_{geraet}")
    wo = (aufbau, geraet)
    _pruefe_spalte(m, wo)
    # Cover, wenn die Spalte ueber den Tasten Platz dafuer hat: aus der Regel
    # in spielerEinpassen() gerechnet, nicht als feste Antwort je Geraet
    leiste = m["tasten"][0]["height"]
    frei = m["kachel"]["height"] - 2 * m["pad"] - leiste - m["gap"]
    if frei >= 36 * m["ks"]:
        assert m["cover"] and m["coverGeladen"], (wo, m)
        assert m["cover"]["bottom"] <= m["tasten"][0]["top"] + 0.5, (wo, m["cover"], m["tasten"][0])
        assert m["cover"]["left"] >= m["spalte"]["left"] - 0.5 and m["cover"]["right"] <= m["spalte"]["right"] + 0.5, wo
    else:
        assert m["cover"] is None and "ohnecover" in m["klassen"], (wo, m)


def test_flache_kachel_am_4zoll_panel_behaelt_die_tasten(tmp_path):
    """3 Zeilen am 4"-Panel: unter dem Text haette die Tastenleiste keinen Platz
    (ohne Spieler-Spalte fielen die Tasten weg), daneben schon."""
    m = _laufen({"split": False, "cols": 2, "rows": 3}, 480, 480, tmp_path, "spieler_flach_4zoll")
    _pruefe_spalte(m, "flach")
    assert "ohnetasten" not in m["klassen"], m["klassen"]


def test_enge_kachel_macht_die_spalte_breiter(tmp_path):
    """800 x 480 mit 3 x 3 und Fuellen: 2x1-Kachel von rund 250 px. In der
    halben Kachel waeren die Tasten schmaler als ein Touch-Ziel - die Spalte
    wird breiter, der Text rueckt zusammen."""
    m = _laufen({"cols": 3, "rows": 3, "fill": True}, 800, 480, tmp_path, "spieler_eng")
    _pruefe_spalte(m, "eng")
    assert "spbreit" in m["klassen"], m["klassen"]


def test_ohne_cover_stehen_die_tasten_mittig(tmp_path):
    m = _laufen({"grid": "auto"}, 1000, 750, tmp_path, "spieler_ohne_cover", states={**STATES, "az3": ""})
    _pruefe_spalte(m, "ohne cover")
    assert m["cover"] is None, m
    t, s = m["tasten"][0], m["spalte"]
    assert abs((t["top"] + t["bottom"]) / 2 - (s["top"] + s["bottom"]) / 2) < 1, (t, s)


def test_taste_schaltet_die_kachel_oeffnet_die_detailseite():
    m = _laufen({"grid": "auto"}, 1000, 750, klicken=True)
    assert m["befehle"] == [("AZ", "pause")], m["befehle"]
    assert '"view":"tab"' in m["route"], m["route"]   # die Taste oeffnet nichts


def test_klassischer_aufbau_bleibt():
    m = _laufen({"grid": "auto", "tileLayout": "classic"}, 1000, 750)
    assert "spieler" not in m["klassen"] and m["spalte"] is None and m["cover"] is None, m


EDITOR = """() => [...document.querySelectorAll('#seHost .se-t')].map(t => {
  const r = e => e ? e.getBoundingClientRect().toJSON() : null, img = t.querySelector('.se-play img');
  return {id: t.dataset.seT, spieler: t.classList.contains('se-spieler'), kachel: r(t), spalte: r(t.querySelector('.se-play')),
          tasten: t.querySelectorAll('.se-tasten i').length, cover: img ? img.getAttribute('src') : null,
          geladen: !!img && img.complete && img.naturalWidth > 0, name: r(t.querySelector('.se-tn'))}; })"""


@pytest.mark.parametrize("klassisch", [False, True])
def test_seiten_editor_zeigt_die_spieler_spalte(klassisch, cfg_ordner, tmp_path):
    """Der Seiten-Editor zeigt die breite Kachel wie die Visu: rechts das Cover
    (aus /api/meta, dieselbe Rechnung wie die Kachel) und so viele Tasten, wie
    die Kachel hat; im klassischen Aufbau nicht."""
    import json
    from lox import KONFIGURATOR_GELADEN
    ui = {"split": False, **({"tileLayout": "classic"} if klassisch else {})}
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"kueche": {
        "title": "Küche", "tabs": ["auswahl", "favoriten"], "ui": ui,
        "pickTabs": [{"name": "Küche", "picks": ["AZ", "L1", "L2"], "byRoom": False,
                      "layout": [{"id": "AZ", "w": 2}, {"id": "L1"}, {"id": "L2"}]}]}}}), encoding="utf-8")

    async def lauf():
        app, _ = _app({})
        app.panels = W.load_panels()
        runner, port, bc = await visu_starten(app, [("GET", "/cover", W.cover_handler)])
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1400, "height": 1000}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator("#plist .pitem", has_text="?panel=kueche").click()
                await pg.locator(".stab[data-sub='seiten']").click()
                await pg.wait_for_selector("#seHost [data-se-flaeche]")
                opts = await pg.eval_on_selector_all("#seHost [data-se-geraet] option", "l => l.map(o => o.textContent)")
                await pg.select_option("#seHost [data-se-geraet]", str(next(i for i, o in enumerate(opts) if o.startswith("4″"))))
                await pg.wait_for_timeout(400)
                erg = await pg.evaluate(EDITOR)
                await pg.locator("#seHost [data-se-flaeche]").screenshot(path=str(tmp_path / f"editor_spieler_{klassisch}.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return erg
    erg = {k["id"]: k for k in asyncio.run(lauf())}
    az = erg["AZ"]
    assert not erg["L1"]["spieler"] and not erg["L2"]["spieler"], erg
    if klassisch:
        assert not az["spieler"] and az["spalte"] is None, az
        return
    k, s = az["kachel"], az["spalte"]
    assert az["spieler"] and az["tasten"] == 3 and az["geladen"], az
    assert az["cover"] == "/cover?u=" + __import__("urllib.parse").parse.quote(COVER_URL, safe=""), az
    assert abs(s["left"] - (k["left"] + k["width"] / 2)) < 1 and s["right"] <= k["right"], az
    assert az["name"]["right"] <= k["left"] + k["width"] / 2, az
