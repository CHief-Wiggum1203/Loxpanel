"""Kachel-Set (ui.tileSet): ein fertiger Look statt der Farben aus der
Grundfarbe. Geprueft werden Speichern (nur bekannte Sets, Farbton und aktive
Kachel des Sets mit Rechnung), das aufgeloeste Profil (Name, Art, Farben und
Masse), der Vorrang vor der Grundfarbe und dem klassischen Aufbau,
ausdruecklich gewaehlte Zustandsfarben, die Auswahl fuer den Konfigurator
und die Kontraste jedes Sets mit denselben Massstaeben wie
theme_colors.derive() - fuer jedes Set mit Rechnung ("touch", "edge") ueber
alle Farbtoene in 5er-Schritten und jede Art der aktiven Kachel. Was geprueft wird, haengt an der Art des
Sets (Aufbau, Leiste), so wie panel.html die Farben aufeinander setzt."""
import pytest

from lox import anlage, konfig, W

import theme_colors as TC

STRUKTUR = anlage({"S": {"name": "Licht", "type": "Switch", "uuidAction": "S", "room": "r1", "cat": "c1",
                         "states": {"active": "s"}}})
SETS = sorted(TC.KACHEL_SETS)
MIT_SATZ = sorted(n for n, e in TC.KACHEL_SETS.items() if "satz" in e)
AKTIV = {n: [a["key"] for a in TC.KACHEL_SETS[n]["aktiv"]["auswahl"]] for n in MIT_SATZ if "aktiv" in TC.KACHEL_SETS[n]}
# Speichern und Profil laufen ueber ui.tileHue; den Schluessel weiterer Sets
# (tileHueEdge) schaltet der Sanitizer noch nicht frei
MIT_TILEHUE = [n for n in MIT_SATZ if TC.KACHEL_SETS[n]["farbton"]["schluessel"] == "tileHue"]


def _app(ui: dict, states: dict | None = None):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    roh = {"title": "P", "tabs": ["favoriten"], "ui": ui}
    if states:
        roh["states"] = states
    app.panels = W.App._sanitize_panels({"p": roh})
    return app


def _gespeichert(ui: dict) -> dict:
    return W.App._sanitize_panels({"p": {"title": "P", "tabs": ["favoriten"], "ui": ui}})["p"].get("ui") or {}


def test_es_gibt_die_drei_arten():
    assert SETS, "theme_colors.KACHEL_SETS ist leer"
    arten = {TC.kachel_set_art(n) for n in SETS}
    assert {a for a, _ in arten} <= {"lx", "mitte", "kreis"} and {lei for _, lei in arten} <= {"pille", "oben", "links"}
    assert TC.kachel_set_art("gibtsnicht") == ("", "") and TC.kachel_set_art(None) == ("", "")


@pytest.mark.parametrize("wert, gespeichert", [
    *[(n, n) for n in SETS], ("", None), ("gibtsnicht", None), (True, None), (None, None),
])
def test_nur_bekannte_sets_werden_gespeichert(wert, gespeichert):
    ui = {"tileSet": wert} if wert is not None else {}
    assert _gespeichert(ui).get("tileSet") == gespeichert


def test_unbekanntes_set_wird_gemeldet():
    roh = {"p": {"title": "P", "tabs": ["favoriten"], "ui": {"tileSet": "gibtsnicht"}}}
    assert W.App._panels_verworfen(roh, W.App._sanitize_panels(roh))


@pytest.mark.parametrize("name", MIT_TILEHUE)
def test_farbton_und_aktive_kachel_speichern(name):
    e = TC.KACHEL_SETS[name]
    hue = e["farbton"]["schluessel"]
    std_ton, std_aktiv = e["farbton"]["standard"], e["aktiv"]["standard"]
    anders = next(k for k in AKTIV[name] if k != std_aktiv)
    ton = next(f["wert"] for f in e["farbton"]["auswahl"] if f["wert"] != std_ton)
    assert _gespeichert({"tileSet": name, hue: ton, "tileActive": anders}) == \
        {"tileSet": name, hue: ton, "tileActive": anders}
    assert _gespeichert({"tileSet": name, hue: 12.7}) == {"tileSet": name, hue: 12}
    # der Standard wird nicht gespeichert und ist kein Verlust
    roh = {"p": {"title": "P", "tabs": ["favoriten"], "ui": {"tileSet": name, hue: std_ton, "tileActive": std_aktiv}}}
    assert W.App._sanitize_panels(roh)["p"]["ui"] == {"tileSet": name}
    assert W.App._panels_verworfen(roh, W.App._sanitize_panels(roh)) == []
    # Ungueltiges faellt weg und wird gemeldet
    for falsch in ({hue: 360}, {hue: -1}, {hue: "rot"}, {hue: True}, {"tileActive": "grell"}):
        roh = {"p": {"title": "P", "tabs": ["favoriten"], "ui": {"tileSet": name, **falsch}}}
        assert W.App._sanitize_panels(roh)["p"]["ui"] == {"tileSet": name}, falsch
        assert W.App._panels_verworfen(roh, W.App._sanitize_panels(roh)), falsch


