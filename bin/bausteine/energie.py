"""Bausteine der Visu, Familie Energie: Fronius, Energiefluss (EFM), Energiemanager, PV-Prognose.

Kachel (@kachel) und Detailseite (@detail) je Typ, siehe bausteine/__init__.py.
Die Helfer (app._state, app._fmt_num ...) sind Methoden von App in webvisu.py."""
from __future__ import annotations

from bausteine import detail, kachel
from bausteine.gemeinsam import _clean


@kachel("Fronius")
def kachel_fronius(app, uuid, c, it):
    prod = app._state(c, "prodCurr")
    it.update(icon="central", nav={"view": "control", "id": uuid},
              sublabel=(app._fmt_num(prod, "%.2fkW") if prod is not None else "PV-Anlage"))
    if prod is None:
        it["subInfo"] = True


@kachel("EFM")
def kachel_energiefluss(app, uuid, c, it):
    # Energieflussmonitor: Ppwr Erzeugung, Gpwr Netz (+Bezug/-Einspeisung),
    # Spwr Speicher (+Entladen/-Laden), actual0..5 = Knoten aus details.nodes
    fmt = (c.get("details") or {}).get("actualFormat") or "%.2f kW"
    bits = []
    p = app._endlich(c, "Ppwr")
    if p is not None:
        bits.append("PV " + app._fmt_num(p, fmt))
    g = app._flow_text(app._state(c, "Gpwr"), fmt, "Bezug", "Einspeisung")
    if g:
        bits.append(g)
    it.update(icon="central", nav={"view": "control", "id": uuid},
              sublabel=" · ".join(bits) or "Energiefluss")
    if not bits:
        it["subInfo"] = True


@kachel("EnergyManager2")
def kachel_energiemanager(app, uuid, c, it):
    bits = []
    p = app._endlich(c, "Ppwr")
    if p is not None:
        bits.append("PV " + app._fmt_num(p, "%.2f kW"))
    soc = app._endlich(c, "Ssoc")
    if soc is not None and (c.get("details") or {}).get("HasSsoc", True):
        bits.append("Speicher " + app._fmt_num(soc, "%.0f") + " %")
    it.update(icon="central", nav={"view": "control", "id": uuid},
              sublabel=" · ".join(bits) or "Energiemanager")
    if not bits:
        it["subInfo"] = True


@kachel("PvProductionForecast")
def kachel_pv_prognose(app, uuid, c, it):
    bits = [f"{lbl} {app._fmt_num(v, '%.1f kWh')}"
            for lbl, v in (("Heute", app._state(c, "today")), ("Morgen", app._state(c, "tomorrow")))
            if v is not None]
    it.update(icon="central", nav={"view": "control", "id": uuid},
              sublabel=" · ".join(bits) or "PV-Prognose")
    if not bits:
        it["subInfo"] = True


@detail("Fronius")
def detail_fronius(app, uuid, c, route):
    prod = app._state(c, "prodCurr")
    rows = []
    for nm, lbl, unit in (("consCurr", "Verbrauch", "%.2fkW"),
                          ("prodCurrDay", "Heute erzeugt", "%.1fkWh"),
                          ("deliveryDay", "Heute eingespeist", "%.1fkWh")):
        v = app._state(c, nm)
        if v is not None:
            rows.append({"k": "status", "text": f"{lbl}: {app._fmt_num(v, unit)}"})
    return {"t": "view", "title": _clean(c.get("name")), "route": route, "blocks": [
        {"k": "hero", "icon": "central"},
        {"k": "big", "text": (app._fmt_num(prod, "%.2fkW") if prod is not None else "–")},
        {"k": "status", "text": "Aktuelle Erzeugung"},
        *rows,
    ]}


