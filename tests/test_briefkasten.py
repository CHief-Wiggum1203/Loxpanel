"""Briefkasten (MailBox): frueher nur "Post da"/"Paket da"/"Leer" als Anzeige.
Laut Loxone-Strukturdoku hat er die Befehle confirmMail, confirmPacket
(entnommen) und disableNotifications/{Sekunden} (0 hebt auf), die States
disableEndTime (Sekunden seit 1.1.2009 UTC) und notificationsDisabledInput und
den Unterbaustein Tracker mit dem Verlauf. Der Baustein kommt aus tests/lox.py
(briefkasten_baustein, State-Namen wie an einer echten Anlage)."""
import time
from datetime import datetime, timedelta

from lox import W, anlage, bloecke, briefkasten_baustein

from bausteine import sicherheit

VERLAUF = "16.10.2026 08:12 Post eingeworfen\n15.10.2026 17:40 Paket abgelegt"


def _app(**kw) -> W.App:
    control, states = briefkasten_baustein(**kw)
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"MB": control}))
    app.states = states
    return app


def _detail(**kw) -> dict:
    return _app(**kw).render({"view": "control", "id": "MB"})


def _zellen(v) -> list:
    return [(z.get("label"), (z.get("cmd") or {}).get("cmd") or z.get("nav"))
            for r in bloecke(v, "row") for z in r["cells"]]


def _lox_zeit(sekunden_ab_jetzt: int) -> int:
    return int(time.time()) - sicherheit.LOX_EPOCH_UTC + sekunden_ab_jetzt


def test_leer():
    v = _detail()
    assert v["anchor"] == "bottom"
    assert [b["text"] for b in bloecke(v, "big")] == ["Leer"] and "tone" not in bloecke(v, "big")[0]
    assert [b["text"] for b in bloecke(v, "head")] == ["Benachrichtigungen pausieren"]
    assert _zellen(v) == [("1 h", "disableNotifications/3600"), ("4 h", "disableNotifications/14400"),
                          ("24 h", "disableNotifications/86400")]
    assert not bloecke(v, "status")


def test_post_und_paket_entnehmen():
    v = _detail(post=1, paket=1)
    big = bloecke(v, "big")[0]
    assert (big["text"], big["tone"]) == ("Post und Paket", "good")
    assert _zellen(v)[:2] == [("Post entnommen", "confirmMail"), ("Paket entnommen", "confirmPacket")]
    assert all(z["cmd"]["uuid"] == "MB" for r in bloecke(v, "row") for z in r["cells"])


def test_nur_was_drin_ist():
    assert [z for z in _zellen(_detail(post=1)) if "entnommen" in z[0]] == [("Post entnommen", "confirmMail")]
    v = _detail(paket=1)
    assert bloecke(v, "big")[0]["text"] == "Paket da"
    assert [z for z in _zellen(v) if "entnommen" in z[0]] == [("Paket entnommen", "confirmPacket")]


def test_pause_laeuft():
    """disableEndTime in der Zukunft: die Seite sagt bis wann und bietet nur
    noch "Wieder an" (disableNotifications/0)."""
    v = _detail(pause_bis=_lox_zeit(2 * 3600))
    assert [b["text"].startswith("Benachrichtigungen pausiert bis ") for b in bloecke(v, "status")] == [True]
    assert [b["text"] for b in bloecke(v, "head")] == ["Benachrichtigungen"]
    assert _zellen(v) == [("Wieder an", "disableNotifications/0")]


def test_abgelaufene_pause_zaehlt_nicht():
    v = _detail(pause_bis=_lox_zeit(-60))
    assert not bloecke(v, "status")
    assert [b["text"] for b in bloecke(v, "head")] == ["Benachrichtigungen pausieren"]


def test_logik_setzt_aus():
    """notificationsDisabledInput: die Logik haelt die Benachrichtigungen an,
    das geht vor einer eigenen Pause."""
    v = _detail(logik_aus=1, pause_bis=_lox_zeit(3600))
    assert [b["text"] for b in bloecke(v, "status")] == ["Benachrichtigungen über die Logik ausgesetzt"]


def test_uhrzeit_text():
    jetzt = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    assert sicherheit._uhrzeit_text(jetzt.replace(hour=18, minute=5)) == "18:05"
    assert sicherheit._uhrzeit_text(jetzt + timedelta(days=1)) == "morgen 12:00"
    spaeter = jetzt + timedelta(days=3)
    assert sicherheit._uhrzeit_text(spaeter) == spaeter.strftime("%d.%m. 12:00")


def test_verlauf_aus_dem_tracker():
    """Der letzte Eintrag steht auf der Detailseite, alle auf der Unterseite
    Verlauf (eigene Route)."""
    app = _app(post=1, eintraege=VERLAUF)
    v = app.render({"view": "control", "id": "MB"})
    assert "Zuletzt: Post eingeworfen (16.10.2026 08:12)" in [b["text"] for b in bloecke(v, "status")]
    assert _zellen(v)[-1] == ("Verlauf", {"view": "verlauf", "id": "MB"})
    s = app.render({"view": "verlauf", "id": "MB"})
    assert (s["title"], s["layout"]) == ("Postkasten · Verlauf", "list")
    assert [(i["label"], i["sublabel"]) for i in s["items"]] == [
        ("Post eingeworfen", "16.10.2026 08:12"), ("Paket abgelegt", "15.10.2026 17:40")]


def test_verlauf_leer():
    app = _app(eintraege="")
    v = app.render({"view": "control", "id": "MB"})
    assert not [b for b in bloecke(v, "status") if b["text"].startswith("Zuletzt")]
    assert _zellen(v)[-1] == ("Verlauf", {"view": "verlauf", "id": "MB"})
    assert [b["text"] for b in bloecke(app.render({"view": "verlauf", "id": "MB"}), "status")] == ["Keine Einträge"]


def test_ohne_tracker_kein_verlauf():
    app = _app()
    assert ("Verlauf", {"view": "verlauf", "id": "MB"}) not in _zellen(app.render({"view": "control", "id": "MB"}))
    s = app.render({"view": "verlauf", "id": "MB"})
    assert [b["text"] for b in s["blocks"]] == ["Dieser Baustein hat keinen Verlauf."]


def test_kachel():
    it = _app(post=1)._control_item("MB")
    assert (it["icon"], it["sublabel"], it["on"]) == ("mail", "Post da", True)
    assert _app()._control_item("MB")["sublabel"] == "Leer"
