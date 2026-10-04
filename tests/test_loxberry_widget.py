"""LoxBerry-Widget (index.cgi): Miniserver-Zugang ueber POST
/api/settings/miniserver speichern und die Antwort richtig anzeigen.

Vertrag des Servers (api_settings_ms): "error" ist ein fester Text, der Fehler
des Miniservers steht getrennt in "fehler". Abgelehnt: nichts gespeichert,
Fehler. Nicht erreichbar: gespeichert ("gespeichert": true), das ist eine
Warnung. Fehlende Eingaben kommen als 400 mit JSON; das heisst nicht, dass der
Container fehlt.

Das CGI laeuft mit perl (Widget aus loxberry.py), gegenueber steht der echte
Server mit dem Miniserver-Nachbau aus lox.py. Config-Ordner umgeleitet
(cfg_ordner), HTTP statt HTTPS (miniserver_http)."""
import asyncio
import html
import re
import subprocess

import pytest
from aiohttp import web

from lox import Miniserver, W, anlage, serve
from loxberry import PERL, Widget
from test_miniserver_zugang import _freier_port

pytestmark = pytest.mark.skipif(not PERL, reason="braucht perl")

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
                   "states": {"active": "l"}}}
ABGELEHNT = "Anmeldung am Miniserver gescheitert. Der Zugang wurde nicht gespeichert."
NICHT_ERREICHBAR = "Miniserver nicht erreichbar. Der Zugang ist trotzdem gespeichert"


@pytest.fixture(autouse=True)
def ohne_umgebung(monkeypatch):
    for k in ("HOST", "USER", "PASS", "PORT", "VERIFY_TLS"):
        monkeypatch.delenv(f"LOXPANEL_MS_{k}", raising=False)


def _ui(app):
    ui = web.Application()
    ui["app"] = app
    ui.router.add_get("/api/settings", W.api_settings)
    ui.router.add_post("/api/settings/miniserver", W.api_settings_ms)
    return ui


def _meldung(seite: str) -> tuple[str, str]:
    """(Art, Text ohne Markup) der Meldung im Status-Feld des Widgets."""
    m = re.search(r"<div class='alert alert-(\w+)'>(.*?)</div>", seite, re.S)
    assert m, seite
    return m.group(1), html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))


def _widget(tmp_path, felder=None, miniserver=None, mit_ms=True, mit_server=True, verbunden=False):
    """Miniserver-Nachbau und Server starten, das Widget einmal aufrufen.
    felder/miniserver duerfen Funktionen des Miniserver-Ports sein.
    verbunden: der Server ist vorher schon mit dem Nachbau verbunden."""
    async def lauf():
        ms = None
        if mit_ms:
            ms = Miniserver()
            ms.struktur = anlage(BAUSTEINE)
            ms = await ms.start(0)
        port = ms.port if ms else _freier_port()
        if verbunden:
            W._write_cfg({"miniserver": {"host": "127.0.0.1", "user": "loxpanel", "pass": "richtig", "port": port}})
        app = W.App(W._config())
        if verbunden:
            await app.reconnect()
            assert app.client is not None
        runner, api = (await serve(_ui(app))) if mit_server else (None, None)
        try:
            befehl = Widget(tmp_path).befehl(felder(port) if callable(felder) else felder,
                                             f"http://127.0.0.1:{api}" if api else None,
                                             miniserver(port) if callable(miniserver) else miniserver)
            r = await asyncio.to_thread(subprocess.run, **befehl)
        finally:
            if runner:
                await runner.cleanup()
            await app._close_conn()
            if ms:
                await ms.stop()
        assert r.returncode == 0, r.stderr
        return r.stdout
    return asyncio.run(lauf())


def _formular(port, **anders):
    return {"action": "miniserver", "host": "127.0.0.1", "user": "loxpanel", "pass": "richtig",
            "port": str(port), **anders}


