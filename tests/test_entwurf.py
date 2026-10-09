"""Entwurf eines Profils (Punkt 10, Teil 3): Der Konfigurator schickt ein noch
nicht gespeichertes Profil an /api/entwurf; der Server prueft es wie beim
Speichern, haelt es aber nur im Speicher. Die Visu zeigt es unter
?panel=<id>&entwurf=<token> - die anderen Verbindungen und panels.json bleiben
unberuehrt. Ein Token, der nichts mehr trifft, faellt auf das gespeicherte
Profil zurueck und sagt es."""
import asyncio

import aiohttp
import pytest

from lox import W, anlage, visu_starten

STRUKTUR = anlage({"S": {"name": "Licht", "type": "Switch", "uuidAction": "S", "room": "r1", "cat": "c1",
                         "isFavorite": True, "states": {"active": "s"}}})
ROUTEN = [("POST", "/api/entwurf", W.api_entwurf), ("POST", "/api/panels", W.api_save_panels)]
GESPEICHERT = {"p": {"title": "Gespeichert", "tabs": ["favoriten"]}}
ENTWURF = {"title": "Entwurf", "tabs": ["zentral"], "ui": {"dpmsOff": 77}}


def _app() -> W.App:
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    app.states = {"s": 0}
    app.panels = W.App._sanitize_panels(GESPEICHERT)
    return app


def test_ablegen_pruefen_ersetzen_verfallen(cfg_ordner, monkeypatch):
    app = _app()
    token, weg = app.entwurf_ablegen("p", {**ENTWURF, "ui": {**ENTWURF["ui"], "gibtsnicht": 1}})
    assert any("gibtsnicht" in w for w in weg), f"was der Server verwirft, wird genannt: {weg}"
    assert not (cfg_ordner / "panels.json").exists(), "ein Entwurf schreibt nichts"
    assert app.panels == W.App._sanitize_panels(GESPEICHERT), "und aendert das gespeicherte Profil nicht"

    profil = app.entwurf_profil(token, "p")
    assert profil["title"] == "Entwurf" and profil["tabs"] == ["zentral"] and "gibtsnicht" not in profil["ui"], profil
    assert app.entwurf_profil(token, "anders") is None, "nur fuer das Profil, zu dem er gehoert"
    assert app.entwurf_profil("unbekannt", "p") is None and app.entwurf_profil("", "p") is None

    # die Visu liest ihn statt der Datei - auch die Nachschlager nach Profil-Kennung
    aufgeloest = app.resolve_profile("p", profil)
    assert aufgeloest["entwurf"] is True and aufgeloest["title"] == "Entwurf" and aufgeloest["tabs"] == ["zentral"]
    assert aufgeloest["roh"] is profil
    gespeichert = app.resolve_profile("p")
    assert gespeichert["title"] == "Gespeichert" and "entwurf" not in gespeichert and "roh" not in gespeichert
    assert app.panel_dpms("p", profil) == 77 and app.panel_dpms("p") is None

    # derselbe Token ersetzt den Entwurf, ein anderes Profil bekommt einen eigenen
    token2, _ = app.entwurf_ablegen("p", {"title": "Neu", "tabs": ["favoriten"]}, token)
    assert token2 == token and app.entwurf_profil(token, "p")["title"] == "Neu"
    token3, _ = app.entwurf_ablegen("q", {"title": "Q", "tabs": ["favoriten"]}, token)
    assert token3 != token and app.entwurf_profil(token, "p")["title"] == "Neu", "fremder Token ersetzt nichts"

    # unbrauchbare Profile
    for pid, roh in (("", ENTWURF), ("_x", ENTWURF), ("p", ["kein", "dict"])):
        with pytest.raises(ValueError):
            app.entwurf_ablegen(pid, roh)

    # abgelaufen: nicht mehr abrufbar, und das naechste Ablegen raeumt auf
    monkeypatch.setattr(W, "ENTWURF_DAUER", -1)
    assert app.entwurf_profil(token, "p") is None
    app.entwurf_ablegen("r", {"title": "R", "tabs": ["favoriten"]})
    assert len(app.entwuerfe) == 1, list(app.entwuerfe)


def test_platz_ist_begrenzt_der_aelteste_geht(monkeypatch):
    monkeypatch.setattr(W, "ENTWURF_MAX", 3)
    app = _app()
    tokens = [app.entwurf_ablegen(f"p{i}", {"title": f"P{i}", "tabs": ["favoriten"]})[0] for i in range(5)]
    assert list(app.entwuerfe) == tokens[2:], "die drei neuesten bleiben"


