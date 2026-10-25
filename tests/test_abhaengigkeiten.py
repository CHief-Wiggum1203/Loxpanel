"""Fremder Code kommt nur festgenagelt ins Image (Lieferkette).

- requirements.txt nennt, was LoxPanel braucht, als Bereiche. Danach
  installieren die App (Chaquopy hat eigene Pakete fuer Android), das .deb und
  die Anleitungen ohne Docker, jeweils mit ihrem eigenen Python.
- requirements-lock.txt ist daraus fuer Python 3.12 gesperrt: jedes Paket, auch
  die mitgezogenen, in genau einer Version, jede Datei mit Pruefsumme. Image und
  CI installieren nur daraus (--require-hashes). Eine neue oder manipulierte
  Version kommt so nicht still beim naechsten Bauen hinein.
- Grundimage und GitHub Actions stehen auf einer Pruefsumme bzw. einem Commit,
  nicht auf einem Etikett wie `v4` oder `3.12-slim`, das sich verschieben laesst.
- Neue Staende kommen als Pull Request (Dependabot) und laufen durch die Tests.
- Keine geschlossene Bibliothek im Bau: setup-gradle cacht mit dem offenen
  Anbieter (`cache-provider: basic`). Ab v6 laedt sein Standard "enhanced"
  die proprietaere `gradle-actions-caching` mit eigenen Nutzungsbedingungen,
  auch im APK-Release neben den Signierschluesseln.

Gelesen werden die echten Dateien; die Gegenproben unten zeigen an
abgewandelten Texten, dass die Pruefungen jeden Fehler erkennen.
"""
from __future__ import annotations

import re

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from lox import ROOT

SPERRLISTE = ROOT / "requirements-lock.txt"
WORKFLOWS = ROOT / ".github" / "workflows"
_HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})\b")
_FROM = re.compile(r"^FROM\s+python:(\d+\.\d+)-slim@sha256:[0-9a-f]{64}\s*$", re.M)
_USES = re.compile(r"^[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}$")


def _logische_zeilen(text: str) -> list[str]:
    """Zeilen einer Anforderungsdatei: Fortsetzungen (\\ am Ende) verbunden,
    Kommentare und Leerzeilen weg."""
    zeilen, teil = [], ""
    for roh in text.splitlines():
        z = roh.split(" #", 1)[0].rstrip() if not roh.lstrip().startswith("#") else ""
        if z.endswith("\\"):
            teil += z[:-1] + " "
            continue
        teil += z
        if teil.strip():
            zeilen.append(teil.strip())
        teil = ""
    return zeilen


def _sperrliste_fehler(text: str) -> tuple[dict, list[str]]:
    """-> ({Paket: Version}, Fehler): jeder Eintrag genau eine Version (==),
    mindestens eine Pruefsumme, kein fremder Index und keine Adresse."""
    fest, fehler = {}, []
    for z in _logische_zeilen(text):
        if z.startswith("-"):
            fehler.append(f"Option statt Paket: {z[:60]}")
            continue
        anf, hashes = _HASH.sub("", z).strip(), _HASH.findall(z)
        try:
            r = Requirement(anf)
        except ValueError:
            fehler.append(f"unlesbar: {z[:60]}")
            continue
        spez = list(r.specifier)
        if r.url or len(spez) != 1 or spez[0].operator != "==" or "*" in spez[0].version:
            fehler.append(f"{r.name}: keine feste Version ({anf})")
        elif not hashes:
            fehler.append(f"{r.name}: ohne Pruefsumme")
        else:
            fest[canonicalize_name(r.name)] = Version(spez[0].version)
    return fest, fehler


def _bereiche(text: str) -> list[Requirement]:
    return [Requirement(z) for z in _logische_zeilen(text) if not z.startswith("-")]


def _passt_nicht(bereiche: list[Requirement], fest: dict) -> list[str]:
    """Pakete aus requirements.txt, die in der Sperrliste fehlen oder deren
    Version nicht in den Bereich passt."""
    falsch = []
    for r in bereiche:
        v = fest.get(canonicalize_name(r.name))
        if v is None or not r.specifier.contains(v, prereleases=True):
            falsch.append(f"{r.name}{r.specifier}: gesperrt {v or 'fehlt'}")
    return falsch


