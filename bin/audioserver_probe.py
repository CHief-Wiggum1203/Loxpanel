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

PLAYER = int(sys.argv[1]) if len(sys.argv) > 1 else 1
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


async def ws_try(host, port, label, cmds, headers=None, query=""):
    """Eine frische WebSocket-Verbindung, Befehle nacheinander, Antworten zeigen."""
    print(f"\n--- {label}")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(f"ws://{host}:{port}/{query}", timeout=8, headers=headers or {}) as ws:
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
    print("Audioserver laut Struktur:", ", ".join(servers) or "keine")
    for hp in servers:
        host, _, port = hp.partition(":")
        port = int(port) if port.strip().isdigit() else 7091
        await probe(host.strip(), port, volume)
        await auth_probe(host.strip(), port)


if __name__ == "__main__":
    asyncio.run(main())
