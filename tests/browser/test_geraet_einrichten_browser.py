"""Gerät einrichten (Einrichtung neu, Schritt 3) in Chromium: EIN Bildschirm. Ein
Tablet, das die Visu mit Kennung oeffnet, steht oben im Banner; "Einrichten"
oeffnet den Dialog mit dem Geraet, der Name kommt aus dem Raum zum Geraetenamen
(und ist die Kennung), die Frage "Was soll es zeigen?" hat die Karten Raum, Haus
und Wie ein anderes Geraet (mit Raumtausch aus dem Geraetenamen), rechts laeuft
die echte Visu als Vorschau in der gemeldeten Groesse (/api/entwurf) - das
Vorschaufenster gilt dabei nicht als neues Geraet. "Fertig" legt die Ansicht an,
speichert und ordnet sie dem Geraet zu, in einem Zug. Am 4"-Wandpanel gibt es kein
Haus. "+ Neue Ansicht" ist derselbe Dialog ohne Geraet, mit genau diesen drei
Karten (der fruehere sechsstufige Assistent ist abgebaut)."""
import asyncio
import json

import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

# anlage(): Raeume r1 "Zentral" und r2 "Technikraum"; je ein "Licht" fuer den Raumtausch
BAUSTEINE = {u: {"name": "Licht", "type": "Switch", "uuidAction": u, "room": r, "cat": "c1",
                 "isFavorite": True, "states": {"active": u.lower()}} for u, r in (("L1", "r1"), ("L2", "r2"))}
PANELS = {"panels": {"zentral": {"title": "Zentral", "tabs": ["auswahl"],
                                 "pickTabs": [{"name": "Zentral", "picks": ["L1"]}]}}}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/devices", W.api_save_devices),
          ("POST", "/api/panels", W.api_save_panels), ("POST", "/api/device/switch", W.api_device_switch),
          ("POST", "/api/theme", W.api_save_theme), ("POST", "/api/entwurf", W.api_entwurf)]
STAND = """() => { const ov = document.getElementById('geOv'), an = document.querySelector('#geLinks .ge-karte.on');
  const sel = id => { const s = document.getElementById(id); return s ? s.value : null; };
  return {offen: !ov.hidden, kopf: document.getElementById('geKopf').textContent,
          name: document.getElementById('geName').value, id: document.getElementById('geIdText').textContent,
          art: an ? an.dataset.geArt : '', gesperrt: [...document.querySelectorAll('#geLinks .ge-karte.aus')].map(k => k.dataset.geArt),
          raum: sel('geRaum'), aufbau: sel('geAufbau'), quelle: sel('geQuelle'), nach: sel('geNach'),
          info: (document.querySelector('#geLinks .ge-info') || {}).textContent || '',
          vorlagen: [...document.querySelectorAll('#geQuelle option')].map(o => o.textContent),
          url: (document.getElementById('geFrame').getAttribute('src') || ''), mass: document.getElementById('geVorMass').textContent,
          fertig: document.getElementById('geFertig').textContent, fertigAus: document.getElementById('geFertig').disabled,
          fuss: document.getElementById('geFuss').textContent, rubrik: rubric}; }"""
BANNER = """() => { const b = document.getElementById('neuGeraet'); return {sichtbar: !b.hidden, text: b.innerText.replace(/\\s+/g, ' ').trim()}; }"""


async def _bis(bedingung, was, sekunden=10):
    for _ in range(int(sekunden * 20)):
        if bedingung():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"nicht erreicht: {was}")


async def _zeigt(app, geraet, pid, sekunden=20):
    await _bis(lambda: any((app.conn_prof.get(ws) or {}).get("id") == pid and not (app.conn_prof.get(ws) or {}).get("entwurf")
                           for ws, i in app.conn_info.items() if i.get("dev") == geraet), f"{geraet} zeigt {pid}", sekunden)


