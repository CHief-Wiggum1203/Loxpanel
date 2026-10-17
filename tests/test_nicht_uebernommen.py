"""Stiller Verlust beim Speichern: was _sanitize_panels nicht uebernimmt,
meldet der Server (Antwort "verworfen", Konfigurator zeigt es an). Gemeldet
wird nur, was einen Inhalt hatte - leere Werte, Standardwerte und bloss
begrenzte Werte nicht."""
import asyncio
import json
import time

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from lox import konfig, ROOT, W, anlage


def _meldung(panels: dict, namen: dict | None = None) -> list[str]:
    return W.App._panels_verworfen(panels, W.App._sanitize_panels(panels), namen)


def test_unbekannt_und_ungueltig_wird_gemeldet():
    roh = {"wz": {"title": "Wohnzimmer", "tabs": ["favoriten", "quatsch"],
                  "ui": {"cols": "3", "neuOption": 5, "iconSize": 30},
                  "tiles": {"U1": {"bg": "#123456", "blinken": True}},
                  "pickTabs": [{"name": "Seite", "picks": ["U1"], "icon": "https://fremd.example/bild"}],
                  "zusatz": {"a": 1}}}
    assert sorted(_meldung(roh, {"U1": "Licht Küche"})) == sorted([
        "Wohnzimmer: tabs: quatsch",
        "Wohnzimmer: ui.cols",
        "Wohnzimmer: ui.neuOption",
        "Wohnzimmer: tiles.Licht Küche.blinken",
        "Wohnzimmer: pickTabs.1.icon",
        "Wohnzimmer: zusatz.a"])


def test_panel_mit_ungueltiger_id():
    assert _meldung({"_intern": {"tabs": ["favoriten"]}, "ok": {"tabs": ["favoriten"]}}) == ["Ansicht „_intern“"]


def test_leer_standard_und_begrenzt_ist_kein_verlust():
    roh = {"p": {"title": "  ", "tabs": ["favoriten"], "rooms": [], "hide": [], "picks": [],
                 "pickName": "", "roomCats": [], "states": {}, "tiles": {"U1": {"chartStyle": "trend"}},
                 "ui": {"split": True, "catFilter": False, "fill": False, "bold": False,
                        "iconSize": 200, "nudgeX": -99, "font": "x" * 300, "overlay": {}}}}
    assert _meldung(roh) == []


def test_beispielkonfiguration_und_zweiter_durchlauf():
    doc = json.loads((ROOT / "config" / "panels.json.example").read_text(encoding="utf-8"))
    roh = {k: v for k, v in (doc.get("panels") or doc).items() if not k.startswith("_")}
    assert roh and _meldung(roh) == []
    sauber = W.App._sanitize_panels(roh)
    assert _meldung(sauber) == []


def test_lange_liste_bleibt_schnell():
    """100.000 ausgeblendete Kacheln: der Abgleich ging frueher jede Angabe
    einzeln durch die ganze Liste (quadratisch, ~1 min Event-Loop blockiert),
    eine Sicherung mit so einer Liste legte den Server lahm."""
    hide = [f"U{i:06d}" for i in range(100_000)]
    beginn = time.perf_counter()
    meldung = _meldung({"p": {"title": "Flur", "hide": hide + [5, "U000001"]}})
    dauer = time.perf_counter() - beginn
    assert meldung == ["Flur: hide: 5"]
    assert dauer < 5, f"{dauer:.1f} s"


def test_speichern_antwortet_mit_verworfen():
    """/api/panels speichert das Uebernommene und nennt den Rest; die Datei
    schreibt hier ein Stellvertreter (kein Test darf config/ veraendern)."""
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage({"U1": {"name": "Licht Küche", "type": "Switch", "uuidAction": "U1",
                                            "room": "r1", "cat": "c1", "states": {"active": "s1"}}}))
        geschrieben = []
        app._write_panels = geschrieben.append
        ui = web.Application()
        ui["app"] = app
        ui.router.add_post("/api/panels", W.api_save_panels)
        async with TestClient(TestServer(ui)) as cl:
            r = await cl.post("/api/panels", json={"panels": {
                "wz": {"title": "Wohnzimmer", "tabs": ["favoriten"], "ui": {"neuOption": 1},
                       "tiles": {"U1": {"bold": True, "blinken": True}}}}})
            j = await r.json()
        assert j["ok"] is True and j["count"] == 1
        assert j["verworfen"] == ["Wohnzimmer: ui.neuOption", "Wohnzimmer: tiles.Licht Küche.blinken"]
        assert geschrieben == [{"wz": {"title": "Wohnzimmer", "tabs": ["favoriten"], "rooms": [], "cats": [],
                                       "tiles": {"U1": {"bold": True}}}}]
    asyncio.run(lauf())


def test_speichern_antwortet_mit_dem_gespeicherten_stand(cfg_ordner):
    """Die Antwort nennt unter `panels`, was jetzt in der Datei steht, in der Form
    von /api/meta: ohne das Verworfene und normiert. Das fuehrt der Konfigurator als
    gespeicherten Stand; ein spaeteres "Ansicht loeschen" baut darauf auf."""
    async def lauf():
        app = W.App({"host": "", "port": 80})
        app._apply_structure(anlage({"U1": {"name": "Licht Küche", "type": "Switch", "uuidAction": "U1",
                                            "room": "r1", "cat": "c1", "states": {"active": "s1"}}}))
        ui = web.Application()
        ui["app"] = app
        ui.router.add_post("/api/panels", W.api_save_panels)
        async with TestClient(TestServer(ui)) as cl:
            r = await cl.post("/api/panels", json={"panels": {
                "wz": {"title": "Wohnzimmer", "tabs": ["favoriten", "quatsch"], "ui": {"neuOption": 1},
                       "tiles": {"U1": {"bold": True, "blinken": True}}}}})
            j = await r.json()
        assert j["ok"] is True
        assert j["panels"] == {pid: app._panel_export(raw) for pid, raw in app.panels.items()}
        wz = j["panels"]["wz"]
        assert wz["title"] == "Wohnzimmer" and wz["tabs"] == ["favoriten"]
        assert "neuOption" not in wz.get("ui", {}) and wz["tiles"] == {"U1": {"bold": True}}
        doc = json.loads((cfg_ordner / "panels.json").read_text(encoding="utf-8"))
        assert sorted(doc["panels"]) == sorted(j["panels"])
    asyncio.run(lauf())


