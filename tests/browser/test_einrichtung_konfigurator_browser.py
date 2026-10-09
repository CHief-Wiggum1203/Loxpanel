"""Ersteinrichtung im Konfigurator (Chromium): Solange der Server keine Struktur
vom Miniserver hat, oeffnet der Konfigurator Settings -> Miniserver mit einem
Hinweis, und alles andere ausser der Sicherung ist gesperrt. Steht die
Verbindung - ueber "Verbinden & Speichern" oder von selbst -, laedt er neu und
zeigt den naechsten Schritt. Config-Ordner umgeleitet (Fixture cfg_ordner),
reconnect() ersetzt."""
import asyncio
import json
import socket
import types

import pytest

from aiohttp import web

from lox import KONFIGURATOR_GELADEN, W, anlage, serve

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {
    "L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
          "states": {"active": "l"}},
    "J": {"name": "Jalousie", "type": "Jalousie", "uuidAction": "J", "room": "r2", "cat": "c1",
          "states": {"position": "j"}},
}
# Was der Konfigurator ohne Struktur sperrt: alle Rubriken ausser Settings und
# dort alle Reiter ausser Miniserver und Sicherung.
GESPERRT = ["overview", "assistant", "pconf", "displays", "devices"]
REITER_GESPERRT = ["intercom", "sip", "audio", "calendar", "newpanel"]

ZUSTAND = """() => {
  const sichtbar = id => !document.getElementById(id).hidden;
  return {
    rubrik: rubric, reiter: subSet,
    gesperrt: [...document.querySelectorAll('.rub:disabled')].map(b => b.dataset.rub),
    reiterGesperrt: [...document.querySelectorAll('.stab:disabled')].map(b => b.dataset.sub),
    neuesPanel: document.getElementById('addBtn').disabled,
    liste: document.getElementById('plist').classList.contains('gesperrt'),
    hinweis: sichtbar('einr'), stand: document.getElementById('einrStand').textContent,
    weiter: sichtbar('einrOk') ? document.getElementById('einrOkText').textContent : null,
    pane: [...document.querySelectorAll('#setHost .spane.active')].map(p => p.dataset.sub),
  };
}"""


async def _konfigurator(app, schritte, warten="#einr:not([hidden])", sprache=None):
    """Server mit den Routen des Konfigurators, config.html oeffnen (in
    `sprache`, sonst wie der Browser), auf `warten` warten und
    schritte(page) ausfuehren."""
    ui = web.Application()
    ui["app"] = app
    for pfad, h in (("/config", W.config_index), ("/api/meta", W.api_meta), ("/api/backup", W.api_backup),
                    ("/api/settings", W.api_settings), ("/api/devices", W.api_devices_get), ("/i18n.js", W.i18n_js), ("/raster.js", W.raster_js)):
        ui.router.add_get(pfad, h)
    ui.router.add_post("/api/settings/miniserver", W.api_settings_ms)
    runner, port = await serve(ui)
    fehler = []
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch()
            pg = await b.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
            pg.on("pageerror", lambda e: fehler.append(str(e)))
            if sprache:
                await pg.add_init_script(f"localStorage.setItem('lp_ui_lang', {json.dumps(sprache)})")
            await pg.goto(f"http://127.0.0.1:{port}/config")
            await pg.wait_for_selector(warten)
            res = await schritte(pg)
            await b.close()
    finally:
        await runner.cleanup()
    assert not fehler, fehler
    return res