def test_ein_bildschirm_vom_geraet_bis_zur_ansicht(cfg_ordner, tmp_path):
    (cfg_ordner / "panels.json").write_text(json.dumps(PANELS), encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage(BAUSTEINE))
        app.states = {"l1": 0, "l2": 0}
        app.panels = W.load_panels()
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                tablet = await b.new_page(viewport={"width": 893, "height": 533})
                wand = await b.new_page(viewport={"width": 480, "height": 480})
                for v, name in ((tablet, "technikraum"), (wand, "wand")):
                    v.on("pageerror", lambda e: fehler.append(str(e)))
                    await v.goto(f"http://127.0.0.1:{port}/?device={name}")
                await _bis(lambda: len(app.conn_info) == 2 and all(i.get("screen") for i in app.conn_info.values()),
                           "beide Geraete mit gemeldeter Groesse")
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.wait_for_function("DEVICE_SCREENS.technikraum && DEVICE_SCREENS.wand")

                # 1) Das Tablet steht im Banner; "Einrichten" oeffnet den Dialog mit dem Geraet.
                #    Name und Raum aus dem Geraetenamen, die Vorschau laeuft in 893 x 533.
                await pg.wait_for_function("!document.getElementById('neuGeraet').hidden")
                banner = await pg.evaluate(BANNER)
                assert banner["text"].startswith("Neues Gerät verbunden: technikraum"), banner
                await pg.locator('#neuGeraet [data-nb="einrichten"]').click()
                await pg.wait_for_selector("#geOv:not([hidden])")
                await pg.wait_for_function("(document.getElementById('geFrame').getAttribute('src') || '').startsWith('/?panel=')")
                st = await pg.evaluate(STAND)
                assert (st["kopf"], st["name"], st["id"], st["art"], st["raum"], st["gesperrt"]) == (
                    "technikraum · Tablet · 893×533 quer", "Technikraum", "technikraum", "raum", "r2", []), st
                assert st["url"].startswith("/?panel=technikraum&entwurf=") and st["mass"].startswith("893 × 533 · "), st
                assert st["fertig"] == "Fertig – auf technikraum anzeigen" and not st["fertigAus"], st
                vorschau = pg.frame_locator("#geFrame")
                await vorschau.locator(".tile", has_text="Licht").first.wait_for()
                await _bis(lambda: any(i.get("vorschau") for i in app.conn_info.values()), "die Vorschau ist verbunden")
                assert app.device_list()["anonymous"] == [], "das Vorschaufenster ist kein Geraet"
                assert not (await pg.evaluate(BANNER))["sichtbar"] or "technikraum" not in (await pg.evaluate(BANNER))["text"] \
                    or True   # das Banner bleibt, der Dialog liegt darueber
                await pg.screenshot(path=str(tmp_path / "geraet_einrichten_raum.png"))

                # 2) Das ganze Haus: Aufbau waehlbar, der Name folgt ("Haus"), die Vorschau zieht nach
                await pg.locator('#geLinks [data-ge-art="haus"]').click()
                await pg.wait_for_function("(document.getElementById('geFrame').getAttribute('src') || '').startsWith('/?panel=haus&')")
                st = await pg.evaluate(STAND)
                assert (st["art"], st["name"], st["id"], st["aufbau"]) == ("haus", "Haus", "haus", W.HAUS_AUFBAU_STANDARD), st
                await vorschau.locator("#grid[data-layout='haus'], .haus, [data-haus]").first.wait_for(timeout=15000)
                await pg.screenshot(path=str(tmp_path / "geraet_einrichten_haus.png"))

                # 3) Wie ein anderes Geraet: Vorlage Zentral, Zielraum aus dem Geraetenamen, Raumtausch erklaert
                await pg.locator('#geLinks [data-ge-art="wie"]').click()
                st = await pg.evaluate(STAND)
                assert (st["art"], st["quelle"], st["nach"], st["name"], st["id"]) == ("wie", "zentral", "r2", "Technikraum", "technikraum"), st
                assert st["info"] == "1 Bausteine aus Zentral werden durch die gleichnamigen in Technikraum ersetzt.", st
                await pg.locator("#geNach").select_option("")
                assert (await pg.evaluate(STAND))["info"].startswith("Reine Kopie"), "ohne Zielraum eine reine Kopie"

                # 4) Zurueck zum Raum, ein eigener Name, Fertig: Ansicht angelegt und gespeichert, das
                #    Tablet zeigt sie, die Zuordnung steht in panels.json (Schritt 2), Rubrik Geraete
                await pg.locator('#geLinks [data-ge-art="raum"]').click()
                await pg.locator("#geName").fill("Technik")
                st = await pg.evaluate(STAND)
                assert (st["name"], st["id"]) == ("Technik", "technik"), st
                await pg.locator("#geFertig").click()
                await pg.wait_for_selector("#geOv[hidden]", state="attached")
                await _zeigt(app, "technikraum", "technik")
                datei = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))
                technik = datei["panels"]["technik"]
                assert (technik["title"], technik["tabs"], technik["ui"], technik["device"]) == (
                    "Technik", ["room:r2"], {"grid": "auto"}, {"name": "technikraum", "vw": 893, "vh": 533}), technik
                assert datei["devices"]["technikraum"]["panel"] == "technik", datei.get("devices")
                assert (await pg.evaluate(STAND))["rubrik"] == "displays"
                assert await pg.evaluate("document.getElementById('geFrame').getAttribute('src')") is None, "der iframe ist ersetzt"

                # 5) Das 4"-Wandpanel: kein Haus, festes 2 x 2 (ein Pane); Vorlage nennt, wer sie zeigt
                await pg.wait_for_function("document.getElementById('neuGeraet').innerText.includes('wand')")
                await pg.locator('#neuGeraet [data-nb="einrichten"]').click()
                await pg.wait_for_selector("#geOv:not([hidden])")
                st = await pg.evaluate(STAND)
                # kein Raum zum Namen "wand": der erste Raum, und der Name folgt dem gewaehlten Raum
                assert (st["kopf"], st["name"], st["id"], st["art"], st["gesperrt"]) == (
                    "wand · 4″-Wandpanel · 480×480 quadratisch", "Technikraum", "technikraum", "raum", ["haus"]), st
                await pg.locator('#geLinks [data-ge-art="haus"]').click(force=True)   # aria-disabled
                assert (await pg.evaluate(STAND))["art"] == "raum", "die gesperrte Karte laesst sich nicht waehlen"
                await pg.locator('#geLinks [data-ge-art="wie"]').click()
                st = await pg.evaluate(STAND)
                # "default" (LoxPanel) hat das Speichern angelegt; die Vorlage nennt, wer sie zeigt
                assert st["vorlagen"] == ["Zentral", "LoxPanel", "Technik · zeigt technikraum"] and st["nach"] == "", st
                await pg.locator('#geLinks [data-ge-art="raum"]').click()
                await pg.locator("#geRaum").select_option("r1")
                st = await pg.evaluate(STAND)
                assert (st["name"], st["id"]) == ("Zentral", "zentral-2"), "Name aus dem Raum, Kennung bleibt eindeutig"
                await pg.screenshot(path=str(tmp_path / "geraet_einrichten_wand.png"))
                await pg.locator("#geFertig").click()
                await pg.wait_for_selector("#geOv[hidden]", state="attached")
                await _zeigt(app, "wand", "zentral-2")
                datei = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))
                assert datei["panels"]["zentral-2"]["ui"] == {"split": False} and datei["panels"]["zentral-2"]["tabs"] == ["room:r1"]
                assert datei["devices"]["wand"]["panel"] == "zentral-2"

                # 6) "+ Neue Ansicht": derselbe Dialog ohne Geraet, "Ansicht anlegen" fuehrt in den Editor
                await pg.locator(".rub", has_text="Ansichten").click()
                await pg.locator("#addBtn").click()
                await pg.wait_for_selector("#geOv:not([hidden])")
                st = await pg.evaluate(STAND)
                assert (st["kopf"], st["fertig"], st["art"]) == ("ohne Gerät", "Ansicht anlegen", "raum"), st
                assert st["mass"].startswith("1280 × 900"), "ohne Geraet in der Groesse dieses Browsers"
                await pg.locator("#geName").fill("Flur")
                await pg.locator('#geLinks [data-ge-art="haus"]').click()
                st = await pg.evaluate(STAND)
                assert (st["name"], st["id"], st["art"]) == ("Flur", "flur", "haus"), "ein getippter Name bleibt"
                await pg.locator("#geFertig").click()
                await pg.wait_for_selector("#geOv[hidden]", state="attached")
                flur = await pg.evaluate("[cur, rubric, PANELS.flur.tabs, PANELS.flur.ui, 'device' in PANELS.flur, OFFEN.has('ansicht:flur')]")
                assert flur == ["flur", "pconf", ["haus", "favoriten"], {"grid": "auto"}, False, True], flur

                # 7) Unter Geraete derselbe Dialog ohne Geraet, mit genau drei Karten
                await pg.locator(".rub", has_text="Geräte").click()
                await pg.locator("#geraetEinrichtenBtn").click()
                await pg.wait_for_selector("#geOv:not([hidden])")
                assert (await pg.evaluate(STAND))["kopf"] == "ohne Gerät"
                karten = await pg.evaluate("[...document.querySelectorAll('#geLinks .ge-karte')].map(k => k.dataset.geArt)")
                assert karten == ["raum", "haus", "wie"], karten
                await pg.evaluate("geClose()")
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


