"""Reine Funktionen des Servers (TODO.md Block 7): Zahlenformat, Farben, Wecker,
Favoriten, Tracker, Whitelists, Panel-Optionen und der Binaerparser des
Miniserver-WebSockets. Eingaben so, wie der Miniserver sie liefert."""
import json
import struct
from datetime import date, datetime, time as uhrzeit, timedelta
from urllib.parse import quote

import pytest

from lox import W
from loxone_ws import LoxoneWS

APP = W.App({"host": "", "port": 80})


def _mit_state(name, wert):
    """Baustein mit einem State `name`, dessen Wert `wert` ist."""
    APP.states = {"s": wert}
    return {"states": {name: "s"}}


@pytest.mark.parametrize("wert, fmt, text", [
    (3.25, "%.2f kW", "3,25 kW"), (3.25, "%.2fkW", "3,25 kW"), (1234.5, "%.1fkWh", "1,2 MWh"),
    (45, "%.0f%%", "45 %"), (21.04, "%.1f°C", "21,0 °C"), (7, "%d", "7"), ("x", "%.1f", ""), (None, "%.1f", ""),
])
def test_zahlenformat(wert, fmt, text):
    assert APP._fmt_num(wert, fmt) == text


def test_farbe_lesen():
    assert W.App._color_parse("hsv(120,50,100)") == ("rgb", 120, 50, 100)
    assert W.App._color_parse("TEMP(80,2700)") == ("temp", 80, 2700, None)
    assert W.App._color_parse("quatsch") == ("none", 0, 0, 0) == W.App._color_parse(None)


def _loxone_zeit(tage, hh=6, mm=30):
    """Sekunden seit 1.1.2009 (Wanduhr) fuer heute + tage um hh:mm."""
    dt = datetime.combine(date.today() + timedelta(days=tage), uhrzeit(hh, mm))
    return int((dt - datetime(2009, 1, 1)).total_seconds())


def test_naechste_weckzeit():
    text = lambda v: APP._alarm_next_text(_mit_state("nextEntryTime", v))   # noqa: E731
    assert text(_loxone_zeit(0)) == "Heute 06:30"
    assert text(_loxone_zeit(1, 7, 5)) == "Morgen 07:05"
    in3 = date.today() + timedelta(days=3)
    assert text(_loxone_zeit(3)) == ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][in3.weekday()] + " 06:30"
    in10 = date.today() + timedelta(days=10)
    assert text(_loxone_zeit(10)) == in10.strftime("%d.%m.") + " 06:30"
    assert text(0) == text("") == text(None) == ""


def test_weckzeiten_liste():
    APP.op_modes = {"3": "Montag", "4": "Dienstag", "9": "Urlaub"}
    roh = {"a": {"name": "Arbeit", "isActive": True, "alarmTime": 6 * 3600 + 30 * 60, "modes": [3, 4]},
           "b": {"name": "", "isActive": False, "alarmTime": 7 * 3600 + 30 * 60, "daily": True},
           "c": {"name": "Frei", "isActive": True, "alarmTime": 9 * 3600, "modes": [9]}}
    liste = APP._alarm_entries(_mit_state("entryList", quote(json.dumps(roh))))   # prozentkodiert wie vom MS
    assert [(e["name"], e["hm"], e["active"]) for e in liste] == [
        ("Arbeit", "06:30", True), ("Frei", "09:00", True), ("Weckzeit", "07:30", False)]
    assert liste[0]["repeat"] == "Mo Di" and liste[1]["repeat"] == "Urlaub" and liste[2]["repeat"] == "Täglich"
    woche = dict(zip("1234567", ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]))
    APP.op_modes = woche
    assert APP._alarm_repeat({"modes": [1, 2, 3, 4, 5, 6, 7]}) == "Täglich"      # alle sieben Tage
    assert APP._alarm_repeat({"modes": [42]}) == "1 Betriebsart"                 # Name unbekannt
    assert APP._alarm_repeat({"modes": [42, 43]}) == "2 Betriebsarten"
    assert APP._alarm_entries(_mit_state("entryList", "{kaputt")) == []


