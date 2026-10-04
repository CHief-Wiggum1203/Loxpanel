"""Gesicherte Bausteine (isSecured), Server-Seite und Befehlsweg der Visu.

- Jede Seite eines gesicherten Bausteins traegt secured, auch die Unterseiten
  (Musikauswahl, Zone, Weckzeit, Wecker-Einstellungen, Klingeln); Gruppe und
  Tab nicht, dort zaehlt die Kachel.
- Player- und Kamera-Bereich bekommen secured mit ihren Bloecken.
- cmdresult nennt Befehl und Code, damit die Visu Druecken und Loslassen
  auseinanderhaelt und "keine Antwort" nicht als falsche PIN meldet.
- PIN merken (ui.pinMerken) ist eine Panel-Option mit Standard.
- In panel.html gibt es genau einen Weg, auf dem ein Befehl die Visu verlaesst.
"""
import asyncio
import re

import aiohttp
import pytest

from lox import ROOT, Miniserver, W, anlage, bewaesserung_baustein, intercom_baustein, neue_app, \
    visu_starten, wecker_baustein

PIN = "4711"
ZONE = {"name": "Küche Musik", "type": "AudioZone", "uuidAction": "ZA", "room": "r1", "cat": "c1",
        "states": {"playState": "za-ps", "volume": "za-v"}}
DIMMER = {"name": "Flur Dimmer", "type": "Dimmer", "uuidAction": "DIM", "room": "r1", "cat": "c1",
          "states": {"position": "dim-p"}}


def _anlage(gesichert: bool) -> tuple[dict, dict]:
    controls, states = {"ZA": dict(ZONE), "DIM": dict(DIMMER)}, {"za-ps": 0, "za-v": 30, "dim-p": 40}
    for c, st in (bewaesserung_baustein(), wecker_baustein(), intercom_baustein()):
        controls[c["uuidAction"]] = c
        states.update(st)
    for c in controls.values():
        c["isFavorite"] = True
        if gesichert:
            c["isSecured"] = True
    return controls, states


def _app(gesichert=True, ui=None, ms=None):
    app = neue_app(ms) if ms else W.App({"host": "", "port": 80})
    controls, states = _anlage(gesichert)
    app._apply_structure(anlage(controls))
    app.states = states
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"], "ui": ui or {}}})
    return app


ROUTEN = [{"view": "control", "id": "DIM"}, {"view": "control", "id": "IC"},
          {"view": "sources", "id": "ZA"}, {"view": "irrzone", "id": "BEW", "zone": 0},
          {"view": "alarmentry", "id": "WK", "entry": "1"}, {"view": "alarmentry", "id": "WK", "entry": ""},
          {"view": "alarmsettings", "id": "WK"}, {"view": "bells", "id": "IC"}]


@pytest.mark.parametrize("route", ROUTEN, ids=lambda r: "-".join(str(v) for v in r.values()))
def test_jede_seite_eines_gesicherten_bausteins_traegt_secured(route):
    assert _app(gesichert=True).render(route).get("secured") is True
    assert "secured" not in _app(gesichert=False).render(route)


def test_gruppe_und_tab_ohne_secured():
    """Auf der Gruppenseite eines gesicherten Zentralbausteins fragen nur die
    gesicherten Mitglieder (Kachel-Klick nimmt view.secured ODER die Kachel)."""
    app = _app(gesichert=False)
    app.controls["ZEN"] = {"name": "Licht Zentral", "type": "CentralLightController", "uuidAction": "ZEN",
                           "isSecured": True, "details": {"controls": [{"uuid": "DIM"}]}}
    gruppe = app.render({"view": "group", "kind": "central", "id": "ZEN"})
    assert "secured" not in gruppe and [i.get("secured") for i in gruppe["items"]] == [None]
    assert "secured" not in app.render({"view": "tab", "tab": "favoriten"})
    assert "secured" not in app.render({"view": "control", "id": "unbekannt"})


