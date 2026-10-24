# LoxOS Stufe 2 – Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Farbton für das Kachel-Set `edge`, Ruhemodus mit gedimmter Uhr über den Loxone-Melder, Wischen zwischen Bento-Seiten mit weichem Übergang.

**Architecture:** Phase 8 verallgemeinert die Farbrechnung der Kachel-Sets (`theme_colors.py`) und speichert den Farbton je Set unter eigenem Schlüssel. Phase 9 ergänzt eine Geräte-Einstellung `ruhe`, die der Server in `theme` und `{t:"ruhe"}` an die Visu gibt; die Visu (neues Teil `panel/ruhe.js`) zeigt dann die vorhandene Nacht-Uhr statt abzuschalten, die Hülle hält die Bildschirme wach. Phase 10 markiert Bento-Seiten in `tabMeta` und blättert per Ein-Finger-Wisch mit View Transitions.

**Tech Stack:** Python 3.12 / aiohttp, Vanilla JS ohne Build, Electron 44 (Node-Tests), pytest + Playwright (Chromium).

**Spec:** `docs/VISION.md`, Abschnitt „Stufe 2 im Detail“ (Branch `feat/loxos-stufe2`).

## Global Constraints

- Nichts hart codiert: jede Zahl ist eine benannte Konstante, jeder Wert kommt aus Konfiguration, Kachel-Set oder Miniserver; keine Platzhalter, keine Mock-Daten, keine TODO-Stubs.
- Für alle Geräte und Ansichten ohne die neuen Einstellungen ändert sich nichts (Fork-Regel; `touch` Wert für Wert gleich).
- Fork-Regeln (`VISION.md`): Logik in neuen Dateien, in Upstream-Dateien nur kleine zusammenhängende Andockblöcke.
- Kommentare im Code mit `ae oe ue ss`, Anzeige-Texte, Commits, `docs/` mit echten Umlauten.
- Admin-Texte über `i18n.js` (Schlüssel = deutscher Text), Panel-Texte hart im Server.
- Neue Panel-Optionen: `_sanitize_panels()` + `_panel_export()`; ein bewusst nicht gespeicherter Standard nach `PANEL_STANDARD`.
- Kein Test verändert `config/`; Konstanten ersetzen mit `ersetzen(monkeypatch, …)` aus `tests/lox.py`.
- Jede Phase endet mit grünem `pytest` (lokal scheitert nur `tests/browser/test_intercom_talk_browser.py`, nicht anfassen) und `cd loxos && npm test`.
- Vor jedem Commit: `.venv/Scripts/python -m py_compile bin/*.py bin/bausteine/*.py bin/routen/*.py` und `.venv/Scripts/python -m ruff check --select F,E9 bin agent tests`.
- Umgesetztes wandert nach `docs/ARCHITEKTUR.md` (in der Aufgabe, die es baut).

## Review Focus

1. Zwei Finger auf einer Bento-Seite: Gesten bedienen den Raum, die Seite blättert nicht (Task 6, `test_zwei_finger_blaettern_nicht`).
2. Wisch, der auf einer Kachel-Taste oder einem Regler beginnt: die Taste reagiert, keine Seite wechselt; der Klick nach einem Seiten-Wisch löst keine Kachel aus (Task 6, `test_wisch_auf_taste_blaettert_nicht`).
3. `view` kommt verspätet oder gar nicht: der Übergang endet trotzdem nach seiner Zeitgrenze, die Visu bleibt bedienbar (Task 6, `test_uebergang_haengt_nicht`).
4. Melder schaltet schnell hin und her (oder der Neuversand aller States nach Reconnect): am Ende passt die Anzeige zum letzten Stand (Task 4, `test_melder_flackert`).
5. Melder wird im Konfigurator entfernt, `ruhe` war an: `ruhe` fällt weg, das Gerät verhält sich wieder wie ohne (Task 3, `test_ruhe_ohne_melder_faellt_weg`; Task 4 prüft die Visu nach `{t:"ruhe", ruhe:false}`).

