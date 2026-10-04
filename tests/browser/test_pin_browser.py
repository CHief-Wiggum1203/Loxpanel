"""Gesicherte Bausteine (isSecured) in Chromium gegen den Miniserver-Nachbau.

Der Nachbau lehnt sps/io auf einen gesicherten Baustein ab und nimmt sps/ios
nur mit dem Hash der richtigen Visu-PIN an (tests/lox.py). Jeder Bedienweg
muss die PIN abfragen, bevor ein Befehl den Miniserver erreicht: Regler und
-/+ der Detailseite, Unterseiten (Zone der Bewaesserung, Weckzeit,
Wecker-Einstellungen, Musikauswahl), Player- und Kamera-Bereich. Dazu PIN
merken (Dauer je Panel), Vergessen bei Uhr-Seite, Seitenwechsel und nach
Ablauf, Abbrechen und Halten-Tasten, bei denen nie ein Druecken ohne sein
Loslassen ankommen darf."""
import asyncio
import json

import pytest

from lox import (BETRIEBSARTEN, KONFIGURATOR_GELADEN, Miniserver, W, anlage, bewaesserung_baustein,
                 intercom_baustein, neue_app, visu_starten, wecker_baustein)

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

PIN = "4711"

DIMMER = ({"name": "Flur Dimmer", "type": "Dimmer", "uuidAction": "DIM", "room": "r1", "cat": "c1",
           "states": {"position": "dim-p", "min": "dim-mn", "max": "dim-mx", "step": "dim-st"}},
          {"dim-p": 40, "dim-mn": 0, "dim-mx": 100, "dim-st": 1})
# Auf/Ab-Taster ohne States (Garagentor): gedrueckt halten = fahren
TOR = ({"name": "Garagentor", "type": "UpDownDigital", "uuidAction": "UDD", "room": "r1", "cat": "c1",
        "states": {}}, {})
ZONE = ({"name": "Küche Musik", "type": "AudioZone", "uuidAction": "ZA", "room": "r1", "cat": "c1",
         "states": {"playState": "za-ps", "volume": "za-v", "sourceList": "za-sl"}},
        {"za-ps": 0, "za-v": 30, "za-sl": json.dumps({"items": [{"slot": 1, "name": "Ö1"}]})})


def _bausteine():
    return [DIMMER, TOR, ZONE, bewaesserung_baustein(), wecker_baustein(), intercom_baustein()]


async def _visu(tmp_path, schritt, ui=None, groesse=(480, 480)):
    """Visu mit allen Bausteinen gesichert; der Nachbau kennt die PIN.
    schritt(pg, ms, app) bedient."""
    ms = Miniserver()
    ms.visu_pin = PIN
    await ms.start()
    app = neue_app(ms)
    controls, states = {}, {}
    for control, st in _bausteine():
        controls[control["uuidAction"]] = {**control, "isSecured": True, "isFavorite": True}
        states.update(st)
    ms.gesichert_io = set(controls)
    struktur = anlage(controls)
    struktur["operatingModes"] = BETRIEBSARTEN
    app._apply_structure(struktur)
    app.states = states
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"], "ui": ui or {}}})
    runner, port, bc = await visu_starten(app)
    fehler = []
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch()
            pg = await b.new_page(viewport={"width": groesse[0], "height": groesse[1]})
            pg.on("pageerror", lambda e: fehler.append(str(e)))
            await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
            await pg.wait_for_timeout(600)
            await pg.evaluate("wake()")
            await pg.wait_for_timeout(800)
            await schritt(pg, ms, app)
            await b.close()
    finally:
        bc.cancel()
        await app.icon_session.close()
        await runner.cleanup()
        await ms.stop()
    assert not fehler, fehler


async def _nav(pg, route):
    await pg.evaluate("r => nav(r)", route)
    await pg.wait_for_timeout(700)


async def _pin(pg, pin=PIN):
    for z in pin:
        await pg.locator(f'.pinov .pinkey[data-k="{z}"]').click()
    await pg.locator('.pinov .pinkey[data-k="ok"]').click()


async def _ios(ms, n, warten=3.0):
    """Wartet, bis n gesicherte Befehle beim Nachbau sind -> (uuid/cmd, Code)."""
    for _ in range(int(warten / 0.05)):
        if len(ms.ios) >= n:
            break
        await asyncio.sleep(0.05)
    return list(ms.ios)


