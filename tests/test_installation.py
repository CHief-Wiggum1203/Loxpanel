"""Installation ausserhalb von Docker und der App (README, deploy/DEPLOY.md).

- Die Python-Pakete stehen nur in requirements.txt. Dockerfile, .deb, App und
  CI nehmen sie von dort; eine Anleitung, die einzelne Pakete nennt, laesst
  icalendar/python-dateutil (Kalender) und cryptography (Intercom, Audioserver)
  weg.
- Fehlt trotzdem ein optionales Paket, startet der Server, meldet sich gesund
  und nennt es einmal beim Start im Log, statt erst am Kalender, an der
  Intercom oder am Audioserver aufzufallen.
- Die Doku nennt den Vorrang des Miniserver-Zugangs so, wie _ms_zugang() ihn
  hat: ein unter Settings gespeicherter Zugang (loxpanel.cfg) vor LOXPANEL_MS_*.
"""
import json
import logging
import re
import sys

import pytest

from lox import ROOT, W

# Anleitungen, nach denen jemand installiert (nicht Journal/TODO unter docs/)
ANLEITUNGEN = [ROOT / "README.md", *sorted((ROOT / "deploy").glob("*.md")),
               ROOT / "android" / "README.md", ROOT / "loxberry-plugin" / "README.md"]


def test_anleitungen_installieren_aus_requirements():
    falsch = []
    for datei in ANLEITUNGEN:
        for nr, zeile in enumerate(datei.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\bpip3?\s+install\b", zeile) and \
                    not re.search(r"\s-r\s+\S*requirements(-dev)?\.txt\b", zeile):
                falsch.append(f"{datei.relative_to(ROOT)}:{nr}: {zeile.strip()}")
    assert falsch == [], "Paketliste nur aus requirements.txt:\n" + "\n".join(falsch)


def test_anleitungen_ohne_feste_glibc_grenze():
    """Ab welcher glibc pip ein fertiges cryptography bekommt, verschiebt jede
    neue cryptography-Version (46.0.4 hob armv7l von manylinux_2_28 auf 2_31,
    requirements.txt hat keine Obergrenze). Eine Zahl in der Anleitung
    veraltet und laesst Rust weg, wo pip doch selbst baut."""
    falsch = []
    for datei in ANLEITUNGEN:
        for nr, zeile in enumerate(datei.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"glibc\s*\(?[^)\n]*?\)?\s*\d+\.\d+", zeile, re.I):
                falsch.append(f"{datei.relative_to(ROOT)}:{nr}: {zeile.strip()}")
    assert falsch == [], "feste glibc-Version:\n" + "\n".join(falsch)


def _start(monkeypatch) -> None:
    """main() wie beim Start des Servers, nur ohne zu lauschen und ohne das
    Log-Level des Testprozesses umzustellen."""
    monkeypatch.setattr(W, "_logging_einrichten", lambda: logging.INFO)
    monkeypatch.setattr(W.web, "run_app", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["webvisu.py"])
    W.main()


def _paketmeldungen(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.name == W.log.name and "requirements.txt" in r.getMessage()]


@pytest.mark.parametrize("modul, flagge, paket, funktion", [
    ("front_info", "HAVE_ICAL", "icalendar", "Kalender"),
    ("front_info", "HAVE_RRULE", "python-dateutil", "Serientermine"),
    ("loxone_secure", "HAVE_CRYPTO", "cryptography", "Intercom"),
    ("audioserver_auth", "HAVE_CRYPTO", "cryptography", "Audioserver"),
], ids=["icalendar", "dateutil", "crypto-intercom", "crypto-audioserver"])
def test_start_nennt_fehlendes_paket(cfg_ordner, monkeypatch, caplog, modul, flagge, paket, funktion):
    monkeypatch.setattr(sys.modules[modul], flagge, False)
    caplog.set_level(logging.WARNING, logger=W.log.name)
    _start(monkeypatch)
    meldungen = _paketmeldungen(caplog)
    assert len(meldungen) == 1, meldungen
    assert paket in meldungen[0] and funktion in meldungen[0], meldungen[0]


def test_start_ohne_fehlende_pakete_still(cfg_ordner, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger=W.log.name)
    _start(monkeypatch)
    assert _paketmeldungen(caplog) == []


# Wo die Doku sagt, welcher Miniserver-Zugang gilt
VORRANG_STELLEN = ["README.md", "deploy/DEPLOY.md", "deploy/DOCKER.md", "deploy/UNRAID.md",
                   "docker-compose.yml", "unraid/loxpanel.xml", "docs/ARCHITEKTUR.md", "CLAUDE.md"]
# "... unter Settings gespeicherter Zugang (loxpanel.cfg) hat Vorrang vor den Variablen"
DATEI_VOR_UMGEBUNG = re.compile(r"(Settings|loxpanel\.cfg|gespeicherter Zugang)[^.]{0,120}?\bVorrang vor\b[^.]{0,40}?"
                                r"(Variablen|Env|LOXPANEL_MS)")
# "(Env hat Vorrang)" und Verwandte, nur in Zeilen zum Miniserver-Zugang: beim
# Panel-Agenten hat die Env tatsaechlich Vorrang (vor der kiosk.conf)
UMGEBUNG_VOR_DATEI = re.compile(r"\b(Env|Umgebungsvariablen?|Variablen|LOXPANEL_MS_\w*)\)?\s+(hat|haben) Vorrang")


@pytest.mark.parametrize("stelle", VORRANG_STELLEN)
def test_doku_nennt_den_vorrang_wie_der_server(cfg_ordner, monkeypatch, stelle):
    """Aendert sich der Vorrang in _ms_zugang(), scheitert schon die erste
    Pruefung; dann gehoeren diese Stellen mit angepasst."""
    monkeypatch.setenv("LOXPANEL_MS_HOST", "10.0.0.2")
    (cfg_ordner / "loxpanel.cfg").write_text(json.dumps({"miniserver": {"host": "10.0.0.1"}}),
                                             encoding="utf-8")
    assert W._ms_zugang()[0]["host"] == "10.0.0.1", "Server: gespeicherter Zugang vor LOXPANEL_MS_*"

    roh = (ROOT / stelle).read_text(encoding="utf-8")
    text = " ".join(z.strip().lstrip("#").strip() for z in roh.splitlines())
    assert DATEI_VOR_UMGEBUNG.search(text), f"{stelle} nennt den Vorrang des gespeicherten Zugangs nicht"
    falsch = [z.strip() for z in roh.splitlines()
              if UMGEBUNG_VOR_DATEI.search(z) and re.search(r"Miniserver|LOXPANEL_MS", z)]
    assert falsch == [], f"{stelle}: {falsch}"