---

### Task 0: Testumgebung

Lokal gibt es kein Python mit pytest (installiert: 3.13 und 3.14, kein 3.12 wie in Image und CI). Die Sperrliste `requirements-lock.txt` gilt für 3.12, darum lokal die Bereiche aus `requirements.txt`; maßgeblich bleibt die CI.

- [ ] **Step 1:** `py -3.13 -m venv .venv` (`.venv/` steht in `.gitignore`)
- [ ] **Step 2:** `.venv/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt` und `.venv/Scripts/python -m playwright install chromium`
- [ ] **Step 3:** `.venv/Scripts/python -m pytest -q` → grün bis auf `tests/browser/test_intercom_talk_browser.py` (Ausgangsstand festhalten); `cd loxos && npm ci && npm test` → grün.

## Phase 8 – Farbton für `edge`

### Task 1: Farbrechnung verallgemeinern, `edge` mit Rechnung

**Files:**
- Modify: `bin/theme_colors.py` (`KACHEL_SETS` touch/edge, `_farbton`, `_aktiv`, `kachel_set`, `kachel_set_pruefung`, `kachel_set_liste`; neu `_edge_satz`, `satz_farben`, `FARBTON_SCHLUESSEL`, `EDGE_AKZENT_ABSTAND`)
- Test: `tests/test_kachel_set.py`

**Interfaces:**
- Produces:
  - `KACHEL_SETS[x]["farbton"]` hat neu `"schluessel"` (touch: `"tileHue"`, edge: `"tileHueEdge"`); edge zusätzlich `"standard": None` und `"regler": <int>` (Startstellung des Reglers ohne Wahl). `"aktiv"` gibt es nur bei touch.
  - `KACHEL_SETS[x]["satz"]["rechnung"]`: `"hell"` (touch) bzw. `"dunkel"` (edge) – die Rechnung hängt an der Art, nie am Namen.
  - `satz_farben(name: str, farbton: int, aktiv: str | None) -> dict` – Farben der Rechnung eines Sets (touch: genau `touch_satz()`).
  - `FARBTON_SCHLUESSEL: tuple[str, ...]` – alle `farbton.schluessel` in Definitionsreihenfolge.
  - `kachel_set(name, farbton=None, aktiv=None)`: bei `farbton is None` und `standard is None` nur die festen `farben` (edge heute).
  - `kachel_set_liste()`: `farbton` mit `schluessel`, `standard`, `regler` (falls da), `auswahl[].farbe`, `verlauf`; `aktiv` nur wenn das Set es hat.

- [ ] **Step 1: Stand von touch sichern (nicht committen)**

Run: `.venv/Scripts/python -c "import sys,json;sys.path.insert(0,'bin');import theme_colors as T;json.dump({f'{h}/{a}':T.kachel_set('touch',h,a) for h in range(360) for a in ('hell','dunkel')},open(r'C:/Users/Erich/AppData/Local/Temp/claude/C--Users-Erich-Projekte-Loxpanel/895b02a0-56c5-44da-8717-49dfd4328b35/scratchpad/touch_vorher.json','w'))"`
Expected: Datei mit 720 Einträgen.

- [ ] **Step 2: Tests anpassen und ergänzen (failing)**

In `tests/test_kachel_set.py`:
- `AKTIV` nur für Sets mit `"aktiv"`; `test_farbton_und_aktive_kachel_speichern`, `test_farbton_wirkt_im_profil`, `test_ohne_set_bleibt_alles_wie_bisher` lesen den Schlüssel aus `e["farbton"]["schluessel"]`, den Teil „aktive Kachel“ nur, wenn das Set sie hat; `test_kontraste_ueber_alle_farbtoene` parametrisiert über `(name, aktiv)` mit `aktiv=None` für Sets ohne Auswahl. Die Erwartungen für touch bleiben wörtlich.
- Neu:

