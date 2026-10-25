"""LoxOS (Fork, docs/VISION.md): Datenformat der Bento-Seiten pruefen.

Eine freie Seite (pickTabs[]) kann statt Kacheln oder eines Widgets ein Raster
mit fest platzierten Zellen sein (pickTabs[].bento). Vorrang beim Anzeigen:
bento vor widget vor Kacheln; die anderen Angaben bleiben gespeichert, damit
ein Wechsel im Editor nichts verliert.

Reine Funktionen ohne Import aus konfig.py: konfig.py ruft bento_seite() mit
seinem Widget-Pruefer und seiner Bildschirmgrenze und bietet die Konstanten
weiter an (_sanitize_panels und _pick_tabs). So bleibt die Andockstelle in der
Upstream-Datei klein (Fork-Regeln in VISION.md).

Die Felder einer Zelle werden einzeln gelesen, nie als Ganzes durchlaufen:
tests/test_kachel_aufbau.py schreibt mit, welche Felder der Sanitizer liest.
"""
from __future__ import annotations

import logging
import math
from typing import Callable
from urllib.parse import urlsplit

log = logging.getLogger("loxpanel.bento")

BENTO_SPALTEN_MIN, BENTO_SPALTEN_MAX, BENTO_SPALTEN_STANDARD = 1, 12, 6
BENTO_ZEILEN_MIN, BENTO_ZEILEN_MAX, BENTO_ZEILEN_STANDARD = 1, 6, 2
# Bausteine in einer Zelle (als Liste untereinander)
BENTO_ZELLE_BAUSTEINE_MAX = 6
BENTO_URL_MAX = 2000
BENTO_NAME_MAX = 40
BENTO_UHR = "clock"
BENTO_IFRAME = "iframe"
BENTO_WETTER = "weather"
BENTO_KALENDER = "calendar"
BENTO_SPIELER = "player:"
BENTO_ENERGIE = "energy:"
# Raum-Display: eine ganze Ansicht (Kennung aus panels.json) in der Zelle
BENTO_ANSICHT = "ansicht:"
# Schnellaktionen: Knoepfe mit Symbol, je Knopf ein Baustein und eine Aktion
# (cells[].knoepfe); so viele Knoepfe hoechstens je Zelle, so lang die Aktion
# (Beschriftung eines Knopfs der Detailseite)
BENTO_SCHNELL = "schnell"
BENTO_KNOEPFE_MAX = 12
BENTO_AKTION_MAX = 60
# Ab welchem Seitenverhaeltnis (Breite/Hoehe) ein Schirm ein Streifen ist; gleich
# der Schwelle der Huelle (loxos/src/monitor.js, ein Test vergleicht beide)
STREIFEN_AB = 2.5
# Zielgeraet (VISION.md "Begriffe"), wenn ein Geraet noch keinen Schirm gemeldet hat
BENTO_FORMAT_STANDARD = {"vw": 2560, "vh": 720}
# Name der vorgeschlagenen Seite
BENTO_VORSCHLAG_NAME = "Start"
# Mass der Zellen im Vorschlag: Uhr ueber alle Zeilen, Wetter/Audio/Energie breit
BENTO_UHR_BREITE, BENTO_WIDGET_BREITE = 1, 2


def _clean_iframe_url(v) -> str:
    """Adresse einer Webseiten-Zelle: nur http und https mit Host. Verworfen
    wird alles andere, vor allem javascript:, data: und file: (liefen in der
    Visu), Adressen ohne Schema (//host), mit Zugangsdaten (user:pw@host -
    Browser laden sie im iframe nicht, und das Kennwort stuende im Klartext in
    panels.json), mit Leer- oder Steuerzeichen oder kaputtem Port. "" =
    ungueltig."""
    if not isinstance(v, str):
        return ""
    u = v.strip()
    if not u or len(u) > BENTO_URL_MAX or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in u):
        return ""
    try:
        teile = urlsplit(u)
        teile.port                          # wirft bei kaputtem Port
    except ValueError:
        return ""
    if teile.scheme.lower() not in ("http", "https") or not teile.hostname:
        return ""
    if teile.username is not None or teile.password is not None:
        return ""
    return u


