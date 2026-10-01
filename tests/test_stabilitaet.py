"""Server-Stabilitaet (TODO.md Block 2): fehlende Oberflaechen-Dateien, Icon-
Cache, Wartezeiten beim Neuverbinden, Favoriten-Rueckfall und haengende Panels.
Dazu Eingaben, die eine Sicherung bringen kann: sehr viele Kategorie-Farben,
Tippfehler im Host von Display und Kamera."""
import asyncio
import time
from pathlib import Path

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

import theme_colors
from lox import W, anlage, serve


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


def test_viele_kategorie_farben_bremsen_nicht(cfg_ordner):
    """Jede Kachel fragt nach der Farbe ihrer Kategorie, die Suche lief jedes
    Mal ueber alle Eintraege: 100.000 Farben (Sicherung, /api/theme) kosteten
    0,7 s je Seite. Das Ergebnis ist je Kategoriename gemerkt und folgt dem
    Theme, sobald es neu geladen wird."""
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({}))                      # Kategorie c1 "Energie"
    viele = {f"kat{i:06d}": "#123456" for i in range(100_000)}
    app.theme = {"categories": {**viele, "nergi": "#ff0000", "Energie": "#00ff00"}}
    beginn = time.perf_counter()
    farben = {app._cat_color("c1") for _ in range(2000)}
    dauer = time.perf_counter() - beginn
    assert farben == {"#ff0000"}, "der erste passende Eintrag gilt, wie bisher"
    assert dauer < 2, f"{dauer:.1f} s"
    app._write_theme({}, {"Energie": {"on": "#0000ff", "off": "#333333"}})
    assert app._cat_color("c1") == "#0000ff"
    assert app._cat_states("c1") == {"on": "#0000ff", "off": "#333333"}


def test_tippfehler_im_display_host_stoppt_die_anderen_nicht():
    """Einen Host wie "tablet..home" nimmt die Namensaufloesung nicht an
    (ValueError statt Verbindungsfehler): display_drivers brach ab, die
    folgenden Geraete blieben dunkel."""
    async def lauf():
        app = W.App({"host": "", "port": 80})
        empfang = []

        async def wallpanel(request):
            empfang.append(await request.json())
            return web.json_response({})
        ui = web.Application()
        ui.router.add_post("/api/command", wallpanel)
        runner, port = await serve(ui)
        app.devices = {"Flur": {"display": {"driver": "fully", "host": "tablet..home", "port": 2323}},
                       "Küche": {"display": {"driver": "wallpanel", "host": "127.0.0.1", "port": port}}}
        try:
            return await app.display_drivers(True), empfang
        finally:
            if app._drv_session:
                await app._drv_session.close()
            await runner.cleanup()
    res, empfang = asyncio.run(lauf())
    assert [(r["device"], r["ok"]) for r in res] == [("Flur", False), ("Küche", True)], res
    assert empfang == [{"wake": True}]


def test_kamera_mit_tippfehler_meldet_502():
    """Host, den die Namensaufloesung nicht annimmt, oder ein Benutzer, der
    nicht in den Basic-Auth-Kopf passt: 502 wie bei einer nicht erreichbaren
    Kamera statt 500. Die Kamera B antwortet, nur der Benutzer passt nicht."""
    async def lauf():
        async def kamera(request):
            return web.Response(body=b"--frame", content_type="multipart/x-mixed-replace")
        cam = web.Application()
        cam.router.add_get("/mjpeg", kamera)
        runner, port = await serve(cam)
        app = W.App({"host": "", "port": 80})
        app.intercom_cfg = {"A": {"url": "http://cam..lan/mjpeg"},
                            "B": {"url": f"http://127.0.0.1:{port}/mjpeg", "user": "Łukasz", "pass": "x"},
                            "C": {"url": f"http://127.0.0.1:{port}/mjpeg", "user": "admin", "pass": "x"}}
        ui = web.Application()
        ui["app"] = app
        ui.router.add_get("/mjpeg", W.mjpeg_handler)
        try:
            async with TestClient(TestServer(ui)) as cl:
                return [(await cl.get("/mjpeg", params={"id": i})).status for i in ("A", "B", "C")]
        finally:
            await runner.cleanup()
    assert asyncio.run(lauf()) == [502, 502, 200]


