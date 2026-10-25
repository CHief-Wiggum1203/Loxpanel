"""LoxOS (Fork, docs/VISION.md): Bento-Seiten auf dem Server.

_view_bento() baut die view-Nachricht mit Raster und Zellen; Widget-Daten
stehen inline und kommen aus denselben Blockbauern wie bei den Panes. Die
Webseiten-Pruefung laeuft gegen einen echten HTTP-Server (aiohttp TestServer).
"""
from __future__ import annotations

import asyncio

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import bento
import konfig
from lox import EFM, HAUS_FAVORITEN, W, anlage, haus_anlage, raum_anlage
from verteilung import _Lesespur


def _app(struktur=None, states=None):
    if struktur is None:
        struktur, states = raum_anlage()
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    app.states = dict(states or {})
    return app


def _seite(app, bento_roh, picks=("S1", "S2", "S3"), **profil):
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["auswahl"], **profil,
                                               "pickTabs": [{"name": "Streifen", "picks": list(picks),
                                                             "bento": bento_roh}]}})
    return app._view_tab("auswahl", app.resolve_profile("p"))


def zelle(x, y, w=1, h=1, **inhalt):
    return {"x": x, "y": y, "w": w, "h": h, **inhalt}


# ---- Aufbau der Nachricht ----------------------------------------------------

def test_bento_seite_liefert_raster_und_zellen():
    v = _seite(_app(), {"cols": 6, "rows": 2, "cells": [zelle(0, 0, 1, 2, widget="clock"),
                                                        zelle(1, 0, 2, 1, ids=["S1", "S2"])]})
    assert v["t"] == "view" and v["tab"] == "auswahl" and v["title"] == "Streifen"
    assert v["bento"] == {"cols": 6, "rows": 2} and v["items"] == []
    uhr, kacheln = v["cells"]
    assert uhr == zelle(0, 0, 1, 2, widget="clock")
    assert [it["id"] for it in kacheln["items"]] == ["S1", "S2"]
    assert (kacheln["x"], kacheln["y"], kacheln["w"], kacheln["h"]) == (1, 0, 2, 1)


def test_bento_geht_vor_widget_und_kacheln():
    app = _app()
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["auswahl"], "pickTabs": [
        {"picks": ["S1"], "widget": "weather", "bento": {"cells": [zelle(0, 0, ids=["S1"])]}}]}})
    v = app._view_tab("auswahl", app.resolve_profile("p"))
    assert "widget" not in v and v["cells"][0]["items"][0]["id"] == "S1"


def test_ohne_bento_bleibt_die_seite_wie_sie_war():
    app = _app()
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["auswahl"],
                                               "pickTabs": [{"picks": ["S1"]}]}})
    v = app._view_tab("auswahl", app.resolve_profile("p"))
    assert "bento" not in v and [it["id"] for it in v["items"]] == ["S1"]


def test_tabmeta_kennt_bento_seiten():
    """Die Visu blaettert nur zwischen Bento-Seiten (bento.js bentoNachbar):
    tabMeta sagt ihr, welche Seiten der Leiste das sind."""
    app = _app()
    app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["auswahl", "favoriten", "auswahl2"],
                                               "pickTabs": [{"name": "A", "picks": ["S1"],
                                                             "bento": {"cells": [zelle(0, 0, ids=["S1"])]}},
                                                            {"name": "B", "picks": ["S2"]}]}})
    meta = app._tab_meta(["auswahl", "favoriten", "auswahl2"], app.resolve_profile("p"))
    assert meta["auswahl"]["bento"] is True
    assert "bento" not in meta["auswahl2"] and "favoriten" not in meta


def test_ausgeblendete_und_unbekannte_bausteine_fallen_aus_der_zelle():
    app = _app()
    v = _seite(app, {"cells": [zelle(0, 0, ids=["S1", "S2"]), zelle(1, 0, ids=["S3"])]},
               picks=("S1", "S2", "S3"), hide=["S2", "S3"])
    assert [[it["id"] for it in c["items"]] for c in v["cells"]] == [["S1"]], \
        "eine Zelle ohne sichtbare Bausteine faellt weg, ihr Platz bleibt frei"
    del app.controls["S1"]
    assert app._view_tab("auswahl", app.resolve_profile("p"))["cells"] == []


def test_leere_bento_seite_hat_keine_zellen():
    v = _seite(_app(), {"cols": 4, "rows": 1})
    assert v["bento"] == {"cols": 4, "rows": 1} and v["cells"] == []


# ---- Widgets inline ------------------------------------------------------------

