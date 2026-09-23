"""Reine Funktionen der Verlaufs-Diagramme: Dateiformate, Zahlenformate,
Zaehlerlogik und die Rechnungen fuer die Kachel-Stile."""
import calendar
import struct
import time

import pytest

from lox import W


def test_monatsdatei_lesen():
    xml = ('<Statistics><S T="2026-09-01 10:00:00" V="1.5" V2="-2"/>'
           '<S T="2026-09-01 09:00:00" V="1"/><S T="kaputt" V="3"/></Statistics>')
    rows = W._parse_stat_xml(xml)
    t10 = calendar.timegm((2026, 9, 1, 10, 0, 0))
    assert rows == [(t10 - 3600, [1.0]), (t10, [1.5, -2.0])]   # sortiert, Wanduhr-Sekunden


def test_v2_binaer_lesen():
    body = struct.pack("<Id", 1_790_000_000, 7.42) + struct.pack("<Id", 1_790_001_800, float("nan"))
    rows = W._parse_stat2_bin(body)
    wand = calendar.timegm(time.localtime(1_790_000_000))
    assert rows[0] == (wand, [7.42]) and rows[1][1] == [None]
    assert W._parse_stat2_bin(body + b"\x00") is None          # Laenge passt nicht -> unbekannt


@pytest.mark.parametrize("fmt, erwartet", [
    ("%.1f °C", (1, "°C")), ("%.0f%%", (0, "%")), ("%.3fkW", (3, "kW")),
    ("0,000kW", (3, "kW")), ("0,0kWh", (1, "kWh")), ("0,00€", (2, "€")), ("0", (0, "")), (None, (0, "")),
])
def test_zahlenformat(fmt, erwartet):
    assert W._stat_fmt(fmt) == erwartet


def test_zaehler_verbrauch_je_abschnitt():
    # 100 -> 101 (+1), -> 100,9 kleiner Ruecksprung (0), -> 1 zurueckgesetzt (+1), -> 3 (+2)
    pts = [(0, 100.0), (10, 101.0), (20, 100.9), (30, 1.0), (40, 3.0)]
    assert W._stat_bars(pts, [0, 25, 50]) == [(0, 1.0), (25, 3.0)]
    # Stand vor dem Fenster ist die Basis des ersten Abschnitts
    assert W._stat_bars([(-5, 10.0), (5, 12.5)], [0, 10]) == [(0, 2.5)]


def test_ausduennen():
    pts = [(t, float(t % 7)) for t in range(0, 1000)]
    duenn = W._stat_thin(pts, 0, 1000, 50, digital=False)
    assert len(duenn) == 50
    spitze = [(t, 1.0 if t == 503 else 0.0) for t in range(0, 1000)]
    assert max(v for _, v in W._stat_thin(spitze, 0, 1000, 50, digital=True)) == 1.0   # kurzes Ein bleibt


def test_stufen_mittel():
    B = W._stat_buckets
    assert B([(0, 0), (30, 10)], [0, 60, 120, 180], 120) == [5, 10, None]   # nach t_end -> None
    assert B([(-100, 4), (50, 8)], [0, 100], 100) == [6]                  # Stand davor zaehlt
    assert B([(150, 3)], [0, 100, 200], 200) == [None, 3]                 # vorher unbekannt
    assert abs(B([(0, 0), (6 * 3600, 1), (12 * 3600, 0)], [0, 86400], 86400)[0] - 0.25) < 1e-9
    assert B([], [0, 10], 10) == [None]


def test_tagesspanne():
    R = W._stat_day_range
    assert R([(-5, 7), (10, 3), (20, 9)], [0, 100, 200], 150) == [(3, 9), (9, 9)]
    assert R([(-5, 7)], [0, 100, 200], 50) == [(7, 7), None]
    assert R([], [0, 100], 100) == [None]


def test_dauer_text():
    D = W.App._stat_dur
    assert D(3 * 3600 + 20 * 60) == "3 h 20 min" and D(40 * 60) == "40 min"
    assert D(3599.9) == "1 h" and D(7200) == "2 h"