def _ungesichert(ms) -> list:
    """Befehle, die ohne PIN (sps/io) bei einem gesicherten Baustein ankamen.
    roomfav/get fordert die Visu beim Oeffnen einer Zone selbst an (Anzeige),
    das ist kein Bedienschritt."""
    return [x for x in ms.io if x.startswith("sps/io/") and "/roomfav/get" not in x]


async def _offen(pg) -> bool:
    return await pg.locator(".pinov").count() == 1


async def _plus(pg):
    await pg.locator('#grid .srow .sbtn[data-sd="up"]').dispatch_event("pointerdown")
    await pg.wait_for_timeout(300)


async def _regler_ziehen(pg, wert):
    await pg.evaluate("""w => { const s=document.querySelector('#grid .sld'); s.value=w;
        s.dispatchEvent(new Event('input')); s.dispatchEvent(new Event('change')); }""", wert)


async def _knopf(pg, text):
    await pg.locator(".brow .btn", has_text=text).first.click()


async def _stepper_plus(pg):
    await pg.locator('.stp .sbtn[data-st="1"]').first.dispatch_event("pointerdown")
    await pg.locator('.stp .sbtn[data-st="1"]').first.dispatch_event("pointerup")
    await pg.wait_for_timeout(1300)     # die Visu sendet erst nach STP_SENDEN_MS Ruhe


SPLIT = (960, 480)
# Bedienweg -> (Seite, Bedienung, erwartete Befehle (Anfang), Panel-ui, Groesse)
BEDIENWEGE = {
    "detail_ein": ({"view": "control", "id": "DIM"}, lambda pg: _knopf(pg, "Ein"), ["DIM/on"], None, None),
    "detail_plus": ({"view": "control", "id": "DIM"}, _plus, ["DIM/41"], None, None),
    "detail_minus": ({"view": "control", "id": "DIM"},
                     lambda pg: pg.locator('#grid .srow .sbtn[data-sd="dn"]').dispatch_event("pointerdown"),
                     ["DIM/39"], None, None),
    "detail_regler": ({"view": "control", "id": "DIM"}, lambda pg: _regler_ziehen(pg, 70), ["DIM/70"], None, None),
    "zone_starten": ({"view": "irrzone", "id": "BEW", "zone": 0}, lambda pg: _knopf(pg, "Zone starten"),
                     ["BEW/select/1"], None, None),
    "zone_laufzeit": ({"view": "irrzone", "id": "BEW", "zone": 0}, _stepper_plus, ["BEW/setDuration/0=660"],
                      None, None),
    "weckzeit_speichern": ({"view": "alarmentry", "id": "WK", "entry": "1"}, lambda pg: _knopf(pg, "Speichern"),
                           ["WK/entryList/put/1/"], None, None),
    "wecker_einstellung": ({"view": "alarmsettings", "id": "WK"}, _stepper_plus, ["WK/setSnoozeDuration/600"],
                           None, None),
    "musik_favorit": ({"view": "sources", "id": "ZA"}, lambda pg: pg.locator(".favs .fav").first.click(),
                      ["ZA/roomfav/play/1"], None, None),
    "player_lautstaerke": (None, lambda pg: pg.locator('#playerpane .ppvol .sbtn[data-sd="up"]')
                           .dispatch_event("pointerdown"), ["ZA/volume/35"],
                           {"panes": {"favoriten": "player:ZA"}}, SPLIT),
    "player_transport": (None, lambda pg: pg.locator('#pptrans [data-c="1"]').dispatch_event("pointerdown"),
                         ["ZA/play"], {"panes": {"favoriten": "player:ZA"}}, SPLIT),
    "kamera_tueroeffner": (None, lambda pg: pg.locator('#frontpane .brow [data-c="0"]')
                           .dispatch_event("pointerdown"), ["IC/1/pulse"],
                           {"panes": {"favoriten": "camera:IC"}}, SPLIT),
}