def _efm_app():
    return _app(anlage({"F": EFM}), {"f-a0": 0.8, "f-a1": 3.2, "f-a2": 0.0, "f-a3": 1.2})


def test_energiefluss_steht_inline_wie_in_der_pane():
    app = _efm_app()
    v = _seite(app, {"cells": [zelle(0, 0, 2, 1, widget="energy:F")]}, picks=())
    assert v["cells"][0]["energy"] == app.energy_blocks("F")


def test_widget_ohne_quelle_bleibt_als_name_stehen():
    v = _seite(_efm_app(), {"cells": [zelle(0, 0, widget="energy:WEG")]}, picks=())
    assert v["cells"][0] == zelle(0, 0, widget="energy:WEG")


def test_verlauf_mit_standard_zeitraum(monkeypatch):
    app = _app()
    aufrufe = []
    monkeypatch.setattr(app, "chart_stack", lambda uu, rng: aufrufe.append((uu, rng)) or {"stack": []})
    v = _seite(app, {"cells": [zelle(0, 0, widget="chart:S1,S2")]})
    assert aufrufe == [(("S1", "S2"), bento.STAT_DEFAULT_RANGE)]
    assert v["cells"][0]["chart"] == {"stack": []}


def test_kamera_mit_werten_unter_dem_bild(monkeypatch):
    app = _app()
    monkeypatch.setattr(app, "intercom_blocks", lambda u: [{"type": "video", "u": u}])
    monkeypatch.setattr(app, "_gesichert", lambda u: u == "K1")
    v = _seite(app, {"cells": [zelle(0, 0, 2, 1, widget="camera:K1|S1,S2")]})
    c = v["cells"][0]
    assert c["camera"] == {"blocks": [{"type": "video", "u": "K1"}], "secured": True}
    assert [it["id"] for it in c["status"]] == ["S1", "S2"]


def test_audio_mit_pin_schutz(monkeypatch):
    app = _app()
    monkeypatch.setattr(app, "player_blocks", lambda z: [{"type": "player", "zone": z}])
    monkeypatch.setattr(app, "_gesichert", lambda u: False)
    c = _seite(app, {"cells": [zelle(0, 0, widget="player:Z1")]})["cells"][0]
    assert c["player"] == {"blocks": [{"type": "player", "zone": "Z1"}]}


def test_audio_zelle_traegt_raum_und_favoriten():
    """Die Zelle nennt den Loxone-Raum der Zone (ohne Raum ihren Namen) und
    traegt die Favoriten als favs-Block wie Pane und Detailseite."""
    struktur, states = haus_anlage()
    struktur["controls"]["AZ"]["name"] = "Musik"          # Zonenname != Raumname
    struktur["controls"]["AB"].pop("room")
    app = _app(struktur, states)
    v = _seite(app, {"cells": [zelle(0, 0, 2, 1, widget="player:AZ"), zelle(2, 0, widget="player:AB")]},
               picks=())
    mit, ohne = v["cells"]
    assert mit["raum"] == "Essen-Kochen-Wohnen" and ohne["raum"] == "Audio-Zone"
    favs = [b for b in mit["player"]["blocks"] if b["k"] == "favs"]
    assert len(favs) == 1 and [f["label"] for f in favs[0]["items"]] == HAUS_FAVORITEN
    assert favs[0]["items"][0]["cmd"] == {"uuid": "AZ", "cmd": "roomfav/play/1"}


def test_kaputter_blockbauer_reisst_die_seite_nicht_mit(monkeypatch):
    app = _app()

    def kaputt(*a):
        raise RuntimeError("Absicht")
    monkeypatch.setattr(app, "energy_blocks", kaputt)
    v = _seite(app, {"cells": [zelle(0, 0, widget="energy:F"), zelle(1, 0, ids=["S1"])]})
    assert v["cells"][0] == zelle(0, 0, widget="energy:F", fehler=True)
    assert v["cells"][1]["items"][0]["id"] == "S1"


def test_zelle_liest_ihre_states_ueber_die_lesespur():
    """Die Verteilung rendert nur neu, wenn ein gelesener State sich aendert:
    die Inline-Daten muessen also ueber self.states lesen."""
    app = _efm_app()
    _seite(app, {"cells": [zelle(0, 0, 2, 1, widget="energy:F")]}, picks=())
    lesen = _Lesespur(app.states)
    app.states = lesen
    try:
        app.render({"view": "tab", "tab": "auswahl"}, app.resolve_profile("p"))
    finally:
        app.states = lesen.quelle
    assert not lesen.alles and {"f-a0", "f-a1"} <= lesen.gelesen


