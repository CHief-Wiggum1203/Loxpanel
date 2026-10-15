"""Bausteine der Visu, Familie Audio: Audiozone (Gen 1) und Audiozone V2.

Kachel (@kachel) und Detailseite (@detail) je Typ, siehe bausteine/__init__.py.
Die Helfer (app._state, app._fmt_num ...) sind Methoden von App in webvisu.py."""
from __future__ import annotations

from bausteine import detail, kachel
from bausteine.gemeinsam import _clean


@kachel("AudioZone")
def kachel_audiozone(app, uuid, c, it):
    playing = app._state(c, "playState") == 2
    ua = c.get("uuidAction")
    it.update(on=playing, sublabel=(app._song(c) or ("An" if playing else "Aus")),
              icon="music", nav={"view": "control", "id": uuid},
              controls=[
                  {"icon": "prev", "cmd": {"uuid": ua, "cmd": "queueminus"}},
                  {"icon": "pause" if playing else "play",
                   "cmd": {"uuid": ua, "cmd": "pause" if playing else "play"}},
                  {"icon": "next", "cmd": {"uuid": ua, "cmd": "queueplus"}},
              ])
    # Sender-Logo bzw. Cover: die breite Kachel zeigt es neben den Tasten
    cover = app._audio_cover(c)
    if cover:
        it["cover"] = cover


@kachel("AudioZoneV2")
def kachel_audiozone_v2(app, uuid, c, it):
    # Audioserver Gen 2: wird ueber den Miniserver gesteuert (play/pause/
    # prev/next/volume) — nicht ueber das Gen-1-Audio-Backend (kein playerid).
    playing = app._state(c, "playState") == 2
    song = app._song(c)
    sm = app._sonn_for(c)          # Sonn liefert Titel/Status, wo Loxone leer ist
    if sm:
        playing = playing or bool(sm.get("playing"))
        song = song or sm.get("title") or ""
    ua = c.get("uuidAction")
    it.update(on=playing, sublabel=(song or ("Spielt" if playing else "Aus")),
              icon="music", nav={"view": "control", "id": uuid},
              controls=[
                  {"icon": "prev", "cmd": {"uuid": ua, "cmd": "prev"}},
                  {"icon": "pause" if playing else "play",
                   "cmd": {"uuid": ua, "cmd": "pause" if playing else "play"}},
                  {"icon": "next", "cmd": {"uuid": ua, "cmd": "next"}},
              ])
    cover = app._audio_cover(c)
    if cover:
        it["cover"] = cover


@detail("AudioZone")
def detail_audiozone(app, uuid, c, route):
    ua = c.get("uuidAction")
    playing = app._state(c, "playState") == 2
    title = app._song(c) or "Radio"
    sub = app._text(c, "artist") or app._text(c, "album")
    vol = int(app._state(c, "volume") or 0)
    cover = app._audio_cover(c)
    blocks = [{"k": "cover", "src": cover}] if cover else []
    blocks += [
        {"k": "title", "text": title, "sub": sub},
        {"k": "row", "cells": [
            {"icon": "prev", "cmd": {"uuid": ua, "cmd": "queueminus"}},
            {"icon": "pause" if playing else "play", "big": True,
             "cmd": {"uuid": ua, "cmd": "pause" if playing else "play"}},
            {"icon": "next", "cmd": {"uuid": ua, "cmd": "queueplus"}},
        ]},
        {"k": "slider", "icon": "vol", "value": vol, "min": 0, "max": 100,
         "cmd": {"uuid": ua, "tmpl": "volume/{v}"}},
    ]
    # Quellen (Radio/Playlist/Spotify) immer auf Unterseite erreichbar
    # (Favoriten werden dort per prime_favs frisch angefordert).
    blocks.append({"k": "more", "route": {"view": "sources", "id": uuid}})
    # Bedienleiste (Transport + Lautstaerke) unten andocken; Cover/Titel
    # oben zentriert. Ohne laufende Musik rutscht so nichts nach oben.
    return {"t": "view", "title": _clean(c.get("name")), "route": route,
            "anchor": "bottom", "blocks": blocks}


@detail("AudioZoneV2")
def detail_audiozone_v2(app, uuid, c, route):
    ua = c.get("uuidAction")
    playing = app._state(c, "playState") == 2
    title = app._song(c)
    sub = app._text(c, "artist") or app._text(c, "album")
    vol = int(app._state(c, "volume") or 0)
    # Sonn/Audioserver4Home reicht Track-Metadaten NICHT ueber das
    # Loxone-Protokoll durch -> per Namensabgleich aus der Sonn-API
    # ergaenzen (nur wo Loxone leer ist). Das Bild: _audio_cover().
    sm = app._sonn_for(c)
    if sm:
        playing = playing or bool(sm.get("playing"))
        title = title or sm.get("title") or ""
        sub = sub or sm.get("artist") or sm.get("album") or ""
        if not vol and sm.get("volume") is not None:
            try:
                vol = int(sm.get("volume"))
            except (TypeError, ValueError):
                pass
    cover = app._audio_cover(c)
    if not title:
        title = "Spielt" if playing else "Aus"
    blocks = [{"k": "cover", "src": cover} if cover else {"k": "hero", "icon": "music"}]
    blocks += [
        {"k": "title", "text": title, "sub": sub},
        {"k": "row", "cells": [
            {"icon": "prev", "cmd": {"uuid": ua, "cmd": "prev"}},
            {"icon": "pause" if playing else "play", "big": True,
             "cmd": {"uuid": ua, "cmd": "pause" if playing else "play"}},
            {"icon": "next", "cmd": {"uuid": ua, "cmd": "next"}},
        ]},
        {"k": "slider", "icon": "vol", "value": vol, "min": 0, "max": 100,
         "cmd": {"uuid": ua, "tmpl": "volume/{v}"}},
    ]
    # 3-Punkte -> Quellen/Favoriten (Sonn via API, sonst Loxone-roomfav)
    blocks.append({"k": "more", "route": {"view": "sources", "id": uuid}})
    return {"t": "view", "title": _clean(c.get("name")), "route": route,
            "anchor": "bottom", "blocks": blocks}
