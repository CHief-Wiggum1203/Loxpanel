"""Wecker (AlarmClock): frueher Anzeige, Schlummern und Aus. Laut
Loxone-Strukturdoku schreibt entryList/put/{entryID}/{name}/{alarmTime}/
{isActive}/{modes|daily} einen Eintrag (neu oder ueberschreibend),
entryList/delete/{entryID} loescht ihn. Die Betriebsarten 3..9 sind Montag bis
Sonntag; Eintraege mit nightLight kennen daily statt modes. Die Dauern setzen
setSnoozeDuration (60..1800 s laut Wissensdatenbank), setRingDuration und
setPrepDuration; Wecksound, Lautstaerke und Helligkeit gibt es nur mit Touch
Nightlight. Der Baustein kommt aus tests/lox.py (wecker_baustein)."""
import json
from datetime import datetime

import pytest

from lox import BETRIEBSARTEN, WECKZEITEN, W, anlage, bloecke, wecker_baustein


def _app(eintraege=None, details=None, **werte) -> W.App:
    control, states = wecker_baustein(eintraege, **werte)
    control["details"].update(details or {})
    app = W.App({"host": "", "port": 80})
    struktur = anlage({"WK": control})
    struktur["operatingModes"] = BETRIEBSARTEN
    app._apply_structure(struktur)
    app.states = states
    return app


def _seite(app: W.App, **route) -> dict:
    return app.render({"id": "WK", **route})


def test_liste_mit_schalter_und_bearbeiten():
    v = _seite(_app(), view="control")
    liste, = bloecke(v, "alarmlist")
    assert [(e["name"], e["hm"], e["active"], e["repeat"]) for e in liste["entries"]] == [
        ("Arbeit", "06:15", True, "Mo Di Mi Do Fr"), ("Nachtlicht", "07:00", False, "Täglich"),
        ("Wochenende", "08:30", False, "Sa So Feiertag")]
    assert [e["cmd"] for e in liste["entries"]] == [
        {"uuid": "WK", "cmd": "entryList/put/1/Arbeit/22500/0/3,4,5,6,7"},   # schaltet aus
        {"uuid": "WK", "cmd": "entryList/put/0/Nachtlicht/25200/1/1"},       # nightLight: daily
        {"uuid": "WK", "cmd": "entryList/put/2/Wochenende/30600/1/8,9,0"}]
    assert [e["nav"] for e in liste["entries"]] == [
        {"view": "alarmentry", "id": "WK", "entry": i} for i in ("1", "0", "2")]
    zeile, = bloecke(v, "row")
    assert [(c["label"], c["nav"]) for c in zeile["cells"]] == [
        ("Neue Weckzeit", {"view": "alarmentry", "id": "WK", "entry": ""}),
        ("Einstellungen", {"view": "alarmsettings", "id": "WK"})]


def test_name_wird_kodiert():
    app = _app({"5": {"name": "Anna / früh", "isActive": False, "alarmTime": 21600, "modes": [3]}})
    e, = bloecke(_seite(app, view="control"), "alarmlist")[0]["entries"]
    assert e["cmd"]["cmd"] == "entryList/put/5/Anna%20%2F%20fr%C3%BCh/21600/1/3"


def test_klingelt():
    zeilen = bloecke(_seite(_app(isAlarmActive=1), view="control"), "row")
    assert [[c["label"] for c in z["cells"]] for z in zeilen] == [
        ["Schlummer", "Wecker aus"], ["Neue Weckzeit", "Einstellungen"]]
    assert [c["cmd"]["cmd"] for c in zeilen[0]["cells"]] == ["snooze", "dismiss"]


def test_per_logik_ausgeschaltet():
    """Eingang DisA: alle Weckzeiten aus (State isEnabled 0)."""
    app = _app(isEnabled=0)
    assert app._control_item("WK")["sublabel"] == "Ausgeschaltet"
    assert [b["text"] for b in bloecke(_seite(app, view="control"), "astat")] == ["Ausgeschaltet"]
    assert _app(isEnabled=None)._control_item("WK")["sublabel"] != "Ausgeschaltet"   # alte Firmware


