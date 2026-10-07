"""Panel-Agent der Linux-Wandpanels (agent/loxpanel-agent.py), ohne X und ohne
echtes Chromium.

Der Agent wird per importlib aus seiner Datei geladen; ein frischer Import ist
ein Neustart des Agenten. Alles, was er anfasst, liegt in tmp_path: kiosk.conf,
HOME, XDG_STATE_HOME und das Chromium-Profil. Im PATH steht nur ein
Stellvertreter fuer Chromium (kurzes Python-Skript, das seine URL protokolliert
und schlaeft, sofort endet oder auf ein Signal sauber endet); xset fehlt, damit
kein Test das Display des Rechners anfasst.

Der Installer deploy/install-agent.sh enthaelt den Agenten als Heredoc. Beide
muessen im Code gleich sein (CLAUDE.md), das prueft der erste Test; die
uebrigen laufen deshalb nur gegen die Datei.

Der letzte Teil spielt Server (webvisu ueber lox.visu_starten, Config in
cfg_ordner) und Agent zusammen: Ansicht wechseln unter Displays und
Betriebsmodus muessen beim Agenten ankommen. Die WebSocket-Verbindung des
Panels baut der Test selbst auf, der Chromium-Stellvertreter verbindet sich
nicht."""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import itertools
import json
import os
import signal
import sys
import threading
import time
import types
from http.server import ThreadingHTTPServer
from pathlib import Path

import aiohttp
import pytest

from lox import ROOT, W, anlage, visu_starten

AGENT = ROOT / "agent" / "loxpanel-agent.py"
INSTALL = ROOT / "deploy" / "install-agent.sh"
_nr = itertools.count()

# Stellvertreter fuer Chromium: protokolliert Start (PID, Zeit, URL) und tut,
# was in der Datei "modus" steht: "laufen" (schlafen bis zum Beenden) oder
# "ende" (sofort mit Code 1 enden, wie ein Absturz beim Start). SIGUSR1 beendet
# ihn sauber mit Code 0 (wie Alt+F4 am Panel).
CHROMIUM = """#!{python}
import json, os, signal, sys, time
ordner = {ordner!r}
with open(os.path.join(ordner, "chromium.log"), "a") as fh:
    fh.write(json.dumps({{"pid": os.getpid(), "t": time.time(), "url": sys.argv[-1]}}) + "\\n")
with open(os.path.join(ordner, "modus")) as fh:
    modus = fh.read().strip()
if modus == "ende":
    sys.exit(1)
signal.signal(signal.SIGUSR1, lambda *a: sys.exit(0))
time.sleep(3600)
"""


# Stellvertreter fuer xset: DPMS-Zustand ("Enabled 600" wie der X-Standard) in
# einer Datei, damit der Test sieht, welche Abschaltzeit der Agent setzt.
XSET = """#!{python}
import os, sys
datei = os.path.join({ordner!r}, "xset.state")
an, aus = open(datei).read().split() if os.path.exists(datei) else ("Enabled", "600")
a = sys.argv[1:]
if a[:1] == ["q"]:
    print("DPMS (Energy Star):\\n  Standby: 0    Suspend: 0    Off: %s\\nDPMS is %s\\n  Monitor is On" % (aus, an))
elif a[:1] == ["+dpms"]:
    an = "Enabled"
elif a[:1] == ["-dpms"]:
    an = "Disabled"
elif a[:1] == ["dpms"]:
    aus = a[3]
open(datei, "w").write("%s %s" % (an, aus))
"""


def heredoc() -> str:
    """Den Agenten aus dem Installer schneiden (zwischen <<'PYEOF' und PYEOF)."""
    text = INSTALL.read_text(encoding="utf-8")
    start = text.index("<<'PYEOF'\n") + len("<<'PYEOF'\n")
    return text[start:text.index("\nPYEOF\n", start) + 1]


class Panel:
    """Ein Wandpanel in tmp_path: kiosk.conf, Benutzerordner, Chromium."""

    def __init__(self, tmp_path: Path, monkeypatch):
        self.tmp = tmp_path
        self.mp = monkeypatch
        self.module: list = []
        for k in list(os.environ):
            if k.startswith("LOXPANEL_"):
                monkeypatch.delenv(k)
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.home = tmp_path / "home"
        self.state_home = self.home / ".local" / "state"
        self.conf_datei = tmp_path / "etc" / "loxpanel" / "kiosk.conf"
        self.conf_datei.parent.mkdir(parents=True)
        monkeypatch.setenv("PATH", str(self.bin))
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.setenv("XDG_STATE_HOME", str(self.state_home))
        monkeypatch.setenv("LOXPANEL_KIOSK_CONF", str(self.conf_datei))
        chromium = self.bin / "chromium"
        chromium.write_text(CHROMIUM.format(python=sys.executable, ordner=str(tmp_path)), encoding="utf-8")
        chromium.chmod(0o755)
        self.modus("laufen")
        self.conf()

    @property
    def state(self) -> Path:
        return self.state_home / "loxpanel" / "agent-state.json"

    def modus(self, m: str) -> None:
        (self.tmp / "modus").write_text(m, encoding="utf-8")

    def conf(self, **werte) -> None:
        """kiosk.conf schreiben; Server auf einen Port, an dem niemand lauscht."""
        basis = {"SERVER": "127.0.0.1:9", "AGENT_NAME": "wand", "PROFILE_DIR": str(self.tmp / "profil"),
                 "BL_DEVICE": "keins", "PANEL": ""}
        basis.update(werte)
        self.conf_datei.write_text("".join(f"{k}={v}\n" for k, v in basis.items()), encoding="utf-8")

    def laden(self, quelle: Path = AGENT):
        """Agent (neu) starten: Modul frisch importieren."""
        spec = importlib.util.spec_from_file_location(f"loxpanel_agent_{next(_nr)}", quelle)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        assert m.CONF_FILE == str(self.conf_datei), "Test liest eine fremde kiosk.conf"
        self.module.append(m)
        return m

    def starten(self, m, *panel) -> int:
        """Kiosk starten und warten, bis der Stellvertreter laeuft -> PID."""
        vorher = len(self.starts())
        assert m.start_kiosk(*panel)
        bis(lambda: len(self.starts()) > vorher, "Chromium gestartet")
        return m._proc.pid

    def starts(self) -> list[dict]:
        log = self.tmp / "chromium.log"
        if not log.exists():
            return []
        return [json.loads(z) for z in log.read_text(encoding="utf-8").splitlines()]

    def aufraeumen(self) -> None:
        for m in self.module:
            m.stop_kiosk()
        for s in self.starts():     # falls ein Test mittendrin scheiterte
            try:
                os.kill(s["pid"], signal.SIGKILL)
            except OSError:
                pass