@pytest.mark.parametrize("weg", list(BEDIENWEGE))
def test_bedienweg_fragt_pin(tmp_path, miniserver_http, weg):
    """Vor der PIN kommt nichts beim Miniserver an, danach genau der Befehl,
    gesichert (sps/ios) und angenommen."""
    route, bedienen, erwartet, ui, groesse = BEDIENWEGE[weg]

    async def schritt(pg, ms, app):
        if route:
            await _nav(pg, route)
        else:
            await pg.wait_for_timeout(1200)     # Bereich wartet auf seinen Push vom Server
        await bedienen(pg)
        await pg.wait_for_timeout(400)
        await pg.screenshot(path=str(tmp_path / f"{weg}.png"))
        assert await _offen(pg), "kein PIN-Fenster"
        assert ms.ios == [] and _ungesichert(ms) == [], (ms.ios, ms.io)
        await _pin(pg)
        await _ios(ms, len(erwartet))
        await pg.wait_for_timeout(300)          # kommt noch etwas hinterher?
        ios = list(ms.ios)
        assert len(ios) == len(erwartet) and all(b.startswith(e) for (b, _), e in zip(ios, erwartet)), ios
        assert all(code == "200" for _, code in ios), ios
        assert _ungesichert(ms) == [], ms.io
    asyncio.run(_visu(tmp_path, schritt, ui, groesse or (480, 480)))


@pytest.mark.parametrize("weg", ["musik_favorit", "weckzeit_speichern"])
def test_zurueck_erst_nach_bestaetigung(tmp_path, miniserver_http, weg):
    """Favorit und "Speichern" gehen danach zurueck - aber erst, wenn der
    Miniserver den Befehl angenommen hat. Abbrechen laesst Seite und
    Eingaben stehen."""
    route, bedienen, erwartet, _, _ = BEDIENWEGE[weg]

    async def schritt(pg, ms, app):
        await _nav(pg, route)
        name = pg.locator('.fld input[data-f="name"]')
        if weg == "weckzeit_speichern":
            await name.fill("Früh")
        tiefe = await pg.evaluate("stack.length")
        await bedienen(pg)
        await pg.wait_for_timeout(400)
        assert await _offen(pg)
        await pg.locator(".pinov .cancel").click()
        await pg.wait_for_timeout(500)
        assert await pg.evaluate("stack.length") == tiefe
        assert await pg.evaluate("view.route.view") == route["view"]
        if weg == "weckzeit_speichern":
            assert await name.input_value() == "Früh"
        assert ms.ios == [] and _ungesichert(ms) == []
        await bedienen(pg)
        await pg.wait_for_timeout(400)
        await _pin(pg)
        ios = await _ios(ms, 1)
        await pg.wait_for_timeout(700)
        assert await pg.evaluate("stack.length") == tiefe - 1, "nach der Bestaetigung zurueck"
        if weg == "weckzeit_speichern":
            assert ios[0][0].startswith("WK/entryList/put/1/Früh/"), ios
    asyncio.run(_visu(tmp_path, schritt))


def test_abbrechen_setzt_den_regler_zurueck(tmp_path, miniserver_http):
    async def schritt(pg, ms, app):
        await _nav(pg, {"view": "control", "id": "DIM"})
        await _regler_ziehen(pg, 70)
        await pg.wait_for_timeout(300)
        assert await _offen(pg)
        await pg.locator(".pinov .cancel").click()
        await pg.wait_for_timeout(300)
        assert await pg.evaluate("document.querySelector('#grid .sld').value") == "40"
        assert await pg.locator("#grid .sval").inner_text() == "40"
        assert ms.ios == [] and _ungesichert(ms) == []
        # Erst falsche PIN, dann Abbrechen in der zweiten Abfrage: auch dann zurueck
        await _regler_ziehen(pg, 70)
        await pg.wait_for_timeout(300)
        await _pin(pg, "0000")
        await _ios(ms, 1)
        await pg.wait_for_timeout(400)
        assert await _offen(pg)
        await pg.locator(".pinov .cancel").click()
        await pg.wait_for_timeout(300)
        assert await pg.evaluate("document.querySelector('#grid .sld').value") == "40"
        assert ms.ios == [("DIM/70", "403")] and _ungesichert(ms) == []
    asyncio.run(_visu(tmp_path, schritt))


