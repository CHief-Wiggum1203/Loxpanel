"""Abos der Visu nach einer Neuverbindung, in Chromium.

Energiefluss, Kamera, Player, Werte und Verlauf meldet die Visu dem Server per
set*-Nachricht an (applyPane). Der Server fuehrt diese Abos je WebSocket und
raeumt sie ab, sobald die Verbindung endet: Neustart oder Update des Servers,
Netzabbruch, ein haengendes Panel (_send_or_drop) oder ein im Konfigurator
benanntes Geraet (setdevice). Die Visu verbindet sich dann neu und muss jedes
aktive Abo neu melden, sonst bleibt das Widget auf dem letzten Stand stehen.

Echter ws_handler mit Broadcaster (visu_starten), echte panel.html. Geprueft
wird je Fall: Die Visu schickt auf der neuen Verbindung wieder set*, der Server
fuehrt das Abo fuer die neue Verbindung, und sein Push kommt dort an."""
import asyncio
import json
import time

import pytest

from lox import EM2, W, anlage, intercom_baustein, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import TimeoutError as PwTimeout  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

ZONE = {"name": "Küche", "type": "AudioZoneV2", "uuidAction": "Z", "room": "r1", "cat": "c1",
        "details": {"playerid": 1}, "states": {}}

# Art der Pane -> (Wert in der Konfiguration, Anmeldung der Visu, Merkzettel
# des Servers je Verbindung, Push des Servers)
ABO = {
    "energy": ("energy:M", "setenergy", "conn_energy", "energy"),
    "camera": ("camera:IC", "setcamera", "conn_camera", "camera"),
    "status": ("status:M", "setsvstatus", "conn_status", "svstatus"),
    "player": ("player:Z", "setplayer", "conn_player", "player"),
    "chart": ("chart:M", "setchart", "conn_chart", "chart"),
}

# Obergrenze fuer jedes Warten. Die Visu verbindet nach einer kurzen festen
# Pause neu (connect() in panel.html); gepollt wird, das Warten endet also,
# sobald Verbindung und Abo stehen. Grosszuegig, damit ein langsamer
# CI-Rechner nicht scheitert.
FRIST_S = 10.0
TAKT_S = 0.05


async def _bis(bedingung) -> bool:
    """Pollt `bedingung`, bis sie gilt oder FRIST_S ablaeuft."""
    ende = time.monotonic() + FRIST_S
    while not bedingung():
        if time.monotonic() > ende:
            return False
        await asyncio.sleep(TAKT_S)
    return True


def _app(panes=None, sv_pane=None, tabs=("favoriten",), pick_tabs=None):
    ic, ic_states = intercom_baustein()
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"M": dict(EM2, isFavorite=True), "IC": ic, "Z": ZONE}))
    app.states = {"m-p": 3.2, "m-g": 0.3, "m-s": 2.0, "m-soc": 64, **ic_states}
    ui = {}
    if panes:
        ui["panes"] = panes
    if sv_pane:
        ui["svPane"] = sv_pane
    prof = {"title": "Test", "tabs": list(tabs), "ui": ui}
    if pick_tabs:
        prof["pickTabs"] = pick_tabs
    app.panels = W.App._sanitize_panels({"test": prof})
    return app


async def _fusszeile_nach_wechsel(app, pg) -> str:
    """Erzeugung aendern; zeigt die Energiefluss-Pane den neuen Wert?"""
    app.states["m-p"] = 4.7
    app._dirty = True
    fuss = "document.querySelector('#frontpane .ebot')"
    try:
        await pg.wait_for_function(f"{fuss} && {fuss}.textContent.startsWith('Erzeugung 4,7 kW')",
                                   timeout=FRIST_S * 1000)
    except PwTimeout:
        pass
    return await pg.locator("#frontpane .ebot").text_content()


def _abo_steht(abos, ws, gesendet) -> bool:
    return ws in abos


async def _lauf(app, art, bild, *, vorher=(), bereit=_abo_steht, waehrend=None, ausloeser="server",
                nachher=None) -> dict:
    """Visu laden, `vorher` (JS) ausfuehren und warten, bis `bereit` gilt (Standard:
    der Server fuehrt das Abo fuer die erste Verbindung). Dann endet die
    Verbindung (`ausloeser`): "server" schliesst sie, "geraet" benennt das
    Geraet (setdevice), worauf die Visu selbst schliesst. `waehrend` (JS) laeuft
    in der Trennung. Danach warten, bis die neue Verbindung steht, ihr Abo
    gefuehrt wird und der Push angekommen ist."""
    _, _, merkzettel, push = ABO[art]
    abos = getattr(app, merkzettel)
    runner, port, bc = await visu_starten(app)
    gesendet, empfangen, fehler = [], [], []   # Nachrichten-Typen je Socket der Visu

    def mitschreiben(ws):
        raus, rein = [], []
        gesendet.append(raus)
        empfangen.append(rein)
        ws.on("framesent", lambda p: raus.append(json.loads(p).get("t")))
        ws.on("framereceived", lambda p: rein.append(json.loads(p).get("t")))

    try:
        async with async_playwright() as p:
            b = await p.chromium.launch()
            pg = await b.new_page(viewport={"width": 900, "height": 500})
            pg.on("pageerror", lambda e: fehler.append(str(e)))
            pg.on("websocket", mitschreiben)
            await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
            await pg.wait_for_function("booted")
            for js in vorher:
                await pg.evaluate(js)
            alt = list(app.conn_route)
            assert len(alt) == 1
            assert await _bis(lambda: bereit(abos, alt[0], gesendet[0])), f"{merkzettel}: Stand vor der Trennung"
            vor_trennung = abos.get(alt[0])
            if ausloeser == "geraet":
                await alt[0].send_json({"t": "setdevice", "name": "Flur"})
            else:
                await alt[0].close()
            in_trennung = None
            if waehrend:
                await pg.wait_for_function("ws.readyState === WebSocket.CLOSED")
                in_trennung = await pg.evaluate(
                    f"(() => {{ const zu = ws.readyState !== WebSocket.OPEN; {waehrend}; return zu; }})()")

            def neue():
                return [w for w in app.conn_route if w not in alt]
            await _bis(lambda: neue() and neue()[0] in abos and len(empfangen) > 1 and push in empfangen[1])
            neu = neue()
            abo_neu = abos.get(neu[0]) if neu else None   # vor dem Schliessen: dann raeumt der Server ab
            sichtbar = await nachher(app, pg) if nachher else None
            await pg.screenshot(path=str(bild))
            await b.close()
    finally:
        bc.cancel()
        await runner.cleanup()
    return {"vor_trennung": vor_trennung, "abo_neu": abo_neu,
            "neue": len(neu), "gesendet": gesendet, "empfangen": empfangen, "fehler": fehler,
            "in_trennung": in_trennung, "sichtbar": sichtbar}


