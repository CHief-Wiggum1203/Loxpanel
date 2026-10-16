"""Beschattung (Jalousie): Die Kachel traegt Auf/Ab-Tasten mit denselben
Befehlen wie die Detailansicht. Im Stand starten sie die Fahrt, waehrend der
Fahrt halten beide an, und die fahrende Richtung zeigt Stop."""
import pytest

from lox import W, anlage, bloecke, jalousie_baustein

ROLLO = {"J": {"name": "Rollo Küche", "type": "Jalousie", "uuidAction": "J", "room": "r1", "cat": "c1",
               "states": {"position": "jp", "up": "ju", "down": "jd"}}}


def _app(**werte):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(ROLLO))
    app.states = {"jp": 0.4, "ju": 0, "jd": 0, **werte}
    return app


@pytest.mark.parametrize("werte, symbole, befehle, zeile", [
    ({}, ["triup", "tridown"], ["Up", "Down"], "40% zu"),
    ({"ju": 1}, ["stop", "tridown"], ["Stop", "Stop"], "▲ öffnet · 40% zu"),
    ({"jd": 1}, ["triup", "stop"], ["Stop", "Stop"], "▼ schließt · 40% zu"),
], ids=["stand", "faehrt-auf", "faehrt-ab"])
def test_kachel_wie_detailansicht(werte, symbole, befehle, zeile):
    app = _app(**werte)
    kachel = app._control_item("J")
    tasten = kachel["controls"]
    assert [t["icon"] for t in tasten] == symbole
    assert [t["cmd"] for t in tasten] == [{"uuid": "J", "cmd": b} for b in befehle]
    assert kachel["sublabel"] == zeile and kachel["nav"] == {"view": "control", "id": "J"}
    auf_ab = next(b for b in app._view_control_inner("J")["blocks"] if b.get("k") == "row")
    assert [z["cmd"] for z in auf_ab["cells"]] == [t["cmd"] for t in tasten], \
        "dieselben Befehle wie Auf/Ab in der Detailansicht"


# ---- Bedienung nach der Strukturdoku (jalousie_baustein in tests/lox.py) ----


def _seite(**kw) -> dict:
    control, states = jalousie_baustein(**kw)
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"JA": control}))
    app.states = states
    return app.render({"view": "control", "id": "JA"})


def _zellen(v) -> list:
    return [(z.get("label"), (z.get("cmd") or {}).get("cmd"), z.get("on"))
            for r in bloecke(v, "row") for z in r["cells"]]


def test_position_und_lamellen():
    regler = bloecke(_seite(), "slider")
    assert [(r["icon"], r["value"], r["cmd"]["tmpl"]) for r in regler] == [
        ("blind", 40, "manualPosition/{v}"), ("lamelle", 50, "manualLamelle/{v}")]


@pytest.mark.parametrize("animation", [1, 2, 4])
def test_ohne_lamellen_bei_rollladen_und_vorhang(animation):
    assert [r["icon"] for r in bloecke(_seite(animation=animation), "slider")] == ["blind"]


def test_automatik_umschalten():
    assert ("Automatik", "NoAuto", True) in _zellen(_seite())
    assert ("Automatik", "auto", False) in _zellen(_seite(autoActive=0))
    assert "Automatik" not in [z[0] for z in _zellen(_seite(automatik=False))]


@pytest.mark.parametrize("werte, text", [
    ({"locked": 1, "infoText": "Fenster offen"}, "Gesperrt: Fenster offen"),
    ({"safetyActive": 1, "infoText": "Wind"}, "Sicherheitsabschaltung: Wind"),
    ({"locked": 1, "safetyActive": 1}, "Gesperrt"),
    ({"deviceState": 1}, "Gerät offline"),
], ids=["gesperrt", "sicherheit", "sperre-geht-vor", "offline"])
def test_sperre_und_sicherheit(werte, text):
    v = _seite(**werte)
    assert text in [b["text"] for b in bloecke(v, "status")]
    control, states = jalousie_baustein(**werte)
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"JA": control}))
    app.states = states
    assert app._control_item("JA")["sublabel"].startswith(text.split(":")[0] + " · ")


def test_zentral_jalousie():
    ja, st = jalousie_baustein()
    zentral = {"name": "Alle Jalousien", "type": "CentralJalousie", "uuidAction": "ZJ", "room": "r1", "cat": "c1",
               "states": {}, "details": {"controls": [{"uuid": "JA", "id": 1}, {"uuid": "FEHLT", "id": 2}]}}
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"JA": ja, "ZJ": zentral}))
    app.states = st
    it = app._control_item("ZJ")
    assert it["nav"] == {"view": "control", "id": "ZJ"} and it["icon"] == "blind"
    assert [t["cmd"] for t in it["controls"]] == [{"uuid": "ZJ", "cmd": "FullUp"}, {"uuid": "ZJ", "cmd": "FullDown"}]
    v = app.render({"view": "control", "id": "ZJ"})
    assert [c[1] for c in _zellen(v)[:6]] == ["FullUp", "stop", "FullDown", "shade", "auto", "NoAuto"]
    einzeln = bloecke(v, "row")[-1]["cells"]
    assert einzeln == [{"label": "Raffstore Süd · 40% zu", "on": True, "nav": {"view": "control", "id": "JA"}}]