async def _ws(app, schritt):
    runner, port, bc = await visu_starten(app)
    try:
        async with aiohttp.ClientSession() as s, s.ws_connect(f"http://127.0.0.1:{port}/ws?panel=test") as ws:
            return await schritt(ws)
    finally:
        bc.cancel()
        await runner.cleanup()


async def _bis(ws, art: str, sekunden=3.0) -> dict:
    while True:
        m = await asyncio.wait_for(ws.receive_json(), sekunden)
        if m.get("t") == art:
            return m


@pytest.mark.parametrize("gesichert", [True, False])
def test_player_und_kamera_bereich_tragen_secured(gesichert):
    """Beim Anmelden (setplayer/setcamera) und bei jedem Tick danach."""
    app = _app(gesichert)

    async def schritt(ws):
        await ws.send_json({"t": "setplayer", "zone": "ZA"})
        anmelden = await _bis(ws, "player")
        app.states["za-v"] = 35
        app._dirty = True
        tick = await _bis(ws, "player")
        await ws.send_json({"t": "setcamera", "uuid": "IC"})
        kamera = await _bis(ws, "camera")
        app.states["ic-bell"] = 1
        app._dirty = True
        kamera_tick = await _bis(ws, "camera")
        return anmelden, tick, kamera, kamera_tick
    meldungen = asyncio.run(_ws(app, schritt))
    assert meldungen[1]["blocks"] != meldungen[0]["blocks"] and meldungen[3]["blocks"] != meldungen[2]["blocks"]
    assert [m.get("secured") for m in meldungen] == [True if gesichert else None] * 4


def test_cmdresult_nennt_befehl_und_code(miniserver_http):
    """Richtige PIN: sps/ios mit dem Hash nach der Loxone-Doku, angenommen.
    Falsche PIN: abgelehnt mit dem Code des Miniservers. Ohne PIN: der
    Miniserver lehnt ab, die Visu bekommt den ueblichen Hinweis."""
    async def lauf():
        ms = Miniserver()
        ms.visu_pin = PIN
        await ms.start()
        app = _app(ms=ms)
        ms.gesichert_io = set(app.controls)
        try:
            async def schritt(ws):
                antworten = []
                for pin in (PIN, "0000"):
                    await ws.send_json({"t": "cmd", "uuid": "DIM", "cmd": "on", "pin": pin})
                    antworten.append(await _bis(ws, "cmdresult"))
                await ws.send_json({"t": "cmd", "uuid": "DIM", "cmd": "off"})
                antworten.append(await _bis(ws, "notify"))
                return antworten
            return await _ws(app, schritt), ms
        finally:
            await app.icon_session.close()
            await ms.stop()
    (richtig, falsch, ohne), ms = asyncio.run(lauf())
    assert richtig == {"t": "cmdresult", "ok": True, "code": "200", "uuid": "DIM", "cmd": "on"}
    assert falsch == {"t": "cmdresult", "ok": False, "code": "403", "uuid": "DIM", "cmd": "on"}
    assert "403" in ohne["text"]
    assert ms.ios == [("DIM/on", "200"), ("DIM/on", "403")]
    assert ms.io == ["sps/io/DIM/off"]


# ---- PIN merken: Panel-Option ui.pinMerken (Sekunden, 0 = jedes Mal fragen)

@pytest.mark.parametrize("wert, gespeichert", [
    (60, 60), (0, 0), (-5, 0), (10 ** 6, "max"), (2.7, 2),
    ("std", None),                       # Standard: nicht gespeichert, kein Verlust
])
def test_pin_merken_speichern(wert, gespeichert):
    roh = {"p": {"title": "P", "ui": {"pinMerken": W.PIN_MERKEN_STANDARD if wert == "std" else wert}}}
    sauber = W.App._sanitize_panels(roh)
    soll = W.PIN_MERKEN_MAX if gespeichert == "max" else gespeichert
    assert (sauber["p"].get("ui") or {}).get("pinMerken") == soll
    assert W.App._panels_verworfen(roh, sauber) == []