@pytest.fixture
def panel(tmp_path, monkeypatch):
    p = Panel(tmp_path, monkeypatch)
    yield p
    p.aufraeumen()


def bis(bedingung, was: str, sekunden: float = 10) -> None:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        if bedingung():
            return
        time.sleep(0.02)
    raise AssertionError(f"nicht erreicht: {was}")


def test_heredoc_gleicht_der_datei():
    """CLAUDE.md: Agent immer an beiden Stellen aendern. Kommentare duerfen
    abweichen, der Code nicht."""
    assert ast.dump(ast.parse(heredoc())) == ast.dump(ast.parse(AGENT.read_text(encoding="utf-8")))


# ---- Panel-Wahl ueber einen Neustart des Agenten ----

def test_wahl_liegt_im_benutzerordner_und_ueberlebt_neustart(panel):
    """Der Installer legt /etc/loxpanel als root an, der Agent laeuft als
    Login-Benutzer: Die Wahl gehoert in dessen Ordner (XDG), nicht neben die
    kiosk.conf."""
    m = panel.laden()
    panel.starten(m, "pool")
    assert json.loads(panel.state.read_text())["panel"] == "pool"
    assert not (panel.conf_datei.parent / "loxpanel-agent-state.json").exists()
    m.stop_kiosk()
    assert panel.laden()._cur_panel == "pool"


def test_wahl_trotz_schreibgeschuetztem_conf_ordner(panel):
    """Wie nach install-agent.sh: der Ordner der kiosk.conf gehoert nicht dem
    Agenten. Laeuft nur, wo der Schreibschutz greift (nicht als root mit
    CAP_DAC_OVERRIDE; in der CI laeuft pytest als normaler Benutzer)."""
    panel.conf_datei.parent.chmod(0o555)
    try:
        (panel.conf_datei.parent / "probe").write_text("")
    except PermissionError:
        pass
    else:
        panel.conf_datei.parent.chmod(0o755)
        pytest.skip("dieser Prozess schreibt auch in schreibgeschuetzte Ordner")
    try:
        panel.laden().start_kiosk("pool")
        assert panel.laden()._cur_panel == "pool"
    finally:
        panel.conf_datei.parent.chmod(0o755)


@pytest.mark.parametrize("xdg", [None, "relativ/state"], ids=["ohne", "relativ"])
def test_ohne_gueltiges_xdg_state_home_gilt_local_state(panel, xdg):
    """XDG-Spezifikation: fehlt XDG_STATE_HOME oder ist es nicht absolut, gilt
    ~/.local/state."""
    if xdg is None:
        panel.mp.delenv("XDG_STATE_HOME")
    else:
        panel.mp.setenv("XDG_STATE_HOME", xdg)
    m = panel.laden()
    assert m.STATE_FILE == str(panel.home / ".local" / "state" / "loxpanel" / "agent-state.json")


def test_alte_state_datei_wird_uebernommen(panel):
    """Bis hierher lag die Datei neben der kiosk.conf. Wer dort schreiben
    konnte (Agent als root), behaelt seine Wahl."""
    (panel.conf_datei.parent / "loxpanel-agent-state.json").write_text('{"panel": "keller"}')
    assert panel.laden()._cur_panel == "keller"
    assert json.loads(panel.state.read_text())["panel"] == "keller"


def test_alte_state_datei_wird_nur_einmal_uebernommen(panel):
    """Nach der Uebernahme ist die alte Datei weg: Wer die neue loescht (README,
    DEPLOY.md: Weg zurueck auf PANEL), bekommt PANEL und nicht die alte Wahl."""
    panel.conf(PANEL="pool")
    alt = panel.conf_datei.parent / "loxpanel-agent-state.json"
    alt.write_text('{"panel": "keller"}')
    assert panel.laden()._cur_panel == "keller"
    assert not alt.exists()
    panel.state.unlink()
    assert panel.laden()._cur_panel == "pool"


