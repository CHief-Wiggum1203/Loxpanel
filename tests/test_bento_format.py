"""LoxOS (Fork, docs/VISION.md): Datenformat der Bento-Seiten.

Geprueft wird der Sanitizer (_bento_seite, ueber _sanitize_panels und
_pick_tabs) gegen die Regeln aus VISION.md: Zellen im Raster ohne
Ueberlappung, Bausteine nur aus picks und je Seite einmal, Widgets wie bei
den Panes plus Uhr und Webseite, gleiche Quelle nur einmal, Webseiten nur mit
http/https - und dass Verworfenes gemeldet wird statt still zu verschwinden.
"""
from __future__ import annotations

import logging

import pytest

import konfig
from konfig import (BENTO_SPALTEN_MAX, BENTO_SPALTEN_STANDARD, BENTO_URL_MAX, BENTO_ZEILEN_MAX,
                    BENTO_ZEILEN_STANDARD, BENTO_ZELLE_BAUSTEINE_MAX, BENTO_NAME_MAX,
                    _bento_seite, _clean_iframe_url, _panels_verworfen, _pick_tabs, _sanitize_panels)

PICKS = ["A", "B", "C", "D"]


def zellen(cells, picks=PICKS, cols=6, rows=2):
    return _bento_seite({"cols": cols, "rows": rows, "cells": cells}, picks)["cells"]


def z(x, y, w=1, h=1, **inhalt):
    return {"x": x, "y": y, "w": w, "h": h, **inhalt}


# ---- Raster ------------------------------------------------------------------

def test_kein_dict_ist_keine_bento_seite():
    for roh in (None, [], "6x2", 3, True):
        assert _bento_seite(roh, PICKS) is None


def test_leeres_raster_bekommt_den_standard_und_leere_zellen():
    assert _bento_seite({}, PICKS) == {"cols": BENTO_SPALTEN_STANDARD, "rows": BENTO_ZEILEN_STANDARD,
                                       "cells": []}


@pytest.mark.parametrize("roh, erwartet", [
    (8, 8), (0, 1), (-3, 1), (BENTO_SPALTEN_MAX + 5, BENTO_SPALTEN_MAX), (4.7, 4),
    ("8", BENTO_SPALTEN_STANDARD), (True, BENTO_SPALTEN_STANDARD), (float("nan"), BENTO_SPALTEN_STANDARD),
])
def test_spalten_werden_begrenzt(roh, erwartet):
    assert _bento_seite({"cols": roh}, PICKS)["cols"] == erwartet


def test_zeilen_werden_begrenzt():
    assert _bento_seite({"rows": BENTO_ZEILEN_MAX + 1}, PICKS)["rows"] == BENTO_ZEILEN_MAX


def test_format_nur_mit_beiden_massen():
    assert _bento_seite({"format": {"vw": 2560, "vh": 720}}, PICKS)["format"] == {"vw": 2560, "vh": 720}
    for fmt in ({"vw": 2560}, {"vw": 0, "vh": 720}, {"vw": "2560", "vh": 720}, [2560, 720]):
        assert "format" not in _bento_seite({"format": fmt}, PICKS)


@pytest.mark.parametrize("zelle", [
    z(-1, 0, widget="clock"), z(6, 0, widget="clock"), z(0, 2, widget="clock"),
    z(5, 0, 2, 1, widget="clock"), z(0, 1, 1, 2, widget="clock"), z(0, 0, 0, 1, widget="clock"),
    z(0, 0, 1, 0, widget="clock"), {"x": "0", "y": 0, "w": 1, "h": 1, "widget": "clock"},
    {"x": True, "y": 0, "w": 1, "h": 1, "widget": "clock"}, {"y": 0, "w": 1, "h": 1, "widget": "clock"},
    {"x": 0.5, "y": 0, "w": 1, "h": 1, "widget": "clock"}, "clock", None,
])
def test_zelle_ausserhalb_oder_kaputt_faellt_weg(zelle):
    assert zellen([zelle]) == []


def test_zelle_am_rand_bleibt():
    assert zellen([z(5, 1, widget="clock")]) == [z(5, 1, widget="clock")]
    assert zellen([z(0, 0, 6, 2, widget="clock")]) == [z(0, 0, 6, 2, widget="clock")]


def test_ueberlappung_die_spaetere_faellt_weg():
    oben = z(0, 0, 2, 2, widget="weather")
    trifft = z(1, 1, 2, 1, widget="calendar")
    daneben = z(2, 0, 1, 1, widget="calendar")
    assert zellen([oben, trifft, daneben]) == [oben, daneben]


