#!/usr/bin/env python3
"""Read-only-Sonde: Wie gibt der Miniserver aufgezeichnete Verlaeufe (Statistik)
heraus? Grundlage fuer Verlaufs-Diagramme in LoxPanel.

Bausteine mit Aufzeichnung tragen in der Struktur `statistic` (alt) oder
`statisticV2` (neu). Wie die Daten abgerufen werden, steht in keiner Datei im
Repo; diese Sonde ermittelt es an der echten Anlage:

  Teil 1  Alle Bausteine mit statistic/statisticV2: Name, Typ, Raum und die
          vollstaendige Statistik-Definition (gekuerzt) — zeigt das Format.
  Teil 2  Die Loxone-Weboberflaeche des Miniservers ist dieselbe App wie die
          Loxone-App. Ihr JavaScript wird nach Statistik-Befehlen durchsucht;
          so kommen die Abrufwege aus der Quelle statt geraten.
  Teil 3  Probeabruf: Statistik-Verzeichnis /stats/ und eine Datei daraus
          (Status, Typ, Groesse, erste Bytes), um das Datenformat zu sehen.

Aufruf im Container (liest nur, veraendert nichts, zeigt keine Passwoerter;
das Token erscheint nur als <JWT>):

    curl -fsSL <raw-url> | docker exec -i LoxPanel python3 -u -
    docker exec -i LoxPanel python3 -u bin/statistic_probe.py      # im Image

Zugang wie der Server: loxpanel.cfg (Settings) vor LOXPANEL_MS_*.
"""
import asyncio
import base64
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import aiohttp

APP_DIR = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/app")
JWT = ""   # wird beim Anmelden gesetzt, damit cut() das Token unkenntlich macht

# Suchmuster fuer Statistik-Befehle im JavaScript der Loxone-Weboberflaeche.
STAT_WORDS = ("binstatisticdata", "statisticdata", "getstatistic", "statisticV2",
              "statistics", "/stats", "statistic/")
MAX_SCRIPTS = 60   # Obergrenze nachgeladener Skripte (die App laedt viele Module)


def cut(s, n=600):
    s = str(s).replace("\n", " ")
    if JWT:
        s = s.replace(JWT, "<JWT>")
    return s if len(s) <= n else s[:n] + f" … (+{len(s) - n} Zeichen)"


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


async def connect() -> tuple:
    """(Basis-URL, Header-Varianten, Struktur). Token wie im Server (loxone_api)."""
    global JWT
    for d in (str(APP_DIR / "bin"), "/app/bin"):
        if d not in sys.path:
            sys.path.insert(0, d)
    from loxone_api import LoxoneClient
    ms = miniserver_config()
    if not ms.get("host"):
        raise RuntimeError("kein Miniserver-Zugang gefunden (loxpanel.cfg oder LOXPANEL_MS_*)")
    port = int(ms.get("port", 443))
    scheme = "http" if port == 80 else "https"
    base = f"{scheme}://{ms['host']}:{port}/"
    c = LoxoneClient(host=ms["host"], user=ms.get("user", ""), password=ms.get("pass", ""),
                     port=port, verify_tls=bool(ms.get("verify_tls", False)))
    if port == 80:   # Gen 1 spricht nur HTTP
        c.base_url = base
    async with c:
        await c.getkey2()
        JWT = await c.authenticate()
        st = await c.load_structure()
    basic = base64.b64encode(f"{ms.get('user', '')}:{ms.get('pass', '')}".encode()).decode()
    headers = [{"Authorization": f"Bearer {JWT}"}, {"Authorization": f"Basic {basic}"}]
    return base, headers, st


async def fetch(s, url, headers) -> tuple:
    """GET mit Bearer, bei 401/403 mit Basic. -> (status, content-type, bytes)."""
    last = (0, "", b"")
    for hdr in headers:
        try:
            async with s.get(url, headers=hdr, timeout=aiohttp.ClientTimeout(total=40)) as r:
                body = await r.read()
                last = (r.status, r.headers.get("Content-Type", ""), body)
                if r.status not in (401, 403):
                    return last
        except Exception as err:
            last = (0, type(err).__name__, str(err).encode())
    return last


def part1(st: dict) -> list:
    rooms = st.get("rooms") or {}
    found = []
    for uuid, c in (st.get("controls") or {}).items():
        if not isinstance(c, dict):
            continue
        for key in ("statistic", "statisticV2"):
            if c.get(key):
                found.append((uuid, c, key))
    print(f"\n===== Teil 1: {len(found)} Bausteine mit Aufzeichnung")
    for uuid, c, key in found:
        room = (rooms.get(c.get("room")) or {}).get("name", "-")
        print(f"\n--- {c.get('name')} [{c.get('type')}] Raum: {room}  ({key})")
        print(f"    uuidAction: {c.get('uuidAction', uuid)}")
        print("    " + cut(json.dumps(c[key], ensure_ascii=False), 700))
    return found