@detail("EFM")
def detail_energiefluss(app, uuid, c, route):
    det = c.get("details") or {}
    fmt = det.get("actualFormat") or "%.2f kW"
    p = app._endlich(c, "Ppwr")
    rows = []
    g = app._flow_text(app._state(c, "Gpwr"), fmt, "Netzbezug", "Einspeisung")
    if g:
        rows.append({"k": "status", "text": g})
    sp = app._flow_text(app._state(c, "Spwr"), det.get("storageFormat") or fmt,
                         "Speicher entlädt", "Speicher lädt", "Speicher")
    if sp:
        rows.append({"k": "status", "text": sp})
    nodes = app._named_items(det.get("nodes"))
    vals = [(label, app._endlich(c, f"actual{i}")) for i, (label, _n) in enumerate(nodes[:6])]
    vals = [(label, v) for label, v in vals if v is not None]
    if vals:
        rows.append({"k": "head", "text": "Verbraucher und Quellen"})
        rows += [{"k": "status", "text": f"{label}: {app._fmt_num(v, fmt)}"} for label, v in vals]
    eb = app.energy_blocks(uuid)   # Radial auch beim Antippen (4"-Panel ohne Split)
    if eb:
        blocks = [{"k": "eflow", "e": eb}]   # zeigt PV/Netz/Speicher + Verbraucher live, wie in der Loxone-App
    else:
        blocks = [{"k": "hero", "icon": "central"},
                  {"k": "big", "text": (app._fmt_num(p, fmt) if p is not None else "–")},
                  {"k": "status", "text": "Aktuelle Erzeugung"}, *rows]
    return {"t": "view", "title": _clean(c.get("name")), "route": route, "blocks": blocks}


@detail("EnergyManager2")
def detail_energiemanager(app, uuid, c, route):
    det = c.get("details") or {}
    p = app._endlich(c, "Ppwr")
    rows = []
    g = app._flow_text(app._state(c, "Gpwr"), "%.2f kW", "Netzbezug", "Einspeisung")
    if g:
        rows.append({"k": "status", "text": g})
    if det.get("HasSpwr", True):
        sp = app._flow_text(app._state(c, "Spwr"), "%.2f kW", "Speicher entlädt", "Speicher lädt", "Speicher")
        if sp:
            rows.append({"k": "status", "text": sp})
    soc = app._endlich(c, "Ssoc")
    if soc is not None and det.get("HasSsoc", True):
        txt = f"Speicher {app._fmt_num(soc, '%.0f')} %"
        mn = app._endlich(c, "MinSoc")
        if mn is not None:
            txt += f" (Reserve {app._fmt_num(mn, '%.0f')} %)"
        rows.append({"k": "status", "text": txt})
    loads = app._named_items(app._json_state(c, "loads"))
    if loads:
        rows.append({"k": "head", "text": "Verbraucher"})
        for label, e in loads:
            st = e.get("status", e.get("state", e.get("active")))
            if isinstance(st, bool) or st in (0, 1, "0", "1"):
                st = "Ein" if st in (True, 1, "1") else "Aus"
            rows.append({"k": "status", "text": label + (f": {st}" if st not in (None, "") else "")})
    eb = app.energy_blocks(uuid)   # Radial auch beim Antippen (4"-Panel ohne Split)
    head = ([{"k": "eflow", "e": eb}] if eb else
            [{"k": "hero", "icon": "central"},
             {"k": "big", "text": (app._fmt_num(p, "%.2f kW") if p is not None else "–")},
             {"k": "status", "text": "Aktuelle Erzeugung"}])
    return {"t": "view", "title": _clean(c.get("name")), "route": route,
            "blocks": [*head, *rows]}


@detail("PvProductionForecast")
def detail_pv_prognose(app, uuid, c, route):
    det = c.get("details") or {}
    today = app._state(c, "today")
    rows = []
    for nm, lbl in (("tomorrow", "Morgen"), ("period", "Aktueller Zeitraum"), ("after", "Danach")):
        v = app._state(c, nm)
        if v is not None:
            rows.append({"k": "status", "text": f"{lbl}: {app._fmt_num(v, '%.1f kWh')}"})
    mp = det.get("maxPower")
    if mp is not None:
        rows.append({"k": "status", "text": f"Anlagenleistung {app._fmt_num(mp, '%.1f kW')}"})
    err = app._text(c, "errorInfo")
    if err:
        rows.append({"k": "status", "text": err})
    return {"t": "view", "title": _clean(c.get("name")), "route": route, "blocks": [
        {"k": "hero", "icon": "central"},
        {"k": "big", "text": (app._fmt_num(today, "%.1f kWh") if today is not None else "–")},
        {"k": "status", "text": "Erwartete Erzeugung heute"},
        *rows,
    ]}
