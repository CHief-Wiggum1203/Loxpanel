"""Kachelfaktor in Chromium: Symbol, Schrift, Tasten, Innenabstand und die
Kopfzeile wachsen mit der Kachel (Breite durch 170 px, die Hoehe begrenzt,
0,85 bis 2,0). Vorher standen 16-px-Schrift und 38-px-Symbol auf jeder
Kachel, ob 122 oder 628 px breit: grosse Kacheln blieben leer, kleine
schnitten Namen ab. Dazu die Textstufen (kst1..3): ein Haupttext, der nicht
in seine Zeilen passt, wird kleiner statt gekappt. Tasten sind Touch-Ziele
und schrumpfen nie. Gemessen an denselben acht Bildschirmgroessen wie die
Messreihe vom 06.10.2026 (480 x 480 bis 2560 x 1600)."""
import asyncio

import pytest

from lox import W, anlage, irc2_baustein, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

KACHEL_REF, KACHEL_REF_H, KS_MIN, KS_MAX, KOPF_H = 170, 150, 0.85, 2.0, 64


def _faktor(breite, hoehe):
    """Dieselbe Regel wie kachelFaktorFuer() in der Visu."""
    return min(KS_MAX, max(KS_MIN, min(breite / KACHEL_REF, hoehe / KACHEL_REF_H)))


def _gemischte_anlage():
    """23 Favoriten quer durch die Bausteine, mit kurzen und sehr langen Namen -
    die Anlage der Messreihe."""
    c, s = {}, {}

    def add(uid, name, typ, states, **extra):
        c[uid] = {"name": name, "type": typ, "uuidAction": uid, "room": "r1", "cat": "c1",
                  "isFavorite": True, "states": {k: f"{uid}.{k}" for k in states}, **extra}
        for k, v in states.items():
            s[f"{uid}.{k}"] = v

    for i, n in enumerate(["Deckenlicht Wohnzimmer", "Stehlampe", "Steckdose TV", "Ambientebeleuchtung Essbereich",
                           "Außenlicht Terrasse", "Garage Licht"]):
        add(f"S{i}", n, "Switch", {"active": i % 2})
    add("D1", "Dimmer Küche", "Dimmer", {"position": 63, "min": 0, "max": 100, "step": 1})
    add("D2", "Dimmer Flur", "Dimmer", {"position": 0, "min": 0, "max": 100, "step": 1})
    for i, n in enumerate(["Jalousie Wohnzimmer Süd", "Jalousie Küche", "Rollladen Schlafzimmer"]):
        add(f"J{i}", n, "Jalousie", {"position": [0.62, 0, 1][i], "shadePosition": 0, "up": 0, "down": 0,
                                     "autoActive": 0, "locked": 0, "safetyActive": 0, "autoAllowed": 1})
    add("G1", "Garagentor", "Gate", {"position": 0, "active": 0, "preventOpen": 0, "preventClose": 0})
    irc, irc_states = irc2_baustein()
    irc["isFavorite"] = True
    c["IRC2"] = irc
    s.update(irc_states)
    for i, n in enumerate(["Audio Wohnzimmer", "Audio Küche"]):
        add(f"A{i}", n, "AudioZoneV2", {"playState": [2, 0][i], "volume": 35, "title": "Radio FM4", "artist": "",
                                        "serverState": 2, "clientState": 2, "power": 1, "enableAirPlay": 0,
                                        "enableSpotifyConnect": 0, "shuffle": 0, "repeat": 0})
    add("T1", "Außentemperatur", "InfoOnlyAnalog", {"value": 14.3}, details={"format": "%.1f°C"})
    add("T2", "Luftfeuchte Badezimmer", "InfoOnlyAnalog", {"value": 61}, details={"format": "%.0f%%"})
    add("T3", "PV-Leistung aktuell", "InfoOnlyAnalog", {"value": 3.42}, details={"format": "%.2f kW"})
    add("I1", "Postkasten", "InfoOnlyDigital", {"active": 1}, details={"text": {"on": "Post da", "off": "Leer"}})
    add("I2", "Fenster Bad", "InfoOnlyDigital", {"active": 0}, details={"text": {"on": "Offen", "off": "Zu"}})
    add("P1", "Türöffner", "Pushbutton", {"active": 0})
    add("P2", "Alles aus", "Pushbutton", {"active": 0})
    add("Z1", "Lüftung Bad Nachlauf", "TimedSwitch", {"deactivationDelay": 0, "deactivationDelayTotal": 900})
    return anlage(c), s


STRUKTUR, ZUSTAND = _gemischte_anlage()

