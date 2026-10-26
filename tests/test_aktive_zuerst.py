"""Zentralbausteine und Fenster-/Tuerueberwachung zeigen aktive Mitglieder
zuerst, wie die Loxone-App (im Forum gewuenscht): Licht-Zentral die
Lichtsteuerungen mit aktiver Stimmung, Fenster- und Tor-Zentral die offenen,
Audio-Zentral die spielenden Zonen, die Fenster-/Tuerueberwachung offene und
gekippte Fenster. Sortiert wird beim Aufruf der Seite (Seiten.aufruf_route):
Schaltet man dort, bleibt jede Kachel stehen, bis die Seite neu aufgerufen
wird."""
import asyncio
import json

import aiohttp
import pytest

from bausteine.gemeinsam import _nach_reihe
from lox import anlage, visu_starten, W

STIMMUNGEN = json.dumps([{"id": 778, "name": "Aus"}, {"id": 1, "name": "Hell"}])
AUS, HELL = json.dumps([778]), json.dumps([1])


def _b(uuid, typ, states, **extra):
    return {"name": f"Baustein {uuid}", "type": typ, "uuidAction": uuid, "room": "r1", "cat": "c1",
            "states": states, **extra}


def _zentrale(uuid, typ, mitglieder):
    return _b(uuid, typ, {}, details={"controls": [{"uuid": m} for m in mitglieder]})


# Zentrale -> (Praefix der Mitglieder, State an, State aus); je Zentrale vier
# Mitglieder, das zweite und vierte sind an
ZENTRALEN = {"CL": ("L", HELL, AUS), "CW": ("W", 1.0, 0.0), "CG": ("G", 1.0, 0.0), "CA": ("A", 2, 0)}
MITGLIED_TYP = {"L": "LightControllerV2", "W": "Window", "G": "Gate", "A": "AudioZoneV2"}
ZENTRAL_TYP = {"CL": "CentralLightController", "CW": "CentralWindow", "CG": "CentralGate",
               "CA": "CentralAudioZone"}
STATE = {"L": "activeMoods", "W": "position", "G": "position", "A": "playState"}

BAUSTEINE = {
    **{z: _zentrale(z, ZENTRAL_TYP[z], [f"{p}{i}" for i in range(1, 5)]) for z, (p, _, _) in ZENTRALEN.items()},
    **{f"{p}{i}": _b(f"{p}{i}", MITGLIED_TYP[p], {STATE[p]: f"{p.lower()}{i}",
                                                  **({"moodList": f"lm{i}"} if p == "L" else {})})
       for p in MITGLIED_TYP for i in range(1, 5)},
    # Alarm-Zentrale: kennt kein "an", bleibt in der Folge der Struktur
    "CX": _zentrale("CX", "CentralAlarm", ["L1", "L2", "L3", "L4"]),
    "WM": _b("WM", "WindowMonitor", {"windowStates": "wm"},
             details={"windows": [{"name": n} for n in ("Küche", "Bad", "Büro", "Flur")]}),
}


def _app() -> W.App:
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {f"lm{i}": STIMMUNGEN for i in range(1, 5)}
    for p, an, aus in ZENTRALEN.values():
        app.states.update({f"{p.lower()}{i}": an if i % 2 == 0 else aus for i in range(1, 5)})
    app.states["wm"] = "1,2,1,4"   # Kueche zu, Bad gekippt, Buero zu, Flur offen
    return app


def _folge(view: dict) -> list:
    return [it["id"] for it in view["items"]]


def _namen(view: dict) -> list:
    return [it["label"] for it in view["items"]]


@pytest.mark.parametrize("zentrale", list(ZENTRALEN))
def test_zentrale_zeigt_aktive_zuerst(zentrale):
    """Aktive zuerst, untereinander und danach wie in der Struktur; die Kachel
    zaehlt dieselben (_zentral_mitglied_an)."""
    p = ZENTRALEN[zentrale][0]
    app = _app()
    assert _folge(app.render({"view": "group", "kind": "central", "id": zentrale})) == \
        [f"{p}2", f"{p}4", f"{p}1", f"{p}3"]
    assert app._zentral_an(app.controls[zentrale]) == 2


def test_zentrale_ohne_an_bleibt_in_strukturfolge():
    assert _folge(_app().render({"view": "group", "kind": "central", "id": "CX"})) == ["L1", "L2", "L3", "L4"]


def test_fenster_offen_und_gekippt_zuerst():
    v = _app().render({"view": "control", "id": "WM"})
    assert [(it["label"], it["sublabel"], it["on"]) for it in v["items"]] == [
        ("Bad", "gekippt", True), ("Flur", "offen", True),
        ("Küche", "geschlossen", False), ("Büro", "geschlossen", False)]


