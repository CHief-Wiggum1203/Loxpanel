#!/usr/bin/env python3
"""Sonde fuer den Loxone-Audioserver (Port 7091): Was antwortet er ohne Anmeldung?

Laeuft im LoxPanel-Container, weil dort aiohttp vorhanden ist und der Server
die Audioserver-Adressen aus der Miniserver-Struktur kennt:

    curl -fsSL <url dieser datei> | docker exec -i LoxPanel python3 - [playerid]

Teil 1 fragt je Audioserver per HTTP und per WebSocket die Zonenliste, den
Zonenstatus und die Raumfavoriten ab und lauscht auf audio_event-Pushs. Die
Ausgabe zeigt, ob der Audioserver Befehle ohne Anmeldung annimmt (JSON) oder
ablehnt ("command not allowed when paired").

Teil 2 holt sich mit den Miniserver-Zugangsdaten aus /app/config/loxpanel.cfg
(oder LOXPANEL_MS_*) ein App-Token (JWT) vom Miniserver und probiert damit die
Anmeldevarianten, die der Audioserver kennen koennte: secure/authenticate,
secure/init, secure/hello, Bearer-Header und Token in der URL. Nach jedem
Versuch wird audio/cfg/all gesendet; verschwindet die Fehlermeldung, ist der
Weg gefunden. Das Token erscheint in der Ausgabe nur als <JWT>. Es wird nichts
dauerhaft veraendert.
"""
import asyncio
import json
import os
import sys
import uuid as uuidlib
from pathlib import Path

import aiohttp

ARG = sys.argv[1] if len(sys.argv) > 1 else ""
FAVS_ONLY = ARG == "favs"
ROOMFAV_ONLY = ARG == "roomfav"
PLAYER = int(ARG) if ARG.isdigit() else 1
PANEL = "http://127.0.0.1:8099"
APP_DIR = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/app")
JWT = ""   # wird in Teil 2 gesetzt, damit cut() das Token unkenntlich macht


def cut(s, n=500):
    s = str(s).replace("\n", " ")
    if JWT:
        s = s.replace(JWT, "<JWT>")
    return s if len(s) <= n else s[:n] + " …"


def miniserver_config() -> dict:
    """Zugang wie der Server: loxpanel.cfg (Settings) vor Umgebungsvariablen."""
    for base in (APP_DIR / "config", Path("/app/config")):
        f = base / "loxpanel.cfg"
        if f.is_file():
            try:
                ms = json.loads(f.read_text(encoding="utf-8")).get("miniserver", {})
            except ValueError:
                ms = {}
            if ms.get("host"):
                return ms
    env = os.environ
    if env.get("LOXPANEL_MS_HOST"):
        return {"host": env["LOXPANEL_MS_HOST"], "user": env.get("LOXPANEL_MS_USER", ""),
                "pass": env.get("LOXPANEL_MS_PASS", ""), "port": int(env.get("LOXPANEL_MS_PORT") or "443"),
                "verify_tls": env.get("LOXPANEL_MS_VERIFY_TLS", "false").lower() in ("1", "true", "yes")}
    return {}


async def fetch_jwt() -> str:
    """App-Token (permission 4) vom Miniserver, derselbe Weg wie im Server."""
    for d in (str(APP_DIR / "bin"), "/app/bin"):
        if d not in sys.path:
            sys.path.insert(0, d)
    from loxone_api import LoxoneClient
    ms = miniserver_config()
    if not ms.get("host"):
        raise RuntimeError("kein Miniserver-Zugang gefunden (loxpanel.cfg oder LOXPANEL_MS_*)")
    port = int(ms.get("port", 443))
    c = LoxoneClient(host=ms["host"], user=ms.get("user", ""), password=ms.get("pass", ""),
                     port=port, verify_tls=bool(ms.get("verify_tls", False)))
    if port == 80:   # wie _ms_https() im Server: Gen 1 spricht nur HTTP
        c.base_url = f"http://{ms['host']}:{port}/"
    async with c:
        await c.getkey2()
        return await c.authenticate()


