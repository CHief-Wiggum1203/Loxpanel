"""Welcher Stand laeuft (bin/version_info.py): Version, Commit und Bauzeit aus
bin/version.json, die APK- und Docker-Build schreiben; ohne die Datei aus
loxberry-plugin/plugin.cfg und Git. /api/settings und /api/health liefern sie,
der Konfigurator zeigt sie in der Seitenleiste."""
import asyncio
import json
import re
import shutil
import subprocess
import sys

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import version_info as V
from lox import ROOT, W

STAND = {"version": "9.8.7", "commit": "abcdef0123456789abcdef0123456789abcdef01", "gebaut": "2026-10-03T12:15:00Z"}


def _baum(tmp_path, version="1.2.3"):
    """Verzeichnis wie im Image oder in der App: bin/ und loxberry-plugin/plugin.cfg."""
    (tmp_path / "bin").mkdir()
    (tmp_path / "loxberry-plugin").mkdir()
    (tmp_path / "loxberry-plugin" / "plugin.cfg").write_text(
        f"[PLUGIN]\nNAME=loxpanel\nVERSION={version}\nAUTHOR_NAME=x\n", encoding="utf-8")
    return tmp_path / "bin"


def test_aus_der_datei(tmp_path):
    b = _baum(tmp_path)
    (b / "version.json").write_text(json.dumps({**STAND, "anderes": 1}), encoding="utf-8")
    assert V.lesen(b) == STAND


def test_ohne_datei_aus_plugin_cfg(tmp_path):
    assert V.lesen(_baum(tmp_path)) == {"version": "1.2.3", "commit": "", "gebaut": ""}


@pytest.mark.parametrize("inhalt", ["kein json", "[1, 2]", ""])
def test_kaputte_datei_wie_ohne(tmp_path, inhalt):
    b = _baum(tmp_path)
    (b / "version.json").write_text(inhalt, encoding="utf-8")
    assert V.lesen(b) == {"version": "1.2.3", "commit": "", "gebaut": ""}


def test_nichts_bekannt(tmp_path):
    (tmp_path / "bin").mkdir()
    assert V.lesen(tmp_path / "bin") == {"version": "", "commit": "", "gebaut": ""}


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def test_commit_aus_git(tmp_path):
    b = _baum(tmp_path)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
         "commit", "-q", "-m", "x")
    assert V.lesen(b) == {"version": "1.2.3", "commit": _git(tmp_path, "rev-parse", "HEAD"), "gebaut": ""}


def test_schreiben_wie_im_dockerfile(tmp_path):
    """`python bin/version_info.py schreiben <commit>` in einer Kopie, damit im
    Repo kein bin/version.json entsteht."""
    b = _baum(tmp_path, "0.7.1")
    shutil.copy(ROOT / "bin" / "version_info.py", b)
    r = subprocess.run([sys.executable, str(b / "version_info.py"), "schreiben", "0123abc"],
                       capture_output=True, text=True, check=True)
    datei = json.loads((b / "version.json").read_text(encoding="utf-8"))
    assert json.loads(r.stdout) == datei
    assert datei["version"] == "0.7.1" and datei["commit"] == "0123abc"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", datei["gebaut"])
    assert V.lesen(b) == datei
    falsch = subprocess.run([sys.executable, str(b / "version_info.py")], capture_output=True, text=True)
    assert falsch.returncode != 0 and "schreiben" in falsch.stderr


def test_der_echte_stand():
    """Im Checkout: Version aus plugin.cfg (dieselbe Quelle wie versionCode der App)."""
    if (ROOT / "bin" / "version.json").exists():
        pytest.skip("bin/version.json liegt im Arbeitsbaum")
    soll = re.search(r"^VERSION=(\S+)", (ROOT / "loxberry-plugin" / "plugin.cfg").read_text(encoding="utf-8"), re.M)
    assert W.VERSION["version"] == soll.group(1) and W.VERSION == V.lesen()


def test_settings_und_health_nennen_die_version(cfg_ordner, monkeypatch):
    monkeypatch.setattr(W, "VERSION", STAND)

    async def lauf():
        ui = web.Application()
        ui["app"] = W.App({"host": "", "port": 80})
        ui["tasks"], ui["started"] = {}, 0.0
        ui.router.add_get("/api/settings", W.api_settings)
        ui.router.add_get("/api/health", W.api_health)
        async with TestClient(TestServer(ui)) as cl:
            return ((await (await cl.get("/api/settings")).json())["version"],
                    (await (await cl.get("/api/health")).json())["version"])
    assert asyncio.run(lauf()) == (STAND, STAND)
