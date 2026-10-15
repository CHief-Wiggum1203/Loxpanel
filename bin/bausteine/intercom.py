"""Bausteine der Visu, Familie Tuersprechstellen: Intercom und IntercomV2.

Kachel (@kachel) und Detailseite (@detail) je Typ, siehe bausteine/__init__.py.
Die Helfer (app._state, app._fmt_num ...) sind Methoden von App in webvisu.py."""
from __future__ import annotations

from bausteine import detail, kachel
from bausteine.gemeinsam import INTERCOM_TYPES, _clean


@kachel(*INTERCOM_TYPES)
def kachel_tuersprechstelle(app, uuid, c, it):
    ring = bool(app._state(c, "bell"))
    # v2: Geraetezustand und Stumm sind Zustaende, keine Beschreibung
    sub = "Es klingelt" if ring else (app._intercom_zustand(c) or
                                      ("Stummgeschaltet" if app._state(c, "muted") else ""))
    it.update(icon="cam", on=ring, sublabel=sub or "Türsprechanlage",
              nav={"view": "control", "id": uuid})
    if not sub:
        it["subInfo"] = True
    if ring:
        it["tone"] = "crit"


@detail(*INTERCOM_TYPES)
def detail_tuersprechstelle(app, uuid, c, route):
    t = c.get("type")
    ua = c.get("uuidAction")
    subs = c.get("subControls") or {}
    cells = [{"label": _clean(sc.get("name")),
              "cmd": {"uuid": sc.get("uuidAction"), "cmd": "pulse"}}
             for sc in subs.values()]
    blocks = []
    if app._state(c, "bell"):
        blocks.append({"k": "astat", "text": "Es klingelt", "tone": "crit"})
    zustand = app._intercom_zustand(c)
    if zustand:
        blocks.append({"k": "status", "id": "zustand", "text": zustand})
    blocks.append(app._intercom_video_block(uuid, c))
    if cells:
        blocks.append({"k": "row", "cells": cells})
    # Die native Bruecke fuehrt Audio; Browser/Fully filtern diesen Block.
    # deviceType ist keine Generation: auch eine Gen-1 kann 0 melden.
    if t == "Intercom":
        blocks.append({"k": "intercom-talk", "uuid": uuid, "nativeOnly": True})
    # Laut Strukturdoku: 'answer' stellt die Klingel ab; lastBellEvents
    # sind die Klingeln, auf die niemand reagiert hat. Eigene Zeile
    # hinter den Ausgaengen - die Kamera-Pane zeigt sie nicht
    # (intercom_blocks).
    extra = []
    if app._state(c, "bell"):
        extra.append({"label": "Klingel abstellen", "cmd": {"uuid": ua, "cmd": "answer"}})
    n = len(app._bell_events(c))
    if n:
        extra.append({"label": f"{n} verpasste Klingel" + ("" if n == 1 else "n"),
                      "nav": {"view": "bells", "id": uuid}})
    if extra:
        blocks.append({"k": "row", "id": "klingel", "cells": extra})
    # Nur v2 (Strukturdoku 17.0, IntercomV2): Antworten spielt die Intercom
    # an der Tuer ab (playTts/{idx}); muted ist der Ausgang Qb des
    # Bausteins, mute/{0/1} schaltet ihn stumm bzw. wieder laut.
    antworten = [{"label": a, "cmd": {"uuid": ua, "cmd": f"playTts/{i}"}}
                 for i, a in app._intercom_antworten(c)] if t == "IntercomV2" else []
    if antworten:
        blocks += [{"k": "head", "id": "antworten", "text": "Antwort abspielen"},
                   {"k": "row", "id": "antworten", "wrap": True, "cells": antworten}]
    if t == "IntercomV2" and "muted" in (c.get("states") or {}):
        stumm = bool(app._state(c, "muted"))
        blocks.append({"k": "row", "id": "stumm", "cells": [
            {"label": "Stumm", "on": stumm, "cmd": {"uuid": ua, "cmd": "mute/0" if stumm else "mute/1"}}]})
    return {"t": "view", "title": _clean(c.get("name")), "route": route, "blocks": blocks}