async def part2(s, base, headers) -> None:
    print("\n===== Teil 2: Statistik-Befehle im Code der Loxone-Weboberflaeche")
    status, ctype, html = await fetch(s, base, headers)
    if status != 200:
        print(f"  Startseite {base} -> HTTP {status}, Abbruch Teil 2")
        return
    text = html.decode("utf-8", "replace")
    origin = "{u.scheme}://{u.netloc}".format(u=urlparse(base))
    ref_re = re.compile(r'["\'\(]([^"\'\(\)\s]+?\.m?js)(?:\?[^"\'\)\s]*)?["\'\)]')
    queue, seen, docs = [], set(), [("(Startseite)", text)]

    def collect(src, from_url):
        refs = set(re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', src, re.I)) | set(ref_re.findall(src))
        for ref in refs:
            if ref.startswith(("data:", "blob:", "//")) or ("://" in ref and not ref.startswith(origin)):
                continue
            cands = [urljoin(from_url, ref)]
            if not ref.startswith(("/", "./", "../")):
                # Worker-Pfade wie "scripts/SandboxComp/..." gelten ab der Startseite,
                # nicht ab dem Skript, das sie nennt: beide Aufloesungen probieren.
                cands.append(urljoin(base, ref))
            for url in cands:
                if url.startswith(origin) and url not in seen:
                    seen.add(url)
                    if "tatistic" in url:   # Statistik-Module zuerst: die App hat ~2000 Skripte
                        queue.insert(0, url)
                    else:
                        queue.append(url)

    collect(text, base)
    apphub = urljoin(base, "scripts/AppHub.js")   # Hauptmodul der App (audioserver_probe)
    if apphub not in seen:
        seen.add(apphub)
        queue.insert(0, apphub)
    loaded = 0
    while queue and loaded < MAX_SCRIPTS:
        url = queue.pop(0)
        st_, _, body = await fetch(s, url, headers)
        if st_ != 200 or not body:
            continue
        js = body.decode("utf-8", "replace")
        loaded += 1
        docs.append((url.replace(origin, ""), js))
        collect(js, url)
    print(f"  {loaded} Skripte geladen" + (f", {len(queue)} weitere nicht mehr verfolgt" if queue else ""))

    lit_re = re.compile(r'["\'`]([^"\'`\n]{0,120}?(?:stat)[^"\'`\n]{0,120}?)["\'`]', re.I)
    literals = set()
    for _name, js in docs:
        for m in lit_re.findall(js):
            if m.lower().endswith((".js", ".mjs", ".css")):
                continue   # Skriptverweise, keine Befehle
            if "/" in m and any(w.lower() in m.lower() for w in STAT_WORDS):
                literals.add(m)
    print(f"\n  Pfad-/Befehlsliterale mit Statistik-Bezug ({len(literals)}):")
    for lit in sorted(literals)[:80]:
        print(f"    {cut(lit, 160)}")
    print("\n  Geladene Statistik-Module: "
          + (", ".join(n for n, _ in docs if "tatistic" in n.lower()) or "keine"))
    # (Suchwort, Fundstellen): Die Aufrufstellen von StatisticV2.GET zeigen, wie
    # die sieben Parameter von getStatistic belegt werden. Ohne Beachtung von
    # Gross-/Kleinschreibung, der Befehl heisst im Code getStatistic.
    for word, maxhits in (("binstatisticdata", 1), ("StatisticV2.GET", 3), ("getStatistic", 2),
                          ("statisticV2", 1), ("/stats", 1)):
        low, shown = word.lower(), 0
        for name, js in docs:
            jl = js.lower()
            i = jl.find(low)
            while i >= 0 and shown < maxhits:
                a, b = max(0, i - 500), min(len(js), i + 900)
                print(f"\n  --- Fundstelle '{word}' in {name} bei {i}:")
                print("      " + cut(js[a:b], 1400))
                shown += 1
                i = jl.find(low, i + 900)          # naechste Stelle ausserhalb dieses Ausschnitts
            if shown >= maxhits:
                break
        if not shown:
            print(f"\n  --- '{word}': keine Fundstelle")


async def part3(s, base, headers) -> None:
    print("\n===== Teil 3: Probeabruf Statistik-Verzeichnis")
    url = urljoin(base, "stats/")
    status, ctype, body = await fetch(s, url, headers)
    text = body.decode("utf-8", "replace")
    print(f"  GET /stats/ -> HTTP {status}, {ctype}, {len(body)} Bytes")
    print("  " + cut(text, 900))
    files = re.findall(r'href=["\']([^"\']+\.(?:xml|bin|json|csv)[^"\']*)["\']', text, re.I)
    if not files:
        files = re.findall(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{16}\.[0-9]{6}\.\w+)', text, re.I)
    print(f"  Dateien im Verzeichnis: {len(files)}" + (f", z.B. {', '.join(files[:5])}" if files else ""))
    if not files:
        return
    furl = urljoin(url, files[0])
    status, ctype, body = await fetch(s, furl, headers)
    print(f"\n  GET {furl.replace(base, '/')} -> HTTP {status}, {ctype}, {len(body)} Bytes")
    head = body[:600]
    printable = sum(32 <= b < 127 or b in (9, 10, 13) for b in head)
    if head and printable / len(head) > 0.9:
        print("  Text: " + cut(head.decode("utf-8", "replace"), 600))
    else:
        print("  Binaer, erste 96 Bytes hex: " + head[:96].hex(" "))


async def main():
    print("Anmelden und Struktur laden ...")
    try:
        base, headers, st = await connect()
    except Exception as err:
        print(f"Miniserver nicht erreichbar/anmeldbar: {cut(err, 200)}")
        return
    found = part1(st)
    if not found:
        print("\nKeine Bausteine mit Aufzeichnung gefunden.")
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as s:
        await part2(s, base, headers)
        await part3(s, base, headers)
    print("\nFertig. Teil 2 zeigt die echten Abrufbefehle der App, Teil 3 das Datenformat.")


if __name__ == "__main__":
    asyncio.run(main())
