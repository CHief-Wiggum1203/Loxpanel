"""Nur rendern, was betroffen ist (TODO §4): Der Takt (_broadcast_tick) rendert
eine Verbindung nur neu, wenn ihre Seite beim letzten Rendern einen der
geaenderten States gelesen hat, ausserhalb der States etwas anders ist
(_dirty), sie Seite, Profil oder Bereich gewechselt hat oder ihr letztes
Rendern RENDER_SPAETESTENS_S her ist. Dazu: JSON-States werden je Text einmal
geparst, ein unlesbarer einmal gemeldet (JSON-States einmal parsen, §4)."""
import asyncio
import json
import logging

import adapters
from bausteine import helfer
from lox import anlage, lichtsteuerung_baustein, verteilung, W

SCHALTER = {f"S{i}": {"name": f"Schalter {i}", "type": "Switch", "uuidAction": f"S{i}",
                      "room": "r1", "cat": "c1", "states": {"active": f"s{i}"}} for i in (1, 2)}


class Ws:
    def __init__(self):
        self.nachrichten = []

    async def send_json(self, msg):
        self.nachrichten.append(msg)

    def ansichten(self) -> list:
        return [m for m in self.nachrichten if m.get("t") == "view"]


def _app(controls: dict, states: dict) -> tuple[W.App, list]:
    """App mit der Anlage und ihren States; render() zaehlt mit, welche Seite
    es rechnet (Baustein-Id bzw. Ansicht) -> (app, gerendert)."""
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(controls))
    app.states = dict(states)
    gerendert = []
    echt = app.render

    def zaehlen(route, prof=None):
        gerendert.append(route.get("id") or route.get("view"))
        return echt(route, prof)
    app.render = zaehlen
    return app, gerendert


def _verbinden(app: W.App, route: dict) -> Ws:
    ws = Ws()
    app.conn_route[ws] = dict(route)
    return ws


async def _takt(app: W.App, gerendert: list) -> list:
    """Ein Takt des Broadcasters -> die Seiten, die er gerendert hat."""
    gerendert.clear()
    await app._broadcast_tick()
    return sorted(gerendert)


def test_nur_die_seite_mit_dem_geaenderten_state():
    app, gerendert = _app(SCHALTER, {"s1": 0, "s2": 0})

    async def lauf():
        a = _verbinden(app, {"view": "control", "id": "S1"})
        b = _verbinden(app, {"view": "control", "id": "S2"})
        erst = await _takt(app, gerendert)              # noch nie gerendert: beide
        app._on_value("s1", 1)
        nur_a = await _takt(app, gerendert)
        app._on_value("fremd", 5)                        # liest keine der Seiten
        keine = await _takt(app, gerendert)
        leer = await _takt(app, gerendert)               # nichts geaendert
        return a, b, (erst, nur_a, keine, leer)
    a, b, takte = asyncio.run(lauf())
    assert takte == (["S1", "S2"], ["S1"], [], []), takte
    # die betroffene Seite kommt mit dem neuen Stand, die andere nur einmal
    assert len(a.ansichten()) == 2 and a.ansichten()[0] != a.ansichten()[1]
    assert len(b.ansichten()) == 1


def test_aenderung_ausserhalb_der_states_rendert_alle():
    """_dirty (Struktur, Theme, Audioserver, Verlaeufe ...) gilt fuer jede Seite."""
    app, gerendert = _app(SCHALTER, {"s1": 0, "s2": 0})

    async def lauf():
        _verbinden(app, {"view": "control", "id": "S1"})
        _verbinden(app, {"view": "control", "id": "S2"})
        await _takt(app, gerendert)
        app._dirty = True
        return await _takt(app, gerendert), app._dirty
    alle, offen = asyncio.run(lauf())
    assert alle == ["S1", "S2"] and offen is False


def test_seiten_und_profilwechsel_rendern_neu():
    """Was die Verbindung zeigt, gehoert zum Schluessel: eine andere Seite, ein
    anderes Profil (neu geladene Ansicht) oder ein anderer Bereich (Player,
    Energiefluss, Verlauf, Kamera, Statusspalte) rendert, ohne dass sich ein
    State bewegt hat."""
    app, gerendert = _app(SCHALTER, {"s1": 0, "s2": 0})

    async def lauf():
        a = _verbinden(app, {"view": "control", "id": "S1"})
        b = _verbinden(app, {"view": "control", "id": "S2"})
        await _takt(app, gerendert)
        app.conn_route[b] = {"view": "control", "id": "S1"}
        seite = await _takt(app, gerendert)
        app.conn_prof[a] = {"id": "flur"}
        profil = await _takt(app, gerendert)
        app.conn_status[a] = ["S2"]
        bereich = await _takt(app, gerendert)
        # der Bereich liest jetzt mit: s2 betrifft a, nicht mehr b
        app._on_value("s2", 1)
        state = await _takt(app, gerendert)
        return a, (seite, profil, bereich, state)
    a, takte = asyncio.run(lauf())
    assert takte == (["S1"], ["S1"], ["S1"], ["S1"]), takte
    assert [m for m in a.nachrichten if m.get("t") == "svstatus"], a.nachrichten