def test_zentrale_bleibt_stehen_bis_zum_neuen_aufruf():
    """Schaltet man auf der Seite, bleibt jede Kachel an ihrem Platz (die Visu
    muss das Raster nicht neu aufbauen), die Kacheln zeigen den neuen Stand.
    Erst ein neuer Aufruf sortiert neu. Die Visu sieht die gemerkte
    Reihenfolge nie."""
    app = _app()
    route = app.aufruf_route({"view": "group", "kind": "central", "id": "CL"})
    erst = app.render(route)
    app.states.update(l2=AUS, l3=HELL)       # das erste aktive Licht aus, ein anderes an
    dann = app.render(route)
    assert _folge(erst) == _folge(dann) == ["L2", "L4", "L1", "L3"]
    assert [it["on"] for it in dann["items"]] == [False, True, False, True]
    neu = app.render(app.aufruf_route({"view": "group", "kind": "central", "id": "CL"}))
    assert _folge(neu) == ["L3", "L4", "L1", "L2"]
    assert [v["route"] for v in (erst, dann, neu)] == [{"view": "group", "kind": "central", "id": "CL"}] * 3


def test_fenster_bleiben_stehen_bis_zum_neuen_aufruf():
    app = _app()
    route = app.aufruf_route({"view": "control", "id": "WM"})
    erst = app.render(route)
    app.states["wm"] = "1,1,4,4"            # Bad zu, Buero auf
    dann = app.render(route)
    assert _namen(erst) == _namen(dann) == ["Bad", "Flur", "Küche", "Büro"]
    assert [it["sublabel"] for it in dann["items"]] == ["geschlossen", "offen", "geschlossen", "offen"]
    assert _namen(app.render(app.aufruf_route({"view": "control", "id": "WM"}))) == ["Büro", "Flur", "Küche", "Bad"]
    assert "reihe" not in dann["route"]


def test_reihe_vom_client_gilt_nicht():
    """Die Reihenfolge rechnet immer der Server; was die Visu mitschickt, faellt
    weg. Andere Seiten bleiben, wie sie kommen, auch mit kaputter Id."""
    app = _app()
    r = app.aufruf_route({"view": "group", "kind": "central", "id": "CL", "reihe": ["L3", "L1"]})
    assert r == {"view": "group", "kind": "central", "id": "CL", "reihe": ["L2", "L4", "L1", "L3"]}
    assert app.aufruf_route({"view": "tab", "tab": "zentral", "reihe": [1]}) == {"view": "tab", "tab": "zentral"}
    assert app.aufruf_route({"view": "control", "id": ["kaputt"]}) == {"view": "control", "id": ["kaputt"]}
    assert app.aufruf_route({"view": "control", "id": "L1"}) == {"view": "control", "id": "L1"}


def test_nach_reihe():
    """Gemerkte Reihenfolge; was sie nicht kennt (seitdem dazugekommen), steht
    hinten in der bisherigen Folge."""
    assert _nach_reihe(["a", "b", "c", "d"], ["c", "a"]) == ["c", "a", "b", "d"]
    assert _nach_reihe(["a", "b"], None) == ["a", "b"]
    assert _nach_reihe(["a"], ["x", "a", "a"]) == ["a"]


def test_ueber_den_websocket():
    """Wie im Betrieb: Die Visu ruft die Seite auf (nav), danach geht ein Licht
    aus. Der Broadcaster schickt die Seite mit dem neuen Stand in derselben
    Reihenfolge, die gemerkte Reihenfolge bleibt beim Server."""
    async def ansicht(ws, id_):
        while True:
            m = await asyncio.wait_for(ws.receive_json(), 5)
            if m.get("t") == "view" and (m.get("route") or {}).get("id") == id_:
                return m

    async def lauf():
        app = _app()
        runner, port, broadcaster = await visu_starten(app)
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://127.0.0.1:{port}/ws?panel=default") as ws:
                    await ws.send_json({"t": "nav", "route": {"view": "group", "kind": "central", "id": "CL"}})
                    erst = await ansicht(ws, "CL")
                    app._on_value("l2", AUS)
                    dann = await ansicht(ws, "CL")
        finally:
            broadcaster.cancel()
            await runner.cleanup()
        return erst, dann
    erst, dann = asyncio.run(lauf())
    assert _folge(erst) == _folge(dann) == ["L2", "L4", "L1", "L3"]
    assert [it["on"] for it in erst["items"]] == [True, True, False, False]
    assert [it["on"] for it in dann["items"]] == [False, True, False, False]
    assert "reihe" not in erst["route"] and "reihe" not in dann["route"]


class Ws:
    def __init__(self):
        self.nachrichten = []

    async def send_json(self, msg):
        self.nachrichten.append(msg)

    def ansichten(self) -> list:
        return [m for m in self.nachrichten if m.get("t") == "view"]