def test_verworfene_zelle_blockiert_keine_felder():
    """Eine Zelle ohne gueltigen Inhalt belegt nichts: die naechste darf dorthin."""
    assert zellen([z(0, 0, widget="unbekannt"), z(0, 0, widget="clock")]) == [z(0, 0, widget="clock")]


def test_nie_mehr_zellen_als_felder():
    viele = [z(i % 6, i // 6 % 2, ids=["A"]) for i in range(10_000)]
    assert len(zellen(viele)) <= 12


# ---- Inhalt: Bausteine -------------------------------------------------------

def test_bausteine_nur_aus_picks_ohne_doppelte():
    assert zellen([z(0, 0, ids=["A", "X", "A", 3, "B"])]) == [z(0, 0, ids=["A", "B"])]


def test_zelle_ohne_baustein_aus_picks_faellt_weg():
    assert zellen([z(0, 0, ids=["X"])]) == []
    assert zellen([z(0, 0, ids="A")]) == []
    assert zellen([z(0, 0)]) == []


def test_baustein_steht_je_seite_einmal():
    assert zellen([z(0, 0, ids=["A", "B"]), z(1, 0, ids=["B", "C"]), z(2, 0, ids=["A"])]) == \
        [z(0, 0, ids=["A", "B"]), z(1, 0, ids=["C"])]


def test_baustein_einer_ueberlappenden_zelle_bleibt_frei():
    assert zellen([z(0, 0, ids=["A"]), z(0, 0, ids=["B"]), z(1, 0, ids=["B"])]) == \
        [z(0, 0, ids=["A"]), z(1, 0, ids=["B"])]


def test_bausteine_je_zelle_begrenzt():
    picks = [f"P{i}" for i in range(BENTO_ZELLE_BAUSTEINE_MAX + 3)]
    assert len(zellen([z(0, 0, ids=picks)], picks=picks)[0]["ids"]) == BENTO_ZELLE_BAUSTEINE_MAX


# ---- Inhalt: Widgets ---------------------------------------------------------

@pytest.mark.parametrize("widget", [
    "clock", "weather", "calendar", "player:Z1", "energy:E1", "camera:K1", "camera:K1|A,B",
    "chart:A,B", "status:A",
])
def test_widgets_wie_bei_den_panes_plus_uhr(widget):
    assert zellen([z(0, 0, widget=widget)]) == [z(0, 0, widget=widget)]


@pytest.mark.parametrize("widget", ["header", "header:A", "haus", "energy:", "chart:", "unbekannt", 3, None])
def test_kopfzeile_hausseite_und_unbekanntes_nicht(widget):
    assert zellen([z(0, 0, widget=widget)]) == []


def test_widget_geht_vor_bausteinen():
    assert zellen([z(0, 0, widget="clock", ids=["A"])]) == [z(0, 0, widget="clock")]


def test_uhr_wetter_kalender_einmal_quellen_mehrfach():
    roh = [z(0, 0, widget="clock"), z(1, 0, widget="clock"),
           z(2, 0, widget="energy:E1"), z(3, 0, widget="energy:E1"), z(4, 0, widget="energy:E2")]
    assert zellen(roh) == [z(0, 0, widget="clock"), z(2, 0, widget="energy:E1"), z(4, 0, widget="energy:E2")]


# ---- Webseite (iframe) ---------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://drucker.local/", "http://192.168.1.42:8080", "https://example.com/a?b=c#d",
    "HTTPS://example.com", "  https://example.com  ", "http://[fe80::1]:8080/",
])
def test_adresse_http_und_https(url):
    assert _clean_iframe_url(url) == url.strip()


@pytest.mark.parametrize("url", [
    "ftp://example.com", "javascript:alert(1)", "data:text/html,<b>x</b>", "file:///etc/passwd",
    "//example.com", "example.com", "https://", "http:///pfad", "https://user:pw@host/",
    "https://user@host/", "https://exa mple.com", "https://example.com/\nx", "https://example.com/\x7f",
    "http://host:99999/", "http://host:abc/", "https://" + "a" * BENTO_URL_MAX, "", None, 3, ["https://x"],
])
def test_andere_adressen_werden_verworfen(url):
    assert _clean_iframe_url(url) == ""


def test_webseite_mit_adresse_und_name():
    roh = z(0, 0, widget="iframe", url="https://drucker.local/", name="  " + "D" * (BENTO_NAME_MAX + 9))
    assert zellen([roh]) == [z(0, 0, widget="iframe", url="https://drucker.local/", name="D" * BENTO_NAME_MAX)]


