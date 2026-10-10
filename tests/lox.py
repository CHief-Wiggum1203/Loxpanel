"""Gemeinsame Hilfen fuer die Tests: Nachbau des Miniservers, Aufzeichnungen
wie am Miniserver und ein App-Objekt, das mit dem Nachbau spricht.

Der Nachbau nimmt nur das aktuell gueltige Token an (Bearer), so lassen sich
Ablauf und Erneuerung pruefen. Alle Server lauschen auf 127.0.0.1 mit einem
freien Port, damit Tests parallel und neben einem laufenden LoxPanel laufen.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import math
import os
import re
import ssl
import struct
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, unquote

import aiohttp
from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import padding as blockpadding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "bin") not in sys.path:
    sys.path.insert(0, str(ROOT / "bin"))

import webvisu as W  # noqa: E402

# Wartebedingung fuer Browser-Tests: Konfigurator hat /api/meta geladen. META
# ist bis zur Antwort null; die Bedingung darf dann nicht werfen, sonst bricht
# wait_for_function sofort ab statt weiter zu warten.
KONFIGURATOR_GELADEN = ("typeof META !== 'undefined' && META !== null"
                        " && Array.isArray(META.controls) && META.controls.length > 0")


async def karte_auf(pg, *namen):
    """Konfigurator, Rubrik Geraete: die Karte jedes Geraets aufklappen, wie von
    Hand ("Einstellungen"). Wartet, bis die Karte da ist (sie kommt mit der
    Abfrage der Geraeteliste); eine offene bleibt offen."""
    for name in namen:
        knopf = pg.locator(f'#geraete .gk[data-gk="{name}"] .gk-auf')
        await knopf.wait_for()
        if await knopf.get_attribute("aria-expanded") != "true":
            await knopf.click()


async def serve(app: web.Application, port: int = 0,
                ssl_context: ssl.SSLContext | None = None) -> tuple[web.AppRunner, int]:
    """aiohttp-App auf einem freien Port (oder auf `port`) starten -> (runner, port).
    ssl_context: HTTPS/WSS statt HTTP (Zertifikat etwa von Zertifizierungsstelle)."""
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port, ssl_context=ssl_context).start()
    return runner, runner.addresses[0][1]


def _x509_name(name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])


class Zertifizierungsstelle:
    """Eigene CA fuer die TLS-Tests, zur Laufzeit erzeugt (keine Zertifikate im
    Repo). `datei` ist die CA als PEM, etwa fuer SSL_CERT_FILE; server() stellt
    ein Server-Zertifikat aus und gibt den SSL-Kontext fuer serve() zurueck.
    Aufbau wie bei einer echten CA (BasicConstraints, KeyUsage, Schluessel-IDs,
    serverAuth), damit auch eine strenge Pruefung es annimmt."""

    def __init__(self, ordner: Path, name: str = "LoxPanel-Test-CA") -> None:
        self.ordner = ordner
        ordner.mkdir(parents=True, exist_ok=True)
        self._jetzt = datetime.now(timezone.utc)
        self._schluessel = ec.generate_private_key(ec.SECP256R1())
        oeffentlich = self._schluessel.public_key()
        self.zertifikat = (
            x509.CertificateBuilder().subject_name(_x509_name(name)).issuer_name(_x509_name(name))
            .public_key(oeffentlich).serial_number(x509.random_serial_number())
            .not_valid_before(self._jetzt - timedelta(days=1)).not_valid_after(self._jetzt + timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                         crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(oeffentlich), critical=False)
            .sign(self._schluessel, hashes.SHA256()))
        self.datei = ordner / "ca.pem"
        self.datei.write_bytes(self.zertifikat.public_bytes(serialization.Encoding.PEM))

    def server(self, *namen: str) -> ssl.SSLContext:
        """Server-Kontext mit einem Zertifikat dieser CA fuer die DNS-Namen `namen`."""
        schluessel = ec.generate_private_key(ec.SECP256R1())
        zert = (
            x509.CertificateBuilder().subject_name(_x509_name(namen[0])).issuer_name(self.zertifikat.subject)
            .public_key(schluessel.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(self._jetzt - timedelta(days=1)).not_valid_after(self._jetzt + timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in namen]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(self._schluessel.public_key()),
                           critical=False)
            .sign(self._schluessel, hashes.SHA256()))
        crt, key = self.ordner / f"{namen[0]}.pem", self.ordner / f"{namen[0]}.key"
        crt.write_bytes(zert.public_bytes(serialization.Encoding.PEM))
        key.write_bytes(schluessel.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                 serialization.NoEncryption()))
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(crt, key)
        return ctx


def monatsdateien(ua: str, zeile, stunden: int, schritt_min: int,
                  jetzt: datetime | None = None) -> dict[str, str]:
    """Aufzeichnung wie am Miniserver: je Monat eine Datei <ua>.<JJJJMM>.xml.

    zeile(t) liefert die Wert-Attribute einer Zeile (z. B. 'V="1.5"'). Die
    Aufteilung nach Monaten haelt die Tests auch am Monatsanfang richtig, wenn
    der Zeitraum in den Vormonat reicht."""
    jetzt = jetzt or datetime.now().replace(second=0, microsecond=0)
    by: dict[str, list] = {}
    t = jetzt - timedelta(hours=stunden)
    while t <= jetzt:
        by.setdefault(t.strftime("%Y%m"), []).append(f'<S T="{t:%Y-%m-%d %H:%M:%S}" {zeile(t)}/>')
        t += timedelta(minutes=schritt_min)
    return {f"{ua}.{ym}.xml": "<Statistics>" + "".join(v) + "</Statistics>" for ym, v in by.items()}


class Miniserver:
    """Nachbau der HTTP- und WebSocket-Seite des Miniservers.

    files   Statistik-Monatsdateien (Name -> XML) fuer /stats/<name>
    v2      (uuidAction, Gruppe, Ausgang) -> (Periode s, fn(unix) -> Wert)
    token   das derzeit gueltige Token; alles andere -> 401
    reject  sps/io-Befehle mit LL-Code 500 ablehnen
    deny    Pfad-Anfaenge, die trotz gueltigem Token 401 bekommen
    bilder  (uuidAction, Zeitstempel) -> JPEG fuer camimage (Klingel-Bilder)
    gesichert  uuidAction -> gesicherte Details (securedDetails), nur ueber
               einen verschluesselten Befehl (jdev/sys/fenc) zu bekommen;
               gesichert_code: LL-Code dafuer (etwa "403": keine Rechte)
    kennwort   Kennwort von `benutzer` fuer die Anmeldung (getkey2/getjwt);
               anmeldungen: "ok"/"abgelehnt" je getjwt, verzoegerung: so viele
               Sekunden laesst sich getjwt Zeit
    struktur   LoxAPP3.json (/data/LoxAPP3.json, nur mit gueltigem Token)
    visu_pin   Visu-Passwort fuer gesicherte Bausteine (isSecured); None: sps/ios
               ungeprueft angenommen wie jeder andere Befehl
    gesichert_io  uuidActions mit isSecured: sps/io darauf lehnt der Nachbau mit
               pin_code ab (Unterbausteine wie IC/1 gehoeren zum Baustein)
    ios        angekommene gesicherte Befehle (sps/ios) als (uuid/cmd, Code)
    pin_code   LL-Code fuer einen abgelehnten gesicherten Befehl (ohne PIN oder
               mit falscher); am Geraet nicht geprueft, der Fehlerbericht nennt 403
    hash_alg   hashAlg aus getkey2; gilt fuer getjwt, die Anmeldung am
               WebSocket (authwithtoken) und autht in verschluesselten Befehlen
    ws_modus   WebSocket /ws/rfc6455 fuer die Live-Werte. "an" (Standard):
               Anmeldung (getkey, authwithtoken mit dem HMAC des Tokens nach
               hash_alg), Status-Updates (erste Tabelle aus ws_werte, weitere
               ueber ws_wert()) und keepalive (Antwort: Header der Kennung 6,
               ohne Nutzdaten); jeden anderen Befehl bestaetigt er mit Wert "1".
               None: keiner (der Aufbau scheitert mit 404). Stumme
               Gegenstellen: "upgrade" beantwortet den Verbindungsaufbau nicht,
               "anmeldung" nimmt an und antwortet auf nichts, "stream" schweigt
               nach der ersten Tabelle, auch auf keepalive.
               ws_trennen_nach: so viele s nach den Status-Updates trennt der
               Nachbau ("an"; None = nie). ws_verbindungen, keepalives zaehlen.
    ws_befehle Befehle, die ueber den WebSocket ankamen, auch keepalive; "stream"
               liest nach der ersten Tabelle nicht mehr mit, "anmeldung" gar nicht
    TLS        start(ssl_context=...): HTTPS/WSS wie ein Gen2, Zertifikat etwa von
               Zertifizierungsstelle.server(); ohne ssl_context HTTP/WS wie ein Gen1

    Die Anmeldung folgt der Loxone-Doku (Token-Authentifizierung): getkey2
    liefert Schluessel (hex), Salz und hashAlg; getjwt traegt
    HMAC(Schluessel, "user:" + HASH("kennwort:salz") in Grossbuchstaben), beides
    mit hashAlg. Am WebSocket meldet sich der Client mit dem Token an:
    jdev/sys/getkey, dann authwithtoken/HMAC(getkey, token)/user.

    Die Verschluesselung ist hier unabhaengig von bin/loxone_secure.py nach der
    Loxone-Doku nachgebaut (Command Encryption, HTTP): eigener RSA-Schluessel,
    Sitzungsschluessel "key:iv", AES-256-CBC mit Nullbytes, Antwort ebenso.

    Gesicherte Befehle ebenso nach der Doku (Secured Commands): getvisusalt
    liefert Schluessel (hex), Salz und hashAlg, sps/ios/{hash}/{uuid}/{cmd}
    traegt HMAC-SHA256(Schluessel, SHA256("pin:salz") in Grossbuchstaben).
    """

    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.v2: dict[tuple, tuple] = {}
        self.token = "T1"
        self.reject = False
        self.deny: set[str] = set()
        self.stat_hits: list[str] = []
        self.v2_paths: list[str] = []
        self.io: list[str] = []
        self.io_roh: list[str] = []          # dieselben Befehle so kodiert, wie sie ankamen
        self.bilder: dict[tuple[str, str], bytes] = {}
        self.bild_abrufe: list[str] = []
        self.gesichert: dict[str, dict] = {}
        self.gesichert_code = "200"
        self.benutzer = "loxpanel"          # Benutzer, den der Befehl nennen muss
        self.kennwort = "richtig"
        self.salz = "53616C7A"
        self.verzoegerung = 0.0
        self.anmeldungen: list[str] = []
        self.struktur: dict | None = None
        self.visu_pin: str | None = None
        self.visu_key, self.visu_salz = "abcd", "s1"   # Antwort von getvisusalt
        self.gesichert_io: set[str] = set()
        self.ios: list[tuple[str, str]] = []
        self.pin_code = "403"
        self.getkey = "4C6F78506F6E656C"    # Schluessel aus jdev/sys/getkey (hex)
        self.hash_alg = "SHA256"
        self.ws_befehle: list[str] = []
        self.schluessel = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        self.schluessel_abrufe = 0
        self.fenc: list[str] = []           # entschluesselte Befehle aus jdev/sys/fenc
        self.live = self.peak = 0
        self.ws_modus: str | None = "an"
        self.ws_werte: dict[str, float] = {}
        self.ws_trennen_nach: float | None = None
        self.ws_verbindungen = 0
        self.keepalives = 0
        self._ws_offen: set[web.WebSocketResponse] = set()
        self._ws_ende = asyncio.Event()      # stop(): stumme Gegenstellen loslassen
        self.runner: web.AppRunner | None = None
        self.port = 0

    def _ok(self, r: web.Request, pfad: str) -> bool:
        return (r.headers.get("Authorization") == "Bearer " + self.token
                and not any(pfad.startswith(d) for d in self.deny))

    async def _stats(self, r: web.Request) -> web.Response:
        name = r.match_info["f"]
        self.stat_hits.append(name)
        if not self._ok(r, "stats/" + name):
            return web.Response(status=401)
        if name in self.files:
            return web.Response(text=self.files[name], content_type="text/xml")
        return web.Response(status=404)

    async def _camimage(self, r: web.Request) -> web.Response:
        ua, ts = r.match_info["ua"], r.match_info["ts"]
        self.bild_abrufe.append(f"{ua}/{ts}")
        if not self._ok(r, f"camimage/{ua}/{ts}"):
            return web.Response(status=401)
        bild = self.bilder.get((ua, ts))
        if bild is None:
            return web.Response(status=404)
        return web.Response(body=bild, content_type="image/png" if bild.startswith(b"\x89PNG") else "image/jpeg")

    def neuer_schluessel(self) -> None:
        """Wie nach einem Neustart: Befehle mit dem alten Schluessel scheitern."""
        self.schluessel = rsa.generate_private_key(public_exponent=65537, key_size=1024)

    def _ll(self, control: str, value, code: str = "200") -> web.Response:
        return web.json_response({"LL": {"control": control, "value": value, "Code": code}})

    def _hash(self):
        return hashlib.sha256 if self.hash_alg == "SHA256" else hashlib.sha1

    def _token_hash(self) -> str:
        """HMAC des Tokens mit dem getkey-Schluessel (authwithtoken, autht)."""
        return hmac.new(bytes.fromhex(self.getkey), self.token.encode(), self._hash()).hexdigest()

    def _fenc(self, r: web.Request) -> web.Response:
        roh = r.raw_path.split("/jdev/sys/fenc/", 1)[1].split("?", 1)[0]
        try:
            sk = self.schluessel.decrypt(base64.b64decode(r.query.get("sk", "")), padding.PKCS1v15())
            key_hex, iv_hex = sk.decode("ascii").split(":")
            key, iv = bytes.fromhex(key_hex), bytes.fromhex(iv_hex)
            dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
            klar = (dec.update(base64.b64decode(unquote(roh))) + dec.finalize()).rstrip(b"\0").decode()
        except (ValueError, TypeError):
            return web.Response(status=401, text="Unauthorized")
        salz, _, cmd = klar[len("salt/"):].partition("/")
        assert klar.startswith("salt/") and salz, klar
        self.fenc.append(cmd)
        pfad, _, query = cmd.partition("?")
        q = dict(parse_qsl(query))
        m = re.fullmatch(r"jdev/sps/io/([^/]+)/securedDetails", pfad)
        token_hash = self._token_hash()
        if not m:
            code, wert = "404", ""
        elif q.get("autht") != token_hash or q.get("user") != self.benutzer:
            code, wert = "401", ""
        elif m.group(1) not in self.gesichert:
            code, wert = "500", ""
        else:
            code = self.gesichert_code
            wert = json.dumps(self.gesichert[m.group(1)]) if code == "200" else ""
        antwort = json.dumps({"LL": {"control": pfad, "value": wert, "Code": code}}).encode()
        enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        antwort += b"\0" * (-len(antwort) % 16)
        return web.Response(text=base64.b64encode(enc.update(antwort) + enc.finalize()).decode(),
                            content_type="text/plain")

    async def _jdev(self, r: web.Request) -> web.Response:
        tail = r.match_info["tail"]
        if tail == "sys/getPublicKey":
            # Wie der Miniserver: beschriftet als CERTIFICATE, in einer Zeile
            self.schluessel_abrufe += 1
            der = self.schluessel.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
            return self._ll(tail, "-----BEGIN CERTIFICATE-----" + base64.b64encode(der).decode()
                            + "-----END CERTIFICATE-----")
        if tail == "sys/getkey":
            return self._ll(tail, self.getkey)
        if tail.startswith("sys/getkey2/"):
            return self._ll(tail, {"key": self.getkey, "salt": self.salz, "hashAlg": self.hash_alg})
        if tail.startswith("sys/getjwt/"):
            return await self._getjwt(tail)
        if tail.startswith("sys/fenc/"):
            return self._fenc(r)
        if not self._ok(r, tail):
            return web.Response(status=401, text="Unauthorized")
        if tail.startswith("sps/getStatistic/"):
            return await self._getstatistic(tail)
        if tail.startswith("sys/getvisusalt/"):
            return web.json_response({"LL": {"control": tail, "Code": "200",
                                             "value": {"key": self.visu_key, "salt": self.visu_salz,
                                                       "hashAlg": "SHA256"}}})
        if tail.startswith("sps/ios/") and self.visu_pin is not None:
            _, _, h, befehl = tail.split("/", 3)
            code = "200" if h.lower() == self._visu_hash() else self.pin_code
            self.ios.append((befehl, code))
            return self._ll(tail, "1" if code == "200" else "", code)
        self.io.append(tail)
        self.io_roh.append(r.raw_path.split("/jdev/", 1)[1])
        if any(tail.startswith(f"sps/io/{u}/") for u in self.gesichert_io):
            return self._ll(tail, "", self.pin_code)
        return web.json_response({"LL": {"control": tail, "value": "1",
                                         "Code": "500" if self.reject else "200"}})

    def _visu_hash(self) -> str:
        pw = hashlib.sha256(f"{self.visu_pin}:{self.visu_salz}".encode()).hexdigest().upper()
        return hmac.new(bytes.fromhex(self.visu_key), pw.encode(), hashlib.sha256).hexdigest()

    async def _getjwt(self, tail: str) -> web.Response:
        _, _, hash_, user, *_ = tail.split("/")
        if self.verzoegerung:
            await asyncio.sleep(self.verzoegerung)
        pw = self._hash()(f"{self.kennwort}:{self.salz}".encode()).hexdigest().upper()
        soll = hmac.new(bytes.fromhex(self.getkey), f"{self.benutzer}:{pw}".encode(), self._hash()).hexdigest()
        ok = user == self.benutzer and hash_ == soll
        self.anmeldungen.append("ok" if ok else "abgelehnt")
        if not ok:
            return web.Response(status=401, text="Unauthorized")
        return self._ll(tail, {"token": self.token, "validUntil": 0, "tokenRights": 4})

    async def _loxapp3(self, r: web.Request) -> web.Response:
        if not self._ok(r, "data/LoxAPP3.json"):
            return web.Response(status=401)
        if self.struktur is None:
            return web.Response(status=404)
        return web.json_response(self.struktur)

    async def _getstatistic(self, tail: str) -> web.Response:
        _, _, ua, kind, frm, to, allw, gid, out = tail.split("/")
        self.v2_paths.append(tail)
        assert kind == "raw" and allw == "all"
        self.live += 1
        self.peak = max(self.peak, self.live)
        await asyncio.sleep(0.1)
        self.live -= 1
        reihe = self.v2.get((ua, gid, out))
        if reihe is None:
            return web.Response(body=b"", content_type="application/octet-stream")
        periode, fn = reihe
        t, body = int(frm) - int(frm) % periode + periode, b""
        while t <= int(to):
            body += struct.pack("<Id", t, fn(t))
            t += periode
        return web.Response(body=body, content_type="application/octet-stream")

    @staticmethod
    async def _ws_senden(ws: web.WebSocketResponse, kennung: int, daten: bytes | str = b"") -> None:
        """Wie der Miniserver: erst der 8-Byte-Header (0x03, Kennung, Info,
        reserviert, Laenge LE), dann die Nutzdaten, Text als Text-Nachricht."""
        roh = daten.encode() if isinstance(daten, str) else daten
        await ws.send_bytes(struct.pack("<BBBBI", 0x03, kennung, 0, 0, len(roh)))
        if isinstance(daten, str):
            await ws.send_str(daten)
        elif roh:
            await ws.send_bytes(roh)

    @staticmethod
    def _werte_tabelle(werte: dict[str, float]) -> bytes:
        """Tabelle der Kennung 2: je Eintrag UUID (16 Byte) und double (LE)."""
        roh = b""
        for u, wert in werte.items():
            d1, d2, d3, d4 = u.split("-")
            roh += struct.pack("<IHH", int(d1, 16), int(d2, 16), int(d3, 16)) + bytes.fromhex(d4)
            roh += struct.pack("<d", wert)
        return roh

    async def ws_wert(self, uuid: str, wert: float) -> None:
        """Wertaenderung an alle offenen WebSocket-Verbindungen schicken."""
        for ws in list(self._ws_offen):
            await self._ws_senden(ws, 2, self._werte_tabelle({uuid: wert}))

    async def _ws(self, r: web.Request) -> web.StreamResponse:
        """WebSocket wie am Miniserver (ws_modus): Antworten mit 8-Byte-Kopf,
        dann LL-JSON. Merkt sich jeden Befehl (ws_befehle)."""
        if self.ws_modus is None:
            return web.Response(status=404)
        self.ws_verbindungen += 1
        if self.ws_modus == "upgrade":
            await self._ws_ende.wait()
            return web.Response(status=503)
        ws = web.WebSocketResponse(protocols=("remotecontrol",))
        await ws.prepare(r)
        self._ws_offen.add(ws)
        trenner = None
        try:
            if self.ws_modus == "anmeldung":
                await self._ws_ende.wait()
                return ws
            async for m in ws:
                if m.type != aiohttp.WSMsgType.TEXT:
                    continue
                befehl = m.data
                self.ws_befehle.append(befehl)
                if befehl == "keepalive":
                    self.keepalives += 1
                    await self._ws_senden(ws, 6)
                    continue
                if befehl == "jdev/sys/getkey":
                    wert, code = self.getkey, "200"
                elif befehl.startswith("authwithtoken/"):
                    _, hash_, user = befehl.split("/")
                    wert, code = "", "200" if hash_ == self._token_hash() and user == self.benutzer else "401"
                else:
                    wert, code = "1", "200"
                await self._ws_senden(ws, 0, json.dumps({"LL": {"control": befehl, "value": wert, "Code": code}}))
                if befehl != "jdev/sps/enablebinstatusupdate":
                    continue
                await self._ws_senden(ws, 2, self._werte_tabelle(self.ws_werte))
                if self.ws_modus == "stream":
                    await self._ws_ende.wait()      # ab hier Stille, der Socket bleibt offen
                    return ws
                if self.ws_trennen_nach is not None:
                    trenner = asyncio.create_task(self._ws_trennen(ws, self.ws_trennen_nach))
            return ws
        finally:
            self._ws_offen.discard(ws)
            if trenner is not None:
                trenner.cancel()

    @staticmethod
    async def _ws_trennen(ws: web.WebSocketResponse, nach: float) -> None:
        await asyncio.sleep(nach)
        await ws.close()

    async def start(self, port: int = 0, ssl_context: ssl.SSLContext | None = None) -> "Miniserver":
        """ssl_context: HTTPS/WSS wie Gen2 (sonst HTTP, siehe Fixture miniserver_http)."""
        app = web.Application()
        app.router.add_get("/stats/{f}", self._stats)
        app.router.add_get("/jdev/{tail:.*}", self._jdev)
        app.router.add_get("/camimage/{ua}/{ts}", self._camimage)
        app.router.add_get("/data/LoxAPP3.json", self._loxapp3)
        app.router.add_get("/ws/rfc6455", self._ws)
        self.runner, self.port = await serve(app, port, ssl_context)
        return self

    async def stop(self) -> None:
        self._ws_ende.set()
        for ws in list(self._ws_offen):
            await ws.close()
        if self.runner:
            await self.runner.cleanup()
            self.runner = None


# SDP einer Tuerstation: G.711 (PCMU, PCMA) und DTMF
TUER_SDP = ("v=0\r\no=tuer 1 1 IN IP4 127.0.0.1\r\ns=-\r\nc=IN IP4 127.0.0.1\r\nt=0 0\r\n"
            "m=audio 7078 RTP/AVP 0 8 101\r\na=rtpmap:0 PCMU/8000\r\na=rtpmap:8 PCMA/8000\r\n"
            "a=rtpmap:101 telephone-event/8000\r\n")


class SipTuer(asyncio.DatagramProtocol):
    """Nachbau einer SIP-Tuerstation fuer OPTIONS ueber UDP auf 127.0.0.1.

    anmeldung   verlangt Digest (401 mit WWW-Authenticate); die Antwort wird hier
                unabhaengig von bin/sip_probe.py nachgerechnet
    proxy       verlangt sie wie ein Proxy (407, Proxy-Authenticate/-Authorization)
    qop         Aufforderung mit qop="auth" (sonst die alte Form ohne)
    algorithmus "MD5" oder "SHA-256"
    sdp         200 OK mit SDP (PCMU, PCMA, telephone-event)
    stumm       antwortet nie (nimmt die Anfragen aber auf)
    vorlaeufig  Sekunden: schickt erst "100 Trying", die Antwort so viel spaeter
    """
    REALM = "tuer.local"

    def __init__(self, user="tuer", passwort="geheim", anmeldung=True, proxy=False, qop=True,
                 algorithmus="MD5", sdp=True, stumm=False, vorlaeufig=0.0) -> None:
        self.user, self.passwort, self.anmeldung, self.proxy, self.qop = user, passwort, anmeldung, proxy, qop
        self.algorithmus, self.sdp, self.stumm, self.vorlaeufig = algorithmus, sdp, stumm, vorlaeufig
        self.anfragen: list[str] = []
        self.nonce = ""
        self.transport = None
        self.port = 0

    async def start(self) -> "SipTuer":
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(lambda: self, local_addr=("127.0.0.1", 0))
        self.port = self.transport.get_extra_info("sockname")[1]
        return self

    def stop(self) -> None:
        if self.transport:
            self.transport.close()

    def datagram_received(self, data: bytes, addr) -> None:
        text = data.decode("utf-8")
        self.anfragen.append(text)
        if self.stumm:
            return
        zeilen = text.split("\r\n")
        methode = zeilen[0].split(" ")[0]
        kopf = {}
        for z in zeilen[1:]:
            if ":" in z:
                n, w = z.split(":", 1)
                kopf[n.strip().lower()] = w.strip()
        auth = "proxy-authorization" if self.proxy else "authorization"
        if self.anmeldung and auth not in kopf:
            self.nonce = os.urandom(8).hex()
            aufforderung = (("Proxy-Authenticate" if self.proxy else "WWW-Authenticate")
                            + f': Digest realm="{self.REALM}", nonce="{self.nonce}", '
                            f"algorithm={self.algorithmus}" + (', qop="auth"' if self.qop else ""))
            return self._antworte(addr, kopf, "407 Proxy Authentication Required" if self.proxy
                                  else "401 Unauthorized", [aufforderung])
        if self.anmeldung and not self._digest_ok(kopf[auth], methode):
            return self._antworte(addr, kopf, "403 Forbidden")
        self._antworte(addr, kopf, "200 OK", ["Allow: INVITE, ACK, CANCEL, BYE, OPTIONS",
                                              "User-Agent: Nachbau-Tuer/1.0"], TUER_SDP if self.sdp else "")

    def _digest_ok(self, auth: str, methode: str) -> bool:
        p = {k: v.strip('"') for k, v in re.findall(r'(\w+)=("[^"]*"|[^,\s]+)', auth)}
        h = hashlib.sha256 if self.algorithmus == "SHA-256" else hashlib.md5

        def H(x: str) -> str:
            return h(x.encode()).hexdigest()
        ha1, ha2 = H(f"{p.get('username')}:{self.REALM}:{self.passwort}"), H(f"{methode}:{p.get('uri')}")
        if self.qop:
            soll = H(f"{ha1}:{p.get('nonce')}:{p.get('nc')}:{p.get('cnonce')}:{p.get('qop')}:{ha2}")
        else:
            soll = H(f"{ha1}:{p.get('nonce')}:{ha2}")
        return p.get("username") == self.user and p.get("nonce") == self.nonce and p.get("response") == soll

    def _antworte(self, addr, kopf: dict, status: str, zusatz=(), rumpf: str = "") -> None:
        def senden(st: str, mit: list[str], body: str) -> None:
            zeilen = [f"SIP/2.0 {st}", f"Via: {kopf['via']}", f"From: {kopf['from']}",
                      f"To: {kopf['to']};tag=tuer1", f"Call-ID: {kopf['call-id']}", f"CSeq: {kopf['cseq']}", *mit]
            if body:
                zeilen.append("Content-Type: application/sdp")
            zeilen += [f"Content-Length: {len(body.encode())}", "", body]
            self.transport.sendto("\r\n".join(zeilen).encode(), addr)
        if self.vorlaeufig:
            senden("100 Trying", [], "")
            asyncio.get_running_loop().call_later(self.vorlaeufig, senden, status, list(zusatz), rumpf)
        else:
            senden(status, list(zusatz), rumpf)


# Antwort eines gekoppelten Audioservers auf einen Befehl ohne Anmeldung
AUDIO_GEKOPPELT = '{"error": "command not allowed when paired"}'


class Audioserver:
    """Nachbau eines Loxone-Audioservers (Port 7091) fuer den Ereignis-Client
    (bin/audioserver_events.py) und das Direkt-Backend (bin/audioserver.py).

    cfg_all       Antworten auf HTTP audio/cfg/all der Reihe nach als (Status,
                  Text), die letzte wiederholt sich; cfg_abrufe zaehlt sie
    verzoegerung  so viele Sekunden laesst sich audio/cfg/all Zeit
    gekoppelt   wie ein mit dem Miniserver gekoppelter Audioserver: Ein
                  Befehl ohne Anmeldung schliesst die WebSocket-Verbindung
    jwt           das Miniserver-JWT, das secure/authenticate tragen muss
    befehle       angekommene Befehle als (Befehl, angemeldet)
    verbindungen  alle WebSocket-Verbindungen, auch geschlossene

    WebSocket "/": Banner mit Session-Token, ein audio_event fuer Zone 1, dann
    audio/cfg/getkey und secure/authenticate. Die Anmeldung ist hier
    unabhaengig von bin/audioserver_auth.py nach dem Ablauf der Loxone-App
    nachgerechnet: RSA-PKCS#1 v1.5 ueber "key:iv:Session-Token", AES-256-CBC
    mit PKCS7 ueber das JWT. getroomfavs liefert einen Favoriten (Slot 1, id 7).
    """

    def __init__(self, gekoppelt: bool = True, cfg_all=((200, AUDIO_GEKOPPELT),), jwt: str = "JWT-1") -> None:
        self.gekoppelt = gekoppelt
        self.cfg_all = list(cfg_all)
        self.cfg_abrufe = 0
        self.verzoegerung = 0.0
        self.jwt = jwt
        self.schluessel = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        self.befehle: list[tuple[str, bool]] = []
        self.verbindungen: list[web.WebSocketResponse] = []
        self.runner: web.AppRunner | None = None
        self.port = 0

    async def _cfg(self, r: web.Request) -> web.Response:
        self.cfg_abrufe += 1
        if self.verzoegerung:
            await asyncio.sleep(self.verzoegerung)
        status, text = self.cfg_all[min(self.cfg_abrufe, len(self.cfg_all)) - 1]
        return web.Response(status=status, text=text)

    def _angemeldet(self, cmd: str, token: str) -> bool:
        _, _, _, rsa_b64, chiffre = cmd.split("/", 4)
        klar = self.schluessel.decrypt(base64.b64decode(unquote(rsa_b64)), padding.PKCS1v15()).decode()
        key_hex, iv_hex, sitzung = klar.split(":", 2)
        dec = Cipher(algorithms.AES(bytes.fromhex(key_hex)), modes.CBC(bytes.fromhex(iv_hex))).decryptor()
        roh = dec.update(base64.b64decode(unquote(chiffre))) + dec.finalize()
        ent = blockpadding.PKCS7(128).unpadder()
        return sitzung == token and (ent.update(roh) + ent.finalize()).decode() == self.jwt

    async def _ws(self, r: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(protocols=("remotecontrol",))
        await ws.prepare(r)
        self.verbindungen.append(ws)
        token, angemeldet = f"S{len(self.verbindungen)}", False
        await ws.send_str(f"LWSS V 17.2.08.28 | ~API:1.6~ | Session-Token: {token}")
        await ws.send_str(json.dumps({"audio_event": [{"playerid": 1, "name": "Küche", "title": "Lied",
                                                       "mode": "play", "volume": 20}]}))
        async for m in ws:
            cmd = m.data
            if cmd == "audio/cfg/getkey":
                n = self.schluessel.public_key().public_numbers()
                await ws.send_str(json.dumps({"getkey_result": [{"exp": n.e, "pubkey": format(n.n, "x")}]}))
            elif cmd.startswith("secure/authenticate/"):
                angemeldet = self._angemeldet(cmd, token)
                await ws.send_str(json.dumps({"authenticate_result":
                                              "authentication successful" if angemeldet else "denied"}))
            else:
                self.befehle.append((cmd, angemeldet))
                if self.gekoppelt and not angemeldet:
                    await ws.close()
                elif cmd.startswith("audio/cfg/getroomfavs/"):
                    await ws.send_str(json.dumps({"getroomfavs_result": [{"id": 1, "items": [
                        {"slot": 1, "id": 7, "name": "Radio 7091", "coverurl": ""}]}]}))
        return ws

    async def start(self) -> "Audioserver":
        app = web.Application()
        app.router.add_get("/audio/cfg/all", self._cfg)
        app.router.add_get("/", self._ws)
        self.runner, self.port = await serve(app)
        return self

    async def stop(self) -> None:
        for ws in self.verbindungen:
            await ws.close()
        if self.runner:
            await self.runner.cleanup()
            self.runner = None


class Anmeldung:
    """Ersatz fuer LoxoneClient.authenticate(): jede Anmeldung stellt am
    Nachbau ein neues gueltiges Token aus. fehler=True: Anmeldung scheitert."""

    def __init__(self, ms: Miniserver, fehler: bool = False) -> None:
        self.ms, self.fehler, self.n = ms, fehler, 0

    async def authenticate(self) -> str:
        self.n += 1
        if self.fehler:
            raise RuntimeError("Anmeldung abgelehnt")
        self.ms.token = f"T{self.n + 1}"
        return self.ms.token

    async def close(self) -> None:
        pass


def neue_app(ms: Miniserver) -> W.App:
    """App-Objekt, das mit dem Nachbau spricht (angemeldet, HTTP statt HTTPS).
    Aufrufer schliesst app.icon_session am Ende."""
    app = W.App({"host": "127.0.0.1", "port": 80})
    app.host, app.port = "127.0.0.1", ms.port
    app.client = Anmeldung(ms)
    app.alg = ms.hash_alg                   # wie nach getkey2
    app.icon_session = aiohttp.ClientSession()
    app._set_token(ms.token)
    return app


def bloecke(view: dict, art: str) -> list:
    return [b for b in view.get("blocks") or [] if b.get("k") == art]


async def visu_starten(app: W.App, routen=()) -> tuple[web.AppRunner, int, asyncio.Task]:
    """Panel-Seite und /ws wie im Betrieb, dazu der Broadcaster.
    routen: weitere (Methode, Pfad, Handler), etwa die des Reiters Displays.
    -> (runner, port, broadcaster); Aufrufer bricht den Broadcaster ab und
    raeumt den runner auf."""
    ui = web.Application()
    ui["app"] = app
    ui.router.add_get("/", W.index)
    ui.router.add_get("/ws", W.ws_handler)
    ui.router.add_get("/config", W.config_index)
    ui.router.add_get("/api/meta", W.api_meta)
    ui.router.add_get("/api/settings", W.api_settings)
    ui.router.add_get("/i18n.js", W.i18n_js)
    ui.router.add_get("/raster.js", W.raster_js)
    for methode, pfad, h in routen:
        ui.router.add_route(methode, pfad, h)
    runner, port = await serve(ui)
    return runner, port, asyncio.create_task(app.broadcaster())


def anlage(controls: dict) -> dict:
    """Minimale Struktur (LoxAPP3) mit zwei Raeumen und einer Kategorie."""
    return {"rooms": {"r1": {"name": "Zentral"}, "r2": {"name": "Technikraum"}},
            "cats": {"c1": {"name": "Energie"}}, "controls": controls}


# Raum mit vier Kategorien fuer die Sprungmarken der unteren Leiste: 3 + 2 + 4 + 3
# Schalter in "Sauna" (r1), dazu 2 Schalter im "Technikraum" (r2) fuer die freie
# Auswahl ueber zwei Raeume. Bei 2x2 beginnt "Heizung" unten rechts auf Seite 1,
# bei 2x3 "Lüftung" - genau dort, wo ein Sprung frueher auf die Folgeseite rutschte.
RAUM_KATS = {"c1": ("Beleuchtung", 3), "c2": ("Heizung", 2), "c3": ("Lüftung", 4), "c4": ("Sonstiges", 3)}


def raum_anlage() -> tuple[dict, dict]:
    """-> (Struktur, States) fuer ein Raum-Panel mit vier Kategorien."""
    controls, states, n = {}, {}, 0
    for cat, (name, anzahl) in RAUM_KATS.items():
        for i in range(anzahl):
            n += 1
            controls[f"S{n}"] = {"name": f"{name} {i + 1}", "type": "Switch", "uuidAction": f"S{n}",
                                 "room": "r1", "cat": cat, "states": {"active": f"s{n}"}}
            states[f"s{n}"] = 0
    for i in (1, 2):
        controls[f"T{i}"] = {"name": f"Technik {i}", "type": "Switch", "uuidAction": f"T{i}",
                             "room": "r2", "cat": "c1", "states": {"active": f"t{i}"}}
        states[f"t{i}"] = 0
    return ({"rooms": {"r1": {"name": "Sauna"}, "r2": {"name": "Technikraum"}},
             "cats": {c: {"name": v[0]} for c, v in RAUM_KATS.items()}, "controls": controls}, states)


# Alte Raumregelung (IRoomController, v1) in der Form, die ein echter Miniserver
# liefert (Struktur aus ioBroker.loxone#22): "temperatures" ist in states eine
# Liste mit einer UUID je Temperatur-Nummer 0..6, details.temperatures sagt je
# Nummer, ob der Wert absolut ist oder von Komfort abhaengt.
IRC1_ABSOLUT = {"0": False, "1": True, "2": True, "3": True, "4": True, "5": False, "6": False}
IRC1_STATES = ("tempTarget", "tempActual", "error", "mode", "serviceMode", "currHeatTempIx",
               "currCoolTempIx", "override", "isPreparing", "valveHeat", "valveCool", "openWindow",
               "overrideTotal", "movement", "manualMode")


def irc1_baustein(**werte) -> tuple[dict, dict]:
    """-> (Control, States) einer alten Raumregelung im Autopilot Heizen mit
    Komfort Heizen aktiv. werte ueberschreibt States nach Namen; "temperatures"
    ist die Liste der Werte je Nummer (Eco, Erhoehte Waerme, Party relativ)."""
    states = {n: f"irc-{n}" for n in IRC1_STATES}
    states["temperatures"] = [f"irc-t{i}" for i in range(len(IRC1_ABSOLUT))]
    control = {"name": "Wohnzimmer Heizung", "type": "IRoomController", "uuidAction": "IRC",
               "room": "r1", "cat": "c1",
               "details": {"restrictedToMode": 0, "format": "%.1f°",
                           "temperatures": {k: {"isAbsolute": v} for k, v in IRC1_ABSOLUT.items()}},
               "states": states}
    w = {"tempTarget": 22.0, "tempActual": 20.5, "error": 0, "mode": 3, "serviceMode": 0,
         "currHeatTempIx": 1, "currCoolTempIx": 2, "override": 0, "isPreparing": 0, "valveHeat": 0,
         "valveCool": 0, "openWindow": 0, "overrideTotal": 0, "movement": 0, "manualMode": 0,
         "temperatures": [2.0, 22.0, 24.0, 12.0, 30.0, 1.0, 0.5], **werte}
    werte_uuid = {states[n]: w[n] for n in IRC1_STATES}
    werte_uuid.update(zip(states["temperatures"], w["temperatures"]))
    return control, werte_uuid


# Intelligente Raumregelung V2 (IRoomControllerV2): State-Namen wie in der
# openHAB-Loxone-Anbindung, Temperatur-Modi (details.timerModes) wie activeMode
# dort: 0 Eco, 1 Komfort, 2 Gebaeudeschutz.
IRC2_STATES = ("activeMode", "operatingMode", "prepareState", "openWindow", "tempActual",
               "tempTarget", "comfortTemperature", "comfortTemperatureCool", "comfortTolerance",
               "absentMinOffset", "absentMaxOffset", "frostProtectTemperature",
               "heatProtectionTemperature", "comfortTemperatureOffset", "overrideEntries")


def irc2_baustein(**werte) -> tuple[dict, dict]:
    """-> (Control, States) einer Raumregelung V2 in Automatik Heizen & Kuehlen
    mit Komfort aktiv; werte ueberschreibt States nach Namen."""
    states = {n: f"irc2-{n}" for n in IRC2_STATES}
    control = {"name": "Bad Heizung", "type": "IRoomControllerV2", "uuidAction": "IRC2",
               "room": "r1", "cat": "c1",
               "details": {"format": "%.1f°", "timerModes": [
                   {"id": 0, "name": "Eco"}, {"id": 1, "name": "Komfort"},
                   {"id": 2, "name": "Gebäudeschutz"}]},
               "states": states}
    w = {"activeMode": 1, "operatingMode": 0, "prepareState": 0, "openWindow": 0,
         "tempActual": 21.0, "tempTarget": 22.5, "comfortTemperature": 22.5,
         "comfortTemperatureCool": 25.0, "comfortTolerance": 1.0, "absentMinOffset": 2.0,
         "absentMaxOffset": 2.0, "frostProtectTemperature": 5.0, "heatProtectionTemperature": 35.0,
         "comfortTemperatureOffset": 0.0, "overrideEntries": "[]", **werte}
    return control, {states[n]: w[n] for n in IRC2_STATES}


# Energieflussmonitor (EFM) mit eigenen Knoten und Energiemanager (EM2) mit
# Ppwr/Gpwr/Spwr in kW, Vorzeichen aus Sicht des Hauses (positiv = ins Haus).
EFM_NODES = [{"name": "Netz", "nodeType": "Grid"}, {"name": "PV", "nodeType": "Production"},
             {"name": "Batterie", "nodeType": "Storage"}, {"name": "Wärmepumpe", "nodeType": "Load"}]

EFM = {"name": "Energieflussmonitor", "type": "EFM", "uuidAction": "F", "room": "r1", "cat": "c1",
       "details": {"actualFormat": "%.2f kW", "nodes": EFM_NODES},
       "states": {"Ppwr": "f-p", "Gpwr": "f-g", "Spwr": "f-s",
                  **{f"actual{i}": f"f-a{i}" for i in range(len(EFM_NODES))}}}

EM2 = {"name": "Energiemanager", "type": "EnergyManager2", "uuidAction": "M", "room": "r1", "cat": "c1",
       "details": {}, "states": {"Ppwr": "m-p", "Gpwr": "m-g", "Spwr": "m-s", "Ssoc": "m-soc"}}


def _zaehler_zeile(jetzt):
    """Echter Zaehler: 0,8 kWh je Stunde aufsummiert, dazu die Leistung als V2."""
    start = jetzt - timedelta(hours=24 * 31)
    return lambda t: (f'V="{1000 + (t - start).total_seconds() / 3600 * 0.8:.3f}" '
                      f'V2="{0.5 + 0.4 * math.sin(t.hour):.3f}"')


def v1_bausteine(ms: Miniserver, jetzt: datetime) -> dict:
    """Aufzeichnungen (V1, ein Monat) am Nachbau ablegen und die Bausteine dazu:
    T Boiler (Messwert), Z Stromzaehler (Zaehlerstand + Leistung), R Regen
    (Ein/Aus), X ohne Aufzeichnung."""
    ms.files.update(monatsdateien("TEMP", lambda t: f'V="{52 + 7 * math.cos((t.hour - 15) / 24 * 2 * math.pi):.2f}"',
                                  24 * 31, 30, jetzt))
    ms.files.update(monatsdateien("ZAEHL", _zaehler_zeile(jetzt), 24 * 31, 20, jetzt))
    ms.files.update(monatsdateien("REGEN", lambda t: 'V="1"' if t.hour in (6, 7, 16) else 'V="0"',
                                  24 * 31, 30, jetzt))
    return {
        "T": {"name": "Boiler", "type": "InfoOnlyAnalog", "uuidAction": "TEMP", "states": {"value": "sv"},
              "details": {"format": "%.1f°C"},
              "statistic": {"frequency": 6, "outputs": [{"id": 0, "name": "Boiler", "format": "%.1f°C", "visuType": 0}]}},
        "Z": {"name": "Stromzähler", "type": "Meter", "uuidAction": "ZAEHL", "states": {"actual": "sa", "total": "st"},
              "details": {"actualFormat": "%.3fkW", "totalFormat": "%.1fkWh"},
              "statistic": {"frequency": 6, "outputs": [
                  {"id": 0, "name": "Gesamtverbrauch", "format": "%.1fkWh", "visuType": 2},
                  {"id": 1, "name": "Leistung", "format": "%.3fkW", "visuType": 0}]}},
        "R": {"name": "Regen", "type": "InfoOnlyDigital", "uuidAction": "REGEN", "states": {"active": "sr"},
              "statistic": {"frequency": 1, "outputs": [{"id": 0, "name": "Regen", "visuType": 1}]}},
        "X": {"name": "Ohne Aufzeichnung", "type": "InfoOnlyAnalog", "uuidAction": "X", "states": {"value": "sx"}},
    }


def pv_leistung(ts):
    """PV-Leistung in kW: Sinusbogen von 6 bis 20 Uhr, Spitze 8 kW."""
    h = time.localtime(ts).tm_hour + time.localtime(ts).tm_min / 60
    return max(0.0, 8.0 * math.sin((h - 6) / 14 * math.pi)) if 6 <= h <= 20 else 0.0


def hauslast(ts):
    """Hausverbrauch in kW: tagsueber 1,1, nachts 0,4."""
    return 1.1 if 7 <= time.localtime(ts).tm_hour < 22 else 0.4


def zaehlerstand(fn, basis=int(time.time()) - 40 * 86400):
    """Zaehlerstand aus einer Leistung fn (kW), aufsummiert ab basis."""
    return lambda ts: 5000 + sum(fn(t) * 0.5 for t in range(basis - basis % 3600, ts - ts % 3600, 1800))


# --- Bausteine nach der Loxone-Strukturdoku (Stand 16.0). State- und
# details-Namen wie an einer echten Anlage (Ausgabe von /api/types), Werte so,
# wie die Doku sie beschreibt.

def aufab_baustein(wert=1, fehler=0, **details) -> tuple[dict, dict]:
    """Auf/Ab-Taster mit Wert (UpDownAnalog, in der Doku "UpDownLeftRight
    analog"): details format/min/max/step, States value und error."""
    control = {"name": "1=kompl AUF 3=Lamelle waagrecht", "type": "UpDownAnalog", "uuidAction": "UDA",
               "room": "r1", "cat": "c1",
               "details": {"format": "%.0f", "min": 1, "max": 3, "step": 1, "jLockable": True, **details},
               "states": {"value": "uda-v", "error": "uda-e", "jLocked": "uda-l"}}
    return control, {"uda-v": wert, "uda-e": fehler, "uda-l": ""}


# Zonen einer Bewaesserung: id ab 0, Laufzeit in Sekunden; die Hecke gibt die
# Logik vor (setByLogic).
BEW_ZONEN = [{"id": 0, "name": "Rasen vorne", "duration": 600, "setByLogic": False},
             {"id": 1, "name": "Beete", "duration": 300, "setByLogic": False},
             {"id": 2, "name": "Hecke", "duration": 900, "setByLogic": True}]
BEW_STATES = ("active", "currentZone", "expectedPrecipitation", "jLocked", "maxExpectedPrecipitation",
              "rainActive", "rainTime", "zones")


def bewaesserung_baustein(**werte) -> tuple[dict, dict]:
    """Bewaesserung (Irrigation): zones als JSON-Text, currentZone -1 = aus,
    0..7 = id der Zone, 8 = alle; rainTime in Sekunden der letzten 24 h."""
    states = {n: f"bew-{n}" for n in BEW_STATES}
    control = {"name": "Bewässerung", "type": "Irrigation", "uuidAction": "BEW", "room": "r1", "cat": "c1",
               "details": {"jLockable": True}, "states": states}
    w = {"active": 0, "currentZone": -1, "expectedPrecipitation": 0.0, "jLocked": "",
         "maxExpectedPrecipitation": 2.0, "rainActive": 0, "rainTime": 0, "zones": json.dumps(BEW_ZONEN),
         **werte}
    return control, {states[n]: w[n] for n in BEW_STATES}


# Betriebsarten wie im Abschnitt operatingModes einer Struktur; 3..9 sind laut
# Doku Montag bis Sonntag, 0..2 haben Vorrang vor ihnen.
BETRIEBSARTEN = {"0": "Feiertag", "1": "Urlaub", "3": "Montag", "4": "Dienstag", "5": "Mittwoch",
                 "6": "Donnerstag", "7": "Freitag", "8": "Samstag", "9": "Sonntag", "10": "Arbeitstag"}
# Weckzeiten: ab Version 13.0 hat jeder Wecker einen Eintrag mit nightLight
# (daily statt modes), dazu zwei gewoehnliche.
WECKZEITEN = {
    "0": {"name": "Nachtlicht", "isActive": False, "alarmTime": 25200, "modes": [], "nightLight": True,
          "daily": True},
    "1": {"name": "Arbeit", "isActive": True, "alarmTime": 22500, "modes": [3, 4, 5, 6, 7],
          "nightLight": False, "daily": False},
    "2": {"name": "Wochenende", "isActive": False, "alarmTime": 30600, "modes": [8, 9, 0],
          "nightLight": False, "daily": False},
}
WECKER_STATES = ("confirmationNeeded", "currentEntry", "deviceSettings", "deviceState", "entryList",
                 "isAlarmActive", "isEnabled", "jLocked", "nextEntry", "nextEntryMode", "nextEntryTime",
                 "prepareDuration", "ringDuration", "ringingTime", "snoozeDuration", "snoozeTime",
                 "wakeAlarmSoundSettings")


def wecker_baustein(eintraege=None, **werte) -> tuple[dict, dict]:
    """Wecker (AlarmClock): entryList als JSON-Text {entryID: {name, isActive,
    alarmTime (Sekunden ab Mitternacht), modes, nightLight, daily}}, Dauern in
    Sekunden."""
    states = {n: f"wk-{n}" for n in WECKER_STATES}
    control = {"name": "Anna Wecker", "type": "AlarmClock", "uuidAction": "WK", "room": "r1", "cat": "c1",
               "details": {"hasNightLight": True, "snoozeDurationConnected": False,
                           "brightActiveConnected": False, "brightInactiveConnected": False,
                           "wakeAlarmSoundConnected": False, "wakeAlarmVolumeConnected": False,
                           "wakeAlarmSlopingConnected": False, "wakeAlarmSounds": [], "jLockable": True},
               "states": states}
    w = {"confirmationNeeded": 0, "currentEntry": -1, "deviceSettings": "", "deviceState": 0,
         "entryList": json.dumps(WECKZEITEN if eintraege is None else eintraege), "isAlarmActive": 0,
         "isEnabled": 1, "jLocked": "", "nextEntry": 1, "nextEntryMode": 3, "nextEntryTime": 0,
         "prepareDuration": 900, "ringDuration": 300, "ringingTime": 0, "snoozeDuration": 540,
         "snoozeTime": 0, "wakeAlarmSoundSettings": "", **werte}
    return control, {states[n]: w[n] for n in WECKER_STATES}


# Verpasste Klingeln wie im State lastBellEvents: JJJJMMTTHHMMSS, mit | getrennt
KLINGELN = ("20261001074904", "20261002181530", "20261003091200")


def intercom_baustein(klingeln=KLINGELN, bilder=True, **werte) -> tuple[dict, dict]:
    """Tuersprechstelle (Intercom, "Door Controller"): Klingel bell, verpasste
    Klingeln lastBellEvents; mit details.lastBellEventImages liefert der
    Miniserver je Klingel ein Bild (camimage). Ausgaenge sind
    Pushbutton-Subcontrols (pulse). Kamera und SIP-Zugang stehen seit 8.1 in
    den gesicherten Details, darum das Kennzeichen securedDetails."""
    names = ("bell", "jLocked", "lastBellEvents", "lastBellTimestamp")
    states = {n: f"ic-{n}" for n in names}
    control = {"name": "Eingang Intercom", "type": "Intercom", "uuidAction": "IC", "room": "r1", "cat": "c1",
               "securedDetails": True,
               "details": {"deviceType": 1, "videoInfo": {}, "audioInfo": {}, "lastBellEventImages": bilder,
                           "showBellImage": False, "jLockable": True},
               "states": states,
               "subControls": {"IC/1": {"name": "Tür öffnen", "type": "Pushbutton", "uuidAction": "IC/1",
                                        "states": {"active": "ic-o1"}}}}
    w = {"bell": 0, "jLocked": "", "lastBellEvents": "|".join(klingeln), "lastBellTimestamp": "", **werte}
    return control, {states[n]: w[n] for n in names}


ANTWORTEN = ("Bin gleich da", "Bitte das Paket vor die Tür legen", "")


def intercom_v2_baustein(geraet=1, gesichert=False, antworten=ANTWORTEN, **werte) -> tuple[dict, dict]:
    """Neue Intercom (IntercomV2, in Loxone Config der Baustein "Intercom") laut
    Strukturdoku 17.0: Klingel bell, Antworten answers (Liste als JSON-Text,
    playTts/{idx} spielt eine ab), muted und mute/{0/1}, Geraetezustand
    deviceState (0 StateUnknown, 1 StateOk, 2 StateRebooting, 3
    StateInitializing), Ausgaenge als Pushbutton-Subcontrols. deviceType 1 ist
    die Loxone Intercom, 0 eine andere. Gesicherte Details nennt die Doku fuer
    den Typ nicht, darum das Kennzeichen nur mit gesichert."""
    names = ("bell", "address", "answers", "muted", "deviceState", "videoSettingsIntern", "videoSettingsExtern")
    states = {n: f"ic2-{n}" for n in names}
    control = {"name": "Haustür Intercom", "type": "IntercomV2", "uuidAction": "IC2V", "room": "r1", "cat": "c1",
               "details": {"deviceType": geraet, "serialNo": "504F94FF1A2B", "deviceName": "Intercom Haustür",
                           "deviceUuid": "1a2b3c4d-0123-4567-ffffeeeeddddcccc",
                           "optionsFramerate": [{"id": 5, "name": "5 fps"}, {"id": 10, "name": "10 fps"}],
                           "optionsResolution": [{"id": 480, "name": "480p"}, {"id": 720, "name": "720p"}]},
               "states": states,
               "subControls": {"IC2V/1": {"name": "Tür öffnen", "type": "Pushbutton", "uuidAction": "IC2V/1",
                                          "states": {"active": "ic2-o1"}}}}
    if gesichert:
        control["securedDetails"] = True
    w = {"bell": 0, "address": "192.168.1.98", "answers": json.dumps(list(antworten), ensure_ascii=False),
         "muted": 0, "deviceState": 1, "videoSettingsIntern": 0, "videoSettingsExtern": 0, **werte}
    return control, {states[n]: w[n] for n in names}
