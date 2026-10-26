"""Strompreis-Optimierer (SpotPriceOptimizer, Strukturdoku 16.0): Kachel und
Detailseite mit Preis, Ausgang, laufendem Zyklus und der Prognose, die der
Miniserver auf getForecasts liefert ([{u, v, s, e, planned}], Start und Ende in
Unix-UTC). Neu geholt wird sie, sobald sich forecastsTimestamp aendert.
start/{Bedarf}/{Zeitraum} startet einen Zyklus (Bedarf von der Logik: 0),
cancel bricht ihn ab; Bedarf, Zeitraum und Mindestlaufzeit in Stunden
(Loxone-Wissensdatenbank). Die Prognose kommt aus dem Miniserver-Nachbau."""
import asyncio
import calendar
import json
import time
from datetime import date, datetime

from bausteine.gemeinsam import LOX_EPOCH_UTC
from lox import Miniserver, W, anlage, bloecke, neue_app
from statistik import _prognose_lesen

FORMAT = "%.3f€/kWh"
STATES = ("active", "current", "demand", "period", "minRuntime", "manualMax", "forecastsTimestamp",
          "cycleFrom", "cycleUntil")
STUNDE = int(time.time()) // 3600 * 3600
# sechs Stunden ab der laufenden, die dritte und vierte eingeplant (die billigsten)
PREISE = (0.301, 0.252, 0.121, 0.104, 0.283, 0.312)
PROGNOSE = [{"u": f"p{i}", "v": v, "s": STUNDE + i * 3600, "e": STUNDE + (i + 1) * 3600,
             **({"planned": True} if i in (2, 3) else {})} for i, v in enumerate(PREISE)]
GET_FORECASTS = "sps/io/SPO/getForecasts"


def _baustein(details=None, **werte) -> tuple[dict, dict]:
    control = {"name": "Boiler", "type": "SpotPriceOptimizer", "uuidAction": "SPO", "room": "r1", "cat": "c1",
               "details": {"format": FORMAT, "demandByLogic": False, "periodByLogic": False,
                           "minRuntimeByLogic": False, "hasAutomation": True, **(details or {})},
               "states": {n: f"sp-{n}" for n in STATES}}
    w = {"active": 0, "current": 0.2451, "demand": 4, "period": 24, "minRuntime": 1, "manualMax": 0.5,
         "forecastsTimestamp": 1000, "cycleFrom": 0, "cycleUntil": 0, **werte}
    return control, {f"sp-{n}": w[n] for n in STATES}


def _app(app=None, details=None, **werte) -> W.App:
    app = app or W.App({"host": "", "port": 80})
    control, states = _baustein(details, **werte)
    app._apply_structure(anlage({"SPO": control}))
    app.states = states
    return app


def _mit_prognose(app: W.App, eintraege=PROGNOSE) -> W.App:
    """Prognose wie nach einem Abruf zum aktuellen forecastsTimestamp."""
    app.prognose_cache["SPO"] = (app.states["sp-forecastsTimestamp"], time.monotonic(), _prognose_lesen(eintraege))
    return app


def _seite(app: W.App) -> dict:
    return app.render({"view": "control", "id": "SPO"})


def _texte(v: dict, art: str) -> list:
    return [b["text"] for b in bloecke(v, art)]


def _zeit(t: int) -> str:
    """Zeitpunkt wie auf der Seite: heute die Uhrzeit, morgen mit "morgen"."""
    d = datetime.fromtimestamp(t)
    tage = (d.date() - date.today()).days
    return d.strftime("%H:%M") if tage == 0 else ("morgen " if tage == 1 else d.strftime("%d.%m. ")) + d.strftime("%H:%M")


def _uhr(t: int) -> int:
    return calendar.timegm(time.localtime(t))


def test_kachel():
    assert _app()._control_item("SPO")["sublabel"] == "0,245 €/kWh"
    an = _app(active=1)._control_item("SPO")
    assert an["sublabel"] == "Ein · 0,245 €/kWh" and an["on"] is True
    assert _app(current=None)._control_item("SPO")["sublabel"] == "Aus"


def test_status_voll():
    typen = {t["type"]: t["status"] for t in _app().types_overview()["types"]}
    assert typen["SpotPriceOptimizer"] == "full"


