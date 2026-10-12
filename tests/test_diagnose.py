"""Diagnosepaket (GET /api/diagnose, bin/diagnose.py).

Das ZIP soll eine Fehlersuche mit einem Klick beginnen lassen: Version,
Verbindungen, Geraet und Ansicht, Einstellungen und die letzten Log-Zeilen.
Die Route hat keine Anmeldung, darum der wichtigste Test: Kein Geheimnis
verlaesst den Server - weder aus den Einstellungsdateien (Kennwoerter,
Kalender-Abos, Standort) noch aus dem Speicher (Token) noch aus dem Log, auch
nicht URL-kodiert oder als Zugang in einer Adresse. Alle Tests arbeiten im
umgeleiteten Config-Ordner (Fixture cfg_ordner)."""
import asyncio
import io
import json
import logging
import zipfile
from urllib.parse import quote, quote_plus

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from lox import W, anlage

import diagnose

GEHEIM = {"ms": "Ms-Geheim-123", "mqtt": "Mqtt-Geheim-456", "tuer": "Tür Geheim/789",
          "fully": "Fully-Geheim-000", "token": "Token-Geheim-xyz",
          "google": "private-0a1b2c3d4e5f", "icloud": "GEHEIMERPFAD42"}
ORT = ("48.20823", "16.37381")
CFG = {"miniserver": {"host": "10.0.0.5", "user": "visu", "pass": GEHEIM["ms"], "port": 443},
       "mqtt": {"host": "127.0.0.1", "user": "lp", "pass": GEHEIM["mqtt"]},
       "intercom": {"IC": {"url": "http://cam.lan/mjpeg", "user": "tuer", "pass": GEHEIM["tuer"]}},
       "calendar": {"sources": [{"name": "Familie", "color": "#e0a24d",
                                 "url": f"https://calendar.google.com/calendar/ical/x%40gmail.com/{GEHEIM['google']}/basic.ics"}],
                    "ical_url": f"webcal://p01-caldav.icloud.com/published/2/{GEHEIM['icloud']}",
                    "holiday_url": "", "lat": float(ORT[0]), "lon": float(ORT[1])}}
PANELS = {"panels": {"wohnen": {"title": "Wohnen", "tabs": ["favoriten", "raeume"],
                                "ui": {"tileSet": "touch", "tileHue": 160}}},
          "devices": {"Küche": {"auto": True, "modes": {"Tag": "wohnen"},
                                "display": {"driver": "fully", "host": "10.0.0.9", "port": 2323,
                                            "password": GEHEIM["fully"]}}}}
THEME = {"ui": {"tabs": ["favoriten"], "lang": "de"}}
STRUKTUR = {**anlage({"S1": {"name": "Stehlampe", "type": "Switch", "uuidAction": "S1", "room": "r1",
                             "cat": "c1", "states": {"active": "s1"}}}),
            "msInfo": {"miniserverType": 2, "msName": "Haus", "projectName": "Projekt Haus",
                       "latitude": 48.2, "longitude": 16.3},
            "lastModified": "2026-10-01 12:00:00"}


def _schreiben(ordner):
    for name, doc in (("loxpanel.cfg", CFG), ("panels.json", PANELS), ("theme.json", THEME)):
        (ordner / name).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _holen(cfg_ordner, pfad: str):
    """App aus dem Config-Ordner, ein Log-Eintrag mit Geheimnissen, dann pfad
    abrufen -> (Status, Kopfzeilen, {Datei: Text} oder JSON)."""
    _schreiben(cfg_ordner)
    app = W.App(W._config(), W._audio_config(), W._audiometa_config())
    app._apply_structure(STRUKTUR)
    app.jwt = GEHEIM["token"]
    wurzel = logging.getLogger()
    wurzel.addHandler(diagnose.LOG)
    try:
        logging.getLogger("loxpanel.test").warning(
            "Anmeldung mit %s an http://tuer:%s@10.0.0.9/x, Token %s, kodiert %s %s %s",
            GEHEIM["ms"], GEHEIM["mqtt"], GEHEIM["token"], quote(GEHEIM["tuer"]),
            quote(GEHEIM["tuer"], safe=""), quote_plus(GEHEIM["tuer"]))

        async def lauf():
            ui = web.Application()
            ui["app"] = app
            ui.router.add_get("/api/diagnose", W.api_diagnose)
            async with TestClient(TestServer(ui)) as c:
                r = await c.get(pfad)
                body = await r.read()
                return r.status, dict(r.headers), body
        status, kopf, body = asyncio.run(lauf())
    finally:
        wurzel.removeHandler(diagnose.LOG)
    if status != 200:
        return status, kopf, json.loads(body)
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        return status, kopf, {n: z.read(n).decode("utf-8") for n in z.namelist()}