# ---- Webseiten -----------------------------------------------------------------

@pytest.mark.parametrize("xfo, csp, stand", [
    ("", "", "ok"),
    ("DENY", "", "gesperrt"),
    ("deny", "", "gesperrt"),
    ("SAMEORIGIN", "", "eingeschraenkt"),
    ("", "default-src 'self'; frame-ancestors 'none'", "gesperrt"),
    ("", "frame-ancestors", "gesperrt"),
    ("", "frame-ancestors 'self' https://a.example", "eingeschraenkt"),
    ("", "frame-ancestors *", "ok"),
    ("DENY", "frame-ancestors *", "ok"),                       # CSP geht vor X-Frame-Options
    ("", "frame-ancestors *,frame-ancestors 'none'", "gesperrt"),   # die strengste gilt
    ("", "default-src 'self'", "ok"),
])
def test_einbetten_stand(xfo, csp, stand):
    assert bento.einbetten_stand(xfo, csp)["stand"] == stand


def _web(handler):
    a = web.Application()
    a.router.add_get("/{p:.*}", handler)
    return a


async def _pruefe(handler, pfad="/", timeout=2.0):
    async with TestServer(_web(handler)) as srv, aiohttp.ClientSession() as s:
        return await bento.webseite_pruefen(s, str(srv.make_url(pfad)), timeout)


@pytest.mark.parametrize("kopf, stand", [
    ({}, "ok"), ({"X-Frame-Options": "DENY"}, "gesperrt"),
    ({"Content-Security-Policy": "frame-ancestors 'self'"}, "eingeschraenkt"),
])
def test_webseite_pruefen_liest_die_kopfzeilen(kopf, stand):
    async def h(req):
        return web.Response(text="x", headers=kopf)
    assert asyncio.run(_pruefe(h))["stand"] == stand


def test_webseite_mit_http_fehler():
    async def h(req):
        return web.Response(status=404)
    assert asyncio.run(_pruefe(h)) == {"stand": "fehler", "grund": "Seite antwortet mit HTTP 404"}


def test_webseite_folgt_weiterleitungen():
    async def h(req):
        if req.path == "/alt":
            raise web.HTTPFound("/neu")
        return web.Response(text="x", headers={"X-Frame-Options": "DENY"})
    assert asyncio.run(_pruefe(h, "/alt"))["stand"] == "gesperrt"


def test_webseite_zu_langsam():
    async def h(req):
        await asyncio.sleep(1)
        return web.Response(text="x")
    assert asyncio.run(_pruefe(h, timeout=0.2))["stand"] == "fehler"


def test_webseite_nicht_erreichbar():
    async def lauf():
        async with aiohttp.ClientSession() as s:
            # Port 9 (discard) ist im Testcontainer nicht offen
            return await bento.webseite_pruefen(s, "http://127.0.0.1:9/", 2)
    assert asyncio.run(lauf()) == {"stand": "fehler", "grund": "Seite nicht erreichbar"}


def test_ungepruefte_adresse_weckt_die_pruefung_und_steht_als_offen():
    app = _app()
    v = _seite(app, {"cells": [zelle(0, 0, widget="iframe", url="https://drucker.local/", name="Drucker")]})
    assert v["cells"][0] == zelle(0, 0, widget="iframe", url="https://drucker.local/", name="Drucker",
                                  pruefung={"stand": "offen"}, ladenS=bento.BENTO_IFRAME_LADEN_S)
    assert app._bento_web()["wecken"].is_set()


def test_pruefrunde_ueber_gespeicherte_und_gerenderte_adressen():
    async def h(req):
        return web.Response(text="x", headers={"X-Frame-Options": "DENY"} if req.path == "/zu" else {})

    async def lauf():
        app = _app()
        async with TestServer(_web(h)) as srv, aiohttp.ClientSession() as s:
            offen, zu = str(srv.make_url("/offen")), str(srv.make_url("/zu"))
            _seite(app, {"cells": [zelle(0, 0, widget="iframe", url=offen)]})
            # eine nur gerenderte Adresse (Entwurf im Editor) zaehlt auch
            app._bento_webseite({"url": zu})
            assert await app._bento_runde(s) is True
            assert {u: e["stand"] for u, e in app._bento_web()["stand"].items()} == \
                {offen: "ok", zu: "gesperrt"}
            v = app._view_tab("auswahl", app.resolve_profile("p"))
            assert v["cells"][0]["pruefung"] == {"stand": "ok"}
            # unveraendert -> kein Neurendern; der Entwurf ist weg -> sein Ergebnis auch
            app._bento_web()["angefragt"].clear()
            assert await app._bento_runde(s) is True
            assert list(app._bento_web()["stand"]) == [offen]
            assert await app._bento_runde(s) is False
    asyncio.run(lauf())



