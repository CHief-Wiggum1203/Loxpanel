"""Kachel-Set (ui.tileSet): ein fertiger Look statt der Farben aus der
Grundfarbe. Geprueft werden Speichern (nur bekannte Sets), das aufgeloeste
Profil (Name und Farben), der Vorrang vor der Grundfarbe, ausdruecklich
gewaehlte Zustandsfarben, die Auswahl fuer den Konfigurator und die Kontraste
jedes Sets mit denselben Massstaeben wie theme_colors.derive()."""
import pytest

from lox import W, anlage

import theme_colors as TC

STRUKTUR = anlage({"S": {"name": "Licht", "type": "Switch", "uuidAction": "S", "room": "r1", "cat": "c1",
                         "states": {"active": "s"}}})
SETS = sorted(TC.KACHEL_SETS)


def _app(ui: dict, states: dict | None = None):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    roh = {"title": "P", "tabs": ["favoriten"], "ui": ui}
    if states:
        roh["states"] = states
    app.panels = W.App._sanitize_panels({"p": roh})
    return app


def test_es_gibt_mindestens_ein_set():
    assert SETS, "theme_colors.KACHEL_SETS ist leer"


@pytest.mark.parametrize("wert, gespeichert", [
    *[(n, n) for n in SETS], ("", None), ("gibtsnicht", None), (True, None), (None, None),
])
def test_nur_bekannte_sets_werden_gespeichert(wert, gespeichert):
    ui = {"tileSet": wert} if wert is not None else {}
    e = W.App._sanitize_panels({"p": {"title": "P", "tabs": ["favoriten"], "ui": ui}})["p"]
    assert (e.get("ui") or {}).get("tileSet") == gespeichert


def test_unbekanntes_set_wird_gemeldet():
    roh = {"p": {"title": "P", "tabs": ["favoriten"], "ui": {"tileSet": "gibtsnicht"}}}
    assert W.App._panels_verworfen(roh, W.App._sanitize_panels(roh))


@pytest.mark.parametrize("name", SETS)
def test_profil_traegt_name_und_farben_des_sets(name):
    prof = _app({"tileSet": name}).resolve_profile("p")
    assert prof["tileSet"] == name
    for var, wert in TC.KACHEL_SETS[name]["farben"].items():
        assert prof["vars"][var] == wert, var


def test_ohne_set_bleibt_alles_wie_bisher():
    prof = _app({}).resolve_profile("p")
    assert prof["tileSet"] == ""
    assert "--kachel-an" not in prof["vars"]


@pytest.mark.parametrize("name", SETS)
def test_set_schlaegt_die_grundfarbe(name):
    prof = _app({"tileSet": name, "baseColor": "#3a6ea5"}).resolve_profile("p")
    assert prof["vars"]["--screen"] == TC.KACHEL_SETS[name]["farben"]["--screen"]


@pytest.mark.parametrize("name", SETS)
def test_ausdrueckliche_zustandsfarbe_gilt_auch_im_set(name):
    prof = _app({"tileSet": name}, {"active": "#00ff00"}).resolve_profile("p")
    assert prof["vars"]["--glow"] == "#00ff00"
    assert prof["vars"]["--on-rgb"] == "0,255,0"


@pytest.mark.parametrize("name", SETS)
def test_vorgabe_zustandsfarbe_ueberschreibt_das_set_nicht(name):
    """load_theme() fuellt states immer aus DEFAULT_THEME - diese Vorgabe ist
    keine Wahl und darf die Farben des Sets nicht ueberdecken."""
    prof = _app({"tileSet": name}, dict(W.DEFAULT_THEME["states"])).resolve_profile("p")
    assert prof["vars"]["--glow"] == TC.KACHEL_SETS[name]["farben"]["--glow"]


def test_auswahl_fuer_den_konfigurator():
    assert TC.kachel_set_liste() == [{"key": k, "label": e["label"]} for k, e in TC.KACHEL_SETS.items()]
    assert TC.kachel_set("gibtsnicht") is None and TC.kachel_set(None) is None


@pytest.mark.parametrize("name", SETS)
def test_kontraste_des_sets(name):
    v = TC.kachel_set(name)
    k = TC.kontrast
    flaechen = [v["--tile"], v["--kachel-an"], v["--taste"], v["--tabbar"]]
    assert k(v["--ink"], v["--screen"]) >= TC.AAA
    assert k(v["--ink"], v["--tabbar"]) >= TC.AAA
    for f in flaechen:
        assert k(v["--ink"], f) >= TC.AA, f
        assert k(v["--muted"], f) >= TC.AA, f
    for rolle in ("--glow", "--good", "--crit", "--cool", "--warn", "--accent"):
        for f in (v["--tile"], v["--kachel-an"]):
            assert k(v[rolle], f) >= TC.AA, (rolle, f)
    assert k(v["--crit-ink"], v["--crit-fill"]) >= TC.AAA
    assert k(v["--crit-muted"], v["--crit-fill"]) >= TC.AA
    assert k(v["--on-glow"], v["--glow"]) >= TC.AA
    assert k(v["--on-accent"], v["--accent"]) >= TC.AA
    assert TC.trennbar(v["--glow"], v["--good"])
    assert TC.trennbar(v["--glow"], v["--muted"]) and TC.trennbar(v["--good"], v["--muted"])
