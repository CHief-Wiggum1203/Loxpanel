"""Die Bausteine der Visu (bin/bausteine/): je Familie ein Modul, das Kachel und
Detailseite je Typ in die Tabellen KACHEL und DETAIL eintraegt. Geprueft wird,
dass die Tabellen genau die Typen der frueheren elif-Ketten kennen (kein Typ
geht beim Umbau verloren, keiner kommt still dazu), dass ein Typ nicht doppelt
eingetragen werden kann, dass die Zentralbausteine ueber ihr Praefix laufen und
dass App._control_item()/_view_control_inner() fuer einen unbekannten Typ eine
Kachel liefern, die das sagt, bzw. die Einzelkachel-Seite."""
import inspect

import pytest

from lox import W, anlage

import bausteine  # noqa: E402  # bin/ liegt durch lox auf dem Pfad

# Typen der Kachel-Kette (Stand vor dem Umbau, 15.10.2026) und ihre Familie
KACHEL_TYPEN = {
    "licht": {"LightControllerV2", "LightController", "Dimmer", "EIBDimmer", "ColorPickerV2"},
    "schalten": {"Switch", "TimedSwitch", "Daytimer", "Pushbutton", "UpDownDigital", "Radio"},
    "beschattung": {"Jalousie", "Gate", "Window"},
    "klima": {"IRoomControllerV2", "IRoomController", "AcControl", "ClimateControllerUS", "Ventilation"},
    "audio": {"AudioZone", "AudioZoneV2"},
    "intercom": {"Intercom", "IntercomV2"},
    "werte": {"ValueSelector", "UpDownAnalog", "Slider", "TextInput", "InfoOnlyAnalog", "InfoOnlyDigital",
              "TextState", "InfoOnlyText", "Meter", "Hourcounter", "Tracker", "Webpage", "SystemScheme"},
    "sicherheit": {"Alarm", "SmokeAlarm", "PresenceDetector", "WindowMonitor", "MailBox"},
    "wecker": {"AlarmClock"},
    "energie": {"Fronius", "EFM", "EnergyManager2", "PvProductionForecast"},
    "garten": {"Irrigation"},
    "wellness": {"Sauna", "SteakThermo"},
}
# Typen ohne eigene Detailseite: Pushbutton und TimedSwitch schalten direkt,
# die Switch-Kachel auch; die Zentralbausteine oeffnen die Gruppe
NUR_KACHEL = {"Switch", "TimedSwitch", "Pushbutton"}
# Detailseiten ohne eigene Kachel: die Zentral-Jalousie (Kachel ueber das
# Praefix Central, die Seite mit den Zentralbefehlen in ihrer Familie)
NUR_DETAIL = {"CentralJalousie": "beschattung"}


def _app(controls: dict, states: dict | None = None):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage(controls))
    app.states = dict(states or {})
    return app


def test_tabellen_kennen_genau_die_typen_der_ketten():
    erwartet = {t for typen in KACHEL_TYPEN.values() for t in typen}
    assert set(bausteine.KACHEL) == erwartet
    assert set(bausteine.DETAIL) == (erwartet - NUR_KACHEL) | set(NUR_DETAIL)
    assert [p for p, _ in bausteine.KACHEL_PRAEFIX] == ["Central"]


@pytest.mark.parametrize("familie", sorted(KACHEL_TYPEN))
def test_jede_familie_traegt_ihre_typen(familie):
    for t in KACHEL_TYPEN[familie]:
        assert bausteine.KACHEL[t].__module__ == f"bausteine.{familie}", t
        if t not in NUR_KACHEL:
            assert bausteine.DETAIL[t].__module__ == f"bausteine.{familie}", t
    for t, fam in NUR_DETAIL.items():
        if fam == familie:
            assert bausteine.DETAIL[t].__module__ == f"bausteine.{familie}", t


def test_signaturen():
    for fn in bausteine.KACHEL.values():
        assert list(inspect.signature(fn).parameters) == ["app", "uuid", "c", "it"], fn.__name__
    for fn in bausteine.DETAIL.values():
        assert list(inspect.signature(fn).parameters) == ["app", "uuid", "c", "route"], fn.__name__
    for _, fn in bausteine.KACHEL_PRAEFIX:
        assert list(inspect.signature(fn).parameters) == ["app", "uuid", "c", "it"], fn.__name__