@pytest.mark.parametrize("name", SETS)
def test_profil_traegt_name_art_und_werte_des_sets(name):
    prof = _app({"tileSet": name}).resolve_profile("p")
    assert (prof["tileSet"], prof["tileSetAufbau"], prof["tileSetLeiste"]) == (name, *TC.kachel_set_art(name))
    for var, wert in TC.kachel_set(name).items():
        assert prof["vars"][var] == wert, var
    # feste Farben und Masse aus der Definition kommen unveraendert an
    for var, wert in {**TC.KACHEL_SETS[name].get("farben", {}), **TC.KACHEL_SETS[name].get("masse", {})}.items():
        assert prof["vars"][var] == wert, var


@pytest.mark.parametrize("name", MIT_TILEHUE)
def test_farbton_wirkt_im_profil(name):
    e = TC.KACHEL_SETS[name]
    anders = next(k for k in AKTIV[name] if k != e["aktiv"]["standard"])
    ton = next(f["wert"] for f in e["farbton"]["auswahl"] if f["wert"] != e["farbton"]["standard"])
    std = _app({"tileSet": name}).resolve_profile("p")["vars"]
    mit = _app({"tileSet": name, e["farbton"]["schluessel"]: ton, "tileActive": anders}).resolve_profile("p")["vars"]
    assert std["--tile"] == TC.kachel_set(name)["--tile"]
    assert mit["--tile"] == TC.kachel_set(name, ton)["--tile"] != std["--tile"]
    assert mit["--kachel-an"] == TC.kachel_set(name, ton, anders)["--kachel-an"] != TC.kachel_set(name, ton)["--kachel-an"]


def test_ohne_set_bleibt_alles_wie_bisher():
    prof = _app({}).resolve_profile("p")
    assert (prof["tileSet"], prof["tileSetAufbau"], prof["tileSetLeiste"]) == ("", "", "")
    assert "--kachel-an" not in prof["vars"] and "--kachel-radius" not in prof["vars"]


@pytest.mark.parametrize("name", SETS)
def test_set_schlaegt_die_grundfarbe_und_den_klassischen_aufbau(name):
    prof = _app({"tileSet": name, "baseColor": "#3a6ea5", "tileLayout": "classic"}).resolve_profile("p")
    assert prof["vars"]["--screen"] == TC.kachel_set(name)["--screen"]
    assert prof["tileLayout"] == "", "das Set bringt seinen eigenen Aufbau mit"
    std = {**konfig.GROESSEN_STANDARD["neu"], **(TC.KACHEL_SETS[name].get("groessen") or {})}
    assert prof["vars"]["--name-size"] == f"{std['nameSize']}px", "Groessen des neuen Aufbaus (und des Sets)"


@pytest.mark.parametrize("name", SETS)
def test_ausdrueckliche_zustandsfarbe_gilt_auch_im_set(name):
    prof = _app({"tileSet": name}, {"active": "#00ff00"}).resolve_profile("p")
    assert prof["vars"]["--glow"] == "#00ff00"
    assert prof["vars"]["--on-rgb"] == "0,255,0"


@pytest.mark.parametrize("name", SETS)
def test_vorgabe_zustandsfarbe_ueberschreibt_das_set_nicht(name):
    """load_theme() fuellt states immer aus DEFAULT_THEME - diese Vorgabe ist
    keine Wahl und darf die Farben des Sets nicht ueberdecken."""
    prof = _app({"tileSet": name}, dict(konfig.DEFAULT_THEME["states"])).resolve_profile("p")
    assert prof["vars"]["--glow"] == TC.kachel_set(name)["--glow"]