# Was eine Pruefung ueber das Raster wissen muss, in einem Zug gemessen
MESSEN = """() => {
  const sc = document.querySelector('.screen'), g = document.getElementById('grid');
  const r = e => e.getBoundingClientRect(), cs = e => getComputedStyle(e), gr = r(g);
  const kacheln = [...g.querySelectorAll('.tile[data-id]')];
  const je = id => kacheln.find(k => k.dataset.id === id);
  const ganz = e => !e || (e.scrollHeight <= e.clientHeight + 1 && e.scrollWidth <= e.clientWidth + 1);
  const kachel = k => { if (!k) return null; const nm = k.querySelector('.name'), ico = k.querySelector('.ico svg, .ico.img, .ico .rawico');
    return {breite: k.clientWidth, hoehe: k.clientHeight, klassen: [...k.classList],
            name: nm ? parseFloat(cs(nm).fontSize) : null, nameGanz: ganz(nm), icon: ico ? Math.round(r(ico).width) : null,
            ueberlauf: k.scrollHeight > k.clientHeight + 1,
            tasten: [...k.querySelectorAll('.tctrls:not([hidden]) .tb')].map(b => Math.round(Math.min(r(b).width, r(b).height)))}; };
  const kleinste = xs => xs.length ? Math.min(...xs) : null;   // null: keine sichtbaren Tasten
  const kz = document.getElementById('kopfzeile'), uhr = kz && kz.querySelector('.kz-uhr .t');
  return {ks: parseFloat(cs(sc).getPropertyValue('--ks')) || 1, raster: [gridCols, gridRows],
    kurz: kachel(je('S1')), lang: kachel(je('T2')), erste: kachel(kacheln[0]),
    abgeschnitten: kacheln.filter(k => [...k.querySelectorAll('.name,.sub')].some(e => !ganz(e))).length,
    ueberlauf: kacheln.filter(k => k.scrollHeight > k.clientHeight + 1).length,
    eng: kacheln.filter(k => /\\beng[123]\\b/.test(k.className)).length,
    kst: kacheln.filter(k => /\\bkst[123]\\b/.test(k.className)).length,
    // Tasten nur, wo die Kachel hoch genug ist (tastenEinpassen): versteckte zaehlen nicht
    tastenMin: kleinste(kacheln.flatMap(k => [...k.querySelectorAll('.tctrls:not([hidden]) .tb')].map(b => Math.min(r(b).width, r(b).height)))),
    leisteMin: kleinste(kacheln.flatMap(k => [...k.querySelectorAll(':scope > .tctrls:not([hidden]) .tb')].map(b => r(b).height))),
    mitTasten: kacheln.filter(k => k.querySelector('.tctrls:not([hidden])')).length,
    ohneTasten: kacheln.filter(k => k.classList.contains('ohnetasten')).length,
    sichtbar: kacheln.filter(k => { const b = r(k); return b.top >= gr.top - 1 && b.bottom <= gr.bottom + 1; }).length,
    zeile: g._zeile || [],   // Zeile je Kachel (rasterLage: breite Kacheln belegen zwei Spalten)
    kopf: (kz && !kz.hidden) ? {hoehe: Math.round(r(kz).height), uhr: uhr ? parseFloat(cs(uhr).fontSize) : null} : null};
}"""


def _laufen(ui, breite, hoehe, schritte=None):
    """Visu mit dem Profil ui in der Groesse breite x hoehe laden, Uhr-Seite
    weg, dann messen (oder schritte(app, pg))."""
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(STRUKTUR)
        app.states = dict(ZUSTAND)
        app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"], "ui": ui}})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": breite, "height": hoehe}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
                await pg.wait_for_selector("#grid .tile[data-id]", state="attached")
                await pg.wait_for_timeout(500)
                await pg.evaluate("wake()")
                await pg.wait_for_timeout(600)
                ergebnis = await (schritte(app, pg) if schritte else pg.evaluate(MESSEN))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return ergebnis
    return asyncio.run(lauf())


FAELLE = {
    "4zoll-2x2": ((480, 480), {"cols": 2, "rows": 2}),
    "800x480-3x3-fuellend": ((800, 480), {"cols": 3, "rows": 3, "fill": True}),
    "10zoll-automatisch": ((1280, 800), {"grid": "auto"}),
    "2560x1600-3x3-fuellend": ((2560, 1600), {"cols": 3, "rows": 3, "fill": True}),
}