```python
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
```

- [ ] **Step 3: Run, verify fail**

Run: `.venv/Scripts/python -m pytest tests/test_kachel_set.py -q`
Expected: FAIL (`EDGE_AKZENT_ABSTAND`/`FARBTON_SCHLUESSEL` fehlen, edge ohne `satz`).

- [ ] **Step 4: Implementieren**

- touch: `"schluessel": "tileHue"` in `farbton`, `"rechnung": "hell"` in `satz`. `touch_satz()` bleibt öffentlich und unverändert.
- edge: `farbton = {"schluessel": "tileHueEdge", "standard": None, "regler": 225, "auswahl": [...]}` (Schnellwahl sechs Töne mit Namen, Wahl frei), `satz = {"rechnung": "dunkel", …}` mit (Sättigung, Helligkeit) je Fläche; Startwerte aus dem heutigen Look: Grund/Feld/Rahmen ≈ L 3,5 %, Leiste ≈ 5,7 %, Karte ≈ 8,6 %, aktive Karte ≈ 13 %, Taste ≈ 14 %, Sättigung ≈ 18 %; Schrift hell im Ton (`--ink` AAA auf Feld/Grund), `--muted` über `_ergaenzen()`.
- `_edge_satz(farbton: int) -> tuple` (gecacht wie `_touch_satz`): Flächen aus `satz`; Akzent: Kandidaten-Töne nach wachsendem Abstand zum gewählten (0, +5, −5, +10, …), der erste mit Kreisabstand ≥ `EDGE_AKZENT_ABSTAND` (Konstante, Startwert 30) zu den Tönen von `--good`, `--warn`, `--crit` aus `farben` und `trennbar()` zu `--good` und `--muted`; Helligkeit wandert (`_wandern`) bis `--glow` AA auf `--tile` und `--kachel-an` trägt. `--accent = --glow`.
- `satz_farben()` wählt nach `satz["rechnung"]`. `kachel_set()`: Rechnung nur, wenn `_farbton()` nicht `None` liefert. `_aktiv()` → `None` für Sets ohne `aktiv`.
- `kachel_set_pruefung()`: Paare nach Aufbau – `mitte` wie heute; `lx`: „Schrift auf Kachel“ (`--ink`/`--tile`, AA), „Akzent auf Kachel“ (`--glow`/`--tile`, AA), „Symbol auf Taste“ (`--ink`/`--taste`, AA). Für edge auch ohne Farbton (feste Farben).
- `kachel_set_liste()`: Farben der Schnellwahl und des Verlaufs über `satz_farben()`; `aktiv` nur wenn vorhanden.

- [ ] **Step 5: Run, verify pass; touch vergleichen**

Run: `.venv/Scripts/python -m pytest tests/test_kachel_set.py -q` → PASS.
Run: dasselbe Einzeiler-Skript wie Step 1 nach `touch_nachher.json`, dann `diff` beider Dateien → keine Ausgabe.

- [ ] **Step 6: Commit** – `git commit -m "LoxOS Phase 8: Farbrechnung für edge"`

### Task 2: Farbton speichern, ausliefern, im Konfigurator wählen

**Files:**
- Modify: `bin/konfig.py:1130-1132` (Speichern generisch je Set), `bin/ansicht.py:178-180` (Farbton aus dem Schlüssel des Sets), `bin/ansicht.py:393` (`*FARBTON_SCHLUESSEL` in der Whitelist), `bin/diagnosedaten.py:77` (Farbton aus dem Schlüssel des Sets)
- Modify: `webfrontend/html/config/ansicht-aussehen.js:134-210` (Schlüssel aus `s.farbton.schluessel`, Taste „Original“ bei `standard === null`, Umschalter „Aktive Kachel“ nur mit `s.aktiv`), `webfrontend/html/i18n.js` („Original“ und die Namen der Schnellwahl)
- Modify: `docs/ARCHITEKTUR.md` §5.4 (Kachel-Sets) und `ui`-Beispiel (§5.3)
- Test: `tests/test_kachel_set.py`, `tests/browser/test_bento_editor_browser.py` oder die vorhandene Konfigurator-Farbton-Prüfung (`grep -rn "ksHue" tests/browser`)

