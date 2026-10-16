"""Bausteine der Visu, Familie Sicherheit und Melder: Alarmanlage, Rauchmelder, Praesenzmelder, Fensterueberwachung, Postkasten.

Kachel (@kachel) und Detailseite (@detail) je Typ, siehe bausteine/__init__.py.
Die Helfer (app._state, app._fmt_num ...) sind Mixins in helfer.py und den Familien, App erbt sie ueber bausteine.BausteinHelfer."""
from __future__ import annotations

import time
from datetime import datetime

from bausteine import detail, kachel
from bausteine.gemeinsam import _clean, _dauer_text

# Briefkasten (MailBox, Strukturdoku): so lange setzen die Tasten die
# Benachrichtigungen aus (disableNotifications/{Sekunden}); 0 hebt die Pause auf.
BRIEFKASTEN_PAUSEN = (3600, 4 * 3600, 24 * 3600)
# disableEndTime zaehlt laut Strukturdoku Sekunden seit 1.1.2009 in UTC
LOX_EPOCH_UTC = 1230768000


@kachel("SmokeAlarm")
def kachel_rauchmelder(app, uuid, c, it):
    ok = (app._state(c, "level") or 0) == 0
    it.update(icon="alarm", sublabel=("Alles ok" if ok else "Alarm!"),
              tone=("good" if ok else "crit"))


@kachel("PresenceDetector")
def kachel_praesenzmelder(app, uuid, c, it):
    on = bool(app._state(c, "active"))
    itxt = app._text(c, "infoText")
    it.update(icon="info", on=on,
              sublabel=(itxt if itxt and itxt.lower() not in ("on", "off")
                        else ("Anwesend" if on else "Abwesend")))


@kachel("WindowMonitor")
def kachel_fensterueberwachung(app, uuid, c, it):
    op = int(app._state(c, "numOpen") or 0) + int(app._state(c, "numTilted") or 0)
    it.update(icon="blind", on=op > 0, nav={"view": "control", "id": uuid},
              sublabel=(f"{op} offen" if op else "Alle geschlossen"))


@kachel("Alarm")
def kachel_alarmanlage(app, uuid, c, it):
    armed = bool(app._state(c, "armed"))
    lvl = app._state(c, "level") or 0
    it.update(icon="alarm", on=armed, tone=("crit" if lvl else None),
              nav={"view": "control", "id": uuid},
              sublabel=("Alarm!" if lvl else ("Scharf" if armed else "Unscharf")))


@kachel("MailBox")
def kachel_postkasten(app, uuid, c, it):
    mail = bool(app._state(c, "mailReceived"))
    pk = bool(app._state(c, "packetReceived"))
    sub = " · ".join(x for x, f in (("Post da", mail), ("Paket da", pk)) if f) or "Leer"
    it.update(icon="mail", on=(mail or pk), nav={"view": "control", "id": uuid}, sublabel=sub)
    if mail or pk:
        it["hinweis"] = {"stufe": "an", "symbol": "mail"}


@detail("WindowMonitor")
def detail_fensterueberwachung(app, uuid, c, route):
    windows = (c.get("details") or {}).get("windows") or []
    codes = [x for x in str(app._state(c, "windowStates") or "").split(",") if x != ""]

    def wtext(b):
        parts = []
        if b & 1:
            parts.append("geschlossen")
        if b & 2:
            parts.append("gekippt")
        if b & 4:
            parts.append("offen")
        if b & 8:
            parts.append("verriegelt")
        if b & 32:
            parts.append("offline")
        return ", ".join(parts) or "–"

    items = []
    for i, w in enumerate(windows):
        try:
            b = int(float(codes[i])) if i < len(codes) else 0
        except (ValueError, TypeError):
            b = 0
        items.append({"id": f"{uuid}:{i}", "icon": "blind", "on": bool(b & 6),
                      "label": _clean(w.get("name") or f"Fenster {i + 1}"),
                      "sublabel": wtext(b)})
    return {"t": "view", "title": _clean(c.get("name")), "route": route,
            "layout": "list", "items": items}


@detail("SmokeAlarm")
def detail_rauchmelder(app, uuid, c, route):
    ok = (app._state(c, "level") or 0) == 0
    return app._big_view(uuid, "alarm", "Alles ok" if ok else "Alarm!",
                          tone=("good" if ok else "crit"))


@detail("PresenceDetector")
def detail_praesenzmelder(app, uuid, c, route):
    on = bool(app._state(c, "active"))
    itxt = app._text(c, "infoText")
    big = itxt if (itxt and itxt.lower() not in ("on", "off")) else ("Anwesend" if on else "Abwesend")
    return app._big_view(uuid, "info", big)