def test_spaetestens_nach_der_frist():
    """Countdowns, "heute"/"morgen" und das Nachladen der Verlaeufe haengen an
    der Zeit: Nach RENDER_SPAETESTENS_S rendert jede Seite auch ohne Aenderung."""
    app, gerendert = _app(SCHALTER, {"s1": 0, "s2": 0})

    async def lauf():
        _verbinden(app, {"view": "control", "id": "S1"})
        _verbinden(app, {"view": "control", "id": "S2"})
        await _takt(app, gerendert)
        vorher = await _takt(app, gerendert)
        for spur in app._render_spur.values():
            spur["zeit"] -= verteilung.RENDER_SPAETESTENS_S
        return vorher, await _takt(app, gerendert)
    vorher, nachher = asyncio.run(lauf())
    assert vorher == [] and nachher == ["S1", "S2"], (vorher, nachher)


def test_seite_die_alle_states_braucht_rendert_jeden_takt():
    """Liest ein Rendern die States im Ganzen (Durchlaufen, Laenge, items()),
    weiss die Spur nicht, welche es braucht: dann jeden Takt neu."""
    app, gerendert = _app(SCHALTER, {"s1": 0, "s2": 0})
    echt = app.render

    def ganz(route, prof=None):
        len(app.states)
        return echt(route, prof)
    app.render = ganz

    async def lauf():
        _verbinden(app, {"view": "control", "id": "S1"})
        await app._broadcast_tick()
        return [await _takt(app, gerendert) for _ in range(2)]
    assert asyncio.run(lauf()) == [["S1"], ["S1"]]
    assert app._render_spur and all(s["liest"] is None for s in app._render_spur.values())


def test_lesespur():
    quelle = {"a": 1, "b": 2}
    s = verteilung._Lesespur(quelle)
    assert s.get("a") == 1 and s["b"] == 2 and "c" not in s and s.get("d", 7) == 7
    assert s.gelesen == {"a", "b", "c", "d"} and not s.alles
    s["e"] = 3                                     # Schreiben geht in die echten States
    assert quelle["e"] == 3 and "e" not in s.gelesen
    assert sorted(s.items()) == [("a", 1), ("b", 2), ("e", 3)] and s.alles
    for zugriff in (len, list):
        t = verteilung._Lesespur(quelle)
        zugriff(t)
        assert t.alles, zugriff


def test_fehler_beim_rendern_haelt_die_anderen_nicht_auf(caplog):
    """Scheitert eine Seite, rendern die anderen weiter; die gescheiterte wird
    nicht jeden Takt wiederholt (das Log liefe voll), sondern wieder, wenn
    sich etwas aendert, das sie gelesen hat, oder nach der Frist."""
    app, gerendert = _app(SCHALTER, {"s1": 0, "s2": 0})
    echt = app.render

    def kaputt(route, prof=None):
        if route.get("id") == "S1":
            gerendert.append("S1")
            app.states.get("s1")
            raise RuntimeError("Kachel kaputt")
        return echt(route, prof)                       # zaehlt selbst mit
    app.render = kaputt

    async def lauf():
        a = _verbinden(app, {"view": "control", "id": "S1"})
        b = _verbinden(app, {"view": "control", "id": "S2"})
        with caplog.at_level(logging.ERROR, logger="loxpanel.webvisu"):
            erst = await _takt(app, gerendert)
            ruhig = await _takt(app, gerendert)
            app._on_value("s1", 1)
            wieder = await _takt(app, gerendert)
        return a, b, (erst, ruhig, wieder)
    a, b, takte = asyncio.run(lauf())
    assert takte == (["S1", "S2"], [], ["S1"]), takte
    assert not a.ansichten() and len(b.ansichten()) == 1
    assert caplog.text.count("render() fehlgeschlagen") == 2, caplog.text


def test_lichtsteuerung_ueber_den_adapter():
    """Bausteine mit Adapter (LIGHT, JAL) bekommen app.states als Ganzes
    uebergeben; die Spur sieht ihre Zugriffe trotzdem: eine andere Stimmung
    erreicht die offene Seite, der State eines fremden Bausteins nicht."""
    lc, werte = lichtsteuerung_baustein()
    app, gerendert = _app({"LV": lc, **SCHALTER}, {**werte, "s1": 0, "s2": 0})

    async def lauf():
        ws = _verbinden(app, {"view": "control", "id": "LV"})
        await _takt(app, gerendert)
        app._on_value("lv-am", json.dumps([1]))
        stimmung = await _takt(app, gerendert)
        app._on_value("s1", 1)
        fremd = await _takt(app, gerendert)
        return ws, stimmung, fremd
    ws, stimmung, fremd = asyncio.run(lauf())
    assert stimmung == ["LV"] and fremd == [], (stimmung, fremd)
    erst, dann = ws.ansichten()
    assert erst != dann


def test_json_state_einmal_parsen_und_einmal_melden(caplog):
    adapters.json_aus_text.cache_clear()
    helfer._json_fehler_melden.cache_clear()
    app = W.App({"host": "", "port": 80})
    c = {"type": "Alarm", "states": {"liste": "sl"}}
    app.states = {"sl": "%5B1%2C%202%5D"}               # prozentkodiert wie vom Miniserver
    a, b = app._json_state(c, "liste"), app._json_state(c, "liste")
    assert a == [1, 2] and a is b                       # derselbe Text: einmal geparst
    assert adapters.json_aus_text.cache_info().hits >= 1
    app.states["sl"] = "{kaputt"
    with caplog.at_level(logging.WARNING, logger="loxpanel.webvisu"):
        assert app._json_state(c, "liste") is None and app._json_state(c, "liste") is None
    assert caplog.text.count("nicht als JSON parsebar") == 1, caplog.text
    assert "Alarm.liste" in caplog.text
    # _parse_json_state der Adapter: Text bleibt Text, wenn er kein JSON ist
    assert adapters._parse_json_state("[3]") == [3] and adapters._parse_json_state("abc") == "abc"
