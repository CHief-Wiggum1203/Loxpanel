#!/usr/bin/env python3
"""Sonde fuer Loxone-Tree-Turbo-Geraete im eigenen Netz: Welche Geraete tauchen
auf, welche Ports oeffnen sie, und was verraten sie ohne Anmeldung?

Tree Turbo ist laut Loxone eine IP-basierte Powerline-Verbindung: die Geraete
(Stereo Extension, Install Speaker Master, Sub, Satellite ...) haengen an einer
Tree-Turbo-Schnittstelle des Audioservers bzw. Miniserver Compact und holen sich
per DHCP eine IP im normalen Heimnetz. Sie sind damit im LAN erreichbar wie jedes
andere Geraet. Diese Sonde sucht sie dort und schaut nach, was sie anbieten.

Laeuft im LoxPanel-Container, weil dort aiohttp vorhanden ist und der Server die
Adressen (Miniserver + Audioserver) aus der Struktur kennt:

    docker exec -i LoxPanel python3 bin/treeturbo_probe.py [argument]

Argumente:
    (ohne)          Adressen aus dem Panel lesen, die zugehoerigen /24-Netze
                    scannen und jeden Treffer abfragen.
    host <ip>       Nur diese eine Adresse abfragen (kein Scan).
    net <cidr>      Dieses Netz scannen, z.B. net 192.168.1.0/24.
    full            Wie ohne Argument, aber breiter Portbereich je Treffer.

Es wird nur gelesen. Nichts wird veraendert, keine Anmeldung erzwungen. Der
Zugang zum Miniserver (fuer die Adressliste aus der Struktur) ist derselbe wie
im Server: loxpanel.cfg (Settings) vor LOXPANEL_MS_*.
"""
import asyncio
import ipaddress
import json
import os
import sys
from pathlib import Path

import aiohttp

PANEL = "http://127.0.0.1:8099"
APP_DIR = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/app")

# Ports, die Loxone-Audio-/Tree-Turbo-Geraete und der Audioserver oeffnen. Der
# Scan probiert genau diese; `full` haengt einen breiteren Bereich an, um bisher
# unbekannte Dienste eines Tree-Turbo-Geraets zu finden.
KNOWN_PORTS = {
    80:   "HTTP (Konfig/Weboberflaeche)",
    443:  "HTTPS",
    7090: "Audioserver REST (Metadaten, /api/v1)",
    7091: "Audioserver-Protokoll (WebSocket, remotecontrol)",
    7092: "Audioserver-Proxy (Cover/Streams)",
    7093: "Audioserver (weiterer Kanal)",
    7095: "Audioserver (weiterer Kanal)",
    8080: "HTTP (alternativ)",
}
# Zusaetzlicher Bereich fuer `full` (ohne die schon in KNOWN_PORTS enthaltenen).
FULL_RANGE = range(1, 10001)

SCAN_TIMEOUT = 0.8      # Sekunden je TCP-Verbindungsversuch
SCAN_CONCURRENCY = 300  # gleichzeitige Verbindungsversuche
ARG = sys.argv[1].lower() if len(sys.argv) > 1 else ""
ARG2 = sys.argv[2] if len(sys.argv) > 2 else ""
FULL = ARG == "full"


def cut(s, n=400):
    s = str(s).replace("\n", " ").replace("\r", " ")
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


async def panel_audio_hosts() -> list:
    """Audioserver-Adressen (host:port) aus dem laufenden Panel (/api/settings)."""
    hosts = []
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{PANEL}/api/settings", timeout=aiohttp.ClientTimeout(total=6)) as r:
                data = await r.json()
        for hp in (data.get("audiometa", {}) or {}).get("servers", []) or []:
            host = str(hp).partition(":")[0].strip()
            if host:
                hosts.append(host)
    except Exception as err:
        print(f"  Panel /api/settings nicht lesbar: {cut(err, 120)}")
    return hosts


