"""Server-Stabilitaet (TODO.md Block 2): fehlende Oberflaechen-Dateien, Icon-
Cache, Wartezeiten beim Neuverbinden, Favoriten-Rueckfall und haengende Panels.
Dazu Eingaben, die eine Sicherung bringen kann: sehr viele Kategorie-Farben,
Tippfehler im Host von Display und Kamera. Und der Audioserver: Kopplung
pruefen, wenn er beim Start noch nicht antwortet, Raumfavorit ohne Verbindung."""
import asyncio
import json
import time
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

import theme_colors
from audioserver_events import AudioEventClient
from lox import AUDIO_GEKOPPELT, Audioserver, Miniserver, W, anlage, bloecke, neue_app, serve


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
    eine Verbindung, die MS_RETRY[-1] Sekunden Daten lieferte, setzt sie
    zurueck (stumme Verbindungen: test_miniserver_ws.py)."""
    halten = iter([1, 1, 1, W.MS_RETRY[-1] + 40, 1])

    class Verbindung:
        def __init__(self, dauer):
            self.dauer = dauer

        async def stream(self, *_):
            pass

        def lebenszeit(self):
            return self.dauer

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
    kanal.paired = None
    assert namen() == ["Radio Miniserver"]          # Kopplung unklar -> wie gekoppelt


async def _bis(bedingung, frist=5.0):
    ende = time.monotonic() + frist
    while not bedingung():
        assert time.monotonic() < ende, "Bedingung nicht erreicht"
        await asyncio.sleep(0.02)


def _audio_lauf(koerper, **nachbau):
    """Miniserver- und Audioserver-Nachbau, App mit einer AudioZoneV2 (Zone 1,
    Favorit des Miniservers im sourceList-State) und laufendem Ereignis-Client
    wie aus audio_events_task(), nur mit kurzer Pause zwischen den Versuchen."""
    async def lauf():
        ms = await Miniserver().start()
        asv = await Audioserver(**nachbau).start()
        app = neue_app(ms)
        st = anlage({"Z": {"name": "Küche", "type": "AudioZoneV2", "uuidAction": "ZA", "room": "r1", "cat": "c1",
                           "states": {"sourceList": "SL"}, "details": {"server": "AS", "playerid": 1}}})
        st["mediaServer"] = {"AS": {"host": f"127.0.0.1:{asv.port}"}}
        app._apply_structure(st)
        app.states["SL"] = json.dumps({"getroomfavs_result": [{"items": [{"slot": 3, "name": "Radio Miniserver"}]}]})
        app.audio_cfg = {"port": asv.port}            # Direkt-Backend an den Nachbau statt an 7091
        cl = AudioEventClient("127.0.0.1", asv.port, user=ms.benutzer, token_provider=lambda: asv.jwt)
        cl.neu_versuch_s = 0.3
        app.audio_clients["127.0.0.1"] = cl
        lauf_cl = asyncio.create_task(cl.run(app._mark_dirty))
        try:
            await koerper(app, ms, asv, cl)
        finally:
            await cl.close()
            lauf_cl.cancel()
            for be in app.audio_backends.values():
                await be.close()
            await asv.stop()
            await app.icon_session.close()
            await ms.stop()
    asyncio.run(lauf())


def _favoriten(app):
    return [i["label"] for b in bloecke(app._view_sources("Z"), "favs") for i in b["items"]]


def test_audioserver_503_beim_start(miniserver_http):
    """Antwortet der Audioserver beim Start mit 503, ist die Kopplung unklar und
    nicht "ungekoppelt": Befehle bleiben am Miniserver, die Pruefung wird
    nachgeholt. Ist er gekoppelt, verbindet der Client neu, meldet sich an und
    holt die Favoriten ueber 7091."""
    async def k(app, ms, asv, cl):
        await _bis(lambda: cl._ws is not None)
        assert cl.paired is None, "503 als Ergebnis der Kopplungspruefung genommen"
        assert await app.command("ZA", "play") == "200"
        assert ms.io == ["sps/io/ZA/play"] and asv.befehle == []
        await _bis(lambda: cl.authed)
        assert cl.paired is True and len(asv.verbindungen) == 2 and asv.cfg_abrufe >= 2
        await _bis(lambda: _favoriten(app) == ["Radio 7091"])
        assert asv.befehle == [("audio/cfg/getroomfavs/1/0/50", True)]
    _audio_lauf(k, cfg_all=[(503, "Service Unavailable"), (200, AUDIO_GEKOPPELT)])


@pytest.mark.parametrize("antwort", [(503, "Service Unavailable"), (500, ""), (408, ""), (429, ""), "Zeitlimit"],
                         ids=["503", "500", "408", "429", "zeitlimit"])
def test_audioserver_kopplung_unklar(miniserver_http, antwort):
    """Solange die Kopplung unklar ist, gilt der Audioserver wie gekoppelt ohne
    Anmeldung: nichts auf dem Ereigniskanal (ein gekoppelter schloesse ihn, Cover
    und Titel waeren weg), Favoriten vom Miniserver. Die Pruefung wiederholt sich."""
    async def k(app, ms, asv, cl):
        if antwort == "Zeitlimit":           # gekoppelt, aber die Antwort kommt zu spaet
            cl.pruef_zeitlimit_s, asv.verzoegerung = 0.1, 0.5
        await _bis(lambda: cl._ws is not None)
        verbindung = cl._ws
        await app.prime_favs("Z")
        assert ms.io == ["sps/io/ZA/roomfav/get/0/20"]
        assert _favoriten(app) == ["Radio Miniserver"]
        await _bis(lambda: asv.cfg_abrufe >= 3)
        assert cl.paired is None and asv.befehle == [] and cl._ws is verbindung and not verbindung.closed
    _audio_lauf(k, cfg_all=[(200, AUDIO_GEKOPPELT) if antwort == "Zeitlimit" else antwort])


def test_audioserver_gekoppelt_bleibt_nach_neustart(miniserver_http):
    """Ein erkanntes "gekoppelt" bleibt, auch wenn der Audioserver nach einem
    Neustart die Pruefung erst mit 404 beantwortet: Der Client meldet sich neu
    an, Transportbefehle bleiben am Miniserver und gehen nicht ohne Anmeldung
    an Port 7091 (dort abgelehnt, aber als Erfolg gemeldet)."""
    async def k(app, ms, asv, cl):
        await _bis(lambda: cl.authed)
        await asv.verbindungen[0].close()            # Audioserver startet neu
        await _bis(lambda: len(asv.verbindungen) == 2)
        await _bis(lambda: cl.authed or cl.paired is not True)
        assert cl.paired is True, "404 nach dem Neustart als ungekoppelt genommen"
        assert cl.authed and asv.cfg_abrufe == 1
        assert await app.command("ZA", "play") == "200"
        assert ms.io == ["sps/io/ZA/play"]
        assert all(angemeldet for _, angemeldet in asv.befehle), asv.befehle
    _audio_lauf(k, cfg_all=[(200, AUDIO_GEKOPPELT), (404, "not found")])


def test_audioserver_falsch_ungekoppelt_heilt(miniserver_http):
    """Hielt die Pruefung einen gekoppelten Audioserver fuer ungekoppelt (404),
    schliesst er den Kanal beim ersten Befehl ohne Anmeldung. Vor dem
    Neuverbinden wird wieder geprueft: gekoppelt, Anmeldung, Favoriten ueber 7091."""
    async def k(app, ms, asv, cl):
        await _bis(lambda: cl._ws is not None)
        assert cl.paired is False
        await app.prime_favs("Z")
        await _bis(lambda: cl.authed)
        assert cl.paired is True and len(asv.verbindungen) == 2
        await _bis(lambda: _favoriten(app) == ["Radio 7091"])
    _audio_lauf(k, cfg_all=[(404, "not found"), (200, AUDIO_GEKOPPELT)])


def test_audioserver_nachbau_nach_503(miniserver_http):
    """Erst 503, dann eine Antwort ohne Kopplungstext: Nachbau. Die Favoriten
    kommen dann ueber 7091, auch auf einer schon offenen Musikauswahl."""
    async def k(app, ms, asv, cl):
        await _bis(lambda: cl._ws is not None)
        assert cl.paired is None
        await _bis(lambda: _favoriten(app) == ["Radio 7091"])
        assert cl.paired is False and len(asv.verbindungen) == 1
        assert asv.befehle == [("audio/cfg/getroomfavs/1/0/50", False)]
    _audio_lauf(k, gekoppelt=False, cfg_all=[(503, "Service Unavailable"), (200, '{"cfg_result": []}')])


@pytest.mark.parametrize("antwort", [(200, '{"cfg_result": []}'), (200, '\ufeff{"cfg_result": []}'),
                                     (200, '{"cfg_result": []}\x00'), (200, ""), (404, "not found")],
                         ids=["json", "bom", "nul", "leer", "404"])
def test_audioserver_nachbau_direkt(miniserver_http, antwort):
    """Jede andere Antwort heisst nicht gekoppelt. Nachbauten und Musikserver
    Gen 1 antworten nicht einheitlich, ein strengeres Kriterium liesse sie am
    Miniserver haengen: Befehle gehen direkt an Port 7091."""
    async def k(app, ms, asv, cl):
        await _bis(lambda: cl.paired is not None)
        assert cl.paired is False
        assert await app.command("ZA", "play") == "200"
        await _bis(lambda: asv.befehle)
        assert asv.befehle == [("audio/1/play", False)] and ms.io == []
    _audio_lauf(k, gekoppelt=False, cfg_all=[antwort])


def test_audioserver_favorit_ohne_verbindung(miniserver_http):
    """Raumfavorit am gekoppelten, angemeldeten Audioserver, die Verbindung ist
    aber schon zu (nach einem Abbruch, bevor run() authed zuruecksetzt): kein
    Erfolg melden, die Visu zeigt einen Hinweis. Der Test setzt dafuer eine
    schon geschlossene echte Verbindung ein; er prueft den Rueckgabeweg, nicht
    das Zeitfenster selbst."""
    async def k(app, ms, asv, cl):
        await _bis(lambda: cl.authed)
        assert await app.command("ZA", "roomfav/play/7") == "200"
        await _bis(lambda: ("audio/1/roomfav/play/7", True) in asv.befehle)
        echt = cl._ws
        ui = web.Application()
        ui["app"] = app
        ui.router.add_get("/ws", W.ws_handler)
        runner, port = await serve(ui)
        try:
            async with aiohttp.ClientSession() as s:
                tot = await s.ws_connect(f"http://127.0.0.1:{asv.port}/", protocols=("remotecontrol",))
                await tot.close()
                cl._ws = tot
                assert await cl.play_roomfav(1, 7) is False
                async with s.ws_connect(f"http://127.0.0.1:{port}/ws") as pws:
                    await pws.send_json({"t": "cmd", "uuid": "ZA", "cmd": "roomfav/play/7"})
                    hinweis = None
                    while hinweis is None:
                        m = await asyncio.wait_for(pws.receive_json(), 3)
                        hinweis = m if m.get("t") == "notify" else None
                    assert hinweis["level"] == "warn"
        finally:
            cl._ws = echt
            await runner.cleanup()
    _audio_lauf(k)


@pytest.mark.parametrize("am, pause, frist", [({}, 5, 6), ({"retry_interval": 2, "response_timeout": 3.5}, 2, 3.5),
                                              ({"retry_interval": 0, "response_timeout": "sechs"}, 5, 6),
                                              ({"retry_interval": True, "response_timeout": -1}, 5, 6)])
def test_audioserver_zeiten_einstellbar(cfg_ordner, am, pause, frist):
    """Pause vor dem naechsten Versuch und Zeitlimit der Kopplungspruefung aus
    loxpanel.cfg (audiometa); ohne gueltigen Wert die Standardwerte."""
    (cfg_ordner / "loxpanel.cfg").write_text(json.dumps({"audiometa": am, "night": {"control": ""}}),
                                             encoding="utf-8")

    async def lauf():
        app = W.App({"host": "", "port": 80}, None, W._audiometa_config())
        app.mediaservers = {"AS": "127.0.0.1:7091"}
        verwalter = asyncio.create_task(app.audio_events_task())
        await _bis(lambda: app.audio_clients)
        verwalter.cancel()
        cl = app.audio_clients["127.0.0.1"]
        await cl.close()
        return cl
    cl = asyncio.run(lauf())
    assert (cl.neu_versuch_s, cl.pruef_zeitlimit_s) == (pause, frist)
    assert (AudioEventClient.NEU_VERSUCH_S, AudioEventClient.PRUEF_ZEITLIMIT_S) == (5, 6)


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
