"""LoxBerry: Ein Plugin-Update nimmt die Konfiguration UND die Sicherungen aus
dem Widget mit (preroot.sh/postroot.sh). LoxBerry loescht zwischen beiden den
ganzen Datenordner; Installation aus loxberry.py spielt den Ablauf von
plugininstall.pl mit den echten Skripten nach.

Laesst sich die Konfiguration nicht sichern, bricht preroot ab (exit 2), bevor
LoxBerry etwas loescht. Fehlen nur die Archive, warnt es (exit 1) und das
Update laeuft weiter. Wie viele Sicherungen bleiben, steht nur in
loxpanel-ctl.sh (KEEP); das Widget liest die Zahl dort."""
import os

import pytest

from loxberry import FEHLENDE_WERKZEUGE, PERL, Installation, Widget

pytestmark = pytest.mark.skipif(bool(FEHLENDE_WERKZEUGE), reason=f"es fehlen {FEHLENDE_WERKZEUGE}")

KONFIG = {"panels.json": b'{"panels":{"flur":{"title":"Flur"}}}\n',
          "theme.json": b'{"ui":{"lang":"de"}}\n',
          "loxpanel.cfg": b'{"miniserver":{"host":"192.0.2.10"}}\n'}
GROSS = 300_000            # Bytes, deutlich ueber GRENZE
GRENZE = 64 * 1024         # Dateigroesse in preroot: GROSS passt nicht in die Zwischenablage
ERFOLG = {"preroot": 0, "preupgrade": 0, "postupgrade": 0, "postroot": 0}


@pytest.fixture
def lb(tmp_path):
    """Installiertes Plugin mit Konfiguration, Container laeuft."""
    lb = Installation(tmp_path)
    lauf = lb.installieren(update=False)
    assert {k: r.returncode for k, r in lauf.items()} == {"preroot": 0, "postroot": 0}, lauf
    lb.conf.mkdir()                                   # legt sonst der Bind-Mount beim ersten Start an
    for n, b in KONFIG.items():
        (lb.conf / n).write_bytes(b)
    return lb


