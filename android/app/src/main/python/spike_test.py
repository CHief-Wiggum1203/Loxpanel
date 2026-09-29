"""
Chaquopy-Machbarkeits-Spike fuer den LoxPanel-Server auf Android.

Prueft unabhaengig voneinander (eine Fehlfunktion bricht die anderen NICHT ab):
  1. cryptography importieren UND eine native AES-GCM-Operation ausfuehren
  2. aiohttp importieren
  3. loxone-api importieren
  4. einen echten aiohttp-Server auf 127.0.0.1:8099 hochziehen und lokal abfragen

Rueckgabe = mehrzeiliger Text, der 1:1 am Geraet angezeigt wird.
"""
import sys
import time
import socket
import threading
import traceback


def _try(label, fn):
    try:
        return "OK   %-16s %s" % (label, fn())
    except Exception as e:
        detail = "%s: %s" % (type(e).__name__, e)
        tb = traceback.format_exc().strip().splitlines()
        return "FAIL %-16s %s\n        %s" % (label, detail, tb[-1] if tb else "")


def _check_cryptography():
    import cryptography
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = AESGCM.generate_key(bit_length=128)
    aes = AESGCM(key)
    ct = aes.encrypt(b"\x00" * 12, b"loxpanel", None)
    aes.decrypt(b"\x00" * 12, ct, None)   # zwingt die native Backend-Nutzung
    return "v" + cryptography.__version__ + " (AES-GCM ok)"


def _check_aiohttp():
    import aiohttp
    import aiohttp.web  # noqa: F401
    return "v" + aiohttp.__version__


def _check_loxone_api():
    import importlib
    for name in ("loxone_api", "pyloxone_api", "loxoneapi", "loxone"):
        try:
            m = importlib.import_module(name)
            return "als '%s' (%s)" % (name, getattr(m, "__version__", "importiert"))
        except ImportError:
            continue
    raise ImportError("kein bekannter Modulname (loxone_api/...) gefunden")


def _check_server():
    import asyncio
    import aiohttp.web
    state = {}

    def serve():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def hello(_req):
            return aiohttp.web.Response(text="loxpanel-spike-ok")

        app = aiohttp.web.Application()
        app.router.add_get("/", hello)
        runner = aiohttp.web.AppRunner(app)
        loop.run_until_complete(runner.setup())
        site = aiohttp.web.TCPSite(runner, "127.0.0.1", 8099)
        loop.run_until_complete(site.start())
        state["up"] = True
        loop.run_forever()

    threading.Thread(target=serve, daemon=True).start()

    # bis zu 5 s auf den Listener warten
    for _ in range(50):
        if state.get("up"):
            break
        time.sleep(0.1)
    if not state.get("up"):
        raise RuntimeError("Server-Thread nicht gestartet")

    s = socket.create_connection(("127.0.0.1", 8099), timeout=3)
    try:
        s.sendall(b"GET / HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        data = s.recv(256)
    finally:
        s.close()
    first = data.split(b"\r\n", 1)[0].decode("latin1", "replace")
    ok = b"loxpanel-spike-ok" in data
    return "%s | Antwort enthaelt Marker: %s" % (first, ok)


def run():
    lines = []
    lines.append("=== LoxPanel Chaquopy Spike ===")
    lines.append("Python %s" % sys.version.split()[0])
    lines.append("Plattform: %s" % getattr(sys, "platform", "?"))
    lines.append("")
    lines.append(_try("cryptography", _check_cryptography))
    lines.append(_try("aiohttp", _check_aiohttp))
    lines.append(_try("loxone-api", _check_loxone_api))
    lines.append(_try("aiohttp-server", _check_server))
    lines.append("")
    lines.append("Fertig. OK = geht, FAIL = Problem (Text zeigt die Ursache).")
    return "\n".join(lines)
