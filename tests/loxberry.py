"""Nachbau der LoxBerry-Umgebung fuer die Skripte in loxberry-plugin/.

Die Skripte laufen echt (bash, sh, tar, gzip, find, mv, flock). Ersetzt werden
nur Befehle, die es im Test nicht gibt oder die dort nichts anrichten duerfen:
sudo und docker. Ihre Stellvertreter schreibt `LoxBerry` zur Laufzeit nach
tmp_path und haengt sie vorn in PATH; im Repo liegen keine.

docker: `run --rm -v QUELLE:/data BILD sh -c BEFEHL [ARG ...]` fuehrt BEFEHL mit
/bin/sh aus (dash, wie im Image), /data im Befehl zeigt auf QUELLE (Ersatz fuer
den Bind-Mount). ps/stop/start/restart/rm/compose fuehren den Zustand des
Containers loxpanel in einer Datei (laeuft, gestoppt, fehlt). Jeder Aufruf
steht als eine Zeile in docker.log: Zustand vor dem Aufruf, dann die Argumente.
Steuerbar ueber die Umgebung: DOCKER_ULIMIT_F begrenzt die Dateigroesse im
Container (ulimit -f, wie ein voller Datentraeger), DOCKER_VERZOEGERUNG
verlangsamt jeden Lauf (Sekunden).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from lox import ROOT

PLUGIN = ROOT / "loxberry-plugin"
CTL = PLUGIN / "bin" / "loxpanel-ctl.sh"
WERKZEUGE = ("bash", "sh", "tar", "gzip", "find", "flock", "mktemp")
FEHLENDE_WERKZEUGE = [w for w in WERKZEUGE if not shutil.which(w)]

SUDO = '''#!/bin/sh
# Stellvertreter fuer sudo: Optionen -n und -u BENUTZER verwerfen, Rest ausfuehren.
while [ $# -gt 0 ]; do
  case "$1" in -n) shift ;; -u) shift 2 ;; *) break ;; esac
done
exec "$@"
'''

DOCKER = r'''#!/bin/bash
# Stellvertreter fuer docker, siehe tests/loxberry.py.
zustand=$(cat "$DOCKER_ZUSTAND" 2>/dev/null || echo fehlt)
printf '%s docker %s\n' "$zustand" "$(printf '%s ' "$@" | tr '\n' ' ')" >> "$DOCKER_LOG"
setzen() { echo "$1" > "$DOCKER_ZUSTAND"; }
case "$1" in
  run)
    shift; quelle=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --rm) shift ;;
        -v) quelle="${2%%:/data}"; shift 2 ;;
        sh) [ "$2" = "-c" ] || { echo "docker-Stellvertreter: nur sh -c" >&2; exit 125; }
            befehl=$3; shift 3; break ;;
        -*) echo "docker-Stellvertreter: unbekannte Option $1" >&2; exit 125 ;;
        *) shift ;;   # Image
      esac
    done
    [ -n "$quelle" ] || { echo "docker-Stellvertreter: kein -v ...:/data" >&2; exit 125; }
    [ -n "$DOCKER_ULIMIT_F" ] && ulimit -f "$DOCKER_ULIMIT_F"
    [ -n "$DOCKER_VERZOEGERUNG" ] && sleep "$DOCKER_VERZOEGERUNG"
    exec /bin/sh -c "${befehl//\/data/$quelle}" "$@" ;;
  ps) [ "$zustand" = laeuft ] && echo 0123456789ab; exit 0 ;;
  stop) [ "$zustand" = fehlt ] && { echo "No such container: $2" >&2; exit 1; }; setzen gestoppt ;;
  start|restart) [ "$zustand" = fehlt ] && { echo "No such container: $2" >&2; exit 1; }; setzen laeuft ;;
  rm) setzen fehlt ;;
  compose)
    case " $* " in *" up "*) setzen laeuft ;; *" down "*) setzen fehlt ;; esac ;;
  *) echo "docker-Stellvertreter: unbekannter Aufruf $*" >&2; exit 125 ;;
esac
exit 0
'''


def _ausfuehrbar(pfad: Path, text: str) -> Path:
    pfad.write_text(text, encoding="utf-8")
    pfad.chmod(0o755)
    return pfad


class LoxBerry:
    """Plugin-Ordner eines LoxBerry in tmp_path: data/ (config/, backups/) und
    config/ (docker-compose.yml) des Plugins, dazu die Stellvertreter.
    ctl() ruft das echte loxpanel-ctl.sh aus dem Repo; die Pfade, die sonst die
    Installation einsetzt, kommen ueber LOXPANEL_CTL_CONFIGDIR/_DATADIR."""

    def __init__(self, tmp: Path, container: str = "laeuft") -> None:
        self.tmp = tmp
        self.data = tmp / "lb" / "data" / "plugins" / "loxpanel"
        self.conf = self.data / "config"
        self.backups = self.data / "backups"
        self.configdir = tmp / "lb" / "config" / "plugins" / "loxpanel"
        for d in (self.conf, self.backups, self.configdir):
            d.mkdir(parents=True)
        shutil.copy(PLUGIN / "config" / "docker-compose.yml", self.configdir / "docker-compose.yml")
        self.fakebin = tmp / "fakebin"
        self.fakebin.mkdir()
        _ausfuehrbar(self.fakebin / "sudo", SUDO)
        _ausfuehrbar(self.fakebin / "docker", DOCKER)
        self.log = tmp / "docker.log"
        self.zustand = tmp / "container"
        self.zustand.write_text(container + "\n")
        self.env = dict(os.environ, PATH=f"{self.fakebin}{os.pathsep}{os.environ['PATH']}",
                        DOCKER_LOG=str(self.log), DOCKER_ZUSTAND=str(self.zustand),
                        LOXPANEL_CTL_CONFIGDIR=str(self.configdir), LOXPANEL_CTL_DATADIR=str(self.data))

    def ctl(self, *args: str, **umgebung: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(CTL), *args], env={**self.env, **umgebung},
                              capture_output=True, text=True, timeout=120)

    def ctl_starten(self, *args: str, **umgebung: str) -> subprocess.Popen:
        return subprocess.Popen(["bash", str(CTL), *args], env={**self.env, **umgebung},
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def mv_scheitert(self, muster: str) -> None:
        """mv im Container scheitert fuer jedes Argument, das `muster` enthaelt."""
        echt = shutil.which("mv")
        _ausfuehrbar(self.fakebin / "mv", f'''#!/bin/sh
for a in "$@"; do case "$a" in *"{muster}"*) echo "mv: Testfehler bei $a" >&2; exit 1 ;; esac; done
exec {echt} "$@"
''')

    def container(self) -> str:
        return self.zustand.read_text().strip()

    def aufrufe(self) -> list[tuple[str, str]]:
        """docker-Aufrufe als (Zustand davor, Argumente)."""
        if not self.log.is_file():
            return []
        return [tuple(z.split(" docker ", 1)) for z in self.log.read_text().splitlines()]

    def stand(self, ordner: Path | None = None) -> dict[str, bytes]:
        ordner = ordner or self.conf
        return {str(p.relative_to(ordner)): p.read_bytes() for p in sorted(ordner.rglob("*")) if p.is_file()}

    def archiv(self, name: str, dateien: dict[str, bytes]) -> Path:
        quelle = self.tmp / ("quelle-" + name.replace("/", "_"))
        quelle.mkdir()
        for n, b in dateien.items():
            (quelle / n).write_bytes(b)
        subprocess.run(["tar", "-czf", str(self.backups / name), "."], cwd=quelle, check=True)
        return self.backups / name

    def entpackt(self, archiv: Path) -> dict[str, bytes]:
        ziel = self.tmp / ("entpackt-" + archiv.name)
        ziel.mkdir()
        subprocess.run(["tar", "-xzf", str(archiv), "-C", str(ziel)], check=True)
        return self.stand(ziel)

    def reste(self) -> list[str]:
        """Zwischenstaende, die nach einem Lauf nicht liegen bleiben duerfen."""
        return sorted([p.name for p in self.data.iterdir() if p.name.startswith(".restore.")]
                      + [p.name for p in self.backups.iterdir() if p.name.endswith(".part")])
