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
uebrigen laufen deshalb nur gegen die Datei."""
from __future__ import annotations

import ast
import importlib.util
import itertools
import json
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from lox import ROOT

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


@pytest.mark.parametrize("secs, maximum", [("bald", "-3"), ("", "")], ids=["ungueltig", "leer"])
def test_ungueltige_werte_nehmen_den_standard(panel, secs, maximum):
    """Leer schreibt der Installer, wenn beim Aufruf nichts gesetzt war."""
    panel.conf(KIOSK_RESTART_SECS=secs, KIOSK_RESTART_MAX_SECS=maximum)
    m = panel.laden()
    assert (m.KIOSK_RESTART_SECS, m.KIOSK_RESTART_MAX_SECS) == (5, 300)


def test_auto_reload_bei_laufendem_kiosk(panel, monkeypatch):
    """Gegenprobe: der periodische Neustart aus der Announce-Antwort bleibt."""
    panel.conf(RELOAD_HOURS="1", KIOSK_RESTART_SECS="0")
    m = panel.laden()

    class Ende(Exception):
        pass

    class Takt:
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