**Interfaces:**
- Consumes: `FARBTON_SCHLUESSEL`, `KACHEL_SETS[x]["farbton"]` aus Task 1.
- Produces: `ui.tileHueEdge` (int 0–359, fehlt = Original).

- [ ] **Step 1: Failing tests**

```python
def test_edge_farbton_eigener_schluessel():
    assert _gespeichert({"tileSet": "edge", "tileHueEdge": 200}) == {"tileSet": "edge", "tileHueEdge": 200}
    # ein alter touch-Farbton faerbt edge nicht
    vars_ = _app({"tileSet": "edge", "tileHue": 95}).resolve_profile("p")["vars"]
    assert vars_["--tile"] == TC.KACHEL_SETS["edge"]["farben"]["--tile"]
    vars_ = _app({"tileSet": "edge", "tileHueEdge": 200}).resolve_profile("p")["vars"]
    assert vars_["--tile"] == TC.kachel_set("edge", 200)["--tile"]

def test_edge_farbton_uebersteht_den_export():
    app = _app({"tileSet": "edge", "tileHueEdge": 200})
    assert app._panel_export(app.panels["p"])["ui"]["tileHueEdge"] == 200
```

Browser (Konfigurator, Set edge): Regler steht auf `regler`, „Original“ ist gedrückt, kein Umschalter „Aktive Kachel“; Regler bewegen setzt `tileHueEdge`, „Original“ löscht ihn; „Nachgerechnet“ zeigt drei Zeilen.

- [ ] **Step 2: Run, verify fail** – `.venv/Scripts/python -m pytest tests/test_kachel_set.py -q -k edge` → FAIL.
- [ ] **Step 3: Implementieren** – Speichern als Schleife über die Sets mit `farbton`: Wert über `_clean_kachel_farbton`, gespeichert, wenn ungleich `standard` (touch behält `PANEL_STANDARD[("ui","tileHue")]`; edge hat keinen Standardwert, braucht also keinen Eintrag). `_theme_vars`: `ui.get(KACHEL_SETS[set]["farbton"]["schluessel"])`.
- [ ] **Step 4: Run, verify pass** – `.venv/Scripts/python -m pytest tests/test_kachel_set.py tests/browser -q -k "kachel or ks"` → PASS.
- [ ] **Step 5: Phase prüfen** – `.venv/Scripts/python -m pytest -q` → grün (bis auf den bekannten Intercom-Test).
- [ ] **Step 6: Commit** – `git commit -m "LoxOS Phase 8: Farbton für edge im Konfigurator"`

---

## Phase 9 – Ruhemodus

### Task 3: Server – Einstellung `ruhe`, kein Abschalten

**Files:**
- Modify: `bin/konfig.py` `_sanitize_devices()` (Docstring + Feld `ruhe`)
- Modify: `bin/geraete.py` (Methode `_ruhe_an`)
- Modify: `bin/routen/visu.py:106` (`theme.ruhe`), `bin/routen/visu.py:172` (`idle` ignorieren)
- Modify: `bin/verteilung.py:207` (Treiber nicht ausschalten mit `ruhe`)
- Modify: `bin/routen/geraete.py:189` (nach dem Speichern `{t:"ruhe"}` an jede Verbindung)
- Modify: `docs/ARCHITEKTUR.md` §4 (`theme.ruhe`, neue Nachricht `ruhe`), §5 (`devices[name].ruhe`), §8 (Präsenzmelder)
- Test: `tests/test_ruhe.py` (neu, baut auf `tests/lox.py` und dem Muster von `tests/test_praesenz.py`)

