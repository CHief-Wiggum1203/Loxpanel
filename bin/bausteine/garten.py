"""Bausteine der Visu, Familie Garten: Bewaesserung.

Kachel (@kachel) und Detailseite (@detail) je Typ, siehe bausteine/__init__.py.
Die Helfer (app._state, app._fmt_num ...) sind Methoden von App in webvisu.py."""
from __future__ import annotations

from bausteine import detail, kachel
from bausteine.gemeinsam import IRR_ALLE_AKTIV, IRR_SELECT_ALLE, IRR_SELECT_AUS, _clean, _dauer_text


@kachel("Irrigation")
def kachel_bewaesserung(app, uuid, c, it):
    act = app._irr_running(c)
    rain = bool(app._state(c, "rainActive"))
    sub = "Bewässert" if act else ("Regenpause" if rain else "Bereit")
    zone = app._irrigation_zone_name(c)
    if act and zone:
        sub += " · " + zone
    it.update(icon="info", on=act, nav={"view": "control", "id": uuid}, sublabel=sub)


@detail("Irrigation")
def detail_bewaesserung(app, uuid, c, route):
    ua = c.get("uuidAction")
    act = app._irr_running(c)
    cur = app._irr_current(c)
    rain = bool(app._state(c, "rainActive"))
    big = "Bewässert" if act else ("Regenpause" if rain else "Bereit")
    rows = []
    zone = app._irrigation_zone_name(c)
    if zone:
        rows.append({"k": "status", "text": "Aktive Zone: " + zone})
    ep = app._state(c, "expectedPrecipitation")
    if ep is not None:
        txt = f"Erwarteter Niederschlag {app._fmt_num(ep, '%.1f mm')}"
        grenze = app._state(c, "maxExpectedPrecipitation")
        if grenze is not None:
            txt += f" · Grenze {app._fmt_num(grenze, '%.1f mm')}"
        rows.append({"k": "status", "text": txt})
    regen = app._state(c, "rainTime")
    if isinstance(regen, (int, float)) and regen > 0:
        rows.append({"k": "status", "text": "Regen in den letzten 24 h: " + _dauer_text(regen)})
    # Zonen: Antippen oeffnet die Zone (starten/stoppen, Laufzeit).
    zones = app._irr_zones(c)
    if zones:
        rows.append({"k": "head", "text": "Zonen"})
        rows.append({"k": "row", "wrap": True, "cells": [
            {"label": z["name"] + (" · " + _dauer_text(z["duration"]) if z["duration"] is not None else ""),
             "on": cur in (z["id"], IRR_ALLE_AKTIV),
             "nav": {"view": "irrzone", "id": uuid, "zone": z["id"]}} for z in zones]})
    # Steuerung laut Loxone-Strukturdoku: start = nur wenn noetig,
    # startForce = erwarteten/vergangenen Regen ignorieren, stop, dazu
    # select fuer alle Zonen an/aus (Zahlen siehe IRR_SELECT_*).
    rows.append({"k": "row", "cells": [
        {"label": "Start", "on": act, "cmd": {"uuid": ua, "cmd": "start"}},
        {"label": "Erzwingen", "cmd": {"uuid": ua, "cmd": "startForce"}},
        {"label": "Stopp", "on": not act, "cmd": {"uuid": ua, "cmd": "stop"}},
    ]})
    rows.append({"k": "row", "cells": [
        {"label": "Alle Zonen", "cmd": {"uuid": ua, "cmd": f"select/{IRR_SELECT_ALLE}"}},
        {"label": "Alles aus", "cmd": {"uuid": ua, "cmd": f"select/{IRR_SELECT_AUS}"}},
    ]})
    return {"t": "view", "title": _clean(c.get("name")), "route": route,
            "anchor": "bottom", "blocks": [
        {"k": "hero", "icon": "info"},
        {"k": "big", "text": big, **({"tone": "good"} if act else {})},
        {"k": "status", "text": "Bewässerung"},
        *rows,
    ]}
