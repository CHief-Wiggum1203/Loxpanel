"""LoxBerry-Widget (index.cgi): Miniserver-Zugang ueber POST
/api/settings/miniserver speichern und die Antwort richtig anzeigen.

Vertrag des Servers (api_settings_ms): "error" ist ein fester Text, der Fehler
des Miniservers steht getrennt in "fehler". Abgelehnt: nichts gespeichert,
Fehler. Nicht erreichbar: gespeichert ("gespeichert": true), das ist eine
Warnung. Fehlende Eingaben kommen als 400 mit JSON; das heisst nicht, dass der
Container fehlt.

Den Zugang bekommt nur LoxPanel: Antwortet unter dem Port etwas anderes (ein
anderes Plugin belegt ihn), geht nichts hinaus, und das Status-Feld nennt den
Grund, ebenso ein gestopptes Panel. Den Port fragt das Widget bei
loxpanel-ctl.sh ab; "Aus LoxBerry uebernehmen" nimmt bei "HTTPS bevorzugen"
den HTTPS-Port des Miniservers.

Das CGI laeuft mit perl (Widget aus loxberry.py) neben dem echten
loxpanel-ctl.sh, gegenueber steht der echte Server unter dem Port des Plugins
mit dem Miniserver-Nachbau aus lox.py. Config-Ordner umgeleitet (cfg_ordner),
HTTP statt HTTPS (miniserver_http)."""
import asyncio
import html
import json
import re
import subprocess
import time

import pytest
from aiohttp import web

from lox import anlage, konfig, Miniserver, serve, W
from loxberry import FEHLENDE_WERKZEUGE, LoxBerry, PERL, Widget
from test_miniserver_zugang import _freier_port

pytestmark = pytest.mark.skipif(not PERL or bool(FEHLENDE_WERKZEUGE),
                                reason=f"braucht perl und {FEHLENDE_WERKZEUGE}")

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
    """(Art, Text ohne Markup) der Meldung im Status-Feld des Widgets; ein
    geschuetztes Leerzeichen (&nbsp;) zaehlt als Leerzeichen."""
    m = re.search(r"<div class='alert alert-(\w+)'>(.*?)</div>", seite, re.S)
    assert m, seite
    return m.group(1), html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))).replace("\xa0", " ")


