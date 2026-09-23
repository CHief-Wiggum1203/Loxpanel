"""Server-Stabilitaet (TODO.md Block 2): fehlende Oberflaechen-Dateien, Icon-
Cache, Wartezeiten beim Neuverbinden, Favoriten-Rueckfall und haengende Panels."""
import asyncio
import time
from pathlib import Path

from lox import W


class _Ersatz:
    """Modul-Ersatz nur fuer webvisu: einzelne Funktionen ueberschreiben, der
    Rest kommt aus dem echten Modul. So bleiben Event-Loop und andere Tests
    unberuehrt."""

    def __init__(self, modul, **ersetzt):
        self._modul, self._ersetzt = modul, ersetzt

    def __getattr__(self, name):
        return self._ersetzt[name] if name in self._ersetzt else getattr(self._modul, name)


def test_fehlende_datei_404():
    r = W._web_file(Path("/nicht/da/panel.html"), "text/html")
    assert r.status == 404 and "panel.html" in r.text
    r = W._web_file(W.HTML, "text/html")
    assert r.status == 200 and "<html" in r.text.lower()


def test_ohne_miniserver_bausteinuebersicht():
    W.App({"host": "", "port": 80}).types_overview()   # warf frueher AttributeError (op_modes)


def test_icon_cache_begrenzt():
    async def lauf():
        app = W.App({"host": "", "port": 80})

        async def http(path, timeout, renew=True):
            return 200, b"<svg/>", "image/svg+xml"
        app._ms_http = http
        for i in range(W.ICON_CACHE_MAX + 50):
            await app.fetch_icon(f"i{i}.svg")
        assert len(app.icon_cache) == W.ICON_CACHE_MAX and next(iter(app.icon_cache)) == "i50.svg"
        await app.fetch_icon("i50.svg")        # Treffer -> zuletzt benutzt
        await app.fetch_icon("neu.svg")        # verdraengt jetzt i51
        assert "i50.svg" in app.icon_cache and "i51.svg" not in app.icon_cache
    asyncio.run(lauf())


def _wartezeiten(monkeypatch, app, anzahl):
    """stream_task laufen lassen, bis anzahl Wartezeiten gesammelt sind."""
    echt, waits = asyncio.sleep, []

    async def schlaf(s):
        waits.append(s)
        if len(waits) >= anzahl:
            raise asyncio.CancelledError
        await echt(0)
    monkeypatch.setattr(W, "asyncio", _Ersatz(asyncio, sleep=schlaf))

    async def lauf():
        try:
            await app.stream_task()
        except asyncio.CancelledError:
            pass
    asyncio.run(lauf())
    return waits


def test_backoff_bei_dauerfehler(monkeypatch):
    app = W.App({"host": "", "port": 80})
    app.host = "miniserver"

    async def kaputt():
        raise ConnectionError("weg")
    app.start = kaputt
    assert _wartezeiten(monkeypatch, app, 7) == [5, 10, 20, 40, 60, 60, 60]


def test_backoff_von_vorn_erst_nach_stabiler_verbindung(monkeypatch):
    """Trennt der Miniserver sofort wieder, waechst die Wartezeit weiter; erst
    eine Verbindung, die MS_RETRY[-1] Sekunden hielt, setzt sie zurueck."""
    uhr = [1000.0]
    monkeypatch.setattr(W, "time", _Ersatz(time, monotonic=lambda: uhr[0]))
    halten = iter([1, 1, 1, W.MS_RETRY[-1] + 40, 1])

    class Verbindung:
        def __init__(self, dauer):
            self.dauer = dauer

        async def stream(self, *_):
            uhr[0] += self.dauer

        async def close(self):
            pass

    app = W.App({"host": "", "port": 80})
    app.host, app.client = "miniserver", object()

    async def verbinden():
        app.ws = Verbindung(next(halten))

    async def nichts():
        return False
    app._connect_ws, app._refresh_structure, app._reauth = verbinden, nichts, nichts
    assert _wartezeiten(monkeypatch, app, 5) == [5, 10, 20, 5, 10]


def test_favoriten_rueckfall():
    app = W.App({"host": "", "port": 80})
    app.controls = {"Z": {"name": "Küche", "type": "AudioZoneV2", "uuidAction": "ZA", "states": {}}}

    class Kanal:
        favs = {1: [{"name": "Radio 7091", "slot": 1, "cover": ""}]}
        paired, authed = True, False
    kanal = Kanal()
    app._audio_client_for = lambda c: (kanal, 1)
    app._audio_favs = lambda c: [{"name": "Radio Miniserver", "slot": 3, "cover": ""}]

    def namen():
        return [i["label"] for b in app._view_sources("Z")["blocks"] if b.get("k") == "favs" for i in b["items"]]
    assert namen() == ["Radio Miniserver"]          # gekoppelt, nicht angemeldet -> Miniserver
    kanal.authed = True
    assert namen() == ["Radio 7091"]
    kanal.paired, kanal.authed = False, False
    assert namen() == ["Radio 7091"]                # Nachbau ohne Kopplung


def test_haengendes_panel_blockiert_push_nicht():
    async def lauf():
        class Haengt:
            async def send_json(self, m):
                await asyncio.sleep(3600)

            async def close(self):
                pass

        class Ok:
            def __init__(self):
                self.got = []

            async def send_json(self, m):
                self.got.append(m)

            async def close(self):
                pass
        app = W.App({"host": "", "port": 80})
        h, o = Haengt(), Ok()
        for w in (h, o):
            app.conn_prof[w] = {"id": "p"}
            app.conn_route[w] = {}
            app.conn_info[w] = {}
        t = time.monotonic()
        n = await W._push(app, {"t": "notify", "text": "x"})
        assert n == 1 and o.got and 4.5 < time.monotonic() - t < 7
        assert h not in app.conn_prof and h not in app.conn_info, "haengendes Panel wird getrennt"
    asyncio.run(lauf())
