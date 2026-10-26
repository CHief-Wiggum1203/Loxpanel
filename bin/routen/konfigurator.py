"""Routen des Konfigurators: /api/meta (was er zum Start braucht), Ansichten
und Vorgaben speichern (/api/panels, /api/theme), einen Entwurf in der Visu
ansehen (/api/entwurf), die Kachel-Sets (/api/kachelset) und die Uebersicht
der Bausteintypen (/api/types).

Die Handler holen die App aus request.app["app"]; main() in webvisu.py traegt
sie in die Routentabelle ein. Importiert webvisu nicht (App nur als Typangabe)."""
from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING
from urllib.parse import quote

import aiohttp
from aiohttp import web

import theme_colors
from bausteine.gemeinsam import _clean
from bento_format import BENTO_VORSCHLAG_NAME, bento_grenzen, bento_vorschlag, STREIFEN_AB   # LoxOS
from front_info import calendar_sources   # LoxOS
from gesten import GESTEN_AUDIO_TYPEN   # LoxOS
from geraete import _lan_adressen, NEULADEN_STUNDE, VORSCHAU_GERAET_DAUER
from haus import HAUS_ENERGIE_TYPEN, HAUS_TITEL
from konfig import (
    _clean_kachel_aktiv, _clean_kachel_farbton, _clean_kachel_set, _devices_export, FRONT_TABS,
    GERAETE_KATALOG, GESTEN_HINWEIS_STANDARD, GESTEN_STANDARD, GROESSEN_STANDARD, HAUS_AKTIV_ARTEN,
    HAUS_AUFBAU_STANDARD, HAUS_AUFBAUTEN, HAUS_ENERGIE_AUS, HAUS_TAB, KACHEL_WACHSEN, KACHEL_ZIEL,
    KACHEL_ZIEL_MAX, KACHEL_ZIEL_MIN, KACHEL_ZIEL_STANDARD, NACHT_STANDARD, PANE_ANTEIL,
    PANE_SPALTEN_MAX, _panels_verworfen, PICK_TAB, PIN_MERKEN_MAX, PIN_MERKEN_STANDARD,
    _sanitize_categories, _sanitize_panels, _sanitize_theme_ui, SCALE_MAX, SCALE_MIN, STAT_RANGES,
    SV_STATUS_MAX, THEME_UI_KEYS, TITEL_MAX)
from routen.gemeinsam import _push
from seiten import KACHEL_BREIT_TYPEN, WERTE_LEISTE_TYPEN
from symbolquellen import _loxlib_names

if TYPE_CHECKING:   # nur fuer die Typangabe, kein Import zur Laufzeit (webvisu importiert hierher)
    from webvisu import App

log = logging.getLogger("loxpanel.webvisu")   # derselbe Logger wie der Server


async def api_kachelset(request: web.Request) -> web.Response:
    """Nachgerechnete Kontraste eines Kachel-Sets zu Farbton und aktiver Kachel
    (?set=touch&farbton=95&aktiv=dunkel), fuer "Nachgerechnet" und die
    Vorschau der Auswahlkarte im Konfigurator. Nur lesend; Ungueltiges gilt als Standard des Sets."""
    q = request.query
    name = _clean_kachel_set(q.get("set"))
    if not name:
        return web.json_response({"error": "unbekanntes Kachel-Set"}, status=404)
    try:
        farbton = _clean_kachel_farbton(int(q.get("farbton", "")))
    except ValueError:
        farbton = None
    aktiv = _clean_kachel_aktiv(q.get("aktiv"))
    return web.json_response({"set": name, "kachel": theme_colors.kachel_set_kachel(name, farbton, aktiv),
                              "vorschau": theme_colors.kachel_set_vorschau(name, farbton, aktiv),
                              "pruefung": theme_colors.kachel_set_pruefung(name, farbton, aktiv)})


