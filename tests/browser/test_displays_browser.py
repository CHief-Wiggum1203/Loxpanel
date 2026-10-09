"""Reiter Displays im Konfigurator (Chromium), bedient wie von Hand. Die
Geraeteliste zeigt jedes Geraet mit Typ, Zustand, Ansicht und Bildschirm: ein
Tablet mit Kennung, eines ohne (nach IP) und eines, das nur in panels.json
steht. Von dort wird die Ansicht gewechselt und ein Name vergeben, die Visu
folgt live. Im Editor darunter werden Display-Treiber, Modus, Automatik und
Praesenzmelder gesetzt und gespeichert: das steht danach in panels.json und
kommt nach dem Neuladen des Konfigurators und nach einem Neustart des Servers
wieder. Das Display-Kennwort bleibt beim Server: Der Konfigurator bekommt nur,
ob eines gespeichert ist. Der Config-Ordner ist umgeleitet (Fixture
cfg_ordner)."""
import asyncio
import copy
import json

import aiohttp
import pytest

from lox import KONFIGURATOR_GELADEN, W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {
    "PM": {"name": "Präsenz Flur", "type": "PresenceDetector", "uuidAction": "PM", "room": "r1", "cat": "c1",
           "states": {"active": "pm_a"}},
    "L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1", "isFavorite": True,
          "states": {"active": "sl"}},
}
PANELS = {"panels": {"wohnen": {"title": "Wohnen", "tabs": ["favoriten"]},
                     "kueche": {"title": "Küche", "tabs": ["favoriten"]}},
          "devices": {"flur": {"auto": True, "modes": {"nacht": "kueche"}}}}
ROUTEN = [("GET", "/api/devices", W.api_devices_get), ("POST", "/api/devices", W.api_save_devices),
          ("POST", "/api/device/switch", W.api_device_switch), ("POST", "/api/device/name", W.api_device_name)]
TABLET = ("?panel=wohnen&device=tablet", {"width": 1024, "height": 600})


def _app(cfg_ordner, panels=PANELS):
    (cfg_ordner / "panels.json").write_text(json.dumps(panels), encoding="utf-8")
    app = W.App({"host": "", "port": 80})       # liest Profile und Geraete aus panels.json
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"pm_a": 0, "sl": 0}
    return app


async def _bis(bedingung, was, sekunden=10):
    """Auf einen Zustand am Server warten; der laeuft in derselben Schleife."""
    for _ in range(int(sekunden * 20)):
        if bedingung():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"nicht erreicht: {was}")


async def _meldung(pg, sel, text):
    """Warten, bis die Meldungsleiste sel den Text zeigt (sie folgt erst der
    Antwort des Servers, nicht schon dem Klick)."""
    await pg.wait_for_function("([s, t]) => document.querySelector(s).textContent === t", arg=[sel, text])


# Stil eines Textfelds; Vergleich ist das Host-Feld unter Settings -> Miniserver.
# Fehlt einem Feld type="text", steht es browserweiss im dunklen Konfigurator.
STIL = "e => { const c = getComputedStyle(e); return [c.backgroundColor, c.color, c.borderTopColor]; }"


async def _wie_textfeld(pg, *felder):
    soll = await pg.locator("#ms_host").evaluate(STIL)
    for feld in felder:
        assert await feld.evaluate(STIL) == soll, await feld.evaluate("e => e.className")


def _geraet(app, name):
    return next((d for d in app.device_list()["devices"] if d["name"] == name), {})