**Interfaces:**
- Produces:
  - `devices[name]["ruhe"] = True` (nur mit `presence`; sonst fehlt der Schlüssel).
  - `Geraete._ruhe_an(self, dev: str) -> bool`.
  - `theme`-Feld `"ruhe": bool`; Nachricht `{"t": "ruhe", "ruhe": bool}`.

- [ ] **Step 1: Failing tests** in `tests/test_ruhe.py`:
  - `test_ruhe_wird_gespeichert`: `{"s": {"presence": "PM", "ruhe": True}}` → Eintrag mit `ruhe: True`; `"ruhe": 1` oder `"ja"` → kein `ruhe`.
  - `test_ruhe_ohne_melder_faellt_weg`: `{"s": {"ruhe": True, "scale": "auto"}}` → kein `ruhe`.
  - `test_theme_traegt_ruhe`: Verbindung mit `?device=s` bekommt `theme.ruhe is True`, ein Gerät ohne → `False`.
  - `test_raum_leer_schaltet_mit_ruhe_nicht_ab`: Gerät mit `display`-Treiber, `presence`, `ruhe`; `display_drivers` per `monkeypatch` protokolliert; `_on_value(pm_a, 0)` + Broadcaster-Takt → kein Aufruf mit `False`, die Visu bekommt trotzdem `{t:"display", on:false, presence:false}`. Ohne `ruhe` → Aufruf mit `False` (wie heute).
  - `test_leerlauf_mit_ruhe_schaltet_nicht_ab`: `{t:"idle"}` von diesem Gerät → kein `display_drivers`.
  - `test_speichern_meldet_ruhe`: `POST /api/devices` mit `ruhe` → verbundene Visu des Geräts bekommt `{t:"ruhe", ruhe:true}`.
- [ ] **Step 2: Run, verify fail** – `.venv/Scripts/python -m pytest tests/test_ruhe.py -q` → FAIL.
- [ ] **Step 3: Implementieren** – `ruhe = cfg.get("ruhe") is True and bool(presence)`; `_ruhe_an()` liest `self.devices`; in `verteilung.py` die Treiber nur überspringen, wenn `not ev["on"] and self._ruhe_an(ev["dev"])`.
- [ ] **Step 4: Run, verify pass** – `.venv/Scripts/python -m pytest tests/test_ruhe.py tests/test_praesenz.py -q` → PASS.
- [ ] **Step 5: Commit** – `git commit -m "LoxOS Phase 9: Ruhemodus im Server"`

### Task 4: Visu – Ruhe-Uhr über die Nacht-Uhr, Konfigurator-Schalter

**Files:**
- Create: `webfrontend/html/panel/ruhe.js` (Teil nach `display.js`, vor `start.js`)
- Modify: `webfrontend/html/panel.html` (Script-Tag mit Kommentar `<!-- LoxOS: Ruhemodus -->`)
- Modify (Andockblöcke, je eine Zeile): `panel/display.js` `nachtUhrAn()`, `armDpms()`, `appLeerlauf()`; `panel/startseite.js` `nachRuhe()`; `panel/verbindung.js` (`theme`: `RUHE` setzen und `ruheAnwenden()`; `display`: mit `RUHE` `ruheAnwenden()` statt `screenOff()`; neue Nachricht `ruhe`)
- Modify: `webfrontend/html/config/geraete.js` (Kästchen `.dp_ruhe` „Ruhe-Uhr statt Display aus“ neben `.dp_presence`, gesperrt ohne Melder; in `devAusServer`, Lesen aus dem DOM, `devicesPayload`), `webfrontend/html/i18n.js`
- Modify: `docs/ARCHITEKTUR.md` §7.1 (Teile der Visu: dreizehn; Nacht-Uhr/Ruhe), `CLAUDE.md` (Zahl der Skriptteile)
- Test: `tests/browser/test_ruhe_browser.py` (neu, Muster `test_praesenz_browser.py`, Fully-Nachbau `FULLY_JS`)