def bento_ansicht_widget(v) -> str:
    """Widget einer Raum-Display-Zelle: "ansicht:<Kennung>". Die Kennung folgt
    der Regel von _sanitize_panels (nicht leer, kein "_" vorn), dazu ohne Leer-
    und Steuerzeichen - sie steht in der Adresse des iframe. Ob es die Ansicht
    gibt, entscheidet erst das Rendern (geloescht -> Zelle "nicht gefunden"),
    wie bei einem geloeschten Baustein. "" = ungueltig."""
    if not isinstance(v, str) or not v.startswith(BENTO_ANSICHT):
        return ""
    pid = v[len(BENTO_ANSICHT):]
    if not pid or pid.startswith("_") or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in pid):
        return ""
    return v


def _knoepfe(v, icon_pruefer: Callable) -> list:
    """Knoepfe einer Schnellaktionen-Zelle, je Knopf: id (Baustein), aktion
    (Beschriftung eines Knopfs seiner Detailseite; fehlt = wie ein Tipp auf
    seine Kachel), optional name (eigener Text) und icon (wie das Symbol einer
    freien Seite: die Adresse aus der Icon-Auswahl, icon_pruefer; fehlt = das
    Symbol der Kachel). Ein Eintrag ohne Baustein faellt weg; ob es den
    Baustein und die Aktion gibt, entscheidet erst das Rendern - wie bei einem
    geloeschten Baustein."""
    out = []
    for k in (v if isinstance(v, list) else [])[:BENTO_KNOEPFE_MAX]:
        if not isinstance(k, dict):
            continue
        uid = k.get("id")
        if not isinstance(uid, str) or not uid or any(c.isspace() or ord(c) < 32 for c in uid):
            continue
        e: dict = {"id": uid}
        aktion = k.get("aktion")
        if isinstance(aktion, str) and aktion.strip():
            e["aktion"] = aktion.strip()[:BENTO_AKTION_MAX]
        name = k.get("name")
        if isinstance(name, str) and name.strip():
            e["name"] = name.strip()[:BENTO_NAME_MAX]
        ic = icon_pruefer(k.get("icon"))
        if ic:
            e["icon"] = ic
        out.append(e)
    return out


def _ganzzahl(v, lo: int, hi: int):
    """Ganzzahl in [lo, hi] oder None; bool zaehlt nicht (True waere sonst 1)."""
    return v if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else None