def _pruefen(r, art, erwartet):
    _, anmeldung, merkzettel, push = ABO[art]
    assert not r["fehler"], r["fehler"]
    assert r["neue"] == 1 and len(r["gesendet"]) == 2, "Visu hat nicht genau einmal neu verbunden"
    assert anmeldung in r["gesendet"][1], f"Visu meldet {anmeldung} nach der Neuverbindung nicht neu an"
    assert r["abo_neu"] == erwartet, f"Server fuehrt {merkzettel} fuer die neue Verbindung nicht"
    assert push in r["empfangen"][1], f"kein {push}-Push auf der neuen Verbindung"


@pytest.mark.parametrize("lage", ["erster Tab", "zweiter Tab"])
@pytest.mark.parametrize("art", list(ABO))
def test_pane2(tmp_path, art, lage):
    """Zusatzspalte (Pane 2) eines Tabs. Auf dem zweiten Tab liegt sie, wenn das
    erste Tab die Favoriten ohne Pane sind - die haeufige Einrichtung."""
    pane = ABO[art][0]
    if lage == "erster Tab":
        app, vorher = _app(panes={"favoriten": pane}), ["wake()"]
    else:
        app = _app(panes={"zentral": pane}, tabs=("favoriten", "zentral"))
        vorher = ["wake()", "goTab('zentral')"]
    nachher = _fusszeile_nach_wechsel if art == "energy" else None
    r = asyncio.run(_lauf(app, art, tmp_path / f"pane2_{art}.png", vorher=vorher, nachher=nachher))
    _pruefen(r, art, r["vor_trennung"])
    if nachher:
        assert r["sichtbar"].startswith("Erzeugung 4,7 kW"), r["sichtbar"]


@pytest.mark.parametrize("art", ["camera", "status"])
def test_uhr_spalte(tmp_path, art):
    """Rechte Spalte der Uhr-Seite (svPane); die Uhr bleibt die ganze Zeit oben."""
    app = _app(sv_pane=ABO[art][0])
    r = asyncio.run(_lauf(app, art, tmp_path / f"uhr_{art}.png"))
    _pruefen(r, art, r["vor_trennung"])


def test_widget_seite_erster_tab(tmp_path):
    """Freie Seite als Vollbild-Widget (Energiefluss), erstes Tab des Profils."""
    app = _app(pick_tabs=[{"name": "Energie", "picks": [], "widget": "energy:M"}], tabs=("auswahl", "favoriten"))
    r = asyncio.run(_lauf(app, "energy", tmp_path / "widget_seite.png", vorher=["wake()"]))
    _pruefen(r, "energy", r["vor_trennung"])


def test_wechsel_waehrend_trennung(tmp_path):
    """Das Panel geht zur Ruhe, waehrend die Verbindung getrennt ist: Die Uhr
    kommt hoch und mit ihr der Energiefluss als rechte Spalte. Die Anmeldung
    dafuer verwirft send() ohne Verbindung - die Visu muss sie nach dem
    Neuverbinden nachholen. Vor der Trennung bestand kein Energie-Abo."""
    app = _app(sv_pane="energy:M")

    def abgemeldet(abos, ws, gesendet):   # Uhr beim Start angemeldet, nach wake() wieder ab
        return gesendet.count("setenergy") == 2 and ws not in abos
    r = asyncio.run(_lauf(app, "energy", tmp_path / "wechsel_in_trennung.png", vorher=["wake()"],
                          bereit=abgemeldet, waehrend="nachRuhe()"))
    assert r["in_trennung"], "Wechsel lief nicht in der Trennung"
    assert r["vor_trennung"] is None
    _pruefen(r, "energy", "M")


def test_geraet_benannt(tmp_path):
    """Benennen des Geraets im Konfigurator: Der Server schickt setdevice, die
    Visu schliesst selbst und verbindet mit der neuen Kennung neu."""
    app = _app(panes={"favoriten": "energy:M"})
    r = asyncio.run(_lauf(app, "energy", tmp_path / "geraet_benannt.png", vorher=["wake()"],
                          ausloeser="geraet", nachher=_fusszeile_nach_wechsel))
    _pruefen(r, "energy", r["vor_trennung"])
    assert r["sichtbar"].startswith("Erzeugung 4,7 kW"), r["sichtbar"]