def _widget(tmp_path, felder=None, miniserver=None, mit_ms=True, mit_server=True, verbunden=False):
    """Miniserver-Nachbau und Server (unter dem Port des Plugins) starten, das
    Widget einmal aufrufen. felder/miniserver duerfen Funktionen des
    Miniserver-Ports sein. verbunden: der Server ist vorher schon mit dem
    Nachbau verbunden. Ohne Server fehlt auch der Container."""
    lb = LoxBerry(tmp_path / "lb", container="laeuft" if mit_server else "fehlt")

    async def lauf():
        ms = None
        if mit_ms:
            ms = Miniserver()
            ms.struktur = anlage(BAUSTEINE)
            ms = await ms.start(0)
        port = ms.port if ms else _freier_port()
        if verbunden:
            konfig._write_cfg({"miniserver": {"host": "127.0.0.1", "user": "loxpanel", "pass": "richtig", "port": port}})
        app = W.App(W._config())
        if verbunden:
            await app.reconnect()
            assert app.client is not None
        runner = (await serve(_ui(app), lb.port))[0] if mit_server else None
        try:
            befehl = Widget(tmp_path, lb=lb).befehl(felder(port) if callable(felder) else felder,
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


# ---- Port am LoxBerry, fremder Dienst auf dem Port, gestoppt ----

def _fremder_dienst(port: int, anfragen: list):
    """Ein anderes Plugin auf dem Port (Aggregator): beantwortet jede Anfrage
    mit seinem eigenen JSON und schreibt mit, was ankommt."""
    async def jede(request):
        anfragen.append((request.method, request.path, await request.text()))
        return web.json_response({"success": False, "error": "Unknown endpoint"})
    ui = web.Application()
    ui.router.add_route("*", "/{pfad:.*}", jede)
    return serve(ui, port)


@pytest.mark.parametrize("fremd", ["", "aggregator"])
def test_fremder_dienst_auf_dem_port_bekommt_keinen_zugang(tmp_path, fremd):
    """Belegt ein anderes Plugin den Port, startet LoxPanel nicht; das Widget
    erreichte unter dem Port das andere Plugin. Es darf ihm den Zugang nicht
    schicken und sagt, wer den Port belegt und wie es weitergeht."""
    lb = LoxBerry(tmp_path / "lb", container="fehlt")
    if fremd:
        lb.env["DOCKER_FREMD"] = fremd
    anfragen = []
    lox = {"IPAddress": "192.0.2.10", "Port": 80, "Admin_RAW": "admin", "Pass_RAW": "geheim-123"}

    async def lauf():
        runner, _ = await _fremder_dienst(lb.port, anfragen)
        try:
            seiten = []
            for felder, ms in (({"action": "fromlox"}, lox), (_formular(80, **{"pass": "geheim-123"}), None), (None, None)):
                r = await asyncio.to_thread(subprocess.run, **Widget(tmp_path, lb=lb).befehl(felder, ms))
                assert r.returncode == 0, r.stderr
                seiten.append(r.stdout)
            return seiten
        finally:
            await runner.cleanup()
    seiten = asyncio.run(lauf())
    wer = f"Docker-Container „{fremd}“" if fremd else "ein anderes Programm"
    for seite in seiten:
        art, text = _meldung(seite)
        assert art == "danger", text
        assert f"Port {lb.port} am LoxBerry ist belegt ({wer})" in text, text
        assert "Port am LoxBerry" in text, "nennt, wo der Port einzustellen ist"
    assert "Zugang nicht gesendet" in _meldung(seiten[0])[1] and "Zugang nicht gesendet" in _meldung(seiten[1])[1]
    assert [m for m, *_ in anfragen if m != "GET"] == [], anfragen
    assert not any("geheim-123" in rumpf or "admin" in rumpf for *_, rumpf in anfragen), anfragen
    assert "Container läuft nicht" in html.unescape(seiten[2])


def test_gestoppt_sagt_seit_wann_und_wie_es_wieder_startet(tmp_path):
    lb = LoxBerry(tmp_path / "lb")
    r = lb.ctl("stop")
    assert r.returncode == 0, r.stdout + r.stderr
    seite = Widget(tmp_path, lb=lb).aufruf()
    art, text = _meldung(seite)
    assert art == "warning", text
    seit = time.strftime("%d.%m.%Y", time.localtime((lb.configdir / "loxpanel_stopped.cfg").stat().st_mtime))
    assert "LoxPanel ist gestoppt" in text and seit in text, text
    assert "„Starten“" in text and "Neustart des LoxBerry" in text, text


def test_container_laeuft_antwortet_aber_nicht(tmp_path):
    lb = LoxBerry(tmp_path / "lb", container="laeuft")
    art, text = _meldung(Widget(tmp_path, lb=lb).aufruf())
    assert art == "warning" and f"antwortet aber (noch) nicht auf Port {lb.port}" in text, text


def test_links_und_feld_nennen_den_port_des_plugins(tmp_path):
    lb = LoxBerry(tmp_path / "lb", container="fehlt")
    (lb.configdir / "loxpanel_plugin.cfg").write_text("PORT=8098\r\n")
    seite = Widget(tmp_path, lb=lb).aufruf()
    assert 'href="http://127.0.0.1:8098/config"' in seite and 'href="http://127.0.0.1:8098/settings"' in seite
    assert 'name="lbport" value="8098"' in seite
    assert ":8099" not in seite and f":{lb.port}" not in seite


def _verlauf(lb, frist=30) -> str:
    """Verlauf der Aktion, die das Widget im Hintergrund gestartet hat."""
    log = lb.data / "last_action.log"
    ende = time.monotonic() + frist
    while time.monotonic() < ende:
        text = log.read_text(encoding="utf-8") if log.is_file() else ""
        if "abgeschlossen" in text:
            return text
        time.sleep(0.1)
    raise AssertionError(f"Aktion nicht abgeschlossen: {log}")


def test_port_im_widget_umstellen(tmp_path):
    lb = LoxBerry(tmp_path / "lb", container="laeuft")
    neu = str(_freier_port())
    art, text = _meldung(Widget(tmp_path, lb=lb).aufruf({"action": "port", "lbport": f" {neu} "}))
    assert art == "info" and "Port wird umgestellt" in text, text
    verlauf = _verlauf(lb)
    assert f"Port am LoxBerry: {neu}" in verlauf, verlauf
    assert f"PORT={neu}" in (lb.configdir / "loxpanel_plugin.cfg").read_text()
    assert f"LOXPANEL_LB_PORT={neu}" in (lb.configdir / "docker-compose.port.env").read_text()


@pytest.mark.parametrize("wert", ["abc", "80; rm -rf /", "123456", ""])
def test_port_im_widget_nur_ziffern(tmp_path, wert):
    lb = LoxBerry(tmp_path / "lb", container="laeuft")
    art, text = _meldung(Widget(tmp_path, lb=lb).aufruf({"action": "port", "lbport": wert}))
    assert art == "danger" and "kein Port" in text, text
    assert not (lb.data / "last_action.log").exists(), "nichts gestartet"
    assert not (lb.configdir / "loxpanel_plugin.cfg").exists()


@pytest.mark.parametrize("bevorzugt, nimmt", [
    (True, "https"), ("1", "https"), ("true", "https"),
    (False, "http"), ("0", "http"), (None, "http"),
])
def test_aus_loxberry_https_bevorzugen_nimmt_den_https_port(cfg_ordner, miniserver_http, tmp_path, bevorzugt, nimmt):
    """PreferHttps (in LoxBerry „HTTPS bevorzugen“): PortHttps statt Port. Der
    Nachbau lauscht nur auf einem der beiden, der andere ist frei."""
    frei = _freier_port()

    def lox(p):
        m = {"IPAddress": "127.0.0.1", "Admin_RAW": "loxpanel", "Pass_RAW": "richtig",
             "Port": p if nimmt == "http" else frei, "PortHttps": p if nimmt == "https" else frei}
        if bevorzugt is not None:
            m["PreferHttps"] = bevorzugt
        return m
    art, text = _meldung(_widget(tmp_path, {"action": "fromlox"}, lox))
    assert art == "success" and "1 Controls geladen" in text, text
    gespeichert = json.loads((cfg_ordner / "loxpanel.cfg").read_text())["miniserver"]["port"]
    assert gespeichert != frei