def test_auswahl_fuer_den_konfigurator():
    liste = TC.kachel_set_liste()
    assert [(s["key"], s["label"], s["info"], s["aufbau"], s["leiste"], s["masse"], s["groessen"]) for s in liste] == \
        [(k, e["label"], e["info"], e["aufbau"], e["leiste"], e.get("masse", {}), e.get("groessen", {}))
         for k, e in TC.KACHEL_SETS.items()]
    for s in liste:
        e = TC.KACHEL_SETS[s["key"]]
        assert ("farbton" in s) == ("satz" in e) and ("aktiv" in s) == ("aktiv" in e)
        if "satz" not in e:
            continue
        aktiv = e["aktiv"]["standard"] if "aktiv" in e else None
        f = e["farbton"]
        assert s["farbton"]["schluessel"] == f["schluessel"] and s["farbton"]["standard"] == f["standard"]
        assert s["farbton"].get("regler") == f.get("regler") and s.get("aktiv") == e.get("aktiv")
        # die Farben rechnet der Server, der Konfigurator zeigt sie nur
        assert [(a["label"], a["wert"], a["farbe"]) for a in s["farbton"]["auswahl"]] == \
            [(a["label"], a["wert"], TC.satz_farben(s["key"], a["wert"], aktiv)["--tile"]) for a in f["auswahl"]]
        assert s["farbton"]["verlauf"] == \
            [TC.satz_farben(s["key"], h, aktiv)["--tile"] for h in range(0, 360, TC.VERLAUF_SCHRITT)]
    # touch: die Farben sind genau die von touch_satz()
    t = next(s for s in liste if s["key"] == "touch")
    hell = TC.KACHEL_SETS["touch"]["aktiv"]["standard"] == "hell"
    assert [f["farbe"] for f in t["farbton"]["auswahl"]] == \
        [TC.touch_satz(f["wert"], hell)["--tile"] for f in TC.KACHEL_SETS["touch"]["farbton"]["auswahl"]]
    assert t["farbton"]["verlauf"] == [TC.touch_satz(h, hell)["--tile"] for h in range(0, 360, TC.VERLAUF_SCHRITT)]
    assert TC.kachel_set("gibtsnicht") is None and TC.kachel_set(None) is None


def test_meta_nennt_die_sets():
    """/api/meta bringt dem Konfigurator die Kachel-Sets mit, wie theme_colors
    sie fuehrt (kachelSets); er rechnet sie nicht selbst nach."""
    import asyncio
    import json

    from aiohttp.test_utils import make_mocked_request
    m = json.loads(asyncio.run(W.api_meta(make_mocked_request("GET", "/api/meta", app={"app": _app({})}))).body)
    assert m["kachelSets"] == TC.kachel_set_liste()


@pytest.mark.parametrize("name", SETS)
def test_masse_sind_css_werte(name):
    """Masse gehen als CSS-Variablen an die Visu und als Zahl in die
    Rasterrechnung des Konfigurators (raster.js setMass): Laengen in px, ein
    Mass mit "-schmal" nur zu einem ohne."""
    masse = TC.KACHEL_SETS[name].get("masse") or {}
    for k, v in masse.items():
        assert k.startswith("--") and isinstance(v, str), (k, v)
        if k.endswith("-schmal"):
            assert k[:-len("-schmal")] in masse, k
        if k not in ("--kachel-schatten", "--kreis-anteil"):
            assert v.endswith("px") and float(v[:-2]) > 0, (k, v)


@pytest.mark.parametrize("name", SETS)
def test_groessen_des_sets(name):
    """Standardgroessen des Sets gelten ohne eigene Einstellung, eine
    eingestellte geht vor."""
    gr = TC.KACHEL_SETS[name].get("groessen") or {}
    std = {**konfig.GROESSEN_STANDARD["neu"], **gr}
    vars_ = _app({"tileSet": name}).resolve_profile("p")["vars"]
    assert vars_["--ico-size"] == f"{std['iconSize']}px" and vars_["--name-size"] == f"{std['nameSize']}px"
    assert _app({"tileSet": name, "iconSize": 30}).resolve_profile("p")["vars"]["--ico-size"] == "30px"


@pytest.mark.parametrize("name", SETS)
def test_vorschau_fuer_die_auswahlkarte(name):
    """Die Auswahlkarte im Konfigurator zeigt die Farben, die die Visu malt:
    Rahmen, Flaeche, Kachel, aktive Kachel, Akzent (im Standard des Sets)."""
    v = TC.kachel_set(name)
    eintrag = next(e for e in TC.kachel_set_liste() if e["key"] == name)
    assert eintrag["vorschau"] == {"rahmen": v["--rahmen"], "flaeche": v["--screen"], "kachel": v["--tile"],
                                   "an": v["--kachel-an"], "akzent": v["--glow"]}
    assert TC.kachel_set_vorschau("gibtsnicht") == {}