def test_alte_state_datei_bleibt_wenn_speichern_scheitert(panel):
    """Kann der Agent am neuen Ort nicht speichern, ist die alte Datei die
    einzige Ablage der Wahl und bleibt liegen. (Ordner unter einer Datei:
    scheitert auch als root.)"""
    (panel.tmp / "datei").write_text("")
    panel.mp.setenv("XDG_STATE_HOME", str(panel.tmp / "datei"))
    alt = panel.conf_datei.parent / "loxpanel-agent-state.json"
    alt.write_text('{"panel": "keller"}')
    assert panel.laden()._cur_panel == "keller"
    assert alt.exists()
    assert panel.laden()._cur_panel == "keller"


def test_standardansicht_ueberlebt_neustart(panel):
    """Gespeichertes "" (Standardansicht) ist eine Wahl, nicht "nichts gemerkt"."""
    panel.conf(PANEL="pool")
    m = panel.laden()
    assert m._cur_panel == "pool"
    m.start_kiosk("")
    m.stop_kiosk()
    assert panel.laden()._cur_panel == ""


def test_ohne_gemerkte_wahl_gilt_die_conf(panel):
    panel.conf(PANEL="pool")
    assert panel.laden()._cur_panel == "pool"


def test_geaenderte_conf_gewinnt(panel):
    """Steht in der kiosk.conf ein anderes PANEL als beim Merken der Wahl (etwa
    nach einem neuen Lauf des Installers), gilt die kiosk.conf - auch dann,
    wenn sie spaeter wieder auf den alten Wert zurueckgestellt wird."""
    panel.conf(PANEL="pool")
    m = panel.laden()
    m.start_kiosk("keller")
    m.stop_kiosk()
    assert panel.laden()._cur_panel == "keller", "unveraenderte Conf: die Wahl gilt"
    panel.conf(PANEL="garten")
    assert panel.laden()._cur_panel == "garten"
    panel.conf(PANEL="pool")
    assert panel.laden()._cur_panel == "pool"


def test_schreibfehler_wird_gemeldet(panel, capsys):
    """Kann der Agent die Wahl nicht speichern, sagt er wo und was zu tun ist."""
    (panel.tmp / "datei").write_text("")
    panel.conf(STATE_FILE=str(panel.tmp / "datei" / "agent-state.json"))
    m = panel.laden()
    m.start_kiosk("pool")
    aus = capsys.readouterr().out
    assert str(panel.tmp / "datei") in aus and "STATE_FILE" in aus, aus


def test_state_datei_ohne_ordner_gilt_im_arbeitsordner(panel, monkeypatch):
    """STATE_FILE=agent-state.json (ohne Ordner) liegt im Arbeitsordner des
    Agenten, wie vor der XDG-Ablage."""
    monkeypatch.chdir(panel.tmp)
    panel.conf(STATE_FILE="agent-state.json")
    panel.laden()._panel_merken("pool")
    assert json.loads((panel.tmp / "agent-state.json").read_text())["panel"] == "pool"
    assert panel.laden()._cur_panel == "pool"


def test_panel_wird_in_der_url_kodiert(panel):
    """Die gemerkte Ansicht landet in der Kiosk-URL; Sonderzeichen duerfen dort
    keinen weiteren Parameter einschleusen."""
    m = panel.laden()
    panel.starten(m, "a&device=fremd")
    assert panel.starts()[-1]["url"].endswith("?panel=a%26device%3Dfremd&device=wand")


# ---- Absturz-Waechter ----

@pytest.mark.parametrize("sig", [signal.SIGKILL, signal.SIGUSR1], ids=["absturz", "sauber-beendet"])
def test_beendetes_chromium_startet_neu(panel, sig):
    """Jedes Ende ohne /stop gilt: Absturz, OOM-Kill oder ein sauberes Beenden
    am Panel (Alt+F4)."""
    panel.conf(PANEL="pool", KIOSK_RESTART_SECS="0.2")
    m = panel.laden()
    alt = panel.starten(m)
    os.kill(alt, sig)
    bis(lambda: len(panel.starts()) == 2 and m.running(), "Chromium neu gestartet")
    assert m._proc.pid != alt
    assert panel.starts()[-1]["url"] == panel.starts()[0]["url"], "dieselbe Ansicht"


def test_bewusster_stop_bleibt_aus(panel):
    panel.conf(KIOSK_RESTART_SECS="0.2")
    m = panel.laden()
    panel.starten(m)
    m.stop_kiosk()
    time.sleep(0.6)
    assert not m.running() and m._proc is None
    assert len(panel.starts()) == 1


def test_waechter_aus_mit_null(panel):
    panel.conf(KIOSK_RESTART_SECS="0")
    m = panel.laden()
    os.kill(panel.starten(m), signal.SIGKILL)
    time.sleep(0.6)
    assert not m.running() and len(panel.starts()) == 1


def test_neustart_gilt_nur_dem_abgestuerzten_prozess(panel):
    """Startet in der Pause jemand neu (/start, Auto-Reload), bleibt dieser
    Kiosk stehen; der Waechter startet ihn nicht noch einmal."""
    panel.conf(KIOSK_RESTART_SECS="0.5")
    m = panel.laden()
    os.kill(panel.starten(m), signal.SIGKILL)
    time.sleep(0.1)
    neu = panel.starten(m, "keller")
    time.sleep(1.0)
    assert m.running() and m._proc.pid == neu
    assert len(panel.starts()) == 2