def test_fuehrt_zuerst_zum_miniserver(cfg_ordner, tmp_path):
    """Frisches Geraet: erst ein falsches Kennwort, dann das richtige."""
    async def lauf():
        app = W.App(W._config())
        versuche = []

        async def reconnect(ms=None):
            # wie App.reconnect: api_settings_ms gibt den zu pruefenden Zugang mit
            versuche.append(dict(ms) if ms is not None else W._config())
            if len(versuche) == 1:
                raise RuntimeError("Anmeldung abgelehnt")
            app.client = types.SimpleNamespace()      # steht fuer den neuen Client
            app._apply_structure(anlage(BAUSTEINE))
            return len(app.controls)
        app.reconnect = reconnect

        async def schritte(pg):
            frisch = await pg.evaluate(ZUSTAND)
            await pg.screenshot(path=str(tmp_path / "einrichtung_konfigurator.png"))
            # Jeder andere Weg fuehrt zurueck, auch der Assistent oeffnet nicht
            await pg.evaluate("() => { setRubric('pconf'); wzOpen(); }")
            umweg = await pg.evaluate(ZUSTAND)
            assistent = await pg.evaluate("document.getElementById('wzOv').hidden")
            await pg.locator(".stab", has_text="Sicherung").click()
            sicherung = await pg.evaluate(ZUSTAND)
            await pg.locator(".stab", has_text="Miniserver").click()
            await pg.fill("#ms_host", "10.0.0.5")
            await pg.fill("#ms_user", "visu")
            await pg.fill("#ms_pass", "falsch")
            await pg.click("#ms_save")
            await pg.wait_for_function("document.getElementById('einrStand').textContent"
                                       ".includes('Anmeldung abgelehnt')")
            await pg.wait_for_timeout(3500)       # ein Nachfragen beim Server ueberdauert die Zeile
            falsch = await pg.evaluate(ZUSTAND)
            await pg.fill("#ms_pass", "richtig")
            async with pg.expect_navigation():
                await pg.click("#ms_save")
            await pg.wait_for_function(KONFIGURATOR_GELADEN)
            await pg.wait_for_selector("#einrOk:not([hidden])")
            verbunden = await pg.evaluate(ZUSTAND)
            await pg.screenshot(path=str(tmp_path / "einrichtung_verbunden.png"))
            await pg.click("#einrAssistent")
            weiter = await pg.evaluate("rubric")
            # Gemeldet am Tablet: ohne Neuladen blieb die Raumliste leer ("alle 0 sichtbar")
            await pg.locator(".rub", has_text="Panel Configuration").click()
            await pg.locator(".stab", has_text="Räume").click()
            raeume = (await pg.inner_text("#cntRooms"),
                      await pg.evaluate("[...document.querySelectorAll('#rooms .opt .nm')].map(e => e.textContent)"))
            return frisch, umweg, assistent, sicherung, falsch, verbunden, weiter, raeume
        return await _konfigurator(app, schritte), versuche
    (frisch, umweg, assistent, sicherung, falsch, verbunden, weiter, raeume), versuche = asyncio.run(lauf())

    assert frisch == {"rubrik": "settings", "reiter": "miniserver", "gesperrt": GESPERRT,
                      "reiterGesperrt": REITER_GESPERRT, "neuesPanel": True, "liste": True,
                      "hinweis": True, "stand": "Noch kein Miniserver eingetragen.", "weiter": None,
                      "pane": ["miniserver"]}
    assert umweg == frisch and assistent, "Profile, Displays und Assistent warten auf die Struktur"
    assert sicherung["pane"] == ["backup"], "eine Sicherung einspielen geht auch vorher"
    assert falsch["stand"] == ("Anmeldung am Miniserver gescheitert. Der Zugang wurde nicht gespeichert. "
                               "(Anmeldung abgelehnt)")
    assert falsch["gesperrt"] == GESPERRT and falsch["hinweis"]
    assert [(v["host"], v["user"], v["pass"]) for v in versuche] == [("10.0.0.5", "visu", "falsch"),
                                                                   ("10.0.0.5", "visu", "richtig")]
    assert verbunden == {"rubrik": "settings", "reiter": "miniserver", "gesperrt": [], "reiterGesperrt": [],
                         "neuesPanel": False, "liste": False, "hinweis": False, "stand": "",
                         "weiter": "Bausteine geladen: 2. Alle Bereiche sind jetzt offen.",
                         "pane": ["miniserver"]}
    assert weiter == "assistant"
    assert raeume == ("alle 2 sichtbar", ["Technikraum", "Zentral"]), "Raeume frisch vom Server"