async def listen(ws, secs):
    """Alle Nachrichten der naechsten `secs` Sekunden ausgeben."""
    loop = asyncio.get_event_loop()
    end = loop.time() + secs
    while True:
        left = end - loop.time()
        if left <= 0:
            return
        try:
            m = await asyncio.wait_for(ws.receive(), timeout=left)
        except asyncio.TimeoutError:
            return
        if m.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
            print(f"  WS geschlossen: {m.type.name} code={m.data} {m.extra or ''}")
            return
        print(f"  WS <- {cut(m.data)}")


async def probe(host, port, volume):
    print(f"\n===== Audioserver {host}:{port}")
    async with aiohttp.ClientSession() as s:
        for path in ("audio/cfg/all", f"audio/{PLAYER}/status",
                     f"audio/cfg/getroomfavs/{PLAYER}/0/10"):
            try:
                async with s.get(f"http://{host}:{port}/{path}",
                                 timeout=aiohttp.ClientTimeout(total=6)) as r:
                    print(f"HTTP GET /{path} -> {r.status} {cut(await r.text(), 400)}")
            except Exception as err:
                print(f"HTTP GET /{path} -> Fehler: {err}")
        try:
            async with s.ws_connect(f"ws://{host}:{port}/", timeout=8) as ws:
                print("WS verbunden, 4 s lauschen:")
                await listen(ws, 4)
                cmds = ["audio/cfg/all", f"audio/{PLAYER}/status",
                        f"audio/cfg/getroomfavs/{PLAYER}/0/10"]
                if volume is not None:
                    cmds.append(f"audio/{PLAYER}/volume/{volume}")
                for cmd in cmds:
                    if ws.closed:
                        break
                    print(f"WS -> {cmd}")
                    await ws.send_str(cmd)
                    await listen(ws, 4)
        except Exception as err:
            print(f"WS Fehler: {err}")


async def ws_try(host, port, label, cmds, headers=None, query="", path="/", protocols=()):
    """Eine frische WebSocket-Verbindung, Befehle nacheinander, Antworten zeigen."""
    print(f"\n--- {label}")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(f"ws://{host}:{port}{path}{query}", timeout=8,
                                    headers=headers or {}, protocols=protocols) as ws:
                if ws.protocol:
                    print(f"  Unterprotokoll bestaetigt: {ws.protocol}")
                await listen(ws, 1.5)
                for cmd in cmds:
                    if ws.closed:
                        print("  (Verbindung ist zu)")
                        break
                    print(f"  WS -> {cut(cmd, 120)}")
                    await ws.send_str(cmd)
                    await listen(ws, 3)
    except Exception as err:
        print(f"  WS Fehler: {cut(err)}")


async def auth_probe(host, port):
    global JWT
    print(f"\n===== Teil 2: Anmeldeversuche an {host}:{port}")
    try:
        JWT = await fetch_jwt()
    except Exception as err:
        print(f"Token vom Miniserver nicht bekommen: {cut(err)}")
        return
    print(f"App-Token vom Miniserver erhalten ({len(JWT)} Zeichen)")
    cid = str(uuidlib.uuid4())
    check = "audio/cfg/all"
    await ws_try(host, port, "secure/info/pairing und secure/hello ohne Token",
                 ["secure/info/pairing", f"secure/hello/{cid}/probe", check])
    await ws_try(host, port, "secure/authenticate/<JWT>", [f"secure/authenticate/{JWT}", check])
    await ws_try(host, port, "secure/init/<JWT>", [f"secure/init/{JWT}", check])
    await ws_try(host, port, "secure/hello/<id>/<JWT> dann authenticate/init",
                 [f"secure/hello/{cid}/{JWT}", f"secure/authenticate/{JWT}", f"secure/init/{JWT}", check])
    await ws_try(host, port, "Bearer-Header", [check], headers={"Authorization": f"Bearer {JWT}"})
    await ws_try(host, port, "Token in der URL (?token=)", [check], query=f"?token={JWT}")
    print("\n--- HTTP: secure/authenticate, dann audio/cfg/all in derselben Sitzung (Cookies)")
    try:
        async with aiohttp.ClientSession() as s:
            for path in (f"secure/authenticate/{JWT}", check, f"{check}?token={JWT}"):
                async with s.get(f"http://{host}:{port}/{path}", headers={"Authorization": f"Bearer {JWT}"},
                                 timeout=aiohttp.ClientTimeout(total=6)) as r:
                    print(f"  HTTP GET /{cut(path, 60)} -> {r.status} {cut(await r.text(), 300)}")
    except Exception as err:
        print(f"  HTTP Fehler: {cut(err)}")