@pytest.mark.parametrize("quelle", [
    {"getroomfavs_result": [{"id": 1, "items": [{"slot": 1, "name": "Ö3"}, {"slot": 2, "name": "FM4"}]}]},
    {"getroomfavs_result": [{"slot": 1, "name": "Ö3"}, {"slot": 2, "name": "FM4"}]},
    {"items": [{"slot": 1, "name": "Ö3"}, {"slot": 2, "name": "FM4"}, {"slot": 2, "name": "doppelt"}]},
])
def test_raumfavoriten(quelle):
    favs = APP._audio_favs(_mit_state("sourceList", json.dumps(quelle)))
    assert [(f["slot"], f["name"]) for f in favs] == [(1, "Ö3"), (2, "FM4")]


def test_raumfavoriten_leer_oder_kaputt():
    assert APP._audio_favs(_mit_state("sourceList", "")) == []
    assert APP._audio_favs(_mit_state("sourceList", "{kaputt")) == []


def test_tracker_zeilen():
    roh = quote("2026-09-23 07:00 Tür auf\\n2026-09-23 06:58 Klingel\r\n\\r\\n2026-09-22 22:10 Alarm")
    assert APP._tracker_lines(_mit_state("entries", roh)) == [
        "2026-09-23 07:00 Tür auf", "2026-09-23 06:58 Klingel", "2026-09-22 22:10 Alarm"]
    assert APP._tracker_lines(_mit_state("entries", "")) == []


def test_whitelist_aufloesen():
    raeume = {"u1": {"name": "1.0.2 Terrasse"}, "u2": {"name": "Küche"}, "u3": {"name": "Küche OG"}}
    assert APP._resolve_ids([], raeume) is None                       # leer = alles sichtbar
    assert APP._resolve_ids(["u2"], raeume) == {"u2"}                 # UUID
    assert APP._resolve_ids(["Terrasse"], raeume) == {"u1"}           # Teilname
    assert APP._resolve_ids(["küche"], raeume) == {"u2"}              # exakter Name schlaegt Teilstring
    assert APP._resolve_ids(["OG", " "], raeume) == {"u3"}


def test_panel_optionen_bereinigen():
    roh = {"wohnen": {"title": "Wohnen", "tabs": ["favoriten", "gibtsnicht"], "unbekannt": 1,
                      "tiles": {"T": {"bg": "#123456", "chart": "30d", "schrott": True}}}}
    p = W.App._sanitize_panels(roh)["wohnen"]
    assert p["title"] == "Wohnen" and "unbekannt" not in p
    assert p["tiles"]["T"] == {"bg": "#123456", "chart": "30d"}


def _uuid_bytes(u):
    d1, d2, d3, d4 = u.split("-")
    return struct.pack("<IHH", int(d1, 16), int(d2, 16), int(d3, 16)) + bytes.fromhex(d4)


def test_websocket_werte_tabelle():
    u1, u2 = "0f1e2d3c-4b5a-6978-8796a5b4c3d2e1f0", "12345678-9abc-def0-0011223344556677"
    daten = _uuid_bytes(u1) + struct.pack("<d", 21.5) + _uuid_bytes(u2) + struct.pack("<d", -1.0)
    got = []
    LoxoneWS._parse_values(daten, lambda u, v: got.append((u, v)))
    assert got == [(u1, 21.5), (u2, -1.0)]


def test_websocket_text_tabelle():
    u1, u2 = "0f1e2d3c-4b5a-6978-8796a5b4c3d2e1f0", "12345678-9abc-def0-0011223344556677"

    def eintrag(u, text):
        t = text.encode()
        roh = _uuid_bytes(u) + bytes(16) + struct.pack("<I", len(t)) + t
        return roh + bytes(-len(roh) % 4)                      # auf 4 Byte aufgefuellt
    got = []
    LoxoneWS._parse_texts(eintrag(u1, "Küche") + eintrag(u2, "ok"), lambda u, v: got.append((u, v)))
    assert got == [(u1, "Küche"), (u2, "ok")]