def _stand(ordner) -> dict:
    if not ordner.is_dir():
        return {}
    return {str(p.relative_to(ordner)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(ordner.rglob("*")) if p.is_file()}


def _konfig(lb) -> dict:
    return {n: b for n, (b, _) in _stand(lb.conf).items()}


def _rc(lauf) -> dict:
    return {k: r.returncode for k, r in lauf.items()}


def _ausgabe(lauf) -> str:
    return "\n".join(f"[{k}] rc={r.returncode}\n{r.stdout}{r.stderr}" for k, r in lauf.items())


def test_update_nimmt_konfiguration_und_sicherungen_mit(lb):
    r = lb.ctl("backup")
    assert r.returncode == 0, r.stdout + r.stderr
    (name,) = [p.name for p in lb.backups.iterdir() if p.name.endswith(".tar.gz")]
    r = lb.ctl("restore", name)                       # legt ein zweites, ...-vor-restore an
    assert r.returncode == 0, r.stdout + r.stderr
    archive = {n: v for n, v in _stand(lb.backups).items() if n.endswith(".tar.gz")}
    assert len(archive) == 2
    if os.geteuid() == 0:                             # wie im Betrieb: Ordner gehoert loxberry, Archive root
        os.chown(lb.backups, 65534, 65534)
    ordner = lb.backups.stat()

    lauf = lb.installieren()
    assert _rc(lauf) == ERFOLG, _ausgabe(lauf)
    assert _konfig(lb) == KONFIG
    assert {n: v for n, v in _stand(lb.backups).items() if n.endswith(".tar.gz")} == archive, \
        "dieselben Archive mit Inhalt und Datum (das Widget zeigt die mtime)"
    nachher = lb.backups.stat()
    assert (nachher.st_uid, nachher.st_mode) == (ordner.st_uid, ordner.st_mode), \
        "backups/ bleibt beim Widget-Benutzer (Loeschen, Rotation)"
    assert list(lb.zwischen.iterdir()) == []
    assert lb.container() == "laeuft"
    r = lb.ctl("restore", name)                       # und sie lassen sich weiter einspielen
    assert r.returncode == 0 and "Konfiguration wiederhergestellt." in r.stdout, r.stdout + r.stderr


def test_erstinstallation_ohne_datenordner(tmp_path):
    lb = Installation(tmp_path, container="fehlt")
    lauf = lb.installieren(update=False)
    assert _rc(lauf) == {"preroot": 0, "postroot": 0}, _ausgabe(lauf)
    assert not lb.backups.exists() and list(lb.zwischen.iterdir()) == []
    assert lb.container() == "laeuft"


def test_archive_scheitern_update_laeuft_weiter(lb):
    """Die Archive passen nicht in die Zwischenablage: deutliche Warnung,
    exit 1 (LoxBerry meldet es), das Update laeuft weiter, die Konfiguration
    kommt mit, keine halbe Kopie bleibt liegen."""
    lb.backups.mkdir()
    (lb.backups / "loxpanel-config-20260101-000000.tar.gz").write_bytes(os.urandom(GROSS))
    lauf = lb.installieren(dateigroesse=GRENZE)
    assert _rc(lauf) == {**ERFOLG, "preroot": 1}, _ausgabe(lauf)
    assert "<WARNING>" in lauf["preroot"].stdout
    assert _konfig(lb) == KONFIG
    assert list(lb.zwischen.iterdir()) == []
    assert lb.container() == "laeuft"


def test_konfiguration_scheitert_update_bricht_vor_dem_loeschen_ab(lb):
    r = lb.ctl("backup")
    assert r.returncode == 0, r.stdout + r.stderr
    (lb.conf / "panels.json.bak").write_bytes(os.urandom(GROSS))
    vorher = _stand(lb.data)
    lauf = lb.installieren(dateigroesse=GRENZE)
    assert _rc(lauf) == {"preroot": 2}, _ausgabe(lauf)
    assert "<FAIL>" in lauf["preroot"].stdout
    assert _stand(lb.data) == vorher, "LoxBerry bricht ab, bevor es loescht"
    assert list(lb.zwischen.iterdir()) == [], "keine Zwischenkopie, die ein spaeteres Update zurueckspielte"


def test_abgebrochenes_update_naechstes_holt_alles_zurueck(lb):
    r = lb.ctl("backup")
    assert r.returncode == 0, r.stdout + r.stderr
    archive = _stand(lb.backups)
    lauf = lb.installieren(abbruch_nach_loeschen=True)
    assert _rc(lauf) == {"preroot": 0, "preupgrade": 0}, _ausgabe(lauf)
    assert not lb.data.exists()
    lauf = lb.installieren()
    assert _rc(lauf) == ERFOLG, _ausgabe(lauf)
    assert "abgebrochenen Update" in lauf["preroot"].stdout
    assert _konfig(lb) == KONFIG and _stand(lb.backups) == archive
    assert list(lb.zwischen.iterdir()) == []


def test_alte_zwischenkopie_taucht_nicht_wieder_auf(lb):
    """Alle Sicherungen geloescht, aber eine Kopie eines frueheren, abgebrochenen
    Updates liegt noch: sie gehoert nicht in den heutigen Stand."""
    alt = lb.zwischen / "loxpanel-upgrade-archive"
    alt.mkdir()
    (alt / "loxpanel-config-20200101-000000.tar.gz").write_bytes(b"alt")
    lauf = lb.installieren()
    assert _rc(lauf) == ERFOLG, _ausgabe(lauf)
    assert _stand(lb.backups) == {}
    assert list(lb.zwischen.iterdir()) == []


@pytest.mark.skipif(not PERL, reason="braucht perl")
def test_widget_nennt_keep_aus_dem_steuerskript(lb, tmp_path):
    ctl = lb.bindir / "loxpanel-ctl.sh"
    text = ctl.read_text(encoding="utf-8")
    assert "\nKEEP=20\n" in text
    ctl.write_text(text.replace("\nKEEP=20\n", "\nKEEP=3\n"), encoding="utf-8")
    lb.backups.mkdir()
    for i in range(5):
        p = lb.backups / f"loxpanel-config-2026010{i}-000000.tar.gz"
        p.write_bytes(b"x")
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
    r = lb.ctl("backup")
    assert r.returncode == 0, r.stdout + r.stderr
    assert lb.ctl("keep").stdout.strip() == "3"
    assert len(list(lb.backups.glob("loxpanel-config-*.tar.gz"))) == 3
    html = Widget(tmp_path, lb.htmlauth / "index.cgi").aufruf()
    assert "Behalten werden die letzten 3." in html
    assert "Plugin-Updates nehmen diese Sicherungen mit" in html
