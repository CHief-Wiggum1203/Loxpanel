"""Bausteine der Visu, Familie Werte: Wertauswahl, Schieberegler, Texteingabe, Anzeigen (analog, digital, Text), Zaehler, Betriebsstunden, Tracker, Webseite, Anlagenschema.

Kachel (@kachel) und Detailseite (@detail) je Typ, siehe bausteine/__init__.py.
Die Helfer (app._state, app._fmt_num ...) sind Methoden von App in webvisu.py."""
from __future__ import annotations

import re
from urllib.parse import quote

from bausteine import detail, kachel
from bausteine.gemeinsam import _clean


@kachel("ValueSelector", "UpDownAnalog")
def kachel_wertauswahl(app, uuid, c, it):
    det = c.get("details") or {}
    it.update(icon="switch", nav={"view": "control", "id": uuid},
              sublabel=app._fmt_num(app._state(c, "value"), det.get("format") or "%.1f"))


@kachel("TextInput")
def kachel_texteingabe(app, uuid, c, it):
    it.update(icon="info", nav={"view": "control", "id": uuid},
              sublabel=str(app._state(c, "text") or ""))


@kachel("Webpage")
def kachel_webseite(app, uuid, c, it):
    det = c.get("details") or {}
    host = re.sub(r"^https?://", "", det.get("url") or "").split("/")[0]
    it.update(icon="info", nav={"view": "control", "id": uuid},
              sublabel=(host or "Webseite"), subInfo=True)
    img = det.get("image")
    if img and not it.get("iconUrl"):
        it["iconUrl"] = "/icon?p=" + quote(img)


@kachel("InfoOnlyDigital")
def kachel_digitalwert(app, uuid, c, it):
    on = bool(app._state(c, "active"))
    txt = (c.get("details") or {}).get("text") or {}
    it.update(on=on, sublabel=(txt.get("on") if on else txt.get("off")) or ("Ein" if on else "Aus"))


@kachel("Meter")
def kachel_zaehler(app, uuid, c, it):
    det = c.get("details") or {}
    a = app._fmt_num(app._state(c, "actual"), det.get("actualFormat", "%.1f"))
    tot = app._fmt_num(app._state(c, "total"), det.get("totalFormat", "%.1f"))
    it["sublabel"] = " • ".join(x for x in (a, tot) if x)


@kachel("Slider")
def kachel_schieberegler(app, uuid, c, it):
    det = c.get("details") or {}
    it.update(sublabel=app._fmt_num(app._state(c, "value"), det.get("format", "%.1f")),
              nav={"view": "control", "id": uuid})


@kachel("InfoOnlyAnalog")
def kachel_analogwert(app, uuid, c, it):
    det = c.get("details") or {}
    it["sublabel"] = app._fmt_num(app._state(c, "value"), det.get("format", "%.1f"))


@kachel("TextState", "InfoOnlyText")
def kachel_textwert(app, uuid, c, it):
    it["sublabel"] = str(app._state(c, "textAndIcon") or app._state(c, "text") or "")


@kachel("SystemScheme")
def kachel_anlagenschema(app, uuid, c, it):
    # Kachel oeffnet die volle Schema-Ansicht (Hintergrundbild + Live-Werte).
    # Als Sublabel den Hauptbaustein (details.mainControl) zeigen, sonst Hinweis.
    main = app._resolve_control((c.get("details") or {}).get("mainControl"))
    wert = app._scheme_value(main).get("text") if main else ""
    it.update(icon="central", sublabel=(wert or "Anlagenschema"), nav={"view": "control", "id": uuid})
    if not wert:
        it["subInfo"] = True


@kachel("Hourcounter")
def kachel_betriebsstunden(app, uuid, c, it):
    it["sublabel"] = ("Wartung fällig" if app._state(c, "overdue")
                      else app._fmt_num(app._state(c, "total"), "%.0f h"))


@kachel("Tracker")
def kachel_tracker(app, uuid, c, it):
    lines = app._tracker_lines(c)
    _, last = app._split_ts(lines[0]) if lines else (None, "")
    it.update(icon="list", nav={"view": "control", "id": uuid},
              sublabel=(last or "Keine Einträge"))


@detail("SystemScheme")
def detail_anlagenschema(app, uuid, c, route):
    return app._view_scheme(uuid, c, route)


@detail("Tracker")
def detail_tracker(app, uuid, c, route):
    lines = app._tracker_lines(c)
    if not lines:
        return app._big_view(uuid, "list", "Keine Einträge")
    items = []
    for i, ln in enumerate(lines):
        ts, txt = app._split_ts(ln)
        entry = {"id": f"{uuid}:{i}", "icon": "list", "label": txt}
        if ts:
            entry["sublabel"] = ts
        items.append(entry)
    return {"t": "view", "title": _clean(c.get("name")), "route": route,
            "layout": "list", "items": items}