def test_neustart_traegt_reihe_nach():
    """Nach einem Neustart des Servers ruft die Visu ihre Seite auf, bevor
    Struktur und States da sind. Gemerkt wird erst, wenn die States der
    Mitglieder bekannt sind (sonst stuende nur die Folge der Struktur fest);
    der Broadcaster traegt die Reihenfolge dann nach, und sie bleibt stehen."""
    dump = _app().states
    app = W.App({"host": "", "port": 80})
    ws = Ws()
    app.conn_route[ws] = app.aufruf_route({"view": "group", "kind": "central", "id": "CL"})

    async def lauf():
        ohne_struktur = dict(app.conn_route[ws])
        app._apply_structure(anlage(BAUSTEINE))           # Struktur da, die States noch nicht
        app._dirty = True
        await app._broadcast_tick()
        ohne_states = dict(app.conn_route[ws])
        for k, v in dump.items():                          # der Miniserver schickt alle Werte
            app._on_value(k, v)
        await app._broadcast_tick()
        gemerkt = app.conn_route[ws].get("reihe")
        app._on_value("l2", AUS)                           # auf der Seite geschaltet
        app._on_value("l3", HELL)
        await app._broadcast_tick()
        return ohne_struktur, ohne_states, gemerkt, ws.ansichten()[-1]
    ohne_struktur, ohne_states, gemerkt, zuletzt = asyncio.run(lauf())
    assert "reihe" not in ohne_struktur and "reihe" not in ohne_states
    assert gemerkt == ["L2", "L4", "L1", "L3"]
    assert _folge(zuletzt) == ["L2", "L4", "L1", "L3"]
    assert [it["on"] for it in zuletzt["items"]] == [False, True, False, True]
    assert "reihe" not in zuletzt["route"]


def test_neustart_wartet_auf_alle_werte():
    """Die Startwerte kommen in mehreren Tabellen. Tickt der Broadcaster, wenn
    erst das geschlossene W1 und W3 gemeldet sind, darf er nichts merken:
    Sonst stuende das offene W2 fest hinter W1."""
    dump = _app().states
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    ws = Ws()
    app.conn_route[ws] = app.aufruf_route({"view": "group", "kind": "central", "id": "CW"})

    async def lauf():
        app._on_value("w1", dump["w1"])                  # erste Tabelle: W1 und W3 zu
        app._on_value("w3", dump["w3"])
        await app._broadcast_tick()
        halb = dict(app.conn_route[ws])
        app._on_value("w2", dump["w2"])                  # zweite Tabelle: W2 und W4 offen
        app._on_value("w4", dump["w4"])
        await app._broadcast_tick()
        return halb, app.conn_route[ws].get("reihe"), ws.ansichten()[-1]
    halb, gemerkt, zuletzt = asyncio.run(lauf())
    assert "reihe" not in halb
    assert gemerkt == ["W2", "W4", "W1", "W3"]
    assert _folge(zuletzt) == ["W2", "W4", "W1", "W3"]


def test_mitglied_ohne_state_haelt_nicht_auf():
    """Ein Mitglied, dessen Struktur den State nicht kennt (hier eine
    Lichtsteuerung ohne activeMoods), meldet nie einen Wert; gemerkt wird
    trotzdem, sobald die uebrigen ihn haben."""
    bausteine = {**BAUSTEINE, "CM": _zentrale("CM", "CentralLightController", ["L1", "LX", "L2"]),
                 "LX": _b("LX", "LightControllerV2", {})}
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(bausteine))
    app.states = {"lm1": STIMMUNGEN, "lm2": STIMMUNGEN, "l1": AUS}
    assert "reihe" not in app.aufruf_route({"view": "group", "kind": "central", "id": "CM"})
    app.states["l2"] = HELL
    assert app.aufruf_route({"view": "group", "kind": "central", "id": "CM"})["reihe"] == ["L2", "L1", "LX"]


def test_fenster_warten_auf_ihre_states():
    app = _app()
    app.states.pop("wm")
    assert "reihe" not in app.aufruf_route({"view": "control", "id": "WM"})


def test_aufruf_route_wirft_nie(monkeypatch, caplog):
    """Scheitert das Ordnen (kaputte Struktur), bleibt die Route ohne reihe -
    auch ohne die des Clients - und die Seite ordnet beim Rendern selbst."""
    app = _app()

    def kaputt(c):
        raise ValueError("kaputt")
    monkeypatch.setattr(app, "_zentral_reihe", kaputt)
    r = app.aufruf_route({"view": "group", "kind": "central", "id": "CL", "reihe": [{"x": 1}]})
    assert r == {"view": "group", "kind": "central", "id": "CL"}
    assert "aufruf_route fehlgeschlagen" in caplog.text


def test_offen_wie_auf_der_kachel():
    """Ein Fenster bei 0,4 % zeigt auf seiner Kachel "Geschlossen": es zaehlt
    nicht als offen und steht nicht vorn."""
    app = _app()
    app.states["w1"] = 0.004
    assert app._control_item("W1")["sublabel"] == "Geschlossen"
    assert app._zentral_an(app.controls["CW"]) == 2
    assert _folge(app.render({"view": "group", "kind": "central", "id": "CW"})) == ["W2", "W4", "W1", "W3"]
    app.states["w1"] = 0.006                               # gerundet 1 %: offen
    assert _folge(app.render({"view": "group", "kind": "central", "id": "CW"})) == ["W1", "W2", "W4", "W3"]