async def structure_hosts() -> list:
    """mediaServer-Adressen aus der Miniserver-Struktur (braucht Zugang). Das
    sind die Audioserver; die Tree-Turbo-Geraete haengen im selben Subnetz."""
    for d in (str(APP_DIR / "bin"), "/app/bin"):
        if d not in sys.path:
            sys.path.insert(0, d)
    ms = miniserver_config()
    if not ms.get("host"):
        return []
    try:
        from loxone_api import LoxoneClient
    except ImportError:
        return []
    port = int(ms.get("port", 443))
    c = LoxoneClient(host=ms["host"], user=ms.get("user", ""), password=ms.get("pass", ""),
                     port=port, verify_tls=bool(ms.get("verify_tls", False)))
    if port == 80:
        c.base_url = f"http://{ms['host']}:{port}/"
    hosts = []
    try:
        async with c:
            await c.getkey2()
            await c.authenticate()
            st = await c.load_structure()
        for v in (st.get("mediaServer") or {}).values():
            h = (v or {}).get("host", "") if isinstance(v, dict) else ""
            h = str(h).partition(":")[0].strip()
            if h:
                hosts.append(h)
    except Exception as err:
        print(f"  Struktur nicht lesbar ({cut(err, 100)}) — nur Panel-Adressen")
    return hosts


def seed_networks(hosts) -> list:
    """Aus IP-Adressen die zugehoerigen /24-Netze ableiten (dedupliziert)."""
    nets = []
    for h in hosts:
        try:
            ip = ipaddress.ip_address(h)
        except ValueError:
            continue   # Hostname statt IP -> kein Subnetz ableitbar
        if ip.version != 4:
            continue
        net = ipaddress.ip_network(f"{ip}/24", strict=False)
        if net not in nets:
            nets.append(net)
    return nets


async def tcp_open(host: str, port: int) -> bool:
    """True, wenn sich port an host oeffnen laesst (kurzer Connect-Versuch)."""
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout=SCAN_TIMEOUT)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except (asyncio.TimeoutError, OSError):
        return False


async def scan_host_alive(host: str, sem: asyncio.Semaphore) -> bool:
    """Lebt der Host? Ein offener der bekannten Ports genuegt als Nachweis."""
    async def one(port):
        async with sem:
            return await tcp_open(host, port)
    results = await asyncio.gather(*(one(p) for p in KNOWN_PORTS))
    return any(results)


async def scan_ports(host: str, ports, sem: asyncio.Semaphore) -> list:
    """Liste der offenen Ports aus `ports` an `host`."""
    async def one(port):
        async with sem:
            return port if await tcp_open(host, port) else None
    res = await asyncio.gather(*(one(p) for p in ports))
    return sorted(p for p in res if p is not None)


async def http_banner(host: str, port: int) -> str:
    """Server-Header und <title> der Startseite (kurz), zur Geraeteerkennung."""
    scheme = "https" if port == 443 else "http"
    url = f"{scheme}://{host}:{port}/"
    conn = aiohttp.TCPConnector(ssl=False)
    try:
        async with aiohttp.ClientSession(connector=conn) as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=6)) as r:
                server = r.headers.get("Server", "")
                text = await r.text(errors="replace")
        import re
        m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        title = (m.group(1).strip() if m else "")[:120]
        parts = [f"HTTP {r.status}"]
        if server:
            parts.append(f"Server: {server}")
        if title:
            parts.append(f"Titel: {title}")
        return " | ".join(parts)
    except Exception as err:
        return f"nicht abrufbar ({cut(err, 80)})"


async def audio_banner(host: str, port: int = 7091) -> str:
    """Audioserver-Protokoll (Port 7091): mit Unterprotokoll remotecontrol
    verbinden und das Begruessungsbanner (LWSS V ... | ~API:...~) einsammeln.
    Das identifiziert Audioserver und (moegliche) Audio-Endpunkte eindeutig."""
    url = f"ws://{host}:{port}/"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(url, timeout=8, protocols=("remotecontrol",)) as ws:
                proto = ws.protocol or "(keins)"
                loop = asyncio.get_event_loop()
                end = loop.time() + 4
                banner = ""
                while loop.time() < end:
                    try:
                        m = await asyncio.wait_for(ws.receive(), timeout=max(0.1, end - loop.time()))
                    except asyncio.TimeoutError:
                        break
                    if m.type != aiohttp.WSMsgType.TEXT:
                        break
                    if m.data.startswith("LWSS"):
                        banner = m.data.strip()
                        break
                    if not banner:
                        banner = cut(m.data, 160)
                return f"WS verbunden (Unterprotokoll {proto})" + (f" — Banner: {banner}" if banner else " — kein Banner in 4 s")
    except Exception as err:
        return f"WS nicht moeglich ({cut(err, 80)})"