@pytest.mark.parametrize("fall", list(FAELLE))
def test_faktor_aus_der_kachel(fall):
    """Faktor = min(Breite / 170, Hoehe / 150), begrenzt; ein kurzer Name traegt
    genau 16 px mal Faktor, das Symbol 38 px mal Faktor."""
    (b, h), ui = FAELLE[fall]
    m = _laufen(ui, b, h)
    k = m["kurz"]
    erwartet = _faktor(k["breite"], k["hoehe"])
    # Automatik rechnet mit der Spaltenbreite (mit Rahmen), gemessen ist das Innenmass
    assert abs(m["ks"] - erwartet) <= 0.02, (m["ks"], erwartet, k)
    assert abs(k["name"] - 16 * erwartet) <= 0.5 and not any(c.startswith("kst") for c in k["klassen"]), k
    assert abs(k["icon"] - 38 * erwartet) <= 1.5, k
    assert m["ueberlauf"] == 0, "keine Kachel laeuft ueber"


def test_kleine_kacheln_schneiden_weniger_ab():
    """800 x 480 mit 3 x 3 und Fuellen: 122-px-Kacheln. Ohne Faktor waren 15 von
    18 Namen abgeschnitten (Messreihe), mit Faktor 0,85 deutlich weniger - und
    weniger als dieselbe Seite ohne Faktor."""
    async def schritte(app, pg):
        mit = await pg.evaluate(MESSEN)
        await pg.evaluate("setzeFaktor(1); kachelnNeuMessen()")
        return mit, await pg.evaluate(MESSEN)
    mit, ohne = _laufen({"cols": 3, "rows": 3, "fill": True}, 800, 480, schritte)
    assert mit["ks"] == KS_MIN and ohne["ks"] == 1
    assert mit["abgeschnitten"] < ohne["abgeschnitten"], (mit["abgeschnitten"], ohne["abgeschnitten"])
    assert mit["abgeschnitten"] <= 8 and mit["eng"] <= ohne["eng"], (mit, ohne)


def test_grosse_kacheln_fuellen_sich():
    """2560 x 1600 mit 3 x 3 und Fuellen: 415-px-Kacheln bekommen den vollen
    Faktor 2 - 32-px-Schrift und 76-px-Symbol statt 16 und 38, nichts
    abgeschnitten, nichts laeuft ueber."""
    m = _laufen({"cols": 3, "rows": 3, "fill": True}, 2560, 1600)
    assert m["ks"] == KS_MAX and m["kurz"]["name"] == 32 and abs(m["kurz"]["icon"] - 76) <= 1, m["kurz"]
    assert m["abgeschnitten"] == 0 and m["ueberlauf"] == 0, m


def test_flache_kacheln_nehmen_die_hoehe():
    """2 x 3 auf dem 4"-Panel: 225 x 128 px. Die Breite ergaebe 1,32, die Hoehe
    begrenzt auf 0,85 - sonst liefe jede Kachel unten ueber. Fuer Text UND
    Tasten ist die flache Kachel zu niedrig: Beschattung und Player haben
    keine Tasten (tastenEinpassen), die Detailseite hat sie."""
    m = _laufen({"cols": 2, "rows": 3}, 480, 480)
    assert m["kurz"]["hoehe"] < 140, m["kurz"]
    assert abs(m["ks"] - KS_MIN) <= 0.01 and m["ueberlauf"] == 0, m
    assert m["tastenMin"] is None and m["mitTasten"] == 0 and m["ohneTasten"] == 5, m   # 3 Jalousien, 2 Audio


def test_langer_name_bleibt_ganz():
    """4"-Panel 2 x 2 (Faktor 1,31): Bei „Luftfeuchte Badezimmer“ steht der
    Wert vorn und der Name einzeilig darunter - bei 18 px passt er nicht
    mehr in seine Zeile und nimmt den Faktor in Stufen zurueck, bis er ganz
    steht (nie unter die 14 px ohne Faktor); „Stehlampe“ behaelt die 21 px.
    (Eine Beschattung taugt hier nicht mehr als Beispiel: sie nimmt fuer
    Text und Tasten ihren eigenen, kleineren Faktor, s. tastenEinpassen.)"""
    m = _laufen({"cols": 2, "rows": 2}, 480, 480)
    kurz, lang = m["kurz"], m["lang"]
    assert abs(kurz["name"] - 16 * m["ks"]) <= 0.5 and kurz["nameGanz"], kurz
    assert "zv" in lang["klassen"] and any(c.startswith("kst") for c in lang["klassen"]) and lang["nameGanz"], lang
    assert 14 <= lang["name"] < 14 * m["ks"] - 0.5, (lang["name"], m["ks"])


