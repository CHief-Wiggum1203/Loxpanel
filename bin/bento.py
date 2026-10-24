"""LoxOS (Fork, docs/VISION.md): Bento-Seiten rendern.

Mixin der App (self ist die App). Eine Bento-Seite ist eine freie Seite mit
pickTabs[].bento (geprueft in bento_format.py). _view_bento() baut daraus die
view-Nachricht: Raster (cols/rows) und je Zelle Lage und Inhalt.

Widget-Daten stehen INLINE in der Zelle. Die Kanaele der Panes (conn_energy,
conn_camera, conn_chart, conn_player, conn_status) gibt es je Verbindung nur
einmal, eine Bento-Seite braucht mehrere zugleich. Gebaut wird mit denselben
Blockbauern wie dort (energy_blocks, intercom_blocks, chart_stack,
player_blocks, status_blocks); weil das Rendern ueber die Lesespur laeuft
(verteilung.py), aendert sich die Zelle, sobald ein gelesener State sich
aendert, und _last_sent verhindert doppeltes Senden. Uhr, Wetter und Kalender
brauchen nichts: Die Uhr tickt in der Visu, Wetter und Kalender kommen mit
{t:"front"}.

Webseiten (iframe) prueft bento_task() im Hintergrund: Erreichbarkeit und ob
die Seite Einbetten verbietet (X-Frame-Options, CSP frame-ancestors). Das kann
die Visu bei fremden Seiten nicht zuverlaessig erkennen.
"""
from __future__ import annotations

import asyncio
import logging

import aiohttp

from bento_format import BENTO_IFRAME
from konfig import _pick_tabs
from statistik import STAT_DEFAULT_RANGE

log = logging.getLogger("loxpanel.bento")

# Webseiten: so oft prueft der Server jede eingetragene Adresse neu, so lange
# wartet er hoechstens auf die Antwort, und so lange wartet die Visu auf das
# Laden des iframe, bevor sie die Zelle als Fehler zeigt.
BENTO_WEBSEITE_PRUEFEN_S = 300
BENTO_WEBSEITE_TIMEOUT_S = 8
BENTO_IFRAME_LADEN_S = 15
# Gleichzeitige Verbindungen je Host bei der Pruefung
BENTO_WEBSEITE_JE_HOST = 2

# Ergebnis einer Pruefung: "ok" (laedt, Einbetten erlaubt), "eingeschraenkt"
# (Einbetten nur fuer bestimmte Seiten oder Zertifikat fraglich - die Visu
# versucht es und nennt bei Zeitueberschreitung den Grund), "gesperrt"
# (Einbetten verboten), "fehler" (nicht erreichbar oder HTTP-Fehler), "offen"
# (noch nicht geprueft).
STAND_OK, STAND_EINGESCHRAENKT, STAND_GESPERRT, STAND_FEHLER, STAND_OFFEN = \
    "ok", "eingeschraenkt", "gesperrt", "fehler", "offen"


def einbetten_stand(xfo: str, csp: str) -> dict:
    """Darf die Seite in einem fremden iframe stehen? Aus den Kopfzeilen
    X-Frame-Options und Content-Security-Policy (mehrere Kopfzeilen mit Komma
    verbunden). Steht frame-ancestors in der CSP, gilt nur das (so halten es
    die Browser); jede CSP-Kopfzeile gilt fuer sich, die strengste
    entscheidet."""
    listen = []
    for richtlinie in (csp or "").split(","):
        for teil in richtlinie.split(";"):
            worte = teil.strip().split()
            if worte and worte[0].lower() == "frame-ancestors":
                listen.append([w.lower() for w in worte[1:]])
    if listen:
        if any(not q or q == ["'none'"] for q in listen):
            return {"stand": STAND_GESPERRT, "grund": "Seite verbietet Einbetten (frame-ancestors)"}
        if all("*" in q for q in listen):
            return {"stand": STAND_OK}
        return {"stand": STAND_EINGESCHRAENKT, "grund": "Einbetten nur für bestimmte Seiten erlaubt"}
    x = (xfo or "").strip().upper()
    if x == "DENY":
        return {"stand": STAND_GESPERRT, "grund": "Seite verbietet Einbetten (X-Frame-Options)"}
    if x:
        return {"stand": STAND_EINGESCHRAENKT, "grund": "Einbetten nur für bestimmte Seiten erlaubt"}
    return {"stand": STAND_OK}