# ---- Vorschlag fuer die Startseite: GET /api/bento/vorschlag ----------------------------

def _vorschlag_antwort(app, geraet="streifen"):
    import json
    from aiohttp.test_utils import make_mocked_request
    r = make_mocked_request("GET", "/api/bento/vorschlag?device=" + geraet, app={"app": app})
    return json.loads(asyncio.run(W.api_bento_vorschlag(r)).body)


def _verbunden(app, geraet, screen):
    app.conn_info[object()] = {"dev": geraet, "screen": screen, "ts": 1}


def test_api_bento_vorschlag(monkeypatch):
    from bento_format import BENTO_FORMAT_STANDARD
    struktur, states = haus_anlage()
    app = _app(struktur, states)
    efm = next(u for u, c in app.controls.items() if c["type"] == "EFM")
    app.calendar_cfg = {"sources": [{"name": "Familie", "url": "https://example.org/a.ics"}]}
    zone = next(u for u, c in app.controls.items() if c["type"] in ("AudioZone", "AudioZoneV2"))
    # Favoriten: die Zone (steht schon als Widget) und mehr Bausteine, als Felder frei sind
    kandidaten = [u for u, c in app.controls.items() if u not in (zone, efm)][:4]
    for u in [zone, *kandidaten]:
        app.controls[u]["isFavorite"] = True
    # Geraet ohne gemeldeten Schirm: Standardformat, formatBekannt false
    a = _vorschlag_antwort(app)
    assert a["format"] == BENTO_FORMAT_STANDARD and a["formatBekannt"] is False
    seite = a["pickTab"]
    assert seite["bento"]["format"] == BENTO_FORMAT_STANDARD
    widgets = [c["widget"] for c in seite["bento"]["cells"] if "widget" in c]
    assert widgets == ["clock", "weather", "player:" + zone, "energy:" + efm, "calendar"]
    # freie Felder neben den Widgets: je eines bekommt einen Favoriten, in der Reihenfolge der Favoriten
    frei = seite["bento"]["cols"] * seite["bento"]["rows"] - sum(c["w"] * c["h"] for c in seite["bento"]["cells"] if "widget" in c)
    assert frei == 3 and len(kandidaten) > frei, (frei, kandidaten)
    assert seite["picks"] == kandidaten[:frei]
    assert W.App._sanitize_panels({"p": {"title": "P", "tabs": ["auswahl"], "pickTabs": [seite]}})["p"]["pickTabs"][0]["bento"] == seite["bento"]
    # Geraet mit gemeldetem Schirm
    _verbunden(app, "streifen", {"vw": 3440, "vh": 600})
    a = _vorschlag_antwort(app)
    assert a["format"] == {"vw": 3440, "vh": 600} and a["formatBekannt"] is True
    assert a["pickTab"]["bento"]["format"] == {"vw": 3440, "vh": 600}


def test_api_bento_vorschlag_ohne_energie_und_kalender():
    struktur, states = raum_anlage()
    app = _app(struktur, states)
    app.calendar_cfg = {}
    seite = _vorschlag_antwort(app)["pickTab"]
    widgets = [c["widget"] for c in seite["bento"]["cells"] if "widget" in c]
    assert widgets == ["clock", "weather"] + [w for w in widgets[2:] if w.startswith("player:")]
    assert "calendar" not in widgets and not any(w.startswith("energy:") for w in widgets)


def test_meta_meldet_titel_max():
    """Der Assistent zaehlt Titel so, wie der Server sie kuerzt: /api/meta nennt die Grenze."""
    import json
    from aiohttp.test_utils import make_mocked_request
    r = make_mocked_request("GET", "/api/meta", app={"app": _app()})
    assert json.loads(asyncio.run(W.api_meta(r)).body)["titelMax"] == konfig.TITEL_MAX
    lang = "x" * (konfig.TITEL_MAX + 5)
    assert W.App._sanitize_panels({"p": {"title": lang}})["p"]["title"] == lang[:konfig.TITEL_MAX]


def test_meta_meldet_streifen_ab():
    import json
    from aiohttp.test_utils import make_mocked_request
    from bento_format import STREIFEN_AB
    r = make_mocked_request("GET", "/api/meta", app={"app": _app()})
    assert json.loads(asyncio.run(W.api_meta(r)).body)["streifenAb"] == STREIFEN_AB
