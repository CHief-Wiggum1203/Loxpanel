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


def _ganzzahl(v, lo: int, hi: int):
    """Ganzzahl in [lo, hi] oder None; bool zaehlt nicht (True waere sonst 1)."""
    return v if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else None


def _klemmen(v, lo: int, hi: int, standard: int) -> int:
    """Spalten/Zeilen: Zahl auf [lo, hi] begrenzt, sonst der Standard."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return standard
    return max(lo, min(hi, int(v)))


def _zelle(z, spalten: int, zeilen: int, drin: set, widget_pruefer: Callable) -> dict | None:
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


def bento_seite(v, picks: list, widget_pruefer: Callable, px_max: int) -> dict | None:
    """Bento-Raster einer freien Seite pruefen: Spalten und Zeilen begrenzt,
    Format des Vorschaugeraets (bis px_max), Zellen. Regeln (VISION.md):
    Zellen liegen im Raster und ueberlappen nicht (die spaetere faellt weg),
    Bausteine stammen aus picks und stehen je Seite einmal, ein Widget mit
    gleicher Quelle (bei Uhr, Wetter und Kalender: ueberhaupt) einmal. Leere
    cells sind gueltig (spaeter Bento-Automatik). widget_pruefer gibt das
    bereinigte Widget oder "" zurueck. None = keine Bento-Seite."""
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
        c = _zelle(z, spalten, zeilen, drin - bausteine, widget_pruefer)
        if c is None:
            continue
        felder = {(c["x"] + i, c["y"] + j) for i in range(c["w"]) for j in range(c["h"])}
        if felder & belegt:
            continue
        if "widget" in c:
            quelle = (c["widget"], c.get("url", ""))
            if quelle in widgets:
                continue
            widgets.add(quelle)
        else:
            bausteine.update(c["ids"])
        belegt |= felder
        zellen.append(c)
    out["cells"] = zellen
    return out

