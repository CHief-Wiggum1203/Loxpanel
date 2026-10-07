"""LoxBerry: Der Container bekommt die Zeitzone des LoxBerry (loxpanel-ctl.sh
start). Der Server rechnet Termine, Heute/Morgen, Nachtmodus, Statistik und
Wecker in der Ortszeit des Prozesses; ohne Zeitzone lief er in UTC.

start legt neben die Compose-Datei eine Override-Datei: /etc/localtime des
LoxBerry nur lesend an einen eigenen Pfad im Container, dazu TZ=":<pfad>",
keine fest eingetragene Zone. Nur wenn die Datei da ist: ein toter Symlink
verhinderte sonst den Start, eine fehlende Datei legte Docker am LoxBerry als
Verzeichnis an. Gegenueber steht der Nachbau aus loxberry.py."""
import importlib.resources
import os
import shutil
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

import front_info as F
from loxberry import FEHLENDE_WERKZEUGE, LoxBerry

pytestmark = pytest.mark.skipif(bool(FEHLENDE_WERKZEUGE), reason=f"es fehlen {FEHLENDE_WERKZEUGE}")

PROBE_ZONE = "Europe/Vienna"     # Testdaten: steht fuer die Zone, die am LoxBerry eingestellt ist
OVERRIDE = "docker-compose.zeitzone.yml"


def _zonendatei() -> Path | None:
    system = Path("/usr/share/zoneinfo") / PROBE_ZONE
    if system.is_file():
        return system
    try:
        paket = importlib.resources.files("tzdata").joinpath("zoneinfo", *PROBE_ZONE.split("/"))
    except ModuleNotFoundError:
        return None
    return Path(str(paket)) if paket.is_file() else None


@pytest.fixture
def lb(tmp_path):
    return LoxBerry(tmp_path, container="fehlt")


@pytest.fixture
def localtime(tmp_path):
    """/etc/localtime wie am LoxBerry: Symlink auf die Zonendatei."""
    quelle = _zonendatei()
    if quelle is None:
        pytest.skip("keine Zonendatei (tzdata) vorhanden")
    zone = tmp_path / "zoneinfo" / PROBE_ZONE
    zone.parent.mkdir(parents=True)
    shutil.copy(quelle, zone)
    link = tmp_path / "etc" / "localtime"
    link.parent.mkdir()
    link.symlink_to(zone)
    return link


def _compose(lb) -> list[str]:
    return [a for _, a in lb.aufrufe() if a.startswith("compose")]


def test_start_reicht_zeitzone_des_loxberry_durch(lb, localtime):
    r = lb.ctl("start", LOXPANEL_CTL_LOCALTIME=str(localtime))
    assert r.returncode == 0, r.stdout + r.stderr
    override = lb.configdir / OVERRIDE
    dateien = f"-f {lb.configdir / 'docker-compose.yml'} -f {override} "
    aufrufe = _compose(lb)
    assert len(aufrufe) == 2 and all(a.startswith(f"compose {dateien}") for a in aufrufe), aufrufe
    dienst = yaml.safe_load(override.read_text(encoding="utf-8"))["services"]["loxpanel"]
    tz = dienst["environment"]["TZ"]
    assert tz.startswith(":"), f"keine fest eingetragene Zone, sondern die Datei: {tz!r}"
    ziel = tz[1:]
    assert dienst["volumes"] == [f"{localtime}:{ziel}:ro"]
    # /etc/localtime ist im Image ein Symlink auf Etc/UTC: Docker folgte ihm und
    # ueberschriebe die UTC-Zone selbst. /etc/timezone liest weder glibc noch Python.
    assert ziel not in ("/etc/localtime", "/etc/timezone")
    basis = yaml.safe_load((lb.configdir / "docker-compose.yml").read_text(encoding="utf-8"))["services"]["loxpanel"]
    assert all(v.split(":")[1] != ziel for v in basis["volumes"])
    assert lb.container() == "laeuft"


@pytest.mark.parametrize("art", ["fehlt", "toter-symlink"])
def test_start_ohne_zeitzonendatei_startet_in_utc(lb, tmp_path, art):
    localtime = tmp_path / "etc" / "localtime"
    localtime.parent.mkdir()
    if art == "toter-symlink":
        localtime.symlink_to(tmp_path / "zoneinfo" / "gibt-es-nicht")
    (lb.configdir / OVERRIDE).write_text("von einem frueheren Start\n")
    r = lb.ctl("start", LOXPANEL_CTL_LOCALTIME=str(localtime))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "UTC" in r.stdout, "warnt, dass die Zeitzone fehlt"
    assert not (lb.configdir / OVERRIDE).exists(), "kein Mount auf eine Datei, die es nicht gibt"
    assert all(f" -f {lb.configdir / OVERRIDE}" not in a for a in _compose(lb))
    assert localtime.is_symlink() if art == "toter-symlink" else not localtime.exists()
    assert lb.container() == "laeuft"


@pytest.fixture
def ortszeit():
    """TZ fuer diesen Prozess setzen; danach wieder wie vorher (auch tzset)."""
    vorher = os.environ.get("TZ")

    def setzen(wert):
        os.environ["TZ"] = wert
        time.tzset()
    yield setzen
    if vorher is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = vorher
    time.tzset()


def test_termin_in_der_zone_des_loxberry(lb, localtime, ortszeit):
    """Was der Server im Container sieht: TZ aus der Override-Datei, am Ziel
    die Datei des LoxBerry. Ein Termin um 10:00Z steht in dessen Ortszeit."""
    r = lb.ctl("start", LOXPANEL_CTL_LOCALTIME=str(localtime))
    assert r.returncode == 0, r.stdout + r.stderr
    dienst = yaml.safe_load((lb.configdir / OVERRIDE).read_text(encoding="utf-8"))["services"]["loxpanel"]
    quelle, ziel, _ = dienst["volumes"][0].split(":")
    assert dienst["environment"]["TZ"] == f":{ziel}"
    ortszeit(f":{quelle}")                  # der Bind-Mount zeigt am Ziel genau diese Datei
    morgen = date.today() + timedelta(days=1)
    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//t//\r\nBEGIN:VEVENT\r\nUID:r\r\n"
           f"DTSTART:{morgen:%Y%m%d}T100000Z\r\nDTEND:{morgen:%Y%m%d}T110000Z\r\n"
           "SUMMARY:Arzt\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n").encode()
    soll = datetime(morgen.year, morgen.month, morgen.day, 10, tzinfo=timezone.utc).astimezone(ZoneInfo(PROBE_ZONE))
    assert [(e["day"], e["time"]) for e in F._parse_events(ics, 7)] == [("Morgen", f"{soll.hour}:{soll.minute:02d}")]
