"""Kamerabilder fuer /mjpeg: ein Strom je Kamera, verteilt an alle Zuschauer.

Bisher holte /mjpeg fuer jeden Zuschauer einen eigenen Strom von der Kamera:
drei Panels und zwei Bento-Zellen hiessen fuenf Stroeme an der Tuerstation, und
riss einer ab, blieb sein Bild stehen. Jetzt haelt der Kameraverteiler je
Kamera (Adresse und Anmeldung) einen Kamerastrom. Der zerlegt den MJPEG-Strom
in Bilder (MjpegZerleger) und gibt jedem Zuschauer das jeweils neueste: Ein
langsames Panel ueberspringt Bilder, statt die anderen aufzuhalten.

- Bricht die Kamera ab, verbindet der Strom mit wachsender Pause neu
  (PAUSE_MIN_S bis PAUSE_MAX_S). Die Zuschauer bleiben verbunden und sehen
  bis dahin das letzte Bild. Ein neuer Zuschauer kuerzt die Pause ab: Er
  wartet auf einen Versuch von jetzt, nicht auf den letzten Fehlschlag.
- Nach dem letzten Zuschauer laeuft er noch NACHLAUF_S weiter (Seitenwechsel,
  neu aufgebaute Seite), dann trennt er.
- Antworten wie bisher: 502, wenn die Kamera nicht erreichbar ist oder nicht
  mit 200 antwortet, 200, sobald sie es tut (auch wenn ihr Strom danach
  abreisst: der Zuschauer wartet dann aufs Neuverbinden). Ein neuer Zuschauer
  bekommt sofort das letzte Bild, solange der Strom laeuft; ist die Kamera
  weg, nur, wenn es juenger als BILD_FRISCH_S ist, sonst 502. Schickt die Kamera ein Einzelbild statt multipart, geht es
  unveraendert an den Zuschauer, und jeder Abruf holt ein neues.
- Je Kamera hoechstens ZUSCHAUER_MAX Zuschauer, danach 503 (docs/ARCHITEKTUR.md,
  Befund S6).

Nur aiohttp, importiert kein Server-Modul. Ins Log kommt von der Adresse nur
der Host: Anmeldedaten in der Adresse bleiben draussen."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web

log = logging.getLogger("loxpanel.webvisu")   # derselbe Logger wie der Server

NACHLAUF_S = 10.0          # so lange haelt der Strom nach dem letzten Zuschauer
PAUSE_MIN_S = 1.0          # Pause vor dem ersten neuen Versuch, verdoppelt sich ...
PAUSE_MAX_S = 30.0         # ... bis hierher; ein gelieferter Strom setzt sie zurueck
VERBINDEN_S = 10.0         # Verbindungsaufbau zur Kamera
LESEN_S = 30.0             # so lange darf die Kamera schweigen (wie bisher)
BILD_FRISCH_S = 30.0       # ein spaeter Zuschauer bekommt ein so junges letztes Bild sofort
ZUSCHAUER_MAX = 16         # je Kamera
SCHREIBEN_S = 30.0         # haengt ein Zuschauer so lange an einem Bild, ist er weg
PRUEF_S = 1.0              # so oft schaut ein wartender Zuschauer, ob er noch verbunden ist
BILD_MAX = 8 * 1024 * 1024
KOPF_MAX = 8 * 1024        # Kopf eines Teils oder Zeile vor der ersten Grenze
GRENZE = "loxpanelbild"    # boundary der Antwort an die Zuschauer

_TYP = re.compile(r"[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+")


def _boundary(ctype: str) -> str:
    """boundary aus dem Content-Type der Kamera, ohne Anfuehrungszeichen; "" ohne."""
    m = re.search(r'boundary\s*=\s*"?([^";]+)"?', ctype or "", re.I)
    return m.group(1).strip() if m else ""


def _kopf_lesen(kopf: str) -> tuple[str, int | None]:
    """Kopf eines Teils -> (Content-Type, Content-Length). Ein Typ, der keiner
    ist, wird image/jpeg; ValueError bei einer Laenge ueber BILD_MAX."""
    typ, laenge = "image/jpeg", None
    for zeile in kopf.splitlines():
        name, _, wert = zeile.partition(":")
        name, wert = name.strip().lower(), wert.strip()
        if name == "content-type" and _TYP.fullmatch(wert.split(";")[0].strip()):
            typ = wert.split(";")[0].strip()
        elif name == "content-length" and wert.isdigit():
            laenge = int(wert)
            if laenge > BILD_MAX:
                raise ValueError(f"Bild mit {laenge} Bytes")
    return typ, laenge


class MjpegZerleger:
    """Zerlegt multipart/x-mixed-replace in Bilder. Die Grenze kommt aus dem
    boundary des Content-Type (mit oder ohne fuehrende "--"); ohne boundary
    gilt die erste Zeile, die mit "--" beginnt. Ein Teil endet nach seinem
    Content-Length oder vor der naechsten Grenze (ohne Content-Length kommt
    ein Bild also erst mit dem Beginn des naechsten). Zeilen enden mit CRLF oder
    LF, ein Teil ohne Kopf (gleich das JPEG) geht auch, Text vor der ersten
    Grenze wird uebergangen. futter() -> fertige Bilder als (Content-Type,
    Daten); ValueError, wenn ein Teil oder ein Kopf ueber die Grenzen waechst."""

    def __init__(self, boundary: str = ""):
        b = boundary.encode("latin-1", "replace")
        self._kandidaten = {b"--" + b, b} if b else set()
        self._grenze = b""
        self._puffer = bytearray()
        self._stand = "grenze"
        self._typ, self._laenge = "image/jpeg", None
        self._ab = 0                 # bis hierher ist der Puffer schon nach der Grenze durchsucht

    def _ist_grenze(self, zeile: bytes) -> bool:
        if self._grenze:
            return zeile in (self._grenze, self._grenze + b"--")
        if (zeile in self._kandidaten) if self._kandidaten else zeile.startswith(b"--"):
            self._grenze = zeile
            return True
        return False

    def futter(self, daten: bytes) -> list[tuple[str, bytes]]:
        self._puffer += daten
        fertig = []
        while True:
            p = self._puffer
            if self._stand == "grenze":
                i = p.find(b"\n")
                if i < 0:
                    if len(p) > KOPF_MAX:
                        raise ValueError("keine Grenze im MJPEG-Strom")
                    break
                zeile = bytes(p[:i]).strip()
                del p[:i + 1]
                if zeile and self._ist_grenze(zeile):
                    self._stand = "kopf"
            elif self._stand == "kopf":
                if p[:2] == b"\xff\xd8":                     # ohne Kopf: gleich das JPEG
                    self._typ, self._laenge, self._stand, self._ab = "image/jpeg", None, "inhalt", 0
                    continue
                if p[:1] == b"\n" or p[:2] == b"\r\n":        # leerer Kopf
                    ende, n = 0, (1 if p[:1] == b"\n" else 2)
                else:
                    treffer = [(i, n) for i, n in ((p.find(b"\r\n\r\n"), 4), (p.find(b"\n\n"), 2)) if i >= 0]
                    if not treffer:
                        if len(p) > KOPF_MAX:
                            raise ValueError("Kopf eines Bildes zu lang")
                        break
                    ende, n = min(treffer)
                self._typ, self._laenge = _kopf_lesen(bytes(p[:ende]).decode("latin-1"))
                del p[:ende + n]
                self._stand, self._ab = "inhalt", 0
            elif self._laenge is not None:
                if len(p) < self._laenge:
                    break
                bild = bytes(p[:self._laenge])
                del p[:self._laenge]
                self._stand = "grenze"
                if bild:
                    fertig.append((self._typ, bild))
            else:
                naechste = b"\n" + self._grenze
                if p.startswith(self._grenze):               # leerer Teil
                    self._stand = "grenze"
                    continue
                i = p.find(naechste, self._ab)
                if i < 0:
                    if len(p) > BILD_MAX:
                        raise ValueError("Bild ohne Ende im MJPEG-Strom")
                    self._ab = max(0, len(p) - len(naechste))
                    break
                bild = bytes(p[:i - 1] if i and p[i - 1:i] == b"\r" else p[:i])
                del p[:i + 1]
                self._stand = "grenze"
                if bild:
                    fertig.append((self._typ, bild))
        return fertig


def _teil(typ: str, bild: bytes) -> bytes:
    """Ein Bild als Teil der Antwort an die Zuschauer (boundary GRENZE)."""
    return (f"--{GRENZE}\r\nContent-Type: {typ}\r\nContent-Length: {len(bild)}\r\n\r\n"
            .encode("latin-1") + bild + b"\r\n")


async def _ganz_lesen(antwort: aiohttp.ClientResponse) -> bytes:
    """Antwort der Kamera ganz, hoechstens BILD_MAX Bytes (sonst ValueError)."""
    daten = bytearray()
    async for teil in antwort.content.iter_any():
        daten += teil
        if len(daten) > BILD_MAX:
            raise ValueError("Einzelbild zu gross")
    return bytes(daten)


class Kamerastrom:
    """Der eine Strom von einer Kamera fuer alle ihre Zuschauer. zustand:
    "verbinden", "laeuft" (die Kamera hat mit 200 und multipart geantwortet),
    "abgerissen" (danach endete der Strom, er verbindet neu), "fehler" (nicht
    erreichbar oder nicht 200, Text in fehler), "einzelbild" (die Kamera
    schickte ein Bild statt eines Stroms) oder "ende" (getrennt)."""

    def __init__(self, cam: dict, beim_ende):
        self.schluessel = Kameraverteiler.schluessel(cam)
        self.url, self.user, self.passwort = self.schluessel
        try:
            self.host = urlsplit(self.url).hostname or "?"
        except ValueError:
            self.host = "?"
        self.zustand, self.fehler = "verbinden", ""
        self.einzelbild: tuple[str, bytes] | None = None
        self.teil = b""              # das neueste Bild, fertig als Teil der Antwort
        self.nummer = 0              # zaehlt die Bilder
        self.zeit = 0.0              # monotonic des neuesten Bildes
        self.zuschauer = 0
        self.ergebnisse = 0          # zaehlt die Ergebnisse der Versuche (laeuft, Fehler, Einzelbild)
        self._signal = asyncio.Event()
        self._weck = asyncio.Event()  # kuerzt die Pause vor dem naechsten Versuch ab
        self._task: asyncio.Task | None = None
        self._nachlauf: asyncio.Task | None = None
        self._beim_ende = beim_ende

    def _melden(self) -> None:
        """Wartende Zuschauer wecken: jeder wartet auf das Event von eben."""
        signal, self._signal = self._signal, asyncio.Event()
        signal.set()

    def _neues_bild(self, typ: str, bild: bytes) -> None:
        self.teil = _teil(typ, bild)
        self.nummer += 1
        self.zeit = time.monotonic()
        self._melden()

    def frisch(self) -> bool:
        return self.nummer > 0 and time.monotonic() - self.zeit < BILD_FRISCH_S

    def bild_gilt(self) -> bool:
        """Darf ein neuer Zuschauer das letzte Bild sofort sehen: bei einem
        laufenden Strom immer (es ist das aktuelle), sonst nur, wenn es frisch ist."""
        return self.nummer > 0 and (self.zustand == "laeuft" or self.frisch())

    def aktiv(self) -> bool:
        return self._task is not None and not self._task.done()

    def starten(self) -> None:
        self._task = asyncio.create_task(self._lauf())

    def nachlauf_abbrechen(self) -> None:
        if self._nachlauf is not None:
            self._nachlauf.cancel()
            self._nachlauf = None

    def nachlauf_starten(self) -> None:
        self.nachlauf_abbrechen()
        self._nachlauf = asyncio.create_task(self._spaeter_trennen())

    async def _spaeter_trennen(self) -> None:
        await asyncio.sleep(NACHLAUF_S)
        self._nachlauf = None
        if self.zuschauer <= 0:
            self._beim_ende(self)        # vor dem Trennen: wer jetzt kommt, bekommt einen neuen Strom
            await self._trennen()

    async def _trennen(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def beenden(self) -> None:
        """Strom trennen und alle Zuschauer entlassen (Herunterfahren)."""
        self.nachlauf_abbrechen()
        await self._trennen()
        if self.zustand != "einzelbild":
            self.zustand = "ende"
        self._melden()

    async def _lauf(self) -> None:
        pause = PAUSE_MIN_S
        try:
            while True:
                if await self._einmal():
                    pause = PAUSE_MIN_S
                if self.zustand == "einzelbild":
                    return
                try:
                    await asyncio.wait_for(self._weck.wait(), pause)
                except asyncio.TimeoutError:
                    pass
                self._weck.clear()
                pause = min(pause * 2, PAUSE_MAX_S)
        except Exception:
            log.exception("Kamera %s: Strom abgebrochen", self.host)
        finally:
            if self.zustand != "einzelbild":
                self.zustand = "ende"
            self._melden()
            self._beim_ende(self)

    def _ergebnis(self, zustand: str) -> None:
        self.zustand = zustand
        self.ergebnisse += 1
        self._melden()

    def _fehlschlag(self, text: str) -> None:
        self.fehler = text
        self._ergebnis("fehler")

    def _abgerissen(self, grund: object) -> None:
        log.info("Kamera %s getrennt (%s), verbinde neu", self.host, grund)
        self.zustand = "abgerissen"
        self._melden()

    async def _einmal(self) -> bool:
        """Ein Abruf bei der Kamera, bis sie den Strom beendet oder abbricht.
        True, wenn er mindestens ein Bild brachte. Eigene ClientSession (nicht
        icon_session): mit deren SSL-Connector liefert die Mobotix nur ein
        Einzelbild statt des Stroms."""
        vorher = self.nummer
        self.zustand = "verbinden"
        sess = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(
            total=None, sock_connect=VERBINDEN_S, sock_read=LESEN_S))
        try:
            # ValueError: unbrauchbarer Host ("cam..lan") oder Benutzer, der nicht
            # in den Basic-Auth-Kopf passt (Doppelpunkt, Zeichen ausserhalb Latin-1)
            auth = aiohttp.BasicAuth(self.user, self.passwort) if self.user else None
            async with sess.get(self.url, auth=auth) as antwort:
                if antwort.status != 200:
                    self._fehlschlag(f"camera status {antwort.status}")
                    return False
                ctype = antwort.headers.get("Content-Type", "multipart/x-mixed-replace")
                if not ctype.lower().startswith("multipart/"):
                    bild = await _ganz_lesen(antwort)
                    self.einzelbild = (ctype, bild)
                    self._beim_ende(self)    # der naechste Abruf holt ein neues Bild
                    typ = ctype.split(";")[0].strip()
                    self._neues_bild(typ if _TYP.fullmatch(typ) else "image/jpeg", bild)
                    self._ergebnis("einzelbild")
                    return True
                zerleger = MjpegZerleger(_boundary(ctype))
                self.fehler = ""
                self._ergebnis("laeuft")
                try:
                    async for daten in antwort.content.iter_any():
                        for typ, bild in zerleger.futter(daten):
                            self._neues_bild(typ, bild)
                    grund: object = "Strom zu Ende"
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError) as err:
                    grund = err
                self._abgerissen(grund)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError):
            self._fehlschlag("camera unreachable")
        finally:
            await sess.close()
        return self.nummer > vorher

    async def _warten(self, bedingung, frist: float) -> None:
        """Warten, bis bedingung() gilt oder frist um ist."""
        bis = time.monotonic() + frist
        while not bedingung() and time.monotonic() < bis:
            signal = self._signal
            try:
                await asyncio.wait_for(signal.wait(), bis - time.monotonic())
            except asyncio.TimeoutError:
                break

    async def senden(self, request: web.Request) -> web.StreamResponse:
        """Antwort an einen Zuschauer: wartet, bis die Kamera geantwortet hat
        (oder ein Bild gilt, bild_gilt), dann 502, das Einzelbild oder der
        Strom mit dem jeweils neuesten Bild, bis der Zuschauer geht oder der
        Strom endet. Steht der Strom ohne gueltiges Bild in der Pause (nach
        einem Fehlschlag oder einem abgerissenen Strom), kuerzt der Zuschauer
        sie ab und wartet auf das Ergebnis dieses neuen Versuchs."""
        stand = self.ergebnisse
        if self.zustand in ("fehler", "abgerissen") and not self.bild_gilt():
            self._weck.set()
        await self._warten(lambda: self.bild_gilt() or self.zustand in ("laeuft", "einzelbild", "ende")
                           or (self.zustand in ("fehler", "abgerissen") and self.ergebnisse > stand),
                           VERBINDEN_S + LESEN_S)
        if self.zustand == "einzelbild" and self.einzelbild is not None:
            typ, bild = self.einzelbild
            return web.Response(body=bild, headers={"Content-Type": typ, "Cache-Control": "no-cache, no-store"})
        if self.zustand not in ("laeuft", "abgerissen") and not self.bild_gilt():
            return web.Response(status=502, text=self.fehler or "camera unreachable")
        resp = web.StreamResponse(status=200, headers={
            "Content-Type": f"multipart/x-mixed-replace; boundary={GRENZE}", "Cache-Control": "no-cache, no-store"})
        await resp.prepare(request)
        gesehen = self.nummer - 1 if self.bild_gilt() else self.nummer
        try:
            while True:
                if self.nummer > gesehen:
                    gesehen = self.nummer
                    await asyncio.wait_for(resp.write(self.teil), SCHREIBEN_S)
                    continue
                if self.zustand in ("ende", "einzelbild"):
                    break
                signal = self._signal
                try:
                    await asyncio.wait_for(signal.wait(), PRUEF_S)
                except asyncio.TimeoutError:
                    if request.transport is None or request.transport.is_closing():
                        break
        except (ConnectionResetError, asyncio.TimeoutError, aiohttp.ClientError):
            pass                         # Zuschauer weg oder haengt
        return resp


class Kameraverteiler:
    """Die laufenden Kamerastroeme je Kamera (Adresse und Anmeldung). Der
    Handler meldet jeden Zuschauer an und nach seiner Antwort wieder ab."""

    def __init__(self):
        self._stroeme: dict[tuple[str, str, str], Kamerastrom] = {}

    @staticmethod
    def schluessel(cam: dict) -> tuple[str, str, str]:
        return str(cam.get("url") or ""), str(cam.get("user") or ""), str(cam.get("pass") or "")

    def anmelden(self, cam: dict) -> Kamerastrom | None:
        """Zuschauer fuer die Kamera cam ({"url", "user", "pass"}): den
        laufenden Strom oder einen neuen. None, wenn sie schon ZUSCHAUER_MAX hat."""
        strom = self._stroeme.get(self.schluessel(cam))
        if strom is None:
            strom = self._stroeme[self.schluessel(cam)] = Kamerastrom(cam, self._vergessen)
            strom.starten()
        elif strom.zuschauer >= ZUSCHAUER_MAX:
            return None
        strom.zuschauer += 1
        strom.nachlauf_abbrechen()
        return strom

    def abmelden(self, strom: Kamerastrom) -> None:
        strom.zuschauer -= 1
        if strom.zuschauer <= 0 and strom.aktiv():
            strom.nachlauf_starten()

    def _vergessen(self, strom: Kamerastrom) -> None:
        """Ein beendeter Strom (oder ein Einzelbild) wird nicht wieder vergeben."""
        if self._stroeme.get(strom.schluessel) is strom:
            del self._stroeme[strom.schluessel]

    def anzahl(self) -> int:
        return len(self._stroeme)

    async def schliessen(self) -> None:
        """Alle Stroeme trennen und ihre Zuschauer entlassen; danach endet jede
        offene /mjpeg-Antwort (Herunterfahren: aiohttp wartet sonst auf sie)."""
        for strom in list(self._stroeme.values()):
            await strom.beenden()
        self._stroeme.clear()
