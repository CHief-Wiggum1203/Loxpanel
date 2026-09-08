#!/usr/bin/env python3
"""Sonde fuer den Loxone-Audioserver (Port 7091): Was antwortet er ohne Anmeldung?

Laeuft im LoxPanel-Container, weil dort aiohttp vorhanden ist und der Server
die Audioserver-Adressen aus der Miniserver-Struktur kennt:

    curl -fsSL <url dieser datei> | docker exec -i LoxPanel python3 - [playerid]

Fragt je Audioserver per HTTP und per WebSocket die Zonenliste, den Zonenstatus
und die Raumfavoriten ab, lauscht auf audio_event-Pushs und setzt einmal die
Lautstaerke auf den aktuellen Wert. Die Ausgabe zeigt, ob der Audioserver
Befehle ohne Anmeldung annimmt (JSON-Antworten) oder sie ignoriert bzw. die
Verbindung schliesst. Es wird nichts dauerhaft veraendert.
"""
import asyncio
import json
import sys

import aiohttp

PLAYER = int(sys.argv[1]) if len(sys.argv) > 1 else 1
PANEL = "http://127.0.0.1:8099"


def cut(s, n=500):
    s = str(s).replace("\n", " ")
    return s if len(s) <= n else s[:n] + " …"


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
        await probe(host.strip(), int(port) if port.strip().isdigit() else 7091, volume)


if __name__ == "__main__":
    asyncio.run(main())
