"""Ein Image auf ghcr.io entsteht nur aus einem Commit, dessen Tests gruen
sind.

Frueher baute und veroeffentlichte docker-image.yml neben tests.yml her: Der
Build war nach einer Minute draussen, die Browser-Tests nach zehn, und ein
Tag v* startete gar keine Tests. GitHub verbindet Jobs nur innerhalb eines
Workflows per `needs`, darum veroeffentlicht jetzt ein Job in tests.yml, der
auf alle Pruef-Jobs desselben Laufs (also desselben Commits) wartet.

Gelesen werden die echten Workflow-Dateien. `_fehler()` sammelt alle Wege,
auf denen ein ungeprueftes Image hinauskaeme oder das Image still ausbliebe;
die Gegenproben unten zeigen an Abwandlungen der echten Dateien, dass sie
jeden davon erkennt.
"""
from __future__ import annotations

import re

import pytest
import yaml

from lox import ROOT

WORKFLOWS = ROOT / ".github" / "workflows"

# Wann veroeffentlicht wird: nur bei Push und manuellem Start, nur von main
# oder einem v*-Tag, nie aus einem Pull Request. Bewusst woertlich, wer das
# Tor aendert, soll hier vorbeikommen.
TOR = re.compile(
    r"(\$\{\{ )?"
    r"\(github\.event_name == 'push' \|\| github\.event_name == 'workflow_dispatch'\) && "
    r"\(github\.ref == 'refs/heads/main' \|\| startsWith\(github\.ref, 'refs/tags/v'\)\)"
    r"( \}\})?")

# Ein Image verlaesst den Runner per docker push, buildx --push, einer Ausgabe
# in die Registry oder imagetools create.
_PUSH = re.compile(r"\bdocker\s+(image\s+)?push\b|--push\b|\bpush=true\b|\btype=registry\b"
                   r"|\bimagetools\s+create\b")
_LOGIN_GHCR = re.compile(r"\blogin\b[^\n]*\bghcr\.io\b")
# Pruef-Schritte: wird einer rot, darf kein Image entstehen ...
_PRUEFT = re.compile(r"\b(pytest|ruff|py_compile)\b")
# ... und keiner darf seinen Fehler verschlucken.
_SCHLUCKT = re.compile(r"\|\||\bset\s+\+e\b|\bexit\s+0\b|;\s*(true|:)\s*$", re.M)


def _lade() -> dict:
    return {p.name: yaml.safe_load(p.read_text(encoding="utf-8"))
            for p in sorted(WORKFLOWS.glob("*.y*ml"))}


def _ausloeser(wf: dict) -> dict:
    on = wf.get("on", wf.get(True))          # PyYAML (YAML 1.1) liest `on` als True
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return dict.fromkeys(on)
    return on or {}


def _an(wert) -> bool:
    """YAML-Schalter; ein Ausdruck ${{ }} zaehlt als an, er koennte es sein."""
    return wert not in (None, False) and str(wert).strip().lower() not in ("", "false")


def _schreibt_packages(rechte) -> bool:
    if isinstance(rechte, str):
        return rechte == "write-all"
    return isinstance(rechte, dict) and rechte.get("packages") == "write"


def _veroeffentlicht(job: dict) -> bool:
    """Schiebt der Job ein Image nach ghcr.io oder holt er sich das Recht dazu?"""
    if _schreibt_packages(job.get("permissions")):
        return True
    for s in job.get("steps") or []:
        uses, mit, lauf = str(s.get("uses", "")), s.get("with") or {}, str(s.get("run", ""))
        if uses.startswith(("docker/build-push-action", "docker/bake-action")) and (
                _an(mit.get("push")) or _PUSH.search(f"{mit.get('outputs', '')} {mit.get('set', '')}")):
            return True
        if uses.startswith("docker/login-action") and "ghcr.io" in str(mit.get("registry", "")):
            return True
        if _PUSH.search(lauf) or _LOGIN_GHCR.search(lauf):
            return True
    return False


def _vorgaenger(jobs: dict, name: str) -> set:
    gesehen, offen = set(), [name]
    while offen:
        needs = jobs[offen.pop()].get("needs") or []
        for n in [needs] if isinstance(needs, str) else needs:
            if n not in gesehen:
                gesehen.add(n)
                offen.append(n)
    return gesehen