async def _visu(b, port, fehler, adresse, groesse):
    """Visu in einem eigenen Browser-Kontext (eigener localStorage, wie ein
    eigenes Geraet)."""
    pg = await b.new_page(viewport=groesse)
    pg.on("pageerror", lambda e: fehler.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{port}/{adresse}")
    return pg


async def _displays(pg, port=None):
    """Konfigurator oeffnen (oder neu laden) und zum Reiter Displays gehen."""
    if port is None:
        await pg.reload()
    else:
        await pg.goto(f"http://127.0.0.1:{port}/config")
    await pg.wait_for_function(KONFIGURATOR_GELADEN)
    await pg.locator(".rub", has_text="Displays").click()


def test_geraeteliste_umschalten_und_benennen(cfg_ordner, tmp_path):
    async def lauf():
        app = _app(cfg_ordner)
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                tablet = await _visu(b, port, fehler, *TABLET)
                ohne = await _visu(b, port, fehler, "?panel=kueche", {"width": 800, "height": 1280})
                await _bis(lambda: len(app.conn_info) == 2 and all(i.get("screen") for i in app.conn_info.values()),
                           "beide Visus verbunden und Bildschirm gemeldet")
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await _displays(pg, port)
                liste = pg.locator("#ag_list")
                await liste.locator(".ag").nth(2).wait_for()
                # Das Geraet ohne Kennung steht mit seinem Kopplungscode in der Liste (Punkt 11)
                code = next(a["code"] for a in app.device_list()["anonymous"])
                assert await liste.locator(".agn").all_text_contents() == ["flur", "tablet", f"Code {code}"]

                flur = liste.locator('.ag[data-name="flur"]')
                assert await flur.locator(".dot").get_attribute("class") == "dot", "nur konfiguriert: offline"
                assert await flur.locator(".tag").text_content() == "Browser"
                assert await flur.locator("button").all_text_contents() == ["Entfernen"], "offline: nichts zu schalten, nur entfernen"

                tab = liste.locator('.ag[data-name="tablet"]')
                assert await tab.locator(".dot").get_attribute("class") == "dot on"
                assert await tab.locator(".tag").text_content() == "Browser"
                assert await tab.locator(".agip").text_content() == "127.0.0.1 · Visu offen"
                assert await tab.locator(".agsel").input_value() == "wohnen"
                assert await tab.locator("button").all_text_contents() == ["Ansicht wechseln", "Neu laden"]
                assert (await tab.locator(".agscr").text_content()).startswith("1024×600 quer")

                anon = liste.locator(f'.ag[data-code="{code}"][data-ip="127.0.0.1"]')
                assert (await anon.locator(".agip").text_content()).startswith(
                    "127.0.0.1 · Browser · Ansicht kueche · 800×1280 hoch")
                await _wie_textfeld(pg, anon.locator(".anname"))
                # Auch der Betriebsmodus-Assistent bietet das Geraet zum Benennen an
                await pg.locator("#mzOpenBtn").click()
                await _wie_textfeld(pg, pg.locator(f'#mzOv .mzanon[data-code="{code}"] .mzname'))
                await pg.locator("#mzX").click()

                # Ansicht wechseln: das Tablet laedt sich mit dem neuen Profil neu
                await tab.locator(".agsel").select_option("kueche")
                await tab.get_by_role("button", name="Ansicht wechseln").click()
                await tablet.wait_for_url(lambda u: "panel=kueche" in u and "device=tablet" in u)
                await tablet.wait_for_function("document.title === 'Küche'")
                await _meldung(pg, "#ag_toast", "✓ switch → 1")
                await _bis(lambda: _geraet(app, "tablet").get("profile") == "kueche"
                           and _geraet(app, "tablet").get("connections") == 1, "Tablet mit kueche verbunden")

                # Namen vergeben: das Geraet ohne Kennung verbindet sich als
                # "kinderzimmer" neu, erscheint in der Liste und im Editor
                await anon.locator(".anname").fill("kinderzimmer")
                await anon.get_by_role("button", name="Namen vergeben").click()
                await _meldung(pg, "#ag_toast", "✓ kinderzimmer")
                kind = liste.locator('.ag[data-name="kinderzimmer"]')
                await kind.wait_for(timeout=15000)
                assert await liste.locator(".agn").all_text_contents() == ["flur", "kinderzimmer", "tablet"]
                assert await kind.locator(".dot").get_attribute("class") == "dot on"
                assert await kind.locator(".agsel").input_value() == "kueche"
                assert await pg.locator("#dev_list .dev").evaluate_all("l => l.map(n => n.dataset.name)") == [
                    "flur", "kinderzimmer", "tablet"]
                assert await ohne.evaluate("localStorage.getItem('lp_device')") == "kinderzimmer"
                assert await tablet.evaluate("localStorage.getItem('lp_device')") is None, \
                    "das Tablet hat schon eine Kennung und bleibt, wie es ist"
                await pg.screenshot(path=str(tmp_path / "displays_liste.png"), full_page=True)

                # Der Name gilt auch nach einem Neuladen der Visu
                await ohne.reload()
                await _bis(lambda: sorted(i["dev"] for i in app.conn_info.values()) == ["kinderzimmer", "tablet"],
                           "nach dem Neuladen wieder als kinderzimmer verbunden")
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


def test_ansicht_wechseln_erreicht_den_agenten(cfg_ordner, tmp_path):
    """Linux-Panel mit Agent: "Ansicht wechseln" stellt die Visu per WebSocket
    um und gibt die Wahl dem Agenten dieser Zeile (ueber seine IP), der sie mit
    seiner naechsten Meldung uebernimmt (tests/test_agent.py spielt den Agenten
    selbst durch)."""
    async def lauf():
        app = _app(cfg_ordner)
        runner, port, bc = await visu_starten(app, ROUTEN + [("POST", "/api/agent/announce", W.api_agent_announce)])
        meldung = {"name": "wand", "panel": "wohnen", "ip": "127.0.0.1", "port": 9, "kiosk": True,
                   "features": ["panel"]}
        fehler = []
        try:
            async with aiohttp.ClientSession() as s, async_playwright() as p:
                async def melden():
                    async with s.post(f"http://127.0.0.1:{port}/api/agent/announce", json=meldung) as r:
                        return await r.json()
                assert "panel" not in await melden()
                b = await p.chromium.launch()
                wand = await _visu(b, port, fehler, "?panel=wohnen&device=wand", {"width": 1024, "height": 600})
                await _bis(lambda: _geraet(app, "wand").get("connections") == 1, "Visu des Panels verbunden")
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await _displays(pg, port)
                zeile = pg.locator('#ag_list .ag[data-name="wand"]')
                await zeile.wait_for()
                assert await zeile.locator(".tag").text_content() == "Agent"
                await zeile.locator(".agsel").select_option("kueche")
                await zeile.get_by_role("button", name="Ansicht wechseln").click()
                await wand.wait_for_url(lambda u: "panel=kueche" in u)
                await _meldung(pg, "#ag_toast", "✓ switch → 1")
                assert app.agent_wunsch == {"127.0.0.1": "kueche"}
                antwort = await melden()
                assert antwort["panel"] == "kueche"
                meldung["panel"] = antwort["panel"]          # Agent hat uebernommen
                assert "panel" not in await melden() and app.agent_wunsch == {}
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


def test_display_treiber_speichern_und_neu_laden(cfg_ordner, tmp_path):
    async def lauf():
        app = _app(cfg_ordner)
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                await _visu(b, port, fehler, *TABLET)
                await _bis(lambda: _geraet(app, "tablet").get("online"), "Tablet verbunden")
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await _displays(pg, port)
                await pg.locator("#displaysHost summary", has_text="Betriebsmodus-Automatik").click()
                editor = pg.locator("#dev_list")
                flur, tab = editor.locator('.dev[data-name="flur"]'), editor.locator('.dev[data-name="tablet"]')
                await tab.wait_for()          # kommt mit der ersten Abfrage der Geraeteliste dazu
                assert await editor.locator(".dev").evaluate_all("l => l.map(n => n.dataset.name)") == [
                    "flur", "tablet"]
                assert [await flur.locator(s).input_value() for s in (".dm_mode", ".dm_prof", ".dd_drv")] == [
                    "nacht", "kueche", ""]

                # Fully Kiosk: Host und Port stehen schon da (IP des Tablets, Standard-Port)
                await tab.locator(".dd_drv").select_option("fully")
                assert await tab.locator(".dd_host").input_value() == "127.0.0.1"
                assert await tab.locator(".dd_port").input_value() == "2323"
                await _wie_textfeld(pg, *(tab.locator(s) for s in (".dm_mode", ".dd_host", ".dd_port", ".dd_pw")))
                await tab.locator(".dd_pw").fill("geheim")
                await tab.locator(".dm_mode").fill("gaeste")
                await tab.locator(".dm_prof").select_option("kueche")
                await tab.locator(".dp_presence").select_option("PM")
                await flur.locator(".dev_auto").uncheck()
                async with pg.expect_response(lambda r: r.url.endswith("/api/devices")
                                              and r.request.method == "POST") as antwort:
                    await pg.locator("#dev_save").click()
                assert (await (await antwort.value).json())["ok"]
                await _meldung(pg, "#dev_toast", "✓ Gespeichert")

                geraete = {
                    "flur": {"auto": False, "modes": {"nacht": "kueche"}},
                    "tablet": {"auto": True, "modes": {"gaeste": "kueche"},
                               "display": {"driver": "fully", "host": "127.0.0.1", "port": 2323,
                                           "password": "geheim"},
                               "presence": "PM"}}
                doc = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))
                assert doc["devices"] == geraete
                assert doc["panels"] == PANELS["panels"], "die Profile bleiben, wie sie waren"
                assert app.presence_map == {"pm_a": ["tablet"]}, "Praesenzmelder sofort gekoppelt"

                # Konfigurator neu laden: alles steht wieder da, nur das
                # Kennwort nicht - das Feld sagt, dass es gespeichert ist
                await _displays(pg)
                await pg.locator("#displaysHost summary", has_text="Betriebsmodus-Automatik").click()
                await tab.wait_for()
                assert [await tab.locator(s).input_value() for s in (
                    ".dd_drv", ".dd_host", ".dd_port", ".dd_pw", ".dm_mode", ".dm_prof", ".dp_presence")] == [
                    "fully", "127.0.0.1", "2323", "", "gaeste", "kueche", "PM"]
                assert await tab.locator(".dd_pw").get_attribute("placeholder") == "unverändert lassen"
                assert await tab.locator(".dev_auto").is_checked()
                assert not await flur.locator(".dev_auto").is_checked()
                assert [await flur.locator(s).input_value() for s in (".dm_mode", ".dm_prof", ".dd_drv")] == [
                    "nacht", "kueche", ""]
                await pg.screenshot(path=str(tmp_path / "displays_editor.png"), full_page=True)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        assert W.App({"host": "", "port": 80}).devices == geraete, "nach einem Neustart dieselben Geraete"
    asyncio.run(lauf())


