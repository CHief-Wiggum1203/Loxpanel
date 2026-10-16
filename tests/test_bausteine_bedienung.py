"""Bedienung nach der Loxone-Strukturdoku fuer Bausteine, die bisher nur
anzeigten oder Befehle vermissen liessen: Rauchmelder (Revisionsmodus,
Probealarm, Quittieren, Sirene aus), Alarmanlage (Bewegungsmelder,
verzoegertes Scharfschalten), Grillthermometer (Ziele, Timer, Alarm
quittieren), Sauna (Feuchte, Lueftung, Sanduhr), Energiemanager
(Speicher-Parameter, Verbraucher) und Bewaesserung (Verlauf). Die Bausteine
kommen aus tests/lox.py, State-Namen wie in der Strukturdoku."""
import json
import time

from lox import (EM2_VERBRAUCHER, W, alarmanlage_baustein, anlage, bewaesserung_baustein, bloecke,
                 energiemanager_baustein, rauchmelder_baustein, sauna_baustein, steak_baustein)


def _app(baustein, **kw) -> tuple[W.App, str]:
    control, states = baustein(**kw)
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({control["uuidAction"]: control}))
    app.states = states
    return app, control["uuidAction"]


def _seite(baustein, **kw) -> dict:
    app, uuid = _app(baustein, **kw)
    return app.render({"view": "control", "id": uuid})


def _zellen(v) -> list:
    return [(z.get("label"), (z.get("cmd") or {}).get("cmd"), z.get("confirm"))
            for r in bloecke(v, "row") for z in r["cells"]]


def _texte(v, k="status") -> list:
    return [b["text"] for b in bloecke(v, k)]


# ---- Rauchmelder -----------------------------------------------------------

def test_rauchmelder_ruhe():
    v = _seite(rauchmelder_baustein)
    assert [(b["text"], b.get("tone")) for b in bloecke(v, "big")] == [("Alles ok", "good")]
    assert _texte(v) == ["Überwacht: Rauch, Wasser"]
    assert _texte(v, "head") == ["Revisionsmodus"]
    assert _zellen(v) == [("1 h", "servicemode/3600", "Melder aussetzen?"),
                          ("4 h", "servicemode/14400", "Melder aussetzen?"),
                          ("Ohne Ende", "servicemode/1", "Melder aussetzen?"),
                          ("Probealarm", "startDrill", "Alarm auslösen?")]


def test_rauchmelder_alarm_mit_ursache():
    v = _seite(rauchmelder_baustein, level=2, alarmCause=0x02, acousticAlarm=1)
    assert [(b["text"], b.get("tone")) for b in bloecke(v, "big")] == [("Hauptalarm: Wasser", "crit")]
    assert _zellen(v)[:2] == [("Sirene aus", "mute", None), ("Quittieren", "confirm", None)]
    app, _ = _app(rauchmelder_baustein, level=1, alarmCause=0x05)
    it = app._control_item("SM")
    assert (it["sublabel"], it["tone"]) == ("Voralarm: Rauch, Temperatur", "crit")


def test_rauchmelder_ohne_sirene_nur_quittieren():
    v = _seite(rauchmelder_baustein, level=2, alarmCause=1)
    assert ("Sirene aus", "mute", None) not in _zellen(v)
    assert ("Quittieren", "confirm", None) in _zellen(v)


def test_rauchmelder_revisionsmodus_laeuft():
    v = _seite(rauchmelder_baustein, timeServiceMode=5400)
    assert bloecke(v, "big")[0]["text"] == "Revisionsmodus" and "tone" not in bloecke(v, "big")[0]
    assert "Revisionsmodus noch 1 h 30 min" in _texte(v)
    assert _zellen(v) == [("Beenden", "servicemode/0", None)]
    assert "Revisionsmodus ohne Ende" in _texte(_seite(rauchmelder_baustein, timeServiceMode=99999))


