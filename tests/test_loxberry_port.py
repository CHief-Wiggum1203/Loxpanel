"""LoxBerry: Port am LoxBerry, belegter Port und "Stoppen" (loxpanel-ctl.sh),
das echte Skript gegen den Nachbau aus loxberry.py.

Der Port steht in loxpanel_plugin.cfg (PORT=, "port <port>" schreibt ihn),
start reicht ihn ueber docker-compose.port.env an die Compose-Datei. Belegt ein
anderes Programm den Port, startet LoxPanel nicht (docker scheiterte erst nach
dem Anlegen, und das Widget erreichte unter dem Port das andere Programm).
"Stoppen" haelt bis "Starten" oder bis zum naechsten Neustart des LoxBerry
(boot), nicht fuer immer. Ein Plugin-Update nimmt den Port mit."""
import re
import socket
import time

import pytest
import yaml

from lox import ROOT
from loxberry import FEHLENDE_WERKZEUGE, Installation, LoxBerry, PLUGIN, freier_port

pytestmark = pytest.mark.skipif(bool(FEHLENDE_WERKZEUGE), reason=f"es fehlen {FEHLENDE_WERKZEUGE}")

EINSTELLUNGEN = "loxpanel_plugin.cfg"
PORTDATEI = "docker-compose.port.env"
GESTOPPT = "loxpanel_stopped.cfg"


