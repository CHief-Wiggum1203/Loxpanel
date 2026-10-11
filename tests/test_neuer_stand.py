"""Stand des Servers fuer das Neuladen nach einem Update: server_stand() ist
der Commit aus bin/version.json (ohne ihn leer), /api/devices nennt ihn
neben den Geraeten. Dass Visu und Konfigurator damit neu laden, pruefen
tests/browser/test_neuer_stand_browser.py."""
import asyncio
import json

from aiohttp.test_utils import make_mocked_request

from lox import W


def test_stand_ist_der_commit(monkeypatch):
    monkeypatch.setitem(W.VERSION, "commit", "abc123")
    assert W.server_stand() == "abc123"
    monkeypatch.setitem(W.VERSION, "commit", "")
    assert W.server_stand() == ""


def test_geraeteliste_nennt_den_stand(monkeypatch):
    monkeypatch.setitem(W.VERSION, "commit", "abc123")
    app = W.App({"host": "", "port": 80})
    r = make_mocked_request("GET", "/api/devices", app={"app": app})
    d = json.loads(asyncio.run(W.api_devices_get(r)).body)
    assert d["stand"] == "abc123"
    assert {k: v for k, v in d.items() if k != "stand"} == app.device_list()