# --- Status-Bausteine: grosse 1/1-Wertseite ---
@detail("Meter")
def detail_zaehler(app, uuid, c, route):
    det = c.get("details") or {}
    a = app._fmt_num(app._state(c, "actual"), det.get("actualFormat", "%.1f"))
    tot = app._fmt_num(app._state(c, "total"), det.get("totalFormat", "%.1f"))
    return app._big_view(uuid, "info", a or "–", (tot + " gesamt") if tot else "")


@detail("Slider", "UpDownAnalog")
def detail_schieberegler(app, uuid, c, route):
    t = c.get("type")
    # Schieberegler und Auf/Ab-Taster sind laut Loxone-Strukturdoku
    # dieselbe Art virtueller Eingang (UpDownAnalog = "UpDownLeftRight
    # analog"): details format/min/max/step, State value und error
    # (ungueltiger Wert), Befehl {wert} zwischen min und max. Die
    # -/+ Tasten schalten um step weiter.
    ua = c.get("uuidAction")
    det = c.get("details") or {}
    fmt = det.get("format", "%.1f")

    def _f(key, dflt):
        try:
            return float(det.get(key, dflt))
        except (TypeError, ValueError):
            return float(dflt)

    def _n(x):   # ganzzahlig darstellen, wenn ohne Nachkommastelle
        return int(x) if float(x).is_integer() else x
    mn, mx = _f("min", 0), _f("max", 100)
    stp = _f("step", 1) or 1
    val = app._state(c, "value")
    try:
        cur = float(val)
    except (TypeError, ValueError):
        cur = mn
    ico = "info" if t == "Slider" else "switch"
    blocks = [{"k": "hero", "icon": ico},
              {"k": "big", "text": app._fmt_num(val, fmt) or "–"}]
    if app._state(c, "error"):
        blocks.append({"k": "status", "text": "Ungültiger Wert"})
    blocks.append({"k": "slider", "icon": "vol" if t == "Slider" else ico, "value": _n(cur),
                   "min": _n(mn), "max": _n(mx), "step": _n(stp),
                   "cmd": {"uuid": ua, "tmpl": "{v}"}})
    return {"t": "view", "title": _clean(c.get("name")), "route": route, "blocks": blocks}


@detail("InfoOnlyAnalog")
def detail_analogwert(app, uuid, c, route):
    det = c.get("details") or {}
    return app._big_view(uuid, "info",
                          app._fmt_num(app._state(c, "value"), det.get("format", "%.1f")) or "–")


@detail("TextState", "InfoOnlyText")
def detail_textwert(app, uuid, c, route):
    return app._big_view(uuid, "info",
                          str(app._state(c, "textAndIcon") or app._state(c, "text") or "–"))


@detail("InfoOnlyDigital")
def detail_digitalwert(app, uuid, c, route):
    on = bool(app._state(c, "active"))
    tx = (c.get("details") or {}).get("text") or {}
    return app._big_view(uuid, "info",
                          (tx.get("on") if on else tx.get("off")) or ("Ein" if on else "Aus"))


@detail("ValueSelector")
def detail_wertauswahl(app, uuid, c, route):
    ua = c.get("uuidAction")
    det = c.get("details") or {}
    val = app._state(c, "value") or 0
    mn = app._state(c, "min"); mx = app._state(c, "max"); stp = app._state(c, "step")
    mn = 0 if mn is None else mn
    mx = 100 if mx is None else mx
    stp = stp if isinstance(stp, (int, float)) and stp else 1
    return {"t": "view", "title": _clean(c.get("name")), "route": route,
            "anchor": "bottom", "blocks": [
        {"k": "hero", "icon": "switch"},
        {"k": "big", "text": app._fmt_num(val, det.get("format") or "%.1f")},
        {"k": "slider", "icon": "vol", "value": val, "min": mn,
         "max": mx, "step": stp, "cmd": {"uuid": ua, "tmpl": "{v}"}},
    ]}


@detail("TextInput")
def detail_texteingabe(app, uuid, c, route):
    return app._big_view(uuid, "info", str(app._state(c, "text") or "–"))


@detail("Webpage")
def detail_webseite(app, uuid, c, route):
    det = c.get("details") or {}
    url = (det.get("urlHd") or det.get("url") or "").strip()
    if url and not re.match(r"^https?://", url):
        url = "http://" + url
    return {"t": "view", "title": _clean(c.get("name")), "route": route,
            "blocks": [{"k": "web", "url": url}]}


@detail("Hourcounter")
def detail_betriebsstunden(app, uuid, c, route):
    ov = app._state(c, "overdue")
    return app._big_view(uuid, "info", app._fmt_num(app._state(c, "total"), "%.0f h") or "–",
                          "Wartung fällig" if ov else "", tone=("crit" if ov else None))
