"""Sicherung einspielen (POST /api/restore): die ZIP aus /api/backup lesen,
alles pruefen, erst dann schreiben und den laufenden Server auffrischen.
Kennwoerter stehen nicht in der Sicherung; ein vorhandenes bleibt nur, wenn es
zum selben Ziel gehoert (Host, URL, Benutzer, Treiber). Alle Tests arbeiten im
umgeleiteten Config-Ordner (Fixture cfg_ordner)."""
import asyncio
import copy
import io
import json
import zipfile

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from lox import W, anlage

BAUSTEINE = {
    "PM": {"name": "Präsenz Küche", "type": "PresenceDetector", "uuidAction": "PM", "room": "r1", "cat": "c1",
           "states": {"active": "pm_a"}},
    "IC": {"name": "Haustür", "type": "Intercom", "uuidAction": "IC", "room": "r1", "cat": "c1",
           "states": {"bell": "ic_b"}},
}
MS = {"host": "10.0.0.5", "user": "visu", "pass": "GEHEIM-MS", "port": 443, "verify_tls": False}
CFG = {"miniserver": MS,
       "intercom": {"IC": {"url": "http://cam/mjpeg", "user": "admin", "pass": "GEHEIM-CAM"}},
       "night": {"control": "PM"},
       "calendar": {"sources": [{"name": "Familie", "url": "https://kal/ics", "color": "#e0a24d"}],
                    "lat": 47.07, "lon": 15.44, "days": 14},
       "audiometa": {"enabled": True}}
PANELS = {"panels": {"wohnen": {"title": "Wohnen", "tabs": ["favoriten", "raeume"]}},
          "devices": {"Küche": {"auto": True, "modes": {"Tag": "wohnen"}, "presence": "PM",
                                "display": {"driver": "fully", "host": "10.0.0.9", "port": 2323,
                                            "password": "GEHEIM-FULLY"}}}}
THEME = {"states": {"active": "#e0a24d"}, "categories": {"Beleuchtung": "#e0a24d"},
         "ui": {"iconSize": 40, "dpmsOff": 120, "nightDim": 40, "tabs": ["favoriten", "zentral"], "lang": "de"}}


def _schreiben(ordner, cfg=CFG, panels=PANELS, theme=THEME):
    ordner.mkdir(exist_ok=True)
    for name, doc in (("loxpanel.cfg", cfg), ("panels.json", panels), ("theme.json", theme)):
        if doc is not None:
            (ordner / name).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _sicherung_von(ordner, **dateien) -> bytes:
    """Sicherung eines anderen Servers: dessen Dateien schreiben, /api/backup-ZIP bauen."""
    _schreiben(ordner, **dateien)
    return W._backup_zip(ordner)


def _lesen(ordner, name):
    return json.loads((ordner / name).read_text(encoding="utf-8"))


def _app():
    app = W.App(W._config(), W._audio_config(), W._audiometa_config())
    app._apply_structure(anlage(BAUSTEINE))
    return app


def _ohne_verbindung(app, fehler=None):
    """reconnect() ersetzen: kein echter Miniserver; merkt sich den Zugang."""
    aufrufe = []

    async def reconnect():
        aufrufe.append(W._config())
        if fehler:
            raise ValueError(fehler)
        return 0
    app.reconnect = reconnect
    return aufrufe


async def _einspielen(app, daten):
    return await W._sicherung_schreiben(app, W._sicherung_pruefen(app, *W._sicherung_lesen(daten)))