def test_rauchmelder_probealarm_quittieren():
    v = _seite(rauchmelder_baustein, testAlarm=1)
    assert bloecke(v, "big")[0]["text"] == "Probealarm"
    assert ("Quittieren", "confirm", None) in _zellen(v)


# ---- Alarmanlage -----------------------------------------------------------

def test_alarmanlage_bewegungsmelder():
    v = _seite(alarmanlage_baustein)
    zelle = bloecke(v, "row")[-1]["cells"][0]
    assert (zelle["label"], zelle["on"], zelle["cmd"]["cmd"]) == ("Bewegungsmelder", True, "dismv/0")
    zelle = bloecke(_seite(alarmanlage_baustein, disabledMove=1), "row")[-1]["cells"][0]
    assert (zelle["on"], zelle["cmd"]["cmd"]) == (False, "dismv/1")


def test_alarmanlage_ohne_state_kein_bewegungsmelder():
    control, states = alarmanlage_baustein()
    del control["states"]["disabledMove"]
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"ALM": control}))
    app.states = states
    v = app.render({"view": "control", "id": "ALM"})
    assert "Bewegungsmelder" not in [c[0] for c in _zellen(v)]


def test_alarmanlage_wird_scharf():
    v = _seite(alarmanlage_baustein, armedAt=int(time.time()) + 30)
    assert _texte(v)[0].startswith("Wird scharf um ")
    assert _texte(_seite(alarmanlage_baustein, armedAt=int(time.time()) - 30)) == ["Bereit zum Scharfschalten"]


# ---- Grillthermometer ------------------------------------------------------

def test_grill_ziele_je_fuehler():
    v = _seite(steak_baustein)
    assert bloecke(v, "big")[0]["text"] == "82 °C"
    assert _texte(v)[:2] == ["Brisket: 82 °C", "Rind & Lamm: 48 °C"]
    ziele = [b for b in bloecke(v, "stepper") if b["label"].startswith("Ziel")]
    assert [(b["label"], b["value"], b["unit"], b["cmd"]["tmpl"]) for b in ziele] == [
        ("Ziel Brisket", 85.0, "°C", "setSensor/0/{v}/Brisket"),
        ("Ziel Rind & Lamm", 56.0, "°C", "setSensor/1/{v}/Rind%20%26%20Lamm")]


def test_grill_fuehler_nicht_eingesteckt():
    info = json.dumps([{"name": "Brisket", "connected": True, "target": 85},
                       {"name": "Fühler 2", "connected": False, "target": 60}])
    v = _seite(steak_baustein, sensorInfo=info)
    assert "Fühler 2: nicht eingesteckt" in _texte(v)
    assert [b["label"] for b in bloecke(v, "stepper") if b["label"].startswith("Ziel")] == ["Ziel Brisket"]


def test_grill_timer():
    v = _seite(steak_baustein)
    dauer = next(b for b in bloecke(v, "stepper") if b["label"] == "Dauer")
    assert (dauer["value"], dauer["fmt"], dauer["cmd"]["tmpl"]) == (300, "dauer", "setTimerDuration/{v}")
    assert ("Timer starten", "startTimer", None) in _zellen(v)
    v = _seite(steak_baustein, timerInfo=json.dumps({"active": True, "duration": 300}), timerRemaining=125)
    assert "Timer · noch 2 min 5 s" in _texte(v, "head")
    assert ("Timer stoppen", "stopTimer", None) in _zellen(v)
    assert not [b for b in bloecke(v, "stepper") if b["label"] == "Dauer"]


def test_grill_alarm_quittieren():
    alarme = json.dumps([{"text": "Zieltemperatur erreicht", "time": 0, "ringing": True}])
    v = _seite(steak_baustein, yellowAlarmActive=1, sensorAlarms=alarme)
    assert "Zieltemperatur erreicht" in _texte(v)
    assert ("Alarm quittieren", "quitAlarm", None) in _zellen(v)
    assert ("Alarm quittieren", "quitAlarm", None) not in _zellen(_seite(steak_baustein))