**Interfaces:**
- Consumes: `theme.ruhe`, `{t:"ruhe"}`, `{t:"display"}` aus Task 3; vorhandene `DISP`, `NIGHT`, `showSaver()`, `hideSaver()`, `nachtUhrSetzen()`, `resetIdle()`.
- Produces (global, `ruhe.js`): `let RUHE=false;` · `ruheAn() -> boolean` (`RUHE && !DISP.presence`) · `ruheAnwenden()` (niemand da: `showSaver()`, sonst `hideSaver()` + `resetIdle()`; danach `nachtUhrSetzen()`) · `ruheNachLeerlauf() -> boolean` (mit `RUHE`: niemand da → `showSaver()`; immer `true`, damit `nachRuhe()` weder Seite wechselt noch bei Anwesenheit die Uhr zeigt).
- Andockungen: `nachtUhrAn()` → `(NIGHT.on && NIGHT.uhr) || ruheAn()`; `armDpms()` und Fully-`screenOff()` nicht mit `RUHE`; `appLeerlauf()` → `setDisplayOff((DISP.presence || RUHE) ? 0 : DISP.dpmsOff)`; erste Zeile von `nachRuhe()`: `if(ruheNachLeerlauf()) return;`.

- [ ] **Step 1: Failing browser tests** (Viewport 2560×720, Gerät `streifen` mit `presence: "PM"`, `ruhe: true`, Ansicht mit zwei Tabs):
  - `test_ruhe_uhr_wenn_niemand_da`: jemand da → nach dem Laden Uhr-Seite weg; `nachRuhe()` aufrufen → Uhr bleibt weg. `_on_value("pm_a", 0)` → `#saver` sichtbar mit Klasse `nacht`, `#svNacht` nicht `hidden`, `window.__fully` ohne `'aus'`.
  - `test_aufwachen_zeigt_die_seite_von_vorher`: auf Tab 2 wechseln, Raum leer, dann `_on_value("pm_a", 1)` → Uhr weg, `view.tab` ist Tab 2.
  - `test_tipp_weckt_und_ruhe_kehrt_zurueck`: Raum leer, Tipp auf `#saver` → Uhr weg; `nachRuhe()` → Uhr wieder da (Klasse `nacht`), Tab unverändert.
  - `test_melder_flackert`: leer/da/leer/da in schneller Folge → Uhr weg; leer/da/leer → Uhr da.
  - `test_ohne_ruhe_wie_bisher`: gleiches Gerät ohne `ruhe` → Raum leer schaltet `__fully` `'aus'` (heutiges Verhalten).
  - `test_ruhe_aus_per_nachricht`: Server schickt `{t:"ruhe", ruhe:false}` bei leerem Raum → keine Ruhe-Uhr mehr (`nachtUhrAn()` falsch tagsüber).
  - Konfigurator: Kästchen ohne Melder gesperrt; mit Melder setzen und speichern → `devices.streifen.ruhe === true` in der gespeicherten Datei (Stellvertreter wie in `test_konfigurator_waehlt_und_speichert_den_melder`).
- [ ] **Step 2: Run, verify fail** – `.venv/Scripts/python -m pytest tests/browser/test_ruhe_browser.py -q` → FAIL.
- [ ] **Step 3: Implementieren** (`ruhe.js` mit Kopfkommentar „Teil x von 13“ wie die übrigen Teile; die Kopfzeilen der anderen Teile auf „von 13“ anpassen).
- [ ] **Step 4: Run, verify pass** – `.venv/Scripts/python -m pytest tests/browser/test_ruhe_browser.py tests/browser/test_praesenz_browser.py tests/browser/test_gesten_browser.py -q` → PASS.
- [ ] **Step 5: Commit** – `git commit -m "LoxOS Phase 9: Ruhe-Uhr in der Visu"`