@detail("Alarm")
def detail_alarmanlage(app, uuid, c, route):
    ua = c.get("uuidAction")
    armed = bool(app._state(c, "armed"))
    lvl = app._state(c, "level") or 0
    big = {"k": "big", "text": ("Alarm!" if lvl else ("Scharf" if armed else "Unscharf"))}
    if lvl:
        big["tone"] = "crit"
    elif not armed:
        big["tone"] = "good"
    if lvl:                                   # Alarm ausgeloest
        sub = "Alarm ausgelöst"
        cells = [{"label": "Quittieren", "cmd": {"uuid": ua, "cmd": "quit"}},
                 {"label": "Unscharf", "cmd": {"uuid": ua, "cmd": "off"}}]
    elif armed:                               # scharf -> nur entschaerfen
        sub = "Anlage ist scharf"
        cells = [{"label": "Unscharf", "cmd": {"uuid": ua, "cmd": "off"}}]
    else:                                     # unscharf -> scharfschalten
        sub = "Bereit zum Scharfschalten"
        cells = [{"label": "Scharf", "cmd": {"uuid": ua, "cmd": "on"}},
                 {"label": "Verzögert", "cmd": {"uuid": ua, "cmd": "delayedon"}}]
    return {"t": "view", "title": _clean(c.get("name")), "route": route,
            "anchor": "bottom", "blocks": [
        {"k": "hero", "icon": "alarm"},
        big,
        {"k": "status", "text": sub},
        {"k": "row", "cells": cells},
    ]}


def _pause_bis(app, c: dict) -> datetime | None:
    """Bis wann die Benachrichtigungen des Briefkastens pausiert sind (State
    disableEndTime, Ortszeit), None ohne laufende Pause."""
    try:
        ts = float(app._state(c, "disableEndTime") or 0)
    except (TypeError, ValueError):
        return None
    ende = LOX_EPOCH_UTC + ts
    return datetime.fromtimestamp(ende) if ts > 0 and ende > time.time() else None


def _uhrzeit_text(dt: datetime) -> str:
    """Zeitpunkt kurz: heute nur die Uhrzeit, morgen mit "morgen", sonst mit Datum."""
    tage = (dt.date() - datetime.now().date()).days
    if tage == 0:
        return dt.strftime("%H:%M")
    if tage == 1:
        return "morgen " + dt.strftime("%H:%M")
    return dt.strftime("%d.%m. %H:%M")


@detail("MailBox")
def detail_postkasten(app, uuid, c, route):
    """Briefkasten (Strukturdoku MailBox): was drin ist, Post bzw. Paket als
    entnommen bestaetigen (confirmMail, confirmPacket), die Benachrichtigungen
    pausieren (disableNotifications) und der Verlauf aus dem Unterbaustein
    Tracker."""
    ua = c.get("uuidAction")
    mail = bool(app._state(c, "mailReceived"))
    pk = bool(app._state(c, "packetReceived"))
    big = {"k": "big", "text": "Post und Paket" if (mail and pk) else
           ("Post da" if mail else ("Paket da" if pk else "Leer"))}
    if mail or pk:
        big["tone"] = "good"
    blocks = [{"k": "hero", "icon": "mail"}, big]
    bis = _pause_bis(app, c)
    if app._state(c, "notificationsDisabledInput"):
        blocks.append({"k": "status", "text": "Benachrichtigungen über die Logik ausgesetzt"})
    elif bis:
        blocks.append({"k": "status", "text": f"Benachrichtigungen pausiert bis {_uhrzeit_text(bis)}"})
    su, tracker = app._verlauf_sub(c)
    zeilen = app._tracker_lines(tracker) if tracker is not None else []
    if zeilen:
        ts, txt = app._split_ts(zeilen[0])
        blocks.append({"k": "status", "text": f"Zuletzt: {txt}" + (f" ({ts})" if ts else "")})
    entnommen = [{"label": text, "cmd": {"uuid": ua, "cmd": cmd}}
                 for da, text, cmd in ((mail, "Post entnommen", "confirmMail"),
                                       (pk, "Paket entnommen", "confirmPacket")) if da]
    if entnommen:
        blocks.append({"k": "row", "cells": entnommen})
    if bis:
        blocks += [{"k": "head", "text": "Benachrichtigungen"},
                   {"k": "row", "cells": [{"label": "Wieder an",
                                           "cmd": {"uuid": ua, "cmd": "disableNotifications/0"}}]}]
    else:
        blocks += [{"k": "head", "text": "Benachrichtigungen pausieren"},
                   {"k": "row", "cells": [{"label": _dauer_text(s),
                                           "cmd": {"uuid": ua, "cmd": f"disableNotifications/{s}"}}
                                          for s in BRIEFKASTEN_PAUSEN]}]
    if tracker is not None:
        blocks.append({"k": "row", "cells": [{"label": "Verlauf", "nav": {"view": "verlauf", "id": uuid}}]})
    return {"t": "view", "title": _clean(c.get("name")), "route": route,
            "anchor": "bottom", "blocks": blocks}