def test_kein_geheimnis_verlaesst_den_server(cfg_ordner):
    status, kopf, dateien = _holen(cfg_ordner, "/api/diagnose?device=K%C3%BCche")
    assert status == 200 and kopf["Content-Type"] == "application/zip"
    assert sorted(dateien) == ["diagnose.json", "diagnose.md", "einstellungen/loxpanel.cfg",
                               "einstellungen/panels.json", "einstellungen/theme.json", "log.txt"]
    for name, text in dateien.items():
        for was, g in GEHEIM.items():
            # im Test nachgerechnet, nicht bei diagnose.kodierungen() gefragt
            for form in (g, quote(g), quote(g, safe=""), quote_plus(g), quote_plus(g, safe="")):
                assert form not in text, (name, was, form)
        for zahl in ORT:
            assert zahl not in text, (name, zahl)
    # was bleibt: der Host der Abos, der Hinweis an Stelle der Werte, die Log-Zeile
    cfg = json.loads(dateien["einstellungen/loxpanel.cfg"])
    assert cfg["calendar"]["sources"][0]["url"] == f"https://calendar.google.com/{diagnose.ENTFERNT}"
    assert cfg["calendar"]["ical_url"] == f"webcal://p01-caldav.icloud.com/{diagnose.ENTFERNT}"
    assert cfg["calendar"]["holiday_url"] == "", "leer bleibt leer"
    assert cfg["miniserver"]["pass"] == diagnose.ENTFERNT and cfg["miniserver"]["user"] == "visu"
    assert "Anmeldung mit (entfernt) an http://(entfernt)@10.0.0.9/x" in dateien["log.txt"]


def test_paket_eines_geraets(cfg_ordner):
    status, kopf, dateien = _holen(cfg_ordner, "/api/diagnose?device=K%C3%BCche")
    assert kopf["Content-Disposition"].startswith('attachment; filename="loxpanel-diagnose-K_che-')
    d = json.loads(dateien["diagnose.json"])
    assert d["version"] == json.loads(json.dumps(W.VERSION))
    assert d["geraet"]["name"] == "Küche" and d["geraet"]["eingerichtet"] and not d["geraet"]["online"]
    assert d["geraet"]["einstellungen"]["display"]["password"] == diagnose.ENTFERNT
    assert "geraete" not in d
    ms = d["miniserver"]
    assert ms["host"] == "10.0.0.5" and ms["struktur"] and ms["bausteine"] == 1
    assert ms["typ"] == "Miniserver (Gen 2)" and ms["projekt"] == "Projekt Haus"
    assert not ms["verbunden"]
    md = dateien["diagnose.md"]
    assert md.startswith("# LoxPanel-Diagnose vom ") and "## Zusammenfassung" in md
    assert "- Miniserver 10.0.0.5 nicht verbunden (noch kein Versuch abgeschlossen)." in md
    assert "- **eingerichtet:** ja" in md and "- **typ:** Miniserver (Gen 2)" in md
    assert "- Gerät „Küche“ (browser) offline." in md