### Task 5: Hülle – Bildschirme wach halten

**Files:**
- Modify: `loxos/src/einstellungen.js` (Feld `bildschirmWach`, Standard `true`, Prüfer bool; Funktion `wachHalten`)
- Modify: `loxos/src/main.js` (`powerSaveBlocker`, Tray-Häkchen „Bildschirme wach halten“, Aufruf in `widgetModus()`, `desktopModus()`, nach `loxos:speichern`)
- Modify: `loxos/src/einrichtung.html`, `loxos/src/einrichtung.js` (Kästchen `#wach`)
- Modify: `loxos/README.md`, `docs/ARCHITEKTUR.md` (Hülle)
- Test: `loxos/test/einstellungen.test.js`

**Interfaces:**
- Produces: `wachHalten(werte: object, modus: 'widget'|'desktop') -> boolean` = `werte.bildschirmWach && modus === 'widget'` (im Desktop-Modus zeigt der Streifen keine Visu; meine Entscheidung).

- [ ] **Step 1: Failing tests** – `bildschirmWach` Standard `true`; `false` bleibt; `"ja"` wird verworfen und gemeldet; `wachHalten({bildschirmWach:true},'widget') === true`, `…,'desktop') === false`, `({bildschirmWach:false},'widget') === false`.
- [ ] **Step 2: Run, verify fail** – `cd loxos && npm test` → FAIL.
- [ ] **Step 3: Implementieren** – in `main.js` eine Funktion `wachSetzen()`: Blocker-ID halten, `powerSaveBlocker.start('prevent-display-sleep')` bzw. `.stop(id)` nach `E.wachHalten(werte, modus)`; nie zwei Blocker zugleich.
- [ ] **Step 4: Run, verify pass** – `cd loxos && npm test` → PASS; `.venv/Scripts/python -m pytest tests/test_loxos_huelle.py -q` → PASS.
- [ ] **Step 5: Phase prüfen** – `.venv/Scripts/python -m pytest -q` → grün.
- [ ] **Step 6: Commit** – `git commit -m "LoxOS Phase 9: Hülle hält die Bildschirme wach"`

---

## Phase 10 – Wischen zwischen Bento-Seiten

### Task 6: Bento-Seiten in `tabMeta`, Wischen und Übergang

**Files:**
- Modify: `bin/seiten.py:120` (`meta[t]["bento"] = True` bei Pick-Tabs mit `bento`)
- Modify: `webfrontend/html/panel/bento.js` (Konstanten, Nachbar, Wischen, Übergang)
- Modify: `webfrontend/html/panel/bento.css` (Keyframes des Übergangs je Richtung)
- Modify: `webfrontend/html/panel/seiten.js:94` (Tipp in die Leiste: `if(!bentoTabWechsel(tab)) goTab(tab)` – eine Zeile)
- Modify: `docs/ARCHITEKTUR.md` §4 (`tabMeta.bento`), §7.1 (Bento: Wischen)
- Test: `tests/test_bento_server.py`, `tests/browser/test_bento_browser.py`