def test_stop_in_der_pause_wartet_nicht_und_bleibt_aus(panel):
    """Die Pause laeuft ohne Sperre: /stop kommt sofort zurueck, danach bleibt
    der Kiosk aus."""
    panel.conf(KIOSK_RESTART_SECS="1")
    m = panel.laden()
    os.kill(panel.starten(m), signal.SIGKILL)
    time.sleep(0.2)
    t0 = time.monotonic()
    m.stop_kiosk()
    assert time.monotonic() - t0 < 0.5
    time.sleep(1.3)
    assert not m.running() and len(panel.starts()) == 1


def test_absturzschleife_verdoppelt_die_pause_bis_zur_obergrenze(panel):
    """Pause je Absturz: Stuerzt Chromium wieder ab, bevor es stabil lief,
    verdoppelt sie sich bis KIOSK_RESTART_MAX_SECS. Stabil heisst: laenger als
    die doppelte Obergrenze gelaufen; dann beginnt es wieder vorn."""
    panel.conf(KIOSK_RESTART_SECS="5", KIOSK_RESTART_MAX_SECS="60")
    m = panel.laden()
    kurz = 1.0
    assert [m._pause_nach_absturz(kurz) for _ in range(6)] == [5, 10, 20, 40, 60, 60]
    assert m._pause_nach_absturz(119) == 60, "unter der doppelten Obergrenze: weiter Schleife"
    assert m._pause_nach_absturz(120) == 5, "stabil gelaufen: von vorn"
    assert m._pause_nach_absturz(kurz) == 10


@pytest.mark.parametrize("befehl", ["stop", "start", "reload"])
def test_befehl_beginnt_die_pause_von_vorn(panel, befehl):
    """Nach einer Absturzschleife ist ein Befehl von Hand (/start, /reload,
    /stop unter Displays) ein Neuanfang: Der naechste Absturz wartet wieder
    KIOSK_RESTART_SECS, nicht die Obergrenze."""
    panel.conf(KIOSK_RESTART_SECS="5", KIOSK_RESTART_MAX_SECS="60")
    m = panel.laden()
    for _ in range(5):
        m._pause_nach_absturz(1.0)
    assert m._absturz_pause == 60
    srv = ThreadingHTTPServer(("127.0.0.1", 0), m.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        anfrage = m.urlreq.Request(f"http://127.0.0.1:{srv.server_address[1]}/{befehl}", data=b"{}")
        assert json.loads(m.urlreq.urlopen(anfrage, timeout=10).read())["ok"]
    finally:
        srv.shutdown()
        srv.server_close()
    assert m._pause_nach_absturz(1.0) == 5


def test_absturzschleife_am_prozess(panel):
    """Echte Schleife: der Stellvertreter endet sofort. Zwischen den Starts
    liegt jeweils mindestens die (wachsende) Pause."""
    panel.modus("ende")
    panel.conf(KIOSK_RESTART_SECS="0.1", KIOSK_RESTART_MAX_SECS="0.4")
    m = panel.laden()
    m.start_kiosk()
    bis(lambda: len(panel.starts()) >= 5, "fuenf Starts", sekunden=15)
    m.stop_kiosk()
    t = [s["t"] for s in panel.starts()[:5]]
    abstand = [b - a for a, b in zip(t, t[1:])]
    assert all(ab >= soll for ab, soll in zip(abstand, [0.1, 0.2, 0.4, 0.4])), abstand


def test_obergrenze_liegt_ueber_der_display_abschaltung(panel):
    """Jeder Kiosk-Start setzt per xset den Leerlaufzaehler zurueck. Laege die
    Obergrenze unter DPMS_OFF, hielte eine Absturzschleife das Display an."""
    m = panel.laden()
    assert m.KIOSK_RESTART_SECS == 5, "wie RestartSec=5 der Dienstdateien"
    assert m.KIOSK_RESTART_MAX_SECS > m._dpms_default()


@pytest.mark.parametrize("secs, maximum", [("bald", "-3"), ("", ""), ("inf", "nan")],
                         ids=["ungueltig", "leer", "nicht-endlich"])
def test_ungueltige_werte_nehmen_den_standard(panel, secs, maximum):
    """Leer schreibt der Installer, wenn beim Aufruf nichts gesetzt war. "inf"
    liesse time.sleep im Waechter mit OverflowError abbrechen."""
    panel.conf(KIOSK_RESTART_SECS=secs, KIOSK_RESTART_MAX_SECS=maximum)
    m = panel.laden()
    assert (m.KIOSK_RESTART_SECS, m.KIOSK_RESTART_MAX_SECS) == (5, 300)


def test_auto_reload_bei_laufendem_kiosk(panel, monkeypatch):
    """Gegenprobe: der periodische Neustart aus der Announce-Antwort bleibt.
    Bis dahin lief der Kiosk ohne Absturz: Eine fruehere Absturzschleife ist
    vorbei, der naechste Absturz wartet wieder KIOSK_RESTART_SECS und nicht die
    Obergrenze."""
    panel.conf(RELOAD_HOURS="1", KIOSK_RESTART_SECS="5", KIOSK_RESTART_MAX_SECS="60")
    m = panel.laden()
    for _ in range(5):
        m._pause_nach_absturz(1.0)   # Schleife vor dem stabilen Lauf
    assert m._absturz_pause == 60

    class Ende(Exception):
        pass

    class Takt:
        monotonic = staticmethod(time.monotonic)   # vor "time": das verdeckt hier das Modul
        time = staticmethod(time.time)

        @staticmethod
        def sleep(_s):
            raise Ende

    class Antwort:
        def read(self):
            return b'{"reloadHours": null}'

    monkeypatch.setattr(m.urlreq, "urlopen", lambda *a, **k: Antwort())
    alt = panel.starten(m, "pool")
    m._last_reload = time.time() - 2 * 3600
    monkeypatch.setattr(m, "time", Takt)
    with pytest.raises(Ende):
        m.announce_loop()
    assert m.running() and m._proc.pid != alt
    assert m._pause_nach_absturz(1.0) == 5


# ---- Ansicht wechseln und Betriebsmodus erreichen den Agenten ----

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "sl"}}}
PROFILE = {"panels": {"day": {"title": "Tag", "tabs": ["favoriten"], "ui": {"dpmsOff": 300, "reloadHours": 6}},
                      "night": {"title": "Nacht", "tabs": ["favoriten"], "ui": {"dpmsOff": 30, "reloadHours": 1}}},
           "devices": {"wand": {"auto": True, "modes": {"tag": "day", "nacht": "night"}}}}