def test_halten_nie_druecken_ohne_loslassen(tmp_path, miniserver_http):
    """Garagentor unter PIN: Der Finger ist oben, bevor die PIN eingegeben
    ist. Ohne gemerkte PIN wirkt der Druck deshalb wie ein Tipp (Druecken und
    Loslassen mit derselben PIN), auch nach einer falschen PIN. Mit gemerkter
    PIN geht echtes Halten: Loslassen erst, wenn der Finger hochgeht."""
    async def schritt(pg, ms, app):
        await _nav(pg, {"view": "control", "id": "UDD"})
        auf = pg.locator("#grid .brow .btn").first
        await auf.dispatch_event("pointerdown")
        await pg.wait_for_timeout(200)
        await pg.evaluate("window.dispatchEvent(new PointerEvent('pointerup'))")
        await pg.wait_for_timeout(300)
        assert await _offen(pg)
        assert ms.ios == [] and _ungesichert(ms) == [], "Loslassen lief ohne PIN voraus"
        await _pin(pg, "0000")
        await _ios(ms, 2)
        await pg.wait_for_timeout(400)
        assert await _offen(pg), "falsche PIN fragt erneut"
        assert "PIN falsch" in await pg.locator(".pinov .pinmsg").inner_text()
        await _pin(pg)
        ios = await _ios(ms, 4)
        assert [b for b, code in ios if code == "200"] == ["UDD/UpOn", "UDD/UpOff"], ios
        await pg.wait_for_timeout(400)
        assert not await _offen(pg), "abgelehntes Loslassen zum abgelehnten Druecken fragt nicht extra"
        # PIN gemerkt: echtes Halten
        ms.ios.clear()
        await auf.dispatch_event("pointerdown")
        await pg.wait_for_timeout(600)
        assert not await _offen(pg)
        assert await _ios(ms, 1) == [("UDD/UpOn", "200")], "faehrt, solange der Finger liegt"
        await pg.evaluate("window.dispatchEvent(new PointerEvent('pointerup'))")
        assert await _ios(ms, 2) == [("UDD/UpOn", "200"), ("UDD/UpOff", "200")]
        # Gemerkte PIN gilt am Miniserver nicht mehr (Visu-Passwort geaendert):
        # Druecken und Loslassen abgelehnt, eine Abfrage, danach beides
        ms.ios.clear()
        ms.visu_pin = "1111"
        await auf.dispatch_event("pointerdown")
        await pg.wait_for_timeout(400)
        await pg.evaluate("window.dispatchEvent(new PointerEvent('pointerup'))")
        await _ios(ms, 2)
        await pg.wait_for_timeout(400)
        assert await _offen(pg)
        await _pin(pg, "1111")
        ios = await _ios(ms, 4)
        assert [b for b, code in ios if code == "200"] == ["UDD/UpOn", "UDD/UpOff"], ios
        await pg.wait_for_timeout(400)
        assert not await _offen(pg)
        assert _ungesichert(ms) == [], ms.io
    asyncio.run(_visu(tmp_path, schritt))


async def _plus_mit_pin(pg, ms):
    n = len(ms.ios)
    await _plus(pg)
    assert await _offen(pg)
    await _pin(pg)
    await _ios(ms, n + 1)
    await pg.wait_for_timeout(300)


def test_pin_gemerkt_bis_zum_ablauf(tmp_path, miniserver_http):
    """ui.pinMerken = 3 s: der zweite Schritt fragt nicht, nach Ablauf wieder."""
    async def schritt(pg, ms, app):
        await _nav(pg, {"view": "control", "id": "DIM"})
        await _plus_mit_pin(pg, ms)
        await _plus(pg)
        assert not await _offen(pg), "PIN gemerkt"
        assert await _ios(ms, 2) == [("DIM/41", "200"), ("DIM/42", "200")]
        await pg.wait_for_timeout(3000)
        await _plus(pg)
        assert await _offen(pg), "nach Ablauf fragt die Visu wieder"
        assert await pg.evaluate("pinMerk") is None, "die PIN ist aus dem Speicher"
    asyncio.run(_visu(tmp_path, schritt, ui={"pinMerken": 3}))


def test_pin_merken_aus(tmp_path, miniserver_http):
    async def schritt(pg, ms, app):
        await _nav(pg, {"view": "control", "id": "DIM"})
        await _plus_mit_pin(pg, ms)
        await _plus(pg)
        assert await _offen(pg), "0 = jedes Mal fragen"
    asyncio.run(_visu(tmp_path, schritt, ui={"pinMerken": 0}))