**Interfaces:**
- Consumes: `tabMeta[t].bento`, `tabsCfg`, `view.tab`, `goTab()`, `renderBento()`.
- Produces (global, `bento.js`):
  - Konstanten `BENTO_WISCH_WEG` (Anteil der Flächenbreite, Startwert 0.06), `BENTO_WISCH_RICHTUNG` (waagerecht mindestens so viel mal senkrecht, Startwert 1.5), `BENTO_WECHSEL_MS` (Dauer, Startwert 280), `BENTO_WECHSEL_GRENZE_MS` (spätestens Ende, wenn `view` ausbleibt, Startwert 1500), `BENTO_KLICKSPERRE_MS` (Klick nach einem Wisch, Startwert wie `GESTE_KLICKSPERRE_MS`).
  - `bentoNachbar(richtung: 1 | -1) -> string | null` – nächste/vorige Bento-Seite in `tabsCfg` ab `view.tab`, normale Seiten übersprungen, kein Rundlauf.
  - `bentoWechsel(tab: string, richtung: 1 | -1)` – mit `document.startViewTransition`: Richtung als `data-bento-richtung` an `<html>`, Übergang wartet auf die nächste `renderBento()`/`updateBento()` dieser Seite oder auf `BENTO_WECHSEL_GRENZE_MS`; ohne Schnittstelle nur `goTab(tab)`.
  - `bentoTabWechsel(tab: string) -> boolean` – Tipp in die Leiste; `true`, wenn von einer Bento- zu einer Bento-Seite (Richtung aus der Lage in `tabsCfg`).
  - Wischen: ein Pointer auf `#grid.bento`; kein Start auf Kachel-Tasten, Reglern, Diagrammen, Webseiten-Zellen (dieselben Ausschlüsse wie die Tasten der Kachel); ein zweiter Pointer bricht ab (Gesten).

- [ ] **Step 1: Failing tests**
  - Server: `test_tabmeta_kennt_bento_seiten` – Pick-Tab mit `bento` → `tabMeta[t]["bento"] is True`, ohne → Schlüssel fehlt.
  - Browser (2560×720 und 1920×480, Leiste `bento A, favoriten, bento B`):
    - `test_wisch_wechselt_zur_naechsten_bento_seite`: Wisch nach links auf A → `view.tab` ist B (favoriten übersprungen); nach rechts auf B → A; nach rechts auf A → bleibt A.
    - `test_tipp_in_die_leiste_gleitet`: Tipp auf B von A → `data-bento-richtung` gesetzt, nach `BENTO_WECHSEL_GRENZE_MS` wieder entfernt, `view.tab` ist B.
    - `test_wisch_auf_taste_blaettert_nicht`: Wisch beginnt auf einer Player-Taste in einer Zelle → Tab bleibt; Klick direkt nach einem Seiten-Wisch löst keine Kachel aus.
    - `test_zwei_finger_blaettern_nicht`: zwei Finger waagerecht (DevTools `Input.dispatchTouchEvent` wie `test_gesten_browser.py`) → Tab bleibt, Geste geht an den Server.
    - `test_uebergang_haengt_nicht`: Server-Antwort auf `nav` verworfen (Stellvertreter) → nach `BENTO_WECHSEL_GRENZE_MS` kein `data-bento-richtung`, Tipp auf eine Kachel wirkt.
- [ ] **Step 2: Run, verify fail** – `.venv/Scripts/python -m pytest tests/test_bento_server.py tests/browser/test_bento_browser.py -q` → FAIL.
- [ ] **Step 3: Implementieren**
- [ ] **Step 4: Run, verify pass** – dieselben Tests plus `tests/browser/test_gesten_browser.py tests/browser/test_kachel_tasten_browser.py` → PASS.
- [ ] **Step 5: Phase prüfen** – `.venv/Scripts/python -m pytest -q` → grün; `cd loxos && npm test` → grün.
- [ ] **Step 6: Commit** – `git commit -m "LoxOS Phase 10: Wischen zwischen Bento-Seiten"`

### Task 7: Abschluss

- [ ] **Step 1:** `docs/VISION.md` „Stufe 2 im Detail“: umgesetzte Phasen mit Verweis auf `ARCHITEKTUR.md` kennzeichnen; `CLAUDE.md`-Tabelle (`panel/ruhe.js`, Zahl der Teile) prüfen.
- [ ] **Step 2:** volle Prüfung wie in `CLAUDE.md` „Prüfen vor einem Push“ → grün bis auf den bekannten Intercom-Test.
- [ ] **Step 3:** Push `feat/loxos-stufe2`, PR gegen `main` von `CHief-Wiggum1203/Loxpanel`, CI beobachten; Merge erst nach OK.