ROUTEN = [("POST", "/api/agent/announce", W.api_agent_announce),
          ("POST", "/api/agent/command", W.api_agent_command),
          ("POST", "/api/device/switch", W.api_device_switch),
          ("GET", "/api/mode/{mode}", W.api_mode)]


class _Halt(BaseException):
    """Beendet die Announce-Schleife nach genau einem Takt (statt time.sleep(15))."""


def _halt(_s):
    raise _Halt


async def _nachricht(ws, art: str, sekunden: float = 5) -> dict:
    """Naechste Nachricht vom Typ `art` (andere ueberspringen), mit Gesamtfrist."""
    async def warten():
        while True:
            m = await ws.receive_json()
            if m.get("t") == art:
                return m
    return await asyncio.wait_for(warten(), sekunden)


class Wand:
    """Server und Agent eines Wandpanels, wie sie im Betrieb zusammenspielen."""

    def __init__(self, app, m, s, basis, lp, panel):
        self.app, self.m, self.s, self.basis, self.lp, self.panel = app, m, s, basis, lp, panel

    async def melden(self) -> None:
        """Ein Takt der Announce-Schleife des Agenten (echter HTTP-Weg)."""
        def einmal():
            echt = self.m.time
            self.m.time = types.SimpleNamespace(time=time.time, sleep=_halt)
            try:
                self.m.announce_loop()
            except _Halt:
                pass
            finally:
                self.m.time = echt
        await self.lp.run_in_executor(None, einmal)

    async def post(self, pfad: str, daten: dict) -> dict:
        async with self.s.post(self.basis + pfad, json=daten) as r:
            return await r.json()

    async def verbinden(self, adresse: str):
        """WebSocket der Visu wie das Chromium des Panels -> (ws, theme)."""
        ws = await self.s.ws_connect(f"{self.basis}/ws{adresse}")
        return ws, await _nachricht(ws, "theme")

    def xset_aus(self) -> int:
        return int((self.panel.tmp / "xset.state").read_text().split()[1])


async def _wand(panel, cfg_ordner, schritt, panels=PROFILE):
    """Server mit den Profilen day (Display aus nach 300 s, Neustart alle 6 h)
    und night (30 s, 1 h), dazu der echte Agent "wand" mit PANEL=day, seinem
    HTTP-Handler und dem xset-Stellvertreter."""
    (cfg_ordner / "panels.json").write_text(json.dumps(panels), encoding="utf-8")
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"sl": 0}
    runner, port, bc = await visu_starten(app, ROUTEN)
    xset = panel.bin / "xset"
    xset.write_text(XSET.format(python=sys.executable, ordner=str(panel.tmp)), encoding="utf-8")
    xset.chmod(0o755)
    # KIOSK_RESTART_SECS=0: melden() ersetzt kurz die Uhr des Agenten
    panel.conf(SERVER=f"127.0.0.1:{port}", PANEL="day", KIOSK_RESTART_SECS="0")
    m = panel.laden()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), m.Handler)   # freier Port, den meldet der Agent
    m.PORT = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    lp = asyncio.get_running_loop()
    try:
        async with aiohttp.ClientSession() as s:
            return await schritt(Wand(app, m, s, f"http://127.0.0.1:{port}", lp, panel))
    finally:
        srv.shutdown()
        srv.server_close()
        await lp.run_in_executor(None, m.stop_kiosk)
        bc.cancel()
        await runner.cleanup()


async def _bis(bedingung, was: str, sekunden: float = 10) -> None:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        if bedingung():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"nicht erreicht: {was}")


async def _switch_empfangen(ws) -> dict:
    return await _nachricht(ws, "switch")