def test_grill_geraet_und_akku():
    v = _seite(steak_baustein, deviceState=1)
    assert "Gerät offline" in _texte(v) and "Akku 64 %" in _texte(v)
    assert "Akku 64 %" not in _texte(_seite(steak_baustein, powerMode=1))


# ---- Sauna -----------------------------------------------------------------

def test_sauna_feuchte_und_lueftung():
    v = _seite(sauna_baustein)
    feuchte = bloecke(v, "stepper")[0]
    assert (feuchte["label"], feuchte["value"], feuchte["cmd"]["tmpl"]) == ("Feuchte", 35.0, "humidity/{v}")
    assert ("Lüftung", "fanon", None) in _zellen(v)
    assert ("Lüftung", "fanoff", None) in _zellen(_seite(sauna_baustein, fan=1))
    assert not bloecke(_seite(sauna_baustein, verdampfer=False), "stepper")


def test_sauna_aus_ohne_luefter_taste():
    """fanon wirkt laut Strukturdoku nur bei aktiver Sauna."""
    assert "Lüftung" not in [z[0] for z in _zellen(_seite(sauna_baustein, active=0))]
    assert ("Lüftung", "fanoff", None) in _zellen(_seite(sauna_baustein, active=0, fan=1))


def test_sauna_sanduhr():
    v = _seite(sauna_baustein)
    assert ("Sanduhr 15 min", "starttimer", None) in _zellen(v)
    v = _seite(sauna_baustein, timer=420)
    assert "Sanduhr noch 7 min" in _texte(v)
    assert not [z for z in _zellen(v) if z[1] == "starttimer"]


# ---- Energiemanager --------------------------------------------------------

def test_energiemanager_speicher_parameter():
    v = _seite(energiemanager_baustein)
    st = {b["label"]: b for b in bloecke(v, "stepper")}
    assert (st["Reserve"]["value"], st["Reserve"]["cmd"]["tmpl"]) == (20.0, "setMinSoc/{v}")
    mx = st["Max. Speicherleistung"]
    assert (mx["value"], mx["unit"], mx["cmd"]["tmpl"]) == (5.0, "kW", "setMaxSpwr/{v}")


def test_energiemanager_gesperrte_parameter():
    v = _seite(energiemanager_baustein, MinSocLocked=True, MaxSpwrLocked=True)
    assert all("cmd" not in b and b["sub"] == "von der Logik vorgegeben" for b in bloecke(v, "stepper"))


def test_energiemanager_verbraucher():
    v = _seite(energiemanager_baustein)
    zellen = bloecke(v, "row")[-1]["cells"]
    assert [(z["label"], z["on"]) for z in zellen] == [("Wallbox: Ein 3,70 kW", True),
                                                        ("Heizstab: Aus (von Hand)", False)]
    assert [m["cmd"] for m in zellen[1]["menu"]] == [
        {"uuid": "EM", "cmd": "L2/activate"}, {"uuid": "EM", "cmd": "L2/deactivate"},
        {"uuid": "EM", "cmd": "L2/automatic"}]
    assert EM2_VERBRAUCHER[1]["uuid"] == "L2"


# ---- Bewaesserung ----------------------------------------------------------

def test_bewaesserung_verlauf():
    control, states = bewaesserung_baustein()
    control["subControls"] = {"BEW/t": {"name": "Verlauf", "type": "Tracker", "uuidAction": "BEW/t",
                                        "states": {"entries": "bew-t"}}}
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"BEW": control}))
    app.states = {**states, "bew-t": "16.10.2026 06:00 Rasen vorne 10 min"}
    v = app.render({"view": "control", "id": "BEW"})
    assert bloecke(v, "row")[-1]["cells"] == [{"label": "Verlauf", "nav": {"view": "verlauf", "id": "BEW"}}]
    s = app.render({"view": "verlauf", "id": "BEW"})
    assert [i["label"] for i in s["items"]] == ["Rasen vorne 10 min"]
    assert "Verlauf" not in [c[0] for c in _zellen(_seite(bewaesserung_baustein))]