async def inspect_host(host: str, sem: asyncio.Semaphore) -> None:
    """Einen Treffer genauer abfragen: offene Ports, HTTP-Banner, Audio-Banner."""
    ports_to_check = list(KNOWN_PORTS)
    if FULL:
        extra = [p for p in FULL_RANGE if p not in KNOWN_PORTS]
        ports_to_check += extra
    open_ports = await scan_ports(host, ports_to_check, sem)
    if not open_ports:
        print(f"\n===== {host}: keine der geprueften Ports offen")
        return
    print(f"\n===== {host}: offene Ports {', '.join(str(p) for p in open_ports)}")
    for p in open_ports:
        label = KNOWN_PORTS.get(p, "unbekannt")
        print(f"  {p:>5}  {label}")
    for p in open_ports:
        if p in (80, 443, 8080):
            print(f"  -> HTTP :{p}: {await http_banner(host, p)}")
    if 7091 in open_ports:
        print(f"  -> Audio :7091: {await audio_banner(host, 7091)}")


async def collect_targets() -> tuple:
    """Zieladressen bestimmen: aus Argument oder aus den Panel-/Struktur-Adressen."""
    if ARG == "host" and ARG2:
        return [ARG2.strip()], []
    if ARG == "net" and ARG2:
        try:
            return [], [ipaddress.ip_network(ARG2.strip(), strict=False)]
        except ValueError as err:
            print(f"Ungueltiges Netz {ARG2!r}: {err}")
            return [], []
    print("Adressen aus dem Panel und der Miniserver-Struktur lesen ...")
    ms = miniserver_config()
    seeds = []
    if ms.get("host"):
        seeds.append(str(ms["host"]).partition(":")[0].strip())
    a = await panel_audio_hosts()
    b = await structure_hosts()
    seeds += a + b
    seeds = [h for h in dict.fromkeys(seeds) if h]
    print(f"  Bekannte Adressen (Miniserver/Audioserver): {', '.join(seeds) or 'keine'}")
    nets = seed_networks(seeds)
    if seeds and not nets:
        print("  (Adressen sind Hostnamen, kein Subnetz ableitbar — nur diese direkt pruefen)")
        return seeds, []
    return [], nets


async def main():
    hosts, nets = await collect_targets()
    sem = asyncio.Semaphore(SCAN_CONCURRENCY)

    live = list(hosts)
    for net in nets:
        addrs = [str(ip) for ip in net.hosts()]
        print(f"\nScanne {net} ({len(addrs)} Adressen) auf offene Loxone-Ports ...")
        alive = await asyncio.gather(*(scan_host_alive(a, sem) for a in addrs))
        found = [a for a, ok in zip(addrs, alive) if ok]
        print(f"  Antwortende Hosts: {', '.join(found) or 'keine'}")
        for f in found:
            if f not in live:
                live.append(f)

    if not live:
        print("\nKeine Geraete gefunden. Haengt eine Stereo Extension/ein Tree-Turbo-Geraet\n"
              "im selben Subnetz und hat es per DHCP eine IP bekommen? (In Loxone Config:\n"
              "Tree-Turbo-Schnittstelle -> Tree-Turbo-Suche zeigt die verbundenen Geraete.)")
        return

    print(f"\n{len(live)} Host(s) werden genauer abgefragt ...")
    for h in live:
        await inspect_host(h, sem)

    print("\nFertig. Ports, die kein bekannter Loxone-Dienst sind, stehen als 'unbekannt' —\n"
          "die sind fuer einen Nachbau am interessantesten.")


if __name__ == "__main__":
    asyncio.run(main())