def test_display_kennwort_bleibt_beim_server(cfg_ordner, tmp_path):
    """Ein gespeichertes Display-Kennwort kommt nicht in den Konfigurator, das
    Feld sagt nur "unverändert lassen". Speichern ohne Eingabe behaelt es. Ein
    anderer Host verwirft es: Der Platzhalter sagt das schon beim Tippen, die
    Meldung nach dem Speichern."""
    async def lauf():
        panels = copy.deepcopy(PANELS)
        panels["devices"]["tablet"] = {"auto": True, "modes": {},
                                       "display": {"driver": "fully", "host": "127.0.0.1", "port": 2323,
                                                   "password": "geheim"}}
        app = _app(cfg_ordner, panels)
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []

        def kennwort():
            doc = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))
            return doc["devices"]["tablet"]["display"]["password"]
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                async with pg.expect_response(lambda r: r.url.endswith("/api/meta")) as meta:
                    await _displays(pg, port)
                assert "geheim" not in await (await meta.value).text()
                await pg.locator("#displaysHost summary", has_text="Betriebsmodus-Automatik").click()
                tab = pg.locator('#dev_list .dev[data-name="tablet"]')
                await tab.wait_for()
                pw = tab.locator(".dd_pw")
                assert await pw.input_value() == ""
                assert await pw.get_attribute("placeholder") == "unverändert lassen"
                assert "geheim" not in await pg.content()

                # Neu zeichnen (+ Modus) laesst den Hinweis stehen
                await tab.locator(".dm_add").click()
                assert await pw.get_attribute("placeholder") == "unverändert lassen"

                # Speichern ohne Eingabe: das Kennwort bleibt
                async with pg.expect_response(lambda r: r.url.endswith("/api/devices")
                                              and r.request.method == "POST") as antwort:
                    await pg.locator("#dev_save").click()
                assert "geheim" not in await (await antwort.value).text()
                await _meldung(pg, "#dev_toast", "✓ Gespeichert")
                assert kennwort() == "geheim"

                # Anderes Ziel: der Platzhalter sagt es beim Tippen, zurueck
                # zum alten Ziel gilt wieder "unverändert lassen"
                await tab.locator(".dd_host").fill("127.0.0.2")
                assert await pw.get_attribute("placeholder") == "Passwort (Fully)"
                await tab.locator(".dd_host").fill("127.0.0.1")
                assert await pw.get_attribute("placeholder") == "unverändert lassen"
                await tab.locator(".dd_drv").select_option("wallpanel")
                assert await pw.get_attribute("placeholder") == "Passwort (Fully)"
                await tab.locator(".dd_drv").select_option("fully")
                assert await pw.get_attribute("placeholder") == "unverändert lassen"

                # Mit anderem Host speichern: verworfen, die Meldung nennt das Geraet
                await tab.locator(".dd_host").fill("127.0.0.2")
                await pg.locator("#dev_save").click()
                await _meldung(pg, "#dev_toast", "✓ Gespeichert · Display-Kennwort nicht übernommen, "
                                                 "weil Host oder Treiber geändert: tablet")
                assert "warn" in await pg.locator("#dev_toast").get_attribute("class")
                assert kennwort() == ""
                # Der 4-s-Timer der Meldung vom ersten Speichern blendet die
                # Warnung nicht aus
                await pg.wait_for_timeout(4300)
                assert "show" in await pg.locator("#dev_toast").get_attribute("class")
                await pg.screenshot(path=str(tmp_path / "displays_kennwort.png"), full_page=True)
                await tab.locator(".dm_add").click()
                assert await pw.get_attribute("placeholder") == "Passwort (Fully)", "kein Kennwort mehr"

                # Neues Kennwort fuer das neue Ziel: Nach dem Speichern sagt das
                # Feld ohne Neuzeichnen, dass ein leeres es behaelt
                await pw.fill("neu")
                async with pg.expect_response(lambda r: r.url.endswith("/api/devices")
                                              and r.request.method == "POST"):
                    await pg.locator("#dev_save").click()
                await _meldung(pg, "#dev_toast", "✓ Gespeichert")
                assert kennwort() == "neu"
                await pw.fill("")
                assert await pw.get_attribute("placeholder") == "unverändert lassen"
                async with pg.expect_response(lambda r: r.url.endswith("/api/devices")
                                              and r.request.method == "POST"):
                    await pg.locator("#dev_save").click()
                assert kennwort() == "neu"
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