async def api_bento_vorschlag(request: web.Request) -> web.Response:
    """LoxOS (Fork): Vorschlag fuer die Bento-Startseite eines Streifens
    (?device=<Name>), Schritt 4 des Assistenten. Sammelt, was die Anlage hat -
    erste Audiozone, Energiefluss (EFM, sonst Energiemanager), Kalender-Abo,
    Favoriten in Strukturreihenfolge - und das gemeldete Format des Geraets
    (wie /api/devices); gerechnet wird in bento_format.bento_vorschlag().
    Nur lesend, speichert nichts."""
    app: App = request.app["app"]
    name = request.query.get("device", "")
    schirm = next((d["screen"] for d in app.device_list()["devices"] if d["name"] == name), {})
    format_ = {k: schirm[k] for k in ("vw", "vh") if k in schirm}
    bekannt = len(format_) == 2
    energie = next((u for t in HAUS_ENERGIE_TYPEN for u, c in app.controls.items() if c.get("type") == t), None)
    zone = next((u for u, c in app.controls.items() if c.get("type") in GESTEN_AUDIO_TYPEN), None)
    favoriten = [u for u, c in app.controls.items() if c.get("isFavorite") and c.get("name")]
    v = bento_vorschlag(format_ if bekannt else None,
                        {"energy": energie, "player": zone, "kalender": bool(calendar_sources(app.calendar_cfg))},
                        favoriten)
    return web.json_response({"pickTab": {"name": BENTO_VORSCHLAG_NAME, "picks": v["picks"], "bento": v["bento"]},
                              "format": v["bento"]["format"], "formatBekannt": bekannt})


async def api_bento_aktionen(request: web.Request) -> web.Response:
    """LoxOS (Fork): Was ein Knopf der Schnellaktionen fuer den Baustein ?id=
    tun kann - die Aktionen seiner Detailseite (Beschriftungen,
    _detail_aktionen) und ob ein Tipp auf seine Kachel etwas tut (kachel:
    "cmd" schaltet, "nav" oeffnet, "" nichts). Fuer die Auswahl im
    Bento-Editor; nur lesend."""
    app: App = request.app["app"]
    u = request.query.get("id", "")
    if u not in app.controls:
        return web.json_response({"ok": False, "error": "Baustein unbekannt"}, status=404)
    it = app._control_item(u)
    return web.json_response({"ok": True, "aktionen": [a["label"] for a in app._detail_aktionen(u)],
                              "kachel": "cmd" if it.get("cmd") else ("nav" if it.get("nav") else "")})