def test_ansicht_wechseln_uebernimmt_der_agent_ohne_neustart(panel, cfg_ordner):
    """Displays -> "Ansicht wechseln": Die Visu wechselt per WebSocket, der Agent
    uebernimmt die Wahl mit seiner naechsten Meldung, ohne Chromium neu zu
    starten. Danach gelten Abschaltzeit und Neustartintervall von night, und
    jeder spaetere Kiosk-Start oeffnet night."""
    async def lauf(w: Wand):
        await w.lp.run_in_executor(None, w.panel.starten, w.m)
        await w.melden()
        assert w.app.agents["127.0.0.1"]["features"] == ["panel"]
        assert w.xset_aus() == 300
        ws, _ = await w.verbinden("?panel=day&device=wand")
        j = await w.post("/api/device/switch", {"device": "wand", "ip": "127.0.0.1", "panel": "night"})
        assert j == {"ok": True, "sent": 1, "via": "ws", "agent": "announce"}
        assert (await _switch_empfangen(ws))["panel"] == "night"
        await w.melden()
        assert w.m._cur_panel == "night"
        assert json.loads(w.panel.state.read_text())["panel"] == "night"
        assert w.xset_aus() == 30
        assert len(w.panel.starts()) == 1, "kein Chromium-Neustart"
        await w.melden()
        assert w.app.agents["127.0.0.1"]["panel"] == "night"
        assert w.app.agent_wunsch == {}, "gemeldet: Wahl erledigt"
        await ws.close()
    asyncio.run(_wand(panel, cfg_ordner, lauf))


def test_alter_agent_startet_mit_dem_neuen_profil(panel, cfg_ordner):
    """Ein Agent ohne die Faehigkeit "panel" (aeltere Fassung) bekommt wie
    bisher /start mit dem neuen Profil, also einen Chromium-Neustart."""
    async def lauf(w: Wand):
        await w.lp.run_in_executor(None, w.panel.starten, w.m)
        await w.post("/api/agent/announce", {"name": "wand", "panel": "day", "ip": "127.0.0.1",
                                             "port": w.m.PORT, "kiosk": True})
        ws, _ = await w.verbinden("?panel=day&device=wand")
        j = await w.post("/api/device/switch", {"device": "wand", "ip": "127.0.0.1", "panel": "night"})
        assert j["ok"] and j["agent"] == "start"
        await _bis(lambda: len(w.panel.starts()) == 2, "Chromium neu gestartet")
        assert "panel=night" in w.panel.starts()[-1]["url"]
        assert w.m._cur_panel == "night"
        await ws.close()
    asyncio.run(_wand(panel, cfg_ordner, lauf))


def test_betriebsmodus_gibt_dem_agenten_das_profil(panel, cfg_ordner):
    """Betriebsmodus von Loxone: Visu per WebSocket, der Agent uebernimmt das
    Profil ebenso (Abschaltzeit, naechster Kiosk-Start)."""
    async def lauf(w: Wand):
        await w.lp.run_in_executor(None, w.panel.starten, w.m)
        await w.melden()
        ws, _ = await w.verbinden("?panel=day&device=wand")
        async with w.s.get(w.basis + "/api/mode/nacht") as r:
            assert (await r.json())["switched"][0]["via"] == "ws"
        assert (await _switch_empfangen(ws))["panel"] == "night"
        await w.melden()
        assert w.m._cur_panel == "night" and w.xset_aus() == 30
        assert len(w.panel.starts()) == 1
        await ws.close()
    asyncio.run(_wand(panel, cfg_ordner, lauf))


def test_reload_vor_der_uebernahme_startet_mit_der_wahl(panel, cfg_ordner):
    """"Reload" gleich nach dem Wechsel, bevor der Agent sich gemeldet hat:
    Chromium startet mit der neuen Ansicht, nicht mit der alten."""
    async def lauf(w: Wand):
        await w.lp.run_in_executor(None, w.panel.starten, w.m)
        await w.melden()
        ws, _ = await w.verbinden("?panel=day&device=wand")
        await w.post("/api/device/switch", {"device": "wand", "ip": "127.0.0.1", "panel": "night"})
        j = await w.post("/api/agent/command", {"ip": "127.0.0.1", "action": "reload"})
        assert j["ok"]
        await _bis(lambda: len(w.panel.starts()) == 2, "Chromium neu gestartet")
        assert "panel=night" in w.panel.starts()[-1]["url"]
        assert w.m._cur_panel == "night"
        await w.melden()
        assert w.app.agent_wunsch == {}, "erledigt, sobald er sie meldet"
        await ws.close()
    asyncio.run(_wand(panel, cfg_ordner, lauf))


def test_start_verwirft_eine_offene_wahl(panel, cfg_ordner):
    """"Start" mit einer Ansicht ist neuer als eine noch nicht uebernommene
    Wahl: die naechste Meldung stellt den Agenten nicht zurueck."""
    async def lauf(w: Wand):
        await w.lp.run_in_executor(None, w.panel.starten, w.m)
        await w.melden()
        ws, _ = await w.verbinden("?panel=day&device=wand")
        j = await w.post("/api/device/switch", {"device": "wand", "ip": "127.0.0.1", "panel": "night"})
        assert j["agent"] == "announce"
        assert (await w.post("/api/agent/command", {"ip": "127.0.0.1", "action": "start", "panel": "day"}))["ok"]
        await w.melden()
        assert w.m._cur_panel == "day"
        await ws.close()
    asyncio.run(_wand(panel, cfg_ordner, lauf))


async def _server(cfg_ordner, schritt, panels=PROFILE):
    """Nur der Server: Agenten melden sich im Test von Hand."""
    (cfg_ordner / "panels.json").write_text(json.dumps(panels), encoding="utf-8")
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(BAUSTEINE))
    app.states = {"sl": 0}
    runner, port, bc = await visu_starten(app, ROUTEN)
    try:
        async with aiohttp.ClientSession() as s:
            return await schritt(Wand(app, None, s, f"http://127.0.0.1:{port}", None, None))
    finally:
        bc.cancel()
        await runner.cleanup()


