"""LoxBerry: Sichern und Wiederherstellen der Konfiguration (loxpanel-ctl.sh
backup/restore), das echte Skript gegen den Nachbau aus loxberry.py.

Wiederherstellen tauscht config/ erst, wenn das Backup vollstaendig entpackt,
als LoxPanel-Konfiguration erkannt und der Ist-Stand gesichert ist; waehrend
des Tauschs steht der Container. Ein Archiv entsteht erst unter .part und
heisst erst nach dem Zuruecklesen so, wie das Widget es anbietet. Zwei Laeufe
gleichzeitig verhindert eine Sperre."""
import fcntl
import os
import re
import subprocess

import pytest

from loxberry import FEHLENDE_WERKZEUGE, LoxBerry

pytestmark = pytest.mark.skipif(bool(FEHLENDE_WERKZEUGE), reason=f"es fehlen {FEHLENDE_WERKZEUGE}")

# Muster aus index.cgi: Liste der Sicherungen und Freigabe fuer restore
LISTE = re.compile(r"^loxpanel-config-.*\.tar\.gz$")
FREIGABE = re.compile(r"^loxpanel-config-[\w.\-]+\.tar\.gz$")

AKTUELL = {"panels.json": b'{"panels":{"wohnen":{"title":"AKTUELL"}}}\n',
           "panels.json.bak": b'{"panels":{}}\n',
           "theme.json": b'{"ui":{"lang":"de"}}\n',
           "loxpanel.cfg": b'{"miniserver":{"host":"10.0.0.5"}}\n',
           ".versteckt": b"Punktdatei\n"}
ALT = {"panels.json": b'{"panels":{"kueche":{"title":"ALT"}}}\n',
       "theme.json": b"{}\n", "loxpanel.cfg": b'{"miniserver":{"host":"10.0.0.6"}}\n'}
GROSS = 300_000          # Bytes Zufallsdaten, deutlich ueber ULIMIT
ULIMIT = "64"            # ulimit -f in bash: 64 KiB -> tar/gzip brechen ab wie bei vollem Datentraeger


@pytest.fixture
def lb(tmp_path):
    lb = LoxBerry(tmp_path)
    for n, b in AKTUELL.items():
        (lb.conf / n).write_bytes(b)
    return lb


def _gueltig(pfad) -> bool:
    return subprocess.run(["tar", "-tzf", str(pfad)], capture_output=True).returncode == 0


def _angeboten(lb) -> list:
    return sorted(p.name for p in lb.backups.iterdir() if LISTE.match(p.name) or FREIGABE.match(p.name))


def _unveraendert(lb, r, stand=AKTUELL):
    assert r.returncode != 0, r.stdout + r.stderr
    assert lb.stand() == stand, "config/ darf sich nicht aendern"
    assert lb.reste() == []
    assert lb.container() == "laeuft", "der Container laeuft danach wie vorher"


def test_restore_gueltig_tauscht_bei_angehaltenem_container(lb):
    name = lb.archiv("loxpanel-config-20260101-000000.tar.gz", ALT).name
    r = lb.ctl("restore", name)
    assert r.returncode == 0, r.stdout + r.stderr
    assert lb.stand() == ALT, "Inhalt genau wie im Archiv, auch die Punktdatei ist weg"
    (vor,) = [p for p in lb.backups.iterdir() if p.name.endswith("-vor-restore.tar.gz")]
    assert FREIGABE.match(vor.name) and lb.entpackt(vor) == AKTUELL, "Ist-Stand samt Punktdatei gesichert"
    assert lb.reste() == []
    assert lb.container() == "laeuft" and "Panel neu gestartet." in r.stdout
    aufrufe = lb.aufrufe()
    tausch = [z for z, a in aufrufe if "mv -t" in a]
    assert tausch and set(tausch) == {"gestoppt"}, aufrufe
    vorher = [z for z, a in aufrufe if a.startswith("run") and "tar -czf" in a]
    assert vorher == ["gestoppt"], "Vorher-Sicherung erst, wenn der Server nichts mehr schreibt"


def test_restore_ohne_konfiguration_braucht_keine_vorher_sicherung(tmp_path):
    lb = LoxBerry(tmp_path)
    name = lb.archiv("loxpanel-config-20260101-000000.tar.gz", ALT).name
    r = lb.ctl("restore", name)
    assert r.returncode == 0, r.stdout + r.stderr
    assert lb.stand() == ALT
    assert [p.name for p in lb.backups.iterdir()] == [name]


def test_restore_kaputtes_archiv_laesst_konfiguration_stehen(lb):
    name = "loxpanel-config-20260101-000000.tar.gz"
    (lb.backups / name).write_bytes(os.urandom(4096))
    _unveraendert(lb, lb.ctl("restore", name))
    assert not any(a.startswith(("stop", "start", "restart")) for _, a in lb.aufrufe())


