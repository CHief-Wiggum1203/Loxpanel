"""Uebersicht "Was ist eingestellt?" (LoxOS, docs/VISION.md, Stufe 2.5): Jeder
ui-Schluessel, den der Konfigurator bekommt (ansicht.PANEL_UI_EXPORT fuer die
Ansichten, konfig.THEME_UI_KEYS fuer die Vorgaben), hat in ABWEICHUNG_FELDER
(config/abweichungen.js) einen Namen und einen Reiter, sonst stuende er dort nur
mit seinem technischen Namen. Die Namen haben einen englischen Eintrag, und
ABWEICHUNG_BLEIBT nennt die Schluessel, die "Alles auf Standard" nicht anfasst."""
import re

import ansicht
import konfig
from lox import ROOT
from test_uebersetzung import _katalog_en

JS = (ROOT / "webfrontend" / "html" / "config" / "abweichungen.js").read_text(encoding="utf-8")
# Reiter, die der Editor kennt (PCONF_TABS bzw. VG_TABS in config/kern.js)
REITER_ANSICHT = {"allgemein", "inhalt", "seiten", "raster", "aussehen", "verhalten"}
REITER_VORGABEN = {"appearance", "catcolors", "verhalten"}


def _block(name: str) -> str:
    m = re.search(rf"const {name}\s*=\s*([{{\[].*?[}}\]]);", JS, re.S)
    assert m, f"{name} fehlt in abweichungen.js"
    return m.group(1)


def _felder() -> dict:
    """ABWEICHUNG_FELDER: Schluessel -> {name, reiter} (eine Zeile je Eintrag)."""
    return {k: {"name": n, "reiter": r} for k, n, r in
            re.findall(r"^\s*(\w+):\s*\{name:'([^']+)',\s*reiter:'(\w+)'\}", _block("ABWEICHUNG_FELDER"), re.M)}


def test_jedes_ui_feld_hat_einen_namen():
    felder = _felder()
    assert len(felder) > 20, felder
    fehlt = sorted(k for k in {*ansicht.PANEL_UI_EXPORT, *konfig.THEME_UI_KEYS} if k not in felder)
    assert fehlt == [], "ohne Eintrag in ABWEICHUNG_FELDER: " + ", ".join(fehlt)
    assert {f["reiter"] for f in felder.values()} <= REITER_ANSICHT
    zuordnung = dict(re.findall(r"(\w+):'(\w+)'", _block("ABWEICHUNG_REITER_VORGABEN")))
    assert set(zuordnung) == REITER_ANSICHT and set(zuordnung.values()) <= REITER_VORGABEN, zuordnung


def test_jeder_name_ist_uebersetzt():
    kat = _katalog_en()
    fehlt = sorted({f["name"] for f in _felder().values()} - set(kat))
    assert fehlt == [], "ohne englischen Eintrag in i18n.js: " + "; ".join(fehlt)


def test_bleibt_liste():
    bleibt = set(re.findall(r"'(\w+)'", _block("ABWEICHUNG_BLEIBT")))
    assert bleibt <= set(_felder()), bleibt - set(_felder())
    # Inhalt und Look: Widgets, Werteleiste, Audio-Zone und Energie-Baustein, Kachel-Set, Farbton
    assert {"panes", "svPane", "valueBar", "player", "hausEnergie",
            "tileSet", "tileHue", "tileHueEdge", "tileActive"} <= bleibt
