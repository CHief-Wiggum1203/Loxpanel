"""LoxOS-Assistent im Konfigurator (Fork, docs/VISION.md "LoxOS-Assistent"):
"LoxOS-Streifen einrichten" in fuenf Schritten - Geraet (Streifen oben, ein
Geraet ohne gemeldeten Schirm unten mit "Groesse noch unbekannt"),
Anwesenheit (Melder, Ruhe-Uhr vorausgewaehlt, "ohne Melder" erlaubt),
Aussehen (Set edge, Farbton-Schnellwahl, "Original" vorausgewaehlt),
Startseite (Vorschlag des Servers, Live-Vorschau in Geraetegroesse) und Fertig
(neue Ansicht "LoxOS · <Geraet>", nie ueberschrieben, dem Geraet zugeordnet,
Melder und Ruhe gespeichert, danach der Bento-Editor offen). Abbrechen aendert
nichts; Betriebsmodi bleiben, Schritt 5 nennt sie."""
import asyncio
import json

import pytest

from lox import anlage, konfig, KONFIGURATOR_GELADEN, visu_starten, W

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

STREIFEN = {"width": 2560, "height": 720}
TABLET = {"width": 893, "height": 533}
BAUSTEINE = {
    "L1": {"name": "Licht", "type": "Switch", "uuidAction": "L1", "room": "r1", "cat": "c1", "isFavorite": True,
           "states": {"active": "l1"}},
    "PM": {"name": "Präsenz Büro", "type": "PresenceDetector", "uuidAction": "PM", "room": "r1", "cat": "c1",
           "states": {"active": "pm_a", "infoText": "pm_t"}},
}
ZENTRAL = {"title": "Zentral", "tabs": ["auswahl"], "pickTabs": [{"name": "Zentral", "picks": ["L1"]}]}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/devices", W.api_save_devices),
          ("POST", "/api/panels", W.api_save_panels), ("POST", "/api/device/switch", W.api_device_switch),
          ("POST", "/api/theme", W.api_save_theme), ("POST", "/api/entwurf", W.api_entwurf),
          ("POST", "/api/device/name", W.api_device_name), ("GET", "/api/bento/vorschlag", W.api_bento_vorschlag)]
STAND = """() => { const ov = document.getElementById('loxOv'), t = s => { const e = document.querySelector(s); return e ? e.innerText.replace(/\\s+/g, ' ').trim() : ''; };
  const ruhe = document.getElementById('loxRuhe');
  return {offen: !ov.hidden, schritt: t('#loxStep'), body: t('#loxBody'),
          geraete: [...document.querySelectorAll('#loxBody [data-lox-geraet]')].map(k => k.dataset.loxGeraet),
          gewaehlt: (document.querySelector('#loxBody [data-lox-geraet].on') || {dataset: {}}).dataset.loxGeraet || '',
          melder: (document.getElementById('loxMelder') || {}).value,
          ruhe: ruhe ? [ruhe.checked, ruhe.disabled] : null,
          ton: (document.querySelector('#loxBody .ks-ton.on') || {innerText: ''}).innerText.trim(),
          url: (document.getElementById('loxFrame').getAttribute('src') || ''), mass: t('#loxVorMass'),
          weiter: document.getElementById('loxNext').textContent, weiterAus: document.getElementById('loxNext').disabled}; }"""


async def _bis(bedingung, was, sekunden=10):
    for _ in range(int(sekunden * 20)):
        if bedingung():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"nicht erreicht: {was}")


async def _zeigt(app, geraet, pid, sekunden=20):
    await _bis(lambda: any((app.conn_prof.get(ws) or {}).get("id") == pid and not (app.conn_prof.get(ws) or {}).get("entwurf")
                           for ws, i in app.conn_info.items() if i.get("dev") == geraet), f"{geraet} zeigt {pid}", sekunden)


def _datei(cfg_ordner):
    return json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))


def _lauf(cfg_ordner, tmp_path, inhalt, geraete, schritte):
    """Server mit der Anlage und panels.json `inhalt`, je Geraet aus `geraete`
    ({name: viewport}) eine Visu mit ?device=, dann der Konfigurator;
    schritte(pg, app, visus) fuehrt den Test. Seitenfehler scheitern ihn."""
    (cfg_ordner / "panels.json").write_text(json.dumps(inhalt), encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"l1": 0, "pm_a": 1.0}
        app.panels, app.devices = konfig.load_panels_doc()
        app._presence_rebuild()
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                visus = {}
                for name, vp in geraete.items():
                    v = await b.new_page(viewport=vp)
                    v.on("pageerror", lambda e: fehler.append(str(e)))
                    await v.goto(f"http://127.0.0.1:{port}/?device={name}")
                    visus[name] = v
                await _bis(lambda: sum(1 for i in app.conn_info.values() if i.get("screen")) == len(geraete),
                           "alle Geraete mit gemeldeter Groesse")
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.wait_for_function("(" + json.dumps(list(geraete)) + ").every(n => DEVICE_SCREENS[n])")
                await schritte(pg, app, visus, port, b)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


