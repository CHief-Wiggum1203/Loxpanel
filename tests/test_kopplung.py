"""Kopplungscode fuer Browser ohne Geraetekennung (Punkt 11): Der Server
vergibt beim Verbinden einen Code (t:"kopplung"), nimmt einen gueltigen
zurueckgeschickten (?code=) wieder an, listet ihn unter /api/devices bei den
Geraeten ohne Kennung, und "Namen vergeben" trifft ueber den Code genau diese
Verbindung; ueber die IP weiterhin alle darunter. Ohne ?panel= verlangt die
Nachricht die Karte "Dieses Geraet einrichten", mit Kennung kommt sie nicht."""
import asyncio
import itertools

import aiohttp

from lox import W, anlage, visu_starten

STRUKTUR = anlage({"S": {"name": "Licht", "type": "Switch", "uuidAction": "S", "room": "r1", "cat": "c1",
                         "isFavorite": True, "states": {"active": "s"}}})
ROUTEN = [("POST", "/api/device/name", W.api_device_name)]


def _app() -> W.App:
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    app.states = {"s": 0}
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"]}})
    return app


async def _naechste(ws, typ: str, frist: float):
    """Naechste Nachricht dieses Typs; None, wenn sie in `frist` Sekunden nicht kommt."""
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


def test_code_kommt_beim_verbinden_und_bleibt():
    async def lauf():
        app = _app()
        runner, port, bc = await visu_starten(app, ROUTEN)
        basis = f"http://127.0.0.1:{port}"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"{basis}/ws") as ws:                     # ohne Kennung, ohne Profil
                    m = await _naechste(ws, "kopplung", 3)
                    assert m and W._KOPPLUNG_RE.fullmatch(m["code"]) and len(m["code"]) == W.KOPPLUNG_LAENGE, m
                    assert set(m["code"]) <= set(W.KOPPLUNG_ZEICHEN)
                    assert m["karte"] is True and m["pfad"] == "/config" and m["titel"] and m["hinweis"] and m["weg"], m
                    code = m["code"]
                    anon = app.device_list()["anonymous"]
                    assert [a["code"] for a in anon] == [code] and anon[0]["ip"] == "127.0.0.1", anon
                async with s.ws_connect(f"{basis}/ws?panel=test&code={code.lower()}") as ws:   # zurueckgeschickt
                    m = await _naechste(ws, "kopplung", 3)
                    assert m["code"] == code, "ein gueltiger Code bleibt (gross geschrieben)"
                    assert m["karte"] is False, "mit ?panel= hat jemand dieses Geraet eingerichtet: keine Karte"
                async with s.ws_connect(f"{basis}/ws?code=abc0") as ws:                # ungueltig (0 ist nicht im Alphabet)
                    m = await _naechste(ws, "kopplung", 3)
                    assert m["code"] != "ABC0" and W._KOPPLUNG_RE.fullmatch(m["code"]), m
                async with s.ws_connect(f"{basis}/ws?device=wand") as ws:              # mit Kennung: kein Code
                    assert await _naechste(ws, "theme", 3)
                    assert await _naechste(ws, "kopplung", 0.5) is None
                    assert app.device_list()["anonymous"] == []
                    assert all("code" not in i for i in app.conn_info.values())
        finally:
            bc.cancel()
            await runner.cleanup()
    asyncio.run(lauf())


def test_namen_vergeben_trifft_den_code():
    """Zwei Browser ohne Kennung hinter derselben IP: der Code trifft genau
    einen, die IP wie bisher alle; ein unbekannter Code benennt niemanden."""
    async def lauf():
        app = _app()
        runner, port, bc = await visu_starten(app, ROUTEN)
        basis = f"http://127.0.0.1:{port}"
        try:
            async with aiohttp.ClientSession() as s, \
                    s.ws_connect(f"{basis}/ws?code=AAAA") as a, s.ws_connect(f"{basis}/ws?code=BBBB") as b:
                assert (await _naechste(a, "kopplung", 3))["code"] == "AAAA"
                assert (await _naechste(b, "kopplung", 3))["code"] == "BBBB"
                assert [x["code"] for x in app.device_list()["anonymous"]] == ["AAAA", "BBBB"]

                async def benennen(body):
                    async with s.post(f"{basis}/api/device/name", json=body) as r:
                        return r.status, await r.json()
                assert await benennen({"code": "bbbb", "name": "Kind"}) == (200, {"ok": True, "sent": 1})
                assert await _naechste(b, "setdevice", 3) == {"t": "setdevice", "name": "Kind"}
                assert await _naechste(a, "setdevice", 0.5) is None, "der andere Browser bleibt unbenannt"
                status, j = await benennen({"code": "ZZZZ", "name": "Nix"})
                assert status == 200 and j["ok"] is False and j["sent"] == 0 and "Code" in j["error"], j
                assert await benennen({"ip": "127.0.0.1", "name": "Alle"}) == (200, {"ok": True, "sent": 2})
                assert (await _naechste(a, "setdevice", 3))["name"] == "Alle"
                assert (await _naechste(b, "setdevice", 3))["name"] == "Alle"
                status, j = await benennen({"name": "Ohne"})
                assert status == 400 and j["ok"] is False, j
        finally:
            bc.cancel()
            await runner.cleanup()
    asyncio.run(lauf())


def test_neuer_code_meidet_vergebene(monkeypatch):
    """Ein neuer Code ist nie einer, den gerade eine andere Verbindung hat."""
    app = _app()
    app.conn_info[object()] = {"dev": "", "code": "AAAA"}
    folge = itertools.chain("AAAA", "BBBB")
    monkeypatch.setattr(W.secrets, "choice", lambda _zeichen: next(folge))
    assert app.kopplungscode("") == "BBBB"
    assert app.kopplungscode(" cdef ") == "CDEF", "ein gueltiger Wunsch wird uebernommen"
    assert app.kopplungscode("AAAA") == "AAAA", "ein zurueckgeschickter Code bleibt, auch wenn er doppelt waere"