def test_webseite_ohne_gueltige_adresse_faellt_weg_und_wird_protokolliert(caplog):
    with caplog.at_level(logging.WARNING, logger="loxpanel.bento"):
        assert zellen([z(0, 0, widget="iframe", url="ftp://x")]) == []
    assert "ftp://x" in caplog.text
    assert zellen([z(0, 0, widget="iframe")]) == []


def test_gleiche_adresse_einmal_andere_mehrfach():
    a = z(0, 0, widget="iframe", url="https://a.example/")
    assert zellen([a, {**a, "x": 1}, z(2, 0, widget="iframe", url="https://b.example/")]) == \
        [a, z(2, 0, widget="iframe", url="https://b.example/")]


def test_name_nur_bei_webseiten():
    assert zellen([z(0, 0, widget="clock", name="Uhr")]) == [z(0, 0, widget="clock")]


# ---- Speichern, Melden, Export -----------------------------------------------

def _profil(bento, picks=PICKS, **seite):
    return {"p": {"title": "Streifen", "tabs": ["auswahl"],
                  "pickTabs": [{"name": "Streifen", "picks": picks, "bento": bento, **seite}]}}


def test_speichern_behaelt_bento_neben_widget_und_layout():
    """Vorrang bento > widget > Kacheln entscheidet die Anzeige; gespeichert
    bleibt alles, damit ein Wechsel im Editor nichts verliert."""
    roh = _profil({"cols": 6, "rows": 2, "cells": [z(0, 0, widget="clock")]}, widget="weather",
                  layout=[{"id": "A", "w": 2, "h": 1}])
    seite = _sanitize_panels(roh)["p"]["pickTabs"][0]
    assert seite["bento"] == {"cols": 6, "rows": 2, "cells": [z(0, 0, widget="clock")]}
    assert seite["widget"] == "weather" and seite["layout"] == [{"id": "A", "w": 2, "h": 1}]


def test_seite_nur_mit_bento_wird_gespeichert():
    roh = {"p": {"title": "S", "pickTabs": [{"bento": {}}]}}
    assert _sanitize_panels(roh)["p"]["pickTabs"] == [{"name": "Auswahl", "picks": [],
                                                       "bento": {"cols": 6, "rows": 2, "cells": []}}]


def test_bausteine_der_zellen_folgen_den_picks():
    roh = _profil({"cells": [z(0, 0, ids=["A", "X"])]}, picks=["A"])
    assert _sanitize_panels(roh)["p"]["pickTabs"][0]["bento"]["cells"] == [z(0, 0, ids=["A"])]


def test_verworfene_zelle_wird_gemeldet():
    roh = _profil({"cols": 6, "rows": 2, "cells": [z(0, 0, widget="clock"),
                                                  z(1, 0, widget="iframe", url="ftp://x")]})
    weg = _panels_verworfen(roh, _sanitize_panels(roh))
    assert any("bento.cells" in t and "1 von 2" in t for t in weg), weg


def test_ungueltiges_format_wird_gemeldet():
    roh = _profil({"format": {"vw": 0, "vh": 720}})
    assert any("bento.format" in t for t in _panels_verworfen(roh, _sanitize_panels(roh)))


def test_speichern_ist_ein_fixpunkt():
    roh = _profil({"cols": 6, "rows": 2, "format": {"vw": 2560, "vh": 720},
                   "cells": [z(0, 0, 1, 2, widget="clock"), z(1, 0, 2, 1, ids=["A", "B"]),
                             z(3, 0, widget="iframe", url="https://drucker.local/", name="Drucker"),
                             z(1, 1, 2, 1, widget="camera:K1|A")]})
    einmal = _sanitize_panels(roh)
    assert _sanitize_panels(einmal) == einmal
    assert _panels_verworfen(roh, einmal) == []


def test_pick_tabs_prueft_auch_alte_dateien():
    """panels.json aus aelteren Staenden ist nie durch _sanitize_panels
    gelaufen: _pick_tabs (Visu und Export) prueft das Raster ebenso."""
    prof = {"pickTabs": [{"name": "S", "picks": ["A"],
                          "bento": {"cols": 99, "cells": [z(0, 0, widget="iframe", url="javascript:x"),
                                                          z(0, 0, ids=["A", "B"])]}}]}
    assert _pick_tabs(prof)[0]["bento"] == {"cols": BENTO_SPALTEN_MAX, "rows": BENTO_ZEILEN_STANDARD,
                                            "cells": [z(0, 0, ids=["A"])]}


