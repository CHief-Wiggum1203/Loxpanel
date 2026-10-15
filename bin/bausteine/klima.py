"""Bausteine der Visu, Familie Klima: Raumregelung V2 und V1, Klimaanlage, Klimaregler, Lueftung.

Kachel (@kachel) und Detailseite (@detail) je Typ, siehe bausteine/__init__.py.
Die Helfer (app._state, app._fmt_num ...) sind Methoden von App in webvisu.py."""
from __future__ import annotations

import json

from bausteine import detail, kachel
from bausteine.gemeinsam import IRC1_ECO, IRC1_MANUELL, IRC1_TEMPS, IRC1_TIMER_S, _clean


@kachel("IRoomControllerV2", "IRoomController")
def kachel_raumregelung(app, uuid, c, it):
    t = c.get("type")
    ta = app._state(c, "tempActual"); tt = app._state(c, "tempTarget")
    # heizt/kuehlt: V2 meldet es in prepareState, die alte Raumregelung
    # ueber ihre Ventile (siehe _irc1)
    prep = app._state(c, "prepareState") if t == "IRoomControllerV2" else app._irc1(c)["prep"]
    fenster = app._state(c, "openWindow")
    bits = app._irc_activity(prep, fenster)
    if fenster:
        # Hinweis der Hausseite: dringend, solange der Raum dabei
        # heizt oder kuehlt
        taetig = app._irc_activity(prep, None)
        it["hinweis"] = {"stufe": "dringend" if taetig else "warnung", "text": "Fenster offen",
                         "symbol": "window", "zusatz": " · ".join(taetig)}
    sub = (f"{app._fmt_num(ta, '%.1f')}° → {app._fmt_num(tt, '%.1f')}°"
           if ta is not None else "Heizung")
    if bits:
        sub += " · " + " · ".join(bits)
    it.update(icon="thermo", nav={"view": "control", "id": uuid},
              on=bool(prep), sublabel=sub)
    if ta is None:
        it["subInfo"] = True
    else:
        # Neuer Kachel-Aufbau: Ist-Temperatur gross an Stelle des
        # Symbols, die Zeile darunter nennt nur noch Soll und Taetigkeit.
        it["big"] = f"{app._fmt_num(ta, '%.1f')}°"
        it["bigSub"] = " · ".join(([f"Soll {app._fmt_num(tt, '%.1f')}°"] if tt is not None else []) + bits)


@kachel("Ventilation")
def kachel_lueftung(app, uuid, c, it):
    spd = app._state(c, "speed") or 0
    it.update(icon="fan", on=spd > 0, nav={"view": "control", "id": uuid},
              sublabel=(f"{round(spd)} %" if spd > 0 else "Aus"))


@kachel("AcControl")
def kachel_klimaanlage(app, uuid, c, it):
    modes = app._json_list_map(c, "operatingModes")
    tt = app._fmt_num(app._state(c, "targetTemperature"), "%.1f")
    ac_sub = " · ".join(x for x in (modes.get(int(app._state(c, "mode") or 0)),
                                    (tt + " °C" if tt else "")) if x)
    it.update(icon="thermo", on=(app._state(c, "status") or 0) != 0,
              nav={"view": "control", "id": uuid}, sublabel=(ac_sub or "Klima"))
    if not ac_sub:
        it["subInfo"] = True


@kachel("ClimateControllerUS")
def kachel_klimaregler(app, uuid, c, it):
    dh = app._state(c, "demandHeat") or 0
    dc = app._state(c, "demandCool") or 0
    it.update(icon="thermo", on=bool(dh or dc),
              nav={"view": "control", "id": uuid},
              sublabel=("Heizt" if dh else ("Kühlt" if dc else "Bereit")))