def test_verbindet_von_selbst(cfg_ordner):
    """Zugang eingetragen, der Server verbindet noch: Der Konfigurator zeigt
    den Stand, fragt nach und gibt frei, sobald die Struktur da ist."""
    async def lauf():
        app = W.App({"host": "10.0.0.5", "port": 443})

        async def schritte(pg):
            verbindet = await pg.evaluate(ZUSTAND)
            app._ms_fehler = "Zeitüberschreitung"
            await pg.wait_for_function("document.getElementById('einrStand').textContent"
                                       ".includes('Zeitüberschreitung')")
            gescheitert = await pg.evaluate(ZUSTAND)
            async with pg.expect_navigation(timeout=10000):
                app._ms_fehler = ""
                app._apply_structure(anlage(BAUSTEINE))
            await pg.wait_for_selector("#einrOk:not([hidden])")
            return verbindet, gescheitert, await pg.evaluate(ZUSTAND)
        return await _konfigurator(app, schritte)
    verbindet, gescheitert, verbunden = asyncio.run(lauf())

    assert verbindet["stand"] == "Verbindung zu 10.0.0.5 wird aufgebaut …"
    assert verbindet["gesperrt"] == GESPERRT
    assert gescheitert["stand"] == "Keine Verbindung zu 10.0.0.5: Zeitüberschreitung"
    assert verbunden["gesperrt"] == [] and not verbunden["hinweis"]
    assert verbunden["weiter"] == "Bausteine geladen: 2. Alle Bereiche sind jetzt offen."


TEXTE = {
    "de": ["Zuerst den Miniserver verbinden",
           "Ohne Verbindung kennt LoxPanel weder Räume noch Bausteine. Adresse, Benutzer und Passwort eintragen, "
           "dann „Verbinden & Speichern“. Danach sind alle Bereiche offen.",
           "Erst den Miniserver verbinden",
           "Der gespeicherte Zugang ist nicht verbunden. Angaben prüfen und erneut „Verbinden & Speichern“.",
           "Verbindung zu 10.0.0.5 wird aufgebaut …", "Keine Verbindung zu 10.0.0.5: timeout",
           "Mit dem Miniserver verbunden", "Panel einrichten", "Sicherung einspielen",
           "Bausteine geladen: 2. Alle Bereiche sind jetzt offen."],
    "en": ["Connect the Miniserver first",
           "Without a connection LoxPanel knows neither rooms nor blocks. Enter address, user and password, "
           "then “Connect & save”. After that all sections are open.",
           "Connect the Miniserver first",
           "The saved access is not connected. Check the entries and “Connect & save” again.",
           "Connecting to 10.0.0.5 …", "No connection to 10.0.0.5: timeout",
           "Connected to the Miniserver", "Set up a panel", "Restore backup",
           "Blocks loaded: 2. All sections are open now."],
}


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_jeder_stand_in_beiden_sprachen(cfg_ordner, sprache):
    """Zugang gespeichert, aber nicht uebernommen (etwa eingespielt ohne
    Kennwort), dann verbindet der Server, scheitert und verbindet doch. Jeder
    Text steht im Katalog, sonst bliebe er im Englischen deutsch."""
    (cfg_ordner / "loxpanel.cfg").write_text(json.dumps(
        {"miniserver": {"host": "10.0.0.5", "user": "visu", "pass": "x"}}), encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 443})
        stand = "document.getElementById('einrStand').textContent"

        async def schritte(pg):
            texte = await pg.evaluate("""() => [...document.querySelectorAll('#einr [data-i18n]')]
                                         .map(e => e.textContent)""")
            texte.append(await pg.evaluate("document.querySelector('.rub:disabled').title"))
            texte.append(await pg.evaluate(stand))
            app.host = "10.0.0.5"
            await pg.wait_for_function(f"{stand} !== {json.dumps(texte[-1])}")
            texte.append(await pg.evaluate(stand))
            app._ms_fehler = "timeout"
            await pg.wait_for_function(f"{stand}.endsWith('timeout')")
            texte.append(await pg.evaluate(stand))
            async with pg.expect_navigation(timeout=10000):
                app._apply_structure(anlage(BAUSTEINE))
            await pg.wait_for_selector("#einrOk:not([hidden])")
            texte += await pg.evaluate("""() => [...document.querySelectorAll('#einrOk [data-i18n]')]
                                          .map(e => e.textContent)""")
            texte.append(await pg.evaluate("document.getElementById('einrOkText').textContent"))
            return texte
        return await _konfigurator(app, schritte, sprache=sprache)
    assert asyncio.run(lauf()) == TEXTE[sprache]