def test_seite_ohne_bento_bleibt_wie_sie_war():
    prof = {"pickTabs": [{"name": "S", "picks": ["A"]}]}
    assert "bento" not in _pick_tabs(prof)[0]
    assert "bento" not in _sanitize_panels({"p": prof})["p"]["pickTabs"][0]


def test_grenzen_sind_konstanten_im_konfig_modul():
    """Regel 6: keine Zahl im Prueffluss, die nicht als Konstante benannt ist."""
    for name in ("BENTO_SPALTEN_MIN", "BENTO_SPALTEN_MAX", "BENTO_ZEILEN_MIN", "BENTO_ZEILEN_MAX",
                 "BENTO_ZELLE_BAUSTEINE_MAX", "BENTO_URL_MAX", "BENTO_NAME_MAX"):
        assert isinstance(getattr(konfig, name), int)


# ---- Vorschlag fuer die Startseite (Assistent Schritt 4) ----------------------------

VOLL = {"energy": "EF", "player": "AZ", "kalender": True}
FAVS = ["F1", "F2", "F3", "F4", "F5"]


def _felder(c):
    return {(c["x"] + i, c["y"] + j) for i in range(c["w"]) for j in range(c["h"])}


def _vorschlag(format_=None, quellen=VOLL, favoriten=FAVS):
    from bento_format import bento_vorschlag
    return bento_vorschlag(format_, dict(quellen), list(favoriten))


def test_vorschlag_volle_anlage():
    v = _vorschlag()
    b = v["bento"]
    assert (b["cols"], b["rows"]) == (BENTO_SPALTEN_STANDARD, BENTO_ZEILEN_STANDARD)
    widgets = [c["widget"] for c in b["cells"] if "widget" in c]
    assert widgets == ["clock", "weather", "player:AZ", "energy:EF", "calendar"]
    uhr = b["cells"][0]
    assert (uhr["x"], uhr["y"], uhr["w"], uhr["h"]) == (0, 0, 1, BENTO_ZEILEN_STANDARD)
    assert all((c["w"], c["h"]) == (2, 1) for c in b["cells"] if c.get("widget") in ("weather", "player:AZ", "energy:EF"))
    favs = [c for c in b["cells"] if "ids" in c]
    assert all((c["w"], c["h"]) == (1, 1) and len(c["ids"]) == 1 for c in favs)
    # die Favoriten in Reihenfolge, so viele wie frei sind (12 Felder - 2 - 2*3 - 1 = 3)
    assert [c["ids"][0] for c in favs] == FAVS[:3] == v["picks"]
    alle = [f for c in b["cells"] for f in _felder(c)]
    assert len(alle) == len(set(alle)) == 12     # nichts ueberlappt, alles im Raster, voll belegt
    assert all(0 <= x < b["cols"] and 0 <= y < b["rows"] for x, y in alle)


def test_vorschlag_mit_karger_anlage():
    v = _vorschlag(quellen={"energy": None, "player": None, "kalender": False}, favoriten=["F1"])
    assert [c.get("widget") or c["ids"] for c in v["bento"]["cells"]] == ["clock", "weather", ["F1"]]
    assert v["picks"] == ["F1"]


def test_vorschlag_ohne_quellen_gibt_den_platz_den_favoriten():
    voll = _vorschlag()["bento"]["cells"]
    karg = _vorschlag(quellen={"energy": None, "player": None, "kalender": False})["bento"]["cells"]
    assert sum("ids" in c for c in karg) == len(FAVS) and sum("ids" in c for c in voll) < len(FAVS)


def test_vorschlag_laesst_favoriten_der_widget_zellen_weg():
    v = _vorschlag(favoriten=["AZ", "F1", "EF", "F1"])
    assert v["picks"] == ["F1"]


@pytest.mark.parametrize("quellen,favs", [(VOLL, FAVS), ({"energy": None, "player": None, "kalender": False}, ["F1"]),
                                           (VOLL, [])])
def test_vorschlag_besteht_bento_seite(quellen, favs):
    v = _vorschlag(quellen=quellen, favoriten=favs)
    assert _bento_seite(v["bento"], v["picks"]) == v["bento"]


def test_vorschlag_ohne_format_nimmt_standard():
    from bento_format import BENTO_FORMAT_STANDARD
    assert _vorschlag()["bento"]["format"] == BENTO_FORMAT_STANDARD == {"vw": 2560, "vh": 720}
    assert _vorschlag({"vw": 1920, "vh": 480})["bento"]["format"] == {"vw": 1920, "vh": 480}

