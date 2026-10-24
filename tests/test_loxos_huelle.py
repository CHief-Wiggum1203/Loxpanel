"""LoxOS (Fork, docs/VISION.md): die Huelle loxos/ (Electron).

- Die reine Logik (Einstellungen, Monitorwahl) testet Node selbst
  (loxos/test/*.test.js); hier laufen sie mit, wo Node da ist.
- Fremder Code kommt nur festgenagelt hinein, wie bei den Python-Paketen
  (test_abhaengigkeiten.py): package.json nennt genaue Versionen, die
  Sperrdatei jede Datei mit Pruefsumme, Dependabot kennt den Ordner.
- Jedes Fenster laeuft isoliert, im Sandbox-Prozess und ohne Node.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
import yaml

from lox import ROOT

LOXOS = ROOT / "loxos"


def test_node_tests_der_huelle():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node fehlt")
    dateien = sorted(str(p) for p in (LOXOS / "test").glob("*.test.js"))
    assert dateien
    r = subprocess.run([node, "--test", *dateien], cwd=LOXOS, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]


def test_versionen_genau_festgenagelt():
    pkg = json.loads((LOXOS / "package.json").read_text(encoding="utf-8"))
    alle = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    assert alle, "keine Abhaengigkeiten?"
    lose = {n: v for n, v in alle.items() if not re.fullmatch(r"\d+\.\d+\.\d+", v)}
    assert lose == {}, f"Bereiche statt genauer Versionen: {lose}"


def test_sperrdatei_mit_pruefsummen_passt_zu_package_json():
    pkg = json.loads((LOXOS / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((LOXOS / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["lockfileVersion"] >= 2
    pakete = lock["packages"]
    ohne = [n for n, p in pakete.items() if n and not str(p.get("integrity", "")).startswith("sha512-")]
    assert ohne == [], f"ohne sha512-Pruefsumme: {ohne}"
    for name, version in pkg.get("devDependencies", {}).items():
        assert pakete[f"node_modules/{name}"]["version"] == version, name
    assert pakete[""]["devDependencies"] == pkg["devDependencies"]


def test_dependabot_kennt_die_huelle():
    db = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    assert any(u["package-ecosystem"] == "npm" and u["directory"] == "/loxos" for u in db["updates"])


def test_jedes_fenster_isoliert_ohne_node():
    main = (LOXOS / "src" / "main.js").read_text(encoding="utf-8")
    fenster = main.count("new BrowserWindow(")
    assert fenster >= 2
    for teil in ("contextIsolation: true", "nodeIntegration: false", "sandbox: true"):
        assert main.count(teil) == fenster, teil
    # die Einrichtung laedt nur eigene Dateien
    html = (LOXOS / "src" / "einrichtung.html").read_text(encoding="utf-8")
    assert "default-src 'none'; script-src 'self'; style-src 'self'" in html


def test_einrichtung_ohne_eigene_farben():
    """Design nur ueber das System (Canvas, CanvasText ...), keine Hex-Farben."""
    css = (LOXOS / "src" / "einrichtung.css").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", css)


PROGRAMME = {"entwicklung": (LOXOS / "node_modules" / "electron" / "dist" / "electron", ["."]),
             "gepackt": (LOXOS / "dist" / "linux-unpacked" / "loxos", [])}


@pytest.mark.parametrize("art", list(PROGRAMME))
def test_huelle_startet_und_meldet_sich_als_geraet(art, tmp_path):
    """Rauchtest: die echte Huelle unter Xvfb (2560 x 720) laedt die Visu mit
    ?device=<Geraet> - aus dem Quelltext (cd loxos && npm ci) und gepackt (npm
    run dist unter Linux). Nur, wo das Programm und Xvfb da sind - in CI wird
    das 100-MB-Programm hier nicht geladen."""
    import http.server
    import os
    import signal
    import threading
    import time

    electron, zusatz = PROGRAMME[art]
    xvfb = shutil.which("xvfb-run")
    if not (electron.is_file() and xvfb):
        pytest.skip(f"Programm ({art}) oder Xvfb fehlt")
    anfragen = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            anfragen.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<!doctype html><title>Visu</title>")

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = tmp_path / "cfg" / "loxos"
    cfg.mkdir(parents=True)
    (cfg / "loxos.json").write_text(json.dumps({"server": f"http://127.0.0.1:{srv.server_port}",
                                                "geraet": "streifen-test", "autostart": False}), encoding="utf-8")
    argumente = [xvfb, "-a", "-s", "-screen 0 2560x720x24", str(electron), "--disable-gpu"]
    if os.geteuid() == 0:
        argumente.append("--no-sandbox")    # Chromium verweigert sonst den Start als root (nur im Container)
    p = subprocess.Popen([*argumente, *zusatz], cwd=LOXOS, env={**os.environ, "XDG_CONFIG_HOME": str(tmp_path / "cfg")},
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        ende = time.monotonic() + 30
        while not anfragen and time.monotonic() < ende and p.poll() is None:
            time.sleep(0.2)
    finally:
        os.killpg(p.pid, signal.SIGTERM)
        p.wait(timeout=10)
        srv.shutdown()
    assert "/?device=streifen-test" in anfragen, anfragen


def test_installer_konfiguration():
    """Ins Paket kommen nur Programm, Symbole und package.json (keine Tests,
    keine Entwicklungspakete); je System ein Installer, nichts wird
    veroeffentlicht (das macht der Workflow), das Symbol ist da."""
    pkg = json.loads((LOXOS / "package.json").read_text(encoding="utf-8"))
    b = pkg["build"]
    assert b["productName"] == "LoxOS" and b["appId"].endswith(".loxos") and b["publish"] is None
    assert b["files"] == ["src/**", "assets/**", "package.json"]
    assert [z["target"] for z in b["win"]["target"]] == ["nsis"]
    assert [z["target"] for z in b["mac"]["target"]] == ["dmg"]
    assert [z["target"] for z in b["linux"]["target"]] == ["AppImage"]
    assert b["mac"]["extendInfo"]["LSUIElement"] is True, "kein Dock-Symbol, LoxOS lebt im Tray"
    icon = LOXOS / b["directories"]["buildResources"] / "icon.png"
    kopf = icon.read_bytes()[:24]
    assert kopf[:8] == b"\x89PNG\r\n\x1a\n" and int.from_bytes(kopf[16:20], "big") >= 512


def test_workflow_baut_auf_allen_systemen():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "loxos.yml").read_text(encoding="utf-8"))
    job = wf["jobs"]["build"]
    assert sorted(job["strategy"]["matrix"]["os"]) == ["macos-latest", "ubuntu-latest", "windows-latest"]
    laeufe = [s.get("run", "") for s in job["steps"]]
    assert "npm ci --no-audit --no-fund" in laeufe, "nur aus der Sperrdatei"
    assert laeufe.index("npm test") < laeufe.index("npm run dist"), "erst die Tests, dann bauen"
    assert any("loxos-v$v" in r for r in laeufe), "Tag muss zur Version passen"
    ausloeser = wf.get("on") or wf.get(True)    # yaml liest "on" als True
    assert ausloeser["push"]["tags"] == ["loxos-v*"]


def test_schwelle_gleich_der_huelle():
    """Ab welchem Seitenverhaeltnis ein Schirm ein Streifen ist, steht einmal im
    Server (STREIFEN_AB, /api/meta) und einmal in der Huelle: beide gleich."""
    from bento_format import STREIFEN_AB
    js = (LOXOS / "src" / "monitor.js").read_text(encoding="utf-8")
    assert STREIFEN_AB == float(re.search(r"const STREIFEN_AB = ([\d.]+);", js).group(1))