def test_display_entfernen(cfg_ordner):
    """"Entfernen" in der Geraeteliste loescht die Einstellungen eines Displays und
    speichert sofort. Ein Display, das nicht verbunden ist, verschwindet ganz;
    eines, das verbunden ist, kommt ohne Einstellungen wieder (die Rueckfrage
    sagt das vorher). Ein verbundenes ohne Einstellungen hat nichts zu entfernen."""
    panels = copy.deepcopy(PANELS)
    panels["devices"]["tablet"] = {"auto": True, "modes": {"gaeste": "wohnen"}}

    async def lauf():
        app = _app(cfg_ordner, panels)
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler, fragen = [], []

        async def dialog(d):
            fragen.append(d.message)
            await d.accept()
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                await _visu(b, port, fehler, *TABLET)
                await _visu(b, port, fehler, "?panel=wohnen&device=ohne", {"width": 800, "height": 480})
                await _bis(lambda: _geraet(app, "tablet").get("online") and _geraet(app, "ohne").get("online"),
                           "Tablets verbunden")
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                pg.on("dialog", dialog)
                await _displays(pg, port)
                liste = pg.locator("#ag_list")
                await liste.locator('.ag[data-name="ohne"]').wait_for()
                knoepfe = await liste.locator(".ag[data-name]").evaluate_all(
                    "l => l.map(n => [n.dataset.name, !!n.querySelector('[data-act=entfernen]')])")
                assert knoepfe == [["flur", True], ["ohne", False], ["tablet", True]], knoepfe

                # flur ist nicht verbunden: weg aus Liste, Editor und panels.json
                await liste.locator('.ag[data-name="flur"] [data-act="entfernen"]').click()
                await _meldung(pg, "#ag_toast", "✓ Entfernt: flur")
                assert "flur" in fragen[0] and "verbunden" not in fragen[0], fragen
                doc = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))
                assert sorted(doc["devices"]) == ["tablet"], doc["devices"]
                assert "flur" not in app.devices
                await pg.wait_for_function("!document.querySelector('#ag_list .ag[data-name=\"flur\"]')")
                assert await pg.locator('#dev_list .dev[data-name="flur"]').count() == 0

                # das Tablet ist verbunden: es kommt ohne Einstellungen wieder
                await liste.locator('.ag[data-name="tablet"] [data-act="entfernen"]').click()
                await _meldung(pg, "#ag_toast", "✓ Entfernt: tablet")
                assert "verbunden" in fragen[1], fragen
                doc = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))
                assert "devices" not in doc and app.devices == {}, doc     # ohne Displays faellt der Schluessel weg
                await pg.wait_for_function("""() => { const n = document.querySelector('#ag_list .ag[data-name="tablet"]');
                    return n && !n.querySelector('[data-act=entfernen]'); }""")
                await pg.locator('#dev_list .dev[data-name="tablet"]').wait_for(state="attached")
                assert await pg.locator('#dev_list .dev[data-name="tablet"] .dm_mode').input_value() == ""
                assert doc["panels"] == panels["panels"], "die Profile bleiben, wie sie waren"
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
    asyncio.run(lauf())


