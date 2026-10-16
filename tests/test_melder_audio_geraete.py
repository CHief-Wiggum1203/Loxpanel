"""Restliche Luecken nach der Loxone-Strukturdoku: Schalter, den die Logik
haelt (lockedOn), naechste Alarmstufe bei Alarmanlage (nextLevelAt) und
Rauchmelder (nextLevelDelay/Total), Praesenzmelder (seit, gesperrt,
Nachlaufzeit, Verlauf), Wecker (Schlummern, Bestaetigung), Audio-Zone Gen. 2
(Hinweise, Bluetooth, Durchsage) und die Geraeteeinstellungen am Touch &
Grill. Die Bausteine kommen aus tests/lox.py."""
import time

from lox import (W, alarmanlage_baustein, anlage, bloecke, haus_anlage, praesenz_baustein, rauchmelder_baustein,
                 steak_baustein, wecker_baustein)


def _app(controls: dict, states: dict) -> W.App:
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(controls))
    app.states = states
    return app


def _baustein(baustein, **kw) -> tuple[W.App, str]:
    control, states = baustein(**kw)
    return _app({control["uuidAction"]: control}, states), control["uuidAction"]


def _seite(baustein, **kw) -> dict:
    app, u = _baustein(baustein, **kw)
    return app.render({"view": "control", "id": u})


def _texte(v, k="status") -> list:
    return [b["text"] for b in bloecke(v, k)]


def _zellen(v) -> list:
    return [(z.get("label"), (z.get("cmd") or {}).get("cmd"), z.get("on")) for r in bloecke(v, "row")
            for z in r["cells"]]


# ---- Schalter --------------------------------------------------------------

def test_schalter_von_der_logik_gehalten():
    sw = {"name": "Pumpe", "type": "Switch", "uuidAction": "SW", "room": "r1", "cat": "c1",
          "states": {"active": "sw-a", "lockedOn": "sw-l"}}
    app = _app({"SW": sw}, {"sw-a": 1, "sw-l": 1})
    assert app._control_item("SW")["sublabel"] == "Ein (von der Logik gehalten)"
    app.states["sw-l"] = 0
    assert app._control_item("SW")["sublabel"] == "Ein"


# ---- Alarmstufen -----------------------------------------------------------

def test_alarmanlage_naechste_stufe():
    control, states = alarmanlage_baustein(armed=1, level=1)
    control["states"].update(nextLevel="al-nl", nextLevelAt="al-na")
    app = _app({"ALM": control}, {**states, "al-nl": 2, "al-na": int(time.time()) + 20})
    text = _texte(app.render({"view": "control", "id": "ALM"}))[0]
    assert text.startswith("Alarm ausgelöst · nächste Stufe (Akustisch) um ")


def test_rauchmelder_naechste_stufe():
    v = _seite(rauchmelder_baustein, level=1, alarmCause=1, nextLevel=2, nextLevelDelay=20, nextLevelDelayTotal=90)
    assert "Nächste Stufe (Akustisch) in 1 min 10 s" in _texte(v)
    assert not [t for t in _texte(_seite(rauchmelder_baustein, nextLevel=2, nextLevelDelayTotal=90))
                if t.startswith("Nächste")]


# ---- Praesenzmelder --------------------------------------------------------

def test_praesenz_seit_und_nachlaufzeit():
    v = _seite(praesenz_baustein)
    assert bloecke(v, "big")[0]["text"] == "Anwesend" and _texte(v)[0].startswith("seit ")
    zeit = bloecke(v, "stepper")[0]
    assert (zeit["label"], zeit["value"], zeit["fmt"], zeit["cmd"]["tmpl"]) == ("Nachlaufzeit", 300, "dauer",
                                                                                "time/{v}")


def test_praesenz_gesperrt_und_logik():
    v = _seite(praesenz_baustein, locked=1, infoText="Urlaub")
    assert "Gesperrt: Urlaub" in _texte(v) and bloecke(v, "big")[0]["text"] == "Anwesend"
    zeit = bloecke(_seite(praesenz_baustein, logik=True), "stepper")[0]
    assert "cmd" not in zeit and zeit["sub"] == "von der Logik vorgegeben"


def test_praesenz_verlauf():
    app, u = _baustein(praesenz_baustein, tracker=True)
    v = app.render({"view": "control", "id": u})
    assert bloecke(v, "row")[-1]["cells"] == [{"label": "Verlauf", "nav": {"view": "verlauf", "id": "PD"}}]
    assert [i["label"] for i in app.render({"view": "verlauf", "id": "PD"})["items"]] == ["Anwesend"]