async def api_meta(request: web.Request) -> web.Response:
    """Alle Räume/Kategorien der Anlage + aktuelle Profile (für den Editor)."""
    app: App = request.app["app"]
    rooms = [{"uuid": ru, "name": _clean(app.rooms[ru].get("name", ""))} for ru in app.rooms_with]
    cats = [{"uuid": cu, "name": _clean(app.cats[cu].get("name", "")),
             "color": app.cats[cu].get("color")}         # Loxone-Voreinstellungsfarbe der Kategorie
            for cu in app.cats_with]
    panels = {pid: app._panel_export(raw) for pid, raw in app.panels.items()}
    controls = []
    for u, c in app.controls.items():
        if not c.get("name"):
            continue
        room = c.get("room")
        # Was die Kachel zeigt, fuer die Vorschau im Seiten-Editor: ihre Tasten
        # (Anzahl) und ein Cover - dieselbe Rechnung wie in der Visu
        kachel = app._control_item(u)
        controls.append({
            "uuid": u, "name": _clean(c.get("name")), "type": c.get("type"),
            "room": room,
            "roomName": _clean((app.rooms.get(room) or {}).get("name", "")) if room else "",
            "cat": c.get("cat"),
            "iconUrl": app._control_icon_url(c),
            # Zeichnet der Baustein auf? Dann bietet der Konfigurator ihn fuer
            # die Verlaufs-Pane und den Mini-Verlauf in der Kachel an.
            "stat": bool(c.get("statistic") or c.get("statisticV2")),
            # Art der Reihe, die die Kachel zeigt (line/digital/counter): die
            # Tagesspanne gibt es nur fuer Linien.
            "statKind": (app._stat_primary(c) or (None, None))[1],
            "tasten": len(kachel.get("controls") or []),
            "cover": kachel.get("cover") or "",
        })
    return web.json_response({
        "rooms": rooms, "cats": cats, "controls": controls,
        # Zeitraeume der Verlaufs-Diagramme (Schluessel, Anzeige) fuer die Auswahl
        # "Verlauf in der Kachel" — eine Quelle mit der Visu (STAT_RANGES).
        "statRanges": [[k, v[0]] for k, v in STAT_RANGES.items()],
        # Wie viele Werte-Kacheln die Uhr-Seite traegt. Der Konfigurator liest
        # die Zahl hier ab, statt sie ein zweites Mal zu fuehren.
        "svStatusMax": SV_STATUS_MAX,
        # LoxOS (Fork): Grenzen und Standards der Bento-Seiten fuer den Editor
        "bento": bento_grenzen(),
        "streifenAb": STREIFEN_AB,           # LoxOS: ab diesem Seitenverhaeltnis ist ein Schirm ein Streifen
        "titelMax": TITEL_MAX,               # LoxOS: so lang speichert der Server einen Ansichtstitel (Assistent)
        # Grenzen des Skalierungsfaktors; der Konfigurator bietet nur Stufen
        # innerhalb davon an.
        "scaleRange": [SCALE_MIN, SCALE_MAX],
        # Groessen ohne Einstellung je Kachel-Aufbau: der Konfigurator zeigt sie
        # in leeren Feldern an, statt sie ein zweites Mal zu fuehren.
        "sizeDefaults": GROESSEN_STANDARD,
        # Kachel-Sets [{key, label}]: die Auswahl im Konfigurator, eine Quelle
        # mit _theme_vars() (theme_colors.KACHEL_SETS).
        "kachelSets": theme_colors.kachel_set_liste(),
        # Nachtmodus ohne Einstellung (Abdunkelung, Aufhellen): leere Felder
        # unter Vorgaben -> Nacht und Ansicht -> Verhalten zeigen ihn.
        "nightDefaults": NACHT_STANDARD,
        # Welche ui-Schluessel eine Vorgabe haben (theme.json): der Konfigurator
        # zeigt nur bei ihnen "aus den Vorgaben" und zaehlt die Ansichten, die
        # sie selbst setzen.
        "themeKeys": list(THEME_UI_KEYS),
        # Stunde des naechtlichen Neuladens ohne Einstellung "Auto-Neustart":
        # der Konfigurator nennt sie im leeren Feld.
        "reloadAt": NEULADEN_STUNDE,
        # PIN merken: Standard und Grenze fuer das Feld im Konfigurator
        "pinMerken": {"standard": PIN_MERKEN_STANDARD, "max": PIN_MERKEN_MAX},
        "icons": {"loxone": app._loxone_icons(), "loxlib": len(_loxlib_names())},
        "tabs": [{"tab": "favoriten", "label": "Favoriten"},
                 {"tab": "zentral", "label": "Zentral"},
                 {"tab": "raeume", "label": "Räume"},
                 {"tab": "kategorien", "label": "Kategorien"},
                 {"tab": PICK_TAB, "label": "Eigene Auswahl", "pick": True}]
        + [{"tab": k, "label": titel} for k, (titel, _teil) in FRONT_TABS.items()]
        + [{"tab": HAUS_TAB, "label": HAUS_TITEL}]
        + [{"tab": "cat:" + cu, "label": _clean(app.cats[cu].get("name", "")),
            "iconUrl": app._icon_url(app.cats[cu].get("image")), "cat": True}
           for cu in app.cats_with]
        + [{"tab": "room:" + ru, "label": _clean(app.rooms[ru].get("name", "")),
            "iconUrl": app._icon_url(app.rooms[ru].get("image")), "room": True}
           for ru in app.rooms_with],
        "panels": panels,
        "devices": _devices_export(app.devices),
        # Zielkachel des automatischen Rasters: Grenzen, Standard, alte Stufen
        "kachelZiel": {"min": KACHEL_ZIEL_MIN, "max": KACHEL_ZIEL_MAX, "std": KACHEL_ZIEL_STANDARD,
                       "stufen": KACHEL_ZIEL, "wachsen": KACHEL_WACHSEN},
        # Widget-Breite im automatischen Raster: groesste feste Spaltenzahl, Anteil der Automatik
        "paneCols": {"max": PANE_SPALTEN_MAX, "anteil": PANE_ANTEIL},
        # Assistent Schritt 1: Geraete zum Vorrechnen, solange keines verbunden ist
        "geraeteKatalog": [dict(k) for k in GERAETE_KATALOG],
        # Bausteintypen, deren Kachel von Haus aus zwei Spalten belegt (Kachel-Editor: Breite)
        "kachelBreit": sorted(KACHEL_BREIT_TYPEN),
        # Bausteintypen, die auf einer Seite mit Werteleiste aus dem Raster in
        # die Leiste wandern (Seiten-Editor: zeigt die Seite wie die Visu)
        "werteLeiste": sorted(WERTE_LEISTE_TYPEN),
        # Bausteine mit active-State: Auswahl fuer den Praesenzmelder je Geraet
        # (dieselbe Liste wie beim Nacht-Ausloeser)
        "activeControls": app.night_control_options(),
        # Gesten: Taster fuer "Raum verlassen" (je Raum) und "Haus aus"
        # (Vorgaben), Lichtsteuerungen mit Stimmungen fuer "Stimmung beim
        # Einschalten" (Geraete) und der Standard ohne Einstellung
        "gestenTaster": app.geste_taster_optionen(),
        "lichtStimmungen": app.licht_stimmung_optionen(),
        "gestenStandard": GESTEN_STANDARD,
        "gestenHinweisStandard": GESTEN_HINWEIS_STANDARD,
        # Aufbau der Hausseite: Auswahl je Ansicht (Aussehen) und ihr Standard
        "hausAufbauten": [{"key": k, "label": v} for k, v in HAUS_AUFBAUTEN.items()],
        "hausAufbauStandard": HAUS_AUFBAU_STANDARD,
        # ... was unter "Gerade aktiv" zaehlen kann und die Energie-Bausteine
        # fuer den Kopf (dazu der Wert fuer "keine")
        "hausAktivArten": [{"key": k, "label": v[0]} for k, v in HAUS_AKTIV_ARTEN.items()],
        "hausEnergien": app.haus_energie_optionen(),
        "hausEnergieAus": HAUS_ENERGIE_AUS,
        "wsDevices": sorted({d for d in app.conn_dev.values() if d}),
        # LAN-Adresse dieses Servers fuer "Geraet verbinden" (auch wenn der
        # Konfigurator ueber 127.0.0.1 laeuft); leer ohne Route ins Netz
        "adressen": _lan_adressen(),
        "theme": {"ui": {k: v for k, v in (app.theme.get("ui") or {}).items()
                         if k in THEME_UI_KEYS},
                  "categories": {k: v for k, v in (app.theme.get("categories") or {}).items()
                                 if not str(k).startswith("_")}},
    })