@pytest.mark.parametrize("name", MIT_SATZ)
def test_nachgerechnet_fuer_den_konfigurator(name):
    e = TC.KACHEL_SETS[name]
    for ohne in (n for n in SETS if n not in MIT_SATZ):
        assert TC.kachel_set_pruefung(ohne) == [], ohne
    if TC.kachel_set_art(name)[0] != "mitte":
        # Aufbau lx: "an" zeigt der Akzent auf der Kachel; auch ohne Farbton (feste Farben)
        for ton in (95, None):
            p = TC.kachel_set_pruefung(name, ton)
            v = TC.kachel_set(name, ton)
            assert [(k["name"], k["wert"], k["ziel"]) for k in p] == [
                ("Schrift auf Kachel", round(TC.kontrast(v["--ink"], v["--tile"]), 2), TC.AA),
                ("Akzent auf Kachel", round(TC.kontrast(v["--glow"], v["--tile"]), 2), e["satz"]["akzent"]["ziel"]),
                ("Symbol auf Taste", round(TC.kontrast(v["--ink"], v["--taste"]), 2), TC.AA)]
            assert all(k["wert"] >= k["ziel"] for k in p), p
        return
    for aktiv in AKTIV[name]:
        p = TC.kachel_set_pruefung(name, 95, aktiv)
        v = TC.kachel_set(name, 95, aktiv)
        assert [k["name"] for k in p] == ["Schrift auf Kachel", "Schrift auf aktiver Kachel", "Symbol auf Taste"]
        assert p[0]["wert"] == round(TC.kontrast(v["--ink"], v["--tile"]), 2) and p[0]["ziel"] == e["satz"]["kachel"]["ziel"]
        assert p[1]["wert"] == round(TC.kontrast(v["--kachel-an-ink"], v["--kachel-an"]), 2)
        assert p[1]["ziel"] == e["satz"]["aktiv"][aktiv]["ziel"] and p[2]["ziel"] == e["satz"]["taste"]["ziel"]
        assert all(k["wert"] >= k["ziel"] for k in p), p


@pytest.mark.parametrize("name", MIT_SATZ)
def test_route_nachgerechnet(name):
    """GET /api/kachelset: nur lesend, Ungueltiges gilt als Standard, ein
    unbekanntes Set ist 404."""
    import asyncio

    from aiohttp.test_utils import make_mocked_request

    async def holen(q):
        r = make_mocked_request("GET", "/api/kachelset?" + q)
        antwort = await W.api_kachelset(r)
        return antwort.status, (antwort.body and __import__("json").loads(antwort.body))
    std = TC.KACHEL_SETS[name]
    status, d = asyncio.run(holen(f"set={name}&farbton=160&aktiv=dunkel"))
    assert status == 200 and d["pruefung"] == TC.kachel_set_pruefung(name, 160, "dunkel")
    assert d["kachel"] == TC.kachel_set(name, 160, "dunkel")["--tile"]
    assert d["vorschau"] == TC.kachel_set_vorschau(name, 160, "dunkel")
    status, d = asyncio.run(holen(f"set={name}&farbton=rot&aktiv=grell"))
    assert d["pruefung"] == TC.kachel_set_pruefung(name, std["farbton"]["standard"], (std.get("aktiv") or {}).get("standard"))
    assert asyncio.run(holen("set=gibtsnicht"))[0] == 404