def test_bearbeiten():
    v = _seite(_app(), view="alarmentry", entry="1")
    assert bloecke(v, "field") == [{"k": "field", "name": "name", "label": "Name", "value": "Arbeit"}]
    assert bloecke(v, "timepick") == [{"k": "timepick", "name": "zeit", "value": 22500}]
    tage, = bloecke(v, "chips")
    assert tage["multi"] is True and tage["name"] == "tage"
    assert [(c["v"], c["label"], c["on"]) for c in tage["items"]] == [
        (3, "Mo", True), (4, "Di", True), (5, "Mi", True), (6, "Do", True), (7, "Fr", True),
        (8, "Sa", False), (9, "So", False), (0, "Feiertag", False), (1, "Urlaub", False)]
    loeschen, speichern = bloecke(v, "row")[0]["cells"]
    assert loeschen == {"label": "Löschen", "confirm": "Wirklich löschen?", "back": True,
                        "cmd": {"uuid": "WK", "cmd": "entryList/delete/1"}}
    assert speichern == {"label": "Speichern", "back": True,
                         "form": {"uuid": "WK", "tmpl": "entryList/put/1/{name}/{zeit}/1/{tage}"}}


def test_bearbeiten_behaelt_aus():
    v = _seite(_app(), view="alarmentry", entry="2")
    speichern = bloecke(v, "row")[0]["cells"][1]
    assert speichern["form"]["tmpl"] == "entryList/put/2/{name}/{zeit}/0/{tage}"
    assert [c["label"] for c in bloecke(v, "chips")[0]["items"] if c["on"]] == ["Sa", "So", "Feiertag"]


def test_bearbeiten_nachtlicht_einmalig_oder_taeglich():
    v = _seite(_app(), view="alarmentry", entry="0")
    assert bloecke(v, "chips") == [{"k": "chips", "name": "tage", "items": [
        {"v": 0, "label": "Einmalig", "on": False}, {"v": 1, "label": "Täglich", "on": True}]}]


def test_weitere_betriebsart_bleibt_waehlbar():
    """Hat ein Eintrag eine Betriebsart ausser den Wochentagen und 0..2, steht
    sie mit zur Wahl - sonst ginge sie beim Speichern verloren."""
    app = _app({"1": {"name": "x", "isActive": True, "alarmTime": 0, "modes": [3, 10, 42]}})
    tage, = bloecke(_seite(app, view="alarmentry", entry="1"), "chips")
    assert [(c["label"], c["on"]) for c in tage["items"]][7:] == [
        ("Feiertag", False), ("Urlaub", False), ("Arbeitstag", True), ("Betriebsart 42", True)]


def test_neue_weckzeit():
    vorher = datetime.now()
    v = _seite(_app(), view="alarmentry", entry="")
    nachher = datetime.now()
    assert bloecke(v, "title")[0]["text"] == "Neue Weckzeit"
    assert bloecke(v, "field")[0]["value"] == "Weckzeit"
    assert bloecke(v, "timepick")[0]["value"] in {t.hour * 3600 + t.minute * 60 for t in (vorher, nachher)}
    assert not any(c["on"] for c in bloecke(v, "chips")[0]["items"])
    speichern, = bloecke(v, "row")[0]["cells"]                     # nichts zu loeschen
    assert speichern["form"]["tmpl"] == "entryList/put/3/{name}/{zeit}/1/{tage}"   # erste freie ID, aktiv


def test_neue_weckzeit_nimmt_luecke():
    app = _app({"0": WECKZEITEN["0"], "2": WECKZEITEN["2"]})
    speichern, = bloecke(_seite(app, view="alarmentry", entry=""), "row")[0]["cells"]
    assert speichern["form"]["tmpl"].startswith("entryList/put/1/")


@pytest.mark.parametrize("entry", ["7", "x"])
def test_unbekannte_weckzeit(entry):
    v = _seite(_app(), view="alarmentry", entry=entry)
    assert [b["text"] for b in bloecke(v, "status")] == ["Diese Weckzeit gibt es nicht mehr."]


def test_liste_ohne_ids_nur_anzeigen():
    """Kaeme entryList als Liste, fehlten die echten IDs: dann nur anzeigen,
    sonst traefe ein Befehl womoeglich einen anderen Eintrag."""
    app = _app(entryList=json.dumps(list(WECKZEITEN.values())))
    v = _seite(app, view="control")
    eintraege = bloecke(v, "alarmlist")[0]["entries"]
    assert len(eintraege) == 3 and not any("cmd" in e or "nav" in e for e in eintraege)
    assert not bloecke(v, "row")
    assert bloecke(_seite(app, view="alarmentry", entry="1"), "status")
    assert bloecke(_seite(app, view="alarmentry", entry=""), "status")