def test_kamera_schliesst_ihre_verbindung_auch_beim_abbruch(monkeypatch):
    """Faehrt der Server herunter, waehrend die Kamera noch nicht geantwortet
    hat, wird der Handler mitten im Verbindungsaufbau abgebrochen. Die Session
    zur Kamera muss trotzdem zu sein, sonst bleiben Socket und Connector offen
    ("Unclosed client session")."""
    sitzungen = []

    def zaehler(*a, **kw):
        s = aiohttp.ClientSession(*a, **kw)
        sitzungen.append(s)
        return s
    monkeypatch.setattr(W, "aiohttp", _Ersatz(aiohttp, ClientSession=zaehler))

    async def lauf():
        angekommen, weiter = asyncio.Event(), asyncio.Event()

        async def kamera(request):
            angekommen.set()
            await weiter.wait()
            return web.Response()
        cam = web.Application()
        cam.router.add_get("/mjpeg", kamera)
        runner, port = await serve(cam)
        app = W.App({"host": "", "port": 80})
        app.intercom_cfg = {"A": {"url": f"http://127.0.0.1:{port}/mjpeg"}}
        ui = web.Application()
        ui["app"] = app
        handler = asyncio.create_task(W.mjpeg_handler(make_mocked_request("GET", "/mjpeg?id=A", app=ui)))
        try:
            await asyncio.wait_for(angekommen.wait(), 5)
            handler.cancel()
            try:
                await handler
            except asyncio.CancelledError:
                pass
            return [s.closed for s in sitzungen]
        finally:
            weiter.set()
            await runner.cleanup()
    assert asyncio.run(lauf()) == [True]


def test_kamera_ohne_text_als_adresse():
    """Eintraege mit "_" am Anfang prueft das Einspielen nicht (Kommentare);
    eine Zahl als Adresse warf TypeError, HTTP 500."""
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app.intercom_cfg = {"_x": {"url": 5}, "_kommentar": "", "leer": {"url": "  "}}
        ui = web.Application()
        ui["app"] = app
        ui.router.add_get("/mjpeg", W.mjpeg_handler)
        async with TestClient(TestServer(ui)) as cl:
            return [(await cl.get("/mjpeg", params={"id": i})).status for i in ("_x", "_kommentar", "leer")]
    assert asyncio.run(lauf()) == [404, 404, 404]


def test_grundfarbe_wird_gemerkt():
    """Eine Herleitung kostet 10 bis 60 ms und lief bei jeder Panel-Verbindung
    und jedem Speichern neu. Jeder Aufrufer bekommt ein eigenes dict."""
    theme_colors._derive.cache_clear()
    a = theme_colors.derive("#74a")
    b = theme_colors.derive(" #74A ")
    assert a == b and a is not b and theme_colors._derive.cache_info().hits == 1
    a["--bg"] = "kaputt"
    assert theme_colors.derive("#74a")["--bg"] != "kaputt"
    assert theme_colors.derive("kein") is None and theme_colors.derive(5) is None


def test_doppelte_raeume_im_profil_kosten_nichts():
    """Raeume und Kategorien eines Profils werden bei jeder Panel-Verbindung
    aufgeloest, jeder Eintrag gegen alle Namen. 150.000 gleiche Eintraege
    (Sicherung, /api/panels) kosteten je Verbindung Sekunden."""
    app = W.App({"host": "", "port": 80})
    app.rooms = {f"r{i}": {"name": f"{i}.0 Raum {i}"} for i in range(300)}
    erwartet = app._resolve_ids(["Raum 7"], app.rooms)
    beginn = time.perf_counter()
    assert app._resolve_ids(["Raum 7"] * 150_000, app.rooms) == erwartet
    assert time.perf_counter() - beginn < 1