async def path_probe(host, port):
    """Teil 3: Auf welchem Pfad und mit welchem Unterprotokoll antwortet der
    WebSocket ueberhaupt? Der Miniserver nutzt /ws/rfc6455 und das
    Unterprotokoll "remotecontrol"; die App verwendet dieselbe Bibliothek."""
    print(f"\n===== Teil 3: WebSocket-Pfade an {host}:{port}")
    probe_cmds = ["secure/info/pairing", "audio/cfg/all"]
    for path in ("/ws/rfc6455", "/ws", "/websocket", "/rfc6455", "/"):
        for protos in (("remotecontrol",), ()):
            label = f"Pfad {path}" + (f", Unterprotokoll {protos[0]}" if protos else ", ohne Unterprotokoll")
            await ws_try(host, port, label, probe_cmds, path=path, protocols=protos)
    print("\n--- HTTP: welche secure/*-Befehle kennt der Server (Fehlertext unterscheidet)?")
    cid = str(uuidlib.uuid4())
    try:
        async with aiohttp.ClientSession() as s:
            for path in ("secure/info/pairing", "secure/info", f"secure/hello/{cid}/probe", "secure/hello/probe",
                         "secure/init/probe", "secure/init", "secure/authenticate/probe", "secure/authenticate",
                         "audio/cfg/ready", "audio/cfg/miniserverip", "audio/cfg/getkey"):
                async with s.get(f"http://{host}:{port}/{path}", timeout=aiohttp.ClientTimeout(total=6)) as r:
                    print(f"  HTTP GET /{cut(path, 60)} -> {r.status} {cut(await r.text(), 220)}")
    except Exception as err:
        print(f"  HTTP Fehler: {cut(err)}")


async def event_probe(host, port):
    """Teil 4: Verhalten des Ereigniskanals mit Unterprotokoll remotecontrol.
    Kommen Ereignisse laufend ohne Befehl? Welcher Befehl schliesst die
    Verbindung? Antwortet secure/info/pairing allein?"""
    print(f"\n===== Teil 4: Ereigniskanal (remotecontrol) an {host}:{port}")
    print("\n--- 10 s nur hoeren, kein Befehl (Lautstaerke oder Titel am Geraet aendern zeigt Ereignisse)")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(f"ws://{host}:{port}/", timeout=8, protocols=("remotecontrol",)) as ws:
                await listen(ws, 10)
                print(f"  Verbindung danach offen: {not ws.closed}")
    except Exception as err:
        print(f"  WS Fehler: {cut(err)}")
    for cmd in (f"audio/{PLAYER}/status", "secure/info/pairing", "audio/cfg/getkey"):
        await ws_try(host, port, f"remotecontrol, nur {cmd}", [cmd], protocols=("remotecontrol",))


