"""Ersteinrichtung: Ein frisches Panel (die App bringt nur die Vorlagen in
config/ mit) hat keinen Miniserver-Zugang. Der Platzhalter der Vorlage
(192.168.1.50, CHANGEME) darf nie als Zugang gelten, und die Panels zeigen,
solange der Server keine Struktur hat, wo der Konfigurator zu oeffnen ist.
Config-Ordner umgeleitet (Fixture cfg_ordner)."""
import asyncio
import shutil
import types

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from lox import ROOT, W, anlage, visu_starten

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
                   "states": {"active": "l"}}}


@pytest.fixture
def mit_vorlage(cfg_ordner):
    """Config-Ordner wie in der frisch installierten App: nur die Vorlage."""
    shutil.copy(ROOT / "config" / "loxpanel.cfg.example", cfg_ordner / "loxpanel.cfg.example")
    return cfg_ordner


def test_vorlage_ist_kein_zugang(mit_vorlage):
    assert W._config() == {}, "mit dem Platzhalter wuerde sich der Server endlos anmelden"
    cfg = W._load_cfg()
    assert "miniserver" not in cfg and cfg["audio"]["enabled"] is True, "die uebrigen Vorgaben gelten weiter"


def test_konfigurator_auf_frischem_geraet(mit_vorlage):
    """Settings zeigt keinen Platzhalter-Zugang und kein "Kennwort gesetzt";
    Speichern ohne Kennwort uebernimmt nicht CHANGEME, und eine andere
    Einstellung schreibt den Platzhalter nicht in die loxpanel.cfg."""
    async def lauf():
        app = W.App(W._config())
        app._apply_structure(anlage(BAUSTEINE))
        ui = web.Application()
        ui["app"] = app
        ui.router.add_get("/api/settings", W.api_settings)
        ui.router.add_post("/api/settings/miniserver", W.api_settings_ms)
        ui.router.add_post("/api/settings/night", W.api_settings_night)
        async with TestClient(TestServer(ui)) as cl:
            ms = (await (await cl.get("/api/settings")).json())["miniserver"]
            r = await cl.post("/api/settings/miniserver", json={"host": "10.0.0.5", "user": "visu"})
            ohne_kennwort = r.status, await r.json()
            nacht = (await cl.post("/api/settings/night", json={"control": "L"})).status
        return ms, ohne_kennwort, nacht
    ms, ohne_kennwort, nacht = asyncio.run(lauf())

    assert ms["host"] == "" and ms["user"] == "" and ms["hasPass"] is False
    assert ohne_kennwort == (400, {"ok": False, "error": "Passwort fehlt"})
    assert nacht == 200
    cfg = W.json.loads((mit_vorlage / "loxpanel.cfg").read_text(encoding="utf-8"))
    assert cfg["night"]["control"] == "L" and "miniserver" not in cfg


def _app(host="", fehler=""):
    app = W.App({"host": host, "port": 443})
    app._ms_fehler = fehler
    return app


def test_einrichtung_je_zustand(monkeypatch):
    monkeypatch.setattr(W, "_lan_adressen", lambda: ["192.168.1.37"])
    frisch = _app()._einrichtung_msg(_app()._einrichtung_stand())
    assert frisch == {"t": "einrichtung", "aktiv": True, "titel": "Miniserver einrichten",
                      "grund": "Noch kein Miniserver eingetragen.",
                      "hinweis": "Konfigurator im Browser eines Computers oder Handys im selben Netz öffnen:",
                      "pfad": "/config", "adressen": ["192.168.1.37"],
                      "unbekannt": "Die Adresse dieses Panels steht in seinen WLAN-Einstellungen."}
    assert _app("10.0.0.5")._einrichtung_stand() is None, "der erste Versuch laeuft noch: kein Aufblitzen"
    assert _app("10.0.0.5", "Anmeldung abgelehnt")._einrichtung_stand() == \
        ("Keine Verbindung zum Miniserver", "10.0.0.5: Anmeldung abgelehnt")
    verbunden = _app("10.0.0.5", "Anmeldung abgelehnt")
    verbunden._apply_structure(anlage(BAUSTEINE))
    assert verbunden._einrichtung_stand() is None
    assert verbunden._einrichtung_msg(None) == {"t": "einrichtung", "aktiv": False}