def test_doppelter_eintrag_ist_ein_fehler():
    with pytest.raises(RuntimeError, match="Kachel fuer Jalousie doppelt"):
        bausteine.kachel("Jalousie")(lambda app, uuid, c, it: None)
    with pytest.raises(RuntimeError, match="Detailseite fuer Jalousie doppelt"):
        bausteine.detail("Jalousie")(lambda app, uuid, c, route: None)
    with pytest.raises(RuntimeError, match="Praefix Central doppelt"):
        bausteine.kachel_praefix("Central")(lambda app, uuid, c, it: None)
    assert bausteine.KACHEL["Jalousie"].__module__ == "bausteine.beschattung"


def test_zentral_ueber_praefix_sonst_genau():
    assert bausteine.kachel_fuer("CentralLightController").__name__ == "kachel_zentralbaustein"
    assert bausteine.kachel_fuer("CentralIrgendwas").__name__ == "kachel_zentralbaustein"
    assert bausteine.kachel_fuer("Jalousie").__name__ == "kachel_jalousie"
    assert bausteine.kachel_fuer("Unbekannt") is None and bausteine.kachel_fuer(None) is None
    assert bausteine.detail_fuer("CentralLightController") is None   # Gruppe, keine Detailseite
    assert bausteine.detail_fuer("Jalousie").__name__ == "detail_jalousie"


def test_typen_uebersicht():
    typen = bausteine.typen()
    assert typen["Jalousie"] == {"modul": "beschattung", "kachel": True, "detail": True}
    assert typen["Pushbutton"] == {"modul": "schalten", "kachel": True}


def test_unbekannter_typ_sagt_es_und_bleibt_einzelseite():
    """Statt einer leeren Kachel "Typ nicht unterstuetzt" als beschreibende
    Zweitzeile (subInfo). /api/types fuehrt den Typ trotzdem als nicht
    unterstuetzt und die Kachel unter den toten; hide blendet sie aus."""
    app = _app({"X": {"name": "Neuer Baustein", "type": "GanzNeu", "uuidAction": "X", "room": "r1", "cat": "c1",
                      "isFavorite": True, "states": {}}})
    it = app._control_item("X")
    assert it["label"] == "Neuer Baustein" and it["icon"] == "info" and it["on"] is False
    assert "nav" not in it and "cmd" not in it and "controls" not in it
    assert it["sublabel"] == "Typ nicht unterstützt" and it["subInfo"] is True
    v = app._view_control_inner("X")
    assert v["title"] == "Neuer Baustein" and v["route"] == {"view": "control", "id": "X"}
    assert [e["id"] for e in v["items"]] == ["X"]
    uebersicht = app.types_overview()
    assert [(t["type"], t["status"]) for t in uebersicht["types"]] == [("GanzNeu", "none")]
    assert [d["uuid"] for d in uebersicht["unsupportedControls"]] == ["X"]
    for hide, ids in (([], ["X"]), (["X"], [])):
        app.panels = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["favoriten"], "hide": hide}})
        seite = app.render({"view": "tab", "tab": "favoriten"}, app.resolve_profile("p"))
        assert [i["id"] for i in seite["items"]] == ids


def test_bekannter_typ_ohne_zweitzeile_bleibt_unterstuetzt():
    """Nur Typen ohne Kachel-Funktion gelten als unbekannt: eine Kachel aus den
    Tabellen behaelt, was ihre Funktion setzt."""
    app = _app({"S": {"name": "Licht", "type": "Switch", "uuidAction": "S", "room": "r1", "cat": "c1",
                      "states": {"active": "s"}}}, {"s": 0})
    it = app._control_item("S")
    assert "unbekannt" not in it and it["sublabel"] != "Typ nicht unterstützt"
    assert [(t["type"], t["status"]) for t in app.types_overview()["types"]] == [("Switch", "full")]


def test_kachel_und_detail_laufen_ueber_die_tabellen():
    """Ein Schalter: Kachel mit cmd aus bausteine.schalten, ohne Detailseite die
    Einzelkachel-Seite; eine Jalousie: Detailseite aus bausteine.beschattung."""
    app = _app({"S": {"name": "Licht Flur", "type": "Switch", "uuidAction": "S", "room": "r1", "cat": "c1",
                      "states": {"active": "s"}},
                "J": {"name": "Jalousie Süd", "type": "Jalousie", "uuidAction": "J", "room": "r1", "cat": "c1",
                      "states": {"position": "p", "up": "u", "down": "d"}}},
               {"s": 1, "p": 0.4, "u": 0, "d": 0})
    it = app._control_item("S")
    assert it["on"] is True and it["cmd"]["uuid"] == "S"
    assert app._view_control_inner("S")["items"][0]["id"] == "S"
    v = app._view_control_inner("J")
    assert v["title"] == "Jalousie Süd" and any(b.get("k") == "row" for b in v["blocks"])