def _marker(zeile: str):
    """Marker-Ausdruck eines pytest-Aufrufs (-m ...), None ohne -m."""
    m = re.search(r"""-m\s+(?:"([^"]*)"|'([^']*)'|(\S+))""", zeile)
    return next((g for g in m.groups() if g is not None), None) if m else None


def _fehler(wfs: dict) -> list:
    fehler = []
    for datei, wf in wfs.items():
        if _schreibt_packages(wf.get("permissions")):
            fehler.append(f"{datei}: packages: write fuer den ganzen Workflow statt nur fuer den "
                          f"Veroeffentlichungs-Job")
    pushend = [(d, n) for d, wf in wfs.items() for n, j in (wf.get("jobs") or {}).items()
               if _veroeffentlicht(j)]
    if len(pushend) != 1:
        fehler.append(f"genau ein Job darf nach ghcr.io veroeffentlichen, gefunden: "
                      f"{[f'{d}:{n}' for d, n in pushend]}")
    for datei, name in pushend:
        wf = wfs[datei]
        jobs, wo = wf["jobs"], f"{datei}:{name}"
        pruefjobs = {n for n, j in jobs.items()
                     if any(_PRUEFT.search(str(s.get("run", ""))) for s in j.get("steps") or [])}
        if not pruefjobs:
            fehler.append(f"{wo} veroeffentlicht, aber im selben Lauf prueft nichts "
                          f"(Ausloeser: {sorted(_ausloeser(wf))})")
        if fehlt := pruefjobs - _vorgaenger(jobs, name):
            fehler.append(f"{wo} wartet nicht auf {sorted(fehlt)}")
        # Ein uebersprungener Vorgaenger ueberspringt auch das Veroeffentlichen,
        # dann bliebe das Image still aus.
        for n in sorted(_vorgaenger(jobs, name) - pruefjobs):
            if "if" in jobs[n]:
                fehler.append(f"{wo} wartet auf {n}, der nicht bei jedem Ereignis laeuft "
                              f"(if: {jobs[n]['if']}), dort bliebe das Image aus")
        marker = {_marker(z) for n in pruefjobs for s in jobs[n].get("steps") or []
                  for z in str(s.get("run", "")).splitlines() if "pytest" in z}
        if pruefjobs and None not in marker and not {"browser", "not browser"} <= marker:
            fehler.append(f"{wo}: die Pruef-Jobs fahren nicht alle Tests (pytest -m {sorted(marker)})")
        for n in sorted(pruefjobs):
            pj = jobs[n]
            if "if" in pj:
                fehler.append(f"{datei}:{n} prueft nicht bei jedem Ereignis (if: {pj['if']})")
            if _an(pj.get("continue-on-error")):
                fehler.append(f"{datei}:{n} hat continue-on-error, rot zaehlt dann als gruen")
            for s in pj.get("steps") or []:
                lauf = str(s.get("run", ""))
                if not _PRUEFT.search(lauf):
                    continue
                # Ein uebersprungener Schritt zaehlt als gruen, der Job ebenso
                if "if" in s:
                    fehler.append(f"{datei}:{n} Schritt {s.get('name')!r} prueft nicht bei jedem "
                                  f"Ereignis (if: {s['if']})")
                if _an(s.get("continue-on-error")):
                    fehler.append(f"{datei}:{n} Schritt {s.get('name')!r} hat continue-on-error")
                if _SCHLUCKT.search(lauf):
                    fehler.append(f"{datei}:{n} Schritt {s.get('name')!r} verschluckt den Fehler: {lauf!r}")
        bedingung = " ".join(str(jobs[name].get("if", "")).split())
        if re.search(r"\b(always|success|failure|cancelled)\s*\(", bedingung):
            fehler.append(f"{wo}: eine Statusfunktion im if hebelt needs aus: {bedingung}")
        elif not TOR.fullmatch(bedingung):
            fehler.append(f"{wo}: if laesst mehr durch als Push oder manuellen Start auf main "
                          f"oder einem v*-Tag: {bedingung!r}")
        push = _ausloeser(wf).get("push") or {}
        if "main" not in (push.get("branches") or []) or "v*" not in (push.get("tags") or []):
            fehler.append(f"{datei}: startet nicht bei Push auf main und auf v*-Tags, "
                          f"dort bliebe das Image aus")
    return fehler


def test_image_nur_nach_gruenen_tests_desselben_laufs():
    assert _fehler(_lade()) == []


# Gegenproben: Abwandlungen der echten Dateien, die je einen Umweg oeffnen.