@detail("IRoomControllerV2")
def detail_raumregelung_v2(app, uuid, c, route):
    ua = c.get("uuidAction")
    ta = app._fmt_num(app._state(c, "tempActual"), "%.1f")
    tt = app._fmt_num(app._state(c, "tempTarget"), "%.1f")
    # -/+ verstellt die Komforttemperatur - nur mit bekanntem Wert (das
    # Soll kann gerade Eco sein, ein angenommener Wert verstellt die Regelung)
    try:
        comfort = float(app._state(c, "comfortTemperature"))
    except (TypeError, ValueError):
        comfort = None
    modes = app._irc_modes(c)
    am = app._state(c, "activeMode")
    try:
        am = int(am) if am is not None else None
    except (TypeError, ValueError):
        am = None
    art, manuell = app._irc_betriebsart(c)
    # Status: Soll-Temp + aktiver Modus + manuelle Betriebsart + heizt/kuehlt/Fenster
    sbits = []
    if am is not None and am in modes:
        sbits.append(modes[am])
    if manuell:
        sbits.append(manuell)
    sbits += app._irc_activity(app._state(c, "prepareState"),
                                app._state(c, "openWindow"))
    status = f"Soll {tt} °C" + (" · " + " · ".join(sbits) if sbits else "")
    blocks = [
        {"k": "big", "text": f"{ta} °C"},          # grosse Ist-Temp statt Icon
        {"k": "status", "text": status},
    ]
    reihe = [art] if art else []
    if comfort is not None:
        reihe = [{"label": "−", "cmd": {"uuid": ua, "cmd": f"setComfortTemperature/{comfort - 0.5:.1f}"}},
                 *reihe,
                 {"label": "+", "cmd": {"uuid": ua, "cmd": f"setComfortTemperature/{comfort + 0.5:.1f}"}}]
    if reihe:
        blocks.append({"k": "row", "cells": reihe})
    # Betriebsmodi in EINER Zeile: Temperatur-Modi (Eco/Komfort) als
    # 1-h-Override + Automatik (zurueck zur Zeitschaltung). Namen aus MS
    # (details.timerModes). Gebaeudeschutz wird ausgelassen (aufgeraeumt).
    if modes:
        cells = [{"label": nm, "on": (mid == am),
                  "cmd": {"uuid": ua, "cmd": f"override/{mid}"}}
                 for mid, nm in sorted(modes.items())
                 if "schutz" not in (nm or "").lower()]
        cells.append({"label": "Automatik",
                      "cmd": {"uuid": ua, "cmd": "stopOverride"}})
        blocks.append({"k": "row", "cells": cells})
    return {"t": "view", "title": _clean(c.get("name")), "route": route,
            "anchor": "bottom", "blocks": blocks}


@detail("IRoomController")
def detail_raumregelung_v1(app, uuid, c, route):
    # Alte Raumregelung (v1), Befehle laut Loxone-Strukturdoku:
    # settemp/<Nr>/<Wert>, starttimer/<Nr>/<Sekunden>, stoptimer.
    ua = c.get("uuidAction")
    z = app._irc1(c)
    art, manuell = app._irc_betriebsart(c)
    ta = app._fmt_num(app._state(c, "tempActual"), "%.1f")
    tt = app._fmt_num(app._state(c, "tempTarget"), "%.1f")
    # manuell: die Betriebsart ("Manuell Heizen") statt der Temperatur "Manuell"
    sbits = [z["name"]] if z["name"] and not (manuell and z["ix"] == IRC1_MANUELL) else []
    if manuell:
        sbits.append(manuell)
    sbits += app._irc_activity(z["prep"], app._state(c, "openWindow"))
    status = f"Soll {tt} °C" + (" · " + " · ".join(sbits) if sbits else "")
    blocks = [
        {"k": "big", "text": f"{ta} °C"},
        {"k": "status", "text": status},
    ]
    # -/+ verstellt Komfort der Periode (manuell: die manuelle
    # Temperatur) - nur mit bekanntem, absolutem Wert. Dazwischen
    # die Betriebsart (mode/<Nr>).
    reihe = [art] if art else []
    if z["stell"] is not None:
        ix, v = z["stell_ix"], z["stell"]
        reihe = [{"label": "−", "cmd": {"uuid": ua, "cmd": f"settemp/{ix}/{v - 0.5:.1f}"}},
                 *reihe,
                 {"label": "+", "cmd": {"uuid": ua, "cmd": f"settemp/{ix}/{v + 0.5:.1f}"}}]
    if reihe:
        blocks.append({"k": "row", "cells": reihe})
    # Eco/Komfort fuer eine Stunde halten, Automatik beendet den Timer.
    blocks.append({"k": "row", "cells": [
        {"label": IRC1_TEMPS[IRC1_ECO], "on": z["ix"] == IRC1_ECO,
         "cmd": {"uuid": ua, "cmd": f"starttimer/{IRC1_ECO}/{IRC1_TIMER_S}"}},
        {"label": "Komfort", "on": z["ix"] == z["komfort_ix"],
         "cmd": {"uuid": ua, "cmd": f"starttimer/{z['komfort_ix']}/{IRC1_TIMER_S}"}},
        {"label": "Automatik", "cmd": {"uuid": ua, "cmd": "stoptimer"}},
    ]})
    return {"t": "view", "title": _clean(c.get("name")), "route": route,
            "anchor": "bottom", "blocks": blocks}


@detail("Ventilation")
def detail_lueftung(app, uuid, c, route):
    spd = app._state(c, "speed") or 0
    return app._big_view(uuid, "fan", (f"{round(spd)} %" if spd else "Aus"),
                          sub="Lüftung")