@pytest.mark.parametrize("vergessen", ["uhrseite", "seitenwechsel"])
def test_pin_vergessen(tmp_path, miniserver_http, vergessen):
    """Mit dem Standard (30 s) gemerkt, aber Uhr-Seite und Seitenwechsel
    vergessen die PIN sofort."""
    async def schritt(pg, ms, app):
        dim = {"view": "control", "id": "DIM"}
        await _nav(pg, dim)
        await _plus_mit_pin(pg, ms)
        if vergessen == "uhrseite":
            await pg.evaluate("showSaver()")
            await pg.wait_for_timeout(300)
            await pg.locator("#saver").dispatch_event("pointerdown")
            await pg.wait_for_timeout(300)
            assert await pg.evaluate("view.route.id") == "DIM", "dieselbe Seite"
        else:
            await pg.evaluate("back()")
            await pg.wait_for_timeout(500)
            await _nav(pg, dim)
        await _plus(pg)
        assert await _offen(pg)
    asyncio.run(_visu(tmp_path, schritt))


def test_kamera_auf_der_uhrseite(tmp_path, miniserver_http):
    """Der Kamera-Bereich laeuft auch auf der Uhr-Seite. Der Tipp auf den
    Tueroeffner nimmt sie weg; die PIN-Abfrage steht danach bedienbar da."""
    async def schritt(pg, ms, app):
        await pg.evaluate("showSaver()")
        await pg.wait_for_timeout(1500)
        await pg.locator('#svBox .brow [data-c="0"]').dispatch_event("pointerdown")
        await pg.wait_for_timeout(400)
        assert await pg.evaluate("saverOn()") is False
        assert await pg.locator(".pinov").is_visible()
        assert ms.ios == [] and _ungesichert(ms) == []
        await _pin(pg)
        assert await _ios(ms, 1) == [("IC/1/pulse", "200")]
    asyncio.run(_visu(tmp_path, schritt, ui={"svPane": "camera:IC"}, groesse=SPLIT))


def test_pin_merken_im_konfigurator(cfg_ordner, tmp_path):
    """Feld "PIN merken" unter Aussehen & Verhalten: leer zeigt es grau den
    Standard vom Server, eine Zahl kommt gespeichert und nach dem Neuladen
    wieder an, der Standard wird nicht gespeichert (und nicht als verworfen
    gemeldet), und die Visu bekommt den Wert mit dem theme."""
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {"flur": {
        "title": "Flur", "tabs": ["favoriten"]}}}), encoding="utf-8")
    routen = [("POST", "/api/panels", W.api_save_panels)]

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage({c["uuidAction"]: {**c, "isFavorite": True} for c, _ in _bausteine()}))
        app.states = {k: v for _, st in _bausteine() for k, v in st.items()}
        app.panels = W.load_panels()
        runner, port, bc = await visu_starten(app, routen)
        fehler, stand = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                feld = pg.locator('#pconfHost input[data-ui="pinMerken"]')

                async def oeffnen():
                    await pg.goto(f"http://127.0.0.1:{port}/config")
                    await pg.wait_for_function(KONFIGURATOR_GELADEN)
                    await pg.locator("#plist .pitem", has_text="Flur").click()
                    await pg.locator('.stab[data-sub="appearance"]').click()

                async def speichern():
                    async with pg.expect_response(lambda r: r.url.endswith("/api/panels")) as antwort:
                        await pg.locator("#saveBtn").click()
                    j = await (await antwort.value).json()
                    assert j["ok"] and j["verworfen"] == [], j
                    return json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))["panels"]["flur"]

                await oeffnen()
                stand["grau"] = (await feld.get_attribute("placeholder"), await feld.get_attribute("max"),
                                 await feld.input_value())
                await feld.fill("45")
                stand["gespeichert"] = (await speichern()).get("ui")
                await oeffnen()
                stand["neu_geladen"] = await feld.input_value()
                await feld.scroll_into_view_if_needed()
                await pg.screenshot(path=str(tmp_path / "konfigurator_pin.png"))
                visu = await b.new_page(viewport={"width": 480, "height": 480})
                await visu.goto(f"http://127.0.0.1:{port}/?panel=flur")
                await visu.wait_for_function("pinMerkenS > 0")
                stand["visu"] = await visu.evaluate("pinMerkenS")
                await feld.fill(str(W.PIN_MERKEN_STANDARD))
                stand["standard"] = (await speichern()).get("ui")
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return stand
    stand = asyncio.run(lauf())
    assert stand["grau"] == (str(W.PIN_MERKEN_STANDARD), str(W.PIN_MERKEN_MAX), ""), stand
    assert stand["gespeichert"] == {"pinMerken": 45}, stand
    assert stand["neu_geladen"] == "45" and stand["visu"] == 45, stand
    assert stand["standard"] is None, stand