async def api_save_panels(request: web.Request) -> web.Response:
    app: App = request.app["app"]
    try:
        data = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        return web.json_response({"ok": False, "error": "kein gültiges JSON"}, status=400)
    panels = data.get("panels")
    if not isinstance(panels, dict):
        return web.json_response({"ok": False, "error": "Feld 'panels' fehlt"}, status=400)
    clean = _sanitize_panels(panels)
    # Was der Server nicht uebernimmt, meldet er (Konfigurator zeigt es an),
    # statt es still zu verlieren.
    weg = _panels_verworfen(panels, clean,
                                {u: _clean(c.get("name")) or u for u, c in app.controls.items()})
    try:
        app._write_panels(clean)
    except OSError as err:
        return web.json_response({"ok": False, "error": str(err)}, status=500)
    # Vorschau-Fenster mit einem Entwurf verlassen ihn: die Entwuerfe sind erledigt, sie
    # laden das gespeicherte Profil. Ein blosses Neuladen liesse sie auf der Entwurfs-
    # Adresse, und der Konfigurator koennte sie nicht sicher umlenken (Wettlauf).
    # Die Gesten-Probe bleibt (_write_panels behaelt sie), sie laedt nur neu.
    for ws, info in list(app.conn_info.items()):
        if info.get("entwurf") and not (app.conn_prof.get(ws) or {}).get("probe"):
            await app._neu_laden(ws, {"t": "entwurfEnde"})
    n = await _push(app, {"t": "reload"})   # offene Panels sofort neu laden
    log.info("panels.json gespeichert: %d Profile (%d Panels neu geladen)", len(clean), n)
    if weg:
        log.warning("panels.json: nicht übernommen: %s", "; ".join(weg))
    # `panels`: was jetzt tatsaechlich in der Datei steht, in der Form von /api/meta.
    # Der Konfigurator fuehrt das als gespeicherten Stand (ohne Verworfenes, normiert).
    return web.json_response({"ok": True, "count": len(clean), "reloaded": n, "verworfen": weg,
                              "panels": {pid: app._panel_export(raw) for pid, raw in app.panels.items()}})


