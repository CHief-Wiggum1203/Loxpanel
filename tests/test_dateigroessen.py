"""Wache gegen das Zuwachsen der Quelldateien: Keine Datei unter bin/, agent/ und
webfrontend/html/ wird laenger als GRENZE Zeilen. Die Altlasten, die heute
darueber liegen, stehen mit ihrem jetzigen Stand in AUSNAHMEN und duerfen nur
schrumpfen - wer eine Ausnahme braucht, senkt die Zahl, wenn er die Datei
kleiner gemacht hat, und hebt sie nie an. Hintergrund: das Zerlegen der grossen
Dateien (docs/ARCHITEKTUR.md Abschnitt 7.2, Konfigurator in config/*.js, Visu in panel/*.js,
Bausteine in bin/bausteine/)."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ORDNER = ("bin", "agent", "webfrontend/html")
ENDUNGEN = {".py", ".js", ".html", ".css"}
GRENZE = 1500
# Noch zu zerlegen (Zeilenzahl beim Anlegen der Wache, 15.10.2026); nur nach unten aendern
AUSNAHMEN = {
    "bin/webvisu.py": 8100,
}


def _quelldateien():
    for ordner in ORDNER:
        basis = ROOT / ordner
        for f in sorted(basis.rglob("*")):
            if f.is_file() and f.suffix in ENDUNGEN and "__pycache__" not in f.parts:
                yield f


def _zeilen(f: Path) -> int:
    return f.read_text(encoding="utf-8", errors="replace").count("\n")


@pytest.mark.parametrize("datei", [f.relative_to(ROOT).as_posix() for f in _quelldateien()])
def test_datei_nicht_zu_lang(datei):
    zeilen = _zeilen(ROOT / datei)
    grenze = AUSNAHMEN.get(datei, GRENZE)
    assert zeilen <= grenze, (f"{datei} hat {zeilen} Zeilen, erlaubt sind {grenze}: aufteilen statt anbauen "
                              f"(docs/ARCHITEKTUR.md 7.2)")


def test_ausnahmen_gelten_nur_fuer_vorhandene_dateien():
    """Eine Ausnahme fuer eine Datei, die es nicht mehr gibt oder die schon
    unter der Grenze liegt, ist erledigt und kommt weg."""
    for datei, grenze in AUSNAHMEN.items():
        f = ROOT / datei
        assert f.is_file(), f"Ausnahme fuer {datei}, die Datei gibt es nicht mehr"
        assert _zeilen(f) > GRENZE, f"{datei} liegt unter {GRENZE} Zeilen, die Ausnahme ist erledigt"
        assert grenze > GRENZE