def _meldung(ip: str, name: str = "linaro", **mehr) -> dict:
    return {"name": name, "panel": "day", "ip": ip, "port": 9, "kiosk": True, "features": ["panel"], **mehr}


def test_agent_wird_ueber_die_ip_zugeordnet(cfg_ordner):
    """Geklonte Panels melden denselben Hostnamen. Die Wahl gilt dem Agenten
    der Zeile unter Displays (ihre IP), nicht irgendeinem mit dem Namen."""
    async def lauf(w: Wand):
        for ip in ("10.0.0.11", "10.0.0.12"):
            await w.post("/api/agent/announce", _meldung(ip))
        ws, _ = await w.verbinden("?panel=day&device=linaro")
        j = await w.post("/api/device/switch", {"device": "linaro", "ip": "10.0.0.12", "panel": "night"})
        assert j["agent"] == "announce"
        r12 = await w.post("/api/agent/announce", _meldung("10.0.0.12"))
        r11 = await w.post("/api/agent/announce", _meldung("10.0.0.11"))
        assert (r12.get("panel"), r12["dpmsOff"], r12["reloadHours"]) == ("night", 30, 1)
        assert ("panel" in r11, r11["dpmsOff"]) == (False, 300)
        await ws.close()
    asyncio.run(_server(cfg_ordner, lauf))


def test_wechsel_ueber_den_agenten_nur_wenn_er_online_ist(cfg_ordner):
    """Hat sich der Agent laenger als AGENT_ONLINE nicht gemeldet, wechselt nur
    die Visu; der Agent bekommt nichts (kein Warten auf ein totes Panel)."""
    async def lauf(w: Wand):
        await w.post("/api/agent/announce", _meldung("10.0.0.11"))
        w.app.agents["10.0.0.11"]["ts"] -= W.AGENT_ONLINE + 1
        ws, _ = await w.verbinden("?panel=day&device=linaro")
        j = await w.post("/api/device/switch", {"device": "linaro", "ip": "10.0.0.11", "panel": "night"})
        assert j == {"ok": True, "sent": 1, "via": "ws", "agent": ""}
        assert w.app.agent_wunsch == {}
        await ws.close()
    asyncio.run(_server(cfg_ordner, lauf))


def test_online_schwelle_folgt_dem_meldetakt():
    """Online heisst: hoechstens drei Meldungen in Folge verpasst; der Takt ist
    der des Agenten (time.sleep am Ende von announce_loop)."""
    baum = ast.parse(AGENT.read_text(encoding="utf-8"))
    schleife = next(f for f in baum.body if isinstance(f, ast.FunctionDef) and f.name == "announce_loop")
    schlaf = [n.args[0].value for n in ast.walk(schleife) if isinstance(n, ast.Call)
              and getattr(n.func, "attr", "") == "sleep"]
    assert schlaf == [W.AGENT_MELDETAKT]
    assert W.AGENT_ONLINE == 4 * W.AGENT_MELDETAKT


def test_ausdrueckliche_wahl_hebt_den_betriebsmodus_auf(cfg_ordner):
    """Laeuft ein Betriebsmodus, zieht der Server ein frisch verbundenes Geraet
    auf dessen Profil. Eine ausdrueckliche Wahl unter Displays muss das fuer
    dieses Geraet aufheben, sonst kehrt die Visu beim naechsten Verbinden
    zurueck. Der naechste Moduswechsel gilt wieder."""
    async def lauf(w: Wand):
        async with w.s.get(w.basis + "/api/mode/tag") as r:
            assert (await r.json())["ok"]
        ws, theme = await w.verbinden("?panel=night&device=wand")
        assert theme["title"] == "Tag", "Betriebsmodus zieht um"
        j = await w.post("/api/device/switch", {"device": "wand", "panel": "night"})
        assert j["ok"] and (await _switch_empfangen(ws))["panel"] == "night"
        await ws.close()
        ws, theme = await w.verbinden("?panel=night&device=wand")   # Visu laedt mit ?panel=night neu
        assert theme["title"] == "Nacht"
        await ws.close()
        async with w.s.get(w.basis + "/api/mode/tag") as r:
            assert (await r.json())["ok"]
        ws, theme = await w.verbinden("?panel=night&device=wand")
        assert theme["title"] == "Tag", "naechster Moduswechsel gilt wieder"
        await ws.close()
    asyncio.run(_server(cfg_ordner, lauf))


def _adresse(url: str) -> str:
    """Query der Kiosk-URL, mit der der Chromium-Stellvertreter gestartet wurde."""
    return "?" + url.split("?", 1)[1]


def test_start_unter_displays_hebt_den_betriebsmodus_auf(panel, cfg_ordner):
    """Bei gestopptem Kiosk waehlt man die Ansicht unter Displays mit "Start"
    ("Ansicht wechseln" gibt es nur bei offener Visu). Laeuft ein Betriebsmodus,
    darf ws_handler die Visu nicht auf dessen Profil ziehen, waehrend der Agent
    sich die Wahl merkt: Visu, Agent und Abschaltzeit zeigen night."""
    async def lauf(w: Wand):
        await w.lp.run_in_executor(None, w.panel.starten, w.m)
        await w.melden()
        async with w.s.get(w.basis + "/api/mode/tag") as r:
            assert (await r.json())["ok"]
        assert (await w.post("/api/agent/command", {"ip": "127.0.0.1", "action": "stop"}))["ok"]
        vorher = len(w.panel.starts())
        j = await w.post("/api/agent/command", {"ip": "127.0.0.1", "action": "start", "panel": "night"})
        assert j["ok"]
        await _bis(lambda: len(w.panel.starts()) > vorher, "Chromium gestartet")
        ws, theme = await w.verbinden(_adresse(w.panel.starts()[-1]["url"]))
        assert theme["title"] == "Nacht"
        await w.melden()
        assert (w.m._cur_panel, w.xset_aus(), w.app.agent_wunsch) == ("night", 30, {})
        await ws.close()
    asyncio.run(_wand(panel, cfg_ordner, lauf))