def _befehl() -> str:
    """Wie die Sperrliste entstand (steht in ihrem Kopf, von pip-compile)."""
    m = re.search(r"^#\s+(pip-compile .+)$", SPERRLISTE.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "?"


def _workflows() -> dict:
    return {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(WORKFLOWS.glob("*.y*ml"))}


def _uses_fehler(wfs: dict) -> list[str]:
    falsch = []
    for name, wf in wfs.items():
        for jn, job in (wf.get("jobs") or {}).items():
            for s in job.get("steps") or []:
                u = s.get("uses")
                if u and not u.startswith("./") and not _USES.match(u):
                    falsch.append(f"{name} {jn}: {u}")
    return falsch


def _gradle_fehler(wfs: dict) -> list[str]:
    """Schritte mit setup-gradle, die nicht den offenen Cache-Anbieter nehmen."""
    return [f"{name} {jn}: {(s.get('with') or {}).get('cache-provider')!r}"
            for name, wf in wfs.items() for jn, job in (wf.get("jobs") or {}).items()
            for s in job.get("steps") or []
            if str(s.get("uses", "")).startswith("gradle/actions/setup-gradle")
            and (s.get("with") or {}).get("cache-provider") != "basic"]


# ---- die echten Dateien ----

def test_sperrliste_jede_version_fest_mit_pruefsumme():
    fest, fehler = _sperrliste_fehler(SPERRLISTE.read_text(encoding="utf-8"))
    assert fehler == [], fehler
    assert len(fest) >= len(_bereiche((ROOT / "requirements.txt").read_text(encoding="utf-8")))


def test_sperrliste_passt_zu_requirements():
    """Wer requirements.txt aendert, erzeugt die Sperrliste neu (Befehl in
    ihrem Kopf, docs/CONTRIBUTING.md)."""
    fest, _ = _sperrliste_fehler(SPERRLISTE.read_text(encoding="utf-8"))
    falsch = _passt_nicht(_bereiche((ROOT / "requirements.txt").read_text(encoding="utf-8")), fest)
    assert falsch == [], f"requirements-lock.txt neu erzeugen ({_befehl()}): {falsch}"
    assert _befehl().endswith(" requirements.txt"), _befehl()


def test_python_ueberall_gleich():
    """Die Sperrliste gilt fuer genau ein Python (Pakete, die nur aelteres
    Python braucht, fehlen darin). Image, CI und Sperrliste muessen es teilen."""
    kopf = re.search(r"autogenerated by pip-compile with Python (\d+\.\d+)",
                     SPERRLISTE.read_text(encoding="utf-8"))
    image = _FROM.search((ROOT / "Dockerfile").read_text(encoding="utf-8"))
    assert kopf and image, "Kopf der Sperrliste oder FROM-Zeile nicht erkannt"
    ci = {str(s["with"]["python-version"])
          for job in _workflows()["tests.yml"]["jobs"].values() for s in job.get("steps") or []
          if str(s.get("uses", "")).startswith("actions/setup-python")}
    assert {kopf.group(1), image.group(1)} | ci == {image.group(1)}, (kopf.group(1), image.group(1), ci)


def test_image_nur_aus_der_sperrliste():
    df = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert len(re.findall(r"^FROM\s", df, re.M)) == len(_FROM.findall(df)) == 1, "FROM ohne @sha256"
    pip = [z for z in df.replace("\\\n", " ").splitlines() if re.search(r"\bpip3?\s+install\b", z)]
    assert pip and all(re.search(r"--require-hashes\b.*-r\s+requirements-lock\.txt\b", z) for z in pip), pip


def test_ci_installiert_aus_der_sperrliste():
    """Die Tests laufen mit denselben Versionen wie das Image: zuerst die
    Sperrliste mit Pruefsummen, danach erst die Werkzeuge (pytest, ruff ...)."""
    falsch = []
    for jn, job in _workflows()["tests.yml"]["jobs"].items():
        laeufe = [str(s.get("run", "")) for s in job.get("steps") or []]
        pip = [z.strip() for r in laeufe for z in r.splitlines() if re.search(r"\bpip\s+install\b", z)]
        if pip and not re.fullmatch(r"pip install --require-hashes -r requirements-lock\.txt", pip[0]):
            falsch.append(f"{jn}: {pip[0]}")
    assert falsch == [], falsch


def test_actions_auf_commit():
    """`uses:` auf einen Commit (40 Hex-Zeichen), die Version als Kommentar
    dahinter, wie Dependabot ihn nachzieht."""
    assert _uses_fehler(_workflows()) == []
    ohne_kommentar = [z.strip() for p in sorted(WORKFLOWS.glob("*.y*ml"))
                      for z in p.read_text(encoding="utf-8").splitlines()
                      if re.search(r"\buses:\s*[\w.-]+/", z) and not re.search(r"@[0-9a-f]{40} # v\d", z)]
    assert ohne_kommentar == [], ohne_kommentar


def test_dependabot_deckt_alles_ab():
    """Jede festgenagelte Quelle bekommt Updates als Pull Request. Eine
    Obergrenze in requirements.txt ist Absicht: Dependabot schlaegt darueber
    hinweg nichts vor. Das Grundimage bleibt bei seiner Python-Version."""
    db = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    je = {u["package-ecosystem"]: u for u in db["updates"] if u.get("directory") == "/"}
    assert {"pip", "docker", "github-actions"} <= set(je), sorted(je)

    def ignoriert(u, name, art):
        return any(i.get("dependency-name") == name and art in (i.get("update-types") or [])
                   for i in u.get("ignore") or [])
    mit_grenze = [r.name for r in _bereiche((ROOT / "requirements.txt").read_text(encoding="utf-8"))
                  if any(s.operator in ("<", "<=", "~=", "==") for s in r.specifier)]
    assert mit_grenze, "requirements.txt ohne Obergrenze? Dann diese Pruefung anpassen"
    ohne = [n for n in mit_grenze if not ignoriert(je["pip"], n, "version-update:semver-major")]
    assert ohne == [], f"Obergrenze ohne ignore in dependabot.yml: {ohne}"
    for art in ("version-update:semver-major", "version-update:semver-minor"):
        assert ignoriert(je["docker"], "python", art), art


def test_gradle_nur_mit_offenem_cache():
    wfs = _workflows()
    assert any(str(s.get("uses", "")).startswith("gradle/actions/setup-gradle")
               for wf in wfs.values() for job in (wf.get("jobs") or {}).values() for s in job.get("steps") or [])
    assert _gradle_fehler(wfs) == []


# ---- Gegenproben: die Pruefungen erkennen jeden Fehler ----

_GUT = "aiohttp==3.14.5 \\\n    --hash=sha256:" + "a" * 64 + "\n    # via loxone-api\n"


@pytest.mark.parametrize("text, erwartet", [
    ("aiohttp>=3.9 \\\n    --hash=sha256:" + "a" * 64 + "\n", "keine feste Version"),
    ("aiohttp==3.14.5\n", "ohne Pruefsumme"),
    ("aiohttp==3.* \\\n    --hash=sha256:" + "a" * 64 + "\n", "keine feste Version"),
    ("--extra-index-url https://example.org/simple\n" + _GUT, "Option statt Paket"),
    ("aiohttp @ https://example.org/aiohttp.whl \\\n    --hash=sha256:" + "a" * 64 + "\n", "keine feste Version"),
], ids=["bereich", "ohne-hash", "stern", "fremder-index", "adresse"])
def test_gegenprobe_sperrliste(text, erwartet):
    assert _sperrliste_fehler(_GUT)[1] == []
    assert any(erwartet in f for f in _sperrliste_fehler(text)[1]), _sperrliste_fehler(text)


def test_gegenprobe_bereich_passt_nicht():
    fest, _ = _sperrliste_fehler(_GUT)
    assert _passt_nicht(_bereiche("aiohttp>=3.9\n"), fest) == []
    assert _passt_nicht(_bereiche("aiohttp>=4\n"), fest)          # Bereich angehoben, Liste alt
    assert _passt_nicht(_bereiche("yarl>=1\n"), fest)             # neues Paket, Liste alt


def test_gegenprobe_actions():
    assert _uses_fehler({"x.yml": {"jobs": {"j": {"steps": [{"uses": "actions/checkout@" + "0" * 40}]}}}}) == []
    for u in ("actions/checkout@v4", "actions/checkout@main", "actions/checkout@" + "0" * 39):
        assert _uses_fehler({"x.yml": {"jobs": {"j": {"steps": [{"uses": u}]}}}}), u


def test_gegenprobe_gradle():
    def wf(mit):
        return {"x.yml": {"jobs": {"j": {"steps": [{"uses": "gradle/actions/setup-gradle@" + "0" * 40, "with": mit}]}}}}
    assert _gradle_fehler(wf({"gradle-version": "8.7", "cache-provider": "basic"})) == []
    for mit in ({"gradle-version": "8.7"}, {"cache-provider": "enhanced"}, None):
        assert _gradle_fehler(wf(mit)), mit
