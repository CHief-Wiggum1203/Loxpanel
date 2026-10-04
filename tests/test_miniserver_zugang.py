"""Miniserver-Zugang speichern (Settings -> Miniserver, POST /api/settings/miniserver).

Erst pruefen, dann schreiben: Lehnt der Miniserver die Anmeldung ab, bleibt
alles beim Alten - Datei und laufende Verbindung. Ist er nicht erreichbar,
wird gespeichert, eine bestehende Verbindung bleibt aber, bis sie neu
aufgebaut wird; ohne Verbindung versucht es der Wiederholungs-Loop sofort mit
dem neuen Zugang. Speichern laeuft nacheinander (auch mit dem Einspielen einer
Sicherung), und Anzeige wie Speichern sehen denselben Zugang wie _config()
(Datei vor LOXPANEL_MS_*).

Gegenueber steht der Nachbau aus lox.py mit Anmeldung (getkey2/getjwt) und
Struktur, verbunden wird mit dem echten LoxoneClient. Config-Ordner umgeleitet
(Fixture cfg_ordner), HTTP statt HTTPS (Fixture miniserver_http)."""
import asyncio
import json
import socket
import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from lox import Miniserver, W, anlage
from test_uebersetzung import _katalog_en

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
                   "states": {"active": "l"}}}
UMGEBUNG = ("HOST", "USER", "PASS", "PORT", "VERIFY_TLS")
ABGELEHNT = "Anmeldung am Miniserver gescheitert. Der Zugang wurde nicht gespeichert."


@pytest.fixture(autouse=True)
def ohne_umgebung(monkeypatch):
    """cfg_ordner loescht nur LOXPANEL_MS_HOST; die Tests setzen alle selbst."""
    for k in UMGEBUNG:
        monkeypatch.delenv(f"LOXPANEL_MS_{k}", raising=False)


def _umgebung(monkeypatch, **werte):
    for k, v in werte.items():
        monkeypatch.setenv(f"LOXPANEL_MS_{k.rstrip('_').upper()}", v)


async def _ms(port=0, **attr) -> Miniserver:
    ms = Miniserver()
    ms.struktur = anlage(BAUSTEINE)
    for k, v in attr.items():
        setattr(ms, k, v)
    return await ms.start(port)