@pytest.fixture
def belegt():
    """Ein anderes Programm lauscht auf einem Port des LoxBerry -> der Port."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        yield s.getsockname()[1]


def _compose(lb) -> list[str]:
    return [a for _, a in lb.aufrufe() if a.startswith("compose")]


def _ausgabe(r) -> str:
    return r.stdout + r.stderr


def test_ohne_einstellung_der_standard(tmp_path):
    lb = LoxBerry(tmp_path)
    r = lb.ctl("port")
    assert r.returncode == 0 and r.stdout == f"{lb.port}\n", _ausgabe(r)


def test_standard_ist_der_port_im_container():
    """Ohne Einstellung gilt am LoxBerry derselbe Port wie im Container: im
    Skript, in der Compose-Datei (ohne Portdatei) und im Dockerfile."""
    ctl = (PLUGIN / "bin" / "loxpanel-ctl.sh").read_text(encoding="utf-8")
    standard = re.search(r'^PORT_STANDARD="\$\{LOXPANEL_CTL_PORT:-(\d+)\}"$', ctl, re.M).group(1)
    innen = re.search(r"^ENV LOXPANEL_PORT=(\d+)$", (ROOT / "Dockerfile").read_text(encoding="utf-8"), re.M).group(1)
    dienst = yaml.safe_load((PLUGIN / "config" / "docker-compose.yml").read_text(encoding="utf-8"))["services"]["loxpanel"]
    assert dienst["ports"] == [f"${{LOXPANEL_LB_PORT:-{innen}}}:{innen}"]
    assert standard == innen


def test_port_einstellen_und_start_reicht_ihn_durch(tmp_path):
    lb = LoxBerry(tmp_path, container="fehlt")
    neu = freier_port()
    r = lb.ctl("port", str(neu))
    assert r.returncode == 0, _ausgabe(r)
    assert f"Port am LoxBerry: {neu} (vorher {lb.port})" in r.stdout
    assert lb.ctl("port").stdout == f"{neu}\n"
    assert lb.container() == "laeuft", "nicht gestoppt -> startet gleich mit dem neuen Port"
    assert (lb.configdir / PORTDATEI).read_text().splitlines()[-1] == f"LOXPANEL_LB_PORT={neu}"
    aufrufe = _compose(lb)
    assert aufrufe and all(a.startswith(f"compose --env-file {lb.configdir / PORTDATEI} -f ") for a in aufrufe), aufrufe


def test_port_bei_laufendem_panel_faehrt_neu_hoch_ohne_pull(tmp_path):
    lb = LoxBerry(tmp_path, container="laeuft")
    neu = freier_port()
    r = lb.ctl("port", str(neu))
    assert r.returncode == 0, _ausgabe(r)
    assert "Starte LoxPanel mit dem neuen Port neu" in r.stdout
    aufrufe = _compose(lb)
    assert len(aufrufe) == 1 and aufrufe[0].endswith(" up -d "), aufrufe
    assert f"LOXPANEL_LB_PORT={neu}" in (lb.configdir / PORTDATEI).read_text()


def test_port_bei_gestopptem_panel_gilt_beim_naechsten_start(tmp_path):
    lb = LoxBerry(tmp_path, container="laeuft")
    assert lb.ctl("stop").returncode == 0
    neu = freier_port()
    r = lb.ctl("port", str(neu))
    assert r.returncode == 0 and "gilt beim nächsten Start" in r.stdout, _ausgabe(r)
    assert lb.container() == "fehlt" and (lb.configdir / GESTOPPT).exists()
    assert lb.ctl("start").returncode == 0
    assert f"LOXPANEL_LB_PORT={neu}" in (lb.configdir / PORTDATEI).read_text()


def test_derselbe_port_aendert_nichts(tmp_path):
    lb = LoxBerry(tmp_path)
    r = lb.ctl("port", str(lb.port))
    assert r.returncode == 0 and f"Port bleibt {lb.port}." in r.stdout, _ausgabe(r)
    assert not (lb.configdir / EINSTELLUNGEN).exists() and lb.aufrufe() == []


@pytest.mark.parametrize("wert", ["0", "65536", "abc", "8098x", "-1", ""])
def test_ungueltiger_port_aendert_nichts(tmp_path, wert):
    lb = LoxBerry(tmp_path)
    r = lb.ctl("port", wert)
    assert r.returncode == 1 and "kein gültiger Port" in r.stdout, _ausgabe(r)
    assert not (lb.configdir / EINSTELLUNGEN).exists() and lb.aufrufe() == []


@pytest.mark.parametrize("fremd", ["", "aggregator"])
def test_belegter_port_wird_nicht_eingestellt(tmp_path, belegt, fremd):
    lb = LoxBerry(tmp_path)
    r = lb.ctl("port", str(belegt), **({"DOCKER_FREMD": fremd} if fremd else {}))
    wer = f"Docker-Container „{fremd}“" if fremd else "ein anderes Programm"
    assert r.returncode == 1 and f"Port {belegt} am LoxBerry ist schon belegt ({wer})" in r.stdout, _ausgabe(r)
    assert not (lb.configdir / EINSTELLUNGEN).exists()
    assert _compose(lb) == []


@pytest.mark.parametrize("befehl", ["start", "check", "restart"])
def test_start_bei_belegtem_port_versucht_es_nicht(tmp_path, belegt, befehl):
    """Kein pull, kein up: das andere Programm haelt den Port, docker
    scheiterte daran erst nach dem Anlegen des Containers."""
    lb = LoxBerry(tmp_path, container="fehlt")
    (lb.configdir / EINSTELLUNGEN).write_text(f"PORT={belegt}\n")
    r = lb.ctl(befehl)
    assert r.returncode == 1, _ausgabe(r)
    assert f"Port {belegt} am LoxBerry ist schon belegt (ein anderes Programm) – LoxPanel startet so nicht" in r.stdout
    assert "Port am LoxBerry" in r.stdout
    assert [a for a in _compose(lb) if " up " in f" {a} " or " pull" in a] == []
    assert lb.container() == "fehlt"


def test_laufendes_panel_haelt_seinen_port_selbst(tmp_path, belegt):
    """Laeuft LoxPanel, ist der Port seiner: start bleibt moeglich."""
    lb = LoxBerry(tmp_path, container="laeuft")
    (lb.configdir / EINSTELLUNGEN).write_text(f"PORT={belegt}\n")
    r = lb.ctl("start")
    assert r.returncode == 0, _ausgabe(r)
    assert any(a.endswith(" up -d ") for a in _compose(lb))


@pytest.mark.parametrize("inhalt", ["PORT=abc\n", "PORT=70000\n", "PORT=\n"])
def test_unlesbare_einstellung_nimmt_den_standard(tmp_path, inhalt):
    lb = LoxBerry(tmp_path)
    (lb.configdir / EINSTELLUNGEN).write_text(inhalt)
    r = lb.ctl("port")
    assert r.returncode == 0 and r.stdout == f"{lb.port}\n", _ausgabe(r)
    if inhalt != "PORT=\n":
        assert "kein gültiger Port" in r.stderr


def test_einstellung_von_hand_mit_kommentar_und_windows_zeilen(tmp_path):
    lb = LoxBerry(tmp_path)
    (lb.configdir / EINSTELLUNGEN).write_text("# eigener Port\r\nPORT = 8097\r\n# PORT=1\r\n")
    assert lb.ctl("port").stdout == "8097\n"


def test_stoppen_haelt_bis_zum_neustart_des_loxberry(tmp_path):
    lb = LoxBerry(tmp_path, container="laeuft")
    assert lb.ctl("stop").returncode == 0
    assert lb.container() == "fehlt"
    r = lb.ctl("check")
    assert r.returncode == 0 and lb.container() == "fehlt", "die 5-Minuten-Pruefung laesst es aus"
    r = lb.ctl("boot")
    assert r.returncode == 0, _ausgabe(r)
    assert "startet mit dem LoxBerry wieder" in r.stdout
    assert lb.container() == "laeuft" and not (lb.configdir / GESTOPPT).exists()


def test_boot_ohne_stoppen_startet_nur_was_fehlt(tmp_path):
    lb = LoxBerry(tmp_path, container="laeuft")
    r = lb.ctl("boot")
    assert r.returncode == 0 and "Stoppen" not in r.stdout, _ausgabe(r)
    assert _compose(lb) == []


def test_daemon_ruft_boot():
    """Beim Start des LoxBerry hebt der Daemon ein "Stoppen" auf, der Cron nicht."""
    assert "loxpanel-ctl.sh boot" in (PLUGIN / "daemon" / "daemon").read_text(encoding="utf-8")
    assert "loxpanel-ctl.sh check" in (PLUGIN / "cron" / "cron.05min").read_text(encoding="utf-8")


def _zustand(lb, **umgebung) -> dict:
    r = lb.ctl("zustand", **umgebung)
    assert r.returncode == 0, _ausgabe(r)
    return dict(z.split("=", 1) for z in r.stdout.splitlines())


def test_zustand_fuer_das_widget(tmp_path, belegt):
    lb = LoxBerry(tmp_path, container="laeuft")
    assert _zustand(lb) == {"port": str(lb.port), "laeuft": "1", "gestoppt": "", "belegt": ""}
    assert lb.ctl("stop").returncode == 0
    z = _zustand(lb)
    assert z["laeuft"] == "0" and z["belegt"] == ""
    assert z["gestoppt"] == time.strftime("%d.%m.%Y %H:%M", time.localtime((lb.configdir / GESTOPPT).stat().st_mtime))
    (lb.configdir / EINSTELLUNGEN).write_text(f"PORT={belegt}\n")
    assert _zustand(lb, DOCKER_FREMD="aggregator")["belegt"] == "Docker-Container „aggregator“"


def test_update_nimmt_den_port_mit(tmp_path):
    lb = Installation(tmp_path)
    lauf = lb.installieren(update=False)
    assert {k: r.returncode for k, r in lauf.items()} == {"preroot": 0, "postroot": 0}, lauf
    neu = freier_port()
    r = lb.ctl("port", str(neu))
    assert r.returncode == 0, _ausgabe(r)
    lauf = lb.installieren(update=True)
    ausgabe = "\n".join(r.stdout + r.stderr for r in lauf.values())
    assert {k: r.returncode for k, r in lauf.items()} == {"preroot": 0, "preupgrade": 0,
                                                         "postupgrade": 0, "postroot": 0}, ausgabe
    assert lb.ctl("port").stdout == f"{neu}\n"
    assert f"LOXPANEL_LB_PORT={neu}" in (lb.configdir / PORTDATEI).read_text()
    assert f"http://<LoxBerry-IP>:{neu}/config" in lauf["postroot"].stdout
    assert list(lb.zwischen.iterdir()) == [], "keine Zwischenkopie bleibt liegen"


def test_update_ohne_eigenen_port_laesst_keine_alte_kopie_auftauchen(tmp_path):
    lb = Installation(tmp_path)
    lb.installieren(update=False)
    (lb.zwischen / "loxpanel-upgrade-plugin.cfg").write_text("PORT=8097\n")    # von einem frueheren Lauf
    lauf = lb.installieren(update=True)
    assert lauf["postroot"].returncode == 0, lauf["postroot"].stdout
    assert lb.ctl("port").stdout == f"{lb.port}\n"
    assert not (lb.configdir / EINSTELLUNGEN).exists()


def test_update_bei_belegtem_port_meldet_es(tmp_path, belegt):
    lb = Installation(tmp_path)
    lb.installieren(update=False)
    (lb.configdir / EINSTELLUNGEN).write_text(f"PORT={belegt}\n")
    lauf = lb.installieren(update=True)
    assert lauf["postroot"].returncode == 1, lauf["postroot"].stdout
    assert "<WARNING> LoxPanel ist nicht gestartet" in lauf["postroot"].stdout
    assert f"Port {belegt} am LoxBerry ist schon belegt" in lauf["postroot"].stdout
    assert lb.ctl("port").stdout == f"{belegt}\n", "die Einstellung bleibt trotzdem"
