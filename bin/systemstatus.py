"""LoxOS (Fork, docs/VISION.md): Widget "Systemstatus" einer Bento-Seite.

Mixin der App (self ist die App). Die Zelle zeigt, was der Miniserver ueber
sich selbst hergibt, und wie es um LoxPanel steht. Nur dokumentierte Quellen:

- Struktur (Strukturdoku, msInfo): Name, Typ (miniserverType), Projekt
  (projectName) und der Stand der Programmierung (lastModified)
- Webservices (Loxone-Doku "Web Services"): Firmware ueber dev/cfg/version,
  Auslastung ueber dev/sys/cpu, dev/sys/heap und dev/sys/numtasks (System
  Monitoring). Wie die Antworten aussehen, beschreibt die Doku nicht: Die
  Zelle zeigt sie so, wie der Miniserver sie schickt. Antwortet er mit einem
  anderen Code (fehlende Rechte), steht der Code da.
- globale States (Strukturdoku, globalStates): die letzte Mitteilung
  (notifications) mit ihrer Stufe data.lvl
- messageCenter (Strukturdoku): states.changed, wann sich der Systemstatus
  zuletzt geaendert hat
- LoxPanel: Verbindung zum Miniserver (seit wann verbunden oder getrennt),
  verbundene Displays, Version

Die States liest das Rendern ueber self.states (Lesespur, verteilung.py); die
Webservices fragt system_task() im Hintergrund ab, nur solange eine Ansicht
eine Systemstatus-Zelle hat oder eine gerendert wurde (auch im Entwurf des
Editors), und setzt _dirty, wenn sich eine Antwort aendert.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

import aiohttp

from bento_format import BENTO_SYSTEM
from diagnosedaten import VERSION
from konfig import _pick_tabs

log = logging.getLogger("loxpanel.bento")

# So oft fragt der Server die Auslastung neu ab, so lange wartet er hoechstens
# auf eine Antwort
SYSTEM_ABFRAGE_S = 30
SYSTEM_TIMEOUT_S = 5
# So viele Zeichen einer Antwort oder Mitteilung stehen hoechstens in der Zelle
SYSTEM_WERT_MAX = 60
SYSTEM_TEXT_MAX = 240
# Webservices (Loxone-Doku "Web Services") und ihre Zeile in der Zelle
SYSTEM_FIRMWARE = ("cfg/version", "Firmware")
SYSTEM_AUSLASTUNG = (("sys/cpu", "CPU-Last"), ("sys/heap", "Speicher (Heap)"), ("sys/numtasks", "Tasks"))
# notifications.data.lvl laut Strukturdoku (globalStates)
SYSTEM_STUFEN = {1: "Info", 2: "Fehler", 3: "Systemfehler"}
# Zeile statt der Auslastung, wenn der Miniserver keinen der Werte herausgibt
SYSTEM_AUSLASTUNG_ZEILE = "Auslastung"

_STEUERZEICHEN = re.compile(r"[\x00-\x1f\x7f]")


def _anzeige(v, laenge: int) -> str:
    """Wert als eine Zeile Text: Steuerzeichen und Zeilenumbrueche zu Leerzeichen,
    hoechstens laenge Zeichen."""
    if v is None:
        return ""
    return " ".join(_STEUERZEICHEN.sub(" ", str(v)).split())[:laenge]


class Systemstatus:
    """Widget Systemstatus der Bento-Seiten; Mixin der App."""

    def _system(self) -> dict:
        """Zustand der Abfrage, beim ersten Zugriff angelegt (die App kennt
        LoxOS nicht): antworten = Webservice -> (Code, Text), firmware_fuer =
        Verbindung (_ms_verbunden_seit), fuer die die Firmware gilt,
        angefragt = seit der letzten Runde gerendert, wecken = Event fuer die
        Schleife."""
        z = self.__dict__.get("_system_zustand")
        if z is None:
            z = self.__dict__["_system_zustand"] = {"antworten": {}, "firmware_fuer": None,
                                                    "angefragt": False, "wecken": asyncio.Event()}
        return z

    def _zeitpunkt(self, ts) -> str:
        """Unix-Sekunden (oder datetime) als Text wie in der Klingelliste
        ('Heute 07:49', 'Gestern 07:49', Wochentag, sonst Datum); leer ohne Zeit."""
        try:
            dt = ts if isinstance(ts, datetime) else datetime.fromtimestamp(float(ts))
        except (TypeError, ValueError, OverflowError, OSError):
            return ""
        return self._bell_text(dt.strftime("%Y%m%d%H%M%S"))

    def _bento_system(self) -> dict:
        """Inhalt einer Systemstatus-Zelle: kopf (Miniserver, Verbindung), die
        letzte Mitteilung, falls es eine gibt, und gruppen mit Name und Wert."""
        z = self._system()
        z["angefragt"] = True
        verbunden = self._ms_verbunden_seit is not None
        if verbunden and SYSTEM_FIRMWARE[0] not in z["antworten"]:
            z["wecken"].set()
        info = self.ms_struktur or {}
        if verbunden:
            text = "Verbunden seit " + self._zeitpunkt(self._ms_verbunden_seit)
        elif self._ms_weg_seit is not None:
            text = "Getrennt seit " + self._zeitpunkt(self._ms_weg_seit)
        else:
            text = "Nicht verbunden"
        kopf = {"name": _anzeige(info.get("name"), SYSTEM_WERT_MAX) or "Miniserver",
                "typ": _anzeige(info.get("typ"), SYSTEM_WERT_MAX), "ok": verbunden, "text": text}
        ms = []
        if verbunden:
            ms += self._system_zeilen(z["antworten"])
        if info.get("projekt"):
            ms.append({"k": "Projekt", "v": _anzeige(info["projekt"], SYSTEM_WERT_MAX)})
        if info.get("stand"):
            try:
                stand = self._zeitpunkt(datetime.strptime(str(info["stand"]), "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                stand = _anzeige(info["stand"], SYSTEM_WERT_MAX)
            ms.append({"k": "Programmiert", "v": stand})
        su = (self.meldezentrale or {}).get("changed")
        geaendert = self.states.get(su) if isinstance(su, str) else None
        zeit = self._zeitpunkt(geaendert) if isinstance(geaendert, (int, float)) and geaendert > 0 else ""
        if zeit:
            ms.append({"k": "Systemstatus geändert", "v": zeit})
        d = {"kopf": kopf, "gruppen": [g for g in ({"titel": "Miniserver", "zeilen": ms},
                                                   {"titel": "LoxPanel", "zeilen": self._system_loxpanel()})
                                       if g["zeilen"]]}
        meldung = self._system_meldung()
        if meldung:
            d["meldung"] = meldung
        return d

    @staticmethod
    def _system_zeilen(antworten: dict) -> list:
        """Firmware und Auslastung aus den Antworten der Webservices. Gibt der
        Miniserver keinen Auslastungswert heraus, steht statt der drei Zeilen
        eine mit dem Code seiner Antwort."""
        zeilen = []
        code, text = antworten.get(SYSTEM_FIRMWARE[0], ("", ""))
        if code == "200" and text:
            zeilen.append({"k": SYSTEM_FIRMWARE[1], "v": text})
        last = [(name, antworten[p]) for p, name in SYSTEM_AUSLASTUNG if p in antworten]
        werte = [{"k": name, "v": text} for name, (code, text) in last if code == "200" and text]
        if werte:
            zeilen += werte
        elif last:
            code = last[0][1][0]
            zeilen.append({"k": SYSTEM_AUSLASTUNG_ZEILE,
                           "v": f"nicht abrufbar (Antwort {code})" if code else "keine Antwort"})
        return zeilen

    def _system_loxpanel(self) -> list:
        """Verbundene Displays (Geraete mit Namen einmal, Browser ohne Namen je
        Verbindung; ohne Raum-Display-Zellen) und Version. Ein Vorschaufenster
        des Konfigurators erbt den Geraetenamen aus dem localStorage
        (routen/visu.py): es zaehlt nur, wenn sein Geraet gerade selbst einen
        Entwurf zeigt (vorschau_geraet), sonst ist es kein Display."""
        namen, ohne = set(), 0
        for info in self.conn_info.values():
            dev = info.get("dev")
            if info.get("eingebettet"):
                continue
            if info.get("vorschau"):
                if dev and dev in self.vorschau_geraet:
                    namen.add(dev)
            elif dev:
                namen.add(dev)
            else:
                ohne += 1
        zeilen = [{"k": "Displays verbunden", "v": str(len(namen) + ohne)}]
        version = VERSION.get("version") or ""
        if version:
            commit = VERSION.get("commit") or ""
            zeilen.append({"k": "Version", "v": version + (f" ({commit[:7]})" if commit else "")})
        return zeilen

    def _system_meldung(self) -> dict | None:
        """Letzte Mitteilung des Miniservers (globaler State notifications,
        JSON laut Strukturdoku: title, message, ts, data.lvl). None, wenn es
        keine gibt."""
        n = self._json_state({"type": "globalStates", "states": self.global_states or {}}, "notifications")
        if not isinstance(n, dict):
            return None
        titel = _anzeige(n.get("title"), SYSTEM_WERT_MAX)
        text = _anzeige(n.get("message"), SYSTEM_TEXT_MAX)
        if not (titel or text):
            return None
        m = {"titel": titel, "text": text}
        daten = n.get("data")
        lvl = daten.get("lvl") if isinstance(daten, dict) else None
        if isinstance(lvl, (int, float)) and lvl in SYSTEM_STUFEN:
            m["stufe"], m["stufeText"] = int(lvl), SYSTEM_STUFEN[lvl]
        zeit = self._zeitpunkt(n.get("ts")) if n.get("ts") else ""
        if zeit:
            m["zeit"] = zeit
        return m

    def _system_gebraucht(self) -> bool:
        """Hat eine gespeicherte Ansicht eine Systemstatus-Zelle, oder wurde seit
        der letzten Runde eine gerendert (Entwurf im Editor)?"""
        if self._system()["angefragt"]:
            return True
        for prof in (self.panels or {}).values():
            if not isinstance(prof, dict):
                continue
            for seite in _pick_tabs(prof):
                if any(c.get("widget") == BENTO_SYSTEM for c in (seite.get("bento") or {}).get("cells", ())):
                    return True
        return False

    async def _system_fragen(self, pfad: str) -> tuple[str, str]:
        """Einen Webservice fragen -> (Code, Text). Ohne Antwort ("", "").
        Ohne neue Anmeldung bei 401: das erneuert der Datenstrom, und 401 kann
        auch fehlende Rechte heissen."""
        try:
            code, wert = await self._ms_jdev(pfad, SYSTEM_TIMEOUT_S, renew=False)
        except (ConnectionError, aiohttp.ClientError, asyncio.TimeoutError, OSError):
            return "", ""
        return code, _anzeige(wert, SYSTEM_WERT_MAX)

    async def _system_runde(self) -> bool:
        """Eine Abfrage: die Firmware einmal je Verbindung, die Auslastung jedes
        Mal. Ohne Verbindung gilt keine Antwort mehr. -> True, wenn sich eine
        Antwort geaendert hat (dann rendern die Panels neu)."""
        z = self._system()
        z["angefragt"] = False
        verbindung = self._ms_verbunden_seit
        if verbindung is None or self.icon_session is None:
            geaendert = bool(z["antworten"])
            z["antworten"], z["firmware_fuer"] = {}, None
            return geaendert
        neu = dict(z["antworten"]) if z["firmware_fuer"] == verbindung else {}
        pfade = [p for p, _ in SYSTEM_AUSLASTUNG]
        if SYSTEM_FIRMWARE[0] not in neu or neu[SYSTEM_FIRMWARE[0]][0] != "200":
            pfade.insert(0, SYSTEM_FIRMWARE[0])
        for p in pfade:
            neu[p] = await self._system_fragen(p)
        geaendert = neu != z["antworten"]
        z["antworten"], z["firmware_fuer"] = neu, verbindung
        return geaendert

    async def system_task(self) -> None:
        """Webservices des Systemstatus periodisch abfragen (SYSTEM_ABFRAGE_S),
        vorzeitig, sobald eine Zelle ohne Firmware gerendert wird. Ohne Zelle
        gelten die alten Antworten nicht mehr (eine neue Zelle fragt frisch).
        Endet nie planmaessig (/api/health)."""
        z = self._system()
        while True:
            z["wecken"].clear()
            try:
                if not self._system_gebraucht():
                    z["antworten"], z["firmware_fuer"] = {}, None
                elif await self._system_runde():
                    self._mark_dirty()
            except Exception:
                log.exception("Abfrage des Systemstatus fehlgeschlagen")
            try:
                await asyncio.wait_for(z["wecken"].wait(), SYSTEM_ABFRAGE_S)
            except asyncio.TimeoutError:
                pass