def test_eingerichtet_ohne_fuehrung(cfg_ordner):
    """Mit Struktur bleibt alles wie gewohnt: Start mit der Uebersicht."""
    async def lauf():
        app = W.App({"host": "10.0.0.5", "port": 443})
        app._apply_structure(anlage(BAUSTEINE))

        async def schritte(pg):
            await pg.wait_for_function(KONFIGURATOR_GELADEN + " && SET !== null")
            return await pg.evaluate(ZUSTAND)
        return await _konfigurator(app, schritte, warten="#overviewHost:visible")
    z = asyncio.run(lauf())
    assert z["rubrik"] == "overview" and z["gesperrt"] == [] and not z["neuesPanel"]
    assert not z["hinweis"] and z["weiter"] is None


def test_zugang_aus_umgebung_im_formular(cfg_ordner, miniserver_http, monkeypatch):
    """Zugang aus LOXPANEL_MS_* mit eigenem Port und Zertifikatspruefung: Das
    Formular zeigt ihn so, wie verbunden wird. Speichern mit leerem
    Kennwortfeld nimmt das Kennwort der Umgebung; ist der Miniserver nicht
    erreichbar, bleibt die Warnung stehen, und in die Datei kommt nichts."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]          # hier lauscht niemand: nicht erreichbar
    umgebung = {"HOST": "127.0.0.1", "USER": "visu", "PASS": "geheim", "PORT": str(port), "VERIFY_TLS": "true"}
    for k, v in umgebung.items():
        monkeypatch.setenv(f"LOXPANEL_MS_{k}", v)

    async def lauf():
        app = W.App(W._config())
        app._apply_structure(anlage(BAUSTEINE))

        async def schritte(pg):
            await pg.wait_for_function(KONFIGURATOR_GELADEN + " && SET !== null")
            await pg.evaluate("setRubric('settings')")
            await pg.locator(".stab", has_text="Miniserver").click()
            formular = await pg.evaluate("""() => ({port: document.getElementById('ms_port').value,
                                                    tls: document.getElementById('ms_tls').checked,
                                                    pass: document.getElementById('ms_pass').placeholder})""")
            await pg.click("#ms_save")
            await pg.wait_for_function("document.getElementById('ms_toast').classList.contains('warn')")
            await pg.wait_for_timeout(4500)       # laenger als eine gewoehnliche Meldung steht
            toast = await pg.evaluate("[...document.getElementById('ms_toast').classList]")
            return formular, toast, await pg.inner_text("#ms_toast")
        return await _konfigurator(app, schritte, warten="#overviewHost:visible"), app._zugang_neu
    (formular, toast, text), neu = asyncio.run(lauf())

    assert formular == {"port": str(port), "tls": True, "pass": "unverändert lassen"}
    assert toast == ["toast", "show", "warn"]
    assert text.startswith("Miniserver nicht erreichbar. Der Zugang ist trotzdem gespeichert, LoxPanel versucht "
                           "es damit weiter. (Cannot connect to host 127.0.0.1:")
    assert not (cfg_ordner / "loxpanel.cfg").exists(), "das Kennwort der Umgebung wird nicht kopiert"
    assert neu == {"host": "127.0.0.1", "user": "visu", "pass": "geheim", "port": port, "verify_tls": True}
