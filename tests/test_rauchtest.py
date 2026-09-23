"""Rauchtest wie im Container: Server als eigener Prozess starten, ohne
erreichbaren Miniserver. Alle Oberflaechen und die Lese-APIs muessen trotzdem
antworten, und im Log darf kein Stacktrace stehen."""
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from lox import ROOT

ROUTEN = ["/", "/config", "/settings", "/i18n.js", "/api/settings", "/api/meta", "/api/types"]


def _freier_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as err:
        return err.code


def test_server_startet_ohne_miniserver(tmp_path):
    port = _freier_port()
    env = dict(os.environ, LOXPANEL_PORT=str(port), LOXPANEL_MS_HOST="127.0.0.1", LOXPANEL_MS_PORT="1",
               LOXPANEL_MS_USER="test", LOXPANEL_MS_PASS="test", PYTHONUNBUFFERED="1")
    log = tmp_path / "server.log"
    with open(log, "w") as out:
        proc = subprocess.Popen([sys.executable, str(ROOT / "bin" / "webvisu.py")], cwd=ROOT, env=env,
                                stdout=out, stderr=subprocess.STDOUT)
    try:
        basis = f"http://127.0.0.1:{port}"
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                if _get(basis + "/api/settings") == 200:
                    break
            except OSError:
                pass
            time.sleep(0.25)
        assert proc.poll() is None, "Server beendet sich:\n" + log.read_text()
        antworten = {r: _get(basis + r) for r in ROUTEN}
        assert antworten == {r: 200 for r in ROUTEN}, antworten
        time.sleep(6)   # ein Verbindungsversuch zum Miniserver scheitert in der Zeit sicher
    finally:
        proc.terminate()
        proc.wait(10)
    text = log.read_text()
    assert "Traceback" not in text, text
    assert "neuer Versuch in 5s" in text, text
