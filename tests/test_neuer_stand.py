"""Stand des Servers fuer das Neuladen nach einem Update: server_stand() ist
der Commit aus bin/version.json (ohne ihn leer), /api/devices nennt ihn
neben den Geraeten. Dass Visu und Konfigurator damit neu laden, pruefen
tests/browser/test_neuer_stand_browser.py."""
import asyncio
import json

from aiohttp.test_utils import make_mocked_request

from lox import diagnosedaten, routen, W


def test_stand_ist_der_commit(monkeypatch):
    monkeypatch.setitem(diagnosedaten.VERSION, "inhalt", "")
    monkeypatch.setitem(diagnosedaten.VERSION, "commit", "abc123")
    assert routen.gemeinsam.server_stand() == "abc123"
    monkeypatch.setitem(diagnosedaten.VERSION, "commit", "")
    assert routen.gemeinsam.server_stand() == ""


def test_ohne_commit_die_kennung_des_inhalts(monkeypatch):
    """Lokaler Build ohne Git (docker compose up --build): der Pruefwert des Codes."""
    monkeypatch.setitem(diagnosedaten.VERSION, "commit", "")
    monkeypatch.setitem(diagnosedaten.VERSION, "inhalt", "0123456789abcdef")
    assert routen.gemeinsam.server_stand() == "0123456789abcdef"
    monkeypatch.setitem(diagnosedaten.VERSION, "commit", "abc123")
    assert routen.gemeinsam.server_stand() == "abc123", "ein Commit geht vor"


def test_geraeteliste_nennt_den_stand(monkeypatch):
    monkeypatch.setitem(diagnosedaten.VERSION, "commit", "abc123")
    app = W.App({"host": "", "port": 80})
    r = make_mocked_request("GET", "/api/devices", app={"app": app})
    d = json.loads(asyncio.run(W.api_devices_get(r)).body)
    assert d["stand"] == "abc123"
    assert {k: v for k, v in d.items() if k != "stand"} == app.device_list()
