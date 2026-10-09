"""Umschalten gleich nach dem Speichern (Assistent, Punkt 9): Das Speichern
schickt jeder offenen Visu {t:"reload"}. Eine so angewiesene Verbindung wird
gleich ersetzt - ein Push an sie geht mit der Seite verloren und darf nicht
als erreicht zaehlen, sonst meldete /api/device/switch "ok", und das Geraet
kaeme mit dem alten Panel zurueck. Erreicht wird erst die neue Verbindung."""
import asyncio

from lox import W


class Ws:
    def __init__(self):
        self.nachrichten = []

    async def send_json(self, msg):
        self.nachrichten.append(msg)


def _verbinden(app, dev, panel):
    ws = Ws()
    app.conn_route[ws] = {"view": "home"}
    app.conn_prof[ws] = {"id": panel}
    app.conn_dev[ws] = dev
    app.conn_info[ws] = {"dev": dev, "kiosk": "", "ip": "10.0.0.5", "ts": 0}
    return ws


def test_umschalten_erreicht_erst_die_neue_verbindung():
    app = W.App({"host": "", "port": 80})
    app.panels = {"alt": {"title": "Alt"}, "flur": {"title": "Flur"}}

    async def lauf():
        alt = _verbinden(app, "tablet", "alt")
        anderes = _verbinden(app, "wand", "alt")
        assert await W._push(app, {"t": "reload"}) == 2
        # die alte Verbindung laedt neu: nichts mehr an sie, auch kein Umschalten
        assert await W._push(app, {"t": "switch", "panel": "flur"}, "", "tablet") == 0
        neu = _verbinden(app, "tablet", "alt")          # nach dem Neuladen wieder da
        assert await W._push(app, {"t": "switch", "panel": "flur"}, "", "tablet") == 1
        return alt, anderes, neu
    alt, anderes, neu = asyncio.run(lauf())
    assert alt.nachrichten == [{"t": "reload"}], alt.nachrichten
    assert anderes.nachrichten == [{"t": "reload"}], anderes.nachrichten
    assert neu.nachrichten == [{"t": "switch", "panel": "flur"}], neu.nachrichten


def test_neuladen_aus_dem_takt_zaehlt_genauso():
    """Hat sich die Loxone-Struktur geaendert, laedt der Takt (_pending_reload)
    alle Panels neu - auch diese Verbindungen erreicht ein Umschalten nicht mehr."""
    app = W.App({"host": "", "port": 80})
    app.panels = {"flur": {"title": "Flur"}}

    async def lauf():
        ws = _verbinden(app, "tablet", "")
        app._pending_reload = True
        await app._broadcast_tick()
        return ws, await W._push(app, {"t": "switch", "panel": "flur"}, "", "tablet")
    ws, n = asyncio.run(lauf())
    arten = [m.get("t") for m in ws.nachrichten]
    assert "reload" in arten and "switch" not in arten and n == 0, (arten, n)
