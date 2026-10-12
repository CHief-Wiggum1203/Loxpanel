"""Was aus config/ in die Android-App kommt (Gradle-Task syncLoxpanelAssets in
android/app/build.gradle.kts): nur die Vorlagen aus dem Repo. Was der Server
zur Laufzeit dort anlegt - loxpanel.cfg mit dem Miniserver-Zugang, Ansichten,
Farben und ihre Sicherungen *.bak - darf nie in eine APK, auch nicht bei einem
lokalen Build aus einem Ordner, in dem der Server schon lief. Darum eine Liste
dessen, was hinein darf (include), statt einer, was draussen bleibt: frueher
schloss exclude() nur drei Namen aus, loxpanel.cfg.bak mit den Kennwoertern
waere mitgekommen.

Gelesen wird die echte Gradle-Datei; die Muster gelten wie bei Gradle fuer
Dateien direkt im Ordner (fnmatch, ein * ueberquert keinen /)."""
from __future__ import annotations

import fnmatch
import re
import subprocess

import pytest

from lox import ROOT

GRADLE = ROOT / "android" / "app" / "build.gradle.kts"
# Was der Server in config/ schreibt (CFG_FILE, PANELS_FILE, THEME_FILE und die
# Sicherungen davor), dazu was .gitignore dort nennt
LAUFZEIT = ["loxpanel.cfg", "loxpanel.cfg.bak", "panels.json", "panels.json.bak", "theme.json",
            "theme.json.bak", "loxpanel.cfg.tmp", "sicherung.zip"]


def _config_block(text: str) -> str:
    m = re.search(r'from\(loxRepoRoot\.resolve\("config"\)\)\s*\{(.*?)\n\s*\}', text, re.S)
    assert m, "kein config-Block in syncLoxpanelAssets"
    return m.group(1)


def _muster(block: str) -> list[str]:
    return [m for aufruf in re.findall(r"\binclude\(([^)]*)\)", block) for m in re.findall(r'"([^"]+)"', aufruf)]


def _faellt_hinein(name: str, muster: list[str]) -> bool:
    return "/" not in name and any(fnmatch.fnmatchcase(name, m) for m in muster)


def _vorlagen() -> list[str]:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), "ls-files", "config"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        r = None
    if r is None or r.returncode != 0 or not r.stdout.strip():
        pytest.skip("ohne Git-Checkout keine Liste der Vorlagen")
    return [z.split("/", 1)[1] for z in r.stdout.split()]


def _gitignore_config() -> list[str]:
    zeilen = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    return [z.strip().split("/", 1)[1] for z in zeilen if z.strip().startswith("config/")]


def test_nur_vorlagen_kommen_in_die_app():
    block = _config_block(GRADLE.read_text(encoding="utf-8"))
    muster = _muster(block)
    assert muster, "config/ braucht eine Liste dessen, was hinein darf (include), nicht nur exclude"
    vorlagen = _vorlagen()
    assert vorlagen and all(_faellt_hinein(v, muster) for v in vorlagen), (vorlagen, muster)
    for name in LAUFZEIT + _gitignore_config():
        assert not _faellt_hinein(name, muster), f"{name} kaeme in die APK ({muster})"


@pytest.mark.parametrize("block, erwartet", [
    ('into("config")\n        exclude("loxpanel.cfg", "panels.json", "theme.json")', "nur exclude"),
    ('into("config")\n        include("*")', "alles"),
    ('into("config")\n        include("*.example*", "*.json")', "json"),
], ids=["frueher", "alles", "json"])
def test_gegenprobe(block, erwartet):
    """Die Pruefung erkennt die alte Fassung (nur exclude) und zu weite Muster."""
    muster = _muster(block)
    durch = bool(muster) and not any(_faellt_hinein(n, muster) for n in LAUFZEIT)
    assert not durch, erwartet
