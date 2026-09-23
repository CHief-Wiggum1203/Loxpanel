"""Unraid-Betrieb (TODO.md Block 5): Zustand fuer den Docker-HEALTHCHECK,
Einstellungen als ZIP ohne Kennwoerter, Log-Level per Umgebungsvariable."""
import asyncio
import io
import json
import logging
import zipfile

import aiohttp
from aiohttp import web

from lox import W, serve


def test_health_meldet_beendete_aufgabe():
    async def lauf():
        app = W.App({"host": "", "port": 80})
        ui = web.Application()
        ui["app"] = app
        ui.router.add_get("/api/health", W.api_health)

        async def ewig():
            await asyncio.sleep(3600)

        async def kaputt():
            raise RuntimeError("abgestuerzt")
        ui["tasks"] = {"miniserver": asyncio.create_task(ewig()), "broadcaster": asyncio.create_task(ewig())}
        ui["started"] = 0.0
        runner, port = await serve(ui)
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"http://127.0.0.1:{port}/api/health") as r:
                    gesund, d = r.status, await r.json()
                assert gesund == 200 and d["ok"] and d["miniserver"] is False, d   # Miniserver weg != ungesund
                assert d["tasks"] == {"miniserver": "läuft", "broadcaster": "läuft"}
                ui["tasks"]["broadcaster"].cancel()
                ui["tasks"]["broadcaster"] = asyncio.create_task(kaputt())
                await asyncio.sleep(0.05)
                async with s.get(f"http://127.0.0.1:{port}/api/health") as r:
                    krank, d = r.status, await r.json()
                assert krank == 503 and not d["ok"]
                assert d["tasks"]["broadcaster"] == "beendet: RuntimeError('abgestuerzt')"
        finally:
            for t in ui["tasks"].values():
                t.cancel()
            await runner.cleanup()
    asyncio.run(lauf())


def _zip_lesen(daten: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(daten)) as z:
        return {n: z.read(n).decode("utf-8") for n in z.namelist()}


def test_backup_ohne_kennwoerter(tmp_path):
    (tmp_path / "loxpanel.cfg").write_text(json.dumps({
        "miniserver": {"host": "10.0.0.5", "user": "visu", "pass": "GEHEIM-MS"},
        "intercom": {"u1": {"url": "http://cam", "user": "admin", "pass": "GEHEIM-CAM"}, "u2": {"pass": ""}},
        "calendar": {"sources": [{"name": "Familie", "url": "https://kal/ics"}]}}), encoding="utf-8")
    (tmp_path / "panels.json").write_text(json.dumps({
        "panels": {"wohnen": {"title": "Wohnen"}},
        "devices": {"Tablet": {"driver": {"driver": "fully", "host": "10.0.0.9", "password": "GEHEIM-FULLY"}}}}),
        encoding="utf-8")
    (tmp_path / "theme.json").write_text('{"ui": {"accent": "#52b881"}}', encoding="utf-8")
    dateien = _zip_lesen(W._backup_zip(tmp_path))
    assert set(dateien) == {"loxpanel.cfg", "panels.json", "theme.json", "LIESMICH.txt"}
    alles = "".join(dateien.values())
    assert "GEHEIM" not in alles, "kein Kennwort im Backup"
    cfg = json.loads(dateien["loxpanel.cfg"])
    assert cfg["miniserver"] == {"host": "10.0.0.5", "user": "visu", "pass": ""}
    assert cfg["calendar"]["sources"][0]["url"] == "https://kal/ics"
    assert json.loads(dateien["panels.json"])["devices"]["Tablet"]["driver"]["host"] == "10.0.0.9"
    liesmich = dateien["LIESMICH.txt"]
    for pfad in ("loxpanel.cfg: miniserver.pass", "loxpanel.cfg: intercom.u1.pass",
                 "panels.json: devices.Tablet.driver.password"):
        assert pfad in liesmich
    assert "intercom.u2" not in liesmich, "leere Kennwoerter sind nichts Entferntes"


def test_backup_kaputte_datei_bleibt_draussen(tmp_path):
    (tmp_path / "loxpanel.cfg").write_text('{"miniserver": {"pass": "GEHEIM"', encoding="utf-8")   # abgeschnitten
    dateien = _zip_lesen(W._backup_zip(tmp_path))
    assert set(dateien) == {"LIESMICH.txt"} and "GEHEIM" not in dateien["LIESMICH.txt"]
    assert "Nicht enthalten, weil nicht lesbar: loxpanel.cfg" in dateien["LIESMICH.txt"]


def test_backup_route():
    async def lauf():
        ui = web.Application()
        ui.router.add_get("/api/backup", W.api_backup)
        runner, port = await serve(ui)
        try:
            async with aiohttp.ClientSession() as s, s.get(f"http://127.0.0.1:{port}/api/backup") as r:
                assert r.status == 200 and r.content_type == "application/zip"
                assert r.headers["Content-Disposition"].startswith('attachment; filename="loxpanel-einstellungen-')
                assert "LIESMICH.txt" in _zip_lesen(await r.read())
        finally:
            await runner.cleanup()
    asyncio.run(lauf())


def test_log_level(monkeypatch):
    for roh, level, warnt in (("", logging.INFO, False), ("debug", logging.DEBUG, False),
                              ("WARNING", logging.WARNING, False), ("laut", logging.INFO, True)):
        monkeypatch.setenv("LOXPANEL_LOG_LEVEL", roh)
        got, warnung = W._log_level()
        assert got == level and bool(warnung) == warnt, roh
    zugriff = logging.getLogger("aiohttp.access")
    vorher = (logging.getLogger().level, zugriff.level)
    try:
        monkeypatch.setenv("LOXPANEL_LOG_LEVEL", "INFO")
        W._logging_einrichten()
        assert not zugriff.isEnabledFor(logging.INFO), "Zugriffs-Log im Normalbetrieb aus"
        monkeypatch.setenv("LOXPANEL_LOG_LEVEL", "DEBUG")
        W._logging_einrichten()
        assert zugriff.isEnabledFor(logging.INFO), "bei DEBUG sichtbar"
    finally:
        logging.getLogger().setLevel(vorher[0])
        zugriff.setLevel(vorher[1])
