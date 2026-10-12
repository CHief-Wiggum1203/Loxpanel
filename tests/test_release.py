"""Ein Tag v* ergibt ein vollstaendiges Release: APK, .deb und LoxBerry-Plugin.

Die drei Workflows haengen ihre Datei per softprops/action-gh-release an das
Release des Tags, wer zuerst fertig ist, legt es an. Ein Release, das ein
Workflow mit GITHUB_TOKEN anlegt, loest bei GitHub keinen weiteren Workflow
aus. Hinge einer an `release:`, fehlte seine Datei, sobald das Release nicht
aus der Oberflaeche kommt; so ging es frueher dem Plugin-ZIP, auf das
ARCHIVEURL in loxberry-plugin/release.cfg zeigt.

Gelesen werden die echten Workflow-Dateien, der Schritt fuer die
Release-Notizen laeuft mit der echten README.
"""
from __future__ import annotations

import os
import re
import subprocess

import pytest
import yaml

from lox import ROOT

WORKFLOWS = ROOT / ".github" / "workflows"
# Workflow -> Datei, die er an das Release haengt
AM_RELEASE = {
    "android-apk.yml": "LoxPanel-Server.apk",
    "deb.yml": "loxpanel-server_*_all.deb",
    "plugin-release.yml": "loxpanel-plugin.zip",
}
NUR_BEI_TAG = "startsWith(github.ref, 'refs/tags/v')"


def _lade(pfad) -> dict:
    return yaml.safe_load(pfad.read_text(encoding="utf-8"))


def _ausloeser(wf: dict) -> dict:
    on = wf.get("on", wf.get(True))          # PyYAML (YAML 1.1) liest `on` als True
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return dict.fromkeys(on)
    return on or {}


def _release_schritte(wf: dict) -> list:
    return [s for job in wf["jobs"].values() for s in job.get("steps", [])
            if str(s.get("uses", "")).startswith("softprops/action-gh-release@")]


@pytest.mark.parametrize("name", sorted(AM_RELEASE))
def test_tag_haengt_die_datei_an_das_release(name):
    wf = _lade(WORKFLOWS / name)
    tags = (_ausloeser(wf).get("push") or {}).get("tags") or []
    assert "v*" in tags, f"{name} laeuft nicht beim Tag"
    assert (wf.get("permissions") or {}).get("contents") == "write", \
        f"{name} darf das Release nicht anlegen"
    schritte = _release_schritte(wf)
    assert len(schritte) == 1, name
    assert schritte[0]["with"]["files"] == AM_RELEASE[name]
    assert schritte[0].get("if") == NUR_BEI_TAG


def test_kein_workflow_haengt_am_release_ereignis():
    haengen = [p.name for p in sorted(WORKFLOWS.glob("*.y*ml"))
               if "release" in _ausloeser(_lade(p))]
    assert not haengen, f"{haengen} liefen bei einem Release aus einem Workflow nicht"


def _notizen(tmp_path, version: str, readme: str) -> tuple[str, str]:
    """Den Schritt "Release-Notizen aus dem Changelog" so ausfuehren, wie ihn
    GitHub ausfuehrt (bash -eo pipefail), mit `readme` als README.md."""
    wf = _lade(WORKFLOWS / "plugin-release.yml")
    schritt = next(s for s in wf["jobs"]["zip"]["steps"]
                   if s.get("name") == "Release-Notizen aus dem Changelog")
    assert schritt.get("if") == NUR_BEI_TAG
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    r = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", schritt["run"]],
                       cwd=tmp_path, env={**os.environ, "GITHUB_REF_NAME": f"v{version}"},
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return (tmp_path / "release-notes.md").read_text(encoding="utf-8"), r.stdout


def test_notizen_sind_der_changelog_eintrag_der_version(tmp_path):
    version = re.search(r"^VERSION=(\S+)",
                        (ROOT / "loxberry-plugin" / "plugin.cfg").read_text(encoding="utf-8"),
                        re.M).group(1)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    kopf = f"- **{version}** – "
    eintraege = [z[len(kopf):] for z in readme.splitlines() if z.startswith(kopf)]
    assert len(eintraege) == 1, f"Changelog der README hat keinen Eintrag für {version}"
    notizen, _ = _notizen(tmp_path, version, readme)
    assert notizen.strip() == eintraege[0].strip()


def test_notizen_nehmen_nur_die_eigene_version(tmp_path):
    readme = ("# Changelog\n\n"
              "- **1.10.0** – zehn\n"
              "- **1.1.0** – eins mit **fett** und `code`\n"
              "- **1.1.0** – spaeterer Doppeleintrag\n")
    assert _notizen(tmp_path, "1.1.0", readme)[0] == "eins mit **fett** und `code`\n"
    assert _notizen(tmp_path, "1.10.0", readme)[0] == "zehn\n"


def test_ohne_eintrag_bleibt_das_release_ohne_notizen(tmp_path):
    notizen, ausgabe = _notizen(tmp_path, "2.0.0", "- **1.0.0** – eins\n")
    assert notizen == ""
    assert "::warning::" in ausgabe
