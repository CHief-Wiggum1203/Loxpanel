"""Nachbau der LoxBerry-Umgebung fuer die Skripte in loxberry-plugin/.

Die Skripte laufen echt (bash, sh, tar, gzip, find, mv, flock, cp, perl).
Ersetzt werden nur Befehle, die es im Test nicht gibt oder die dort nichts
anrichten duerfen: sudo, su und docker. Ihre Stellvertreter schreiben
`LoxBerry` und `Installation` zur Laufzeit nach tmp_path und haengen sie vorn
in PATH; im Repo liegen keine. Dasselbe gilt fuer die Perl-Module, die das
Widget braucht (`Widget`).

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

import json
import os
import resource
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlencode

from lox import ROOT

PLUGIN = ROOT / "loxberry-plugin"
CTL = PLUGIN / "bin" / "loxpanel-ctl.sh"
CGI = PLUGIN / "webfrontend" / "htmlauth" / "index.cgi"
WERKZEUGE = ("bash", "sh", "tar", "gzip", "find", "flock", "mktemp", "cp")
FEHLENDE_WERKZEUGE = [w for w in WERKZEUGE if not shutil.which(w)]
PERL = shutil.which("perl")

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

SU = '''#!/bin/sh
# Stellvertreter fuer su -s SHELL BENUTZER -c BEFEHL: BEFEHL ausfuehren.
while [ $# -gt 0 ]; do
  case "$1" in -s) shift 2 ;; -c) exec bash -c "$2" ;; *) shift ;; esac
done
exit 1
'''

# Perl-Module fuer index.cgi. LoxBerry::* gibt es nur auf einem LoxBerry; CGI
# und LWP::UserAgent fehlen oft, JSON ebenso (JSON::PP und HTTP::Tiny sind
# Kernmodule). LWP spricht ueber HTTP::Tiny mit LOXBERRY_TEST_API statt
# localhost:8099; ohne LOXBERRY_TEST_API ist kein Container erreichbar.
# decoded_content liefert Bytes wie LWP bei application/json (Zeichensatz
# dekodiert LWP nur bei text/* und XML).
PERL_MODULE = {
    "CGI.pm": r'''package CGI;
use strict;
sub new {
    my ($class) = @_;
    my $daten = $ENV{QUERY_STRING} // '';
    if (($ENV{REQUEST_METHOD} // '') eq 'POST') { local $/; my $b = <STDIN>; $daten .= '&' . ($b // ''); }
    my %p;
    for my $paar (grep { length } split /&/, $daten) {
        my ($k, $v) = map { my $s = $_ // ''; $s =~ tr/+/ /; $s =~ s/%([0-9A-Fa-f]{2})/chr(hex($1))/ge; $s }
                      split /=/, $paar, 2;
        $p{$k} = $v;
    }
    return bless { p => \%p }, $class;
}
sub param { my ($self, $k) = @_; return $self->{p}{$k}; }
1;
''',
    "LWP/UserAgent.pm": r'''package LWP::UserAgent;
use strict;
use HTTP::Tiny;
sub new { my ($class, %o) = @_; return bless { timeout => $o{timeout} // 180 }, $class; }
sub get { my ($self, $url) = @_; return $self->_anfrage('GET', $url); }
sub post { my ($self, $url, %h) = @_; return $self->_anfrage('POST', $url, %h); }
sub _anfrage {
    my ($self, $methode, $url, %h) = @_;
    my $ziel = $ENV{LOXBERRY_TEST_API};
    return LWP::UserAgent::Antwort->new(500, "Can't connect to localhost:8099") unless $ziel;
    $url =~ s{^http://localhost:8099}{$ziel};
    my $inhalt = delete $h{Content};
    my $r = HTTP::Tiny->new(timeout => $self->{timeout})->request($methode, $url,
        { headers => \%h, defined $inhalt ? (content => $inhalt) : () });
    return LWP::UserAgent::Antwort->new($r->{status} == 599 ? 500 : $r->{status}, $r->{content});
}
package LWP::UserAgent::Antwort;
sub new { my ($class, $code, $inhalt) = @_; return bless { code => $code, inhalt => $inhalt // '' }, $class; }
sub code { return $_[0]{code}; }
sub is_success { return $_[0]{code} >= 200 && $_[0]{code} < 300; }
sub content { return $_[0]{inhalt}; }
sub decoded_content { return $_[0]{inhalt}; }
1;
''',
    "JSON.pm": r'''package JSON;
use strict;
use JSON::PP ();
use Exporter 'import';
our @EXPORT_OK = qw(encode_json decode_json);
sub encode_json { return JSON::PP::encode_json($_[0]); }
sub decode_json { return JSON::PP::decode_json($_[0]); }
sub true { return JSON::PP::true(); }
sub false { return JSON::PP::false(); }
1;
''',
    "LoxBerry/System.pm": r'''package LoxBerry::System;
use strict;
use JSON::PP ();
sub pluginversion { return '9.9.9'; }
sub get_localip { return '127.0.0.1'; }
sub get_miniservers {
    my $j = $ENV{LOXBERRY_TEST_MINISERVER};
    return $j ? (1 => JSON::PP::decode_json($j)) : ();
}
1;
''',
    "LoxBerry/Web.pm": r'''package LoxBerry::Web;
use strict;
sub lbheader { print "Content-Type: text/html; charset=utf-8\n\n<!-- lbheader -->\n"; }
sub lbfooter { print "<!-- lbfooter -->\n"; }
1;
''',
}

# Platzhalter wie replaceenv() in LoxBerrys sbin/plugininstall.pl
def _ersetzungen(home: Path) -> tuple[tuple[str, str], ...]:
    pf = "loxpanel"
    return (("REPLACELBHOMEDIR", str(home)), ("REPLACELBPPLUGINDIR", pf),
            ("REPLACELBPHTMLAUTHDIR", f"{home}/webfrontend/htmlauth/plugins/{pf}"),
            ("REPLACELBPHTMLDIR", f"{home}/webfrontend/html/plugins/{pf}"),
            ("REPLACELBPTEMPLATEDIR", f"{home}/templates/plugins/{pf}"),
            ("REPLACELBPDATADIR", f"{home}/data/plugins/{pf}"),
            ("REPLACELBPLOGDIR", f"{home}/log/plugins/{pf}"),
            ("REPLACELBPCONFIGDIR", f"{home}/config/plugins/{pf}"),
            ("REPLACELBPBINDIR", f"{home}/bin/plugins/{pf}"))


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


class Installation:
    """Ein LoxBerry (LBHOMEDIR) in tmp_path, auf dem sbin/plugininstall.pl das
    Plugin aus dem Repo einspielt, als Erstinstallation oder als Update:
    Platzhalter ersetzen (replaceenv), preroot, beim Update preupgrade und
    purge_installation (dieselben Ordner wie dort), Dateien kopieren, beim
    Update postupgrade, dann postroot. Die Skripte bekommen dieselben
    Argumente; endet preroot mit mehr als 1, bricht der Installer ab (fail()).
    LOXPANEL_UPGRADE_TMP lenkt die Zwischenablage (sonst /tmp) nach tmp_path.
    Der Test laeuft als ein Benutzer: chown auf loxberry scheitert still wie
    auf einem Rechner ohne diesen Benutzer, Besitzrechte prueft er nur als root."""

    PURGE = ("config/plugins", "bin/plugins", "data/plugins", "templates/plugins",
             "webfrontend/htmlauth/plugins", "webfrontend/html/plugins")

    def __init__(self, tmp: Path, container: str = "laeuft") -> None:
        self.tmp = tmp
        self.home = tmp / "lb"
        self.data = self.home / "data" / "plugins" / "loxpanel"
        self.conf = self.data / "config"
        self.backups = self.data / "backups"
        self.bindir = self.home / "bin" / "plugins" / "loxpanel"
        self.configdir = self.home / "config" / "plugins" / "loxpanel"
        self.htmlauth = self.home / "webfrontend" / "htmlauth" / "plugins" / "loxpanel"
        self.zwischen = tmp / "zwischen"
        self.zwischen.mkdir()
        fakebin = tmp / "fakebin"
        fakebin.mkdir()
        for name, text in (("sudo", SUDO), ("docker", DOCKER), ("su", SU)):
            _ausfuehrbar(fakebin / name, text)
        self.log = tmp / "docker.log"
        self.zustand = tmp / "container"
        self.zustand.write_text(container + "\n")
        self.env = dict(os.environ, PATH=f"{fakebin}{os.pathsep}{os.environ['PATH']}",
                        DOCKER_LOG=str(self.log), DOCKER_ZUSTAND=str(self.zustand),
                        LOXPANEL_UPGRADE_TMP=str(self.zwischen))
        # preroot legt sonst echte apt-Quellen fuer Docker an
        assert shutil.which("docker", path=self.env["PATH"]) == str(fakebin / "docker")
        self._pakete = 0

    def paket(self) -> Path:
        """Das Plugin-ZIP, entpackt und mit ersetzten Platzhaltern."""
        self._pakete += 1
        ziel = self.tmp / f"paket{self._pakete}"
        shutil.copytree(PLUGIN, ziel)
        for f in ziel.rglob("*"):
            if f.is_file():
                try:
                    text = f.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                for alt, neu in _ersetzungen(self.home):
                    text = text.replace(alt, neu)
                f.write_text(text, encoding="utf-8")
        return ziel

    def _skript(self, paket: Path, name: str, dateigroesse: int | None = None) -> subprocess.CompletedProcess:
        def grenze():
            if dateigroesse:
                resource.setrlimit(resource.RLIMIT_FSIZE, (dateigroesse, dateigroesse))
        s = paket / name
        s.chmod(0o755)
        return subprocess.run([str(s), "tmpdatei", "loxpanel", "loxpanel", "9.9.9", str(self.home), str(paket)],
                              cwd=paket, env=self.env, capture_output=True, text=True, timeout=120,
                              preexec_fn=grenze)

    def _kopieren(self, paket: Path) -> None:
        for quelle, ziel in (("bin", self.bindir), ("config", self.configdir),
                             ("webfrontend/htmlauth", self.htmlauth)):
            shutil.copytree(paket / quelle, ziel, dirs_exist_ok=True)
        self.data.mkdir(parents=True, exist_ok=True)
        for f in (*self.bindir.iterdir(), self.htmlauth / "index.cgi"):
            f.chmod(0o755)

    def installieren(self, update: bool = True, dateigroesse: int | None = None,
                     abbruch_nach_loeschen: bool = False) -> dict:
        """Ablauf von plugininstall.pl -> {Skript: CompletedProcess}.
        dateigroesse begrenzt in preroot die Dateigroesse (wie ein voller
        Datentraeger an der Zwischenablage); abbruch_nach_loeschen endet wie
        ein fail() des Installers zwischen purge und postroot."""
        paket = self.paket()
        lauf = {"preroot": self._skript(paket, "preroot.sh", dateigroesse)}
        if lauf["preroot"].returncode > 1:
            return lauf
        if update:
            lauf["preupgrade"] = self._skript(paket, "preupgrade.sh")
            for d in self.PURGE:
                shutil.rmtree(self.home / d / "loxpanel", ignore_errors=True)
            if abbruch_nach_loeschen:
                return lauf
        self._kopieren(paket)
        if update:
            lauf["postupgrade"] = self._skript(paket, "postupgrade.sh")
        lauf["postroot"] = self._skript(paket, "postroot.sh")
        return lauf

    def ctl(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(self.bindir / "loxpanel-ctl.sh"), *args], env=self.env,
                              capture_output=True, text=True, timeout=120)

    def container(self) -> str:
        return self.zustand.read_text().strip()


class Widget:
    """index.cgi mit perl ausfuehren, wie Apache ein CGI aufruft (POST-Felder
    auf stdin). Die Perl-Module aus PERL_MODULE liegen in tmp_path.
    api: Adresse des LoxPanel-Servers (sonst ist kein Container erreichbar),
    miniserver: Miniserver aus der LoxBerry-Konfiguration (get_miniservers)."""

    def __init__(self, tmp: Path, skript: Path = CGI) -> None:
        self.skript = skript
        self.module = tmp / "perl5"
        for name, text in PERL_MODULE.items():
            (self.module / name).parent.mkdir(parents=True, exist_ok=True)
            (self.module / name).write_text(text, encoding="utf-8")

    def befehl(self, felder: dict | None = None, api: str | None = None,
               miniserver: dict | None = None) -> dict:
        """Argumente fuer subprocess.run (auch aus einem Thread heraus)."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("LOXBERRY_TEST_")}
        rumpf = urlencode(felder or {})
        env.update(REQUEST_METHOD="POST" if felder else "GET", QUERY_STRING="",
                   CONTENT_TYPE="application/x-www-form-urlencoded", CONTENT_LENGTH=str(len(rumpf)))
        if api:
            env["LOXBERRY_TEST_API"] = api
        if miniserver is not None:
            env["LOXBERRY_TEST_MINISERVER"] = json.dumps(miniserver)
        return {"args": [PERL, "-I", str(self.module), str(self.skript)], "env": env, "input": rumpf,
                "capture_output": True, "text": True, "timeout": 60}

    def aufruf(self, felder: dict | None = None, api: str | None = None,
               miniserver: dict | None = None) -> str:
        r = subprocess.run(**self.befehl(felder, api, miniserver))
        assert r.returncode == 0, r.stderr
        return r.stdout