@pytest.mark.parametrize("wert", ["30", True])
def test_pin_merken_ungueltig_wird_gemeldet(wert):
    roh = {"p": {"title": "P", "ui": {"pinMerken": wert}}}
    sauber = W.App._sanitize_panels(roh)
    assert "pinMerken" not in (sauber["p"].get("ui") or {})
    assert W.App._panels_verworfen(roh, sauber) == ["P: ui.pinMerken"]


def test_pin_merken_standard_ist_begruendet_klein():
    """Der Standard reicht fuer eine Bedienung und laesst das Panel nicht
    offen stehen: kuerzer als die Ruhe, nach der die Visu zur Uhr-Seite geht."""
    src = (ROOT / "webfrontend/html/panel.html").read_text(encoding="utf-8")
    ruhe_ms = int(re.search(r"const SAVER_IDLE_MS\s*=\s*(\d+)", src).group(1))
    assert 0 < W.PIN_MERKEN_STANDARD <= W.PIN_MERKEN_MAX
    assert W.PIN_MERKEN_STANDARD * 1000 < ruhe_ms


@pytest.mark.parametrize("ui, sekunden", [({}, "std"), ({"pinMerken": 0}, 0), ({"pinMerken": 90}, 90)])
def test_pin_merken_kommt_mit_dem_theme(ui, sekunden):
    app = _app(ui=ui)
    soll = W.PIN_MERKEN_STANDARD if sekunden == "std" else sekunden
    assert app.resolve_profile("test")["pinMerken"] == soll
    assert asyncio.run(_ws(app, lambda ws: _bis(ws, "theme")))["pinMerken"] == soll


def test_pin_merken_im_konfigurator():
    """/api/meta nennt Standard und Grenze, das Feld liest sie dort ab;
    _panel_export gibt den gespeicherten Wert zurueck."""
    app = _app(ui={"pinMerken": 90})

    async def meta():
        runner, port, bc = await visu_starten(app)
        try:
            async with aiohttp.ClientSession() as s, s.get(f"http://127.0.0.1:{port}/api/meta") as r:
                return await r.json()
        finally:
            bc.cancel()
            await runner.cleanup()
    m = asyncio.run(meta())
    assert m["pinMerken"] == {"standard": W.PIN_MERKEN_STANDARD, "max": W.PIN_MERKEN_MAX}
    assert m["panels"]["test"]["ui"]["pinMerken"] == 90
    html = (ROOT / "webfrontend/html/config.html").read_text(encoding="utf-8")
    assert 'data-ui="pinMerken"' in html


# ---- Ein Befehlsweg in der Visu

def _funktion_an(src: str, pos: int) -> str:
    """Name der Funktion, in der die Stelle pos steht (letzte Deklaration davor)."""
    namen = re.findall(r"function\s+(\w+)\s*\(", src[:pos])
    return namen[-1] if namen else ""


def test_ein_befehlsweg_in_der_visu():
    """{t:'cmd'} baut nur cmdSchicken(), und die rufen nur sendCmd(), der
    PIN-Weg und das Loslassen einer Halten-Taste. Jeder andere Bedienweg muss
    ueber sendCmd() mit der richtigen secured-Angabe gehen - sonst umgeht er
    die PIN-Abfrage (Regler, -/+, Player, Favoriten hatten eigene Wege)."""
    src = (ROOT / "webfrontend/html/panel.html").read_text(encoding="utf-8")
    src = re.sub(r"(?m)^\s*//.*$", "", src)      # Kommentarzeilen zaehlen nicht
    bauen = [_funktion_an(src, m.start()) for m in re.finditer(r"""t\s*:\s*['"]cmd['"]""", src)]
    assert bauen == ["cmdSchicken"], bauen
    rufer = {_funktion_an(src, m.start()) for m in re.finditer(r"(?<!function )\bcmdSchicken\s*\(", src)}
    assert rufer == {"sendCmd", "pinSenden", "endHold"}, rufer
    # Der Kamera-Bereich fragte mit fest eingetragenem false nie nach der PIN
    assert not re.search(r"sendCmd\([^;]*,\s*false\s*\)", src)