# ---- Kontraste --------------------------------------------------------------
def _paare(name: str, v: dict) -> list:
    """(vorn, hinten, Ziel, was) fuer alles, was panel.html bei diesem Set
    aufeinander setzt. Hauptschrift AAA auf Flaeche und Leiste, sonst AA,
    Symbole und Kreise 3:1 (WCAG 1.4.11)."""
    aufbau, leiste = TC.kachel_set_art(name)
    k = []
    # Schrift auf Flaeche, Kachel, Taste; Zweitzeile ebenso
    k += [("--ink", "--screen", TC.AAA, "Schrift auf der Flaeche")]
    # Grund der Uhr-Seite und der PIN; der Rahmen (--rahmen) traegt keinen Text
    k += [("--ink", "--bg", TC.AAA, "Schrift auf dem Grund"), ("--muted", "--bg", TC.AA, "Zweitzeile auf dem Grund")]
    k += [("--ink", f, TC.AA, "Schrift") for f in ("--tile", "--taste")]
    k += [("--muted", f, TC.AA, "Zweitzeile") for f in ("--tile", "--screen")]   # auf der Taste nur Symbole
    if aufbau == "mitte":
        # aktive Kachel kippt ganz um: eigene Schrift fuer Text und Symbol
        ziel = TC.KACHEL_SETS[name]["satz"]["aktiv"]["hell" if TC.luminanz(v["--kachel-an"]) > 0.18 else "dunkel"]["ziel"]
        k += [("--kachel-an-ink", "--kachel-an", ziel, "Schrift auf der aktiven Kachel"),
              ("--kachel-an-muted", "--kachel-an", TC.AA, "Zweitzeile auf der aktiven Kachel")]
    else:
        k += [("--ink", "--kachel-an", TC.AA, "Schrift auf der aktiven Kachel"),
              ("--muted", "--kachel-an", TC.AA, "Zweitzeile auf der aktiven Kachel")]
        an_text = "--an-text" if "--an-text" in v else "--glow"
        k += [(an_text, f, TC.AA, "Zustand an") for f in ("--tile", "--kachel-an")]
        k += [("--glow", f, TC.GRAFIK, "Symbol an") for f in ("--tile", "--kachel-an")]
    if aufbau == "kreis":
        k += [("--ink", "--taste", TC.GRAFIK, "Symbol im Kreis"),
              ("--kreis-an-symbol", "--glow", TC.GRAFIK, "Symbol im aktiven Kreis"),
              ("--glow", "--tile", TC.GRAFIK, "aktiver Kreis auf der Kachel")]
    # Zustandsfarben als Text auf der Kachel, Stoerung gefuellt, Text auf Akzent
    k += [(r, "--tile", TC.AA, "Zustandsfarbe") for r in ("--good", "--crit", "--cool", "--warn", "--accent")]
    k += [("--crit-ink", "--crit-fill", TC.AAA, "Stoerung"), ("--crit-muted", "--crit-fill", TC.AA, "Stoerung, Zweitzeile"),
          ("--on-glow", "--glow", TC.AA, "Text auf Akzent"), ("--on-accent", "--accent", TC.AA, "Text auf OK")]
    # Tab-Leiste
    if leiste == "oben":
        k += [("--tab-an", "--tabbar", TC.AA, "aktiver Tab"), ("--tab-aus", "--tabbar", TC.AA, "Tab")]
    else:
        k += [("--ink", "--tabbar", TC.AAA, "Schrift auf der Leiste"), ("--muted", "--tabbar", TC.AA, "Tab")]
    return k


def _pruefen(name: str, v: dict) -> list:
    fehler = [f"{was}: {vorn} {v[vorn]} auf {hinten} {v[hinten]} = {TC.kontrast(v[vorn], v[hinten]):.2f} < {ziel}"
              for vorn, hinten, ziel, was in _paare(name, v) if TC.kontrast(v[vorn], v[hinten]) < ziel]
    # Wo nur die Toenung "aktiv" zeigt (Aufbau lx), muessen sich die Zustaende
    # auch fuer rot-gruen-blinde Augen unterscheiden; "mitte" (kippt ganz um)
    # und "kreis" (der Kreis fuellt sich) tragen den Zustand ueber die Form.
    if TC.kachel_set_art(name)[0] == "lx":
        for a, b in (("--glow", "--good"), ("--glow", "--muted"), ("--good", "--muted")):
            if not TC.trennbar(v[a], v[b]):
                fehler.append(f"nicht trennbar: {a} {v[a]} / {b} {v[b]}")
    return fehler


@pytest.mark.parametrize("name", SETS)
def test_kontraste_des_sets(name):
    v = TC.kachel_set(name)
    assert not _pruefen(name, v), _pruefen(name, v)


@pytest.mark.parametrize("name, aktiv", [(n, a) for n in MIT_SATZ for a in AKTIV.get(n, [None])])
def test_kontraste_ueber_alle_farbtoene(name, aktiv):
    fehler = {h: f for h in range(0, 360, 5) if (f := _pruefen(name, TC.kachel_set(name, h, aktiv)))}
    assert not fehler, fehler