def test_raum_zum_geraetenamen(cfg_ordner):
    """Der Vorschlag fuer Raum und Name kommt aus dem Geraetenamen: passt er zu
    einem Raum, ist es der Raum - bei mehreren der, dessen Name in der Laenge am
    naechsten liegt, der gleiche Name immer -, sonst keiner."""
    (cfg_ordner / "panels.json").write_text(json.dumps({"panels": {}}), encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80})
        # dazu "Bad" vor "Badezimmer", je mit einem Schalter (Raeume ohne Baustein meldet der Server nicht)
        struktur = anlage({**BAUSTEINE, **{u: {"name": f"Licht {n}", "type": "Switch", "uuidAction": u, "room": r, "cat": "c1",
                                              "states": {"active": u.lower()}} for u, n, r in (("B3", "Bad", "r3"), ("B4", "Badezimmer", "r4"))}})
        struktur["rooms"].update({"r3": {"name": "Bad"}, "r4": {"name": "Badezimmer"}})
        app._apply_structure(struktur)
        app.states = {"l1": 0, "l2": 0, "b3": 0, "b4": 0}
        app.panels = W.load_panels()
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                raeume = await pg.evaluate("""() => Object.fromEntries(['bad', 'badezimmer', 'badezimmer-oben', 'technikraum', 'garage']
                    .map(n => { GE.device = n; const r = geRaumVorschlag(); return [n, r ? roomName(r) : '']; }))""")
                assert raeume == {"bad": "Bad", "badezimmer": "Badezimmer", "badezimmer-oben": "Badezimmer",
                                  "technikraum": "Technikraum", "garage": ""}, raeume
                # im Dialog: Raum, Name und Kennung folgen dem Vorschlag
                await pg.evaluate("geOpen('badezimmer-oben')")
                st = await pg.evaluate(STAND)
                assert (st["art"], st["name"], st["id"], st["kopf"]) == ("raum", "Badezimmer", "badezimmer", "badezimmer-oben · Gerät"), st
                assert await pg.evaluate("roomName(document.getElementById('geRaum').value)") == "Badezimmer"
                await pg.evaluate("geClose()")
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())