def test_detailseite():
    v = _seite(_mit_prognose(_app()))
    assert _texte(v, "big") == ["0,245 €/kWh"]
    assert _texte(v, "status")[:2] == [
        "Ausgang aus",
        f"Nächster Einsatz {_zeit(STUNDE + 2 * 3600)} bis " + (
            datetime.fromtimestamp(STUNDE + 4 * 3600).strftime("%H:%M")
            if datetime.fromtimestamp(STUNDE + 4 * 3600).date() == datetime.fromtimestamp(STUNDE + 2 * 3600).date()
            else _zeit(STUNDE + 4 * 3600))]
    preis, geplant = bloecke(v, "chart")
    assert (preis["kind"], preis["unit"], preis["state"], preis["t0"], preis["t1"]) == (
        "analog", "€/kWh", "ok", _uhr(STUNDE), _uhr(STUNDE + 6 * 3600))
    assert preis["series"][0]["name"] == "Preis" and preis["series"][0]["dec"] == 3
    assert preis["series"][0]["pts"][:4] == [[_uhr(STUNDE), 0.301], [_uhr(STUNDE + 3600), 0.301],
                                             [_uhr(STUNDE + 3600), 0.252], [_uhr(STUNDE + 7200), 0.252]]
    assert geplant["kind"] == "digital" and geplant["series"][0]["name"] == "Eingeplant"
    assert [p[1] for p in geplant["series"][0]["pts"]] == [0, 0, 1, 1, 0, 0]
    # Zyklus: Bedarf und Zeitraum fuellen die Vorlage, die Mindestlaufzeit steht nur da
    stufen = {b["label"]: b for b in bloecke(v, "stepper")}
    assert stufen["Bedarf"] == {"k": "stepper", "label": "Bedarf", "value": 4, "unit": "h", "name": "bedarf",
                                "step": 0.25, "min": 0}
    assert stufen["Zeitraum"] == {"k": "stepper", "label": "Zeitraum", "value": 24, "unit": "h",
                                  "name": "zeitraum", "step": 1, "min": 1}
    assert stufen["Mindestlaufzeit"] == {"k": "stepper", "label": "Mindestlaufzeit", "value": 1, "unit": "h"}
    zeile, = bloecke(v, "row")
    assert zeile["cells"] == [{"label": "Zyklus starten", "form": {"uuid": "SPO", "tmpl": "start/{bedarf}/{zeitraum}"}}]


def test_zyklus_laeuft():
    """cycleUntil zaehlt Sekunden seit 2009 in UTC; laeuft der Zyklus, steht bis
    wann, und er laesst sich abbrechen (mit Rueckfrage). Laeuft der eingeplante
    Einsatz schon, heisst es "Eingeplant bis"."""
    bis = STUNDE + 4 * 3600
    app = _app(active=1, cycleFrom=STUNDE - LOX_EPOCH_UTC, cycleUntil=bis - LOX_EPOCH_UTC)
    eintraege = [dict(e, planned=True) if i == 0 else e for i, e in enumerate(PROGNOSE)]
    v = _seite(_mit_prognose(app, eintraege))
    assert bloecke(v, "big")[0]["tone"] == "good"
    assert _texte(v, "status")[:3] == ["Ausgang ein", f"Zyklus läuft bis {_zeit(bis)}",
                                       f"Eingeplant bis {_zeit(STUNDE + 3600)}"]
    assert bloecke(v, "row")[0]["cells"][1] == {"label": "Zyklus abbrechen", "confirm": "Zyklus wirklich abbrechen?",
                                                "cmd": {"uuid": "SPO", "cmd": "cancel"}}
    vorbei = _seite(_mit_prognose(_app(cycleUntil=STUNDE - 3600 - LOX_EPOCH_UTC)))
    assert not any(t.startswith("Zyklus läuft") for t in _texte(vorbei, "status"))
    assert [c["label"] for c in bloecke(vorbei, "row")[0]["cells"]] == ["Zyklus starten"]


def test_von_der_logik_vorgegeben():
    """Gibt die Logik den Bedarf vor, steht dort laut Strukturdoku 0; ein
    vorgegebener Zeitraum geht mit seinem Wert mit. Beide sind dann fest."""
    v = _seite(_mit_prognose(_app(details={"demandByLogic": True, "periodByLogic": True,
                                           "minRuntimeByLogic": True}, period=12.5)))
    stufen = {b["label"]: b for b in bloecke(v, "stepper")}
    assert all(b.get("sub") == "von der Logik vorgegeben" and "name" not in b for b in stufen.values()), stufen
    assert bloecke(v, "row")[0]["cells"][0]["form"]["tmpl"] == "start/0/12.5"
    nur_bedarf = _seite(_mit_prognose(_app(details={"demandByLogic": True})))
    assert bloecke(nur_bedarf, "row")[0]["cells"][0]["form"]["tmpl"] == "start/0/{zeitraum}"


def test_ohne_werte_kein_start():
    """Fehlt Bedarf oder Zeitraum (State fehlt), gibt es nichts zu starten."""
    v = _seite(_mit_prognose(_app(demand=None)))
    assert "Bedarf" not in {b["label"] for b in bloecke(v, "stepper")}
    assert not bloecke(v, "row")