def test_stand_fuer_den_konfigurator():
    """Der Konfigurator fuehrt nach diesem Stand zuerst zum Miniserver; anders
    als die Karte der Panels auch waehrend des ersten Versuchs."""
    assert _app()._einrichtung_info() == {"stand": "kein_zugang"}
    assert _app("10.0.0.5")._einrichtung_info() == {"stand": "verbindet", "host": "10.0.0.5"}
    assert _app("10.0.0.5", "Anmeldung abgelehnt")._einrichtung_info() == \
        {"stand": "fehler", "host": "10.0.0.5", "fehler": "Anmeldung abgelehnt"}
    verbunden = _app("10.0.0.5", "Anmeldung abgelehnt")
    verbunden._apply_structure(anlage(BAUSTEINE))
    assert verbunden._einrichtung_info() is None


def test_settings_nennen_den_stand(cfg_ordner):
    async def lauf():
        app = _app()
        ui = web.Application()
        ui["app"] = app
        ui.router.add_get("/api/settings", W.api_settings)
        async with TestClient(TestServer(ui)) as cl:
            frisch = (await (await cl.get("/api/settings")).json())["einrichtung"]
            app._apply_structure(anlage(BAUSTEINE))
            fertig = (await (await cl.get("/api/settings")).json())["einrichtung"]
        return frisch, fertig
    assert asyncio.run(lauf()) == ({"stand": "kein_zugang"}, None)


@pytest.mark.parametrize("fehler, erwartet", [
    (ConnectionError("Anmeldung\n   abgelehnt"), "Anmeldung abgelehnt"),
    (ConnectionError("x" * 500), "x" * W.EINRICHTUNG_FEHLER_MAX + " …"),
    (TimeoutError(), "TimeoutError"),
], ids=["zeilen", "lang", "ohne-text"])
def test_verbindungsfehler_landet_im_hinweis(fehler, erwartet):
    """Den Grund nimmt stream_task aus dem gescheiterten Versuch: eine Zeile,
    so kurz, dass sie aufs Panel passt."""
    async def lauf():
        app = _app("10.0.0.5")

        async def start():
            raise fehler
        app.start = start
        task = asyncio.create_task(app.stream_task())
        for _ in range(100):
            await asyncio.sleep(0.01)
            if app._ms_fehler:
                break
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return app._ms_fehler
    assert asyncio.run(lauf()) == erwartet


class _Socket:
    """Stellvertreter fuer socket.socket: liefert eine feste Quelladresse
    oder scheitert beim connect wie ohne Route."""
    adresse = "192.168.1.37"

    def __init__(self, *args):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def connect(self, ziel):
        if self.adresse is None:
            raise OSError("Network is unreachable")

    def getsockname(self):
        return (self.adresse, 40000)


@pytest.mark.parametrize("adresse, erwartet", [("192.168.1.37", ["192.168.1.37"]), ("127.0.1.1", []),
                                               (None, [])], ids=["wlan", "loopback", "keine-route"])
def test_adresse_im_netz(monkeypatch, adresse, erwartet):
    monkeypatch.setattr(_Socket, "adresse", adresse)
    monkeypatch.setattr(W, "socket", types.SimpleNamespace(socket=_Socket, AF_INET=2, SOCK_DGRAM=2))
    assert W._lan_adressen() == erwartet


def test_panel_bekommt_hinweis_und_dessen_ende(monkeypatch):
    """Beim Verbinden kommt der Hinweis; sobald die Struktur da ist, schickt
    der Broadcaster das Ende."""
    monkeypatch.setattr(W, "_lan_adressen", lambda: ["192.168.1.37"])

    async def naechste(ws):
        while True:
            m = await asyncio.wait_for(ws.receive_json(), 5)
            if m.get("t") == "einrichtung":
                return m

    async def lauf():
        app = _app()
        runner, port, broadcaster = await visu_starten(app)
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://127.0.0.1:{port}/ws?panel=default") as ws:
                    anfang = await naechste(ws)
                    app._apply_structure(anlage(BAUSTEINE))
                    ende = await naechste(ws)
        finally:
            broadcaster.cancel()
            await runner.cleanup()
        return anfang, ende
    anfang, ende = asyncio.run(lauf())
    assert anfang["aktiv"] and anfang["adressen"] == ["192.168.1.37"]
    assert ende == {"t": "einrichtung", "aktiv": False}