def test_zustandsfarben_nur_gueltige():
    """Zustandsfarben einer Ansicht landen als CSS-Variablen im Panel (--glow,
    --good ...). Was keine Farbe ist, uebernimmt der Server nicht und meldet es."""
    roh = {"wz": {"title": "Wohnzimmer", "tabs": ["favoriten"],
                  "states": {"active": " #e0a24d ", "good": "rgb(1,2,3)",
                             "warn": "red;}body{display:none", "crit": 5}}}
    p = W.App._sanitize_panels(roh)["wz"]
    assert p["states"] == {"active": "#e0a24d", "good": "rgb(1,2,3)"}
    assert sorted(_meldung(roh)) == ["Wohnzimmer: states.crit", "Wohnzimmer: states.warn"]


SEITEN_ICONS_GUT = ["/icon?p=IconsFilled%2Flight.svg", "/loxlib?n=lampe.svg", "IconsFilled/light.svg",
                    "Icons/bild.png"]
SEITEN_ICONS_FREMD = ["//fremd.example/x.png", "https://fremd.example/x.png", "/fremd/x.svg",
                      "../x.svg", "IconsFilled/../x.svg", "javascript:x.svg", "\\\\fremd.example\\x.png",
                      "IconsFilled/light"]


def test_seiten_icon_nur_eigene_adressen():
    """Icon einer freien Seite: was die Icon-Auswahl schreibt (/icon?, /loxlib?)
    oder ein Loxone-Pfad. "//fremd..." faengt mit "/" an und lud das Bild frueher
    vom fremden Host."""
    for ic in SEITEN_ICONS_GUT:
        assert konfig._clean_seiten_icon(ic) == ic, ic
    for ic in SEITEN_ICONS_FREMD:
        assert konfig._clean_seiten_icon(ic) == "", ic
    roh = {"wz": {"title": "Wohnzimmer", "tabs": ["auswahl"],
                  "pickTabs": [{"name": "Seite", "picks": ["U1"], "icon": "//fremd.example/x.png"}]}}
    assert "icon" not in W.App._sanitize_panels(roh)["wz"]["pickTabs"][0]
    assert _meldung(roh) == ["Wohnzimmer: pickTabs.1.icon"]


def test_seiten_icon_aus_aelterer_datei():
    """panels.json wird beim Laden nicht sanitisiert: eine fremde Adresse aus
    einem aelteren Stand erreicht weder die Tab-Leiste noch den Konfigurator."""
    app = W.App({"host": "", "port": 80})
    for ic in SEITEN_ICONS_FREMD:
        prof = {"tabs": ["auswahl"], "pickTabs": [{"name": "Seite", "picks": [], "icon": ic}]}
        assert konfig._pick_tabs(prof)[0]["icon"] == "", ic
        assert app._tab_meta(["auswahl"], prof)["auswahl"]["iconUrl"] == "", ic
    prof = {"tabs": ["auswahl"], "pickTabs": [{"name": "Seite", "picks": [], "icon": "IconsFilled/light.svg"}]}
    assert app._tab_meta(["auswahl"], prof)["auswahl"]["iconUrl"] == "/icon?p=IconsFilled/light.svg"


def test_kachel_icon_nur_angebotene_quellen():
    """Google- und eigene Icons (/gicon, /uicon) hat der Server nie ausgeliefert
    und der Kachel-Editor nie angeboten: der Server nimmt sie nicht an, und eine
    von Hand geschriebene Angabe erzeugt keine Adresse ins Leere."""
    roh = {"wz": {"title": "Wohnzimmer", "tabs": ["favoriten"],
                  "tiles": {"U1": {"icon": {"src": "google", "name": "lightbulb"}},
                            "U2": {"icon": {"src": "custom", "file": "lampe.png"}},
                            "U3": {"icon": {"src": "loxlib", "name": "lampe.svg"}}}}}
    p = W.App._sanitize_panels(roh)["wz"]
    assert p["tiles"] == {"U3": {"icon": {"src": "loxlib", "name": "lampe.svg"}}}
    assert sorted(_meldung(roh)) == ["Wohnzimmer: tiles.U1.icon.name", "Wohnzimmer: tiles.U1.icon.src",
                                     "Wohnzimmer: tiles.U2.icon.file", "Wohnzimmer: tiles.U2.icon.src"]
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({u: {"name": f"Licht {u}", "type": "Switch", "uuidAction": u, "room": "r1",
                                     "cat": "c1", "states": {"active": f"s{u}"}} for u in ("U1", "U2", "U3")}))
    kacheln = {u: app._control_item(u, roh["wz"]) for u in ("U1", "U2", "U3")}
    for u in ("U1", "U2"):
        assert "gicon" not in str(kacheln[u]) and "uicon" not in str(kacheln[u]) and "iconImg" not in kacheln[u]
    assert kacheln["U3"]["iconUrl"] == "/loxlib?n=lampe.svg"