async def _oeffnen(pg, ueber="geraete"):
    if ueber == "geraete":
        await pg.locator(".rub", has_text="Geräte").click()
        await pg.locator("#loxOpenBtn").click()
    else:
        await pg.locator(".rub", has_text="Übersicht").click()
        await pg.locator("#ovLoxOS").click()
    await pg.wait_for_selector("#loxOv:not([hidden])")


async def _bis_schritt5(pg, geraet="streifen", melder="PM", ton=None):
    """Schritte 1-4 durchklicken; steht danach auf Schritt 5."""
    await pg.locator(f'#loxBody [data-lox-geraet="{geraet}"]').click()
    await pg.locator("#loxNext").click()
    await pg.wait_for_selector("#loxMelder")
    await pg.locator("#loxMelder").select_option(melder)
    await pg.locator("#loxNext").click()
    if ton is not None:
        await pg.locator(f'#loxBody [data-lox-ton="{ton}"]').click()
    await pg.locator("#loxNext").click()
    await pg.wait_for_function("(document.getElementById('loxFrame').getAttribute('src') || '').startsWith('/?panel=')")
    await pg.locator("#loxNext").click()
    await pg.wait_for_function("document.getElementById('loxStep').textContent.includes('5 / 5')")


def test_assistent_vom_geraet_bis_zur_bento_seite(cfg_ordner, tmp_path):
    async def schritte(pg, app, visus, port, b):
        # Schritt 1: das Geraet; der Streifen ist gemeldet, "Weiter" erst mit Wahl
        await _oeffnen(pg, "uebersicht")
        st = await pg.evaluate(STAND)
        assert st["schritt"] == "Schritt 1 / 5" and st["geraete"] == ["streifen"] and st["weiterAus"], st
        assert "2560×720" in st["body"] and "Streifen" in st["body"], st
        await pg.locator('#loxBody [data-lox-geraet="streifen"]').click()
        st = await pg.evaluate(STAND)
        assert st["gewaehlt"] == "streifen" and not st["weiterAus"], st
        await pg.locator("#loxNext").click()

        # Schritt 2: Melder waehlen, Ruhe-Uhr ist vorausgewaehlt
        await pg.wait_for_selector("#loxMelder")
        st = await pg.evaluate(STAND)
        assert (st["schritt"], st["melder"], st["ruhe"]) == ("Schritt 2 / 5", "", [True, True]), st
        await pg.locator("#loxMelder").select_option("PM")
        assert (await pg.evaluate(STAND))["ruhe"] == [True, False]
        await pg.locator("#loxNext").click()

        # Schritt 3: Set edge, "Original" vorausgewaehlt, Petrol waehlen
        st = await pg.evaluate(STAND)
        assert st["schritt"] == "Schritt 3 / 5" and st["ton"] == "Original", st
        assert "Edge" in st["body"], st
        await pg.locator('#loxBody [data-lox-ton="190"]').click()
        assert (await pg.evaluate(STAND))["ton"] == "Petrol"
        await pg.locator("#loxNext").click()

        # Schritt 4: der Vorschlag, die Vorschau in Geraetegroesse zeigt die Bento-Seite
        await pg.wait_for_function("(document.getElementById('loxFrame').getAttribute('src') || '').startsWith('/?panel=loxos-streifen&entwurf=')")
        st = await pg.evaluate(STAND)
        assert st["schritt"] == "Schritt 4 / 5" and st["mass"].startswith("2560 × 720"), st
        assert "Uhr" in st["body"] and "Wetter" in st["body"] and "Licht" in st["body"], st
        await pg.frame_locator("#loxFrame").locator("#grid.bento > .bz").first.wait_for(state="attached")
        hinweis = await pg.locator("#loxVorHinweis").text_content()
        assert "Nicht übernommen" not in hinweis, hinweis
        await pg.screenshot(path=str(tmp_path / "loxos_assistent_startseite.png"))
        await pg.locator("#loxNext").click()

        # Schritt 5: Zusammenfassung, Fertig
        st = await pg.evaluate(STAND)
        assert st["schritt"] == "Schritt 5 / 5" and "LoxOS · streifen" in st["body"], st
        assert st["weiter"] == "Fertig – auf streifen anzeigen", st
        assert "Betriebsmodi" not in st["body"], "ohne Modi kein Hinweis"
        offen_vorher = await pg.evaluate("Object.keys(PANELS).sort()")
        assert "loxos-streifen" not in offen_vorher, "angelegt wird erst mit Fertig"
        await pg.locator("#loxNext").click()
        await pg.wait_for_selector("#loxOv[hidden]", state="attached")
        await _zeigt(app, "streifen", "loxos-streifen")
        await _bis(lambda: (_datei(cfg_ordner).get("devices") or {}).get("streifen", {}).get("presence") == "PM",
                   "Melder gespeichert")
        datei = _datei(cfg_ordner)
        neu = datei["panels"]["loxos-streifen"]
        assert (neu["title"], neu["tabs"], neu["ui"], neu["device"]) == (
            "LoxOS · streifen", ["auswahl"], {"tileSet": "edge", "tileHueEdge": 190},
            {"name": "streifen", "vw": 2560, "vh": 720}), neu
        assert len(neu["pickTabs"]) == 1 and neu["pickTabs"][0]["bento"]["format"] == {"vw": 2560, "vh": 720}, neu
        assert not neu.get("rooms") and not neu.get("cats"), neu
        assert datei["devices"]["streifen"] == {"auto": True, "modes": {}, "panel": "loxos-streifen", "presence": "PM", "ruhe": True}, datei["devices"]
        # die Visu des Streifens zeigt die Bento-Seite, ohne Leiste
        await visus["streifen"].wait_for_selector("#grid.bento > .bz", state="attached", timeout=15000)
        # danach steht der Bento-Editor der neuen Ansicht offen
        ed = await pg.evaluate("[cur, rubric, subPconf, curPickIdx]")
        assert ed == ["loxos-streifen", "pconf", "seiten", 0], ed
        await pg.wait_for_selector(".be-flaeche", state="visible")
        assert await pg.evaluate("document.getElementById('loxFrame').getAttribute('src')") is None, "der iframe ist ersetzt"
        await pg.screenshot(path=str(tmp_path / "loxos_assistent_editor.png"))
    _lauf(cfg_ordner, tmp_path, {"panels": {"zentral": ZENTRAL}}, {"streifen": STREIFEN}, schritte)