def _freier_port() -> int:
    """Port, auf dem niemand lauscht: Verbinden scheitert sofort (nicht erreichbar)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ui(app):
    ui = web.Application()
    ui["app"] = app
    ui.router.add_get("/api/settings", W.api_settings)
    ui.router.add_post("/api/settings/miniserver", W.api_settings_ms)
    ui.router.add_post("/api/restore", W.api_restore)
    return ui


async def _speichern(cl, **body):
    r = await cl.post("/api/settings/miniserver", json=body)
    return r.status, await r.json()


def _zugang(port, kennwort="richtig", **mehr):
    return {"host": "127.0.0.1", "user": "loxpanel", "pass": kennwort, "port": port,
            "verify_tls": False, **mehr}


def _cfg_schreiben(ordner, ms):
    (ordner / "loxpanel.cfg").write_text(json.dumps({"miniserver": ms, "night": {"control": ""}}),
                                         encoding="utf-8")


def _datei_ms(ordner):
    return json.loads((ordner / "loxpanel.cfg").read_text(encoding="utf-8")).get("miniserver")


async def _bis(bedingung, frist=5.0):
    ende = time.monotonic() + frist
    while not bedingung():
        assert time.monotonic() < ende, "Bedingung nicht erreicht"
        await asyncio.sleep(0.02)


async def _abbrechen(task):
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def _uebersetzt(antwort):
    """Meldungen sind feste Schluessel des Katalogs; der Fehlertext steht getrennt."""
    assert antwort["error"] in _katalog_en(), antwort["error"]


def test_abgelehnter_zugang_ersetzt_nichts(cfg_ordner, miniserver_http):
    """Verbunden, dann mit Tippfehler im Kennwort gespeichert: Datei und
    Verbindung bleiben, ein Neustart verbindet weiter."""
    async def lauf():
        ms = await _ms()
        _cfg_schreiben(cfg_ordner, _zugang(ms.port))
        vorher = (cfg_ordner / "loxpanel.cfg").read_bytes()
        app = W.App(W._config())
        await app.reconnect()
        client = app.client
        async with TestClient(TestServer(_ui(app))) as cl:
            antwort = await _speichern(cl, **_zugang(ms.port, "Tippfehler"))
        live = (app.client is client, app.password)
        neu = W.App(W._config())                    # "Neustart": main() baut die App aus _config()
        n = await neu.reconnect()
        await app._close_conn()
        await neu._close_conn()
        await ms.stop()
        return antwort, vorher, live, n, ms.anmeldungen
    (status, j), vorher, live, n, anmeldungen = asyncio.run(lauf())

    assert status == 200 and j["ok"] is False and not j.get("gespeichert")
    assert j["error"] == ABGELEHNT and "401" in j["fehler"]
    _uebersetzt(j)
    assert (cfg_ordner / "loxpanel.cfg").read_bytes() == vorher, "abgelehnter Zugang steht nicht in der Datei"
    assert live == (True, "richtig"), "die laufende Verbindung bleibt"
    assert n == 1 and anmeldungen == ["ok", "abgelehnt", "ok"]


def test_parallel_speichern_bleibt_einig(cfg_ordner, miniserver_http):
    """Zwei Fenster speichern fast gleichzeitig, A antwortet langsam: Danach
    nennen Datei und Verbindung denselben Miniserver."""
    async def lauf():
        a = await _ms(verzoegerung=0.5)
        b = await _ms()
        app = W.App(W._config())
        async with TestClient(TestServer(_ui(app))) as cl:
            ta = asyncio.create_task(_speichern(cl, **_zugang(a.port)))
            await _bis(app._zugang_sperre.locked)        # A prueft schon
            tb = asyncio.create_task(_speichern(cl, **_zugang(b.port)))
            ra, rb = await ta, await tb
        live = app.port
        await app._close_conn()
        await a.stop()
        await b.stop()
        return ra, rb, live, a.port, b.port
    ra, rb, live, pa, pb = asyncio.run(lauf())

    assert ra[1]["ok"] and rb[1]["ok"]
    assert live == _datei_ms(cfg_ordner)["port"] == pb, "Verbindung und Datei nennen denselben Miniserver"


@pytest.mark.parametrize("port, erwartet", [("80", 80), ("", 443), ("acht", 443), ("70000", 443)],
                         ids=["gen1", "leer", "keine-zahl", "zu-gross"])
def test_anzeige_wie_config_umgebung(cfg_ordner, monkeypatch, port, erwartet):
    """Zugang aus LOXPANEL_MS_*: Settings zeigt Port und Zertifikatspruefung
    so, wie verbunden wird; ein leerer oder kaputter Port stuerzt nicht ab."""
    _umgebung(monkeypatch, host="10.0.0.5", user="visu", pass_="geheim", port=port, verify_tls="true")

    async def lauf():
        async with TestClient(TestServer(_ui(W.App(W._config())))) as cl:
            return (await (await cl.get("/api/settings")).json())["miniserver"]
    anzeige = asyncio.run(lauf())

    wirksam = W._config()
    assert wirksam["port"] == erwartet and wirksam["verify_tls"] is True
    assert anzeige == {"host": "10.0.0.5", "user": "visu", "port": erwartet, "verify_tls": True, "hasPass": True}


def test_anzeige_datei_ohne_kennwort(cfg_ordner, monkeypatch):
    """Hat die Datei einen Host, gilt sie ganz - ihr fehlendes Kennwort fuellt
    die Umgebung nicht, also auch kein "unveraendert lassen"."""
    _umgebung(monkeypatch, host="10.0.0.5", user="visu", pass_="geheim")
    _cfg_schreiben(cfg_ordner, {"host": "10.0.0.6", "user": "visu", "port": 80})

    async def lauf():
        async with TestClient(TestServer(_ui(W.App(W._config())))) as cl:
            return (await (await cl.get("/api/settings")).json())["miniserver"]
    anzeige = asyncio.run(lauf())

    assert W._config().get("pass") is None
    assert anzeige == {"host": "10.0.0.6", "user": "visu", "port": 80, "verify_tls": False, "hasPass": False}


@pytest.mark.parametrize("tls", [False, True], ids=["unveraendert", "tls-geaendert"])
def test_umgebung_speichern_ohne_kennwortfeld(cfg_ordner, miniserver_http, monkeypatch, tls):
    """Zugang aus LOXPANEL_MS_*, gespeichert mit leerem Kennwortfeld (Host und
    Benutzer gleich): Unveraendert schreibt nichts, die Umgebung gilt weiter;
    mit geaenderter Zertifikatspruefung braucht die Datei den ganzen Zugang."""
    async def lauf():
        ms = await _ms()
        _umgebung(monkeypatch, host="127.0.0.1", user="loxpanel", pass_="richtig", port=str(ms.port))
        app = W.App(W._config())
        await app.reconnect()
        async with TestClient(TestServer(_ui(app))) as cl:
            anzeige = (await (await cl.get("/api/settings")).json())["miniserver"]
            antwort = await _speichern(cl, host=anzeige["host"], user=anzeige["user"],
                                       port=anzeige["port"], verify_tls=tls)
        await app._close_conn()
        await ms.stop()
        return anzeige, antwort, ms.port
    anzeige, (status, j), port = asyncio.run(lauf())

    assert anzeige["port"] == port and anzeige["hasPass"] is True
    assert status == 200 and j["ok"] is True
    if tls:
        assert _datei_ms(cfg_ordner) == _zugang(port, verify_tls=True)
    else:
        assert not (cfg_ordner / "loxpanel.cfg").exists(), "das Kennwort der Umgebung wird nicht kopiert"
        assert W._ms_zugang() == (_zugang(port), "umgebung")


def test_umgebung_bleibt_bei_ablehnung(cfg_ordner, miniserver_http, monkeypatch):
    async def lauf():
        ms = await _ms()
        _umgebung(monkeypatch, host="127.0.0.1", user="loxpanel", pass_="richtig", port=str(ms.port))
        app = W.App(W._config())
        await app.reconnect()
        async with TestClient(TestServer(_ui(app))) as cl:
            antwort = await _speichern(cl, **_zugang(ms.port, "falsch"))
        await app._close_conn()
        await ms.stop()
        return antwort, ms.port
    (_, j), port = asyncio.run(lauf())

    assert j["ok"] is False and j["error"] == ABGELEHNT
    assert not (cfg_ordner / "loxpanel.cfg").exists()
    assert W._config() == _zugang(port), "die Umgebung gilt weiter"


def test_neues_ziel_braucht_kennwort(cfg_ordner, miniserver_http):
    """Leeres Kennwortfeld behaelt das Kennwort nur fuer denselben Host und
    Benutzer - an ein anderes Ziel geht es nicht."""
    async def lauf():
        ms = await _ms()
        _cfg_schreiben(cfg_ordner, _zugang(ms.port))
        app = W.App(W._config())
        async with TestClient(TestServer(_ui(app))) as cl:
            anderer = await _speichern(cl, host="127.0.0.1", user="admin", port=ms.port)
            gleicher = await _speichern(cl, host="127.0.0.1", user="loxpanel", port=ms.port)
        await app._close_conn()
        await ms.stop()
        return anderer, gleicher, ms.anmeldungen
    (status, j), gleicher, anmeldungen = asyncio.run(lauf())

    assert status == 400 and j == {"ok": False, "error": "Neuer Host oder Benutzer: bitte das Passwort eingeben."}
    _uebersetzt(j)
    assert gleicher[1]["ok"] is True and anmeldungen == ["ok"], "nur der gleiche Zugang hat sich angemeldet"


def test_weitere_schluessel_bleiben(cfg_ordner, miniserver_http):
    """msno, _comment und die Antwortfrist im Abschnitt ueberleben das Speichern."""
    async def lauf():
        ms = await _ms()
        _cfg_schreiben(cfg_ordner, {"_comment": "Notiz", "msno": 1, "response_timeout": 5,
                                    **_zugang(ms.port, "alt")})
        app = W.App(W._config())
        async with TestClient(TestServer(_ui(app))) as cl:
            antwort = await _speichern(cl, **_zugang(ms.port))
        await app._close_conn()
        await ms.stop()
        return antwort, ms.port
    (_, j), port = asyncio.run(lauf())

    assert j["ok"] is True
    assert _datei_ms(cfg_ordner) == {"_comment": "Notiz", "msno": 1, "response_timeout": 5, **_zugang(port)}


def test_nicht_erreichbar_bei_bestehender_verbindung(cfg_ordner, miniserver_http, monkeypatch):
    """Verbunden mit A, gespeichert wird B, der gerade nicht erreichbar ist:
    gespeichert mit Warnung, die Verbindung zu A bleibt. Bricht sie ab, baut
    der Loop sie mit B neu auf."""
    monkeypatch.setattr(W, "MS_RETRY", (0.05,))

    async def lauf():
        a = await _ms()
        _cfg_schreiben(cfg_ordner, _zugang(a.port))
        app = W.App(W._config())
        await app.reconnect()
        client = app.client
        port_b = _freier_port()
        async with TestClient(TestServer(_ui(app))) as cl:
            antwort = await _speichern(cl, **_zugang(port_b))
        live = (app.port, app.client is client)
        datei = _datei_ms(cfg_ordner)
        b = await _ms(port=port_b)
        # Der Nachbau hat keinen WebSocket: Der Loop scheitert daran wie an
        # einem Abbruch und baut neu auf.
        loop = asyncio.create_task(app.stream_task())
        await _bis(lambda: "ok" in b.anmeldungen)
        await _abbrechen(loop)
        nachher = (app.port, app._zugang_neu)
        await app._close_conn()
        await a.stop()
        await b.stop()
        return antwort, live, datei, nachher, a.port, port_b
    (status, j), live, datei, nachher, port_a, port_b = asyncio.run(lauf())

    assert status == 200 and j["ok"] is False and j["gespeichert"] is True and j["connected"] is True
    assert j["error"] == ("Miniserver nicht erreichbar. Der Zugang ist trotzdem gespeichert: Die bestehende "
                          "Verbindung bleibt, der neue Zugang gilt ab dem nächsten Verbindungsaufbau.")
    assert j["fehler"]
    _uebersetzt(j)
    assert live == (port_a, True), "die funktionierende Verbindung bleibt"
    assert datei == _zugang(port_b)
    assert nachher == (port_b, None), "beim naechsten Verbindungsaufbau gilt der neue Zugang"


def test_nicht_erreichbar_ohne_verbindung(cfg_ordner, miniserver_http, monkeypatch):
    """Ersteinrichtung, der Miniserver ist noch aus: gespeichert, und der Loop
    versucht es ohne Neustart mit dem neuen Zugang."""
    monkeypatch.setattr(W, "MS_RETRY", (0.05,))

    async def lauf():
        app = W.App(W._config())
        port = _freier_port()
        async with TestClient(TestServer(_ui(app))) as cl:
            antwort = await _speichern(cl, **_zugang(port))
        ms = await _ms(port=port)
        loop = asyncio.create_task(app.stream_task())
        await _bis(lambda: len(app.controls) == 1)
        await _abbrechen(loop)
        nachher = (app.host, app.port, app.password, ms.anmeldungen)
        await app._close_conn()
        await ms.stop()
        return antwort, nachher, port
    (_, j), nachher, port = asyncio.run(lauf())

    assert j["ok"] is False and j["gespeichert"] is True and j["connected"] is False
    assert j["error"] == "Miniserver nicht erreichbar. Der Zugang ist trotzdem gespeichert, LoxPanel versucht es damit weiter."
    _uebersetzt(j)
    assert _datei_ms(cfg_ordner) == _zugang(port)
    assert nachher[:3] == ("127.0.0.1", port, "richtig") and "ok" in nachher[3]


def test_antwortfrist(cfg_ordner, miniserver_http):
    """Antwortet der Miniserver nicht innerhalb von miniserver.response_timeout,
    gilt er als nicht erreichbar - das Speichern haengt nicht."""
    async def lauf():
        ms = await _ms(verzoegerung=1.5)
        _cfg_schreiben(cfg_ordner, {"response_timeout": 0.3})
        app = W.App(W._config())
        async with TestClient(TestServer(_ui(app))) as cl:
            t0 = time.monotonic()
            antwort = await _speichern(cl, **_zugang(ms.port))
            dauer = time.monotonic() - t0
        await app._close_conn()
        await ms.stop()
        return antwort, dauer
    (_, j), dauer = asyncio.run(lauf())

    assert dauer < 1.2, dauer
    assert j["gespeichert"] is True and j["fehler"] == "keine Antwort innerhalb von 0.3 s"


@pytest.mark.parametrize("wert, frist", [(None, W.MS_CMD_TIMEOUT), (2.5, 2.5), (20, 20), (0, W.MS_CMD_TIMEOUT),
                                         (-1, W.MS_CMD_TIMEOUT), ("zehn", W.MS_CMD_TIMEOUT),
                                         (True, W.MS_CMD_TIMEOUT)])
def test_antwortfrist_einstellung(cfg_ordner, wert, frist):
    _cfg_schreiben(cfg_ordner, {} if wert is None else {"response_timeout": wert})
    assert W._ms_antwortfrist() == frist


def test_einspielen_wartet_auf_speichern(cfg_ordner, tmp_path):
    """Einspielen einer Sicherung (loxpanel.cfg + reconnect) und Speichern des
    Zugangs laufen nacheinander."""
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    (quelle / "loxpanel.cfg").write_text(json.dumps({"night": {"control": ""}}), encoding="utf-8")
    daten = W._backup_zip(quelle)

    async def lauf():
        app = W.App(W._config())
        async with TestClient(TestServer(_ui(app))) as cl:
            async def einspielen():
                return (await cl.post("/api/restore", data=daten)).status
            async with app._zugang_sperre:
                task = asyncio.create_task(einspielen())
                await asyncio.sleep(0.3)
                wartet = not task.done()
            return wartet, await task
    wartet, status = asyncio.run(lauf())
    assert wartet and status == 200


def test_einspielen_ersetzt_ungeprueften_zugang(cfg_ordner, miniserver_http, tmp_path):
    """Ungeprueft gespeichert (nicht erreichbar), danach eine Sicherung mit dem
    laufenden Zugang eingespielt: Es gilt wieder, was in der Datei steht - der
    Loop wechselt beim naechsten Aufbau nicht mehr auf den ungeprueften."""
    async def lauf():
        a = await _ms()
        _cfg_schreiben(cfg_ordner, _zugang(a.port))
        quelle = tmp_path / "quelle"
        quelle.mkdir()
        _cfg_schreiben(quelle, _zugang(a.port))
        daten = W._backup_zip(quelle)            # Kennwort entfernt, gleicher Host und Benutzer
        app = W.App(W._config())
        await app.reconnect()
        async with TestClient(TestServer(_ui(app))) as cl:
            await _speichern(cl, **_zugang(_freier_port()))
            vorher = app._zugang_neu is not None
            j = await (await cl.post("/api/restore", data=daten)).json()
        nachher = app._zugang_neu
        await app._close_conn()
        await a.stop()
        return vorher, j, nachher, a.port
    vorher, j, nachher, port = asyncio.run(lauf())

    assert vorher and j["miniserver"] == "unveraendert"
    assert _datei_ms(cfg_ordner) == _zugang(port) and nachher is None