def test_einstellungen():
    v = _seite(_app(), view="alarmsettings")
    assert bloecke(v, "stepper") == [
        {"k": "stepper", "label": "Schlummerdauer", "value": 540, "fmt": "dauer", "step": 60, "min": 60,
         "max": 1800, "cmd": {"uuid": "WK", "tmpl": "setSnoozeDuration/{v}"}},
        {"k": "stepper", "label": "Maximale Weckdauer", "value": 300, "fmt": "dauer", "step": 60, "min": 60,
         "cmd": {"uuid": "WK", "tmpl": "setRingDuration/{v}"}},
        {"k": "stepper", "label": "Vorweckzeit", "value": 900, "fmt": "dauer", "step": 60, "min": 0,
         "cmd": {"uuid": "WK", "tmpl": "setPrepDuration/{v}"}}]
    assert not bloecke(v, "head")                      # kein Touch Nightlight


def test_schlummerdauer_von_der_logik():
    st = bloecke(_seite(_app(details={"snoozeDurationConnected": True}), view="alarmsettings"), "stepper")[0]
    assert st["label"] == "Schlummerdauer" and "cmd" not in st and st["sub"] == "von der Logik vorgegeben"


NIGHTLIGHT = {"deviceState": 2,
              "deviceSettings": json.dumps({"beepUsed": True, "brightInactive": 0, "brightActive": 50}),
              "wakeAlarmSoundSettings": json.dumps({"sound": 2, "volume": 80, "isSloping": False})}
SOUNDS = {"wakeAlarmSounds": [{"id": 1, "name": "Tiefer 4-fach Piep"}, {"id": 2, "name": "Sirene"}]}


def test_einstellungen_touch_nightlight():
    v = _seite(_app(details=SOUNDS, **NIGHTLIGHT), view="alarmsettings")
    assert [b["text"] for b in bloecke(v, "head")] == ["Touch Nightlight"]
    zeile, = bloecke(v, "row")
    sound, sloping, beep = zeile["cells"]
    assert sound["label"] == "Wecksound: Sirene"
    assert [(m["label"], m["on"], m["cmd"]["cmd"]) for m in sound["menu"]] == [
        ("Tiefer 4-fach Piep", False, "setWakeAlarmSound/1"), ("Sirene", True, "setWakeAlarmSound/2")]
    assert (sloping["label"], sloping["on"], sloping["cmd"]["cmd"]) == ("Lauter werdend", False,
                                                                        "setWakeAlarmSlopingOn/1")
    assert (beep["label"], beep["on"], beep["cmd"]["cmd"]) == ("Signalton", True, "setBeepOn/0")
    assert [(s["label"], s["value"], s["min"], s["max"], s["cmd"]["tmpl"]) for s in bloecke(v, "stepper")[3:]] == [
        ("Lautstärke", 80, 5, 100, "setWakeAlarmVolume/{v}"),
        ("Helligkeit inaktiv", 0, 0, 100, "setBrightnessInactive/{v}"),
        ("Helligkeit aktiv", 50, 0, 100, "setBrightnessActive/{v}")]


def test_touch_nightlight_von_der_logik():
    fest = {"wakeAlarmSoundConnected": True, "wakeAlarmSlopingConnected": True,
            "wakeAlarmVolumeConnected": True, "brightActiveConnected": True}
    v = _seite(_app(details={**SOUNDS, **fest}, **NIGHTLIGHT), view="alarmsettings")
    assert [b["text"] for b in bloecke(v, "status")] == ["Wecksound: Sirene"]
    assert [c["label"] for c in bloecke(v, "row")[0]["cells"]] == ["Signalton"]
    st = {s["label"]: s for s in bloecke(v, "stepper")}
    assert "cmd" not in st["Lautstärke"] and "cmd" not in st["Helligkeit aktiv"]
    assert "cmd" in st["Helligkeit inaktiv"]


def test_status_voll():
    assert {t["type"]: t["status"] for t in _app().types_overview()["types"]}["AlarmClock"] == "full"