# ---- Wecker ----------------------------------------------------------------

def test_wecker_schlummert():
    v = _seite(wecker_baustein, snoozeTime=240)
    assert "Schlummert noch 4 min" in _texte(v)
    assert ("Wecker aus", "dismiss", None) in _zellen(v)


def test_wecker_bestaetigung():
    v = _seite(wecker_baustein, confirmationNeeded=1)
    assert "Bitte bestätigen" in _texte(v) and ("Wecker aus", "dismiss", None) in _zellen(v)
    assert ("Wecker aus", "dismiss", None) not in _zellen(_seite(wecker_baustein))


# ---- Audio-Zone Gen. 2 -----------------------------------------------------

def _zone(**states):
    struktur, st = haus_anlage()
    az = struktur["controls"]["AZ"]
    az["states"].update({k: f"az-{k}" for k in states})
    return _app(struktur["controls"], {**st, **{f"az-{k}": v for k, v in states.items()}})


def test_zone_hinweise():
    v = _zone(serverState=0, clientState=2, isLocked=1).render({"view": "control", "id": "AZ"})
    assert _texte(v)[:2] == ["Audioserver offline", "Zone gesperrt"]
    v = _zone(serverState=2, clientState=-5).render({"view": "control", "id": "AZ"})
    assert _texte(v)[0] == "Lautsprecher startet neu"


def test_zone_bluetooth():
    app = _zone(bluetooth=1)
    assert ("Bluetooth", "bluetooth/0", True) in _zellen(app.render({"view": "control", "id": "AZ"}))
    app.controls["AZ"]["details"] = {"parameterConnections": 1 << 9}
    zelle = next(z for r in bloecke(app.render({"view": "control", "id": "AZ"}), "row") for z in r["cells"]
                 if z.get("label") == "Bluetooth")
    assert "cmd" not in zelle
    app.controls["AZ"]["details"] = {"disableFeature": 1 << 2}
    assert "Bluetooth" not in [z[0] for z in _zellen(app.render({"view": "control", "id": "AZ"}))]
    assert "Bluetooth" not in [z[0] for z in _zellen(_zone().render({"view": "control", "id": "AZ"}))]


def test_zone_durchsage():
    app = _zone()
    zelle = bloecke(app.render({"view": "control", "id": "AZ"}), "row")[-1]["cells"][-1]
    assert zelle == {"label": "Durchsage", "nav": {"view": "durchsage", "id": "AZ"}}
    s = app.render({"view": "durchsage", "id": "AZ"})
    assert bloecke(s, "field")[0]["name"] == "text"
    assert bloecke(s, "row")[0]["cells"][0]["form"] == {"uuid": "AZ", "tmpl": "tts/{text}"}
    assert _texte(app.render({"view": "durchsage", "id": "AB"})) == ["Diese Zone gibt es nicht mehr."]


# ---- Touch & Grill ---------------------------------------------------------

def test_grill_geraeteeinstellungen():
    control, states = steak_baustein()
    control["states"].update(displayBrightness="st-db", touchProtection="st-tp", displayAlwaysOnBat="st-ab",
                             displayAlwaysOnDc="st-ad")
    app = _app({"STK": control}, {**states, "st-db": 60, "st-tp": 1, "st-ab": 0, "st-ad": 1})
    v = app.render({"view": "control", "id": "STK"})
    hell = next(b for b in bloecke(v, "stepper") if b["label"] == "Display-Helligkeit")
    assert (hell["value"], hell["cmd"]["tmpl"]) == (60, "setDisplayBrightness/{v}")
    assert bloecke(v, "row")[-1]["cells"] == [
        {"label": "Tastensperre", "on": True, "cmd": {"uuid": "STK", "cmd": "setTouchProtection/0"}},
        {"label": "Display an (Akku)", "on": False, "cmd": {"uuid": "STK", "cmd": "setDisplayAlwaysOnBat/1"}},
        {"label": "Display an (Netz)", "on": True, "cmd": {"uuid": "STK", "cmd": "setDisplayAlwaysOnDc/0"}}]
    control["details"].update(isTouchProtectConnected=1, isBrightnessConnected=1)
    app._apply_structure(anlage({"STK": control}))
    v = app.render({"view": "control", "id": "STK"})
    assert "cmd" not in next(b for b in bloecke(v, "stepper") if b["label"] == "Display-Helligkeit")
    assert "cmd" not in bloecke(v, "row")[-1]["cells"][0]
    assert bloecke(v, "head")[-1]["text"] == "Gerät"