def test_prognose_lesen():
    assert _prognose_lesen(json.dumps(PROGNOSE[:2])) == [
        (STUNDE, STUNDE + 3600, 0.301, False), (STUNDE + 3600, STUNDE + 7200, 0.252, False)]
    assert _prognose_lesen([PROGNOSE[3], PROGNOSE[2]]) == [
        (STUNDE + 7200, STUNDE + 10800, 0.121, True), (STUNDE + 10800, STUNDE + 14400, 0.104, True)]
    kaputt = [{"v": "x", "s": 1, "e": 2}, {"v": 1, "s": 5, "e": 5}, {"v": float("nan"), "s": 1, "e": 2},
              {"s": 1, "e": 2}, "text", {"v": 0.2, "s": 1, "e": 2, "planned": "ja"}]
    assert _prognose_lesen(kaputt) == [(1, 2, 0.2, False)]
    assert _prognose_lesen("{kaputt") is None and _prognose_lesen({"v": 1}) is None


async def _hintergrund(app: W.App) -> None:
    await asyncio.gather(*list(app.bg_tasks))


def test_prognose_vom_miniserver(miniserver_http):
    """Die erste Seite sagt, dass die Prognose laedt, und holt sie im
    Hintergrund; danach stehen die Diagramme da. Derselbe forecastsTimestamp
    holt nicht noch einmal, ein neuer schon."""
    async def lauf():
        ms = await Miniserver().start()
        ms.system = {GET_FORECASTS: ("200", json.dumps(PROGNOSE))}
        app = _app(neue_app(ms))
        try:
            erst = _seite(app)
            await _hintergrund(app)
            dann = _seite(app)
            await _hintergrund(app)
            einmal = ms.system_abrufe.get(GET_FORECASTS)
            app.states["sp-forecastsTimestamp"] = 2000
            _seite(app)
            await _hintergrund(app)
            return erst, dann, einmal, ms.system_abrufe.get(GET_FORECASTS)
        finally:
            await app.icon_session.close()
            await ms.stop()
    erst, dann, einmal, zweimal = asyncio.run(lauf())
    assert "Prognose wird geladen …" in _texte(erst, "status") and not bloecke(erst, "chart")
    assert [b["kind"] for b in bloecke(dann, "chart")] == ["analog", "digital"]
    assert (einmal, zweimal) == (1, 2)


def test_prognose_nicht_abrufbar(miniserver_http):
    """Lehnt der Miniserver ab, steht das da; neu versucht wird nicht sofort."""
    async def lauf():
        ms = await Miniserver().start()
        ms.system = {GET_FORECASTS: ("500", "")}
        app = _app(neue_app(ms))
        try:
            _seite(app)
            await _hintergrund(app)
            v = _seite(app)
            await _hintergrund(app)
            return v, ms.system_abrufe.get(GET_FORECASTS)
        finally:
            await app.icon_session.close()
            await ms.stop()
    v, abrufe = asyncio.run(lauf())
    assert "Prognose nicht abrufbar" in _texte(v, "status")
    assert abrufe == 1


class Ws:
    def __init__(self):
        self.nachrichten = []

    async def send_json(self, msg):
        self.nachrichten.append(msg)

    def ansichten(self) -> list:
        return [m for m in self.nachrichten if m.get("t") == "view"]


def test_neue_prognose_kommt_auf_die_offene_seite(miniserver_http):
    """Wie im Betrieb: Die Seite ist offen, der Miniserver meldet einen neuen
    forecastsTimestamp (Lesespur: die Seite liest ihn), der Broadcaster
    rendert sie, sie holt die neue Prognose, und die kommt ohne Zutun an."""
    neu = [dict(e, v=round(e["v"] / 2, 4)) for e in PROGNOSE]

    async def takt(app):
        await app._broadcast_tick()
        await _hintergrund(app)
        await app._broadcast_tick()

    async def lauf():
        ms = await Miniserver().start()
        ms.system = {GET_FORECASTS: ("200", json.dumps(PROGNOSE))}
        app = _app(neue_app(ms))
        ws = Ws()
        app.conn_route[ws] = {"view": "control", "id": "SPO"}
        try:
            await takt(app)
            ms.system[GET_FORECASTS] = ("200", json.dumps(neu))
            app._on_value("sp-forecastsTimestamp", 2000)
            await takt(app)
            return ws.ansichten()
        finally:
            await app.icon_session.close()
            await ms.stop()
    ansichten = asyncio.run(lauf())
    preise = [[p[1] for p in bloecke(v, "chart")[0]["series"][0]["pts"]] for v in ansichten if bloecke(v, "chart")]
    assert preise[0][0] == 0.301 and preise[-1][0] == 0.1505, preise