def test_verbunden(cfg_ordner, miniserver_http, tmp_path):
    art, text = _meldung(_widget(tmp_path, _formular))
    assert art == "success" and "1 Controls geladen" in text


def test_abgelehnt_zeigt_fehler_und_text_des_miniservers(cfg_ordner, miniserver_http, tmp_path):
    art, text = _meldung(_widget(tmp_path, lambda p: _formular(p, **{"pass": "Tippfehler"})))
    assert art == "danger"
    assert ABGELEHNT in text and "401" in text, text
    assert not (cfg_ordner / "loxpanel.cfg").exists()


def test_nicht_erreichbar_ist_eine_warnung(cfg_ordner, miniserver_http, tmp_path):
    """Gespeichert, aber nicht geprueft: Warnung samt Grund, kein Fehler."""
    art, text = _meldung(_widget(tmp_path, _formular, mit_ms=False))
    assert art == "warning", text
    assert NICHT_ERREICHBAR in text and "127.0.0.1" in text, text
    assert (cfg_ordner / "loxpanel.cfg").exists()


def test_nicht_erreichbar_bei_bestehender_verbindung(cfg_ordner, miniserver_http, tmp_path):
    """Der Text des Servers hat Umlaute; die Seite ist UTF-8 (Widget.befehl
    liest sie so), Latin-1 aus decode_json kaeme dort als Fehler an."""
    art, text = _meldung(_widget(tmp_path, lambda p: _formular(_freier_port()), verbunden=True))
    assert art == "warning", text
    assert "der neue Zugang gilt ab dem nächsten Verbindungsaufbau" in text, text


def test_port_ungueltig(cfg_ordner, miniserver_http, tmp_path):
    art, text = _meldung(_widget(tmp_path, _formular(99999), mit_ms=False))
    assert art == "danger" and "Port ungültig" in text, text
    assert "Container" not in text


def test_speichern_scheitert_mit_500(cfg_ordner, miniserver_http, tmp_path):
    """Verbunden, aber loxpanel.cfg laesst sich nicht schreiben (hier ein
    Ordner an ihrer Stelle): 500 mit JSON ist eine Meldung des Servers."""
    (cfg_ordner / "loxpanel.cfg").mkdir()
    art, text = _meldung(_widget(tmp_path, _formular))
    assert art == "danger", text
    assert "Verbunden, aber der Zugang ließ sich nicht speichern" in text and "loxpanel.cfg" in text, text


def test_leerer_benutzer_ist_kein_toter_container(cfg_ordner, miniserver_http, tmp_path):
    art, text = _meldung(_widget(tmp_path, lambda p: _formular(p, user="")))
    assert art == "danger" and "Benutzer fehlt" in text, text
    assert "Container" not in text


def test_aus_loxberry_ohne_benutzer(cfg_ordner, miniserver_http, tmp_path):
    lox = lambda p: {"IPAddress": "127.0.0.1", "Port": p, "Admin_RAW": "", "Pass_RAW": "richtig"}  # noqa: E731
    art, text = _meldung(_widget(tmp_path, {"action": "fromlox"}, lox))
    assert art == "danger" and "kein Benutzer" in text and "LoxBerry" in text, text
    assert not (cfg_ordner / "loxpanel.cfg").exists()


def test_aus_loxberry_verbunden(cfg_ordner, miniserver_http, tmp_path):
    lox = lambda p: {"IPAddress": "127.0.0.1", "Port": p, "Admin_RAW": "loxpanel", "Pass_RAW": "richtig"}  # noqa: E731
    art, text = _meldung(_widget(tmp_path, {"action": "fromlox"}, lox))
    assert art == "success" and "1 Controls geladen" in text, text


def test_ohne_container(cfg_ordner, tmp_path):
    art, text = _meldung(_widget(tmp_path, _formular, mit_ms=False, mit_server=False))
    assert art == "danger" and "Container nicht erreichbar" in text, text