async def collect_players(host, port, secs=3):
    """Playerids aus den audio_event-Pushs einer remotecontrol-Verbindung."""
    ids = {}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(f"ws://{host}:{port}/", timeout=8, protocols=("remotecontrol",)) as ws:
                end = asyncio.get_event_loop().time() + secs
                while True:
                    left = end - asyncio.get_event_loop().time()
                    if left <= 0:
                        break
                    try:
                        m = await asyncio.wait_for(ws.receive(), timeout=left)
                    except asyncio.TimeoutError:
                        break
                    if m.type != aiohttp.WSMsgType.TEXT:
                        break
                    try:
                        data = json.loads(m.data)
                    except (ValueError, TypeError):
                        continue
                    for e in data.get("audio_event", []) or []:
                        if isinstance(e, dict) and e.get("playerid") is not None:
                            ids.setdefault(e["playerid"], (e.get("name") or "").strip())
    except Exception as err:
        print(f"  Playerids nicht lesbar: {cut(err)}")
    return ids


async def favs_probe(host, port):
    """Teil 5: Holt der gekoppelte Audioserver Favoriten heraus, bevor er die
    remotecontrol-Verbindung schliesst? Je Zone eine frische Verbindung:
    zuerst die Events abwarten, dann getroomfavs senden und die Antwort samt
    Schliess-Zeitpunkt zeigen. Nichts wird veraendert."""
    print(f"\n===== Teil 5: Favoriten ueber frische remotecontrol-Verbindungen an {host}:{port}")
    players = await collect_players(host, port)
    if not players:
        print("  Keine Playerids aus den Ereignissen — laeuft Musik? Sonst spaeter erneut.")
        return
    print("  Playerids:", ", ".join(f"{pid} ({name})" for pid, name in sorted(players.items())))
    for pid in sorted(players):
        label = f"Zone {pid} ({players[pid]})"
        got = {"result": False, "closed_after_send": False}
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"ws://{host}:{port}/", timeout=8, protocols=("remotecontrol",)) as ws:
                    await listen(ws, 1.5)   # Banner + erste Events schlucken
                    cmd = f"audio/cfg/getroomfavs/{pid}/0/50"
                    print(f"\n--- {label}: sende {cmd}")
                    if ws.closed:
                        print("  (Verbindung war schon zu)")
                        continue
                    await ws.send_str(cmd)
                    loop = asyncio.get_event_loop(); end = loop.time() + 6
                    while True:
                        left = end - loop.time()
                        if left <= 0:
                            break
                        try:
                            m = await asyncio.wait_for(ws.receive(), timeout=left)
                        except asyncio.TimeoutError:
                            break
                        if m.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                            print(f"  WS geschlossen: {m.type.name}")
                            got["closed_after_send"] = True
                            break
                        if m.type == aiohttp.WSMsgType.TEXT:
                            if "getroomfavs_result" in m.data or "roomfav" in m.data:
                                got["result"] = True
                                print(f"  >>> FAVORITEN: {cut(m.data, 700)}")
                            else:
                                print(f"  WS <- {cut(m.data, 160)}")
        except Exception as err:
            print(f"  WS Fehler: {cut(err)}")
        print(f"  Ergebnis Zone {pid}: Favoriten={got['result']}, Verbindung geschlossen={got['closed_after_send']}")