def _jobs(wfs):
    return wfs["tests.yml"]["jobs"]


def _pytest(job):
    return next(s for s in job["steps"] if "pytest" in str(s.get("run", "")))


def _tor(wfs):
    return _jobs(wfs)["veroeffentlichen"]["if"]


def _alter_workflow(wfs):
    """Der fruehere docker-image.yml: derselbe Job ohne needs und ohne Tor."""
    job = {k: v for k, v in _jobs(wfs)["veroeffentlichen"].items() if k not in ("needs", "if")}
    wfs["docker-image.yml"] = {True: {"push": {"branches": ["main"], "tags": ["v*"]},
                                      "workflow_dispatch": None},
                               "jobs": {"build": job}}


GEGENPROBEN = [
    ("browser_nicht_abgewartet",
     lambda w: _jobs(w)["veroeffentlichen"].update(needs=["pruefen"]), "wartet nicht auf ['visu']"),
    ("always",
     lambda w: _jobs(w)["veroeffentlichen"].update({"if": f"always() && {_tor(w)}"}), "hebelt needs aus"),
    ("success_oder",
     lambda w: _jobs(w)["veroeffentlichen"].update({"if": f"success() || {_tor(w)}"}), "hebelt needs aus"),
    ("pull_request_durchgelassen",
     lambda w: _jobs(w)["veroeffentlichen"].update(
         {"if": f"github.event_name == 'pull_request' || {_tor(w)}"}), "laesst mehr durch"),
    ("browser_tests_nur_bei_prs",
     lambda w: _jobs(w)["visu"].update({"if": "github.event_name == 'pull_request'"}),
     "prueft nicht bei jedem Ereignis"),
    ("browser_schritt_nur_bei_prs",
     lambda w: _pytest(_jobs(w)["visu"]).update({"if": "github.event_name == 'pull_request'"}),
     "Schritt 'Browser-Tests' prueft nicht bei jedem Ereignis"),
    ("pytest_schritt_aus",
     lambda w: _pytest(_jobs(w)["pruefen"]).update({"if": False}),
     "Schritt 'Tests und Rauchtest' prueft nicht bei jedem Ereignis"),
    ("wartet_auf_pr_job",
     lambda w: _jobs(w)["veroeffentlichen"].update(needs=["pruefen", "visu", "image"]),
     "wartet auf image, der nicht bei jedem Ereignis laeuft"),
    ("continue_on_error_am_job",
     lambda w: _jobs(w)["visu"].update({"continue-on-error": True}), "rot zaehlt dann als gruen"),
    ("continue_on_error_am_schritt",
     lambda w: _pytest(_jobs(w)["visu"]).update({"continue-on-error": True}), "hat continue-on-error"),
    ("oder_true_hinter_pytest",
     lambda w: _pytest(_jobs(w)["visu"]).update(run=_pytest(_jobs(w)["visu"])["run"] + " || true"),
     "verschluckt den Fehler"),
    ("browser_tests_entfernt",
     lambda w: _jobs(w)["visu"]["steps"].remove(_pytest(_jobs(w)["visu"])), "fahren nicht alle Tests"),
    ("pr_image_mit_push",
     lambda w: next(s for s in _jobs(w)["image"]["steps"]
                    if "build-push-action" in str(s.get("uses"))).update({"with": {"push": True}}),
     "genau ein Job"),
    ("docker_push_per_run",
     lambda w: _jobs(w)["image"]["steps"].append(
         {"run": "docker buildx build --push -t ghcr.io/chief-wiggum1203/loxpanel:pr ."}),
     "genau ein Job"),
    ("packages_write_fuer_alle",
     lambda w: w["tests.yml"]["permissions"].update(packages="write"), "fuer den ganzen Workflow"),
    ("kein_tag_ausloeser",
     lambda w: _ausloeser(w["tests.yml"])["push"].pop("tags"), "auf v*-Tags"),
    ("alter_docker_workflow", _alter_workflow, "genau ein Job"),
]


@pytest.mark.parametrize("abwandeln,erwartet", [g[1:] for g in GEGENPROBEN],
                         ids=[g[0] for g in GEGENPROBEN])
def test_gegenprobe_erkennt_umweg(abwandeln, erwartet):
    wfs = _lade()
    abwandeln(wfs)
    fehler = _fehler(wfs)
    assert any(erwartet in f for f in fehler), fehler