def test_assistent_ueberschreibt_nie(cfg_ordner, tmp_path):
    # wie der Server sie speichert, sonst saehe das Speichern aller Ansichten wie eine Aenderung aus
    alt = W.App._sanitize_panels({"loxos-streifen": {"title": "LoxOS · streifen", "tabs": ["favoriten"]}})["loxos-streifen"]

    async def schritte(pg, app, visus, port, b):
        await _oeffnen(pg)
        await _bis_schritt5(pg)
        assert "LoxOS · streifen 2" in (await pg.evaluate(STAND))["body"]
        await pg.locator("#loxNext").click()
        await _zeigt(app, "streifen", "loxos-streifen-2")
        await _bis(lambda: (_datei(cfg_ordner).get("devices") or {}).get("streifen", {}).get("panel") == "loxos-streifen-2",
                   "zugeordnet")
        datei = _datei(cfg_ordner)
        assert datei["panels"]["loxos-streifen"] == alt, "die bestehende Ansicht bleibt, wie sie ist"
        assert datei["panels"]["loxos-streifen-2"]["title"] == "LoxOS · streifen 2"
    _lauf(cfg_ordner, tmp_path, {"panels": {"zentral": ZENTRAL, "loxos-streifen": alt}}, {"streifen": STREIFEN}, schritte)


def test_abbrechen_aendert_nichts(cfg_ordner, tmp_path):
    async def schritte(pg, app, visus, port, b):
        vorher = (cfg_ordner / "panels.json").read_bytes()
        stand = await pg.evaluate("[Object.keys(PANELS).sort(), OFFEN.size, cur]")
        await _oeffnen(pg)
        await _bis_schritt5(pg, ton=190)
        await _bis(lambda: any(i.get("vorschau") for i in app.conn_info.values()), "die Vorschau ist verbunden")
        await pg.locator("#loxAbbrechen").click()
        await pg.wait_for_selector("#loxOv[hidden]", state="attached")
        assert await pg.evaluate("[Object.keys(PANELS).sort(), OFFEN.size, cur]") == stand
        assert await pg.evaluate("document.getElementById('loxFrame').getAttribute('src')") is None
        # Esc schliesst ebenso
        await _oeffnen(pg)
        await pg.keyboard.press("Escape")
        await pg.wait_for_selector("#loxOv[hidden]", state="attached")
        await asyncio.sleep(1)
        assert (cfg_ordner / "panels.json").read_bytes() == vorher
        assert app.device_list()["anonymous"] == [], "die Vorschau bleibt kein Geraet ohne Namen"
    _lauf(cfg_ordner, tmp_path, {"panels": {"zentral": ZENTRAL}}, {"streifen": STREIFEN}, schritte)


