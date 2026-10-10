"""Neuer Kachel-Aufbau (Standard, nach den Kacheln der Loxone-App) in
Chromium: Raum klein oben rechts, der Zustand gross und der Name klein
darunter, Messwerte gross an Stelle des Symbols, Tasten als Leiste unten.
Am Tablet wie am 4"-Panel, dessen Raster (2x2, 3x3) bleibt; auf engen
Kacheln wird der Text gekuerzt statt abgeschnitten. Der klassische Aufbau
bleibt waehlbar und unveraendert, Schriftgroessen und die Schrift einzelner
Kacheln wirken in beiden, und der Konfigurator stellt den Aufbau um. Dazu ein
Fehler, den beide Aufbauten hatten: Eine enge Kachel verlor bei einem
Zustandswechsel ohne neuen Text (Player: Pause) die Lage ihrer Tasten."""
import asyncio
import json
import shutil

import pytest

from lox import EFM, EFM_NODES, KONFIGURATOR_GELADEN, ROOT, W, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser


def _c(uuid, name, typ, room, states, **extra):
    return {"name": name, "type": typ, "uuidAction": uuid, "room": room, "cat": "c1",
            "isFavorite": True, "states": states, **extra}


# Die Bausteine vom Loxone-Bild (Favoriten am iPad), dazu Beschattung und Raumregelung
STRUKTUR = {
    "rooms": {"r1": {"name": "Zentral"}, "r2": {"name": "Eingang"}, "r3": {"name": "Bad"},
              "r4": {"name": "Essen-Kochen-Wohnen"}, "r5": {"name": "Sauna"}, "r6": {"name": "Küche"}},
    "cats": {"c1": {"name": "Allgemein"}},
    "controls": {
        "F": {**EFM, "isFavorite": True},
        "MB": _c("MB", "Postkasten", "MailBox", "r2", {"mailReceived": "mb1", "packetReceived": "mb2"}),
        "TS": _c("TS", "Timer IR Heizung", "TimedSwitch", "r3", {"deactivationDelay": "ts1"}),
        "AZ": _c("AZ", "Essen-Kochen-Wohnen", "AudioZoneV2", "r4", {"playState": "az1", "songName": "az2"}),
        "FS": _c("FS", "Frostsicherung", "Switch", "r1", {"active": "fs1"}),
        "CA": _c("CA", "Audio Zentral", "CentralAudioZone", "r1", {}, details={"controls": [{"uuid": "AZ"}]}),
        "IC": _c("IC", "Eingang Intercom", "Intercom", "r2", {"bell": "ic1"}),
        "SA": _c("SA", "Saunasteuerung", "Sauna", "r5", {"active": "sa1", "tempActual": "sa2"}),
        "LC": _c("LC", "Sauna", "LightControllerV2", "r5", {"activeMoods": "lc1", "moodList": "lc2"}),
        "RA": _c("RA", "Lüfterstufen", "Radio", "r1", {"activeOutput": "ra1"},
                 details={"allOff": "Automatik", "outputs": {"1": "Stufe 1", "2": "Stufe 2"}}),
        "J": _c("J", "Rollo Küche", "Jalousie", "r6", {"position": "j1", "up": "j2", "down": "j3"}),
        "IR": _c("IR", "Raumregelung Küche", "IRoomControllerV2", "r6",
                 {"tempActual": "ir1", "tempTarget": "ir2", "prepareState": "ir3", "openWindow": "ir4"}),
        # ohne Messwert nur "PV-Anlage" (Beschreibung), mit Wert ein Zustand
        "PV": _c("PV", "Wechselrichter", "Fronius", "r1", {"prodCurr": "pv1"}),
    },
}
STATES = {
    "f-p": 0.55, "f-g": 0.153, "f-s": 0.0, **{f"f-a{i}": 0.1 for i in range(len(EFM_NODES))},
    "mb1": 0, "mb2": 0, "ts1": 0, "az1": 2, "az2": "Hitradio Ö3", "fs1": 1, "ic1": 0, "sa1": 0, "sa2": 25.4,
    "lc1": json.dumps([778]), "lc2": json.dumps([{"id": 778, "name": "Aus"}, {"id": 1, "name": "Hell"}]),
    "ra1": 0, "j1": 0.62, "j2": 0, "j3": 0, "ir1": 21.5, "ir2": 22.0, "ir3": 1, "ir4": 0,
}