def test_zwei_displays_schnell_hintereinander_entfernen(cfg_ordner):
    """Das zweite Entfernen kommt, waehrend das erste noch speichert (hier haelt
    der Test die erste Anfrage eine Sekunde auf). Weder darf das zweite Speichern
    das erste Display aus dem Editor wieder einlesen, noch eine fruehere Anfrage
    eine spaetere ueberholen: am Ende sind beide weg."""
    panels = copy.deepcopy(PANELS)
    panels["devices"]["kueche-wand"] = {"auto": True, "modes": {"gaeste": "wohnen"}}

    async def lauf():
        app = _app(cfg_ordner, panels)
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler, posts = [], []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

                async def bremse(route):
                    if route.request.method == "POST":
                        posts.append(json.loads(route.request.post_data)["devices"])
                        if len(posts) == 1:
                            await asyncio.sleep(1)
                    await route.continue_()
                await pg.route("**/api/devices", bremse)
                await _displays(pg, port)
                liste = pg.locator("#ag_list")
                await liste.locator('.ag[data-name="kueche-wand"]').wait_for()
                await liste.locator('.ag[data-name="flur"] [data-act="entfernen"]').click()
                await liste.locator('.ag[data-name="kueche-wand"] [data-act="entfernen"]').click()
                await _meldung(pg, "#ag_toast", "✓ Entfernt: kueche-wand")
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        assert [sorted(d) for d in posts] == [["kueche-wand"], []], posts
        doc = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))
        assert "devices" not in doc and app.devices == {}, doc
    asyncio.run(lauf())