def test_restore_abgeschnittenes_archiv_entpackt_nichts(lb):
    p = lb.archiv("loxpanel-config-20260102-000000.tar.gz", {"a-gross.json": os.urandom(GROSS), **ALT})
    p.write_bytes(p.read_bytes()[: p.stat().st_size // 2])
    _unveraendert(lb, lb.ctl("restore", p.name))


@pytest.mark.parametrize("inhalt", [{}, {"notiz.txt": b"fremd\n"}], ids=["leer", "fremd"])
def test_restore_ohne_loxpanel_konfiguration_wird_abgelehnt(lb, inhalt):
    """Ein leeres Archiv (heute: backup bei leerem config/) oder eines ohne
    loxpanel.cfg, panels.json und theme.json loeschte sonst alles."""
    name = lb.archiv("loxpanel-config-20260104-000000.tar.gz", inhalt).name
    _unveraendert(lb, lb.ctl("restore", name))


def test_restore_bricht_ab_wenn_vorher_sicherung_scheitert(lb):
    (lb.conf / "panels.json.bak").write_bytes(os.urandom(GROSS))
    stand = lb.stand()
    name = lb.archiv("loxpanel-config-20260103-000000.tar.gz", ALT).name
    _unveraendert(lb, lb.ctl("restore", name, DOCKER_ULIMIT_F=ULIMIT), stand)
    assert _angeboten(lb) == [name], "kein halbes vor-restore-Archiv"


def test_restore_stellt_zurueck_wenn_tausch_scheitert(lb):
    """Verschieben ins config/ scheitert (find -exec mv meldet das sonst nicht
    weiter): der Ist-Stand kommt zurueck, das Panel laeuft wieder."""
    name = lb.archiv("loxpanel-config-20260105-000000.tar.gz", ALT).name
    lb.mv_scheitert("/neu/")
    r = lb.ctl("restore", name)
    assert r.returncode != 0, r.stdout
    assert lb.stand() == AKTUELL
    assert lb.container() == "laeuft"
    (lb.fakebin / "mv").unlink()
    r = lb.ctl("restore", name)                      # naechster Lauf raeumt den Rest weg
    assert r.returncode == 0, r.stdout + r.stderr
    assert lb.stand() == ALT and lb.reste() == []
    vor = [p for p in lb.backups.iterdir() if p.name.endswith("-vor-restore.tar.gz")]
    assert len(vor) == 2 and all(lb.entpackt(p) == AKTUELL for p in vor), "keine Vorher-Sicherung ersetzt"


def test_restore_name_wird_nicht_ausgefuehrt(lb):
    """Der Name steht unquotiert in keinem Befehl, der als root laeuft."""
    name = lb.archiv("loxpanel-config-1;touch GEKAPERT;.tar.gz", ALT).name
    r = lb.ctl("restore", name)
    assert r.returncode == 0, r.stdout + r.stderr
    assert lb.stand() == ALT
    assert not list(lb.tmp.rglob("GEKAPERT"))


def test_restore_wartet_nicht_auf_laufende_sicherung(lb):
    name = lb.archiv("loxpanel-config-20260106-000000.tar.gz", ALT).name
    with open(lb.data / ".loxpanel-ctl.lock", "w") as sperre:
        fcntl.flock(sperre, fcntl.LOCK_EX)
        r = lb.ctl("restore", name)
        b = lb.ctl("backup")
    _unveraendert(lb, r)
    assert b.returncode != 0 and _angeboten(lb) == [name]
    assert "läuft schon" in r.stdout and lb.aufrufe() == []


def test_zwei_wiederherstellungen_gleichzeitig(lb):
    name = lb.archiv("loxpanel-config-20260107-000000.tar.gz", ALT).name
    laeufe = [lb.ctl_starten("restore", name, DOCKER_VERZOEGERUNG="0.2") for _ in range(2)]
    ergebnisse = [(p.wait(timeout=120), p.stdout.read()) for p in laeufe]
    assert any(rc == 0 for rc, _ in ergebnisse), ergebnisse
    for rc, aus in ergebnisse:
        assert rc == 0 or "läuft schon" in aus, aus
    assert lb.stand() == ALT and lb.reste() == []
    assert all(_gueltig(lb.backups / n) for n in _angeboten(lb))


def test_backup_gueltig(lb):
    r = lb.ctl("backup")
    assert r.returncode == 0, r.stdout + r.stderr
    (a,) = _angeboten(lb)
    assert lb.entpackt(lb.backups / a) == AKTUELL and lb.reste() == []


def test_backup_kurz_hintereinander_ersetzt_keins(lb):
    """Archivnamen zaehlen Sekunden; in derselben Sekunde kommt eine Nummer dazu."""
    for _ in range(3):
        r = lb.ctl("backup")
        assert r.returncode == 0, r.stdout + r.stderr
    angeboten = _angeboten(lb)
    assert len(angeboten) == 3 and all(lb.entpackt(lb.backups / a) == AKTUELL for a in angeboten)


def test_backup_fehlschlag_hinterlaesst_kein_angebotenes_archiv(lb):
    (lb.conf / "panels.json.bak").write_bytes(os.urandom(GROSS))
    r = lb.ctl("backup", DOCKER_ULIMIT_F=ULIMIT)
    assert r.returncode != 0
    assert _angeboten(lb) == [] and lb.reste() == []


@pytest.mark.parametrize("leer", [True, False], ids=["leer", "fehlt"])
def test_backup_ohne_konfiguration(tmp_path, leer):
    lb = LoxBerry(tmp_path)
    if not leer:
        lb.conf.rmdir()
    r = lb.ctl("backup")
    assert r.returncode != 0 and "nichts zu sichern" in r.stdout
    assert _angeboten(lb) == []