def test_paket_des_servers_nennt_alle_geraete(cfg_ordner):
    status, kopf, dateien = _holen(cfg_ordner, "/api/diagnose")
    d = json.loads(dateien["diagnose.json"])
    assert status == 200 and "-server-" in kopf["Content-Disposition"]
    assert d["geraete"] == [{"name": "Küche", "typ": "browser", "online": False, "ansicht": ""}]
    assert "geraet" not in d and "## Alle Geräte" in dateien["diagnose.md"]


def test_unbekanntes_geraet(cfg_ordner):
    status, _, antwort = _holen(cfg_ordner, "/api/diagnose?device=Gibtsnicht")
    assert status == 404 and antwort["ok"] is False


def test_bereinigen():
    daten, gefunden = diagnose.bereinigen({
        "a": {"pass": "x1234", "Password": "", "token": None, "user": "u", "flag": True},
        "calendar": {"sources": [{"url": "https://h.example/geheim/pfad.ics", "name": "n"}], "lat": 1.5},
        "url": "http://user:pw9876@host/p", "liste": ["https://h/a", "kein text"]})
    assert daten == {"a": {"pass": diagnose.ENTFERNT, "Password": "", "token": None, "user": "u", "flag": True},
                     "calendar": {"sources": [{"url": f"https://h.example/{diagnose.ENTFERNT}", "name": "n"}],
                                  "lat": diagnose.ENTFERNT},
                     "url": f"http://{diagnose.ENTFERNT}@host/p", "liste": ["https://h/a", "kein text"]}
    assert gefunden == {"x1234", "https://h.example/geheim/pfad.ics", "user:pw9876"}
    # eine url ausserhalb des Kalenders bleibt (Kamera-Adresse ohne Zugang)
    assert diagnose.bereinigen({"intercom": {"url": "http://cam/mjpeg"}})[0] == {"intercom": {"url": "http://cam/mjpeg"}}


def test_schwaerzen():
    text = "a p@ss wort! b p%40ss%20wort%21 c p%40ss+wort%21 d http://u:v@h/ e 123"
    assert diagnose.schwaerzen(text, {"p@ss wort!", "123"}) == \
        "a (entfernt) b (entfernt) c (entfernt) d http://(entfernt)@h/ e 123", "zu kurz: bleibt"


def test_log_puffer_haelt_menge_und_alter():
    puffer = diagnose.LogPuffer(zeilen=3)
    lg = logging.getLogger("loxpanel.puffertest")
    lg.addHandler(puffer)
    try:
        for i in range(5):
            lg.warning("Zeile %d", i)
    finally:
        lg.removeHandler(puffer)
    zeilen = puffer.zeilen()
    assert [z.rsplit(": ", 1)[1] for z in zeilen] == ["Zeile 2", "Zeile 3", "Zeile 4"]
    assert "WARNING loxpanel.puffertest" in zeilen[0]
    jetzt = puffer._eintraege[-1][0]
    assert puffer.zeilen(minuten=1, jetzt=jetzt + 61) == []
    assert len(puffer.zeilen(minuten=1, jetzt=jetzt + 59)) == 3


def test_zusammenfassung_nennt_jede_verbindung():
    s = diagnose.zusammenfassung({
        "miniserver": {"host": "ms", "struktur": True, "verbunden": False, "weg_seit": 1790000000,
                       "fehler": "Zeitlimit"},
        "audioserver": [{"host": "as1", "verbunden": True, "gekoppelt": True, "angemeldet": True},
                        {"host": "as2", "verbunden": False}],
        "server": {"aufgaben": {"miniserver": "läuft", "front": "beendet"}, "panels": 2}})
    assert s[0].startswith("Miniserver ms seit ") and s[0].endswith("(Fehler: Zeitlimit).")
    assert s[1:] == ["Audioserver as1 verbunden (gekoppelt, angemeldet).", "Audioserver as2 nicht verbunden.",
                     "Hintergrundaufgaben beendet: front (Neustart nötig).", "2 Panel-Verbindung(en) offen."]