def test_speichern_verwirft_die_entwuerfe(cfg_ordner):
    app = _app()
    token, _ = app.entwurf_ablegen("p", ENTWURF)
    app._write_panels(W.App._sanitize_panels({"p": {"title": "Fertig", "tabs": ["favoriten"]}}))
    assert (cfg_ordner / "panels.json").exists() and app.entwuerfe == {}
    assert app.entwurf_profil(token, "p") is None


async def _naechste(ws, typ: str, frist: float = 3):
    loop = asyncio.get_running_loop()
    ende = loop.time() + frist
    while (rest := ende - loop.time()) > 0:
        try:
            m = await asyncio.wait_for(ws.receive_json(), rest)
        except asyncio.TimeoutError:
            return None
        if m.get("t") == typ:
            return m
    return None


def test_visu_zeigt_den_entwurf_und_nur_ihn(cfg_ordner):
    async def lauf():
        app = _app()
        runner, port, bc = await visu_starten(app, ROUTEN)
        basis = f"http://127.0.0.1:{port}"
        try:
            async with aiohttp.ClientSession() as s:
                async def post(pfad, daten):
                    async with s.post(basis + pfad, json=daten) as r:
                        return r.status, await r.json()

                status, j = await post("/api/entwurf", {"id": "p", "panel": ENTWURF})
                assert status == 200 and j["ok"] and j["reloaded"] == 0 and j["verworfen"] == [], j
                token = j["token"]
                assert j["url"] == f"/?panel=p&entwurf={token}", j
                assert not (cfg_ordner / "panels.json").exists()

                async with s.ws_connect(f"{basis}/ws?panel=p&entwurf={token}") as vorschau:
                    t = await _naechste(vorschau, "theme")
                    assert (t["entwurf"], t["title"], t["tabs"], t["dpmsOff"]) == (True, "Entwurf", ["zentral"], 77), t
                    assert app.conn_info[next(iter(app.conn_info))].get("entwurf") == token

                    async with s.ws_connect(f"{basis}/ws?panel=p") as normal:      # ohne Token: das gespeicherte
                        t = await _naechste(normal, "theme")
                        assert (t["entwurf"], t["title"], t["tabs"]) == (None, "Gespeichert", ["favoriten"]), t
                    async with s.ws_connect(f"{basis}/ws?panel=q&entwurf={token}") as fremd:   # anderes Profil
                        t = await _naechste(fremd, "theme")
                        assert t["entwurf"] is False and t["title"] != "Entwurf", t

                    # Aenderungen nachziehen: dieselbe Vorschau laedt neu und bekommt den neuen Stand
                    status, j2 = await post("/api/entwurf", {"id": "p", "token": token,
                                                              "panel": {**ENTWURF, "title": "Entwurf 2"}})
                    assert j2["token"] == token and j2["reloaded"] == 1, j2
                    assert await _naechste(vorschau, "reload"), "die offene Vorschau soll neu laden"
                async with s.ws_connect(f"{basis}/ws?panel=p&entwurf={token}") as neu:
                    assert (await _naechste(neu, "theme"))["title"] == "Entwurf 2"

                # Fehler: keine Kennung, kein Profil, unbrauchbare Kennung
                for daten in ({"panel": ENTWURF}, {"id": "p"}, {"id": "p", "panel": []}, {"id": " ", "panel": ENTWURF}):
                    status, j = await post("/api/entwurf", daten)
                    assert status == 400 and not j["ok"], (daten, status, j)
                status, j = await post("/api/entwurf", {"id": "_x", "panel": ENTWURF})
                assert status == 400 and "nicht brauchbar" in j["error"], j

                # Speichern erledigt die Entwuerfe: Vorschau-Fenster verlassen ihn ({t:"entwurfEnde"}
                # statt eines blossen Neuladens), alle anderen laden neu; derselbe Token trifft
                # nichts mehr, die Visu sagt es
                async with s.ws_connect(f"{basis}/ws?panel=p&entwurf={token}") as vor, \
                        s.ws_connect(f"{basis}/ws?panel=p") as andere:
                    await _naechste(vor, "theme")
                    await _naechste(andere, "theme")
                    status, j = await post("/api/panels", {"panels": {"p": {"title": "Fertig", "tabs": ["favoriten"]}}})
                    assert j["ok"]
                    assert await _naechste(vor, "entwurfEnde"), "die Vorschau soll den Entwurf verlassen"
                    assert await _naechste(andere, "reload") and True
                    assert j["reloaded"] == 1, "das Vorschau-Fenster zaehlt nicht doppelt: nur das andere Panel"
                async with s.ws_connect(f"{basis}/ws?panel=p&entwurf={token}") as alt:
                    t = await _naechste(alt, "theme")
                    assert (t["entwurf"], t["title"]) == (False, "Fertig"), t
        finally:
            bc.cancel()
            await runner.cleanup()
    asyncio.run(lauf())