# Je Kachel, was der Aufbau zeigt (Lage, Reihenfolge, Groessen, Ueberlauf).
# Groessen auf den Kachelfaktor (--ks am .screen) zurueckgerechnet: die
# eingestellte Groesse gilt "bei 170-px-Kachel", die Kachel traegt sie mal Faktor.
MESSEN = """() => Object.fromEntries([...document.querySelectorAll('#grid .tile[data-id]')].map(t => {
  const q = s => t.querySelector(s), r = e => e ? e.getBoundingClientRect() : null;
  const ks = parseFloat(getComputedStyle(document.querySelector('.screen')).getPropertyValue('--ks')) || 1;
  const grund = e => e ? (Math.round(parseFloat(getComputedStyle(e).fontSize) / ks * 10) / 10) + 'px' : null;
  const cs = e => e ? getComputedStyle(e) : null, kopfRaum = q('.head .room'), sub = q('.sub'), name = q('.name');
  const sichtbar = e => !!e && cs(e).display !== 'none';
  const ganz = e => sichtbar(e) ? e.scrollHeight <= e.clientHeight + 1 && e.scrollWidth <= e.clientWidth + 1 : null;
  const ctrl = q('.tctrls');
  return [t.dataset.id, {
    klassen: [...t.classList], raumKopf: kopfRaum ? kopfRaum.textContent : null,
    raumKopfRechts: kopfRaum ? r(t).right - r(kopfRaum).right : null,
    raumText: q('.body .room:not(.tsline)') ? q('.body .room:not(.tsline)').textContent : null,
    raumVersal: q('.body .room:not(.tsline)') ? cs(q('.body .room:not(.tsline)')).textTransform : null,
    pfeil: !!q('.chev'), symbol: !!q('.head .ico'), big: q('.bigv') ? q('.bigv').textContent : null,
    sub: sichtbar(sub) ? sub.innerText : null, name: sichtbar(name) ? name.innerText : null,
    ganz: {sub: ganz(sub), name: ganz(name)},
    subOben: sichtbar(sub) && sichtbar(name) ? r(sub).top < r(name).top : null,
    groesse: {sub: grund(sub), name: grund(name), raum: grund(kopfRaum), big: grund(q('.bigv'))}, ks,
    subStil: sub ? [cs(sub).color, cs(sub).fontWeight, cs(sub).fontStyle] : null,
    ueberlauf: t.scrollHeight - t.clientHeight,
    textUnten: Math.max(...[sub, name].filter(sichtbar).map(e => r(e).bottom)) - r(t).bottom,
    tastenImKopf: !!(ctrl && ctrl.parentNode.classList.contains('head')),
    tastenWeg: !!(ctrl && (ctrl.hidden || cs(ctrl).display === 'none')),
    eigenerKs: parseFloat(t.style.getPropertyValue('--ks')) || null,
    tastenUnten: ctrl && ctrl.parentNode === t ? r(ctrl).top - r(q('.body')).bottom : null,
    tasten: [...t.querySelectorAll('.tctrls .tb')].map(b => [Math.round(r(b).width), Math.round(r(b).height),
             r(b).bottom <= r(t).bottom + 0.5, b.innerHTML]),
    innenBreite: t.clientWidth - parseFloat(cs(t).paddingLeft) - parseFloat(cs(t).paddingRight),
    links: Math.round(r(t).left)}];
}))"""


@pytest.fixture(autouse=True)
def _frische_installation(cfg_ordner):
    """Jeder Test laeuft wie eine frische Installation: nur die Vorlage
    theme.example.json, kein theme.json. So zaehlt, was die Vorlage festlegt,
    nicht was zufaellig in config/ liegt - die Schriftgroessen entscheiden mit,
    wie eng eine Kachel wird."""
    shutil.copy(ROOT / "config" / "theme.example.json", cfg_ordner / "theme.example.json")


def _app(ui: dict, tiles: dict | None = None):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    app.states = dict(STATES)
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"], "ui": ui,
                                                  **({"tiles": tiles} if tiles else {})}})
    return app