@pytest.mark.parametrize("aktiv_hell", [True, False])
def test_touch_satz_folgt_der_rechnung(aktiv_hell):
    """touch_satz(): jede Flaeche wandert nur so weit, bis ihr Ziel erreicht ist
    - einen Schritt davor war es noch nicht erreicht."""
    p = TC.KACHEL_SETS["touch"]["satz"]
    a = p["aktiv"]["hell" if aktiv_hell else "dunkel"]
    for h in range(0, 360, 5):
        v = TC.touch_satz(h, aktiv_hell)
        assert v["--ink"] == TC._hsl(h, *p["ink"])
        hell = round(TC._hls(v["--tile"])[1] * 100)
        assert TC.kontrast(v["--ink"], v["--tile"]) >= p["kachel"]["ziel"] or hell >= p["kachel"]["bis"], h
        assert hell == p["kachel"]["l"] or TC.kontrast(v["--ink"], TC._hsl(h, p["kachel"]["s"], hell - 1)) < p["kachel"]["ziel"], h
        assert v["--screen"] == TC._hsl(h, p["feld"]["s"], min(p["feld"]["bis"], hell + p["feld"]["plus"])), h
        assert TC.kontrast(v["--ink"], v["--taste"]) >= p["taste"]["ziel"], h
        assert v["--kachel-an"] == TC._hsl(h, *a["flaeche"]), h
        assert TC.kontrast(v["--kachel-an-ink"], v["--kachel-an"]) >= a["ziel"], h
        assert TC.kontrast(v["--tab-aus"], p["rahmen"]) >= p["tab_aus"]["ziel"], h
        assert v["--tabbar"] == v["--rahmen"] == p["rahmen"]
        # Text steht nie auf dem Rahmen: der Grund (Uhr-Seite, PIN) ist das Feld
        assert TC.kachel_set("touch", h, "hell" if aktiv_hell else "dunkel")["--bg"] == v["--screen"], h
    assert TC.touch_satz(361, aktiv_hell) == TC.touch_satz(1, aktiv_hell)


@pytest.mark.parametrize("aktiv", AKTIV["touch"])
def test_satz_farben_von_touch_sind_touch_satz(aktiv):
    for h in range(360):
        assert TC.satz_farben("touch", h, aktiv) == TC.touch_satz(h, aktiv == "hell"), h


def test_edge_ohne_farbton_bleibt_wie_heute():
    v = TC.kachel_set("edge")
    for var, wert in TC.KACHEL_SETS["edge"]["farben"].items():
        assert v[var] == wert, var


@pytest.mark.parametrize("h", range(0, 360, 5))
def test_edge_akzent_haelt_abstand_zu_den_zustandsfarben(h):
    v = TC.kachel_set("edge", h)
    ton = lambda c: TC._hls(c)[0] * 360
    abstand = lambda a, b: min(abs(a - b), 360 - abs(a - b))
    for rolle in ("--good", "--warn", "--crit"):
        assert abstand(ton(v["--glow"]), ton(v[rolle])) >= TC.EDGE_AKZENT_ABSTAND, (h, rolle)
    assert v["--accent"] == v["--glow"]
    assert TC.luminanz(v["--screen"]) < TC.luminanz(v["--tile"]) < 0.05   # bleibt dunkel


def test_edge_farbton_toent_den_grund():
    a, b = TC.kachel_set("edge", 30), TC.kachel_set("edge", 210)
    for var in ("--bg", "--screen", "--rahmen", "--tile", "--taste", "--tabbar", "--kachel-an"):
        assert a[var] != b[var], var


def test_schluessel_je_set():
    assert TC.FARBTON_SCHLUESSEL == ("tileHue", "tileHueEdge")


@pytest.mark.parametrize("ui", [{}, {"baseColor": "#f4efe6"}, {"tileSet": "touch"}, {"tileSet": "kreide"}])
@pytest.mark.parametrize("farbe", ["#1f6d3c", "#9fe0b0"])
def test_schrift_auf_eingestellter_ok_farbe(ui, farbe):
    """Eine eingestellte OK-Farbe zieht den Akzent mit (Kalender "heute",
    Entwurfsmarke) - und die Schrift darauf mit ihr, mit oder ohne Set."""
    v = W.App._theme_vars({**konfig.DEFAULT_THEME["states"], "good": farbe}, ui)
    assert v["--accent"] == farbe
    assert TC.kontrast(v["--on-accent"], farbe) >= TC.AA, (ui, farbe, v["--on-accent"])
