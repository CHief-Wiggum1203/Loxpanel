"""Bausteine der Visu, Familie Wecker (AlarmClock).

Kachel (@kachel) und Detailseite (@detail) je Typ, siehe bausteine/__init__.py.
Die Helfer (app._state, app._fmt_num ...) sind Methoden von App in webvisu.py."""
from __future__ import annotations

from bausteine import detail, kachel
from bausteine.gemeinsam import _clean


@kachel("AlarmClock")
def kachel_wecker(app, uuid, c, it):
    ringing = bool(app._state(c, "isAlarmActive"))
    nxt = app._alarm_next_text(c)
    has = bool(app._alarm_entries(uuid))
    rn = _clean((app.rooms.get(c.get("room")) or {}).get("name"))
    if rn:
        it["room"] = rn   # Raum auf der Kachel zeigen (mehrere Wecker unterscheidbar)
    it.update(icon="alarm", on=ringing, tone=("crit" if ringing else None),
              nav={"view": "control", "id": uuid},
              sublabel=("Weckt!" if ringing else
                        "Ausgeschaltet" if app._alarm_aus(c) else
                        (nxt or ("Keine Weckzeit aktiv" if has else "Kein Wecker"))))


@detail("AlarmClock")
def detail_wecker(app, uuid, c, route):
    ua = c.get("uuidAction")
    ringing = bool(app._state(c, "isAlarmActive"))
    nxt = app._alarm_next_text(c)
    entries = app._alarm_entries(uuid)
    room = _clean((app.rooms.get(c.get("room")) or {}).get("name"))
    # Layout wie IRR/Klima (anchor:bottom): Statuszeile mittig oben (Raum
    # als Unterzeile), die Weckzeit-Eintraege unten angedockt. Je Eintrag
    # ein Schalter (ein/aus), Antippen oeffnet ihn zum Bearbeiten. Klingelt
    # der Wecker, gibt es Schlummer (Loxone 'snooze') und Wecker aus
    # ('dismiss' -> isAlarmActive 0 -> Weckton stoppt).
    stat = {"k": "astat", "text": ("Weckt jetzt" if ringing else
                                   "Ausgeschaltet" if app._alarm_aus(c) else
                                   (nxt or "Keine Weckzeit aktiv"))}
    if ringing:
        stat["tone"] = "crit"
    if room:
        stat["sub"] = room
    blocks = [{"k": "hero", "icon": "alarm"}, stat, {"k": "alarmlist", "entries": entries}]
    if ringing:
        blocks.append({"k": "row", "cells": [
            {"label": "Schlummer", "cmd": {"uuid": ua, "cmd": "snooze"}},
            {"label": "Wecker aus", "cmd": {"uuid": ua, "cmd": "dismiss"}}]})
    if (app._alarm_raw(c) or ({}, False))[1]:
        blocks.append({"k": "row", "cells": [
            {"label": "Neue Weckzeit", "nav": {"view": "alarmentry", "id": uuid, "entry": ""}},
            {"label": "Einstellungen", "nav": {"view": "alarmsettings", "id": uuid}}]})
    return {"t": "view", "title": _clean(c.get("name")), "route": route,
            "anchor": "bottom", "blocks": blocks}