@detail("AcControl")
def detail_klimaanlage(app, uuid, c, route):
    ua = c.get("uuidAction")
    # An die IRR-Detailseite angeglichen: grosse Ist-Temp oben, Status-
    # zeile, dann 2 Bedienzeilen. Modus/Fan klappen ihre Auswahl inline
    # auf (viele Optionen passen nicht in eine feste Zeile).
    modes = app._json_list_map(c, "operatingModes")   # {id: name}
    fans = app._json_list_map(c, "fanspeeds")          # {id: name}
    on = (app._state(c, "status") or 0) != 0
    def _as_int(v, d=0):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return d
    cur_mode = _as_int(app._state(c, "mode"))
    cur_fan = _as_int(app._state(c, "fan"))
    tgt = app._state(c, "targetTemperature")
    ist = app._state(c, "temperature")
    try:
        cur_t = float(tgt)
    except (TypeError, ValueError):
        cur_t = 22.0
    try:
        lo = float(app._state(c, "minTemp"))
    except (TypeError, ValueError):
        lo = 5.0
    try:
        hi = float(app._state(c, "maxTemp"))
    except (TypeError, ValueError):
        hi = 40.0
    dn = max(lo, cur_t - 0.5); up = min(hi, cur_t + 0.5)
    # grosse Anzeige = Ist-Temp (wie IRR); Fallback Soll, wenn kein Ist
    try:
        ist_ok = ist is not None and float(ist) > -50
    except (TypeError, ValueError):
        ist_ok = False
    big = (app._fmt_num(ist, "%.1f") + " °C") if ist_ok else \
          ((app._fmt_num(tgt, "%.1f") + " °C") if tgt is not None else "–")
    sbits = []
    if tgt is not None:
        sbits.append(f"Soll {app._fmt_num(tgt, '%.1f')} °C")
    if cur_mode in modes:
        sbits.append(modes[cur_mode])
    sbits.append("Ein" if on else "Aus")
    status = " · ".join(x for x in sbits if x)
    # Zeile 2: Auto (Schnellzugriff Auto-Modus) + Modus/Fan-Aufklapper
    auto_id = next((mid for mid, nm in modes.items()
                    if (nm or "").strip().lower() == "auto"), None)
    row2 = []
    if auto_id is not None:
        row2.append({"label": modes[auto_id], "on": cur_mode == auto_id,
                     "cmd": {"uuid": ua, "cmd": f"setMode/{auto_id}"}})
    # Modus/Fan oeffnen ein Popup mit der Auswahl (statt Inline-Zeilen)
    if modes:
        row2.append({"label": "Modus", "menu": [
            {"label": nm, "on": mid == cur_mode, "cmd": {"uuid": ua, "cmd": f"setMode/{mid}"}}
            for mid, nm in sorted(modes.items())]})
    if fans:
        row2.append({"label": "Fan", "menu": [
            {"label": nm, "on": fid == cur_fan, "cmd": {"uuid": ua, "cmd": f"setFan/{fid}"}}
            for fid, nm in sorted(fans.items())]})
    blocks = [
        {"k": "big", "text": big},
        {"k": "status", "text": status},
        {"k": "row", "cells": [
            {"label": "−", "cmd": {"uuid": ua, "cmd": f"setTarget/{dn:.1f}"}},
            {"label": "Aus", "on": not on, "cmd": {"uuid": ua, "cmd": "off"}},
            {"label": "Ein", "on": on, "cmd": {"uuid": ua, "cmd": "on"}},
            {"label": "+", "cmd": {"uuid": ua, "cmd": f"setTarget/{up:.1f}"}},
        ]},
        {"k": "row", "cells": row2},
    ]
    return {"t": "view", "title": _clean(c.get("name")), "route": route,
            "anchor": "bottom", "blocks": blocks}


@detail("ClimateControllerUS")
def detail_klimaregler(app, uuid, c, route):
    dh = app._state(c, "demandHeat") or 0
    dc = app._state(c, "demandCool") or 0
    big = "Heizt" if dh else ("Kühlt" if dc else "Bereit")
    # verwaltete AC-Einheiten + wie viele gerade Bedarf anmelden
    try:
        units = json.loads(app._state(c, "controls") or "[]")
    except (ValueError, TypeError):
        units = []
    active = sum(1 for u in units if isinstance(u, dict) and u.get("demand"))
    sbits = [f"{active}/{len(units)} Anlagen aktiv"] if units else []
    hum = app._state(c, "humidity") or 0
    if hum:
        sbits.append(f"Feuchte {app._fmt_num(hum, '%.0f')} %")
    out = app._state(c, "actualOutdoorTemp")
    try:
        if out is not None and float(out) > -100:
            sbits.append(f"Außen {app._fmt_num(out, '%.1f')} °C")
    except (TypeError, ValueError):
        pass
    return app._big_view(uuid, "thermo", big, " · ".join(sbits),
                          tone=("crit" if dc else None))