async def webseite_pruefen(session: aiohttp.ClientSession, url: str, timeout_s: float) -> dict:
    """Eine Adresse abrufen und einordnen (einbetten_stand). Gelesen werden nur
    Status und Kopfzeilen, der Inhalt nicht."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout_s),
                               allow_redirects=True) as r:
            if r.status >= 400:
                return {"stand": STAND_FEHLER, "grund": f"Seite antwortet mit HTTP {r.status}"}
            return einbetten_stand(r.headers.get("X-Frame-Options", ""),
                                   ",".join(r.headers.getall("Content-Security-Policy", [])))
    except asyncio.TimeoutError:
        return {"stand": STAND_FEHLER, "grund": "Seite antwortet nicht (Zeitüberschreitung)"}
    except (aiohttp.ClientSSLError, aiohttp.ClientConnectorCertificateError):
        # Ein eigenes Zertifikat im Heimnetz: der Browser am Geraet kennt es
        # vielleicht, der Server nicht - die Visu versucht es trotzdem.
        return {"stand": STAND_EINGESCHRAENKT, "grund": "Zertifikat der Seite nicht vertrauenswürdig"}
    except (aiohttp.ClientError, ValueError, OSError):
        return {"stand": STAND_FEHLER, "grund": "Seite nicht erreichbar"}


class Bento:
    """Bento-Seiten der Visu; Mixin der App."""

    def _bento_web(self) -> dict:
        """Zustand der Webseiten-Pruefung, beim ersten Zugriff angelegt (die App
        kennt LoxOS nicht): stand je Adresse, angefragt = Adressen, die seit der
        letzten Runde gerendert wurden (auch aus Entwuerfen des Editors),
        wecken = Event fuer die Pruefschleife."""
        z = self.__dict__.get("_bento_web_zustand")
        if z is None:
            z = self.__dict__["_bento_web_zustand"] = {"stand": {}, "angefragt": set(),
                                                       "wecken": asyncio.Event()}
        return z

    def _view_bento(self, tab: str, entry: dict, prof: dict | None) -> dict:
        """view-Nachricht einer Bento-Seite. Bausteine wie im Fliessraster nur,
        wenn es sie gibt und sie nicht ausgeblendet sind (_shown); eine Zelle,
        der so alle Bausteine fehlen, faellt weg (ihr Platz bleibt frei)."""
        b = entry["bento"]
        alle = [u for c in b["cells"] for u in c.get("ids", ())
                if u in self.controls and self._shown(u, prof)]
        sr = self._spans_rooms(alle)
        zellen = []
        for c in b["cells"]:
            z = {k: c[k] for k in ("x", "y", "w", "h")}
            if "ids" in c:
                items = [self._control_item(u, prof, show_room=sr) for u in c["ids"]
                         if u in self.controls and self._shown(u, prof)]
                if not items:
                    continue
                z["items"] = items
            else:
                z.update(self._bento_widget_daten(c))
            zellen.append(z)
        return {"t": "view", "title": entry.get("name") or "", "tab": tab,
                "route": {"view": "tab", "tab": tab}, "items": [],
                "bento": {"cols": b["cols"], "rows": b["rows"]}, "cells": zellen}

    def _bento_widget_daten(self, c: dict) -> dict:
        """Inhalt einer Widget-Zelle. Fehlt die Quelle (Baustein geloescht,
        Zone unbekannt), bleibt nur der Widget-Name stehen und die Visu zeigt
        die Zelle als nicht verfuegbar; scheitert ein Blockbauer, steht
        fehler=True - eine kaputte Zelle darf die Seite nicht mitreissen."""
        w = c["widget"]
        d: dict = {"widget": w}
        art, _, arg = w.partition(":")
        try:
            if art == "player":
                pb = self.player_blocks(arg)
                if pb is not None:
                    d["player"] = self._bento_pane("player", arg, pb)
            elif art == "energy":
                eb = self.energy_blocks(arg)
                if eb is not None:
                    d["energy"] = eb
            elif art == "camera":
                cam, _, werte = arg.partition("|")
                ib = self.intercom_blocks(cam)
                if ib is not None:
                    d["camera"] = self._bento_pane("camera", cam, ib)
                if werte:
                    d["status"] = self.status_blocks(tuple(werte.split(",")))
            elif art == "chart":
                d["chart"] = self.chart_stack(tuple(arg.split(",")), STAT_DEFAULT_RANGE)
            elif art == "status":
                d["status"] = self.status_blocks(tuple(arg.split(",")))
            elif w == BENTO_IFRAME:
                d.update(self._bento_webseite(c))
        except Exception:
            log.exception("Bento-Zelle %s fehlgeschlagen", w)
            d["fehler"] = True
        return d

    def _bento_pane(self, art: str, uuid: str, blocks: list) -> dict:
        """Wie _pane_msg (inkl. secured fuer PIN-geschuetzte Zonen und
        Intercoms), ohne den Nachrichtentyp - die Zelle ist keine Nachricht."""
        m = self._pane_msg(art, uuid, blocks)
        m.pop("t", None)
        return m

    def _bento_webseite(self, c: dict) -> dict:
        """Adresse, Name und Pruefergebnis einer Webseiten-Zelle. Eine noch nie
        gepruefte Adresse weckt die Pruefschleife."""
        z = self._bento_web()
        url = c["url"]
        z["angefragt"].add(url)
        pruefung = z["stand"].get(url)
        if pruefung is None:
            z["wecken"].set()
            pruefung = {"stand": STAND_OFFEN}
        d = {"url": url, "pruefung": dict(pruefung), "ladenS": BENTO_IFRAME_LADEN_S}
        if c.get("name"):
            d["name"] = c["name"]
        return d

    def _bento_adressen(self) -> set:
        """Alle Webseiten-Adressen der gespeicherten Ansichten."""
        raus = set()
        for prof in (self.panels or {}).values():
            if not isinstance(prof, dict):
                continue
            for seite in _pick_tabs(prof):
                for c in (seite.get("bento") or {}).get("cells", ()):
                    if c.get("widget") == BENTO_IFRAME:
                        raus.add(c["url"])
        return raus

    async def _bento_runde(self, session: aiohttp.ClientSession) -> bool:
        """Eine Pruefrunde ueber alle gespeicherten und zuletzt gerenderten
        Adressen. Ergebnisse von Adressen, die nirgends mehr stehen, fallen
        weg. -> True, wenn sich ein Ergebnis geaendert hat (dann rendern die
        Panels neu)."""
        z = self._bento_web()
        urls = self._bento_adressen() | z["angefragt"]
        z["angefragt"] = set()
        urls = sorted(urls)
        ergebnisse = await asyncio.gather(
            *(webseite_pruefen(session, u, BENTO_WEBSEITE_TIMEOUT_S) for u in urls))
        neu = dict(zip(urls, ergebnisse))
        geaendert = neu != z["stand"]
        z["stand"] = neu
        return geaendert

    async def bento_task(self) -> None:
        """Webseiten der Bento-Seiten periodisch pruefen (BENTO_WEBSEITE_PRUEFEN_S),
        vorzeitig, sobald eine ungepruefte Adresse gerendert wird. Endet nie
        planmaessig (/api/health)."""
        z = self._bento_web()
        async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit_per_host=BENTO_WEBSEITE_JE_HOST)) as s:
            while True:
                z["wecken"].clear()
                try:
                    if await self._bento_runde(s):
                        self._mark_dirty()
                except Exception:
                    log.exception("Pruefung der Bento-Webseiten fehlgeschlagen")
                try:
                    await asyncio.wait_for(z["wecken"].wait(), BENTO_WEBSEITE_PRUEFEN_S)
                except asyncio.TimeoutError:
                    pass