def _klemmen(v, lo: int, hi: int, standard: int) -> int:
    """Spalten/Zeilen: Zahl auf [lo, hi] begrenzt, sonst der Standard."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return standard
    return max(lo, min(hi, int(v)))


def _zelle(z, spalten: int, zeilen: int, drin: set, widget_pruefer: Callable,
           icon_pruefer: Callable) -> dict | None:
    """Eine Zelle pruefen: Lage im Raster und Inhalt, ohne Blick auf die
    anderen Zellen (das macht bento_seite). Inhalt ist entweder ein Widget oder
    eine Liste von Bausteinen aus drin; was ueber den Rand ragt, keinen
    gueltigen Inhalt hat oder eine Webseite ohne gueltige Adresse ist, faellt
    weg -> None."""
    if not isinstance(z, dict):
        return None
    x = _ganzzahl(z.get("x"), 0, spalten - 1)
    y = _ganzzahl(z.get("y"), 0, zeilen - 1)
    if x is None or y is None:
        return None
    w = _ganzzahl(z.get("w"), 1, spalten - x)
    h = _ganzzahl(z.get("h"), 1, zeilen - y)
    if w is None or h is None:
        return None
    c = {"x": x, "y": y, "w": w, "h": h}
    wdg = widget_pruefer(z.get("widget"))
    if wdg:
        c["widget"] = wdg
        if wdg == BENTO_IFRAME:
            url = _clean_iframe_url(z.get("url"))
            if not url:
                log.warning("Bento-Zelle verworfen: Adresse %r ist keine http/https-Adresse",
                            str(z.get("url"))[:200])
                return None
            c["url"] = url
            name = str(z.get("name") or "").strip()[:BENTO_NAME_MAX]
            if name:
                c["name"] = name
        elif wdg == BENTO_SCHNELL:
            c["knoepfe"] = _knoepfe(z.get("knoepfe"), icon_pruefer)
        return c
    roh = z.get("ids")
    ids: list = []
    for u in roh if isinstance(roh, list) else []:
        if isinstance(u, str) and u in drin and u not in ids:
            ids.append(u)
    if not ids:
        return None
    c["ids"] = ids[:BENTO_ZELLE_BAUSTEINE_MAX]
    return c


def bento_seite(v, picks: list, widget_pruefer: Callable, px_max: int,
                icon_pruefer: Callable = lambda v: None) -> dict | None:
    """Bento-Raster einer freien Seite pruefen: Spalten und Zeilen begrenzt,
    Format des Vorschaugeraets (bis px_max), Zellen. Regeln (VISION.md):
    Zellen liegen im Raster und ueberlappen nicht (die spaetere faellt weg),
    Bausteine stammen aus picks und stehen je Seite einmal, ein Widget mit
    gleicher Quelle (bei Uhr, Wetter und Kalender: ueberhaupt) einmal,
    Schnellaktionen beliebig oft. Leere cells sind gueltig (spaeter
    Bento-Automatik). widget_pruefer gibt das bereinigte Widget oder ""
    zurueck, icon_pruefer das Symbol eines Knopfs oder None. None = keine
    Bento-Seite."""
    if not isinstance(v, dict):
        return None
    spalten = _klemmen(v.get("cols"), BENTO_SPALTEN_MIN, BENTO_SPALTEN_MAX, BENTO_SPALTEN_STANDARD)
    zeilen = _klemmen(v.get("rows"), BENTO_ZEILEN_MIN, BENTO_ZEILEN_MAX, BENTO_ZEILEN_STANDARD)
    out: dict = {"cols": spalten, "rows": zeilen}
    fmt = v.get("format")
    if isinstance(fmt, dict):
        vw = _ganzzahl(fmt.get("vw"), 1, px_max)
        vh = _ganzzahl(fmt.get("vh"), 1, px_max)
        if vw and vh:
            out["format"] = {"vw": vw, "vh": vh}
    drin = set(picks)
    belegt: set = set()
    widgets: set = set()
    bausteine: set = set()
    zellen = []
    roh = v.get("cells")
    # mehr Zellen als Felder kann es nicht geben
    for z in (roh if isinstance(roh, list) else [])[:spalten * zeilen]:
        c = _zelle(z, spalten, zeilen, drin - bausteine, widget_pruefer, icon_pruefer)
        if c is None:
            continue
        felder = {(c["x"] + i, c["y"] + j) for i in range(c["w"]) for j in range(c["h"])}
        if felder & belegt:
            continue
        if "widget" in c:
            quelle = (c["widget"], c.get("url", ""))
            if quelle in widgets:
                continue
            if c["widget"] != BENTO_SCHNELL:
                widgets.add(quelle)
        else:
            bausteine.update(c["ids"])
        belegt |= felder
        zellen.append(c)
    out["cells"] = zellen
    return out


def _erste_freie_stelle(belegt: set, spalten: int, zeilen: int, w: int, h: int):
    """Erste Stelle (Zeile fuer Zeile, links zuerst), an der w x h frei ist, oder None."""
    for y in range(zeilen - h + 1):
        for x in range(spalten - w + 1):
            if not any((x + i, y + j) in belegt for i in range(w) for j in range(h)):
                return x, y
    return None


def bento_vorschlag(format_: dict | None, quellen: dict, favoriten: list) -> dict:
    """Vorschlag fuer die Startseite eines Streifens (Assistent, VISION.md):
    {"bento": {cols, rows, format, cells}, "picks": [uuid, ...]}. quellen =
    {"energy": uuid|None, "player": uuid|None, "kalender": bool}; Uhr und
    Wetter gibt es immer. Reihenfolge und Platz: Uhr (ueber alle Zeilen),
    Wetter, Audio, Energie, Kalender, dann je ein Favorit in einer Zelle, so
    viele wie frei sind. Jedes Stueck nimmt die erste freie Stelle (Zeile fuer
    Zeile); was nicht mehr passt oder fehlt, laesst seinen Platz den Favoriten.
    Rein: kennt weder die Anlage noch die App, bekommt alles als einfache Daten.
    Das Ergebnis besteht bento_seite() unveraendert."""
    spalten, zeilen = BENTO_SPALTEN_STANDARD, BENTO_ZEILEN_STANDARD
    vw = _ganzzahl((format_ or {}).get("vw"), 1, 10 ** 6)
    vh = _ganzzahl((format_ or {}).get("vh"), 1, 10 ** 6)
    fmt = {"vw": vw, "vh": vh} if vw and vh else dict(BENTO_FORMAT_STANDARD)
    stuecke = [(BENTO_UHR, BENTO_UHR_BREITE, zeilen), (BENTO_WETTER, BENTO_WIDGET_BREITE, 1)]
    if quellen.get("player"):
        stuecke.append((BENTO_SPIELER + quellen["player"], BENTO_WIDGET_BREITE, 1))
    if quellen.get("energy"):
        stuecke.append((BENTO_ENERGIE + quellen["energy"], BENTO_WIDGET_BREITE, 1))
    if quellen.get("kalender"):
        stuecke.append((BENTO_KALENDER, 1, 1))
    belegt: set = set()
    zellen: list = []

    def setze(inhalt: dict, w: int, h: int) -> bool:
        stelle = _erste_freie_stelle(belegt, spalten, zeilen, w, h)
        if stelle is None:
            return False
        x, y = stelle
        belegt.update((x + i, y + j) for i in range(w) for j in range(h))
        zellen.append({"x": x, "y": y, "w": w, "h": h, **inhalt})
        return True

    for widget, w, h in stuecke:
        setze({"widget": widget}, w, h)
    # Bausteine, die schon als Widget stehen, kommen nicht noch einmal als Kachel
    schon = {quellen.get("player"), quellen.get("energy")}
    picks: list = []
    for u in favoriten:
        if not isinstance(u, str) or u in schon or u in picks:
            continue
        if not setze({"ids": [u]}, 1, 1):
            break
        picks.append(u)
    return {"bento": {"cols": spalten, "rows": zeilen, "format": fmt, "cells": zellen}, "picks": picks}


def bento_grenzen() -> dict:
    """Grenzen und Standards fuer den Seiten-Editor (/api/meta "bento"): der
    Konfigurator liest sie hier ab, statt sie ein zweites Mal zu fuehren."""
    return {"spaltenMin": BENTO_SPALTEN_MIN, "spaltenMax": BENTO_SPALTEN_MAX,
            "spaltenStandard": BENTO_SPALTEN_STANDARD,
            "zeilenMin": BENTO_ZEILEN_MIN, "zeilenMax": BENTO_ZEILEN_MAX,
            "zeilenStandard": BENTO_ZEILEN_STANDARD,
            "bausteineMax": BENTO_ZELLE_BAUSTEINE_MAX, "urlMax": BENTO_URL_MAX, "nameMax": BENTO_NAME_MAX,
            "knoepfeMax": BENTO_KNOEPFE_MAX}