async def api_entwurf(request: web.Request) -> web.Response:
    """Entwurf eines Profils fuer die Vorschau in der echten Visu: {id, panel,
    token?, gestenProbe?}. `panel` ist das Profil in der Form, in der der Konfigurator es
    speichert; es wird wie dort geprueft (was verworfen wuerde, steht in
    `verworfen`), aber nur im Speicher gehalten - panels.json bleibt unberuehrt.
    Antwort: `token` und `url` der Visu (/?panel=<id>&entwurf=<token>). Mit dem
    Token eines vorhandenen Entwurfs desselben Profils wird er ersetzt, und die
    Visus, die ihn gerade zeigen, laden neu (`reloaded`). `gestenProbe`
    ({schalten, vorgaben, geraet}, Vorgaben -> Verhalten) macht ihn zur
    Gesten-Probe: die Maus bedient die Visu wie zwei Finger, die Befehle
    zeigt der Konfigurator, gesendet werden sie nur mit `schalten`."""
    app: App = request.app["app"]
    try:
        data = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        return web.json_response({"ok": False, "error": "kein gültiges JSON"}, status=400)
    pid, panel = data.get("id"), data.get("panel")
    if not isinstance(pid, str) or not pid.strip() or not isinstance(panel, dict):
        return web.json_response({"ok": False, "error": "Felder 'id' und 'panel' fehlen"}, status=400)
    pid = pid.strip()
    try:
        token, weg = app.entwurf_ablegen(pid, panel, str(data.get("token") or ""),
                                         app.gesten_probe_pruefen(data.get("gestenProbe")))
    except ValueError as err:
        return web.json_response({"ok": False, "error": str(err)}, status=400)
    n = 0
    for ws, info in list(app.conn_info.items()):
        if info.get("entwurf") == token and await app._neu_laden(ws):
            n += 1
    for v in app.vorschau_geraet.values():   # der Konfigurator arbeitet noch daran: die Vorschau am Geraet bleibt
        if v["token"] == token:
            v["bis"] = time.time() + VORSCHAU_GERAET_DAUER
    return web.json_response({"ok": True, "token": token, "reloaded": n, "verworfen": weg,
                              "url": "/?panel=" + quote(pid, safe="") + "&entwurf=" + token})


async def api_save_theme(request: web.Request) -> web.Response:
    """Globale Darstellung (theme.json ui) speichern — gilt fuer alle Panels."""
    app: App = request.app["app"]
    try:
        data = await request.json()
    except (ValueError, aiohttp.ContentTypeError):
        return web.json_response({"ok": False, "error": "kein gültiges JSON"}, status=400)
    ui = data.get("ui")
    if not isinstance(ui, dict):
        return web.json_response({"ok": False, "error": "Feld 'ui' fehlt"}, status=400)
    clean = _sanitize_theme_ui(ui)
    cats = data.get("categories")
    clean_cats = _sanitize_categories(cats) if isinstance(cats, dict) else None
    try:
        app._write_theme(clean, clean_cats)
    except OSError as err:
        return web.json_response({"ok": False, "error": str(err)}, status=500)
    n = await _push(app, {"t": "reload"})   # offene Panels sofort neu laden
    log.info("theme.json (globale Darstellung%s) gespeichert (%d Panels neu geladen)",
             " + Kategorie-Farben" if clean_cats is not None else "", n)
    return web.json_response({"ok": True, "reloaded": n})


async def api_types(request: web.Request) -> web.Response:
    """Diagnose: Bausteintypen der Anlage mit Unterstuetzungsstatus. JSON,
    mit ?format=text als lesbare Tabelle fuer den Browser."""
    app: App = request.app["app"]
    if not app.controls:
        data = {"connected": app.client is not None, "controls": 0, "typeCount": 0,
                "typesByStatus": {"full": 0, "partial": 0, "none": 0}, "types": [],
                "unsupportedControls": [],
                "hint": "Keine Struktur geladen. Miniserver unter /config verbinden."}
    else:
        data = app.types_overview()
    if request.query.get("format") == "text":
        lines = [f"LoxPanel Bausteintypen: {data['controls']} Controls, {data['typeCount']} Typen "
                 f"(voll {data['typesByStatus']['full']}, teilweise {data['typesByStatus']['partial']}, "
                 f"keine {data['typesByStatus']['none']})", ""]
        if data.get("hint"):
            lines.append(data["hint"])
        label = {"full": "voll", "partial": "teilw.", "none": "KEINE"}
        lines.append(f"{'Status':8} {'Anzahl':>6}  {'Typ':30} Beispiele")
        for e in data["types"]:
            lines.append(f"{label[e['status']]:8} {e['count']:6}  {e['type']:30} {', '.join(e['examples'])}")
        if data["unsupportedControls"]:
            lines += ["", "Nicht unterstuetzte Controls (tote Kacheln):"]
            lines += [f"  {d['room'] or '-':24} {d['name']:36} {d['type']}" for d in data["unsupportedControls"]]
        lines += ["", "States/Details je Typ:"]
        for e in data["types"]:
            lines.append(f"  {e['type']}: states={', '.join(e['states']) or '-'} | details={', '.join(e['details']) or '-'}")
        return web.Response(text="\n".join(lines) + "\n", content_type="text/plain", charset="utf-8")
    return web.json_response(data, dumps=lambda d: json.dumps(d, ensure_ascii=False, indent=2))