@pytest.mark.parametrize("vorher", ["unbekannt", "offline"])
def test_betriebsmodus_beim_verbinden_erreicht_den_agenten(panel, cfg_ordner, vorher):
    """War der Agent beim Moduswechsel nicht da (noch nie gemeldet oder laenger
    als AGENT_ONLINE still), zieht ws_handler sein Chromium beim Verbinden auf
    das Profil des Modus. Das muss auch der Agent erfahren, sonst gelten
    Abschaltzeit und Neustartintervall des alten Profils weiter und der naechste
    Kiosk-Start oeffnet es wieder. Ein /start bekommt ein Agent, der nicht
    online ist, vom Moduswechsel nicht (kein Warten auf ein totes Panel)."""
    async def lauf(w: Wand):
        await w.lp.run_in_executor(None, w.panel.starten, w.m, "night")
        if vorher == "offline":
            await w.melden()
            w.app.agents["127.0.0.1"]["ts"] -= W.AGENT_ONLINE + 1
        async with w.s.get(w.basis + "/api/mode/tag") as r:
            assert (await r.json())["switched"] == [
                {"panel": "wand", "profile": "day", "ok": False, "error": "Panel nicht online"}]
        await w.melden()   # Agent wieder da, sein Chromium verbindet
        assert "panel=night" in w.panel.starts()[-1]["url"]
        ws, theme = await w.verbinden(_adresse(w.panel.starts()[-1]["url"]))
        assert theme["title"] == "Tag"
        await w.melden()
        assert (w.m._cur_panel, w.xset_aus()) == ("day", 300)
        assert len(w.panel.starts()) == 1, "ohne Chromium-Neustart"
        await w.melden()
        assert w.app.agent_wunsch == {}
        await ws.close()
    asyncio.run(_wand(panel, cfg_ordner, lauf))


def test_kiosk_start_vor_der_uebernahme_zeigt_die_wahl(panel, cfg_ordner):
    """Startet Chromium neu, bevor der Agent die Wahl gemeldet hat (Absturz-
    Waechter, Auto-Reload, Neustart des Agenten), oeffnet es noch die alte
    Ansicht. Die Visu zeigt trotzdem die Wahl, wie der Agent nach seiner
    naechsten Meldung auch; sonst liefen beide bis zum naechsten Chromium-Start
    auseinander."""
    async def lauf(w: Wand):
        await w.lp.run_in_executor(None, w.panel.starten, w.m)
        await w.melden()
        ws, _ = await w.verbinden("?panel=day&device=wand")
        await w.post("/api/device/switch", {"device": "wand", "ip": "127.0.0.1", "panel": "night"})
        await ws.close()
        await w.lp.run_in_executor(None, w.panel.starten, w.m)   # wie der Waechter: start_kiosk()
        assert "panel=day" in w.panel.starts()[-1]["url"]
        ws, theme = await w.verbinden(_adresse(w.panel.starts()[-1]["url"]))
        assert theme["title"] == "Nacht"
        await w.melden()
        assert w.m._cur_panel == "night"
        await ws.close()
    asyncio.run(_wand(panel, cfg_ordner, lauf))


def test_gescheiterter_befehl_behaelt_die_wahl(panel, cfg_ordner):
    """Erreicht ein Befehl den Agenten nicht (Zeitlimit, Port gesperrt), bleibt
    die Wahl stehen und der Agent uebernimmt sie mit seiner naechsten Meldung."""
    async def lauf(w: Wand):
        await w.lp.run_in_executor(None, w.panel.starten, w.m)
        await w.melden()
        ws, _ = await w.verbinden("?panel=day&device=wand")
        await w.post("/api/device/switch", {"device": "wand", "ip": "127.0.0.1", "panel": "night"})
        await ws.close()
        await _bis(lambda: not w.app.conn_dev, "Visu getrennt")
        # "Reload" mit offener Wahl wird zu /start mit ihr
        w.app.agents["127.0.0.1"]["port"] = 9   # dort lauscht niemand
        assert not (await w.post("/api/agent/command", {"ip": "127.0.0.1", "action": "reload"}))["ok"]
        assert w.app.agent_wunsch == {"127.0.0.1": "night"}
        await w.melden()
        assert w.m._cur_panel == "night"
        # "Ansicht wechseln" bei laufendem Kiosk ohne offene Visu schickt /start
        w.app.agents["127.0.0.1"]["port"] = 9
        j = await w.post("/api/device/switch", {"device": "wand", "ip": "127.0.0.1", "panel": "day"})
        assert j == {"ok": True, "sent": 1, "via": "agent", "agent": "announce"}
        await w.melden()
        assert (w.m._cur_panel, w.xset_aus()) == ("day", 300)
        assert len(w.panel.starts()) == 1
    asyncio.run(_wand(panel, cfg_ordner, lauf))