async def roomfav_probe():
    """Teil 6: Holt der MINISERVER die Raumfavoriten inline zurueck?

    Baut den Miniserver-Client wie der Server (Token-Anmeldung), laedt die
    Struktur, findet die AudioZoneV2-Zonen und schickt fuer die ersten zwei
    `jdev/sps/io/<uuidAction>/roomfav/get/0/50`. Zeigt die rohe Antwort und
    LL.value. Erwartung bei Erfolg: LL.value ist ein (evtl. prozentkodierter)
    JSON-Text mit getroomfavs_result und items (slot, name, coverurl). Damit
    liesse sich die Favoritenliste ohne Audioserver-Anmeldung fuellen.
    Es wird nichts veraendert (roomfav/get liest nur)."""
    print("\n===== Teil 6: Raumfavoriten ueber den Miniserver (roomfav/get)")
    for d in (str(APP_DIR / "bin"), "/app/bin"):
        if d not in sys.path:
            sys.path.insert(0, d)
    from loxone_api import LoxoneClient
    ms = miniserver_config()
    if not ms.get("host"):
        print("  kein Miniserver-Zugang gefunden"); return
    port = int(ms.get("port", 443))
    c = LoxoneClient(host=ms["host"], user=ms.get("user", ""), password=ms.get("pass", ""),
                     port=port, verify_tls=bool(ms.get("verify_tls", False)))
    if port == 80:
        c.base_url = f"http://{ms['host']}:{port}/"
    async with c:
        await c.getkey2()
        await c.authenticate()
        st = await c.load_structure()
    controls = st.get("controls", {}) if isinstance(st, dict) else {}
    zones = [(u, cc) for u, cc in controls.items() if isinstance(cc, dict) and cc.get("type") == "AudioZoneV2"]
    print(f"  {len(zones)} AudioZoneV2-Zonen in der Struktur")
    if not zones:
        return
    # Der Client muss fuer die Kommandos offen bleiben:
    c2 = LoxoneClient(host=ms["host"], user=ms.get("user", ""), password=ms.get("pass", ""),
                      port=port, verify_tls=bool(ms.get("verify_tls", False)))
    if port == 80:
        c2.base_url = f"http://{ms['host']}:{port}/"
    async with c2:
        await c2.getkey2()
        await c2.authenticate()
        for u, cc in zones[:2]:
            ua = cc.get("uuidAction") or u
            name = cc.get("name", "")
            print(f"\n--- Zone {name} (uuidAction {ua})")
            path = f"sps/io/{ua}/roomfav/get/0/50"
            try:
                r = await c2.jdev_get(path)
            except Exception as err:
                print(f"  jdev_get Fehler: {cut(err, 300)}"); continue
            ll = (r.get("LL") or {}) if isinstance(r, dict) else {}
            val = ll.get("value")
            code = ll.get("Code") or ll.get("code")
            print(f"  Code: {code}")
            print(f"  LL.value (roh): {cut(repr(val), 700)}")
            if isinstance(val, str) and val.strip():
                from urllib.parse import unquote
                txt = unquote(val)
                try:
                    parsed = json.loads(txt)
                    print(f"  LL.value als JSON: {cut(json.dumps(parsed, ensure_ascii=False), 700)}")
                except (ValueError, TypeError):
                    if txt != val:
                        print(f"  LL.value (url-dekodiert): {cut(txt, 500)}")
                    print("  (nicht als JSON parsebar)")


async def main():
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{PANEL}/api/settings") as r:
            servers = (await r.json()).get("audiometa", {}).get("servers", [])
        volume = None
        try:
            async with s.get(f"{PANEL}/api/meta") as r:
                meta = await r.json()
            zones = [c for c in meta.get("controls", []) if c.get("type") == "AudioZoneV2"]
            print("AudioZoneV2-Zonen laut Struktur:",
                  ", ".join(f"{z.get('name')} ({z.get('roomName')})" for z in zones) or "keine")
        except Exception as err:
            print("Zonenliste nicht lesbar:", err)
    if ROOMFAV_ONLY:
        await roomfav_probe()
        return
    print("Audioserver laut Struktur:", ", ".join(servers) or "keine")
    for hp in servers:
        host, _, port = hp.partition(":")
        port = int(port) if port.strip().isdigit() else 7091
        if FAVS_ONLY:
            await favs_probe(host.strip(), port)
            continue
        await probe(host.strip(), port, volume)
        await event_probe(host.strip(), port)
        await path_probe(host.strip(), port)
        await auth_probe(host.strip(), port)
        await favs_probe(host.strip(), port)


if __name__ == "__main__":
    asyncio.run(main())