def test_streifen_steht_oben(cfg_ordner, tmp_path):
    # "alt" hat sich nie gemeldet (nur ein Eintrag in panels.json): unten, Groesse unbekannt
    inhalt = {"panels": {"zentral": ZENTRAL}, "devices": {"alt": {"presence": "PM"}}}

    async def schritte(pg, app, visus, port, b):
        await _oeffnen(pg)
        st = await pg.evaluate(STAND)
        assert st["geraete"] == ["streifen", "tablet", "alt"], st
        alt = await pg.locator('#loxBody [data-lox-geraet="alt"]').inner_text()
        assert "Größe noch unbekannt" in alt, alt
        # ein Geraet ohne Namen wird hier benannt und ist danach gewaehlt
        anon = await b.new_page(viewport=TABLET)
        await anon.goto(f"http://127.0.0.1:{port}/")
        await pg.wait_for_selector("#loxBody [data-lox-anon] .loxname", timeout=15000)
        await pg.locator("#loxBody [data-lox-anon] .loxname").fill("kueche")
        await pg.locator("#loxBody [data-lox-anon] [data-lox-name]").click()
        await pg.wait_for_function("document.querySelector('#loxBody [data-lox-geraet=\"kueche\"].on')", timeout=20000)
        # ohne gemeldeten Schirm: der Vorschlag nimmt das Zielgeraet
        await pg.locator('#loxBody [data-lox-geraet="alt"]').click()
        await pg.locator("#loxNext").click()
        await pg.locator("#loxNext").click()
        await pg.locator("#loxNext").click()
        await pg.wait_for_function("document.getElementById('loxVorMass').textContent.startsWith('2560 × 720')")
        assert "Größe noch unbekannt" in (await pg.evaluate(STAND))["body"]
        await pg.locator("#loxAbbrechen").click()
    _lauf(cfg_ordner, tmp_path, inhalt, {"streifen": STREIFEN, "tablet": TABLET}, schritte)


def test_ohne_melder(cfg_ordner, tmp_path):
    async def schritte(pg, app, visus, port, b):
        await _oeffnen(pg)
        await pg.locator('#loxBody [data-lox-geraet="streifen"]').click()
        await pg.locator("#loxNext").click()
        await pg.locator("#loxMelder").select_option("PM")
        await pg.locator("#loxMelder").select_option("")
        st = await pg.evaluate(STAND)
        assert st["ruhe"] == [True, True] and "ohne Melder" in st["body"], st
        await pg.locator("#loxNext").click()
        await pg.locator("#loxNext").click()
        await pg.wait_for_function("(document.getElementById('loxFrame').getAttribute('src') || '').startsWith('/?panel=')")
        await pg.locator("#loxNext").click()
        await pg.locator("#loxNext").click()
        await _zeigt(app, "streifen", "loxos-streifen")
        await _bis(lambda: (_datei(cfg_ordner).get("devices") or {}).get("streifen", {}).get("panel") == "loxos-streifen",
                   "zugeordnet")
        await asyncio.sleep(1)   # das Speichern der Geraete laeuft nach dem Umschalten
        d = _datei(cfg_ordner)
        assert d["devices"]["streifen"]["panel"] == "loxos-streifen", d["devices"]
        assert "presence" not in d["devices"]["streifen"] and "ruhe" not in d["devices"]["streifen"], d["devices"]
        assert "tileHueEdge" not in d["panels"]["loxos-streifen"]["ui"], "Original: kein Farbton gespeichert"
    _lauf(cfg_ordner, tmp_path, {"panels": {"zentral": ZENTRAL}}, {"streifen": STREIFEN}, schritte)


def test_hinweis_bei_betriebsmodi(cfg_ordner, tmp_path):
    inhalt = {"panels": {"zentral": ZENTRAL}, "devices": {"streifen": {"modes": {"nacht": "zentral"}}}}

    async def schritte(pg, app, visus, port, b):
        await _oeffnen(pg)
        await _bis_schritt5(pg)
        body = (await pg.evaluate(STAND))["body"]
        assert "Betriebsmodi" in body and "nacht" in body and "Geräte" in body, body
        await pg.locator("#loxNext").click()
        await _zeigt(app, "streifen", "loxos-streifen")
        await _bis(lambda: (_datei(cfg_ordner).get("devices") or {}).get("streifen", {}).get("presence") == "PM",
                   "Melder gespeichert")
        assert _datei(cfg_ordner)["devices"]["streifen"]["modes"] == {"nacht": "zentral"}, "Betriebsmodi bleiben"
    _lauf(cfg_ordner, tmp_path, inhalt, {"streifen": STREIFEN}, schritte)