async def _visu(b, port, breite, hoehe, fehler):
    pg = await b.new_page(viewport={"width": breite, "height": hoehe})
    pg.on("pageerror", lambda e: fehler.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
    await pg.wait_for_selector("#grid .tile[data-id]", state="attached")
    if await pg.locator("#saver:not(.hidden)").count():
        await pg.click("#saver")
        await pg.wait_for_selector("#saver.hidden", state="attached")
    await pg.wait_for_timeout(500)
    return pg


def _laufen(ui, breite, hoehe, schritte, tiles=None, tmp_path=None, bild=None):
    """Visu oeffnen, schritte(app, pg) ausfuehren -> deren Ergebnis."""
    async def lauf():
        app = _app(ui, tiles)
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _visu(b, port, breite, hoehe, fehler)
                ergebnis = await schritte(app, pg)
                if tmp_path and bild:
                    await pg.screenshot(path=str(tmp_path / f"{bild}.png"))
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return ergebnis
    return asyncio.run(lauf())


def test_neuer_aufbau_am_tablet(tmp_path):
    async def schritte(app, pg):
        vorher = await pg.evaluate(MESSEN)
        lx = await pg.evaluate("document.getElementById('grid').classList.contains('lx')")
        # Live: Ist-Temperatur steigt, die PV-Anlage meldet einen Wert - an Ort
        # und Stelle, ohne neuen Aufbau
        await pg.evaluate("document.querySelectorAll('#grid .tile[data-id]').forEach(t => t._alt = true)")
        app._on_value("ir1", 22.3)
        app._on_value("pv1", 2.5)
        await pg.wait_for_function("document.querySelector('.tile[data-id=\"IR\"] .bigv').textContent === '22,3°'")
        await pg.wait_for_timeout(300)
        nachher = await pg.evaluate(MESSEN)
        alt = await pg.evaluate("[...document.querySelectorAll('#grid .tile[data-id]')].every(t => t._alt)")
        return lx, vorher, nachher, alt
    lx, k, nachher, alt = _laufen({"cols": 3, "rows": 3}, 1000, 750, schritte, tmp_path=tmp_path, bild="tablet_neu")

    assert lx, "der neue Aufbau ist der Standard"
    assert not any(e["pfeil"] for e in k.values()), "kein Pfeil mehr"
    assert all(e["ueberlauf"] <= 1 and e["textUnten"] <= 0 for e in k.values()), k
    assert not any("eng1" in e["klassen"] for e in k.values()), "am Tablet ist Platz fuer alles"
    # Raum oben rechts im Kopf, nicht in Versalien ueber dem Namen
    mb = k["MB"]
    assert mb["raumKopf"] == "Eingang" and mb["raumText"] is None and 13 <= mb["raumKopfRechts"] <= 16, mb
    # Zustand vorn: gross, der Name klein darunter
    assert "zv" in mb["klassen"] and mb["subOben"] and (mb["sub"], mb["name"]) == ("Leer", "Postkasten"), mb
    assert mb["groesse"]["sub"] == "16px" and mb["groesse"]["name"] == "14px" and mb["groesse"]["raum"] == "13px"
    assert k["CA"]["sub"] == "Spielt in 1 Raum" and k["RA"]["sub"] == "Automatik"
    # Kacheln, die direkt schalten, und reine Beschreibungen: der Name bleibt vorn
    assert "zv" not in k["FS"]["klassen"] and k["FS"]["subOben"] is False, k["FS"]
    assert "bi" in k["IC"]["klassen"] and "zv" not in k["IC"]["klassen"], k["IC"]
    # Messwert gross an Stelle des Symbols, mehrteiliger Zustand untereinander
    ir = k["IR"]
    assert ir["big"] == "21,5°" and not ir["symbol"] and ir["groesse"]["big"] == "36px", ir
    # breite Raumregelungs-Kachel: die Teile des Zustands bleiben nebeneinander
    assert ir["sub"] == "Soll 22,0° · heizt" and ir["name"] == "Raumregelung Küche", ir
    assert k["SA"]["big"] == "25,4°" and k["SA"]["sub"] == "Aus", k["SA"]
    # Tasten als Leiste unten ueber die ganze Breite, gross genug fuer den Finger
    for kid in ("J", "AZ"):
        e = k[kid]
        assert not e["tastenImKopf"] and e["tastenUnten"] >= 0, e
        assert all(h >= 44 and drin for _, h, drin, _ in e["tasten"]), e
        assert sum(w for w, _, _, _ in e["tasten"]) >= 0.85 * e["innenBreite"], e
    # Live: neuer Messwert an Ort und Stelle; der Wert macht aus der Beschreibung einen Zustand
    assert alt, "aktualisiert ohne neuen Aufbau"
    assert nachher["IR"]["big"] == "22,3°"
    assert "bi" in k["PV"]["klassen"] and k["PV"]["sub"] == "PV-Anlage", k["PV"]
    assert nachher["PV"]["sub"] == "2,50 kW" and "zv" in nachher["PV"]["klassen"] \
        and "bi" not in nachher["PV"]["klassen"], nachher["PV"]


# "bestand": Groessen, die bestehende Installationen aus der frueheren Vorlage
# in theme.json stehen haben (Haupttext 20, Zweittext 15)
@pytest.mark.parametrize("ui, spalten", [
    ({"split": False}, 2), ({"split": False, "cols": 3, "rows": 3}, 3),
    ({"split": False, "cols": 3, "rows": 3, "nameSize": 20, "subSize": 15}, 3),
], ids=["2x2", "3x3", "3x3-bestand"])
def test_neuer_aufbau_am_4zoll_panel(tmp_path, request, ui, spalten):
    async def schritte(app, pg):
        return await pg.evaluate(MESSEN)
    fall = request.node.callspec.id
    k = _laufen(ui, 480, 480, schritte, tmp_path=tmp_path, bild=f"panel_4zoll_{fall}")
    klassisch = _laufen({**ui, "tileLayout": "classic"}, 480, 480, schritte)

    erste = sorted({e["links"] for e in k.values()})
    assert len(erste) == spalten, f"das Raster bleibt {spalten} Spalten breit: {erste}"
    assert all(e["ueberlauf"] <= 1 and e["textUnten"] <= 0 for e in k.values()), k
    assert all(drin for e in k.values() for _, _, drin, _ in e["tasten"]), "keine Taste ragt heraus"
    # Nichts abgeschnitten, was der klassische Aufbau ganz zeigt. Nur eine
    # reine Beschreibung (.bi) darf auf enger Kachel ganz weichen.
    for kid, e in k.items():
        for zeile in ("name", "sub"):
            if klassisch[kid]["ganz"][zeile] and not (zeile == "sub" and "bi" in e["klassen"]):
                assert e["ganz"][zeile], (kid, zeile, e, klassisch[kid])
    if fall == "3x3":
        # Enge Kachel: mit dem Kachelfaktor (147-px-Kachel -> 0,86) passen Name
        # UND Beschreibung; frueher wich die Beschreibung (eng1) und der
        # klassische Aufbau schnitt den Namen ab.
        ic = k["IC"]
        assert "bi" in ic["klassen"] and "eng1" not in ic["klassen"], ic
        assert ic["ganz"]["name"] and ic["name"].replace("\n", " ") == "Eingang Intercom", ic
        assert ic["sub"] is not None and ic["ganz"]["sub"], ic
        assert 0.85 <= ic["ks"] <= 0.9, ic["ks"]
    # Player: in drei Zeilen (128 px) ist die Kachel fuer Text UND Tasten zu
    # niedrig - keine Tasten, die Detailseite hat sie (tastenEinpassen); in
    # zwei Zeilen stehen sie unter dem Text, die Kachel nimmt dafuer einen
    # kleineren Faktor als die Seite
    if spalten == 3:
        assert k["AZ"]["tastenWeg"] and not k["AZ"]["tastenImKopf"] and "ohnetasten" in k["AZ"]["klassen"], k["AZ"]
    else:
        assert not k["AZ"]["tastenWeg"] and k["AZ"]["tastenUnten"] >= 0, k["AZ"]
        assert k["AZ"]["eigenerKs"] and k["AZ"]["eigenerKs"] < k["AZ"]["ks"], k["AZ"]


@pytest.mark.parametrize("aufbau", ["neu", "classic"])
def test_enge_kachel_hat_keine_tasten(tmp_path, aufbau):
    """3x3 am 4"-Panel (128 px): fuer Text und Tasten ist die Kachel zu
    niedrig, also keine Tasten (tastenEinpassen, aus dem Faktor statt
    gemessen) - ein Tipp auf die Kachel oeffnet die Detailseite, dort sind
    sie. Ein Zustandswechsel ohne neuen Text (Pause) aendert daran nichts,
    die Tasten bleiben fuer den naechsten Aufbau aktuell, nichts laeuft ueber."""
    ui = {"split": False, "cols": 3, "rows": 3, **({"tileLayout": "classic"} if aufbau == "classic" else {})}

    async def schritte(app, pg):
        vorher = (await pg.evaluate(MESSEN))["AZ"]
        app._on_value("az1", 0)
        await pg.wait_for_function("document.querySelector('.tile[data-id=\"AZ\"]').classList.contains('on') === false")
        await pg.wait_for_timeout(300)
        nachher = (await pg.evaluate(MESSEN))["AZ"]
        await pg.locator('.tile[data-id="AZ"]').click()
        await pg.wait_for_timeout(600)
        return vorher, nachher, await pg.evaluate("view && view.route")
    # Die Audio-Kachel ist seit den breiten Kacheln von Haus aus zwei Spalten
    # breit; hier geht es um die ENGE Kachel, also eine Spalte (tiles.AZ.w = 1)
    vorher, nachher, route = _laufen(ui, 480, 480, schritte, tiles={"AZ": {"w": 1}}, tmp_path=tmp_path, bild=f"enge_kachel_{aufbau}")

    assert vorher["tastenWeg"] and "ohnetasten" in vorher["klassen"] and not vorher["tastenImKopf"], vorher
    assert nachher["tastenWeg"] and "ohnetasten" in nachher["klassen"] and not nachher["tastenImKopf"], nachher
    assert vorher["tasten"][1][3] != nachher["tasten"][1][3], "Pause wurde zu Play"
    assert vorher["ueberlauf"] <= 1 and nachher["ueberlauf"] <= 1, nachher
    assert route == {"view": "control", "id": "AZ"}, route


def test_klassischer_aufbau_bleibt_waehlbar(tmp_path):
    async def schritte(app, pg):
        lx = await pg.evaluate("document.getElementById('grid').classList.contains('lx')")
        return lx, await pg.evaluate(MESSEN)
    lx, k = _laufen({"split": False, "tileLayout": "classic"}, 480, 480, schritte, tmp_path=tmp_path,
                    bild="panel_klassisch")

    assert not lx
    mb = k["MB"]
    assert mb["raumKopf"] is None and mb["raumText"] == "Eingang" and mb["raumVersal"] == "uppercase", mb
    assert mb["pfeil"] and mb["subOben"] is False and "zv" not in mb["klassen"], mb
    assert mb["groesse"]["name"] == "18px" and mb["groesse"]["sub"] == "15px", mb


def test_schriften_lassen_sich_einstellen(tmp_path):
    groessen = {"nameSize": 20, "subSize": 12, "roomSize": 15, "bigSize": 44,
                "textColor": "#00ff00"}            # Schriftfarbe (Haupttext) des Panels
    stil = {"MB": {"textColor": "#ff0000", "bold": True, "italic": True}}

    async def schritte(app, pg):
        return await pg.evaluate(MESSEN)
    neu = _laufen({"cols": 3, "rows": 3, **groessen}, 1000, 750, schritte, tiles=stil,
                  tmp_path=tmp_path, bild="schriften_neu")
    alt = _laufen({"cols": 3, "rows": 3, "tileLayout": "classic", **groessen}, 1000, 750, schritte, tiles=stil)

    mb = neu["MB"]
    assert mb["groesse"] == {"sub": "20px", "name": "12px", "raum": "15px", "big": None}, mb
    assert neu["IR"]["groesse"]["big"] == "44px"
    # Schrift der Kachel trifft auch den Zustand, wenn er vorn steht, und schlaegt
    # dort die Schriftfarbe des Panels; die gilt fuer den Zustand der uebrigen
    assert mb["subStil"] == ["rgb(255, 0, 0)", "700", "italic"], mb
    assert neu["RA"]["subStil"][0] == "rgb(0, 255, 0)" and "zv" in neu["RA"]["klassen"], neu["RA"]
    assert alt["MB"]["groesse"]["name"] == "20px" and alt["MB"]["groesse"]["sub"] == "12px", alt["MB"]


def test_aufbau_und_schrift_im_konfigurator(cfg_ordner, tmp_path):
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"flur": {
        "title": "Flur", "tabs": ["favoriten"]}}}), encoding="utf-8")
    routen = [("POST", "/api/panels", W.api_save_panels), ("POST", "/api/theme", W.api_save_theme)]

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(STRUKTUR)
        app.states = dict(STATES)
        app.panels = W.load_panels()
        runner, port, bc = await visu_starten(app, routen)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))

                async def oeffnen():
                    await pg.goto(f"http://127.0.0.1:{port}/config")
                    await pg.wait_for_function(KONFIGURATOR_GELADEN)
                    await pg.locator("#plist .pitem", has_text="Flur").click()
                    await pg.locator('.stab[data-sub="aussehen"]').click()

                async def grau():
                    """Was die leeren Groessenfelder grau zeigen"""
                    return await pg.evaluate("Object.fromEntries([...document.querySelectorAll("
                                             "'#pconfHost input[data-ui$=\"Size\"]')].map(i => [i.dataset.ui, i.placeholder]))")

                async def speichern():
                    async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
                        await pg.locator("#saveBtn").click()
                    j = await (await antwort.value).json()
                    assert j["ok"] and j["verworfen"] == [], j
                    return json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]["flur"]

                await oeffnen()
                stand = {"anfang": await pg.locator("#fTileLayout").input_value(), "grau_neu": await grau()}
                await pg.locator("#fTileLayout").select_option("classic")
                stand["grau_klassisch"] = await grau()
                await pg.locator('#pconfHost input[data-ui="roomSize"]').fill("15")
                stand["gespeichert"] = (await speichern()).get("ui")
                await oeffnen()
                stand["nach_neuladen"] = (await pg.locator("#fTileLayout").input_value(),
                                          await pg.locator('#pconfHost input[data-ui="roomSize"]').input_value())
                await pg.locator("#fTileLayout").select_option("")
                stand["zurueck"] = (await speichern()).get("ui")
                await pg.screenshot(path=str(tmp_path / "konfigurator_aufbau.png"))
                visu_flur = await b.new_page(viewport={"width": 480, "height": 480})
                await visu_flur.goto(f"http://127.0.0.1:{port}/?panel=flur")
                await visu_flur.wait_for_selector("#grid .tile[data-id]", state="attached")
                stand["visu"] = await visu_flur.evaluate(
                    "[document.getElementById('grid').classList.contains('lx'),"
                    " getComputedStyle(document.documentElement).getPropertyValue('--room-size').trim()]")
                # Global eingestellt: das Panel zeigt grau, was es davon erbt
                await pg.locator("#plist .pitem", has_text="Vorgaben").click()
                stand["grau_global"] = await grau()
                await pg.locator('#pconfHost input[data-ui="nameSize"]').fill("19")
                await pg.locator("#plist .pitem", has_text="Flur").click()
                await pg.locator('.stab[data-sub="aussehen"]').click()
                stand["grau_erbt"] = await grau()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return stand
    stand = asyncio.run(lauf())

    assert stand["anfang"] == "", "ohne Einstellung der neue Aufbau"
    # Leere Felder zeigen grau, was gilt: den Standard des Aufbaus vom Server,
    # beim Umstellen sofort den des anderen, und was das Panel global erbt
    neu, klassisch = ({k: str(v) for k, v in W.GROESSEN_STANDARD[a].items()} for a in ("neu", "classic"))
    assert neu != klassisch
    assert stand["grau_neu"] == neu and stand["grau_klassisch"] == klassisch, stand
    assert stand["grau_global"] == neu, stand
    assert stand["grau_erbt"] == {**neu, "nameSize": "19"}, stand
    assert stand["gespeichert"] == {"tileLayout": "classic", "roomSize": 15}, stand
    assert stand["nach_neuladen"] == ("classic", "15"), stand
    assert stand["zurueck"] == {"roomSize": 15}, "der neue Aufbau ist der Standard und wird nicht gespeichert"
    assert stand["visu"] == [True, "15px"], stand