def _zip(dateien: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, inhalt in dateien.items():
            z.writestr(name, inhalt if isinstance(inhalt, (bytes, str)) else json.dumps(inhalt))
    return buf.getvalue()


def test_rundlauf_behaelt_kennwoerter_und_frischt_auf(cfg_ordner):
    _schreiben(cfg_ordner)
    sicherung = W._backup_zip(cfg_ordner)
    with zipfile.ZipFile(io.BytesIO(sicherung)) as z:
        assert "GEHEIM" not in "".join(z.read(n).decode("utf-8") for n in z.namelist())
    # danach aendert sich hier einiges, das die Sicherung zurueckholt
    _schreiben(cfg_ordner, cfg={**CFG, "night": {"control": ""}},
               panels={"panels": {"anders": {"title": "Anders"}}, "devices": PANELS["devices"]},
               theme={"ui": {"iconSize": 20}})

    async def lauf():
        app = _app()
        aufrufe = _ohne_verbindung(app)
        return app, await _einspielen(app, sicherung), aufrufe
    app, j, aufrufe = asyncio.run(lauf())

    assert j["ok"] and j["dateien"] == ["loxpanel.cfg", "panels.json", "theme.json"], j
    assert j["kennwoerter"]["fehlen"] == [] and j["nichtEnthalten"] == []
    assert sorted(z["art"] for z in j["kennwoerter"]["behalten"]) == ["display", "kamera", "miniserver"]
    assert {"art": "kamera", "name": "Haustür"} in j["kennwoerter"]["behalten"]
    assert {"art": "display", "name": "Küche"} in j["kennwoerter"]["behalten"]
    assert j["miniserver"] == "unveraendert" and aufrufe == [], "gleicher Zugang: Verbindung bleibt"

    cfg = _lesen(cfg_ordner, "loxpanel.cfg")
    assert cfg["miniserver"] == MS and cfg["intercom"]["IC"]["pass"] == "GEHEIM-CAM"
    assert cfg["night"] == {"control": "PM"}
    pj = _lesen(cfg_ordner, "panels.json")
    assert set(pj["panels"]) == {"wohnen"}
    assert pj["devices"]["Küche"]["display"]["password"] == "GEHEIM-FULLY"
    ui = _lesen(cfg_ordner, "theme.json")["ui"]
    assert ui["dpmsOff"] == 120 and ui["nightDim"] == 40 and ui["tabs"] == ["favoriten", "zentral"], \
        "auch was die Darstellungs-Seite nicht setzt, bleibt erhalten"

    # der laufende Server ist aufgefrischt, ohne Neustart
    assert set(app.panels) == {"wohnen"} and app.devices["Küche"]["presence"] == "PM"
    assert app.presence_map == {"pm_a": ["Küche"]}
    assert app.night_cfg == {"control": "PM"} and app.intercom_cfg["IC"]["pass"] == "GEHEIM-CAM"
    assert app.calendar_cfg["sources"][0]["name"] == "Familie"
    assert app._front_refresh.is_set() and app._front_cal_due == 0.0
    assert app.theme["ui"]["dpmsOff"] == 120 and app.theme["states"]["active"] == "#e0a24d"

    # der bisherige Stand liegt als .bak daneben
    assert _lesen(cfg_ordner, "loxpanel.cfg.bak")["night"] == {"control": ""}
    assert set(_lesen(cfg_ordner, "panels.json.bak")["panels"]) == {"anders"}
    assert _lesen(cfg_ordner, "theme.json.bak") == {"ui": {"iconSize": 20}}


def test_anderes_ziel_bekommt_kein_kennwort(cfg_ordner, tmp_path):
    _schreiben(cfg_ordner)
    fremd_panels = copy.deepcopy(PANELS)
    fremd_panels["devices"]["Küche"]["display"]["host"] = "10.0.0.99"
    sicherung = _sicherung_von(
        tmp_path / "anderer-server",
        cfg={**CFG, "miniserver": {**MS, "host": "10.9.9.9"},
             "intercom": {"IC": {"url": "http://andere-kamera/mjpeg", "user": "admin", "pass": "X"}}},
        panels=fremd_panels)

    async def lauf():
        app = _app()
        aufrufe = _ohne_verbindung(app)
        return await _einspielen(app, sicherung), aufrufe
    j, aufrufe = asyncio.run(lauf())

    assert j["ok"] and j["kennwoerter"]["behalten"] == []
    assert sorted(z["art"] for z in j["kennwoerter"]["fehlen"]) == ["display", "kamera", "miniserver"]
    assert j["miniserver"] == "kein_kennwort" and aufrufe == []
    cfg = _lesen(cfg_ordner, "loxpanel.cfg")
    assert cfg["miniserver"]["host"] == "10.9.9.9" and cfg["miniserver"]["pass"] == ""
    assert cfg["intercom"]["IC"]["pass"] == ""
    assert _lesen(cfg_ordner, "panels.json")["devices"]["Küche"]["display"]["password"] == ""
    alles = "".join((cfg_ordner / n).read_text(encoding="utf-8") for n in W.BACKUP_FILES)
    assert "GEHEIM" not in alles, "kein Kennwort geht an ein anderes Ziel"


def test_sicherung_ohne_miniserver_behaelt_den_zugang(cfg_ordner, tmp_path):
    _schreiben(cfg_ordner)
    sicherung = _sicherung_von(tmp_path / "ohne", cfg={k: v for k, v in CFG.items() if k != "miniserver"},
                               panels=None, theme=None)

    async def lauf():
        app = _app()
        aufrufe = _ohne_verbindung(app)
        return await _einspielen(app, sicherung), aufrufe
    j, aufrufe = asyncio.run(lauf())

    assert j["ok"] and j["miniserver"] == "behalten" and aufrufe == []
    assert _lesen(cfg_ordner, "loxpanel.cfg")["miniserver"] == MS
    assert j["dateien"] == ["loxpanel.cfg"] and j["nichtEnthalten"] == ["panels.json", "theme.json"]
    assert _lesen(cfg_ordner, "panels.json") == PANELS, "nicht Enthaltenes bleibt stehen"


def test_zugang_aus_umgebungsvariablen_bleibt(cfg_ordner, tmp_path, monkeypatch):
    for k, v in (("HOST", "10.0.0.5"), ("USER", "visu"), ("PASS", "GEHEIM-ENV")):
        monkeypatch.setenv(f"LOXPANEL_MS_{k}", v)
    _schreiben(cfg_ordner, cfg={k: v for k, v in CFG.items() if k != "miniserver"})
    sicherung = _sicherung_von(tmp_path / "quelle")   # mit Miniserver-Abschnitt, Kennwort entfernt

    async def lauf():
        app = _app()
        _ohne_verbindung(app)
        return await _einspielen(app, sicherung)
    j = asyncio.run(lauf())

    assert j["ok"] and j["miniserver"] == "umgebung"
    assert "miniserver" not in _lesen(cfg_ordner, "loxpanel.cfg"), \
        "ein Abschnitt ohne Kennwort verdraengte sonst die Umgebungsvariablen"
    assert W._config()["pass"] == "GEHEIM-ENV"
    assert all(z["art"] != "miniserver" for z in j["kennwoerter"]["fehlen"])


@pytest.mark.parametrize("fehler", [None, "Anmeldung abgelehnt"])
def test_geaenderter_zugang_verbindet_neu(cfg_ordner, tmp_path, fehler):
    _schreiben(cfg_ordner)
    sicherung = _sicherung_von(tmp_path / "quelle", cfg={**CFG, "miniserver": {**MS, "port": 80}})

    async def lauf():
        app = _app()
        aufrufe = _ohne_verbindung(app, fehler)
        return await _einspielen(app, sicherung), aufrufe
    j, aufrufe = asyncio.run(lauf())

    assert len(aufrufe) == 1 and aufrufe[0]["port"] == 80 and aufrufe[0]["pass"] == "GEHEIM-MS", \
        "gleicher Host und Benutzer: das Kennwort bleibt, der neue Port verbindet neu"
    assert j["ok"], "die Datei ist geschrieben, auch wenn die Verbindung scheitert"
    if fehler:
        assert j["miniserver"] == "fehler" and j["miniserverFehler"] == fehler
    else:
        assert j["miniserver"] == "verbunden"


KAPUTT = [
    ("keine-zip", b"kein zip", "keine ZIP-Datei"),
    ("fremde-zip", _zip({"bild.png": b"x"}), "Keine LoxPanel-Sicherung"),
    ("kein-json", _zip({"loxpanel.cfg": "{kaputt"}), "loxpanel.cfg ist kein gültiges JSON"),
    ("liste-statt-objekt", _zip({"panels.json": []}), "panels.json enthält kein JSON-Objekt"),
    ("nan", _zip({"theme.json": '{"ui": {"dpmsOff": NaN}}'}), "theme.json ist kein gültiges JSON"),
    ("unendlich", _zip({"theme.json": '{"ui": {"dpmsOff": 1e400}}'}), "theme.json: ui.dpmsOff ist keine gültige Zahl"),
    ("riesenzahl", _zip({"panels.json": '{"panels": {"a": {"ui": {"scale": 1' + "0" * 30 + '}}}}'}),
     "panels.json: panels.a.ui.scale ist keine gültige Zahl"),
    ("miniserver-liste", _zip({"loxpanel.cfg": {"miniserver": []}}), "„miniserver“ muss ein Objekt sein"),
    ("intercom-null", _zip({"loxpanel.cfg": {"intercom": None}}), "„intercom“ muss ein Objekt sein"),
    ("port-text", _zip({"loxpanel.cfg": {"miniserver": {"host": "h", "port": "abc"}}}), "miniserver.port"),
    ("nacht-liste", _zip({"loxpanel.cfg": {"night": {"control": ["PM"]}}}), "night.control"),
    ("kalender-url", _zip({"loxpanel.cfg": {"calendar": {"sources": [{"url": 5}]}}}), "calendar.sources[0]"),
    ("kamera-doppelpunkt", _zip({"loxpanel.cfg": {"intercom": {"IC": {"url": "http://c", "user": "a:b"}}}}),
     "intercom.IC"),
    ("profil-tabs-zahl", _zip({"panels.json": {"panels": {"wohnen": {"tabs": 5}}}}), "Profil „wohnen“"),
    ("geraet-modes-liste", _zip({"panels.json": {"panels": {}, "devices": {"Küche": {"modes": ["Tag"]}}}}),
     "Gerät „Küche“"),
    ("theme-ui-liste", _zip({"theme.json": {"ui": ["x"]}}), "„ui“ muss ein Objekt sein"),
    ("doppelt", _zip({"a/loxpanel.cfg": {}, "b/loxpanel.cfg": {}}), "loxpanel.cfg steckt mehrmals"),
]


@pytest.mark.parametrize("daten, meldung", [k[1:] for k in KAPUTT], ids=[k[0] for k in KAPUTT])
def test_kaputte_sicherung_wird_abgelehnt_und_schreibt_nichts(cfg_ordner, daten, meldung):
    _schreiben(cfg_ordner)
    vorher = {p.name: p.read_bytes() for p in cfg_ordner.iterdir()}

    async def lauf():
        ui = web.Application()
        ui["app"] = _app()
        ui.router.add_post("/api/restore", W.api_restore)
        async with TestClient(TestServer(ui)) as cl:
            r = await cl.post("/api/restore", data=daten, headers={"Content-Type": "application/zip"})
            return r.status, await r.json()
    status, j = asyncio.run(lauf())

    assert status == 400 and not j["ok"] and meldung in j["error"], j
    assert {p.name: p.read_bytes() for p in cfg_ordner.iterdir()} == vorher, "nichts geschrieben, keine .bak"


def test_zu_grosse_datei_in_der_zip(cfg_ordner):
    daten = _zip({"loxpanel.cfg": " " * (W.RESTORE_MAX_DATEI + 1)})
    with pytest.raises(ValueError, match="zu groß"):
        W._sicherung_lesen(daten)


def test_neu_gepackte_zip_mit_ordner_und_mac_resten(cfg_ordner):
    """Entpackt und am Mac neu gepackt: Ordner davor, __MACOSX-Reste, keine
    sicherung.json. Leere Kennwoerter neben Host/URL gelten als entfernt."""
    ohne = {**CFG, "miniserver": {**MS, "pass": ""},
            "intercom": {"IC": {"url": "http://cam/mjpeg", "user": "admin", "pass": ""}}}
    daten = _zip({"loxpanel-einstellungen/loxpanel.cfg": ohne,
                  "__MACOSX/loxpanel-einstellungen/._loxpanel.cfg": b"\x00\x05\x16\x07",
                  "loxpanel-einstellungen/LIESMICH.txt": "Hinweise"})

    async def lauf():
        app = _app()
        _ohne_verbindung(app)
        return await _einspielen(app, daten)
    j = asyncio.run(lauf())

    assert j["ok"] and j["dateien"] == ["loxpanel.cfg"] and j["nichtEnthalten"] == ["panels.json", "theme.json"]
    assert sorted(z["art"] for z in j["kennwoerter"]["fehlen"]) == ["kamera", "miniserver"]
    assert j["miniserver"] == "kein_kennwort"


def test_aeltere_sicherung_ohne_vermerk_behaelt_kennwoerter(cfg_ordner):
    _schreiben(cfg_ordner)
    with zipfile.ZipFile(io.BytesIO(W._backup_zip(cfg_ordner))) as z:
        alt = _zip({n: z.read(n) for n in z.namelist() if n != W.BACKUP_VERMERK})

    async def lauf():
        app = _app()
        _ohne_verbindung(app)
        return await _einspielen(app, alt)
    j = asyncio.run(lauf())

    assert j["ok"] and j["kennwoerter"]["fehlen"] == []
    assert sorted(z["art"] for z in j["kennwoerter"]["behalten"]) == ["display", "kamera", "miniserver"]
    assert _lesen(cfg_ordner, "loxpanel.cfg")["miniserver"]["pass"] == "GEHEIM-MS"


def test_nicht_uebernommenes_wird_gemeldet(cfg_ordner, tmp_path):
    sicherung = _sicherung_von(
        tmp_path / "quelle", cfg=None,
        panels={"panels": {"wohnen": {"title": "Wohnen", "tabs": ["favoriten", "gibtsnicht"]}}},
        theme={"ui": {"iconSize": 40, "gibtsnicht": 1, "lang": "xx"}})

    async def lauf():
        app = _app()
        return await _einspielen(app, sicherung)
    j = asyncio.run(lauf())

    assert j["ok"] and j["miniserver"] == "", "ohne loxpanel.cfg bleibt der Miniserver unberuehrt"
    weg = " | ".join(j["verworfen"])
    assert "Wohnen: tabs: gibtsnicht" in weg and "Darstellung: ui.gibtsnicht" in weg and "ui.lang" in weg, weg
    assert _lesen(cfg_ordner, "theme.json")["ui"] == {"iconSize": 40}


def test_audioserver_wechselt_ohne_neustart(cfg_ordner, tmp_path):
    _schreiben(cfg_ordner)
    sicherung = _sicherung_von(tmp_path / "quelle", cfg={**CFG, "audio": {"host": "10.0.0.7", "port": 7091}})

    async def lauf():
        app = _app()
        _ohne_verbindung(app)
        assert app.audio is None
        j = await _einspielen(app, sicherung)
        backend, cfg = app.audio, app.audio_cfg
        await backend.close()
        return j, backend, cfg
    j, backend, cfg = asyncio.run(lauf())

    assert j["ok"] and cfg == {"host": "10.0.0.7", "port": 7091} and backend is not None


def test_schreibfehler_wird_gemeldet(cfg_ordner, tmp_path, monkeypatch):
    _schreiben(cfg_ordner)
    sicherung = _sicherung_von(tmp_path / "quelle", panels={"panels": {"neu": {"title": "Neu"}}})

    def voll(cfg):
        raise OSError("Kein Platz auf dem Gerät")
    monkeypatch.setattr(W, "_write_cfg", voll)

    async def lauf():
        app = _app()
        return await _einspielen(app, sicherung)
    j = asyncio.run(lauf())

    assert not j["ok"] and j["dateien"] == [] and "Kein Platz" in j["error"]
    assert _lesen(cfg_ordner, "panels.json") == PANELS, "nach dem Fehler wird nichts weiter geschrieben"


def test_route_leer_und_zu_gross(cfg_ordner):
    async def lauf():
        ui = web.Application()
        ui["app"] = _app()
        ui.router.add_post("/api/restore", W.api_restore)
        async with TestClient(TestServer(ui)) as cl:
            leer = await cl.post("/api/restore", data=b"")
            gross = await cl.post("/api/restore", data=b"x" * (1024 * 1024 + 1))
            return (leer.status, await leer.json()), (gross.status, await gross.json())
    (s1, j1), (s2, j2) = asyncio.run(lauf())
    assert s1 == 400 and j1["error"] == "Keine Datei erhalten."
    assert s2 == 413 and "zu groß" in j2["error"], "auch die Grenze des Servers antwortet mit JSON"


def test_route_spielt_ein(cfg_ordner, tmp_path):
    _schreiben(cfg_ordner)
    sicherung = _sicherung_von(tmp_path / "quelle", panels={"panels": {"neu": {"title": "Neu"}}})

    async def lauf():
        app = _app()
        _ohne_verbindung(app)
        ui = web.Application()
        ui["app"] = app
        ui.router.add_post("/api/restore", W.api_restore)
        async with TestClient(TestServer(ui)) as cl:
            r = await cl.post("/api/restore", data=sicherung, headers={"Content-Type": "application/zip"})
            return r.status, await r.json(), app
    status, j, app = asyncio.run(lauf())
    assert status == 200 and j["ok"] and set(app.panels) == {"neu"}