def test_tasten_schrumpfen_nicht():
    """Faktor 0,85 (3 x 2 auf dem 4"-Panel, 147 x 198 px): Schrift und Symbol
    werden kleiner, die Tasten (Touch-Ziele) bleiben bei 44 px in der Leiste.
    Flache Kacheln (3 x 3 auf 800 x 480, 128 px) haben gar keine Tasten. Bei
    grossem Faktor wachsen die Tasten mit dem Faktor der SEITE, auch wo die
    Kachel fuer Text und Tasten einen kleineren nimmt (tastenEinpassen)."""
    m = _laufen({"cols": 3, "rows": 2}, 480, 480)
    assert abs(m["ks"] - KS_MIN) <= 0.01 and m["mitTasten"] == 5 and m["tastenMin"] >= 34 and m["leisteMin"] >= 44, m
    flach = _laufen({"cols": 3, "rows": 3, "fill": True}, 800, 480)
    assert abs(flach["ks"] - KS_MIN) <= 0.01 and flach["mitTasten"] == 0 and flach["ohneTasten"] == 5 \
        and flach["tastenMin"] is None, flach
    gross = _laufen({"cols": 3, "rows": 3, "fill": True}, 1280, 800)
    assert gross["ks"] > 1 and gross["mitTasten"] == 5 and gross["leisteMin"] >= 44 * gross["ks"] - 1 \
        and gross["tastenMin"] >= 34, gross


def test_kopfzeile_waechst_mit():
    """Die Kopfzeile traegt denselben Faktor: Hoehe 64 px mal Faktor, Uhr 26 px
    mal Faktor; das automatische Raster rechnet die groessere Zeile ab."""
    m = _laufen({"cols": 3, "rows": 3, "fill": True, "panes": {"favoriten": "header"}}, 1280, 800)
    assert m["ks"] > 1 and m["kopf"], m
    assert m["kopf"]["hoehe"] == round(KOPF_H * m["ks"]) and abs(m["kopf"]["uhr"] - 26 * m["ks"]) <= 0.5, m["kopf"]
    a = _laufen({"grid": "auto", "tileSize": "large", "panes": {"favoriten": "header"}}, 1280, 800)
    # sichtbar sind die Kacheln der ersten Seite - mit den beiden breiten Audio-Kacheln weniger als cols x rows
    assert a["kopf"]["hoehe"] == round(KOPF_H * a["ks"]) and a["sichtbar"] == sum(1 for z in a["zeile"] if z < a["raster"][1]), a


def test_faktor_zieht_bei_groessenaenderung_nach():
    """Fenster waechst, Raster bleibt (quadratisch 2 x 2 mit Fuellen): der Faktor
    folgt der Kachelbreite ohne Neuaufbau, die Schrift waechst mit."""
    async def schritte(app, pg):
        vorher = await pg.evaluate(MESSEN)
        await pg.set_viewport_size({"width": 640, "height": 640})
        await pg.wait_for_timeout(500)
        return vorher, await pg.evaluate(MESSEN)
    vorher, nachher = _laufen({"cols": 2, "rows": 2, "fill": True}, 480, 480, schritte)
    assert vorher["raster"] == nachher["raster"] == [2, 2]
    assert nachher["ks"] > vorher["ks"] + 0.2 and nachher["kurz"]["name"] > vorher["kurz"]["name"] + 3, (vorher["ks"], nachher["ks"])
    assert abs(nachher["kurz"]["name"] - 16 * nachher["ks"]) <= 0.5 and nachher["ueberlauf"] == 0, nachher["kurz"]


# Lesbarkeits-Pruefung (Vorschlag 16, Teil Abschneiden): auf den Standardgeraeten
# darf mit Faktor nicht mehr abgeschnitten sein als ohne, und keine Kachel laeuft ueber.
STANDARD = {"taba9-quer": ((893, 533), {"grid": "auto"}), "taba9-hoch": ((533, 893), {"grid": "auto"}),
            "zehn-quer": ((1280, 800), {"grid": "auto"}), "ipad-quer": ((1024, 768), {"grid": "auto"}),
            "4zoll": ((480, 480), {"cols": 2, "rows": 2})}


@pytest.mark.parametrize("geraet", list(STANDARD))
def test_lesbarkeit_auf_standardgeraeten(geraet):
    async def schritte(app, pg):
        mit = await pg.evaluate(MESSEN)
        await pg.evaluate("setzeFaktor(1); kachelnNeuMessen()")
        return mit, await pg.evaluate(MESSEN)
    (b, h), ui = STANDARD[geraet]
    mit, ohne = _laufen(ui, b, h, schritte)
    assert mit["ueberlauf"] == 0, mit
    assert mit["abgeschnitten"] <= ohne["abgeschnitten"], (mit["abgeschnitten"], ohne["abgeschnitten"])
