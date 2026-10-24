# Mitentwickeln & den Fork synchron halten

Dieser Fork (`CHief-Wiggum1203/Loxpanel`) wird eigenständig weiterentwickelt und
auf Unraid betrieben, bleibt aber eng an das Original
(`Lenardo1/Loxpanel`, hier `upstream`) angelehnt. Diese Datei beschreibt, wie
Entwicklung und Abgleich praktisch ablaufen. Kurzfassung der Git-Konventionen
steht in [`CLAUDE.md`](../CLAUDE.md), Architektur in
[`ARCHITEKTUR.md`](ARCHITEKTUR.md).

## Mentalmodell: „Fork = Upstream + dünne Identitätsschicht"

Der Fork bleibt genau dann leicht synchron, wenn möglichst wenig ihn vom
Upstream unterscheidet:

> So viel wie möglich gehört nach Upstream. Im Fork bleibt nur, was wirklich nur
> diese Installation betrifft.

Je dünner die Fork-eigene Schicht, desto reibungsloser jeder Abgleich. Neue
Bausteine, Bugfixes und allgemeine Verbesserungen fließen daher nach Upstream –
nicht nur in den Fork. Wer allgemeine Arbeit nur im Fork ablegt, baut sich bei
jedem Upstream-Update dieselben Konflikte neu.

## Was gehört wohin?

| Nach Upstream (`Lenardo1/Loxpanel`) | Nur in den Fork |
|---|---|
| Neue Bausteintypen, Steuer-Logik | Image-Name `ghcr.io/chief-wiggum1203/loxpanel` (klein) |
| Front/Screensaver, Audio, Bugfixes | Repo-/Archiv-Links, `ARCHIVEURL` in `loxberry-plugin/release.cfg` |
| Allgemeine Doku (`ARCHITEKTUR.md`, `TODO.md`) | `plugin.cfg` NAME/FOLDER/AUTHOR |
| Alles, wovon andere Nutzer profitieren | `unraid/`-Template + Unraid-Doku, diese `CONTRIBUTING.md`, `CLAUDE.md` |
| | LoxOS: Bento-Seiten, Kachel-Set `edge`, Hülle `loxos/` (Ablauf E, [`VISION.md`](VISION.md)) |

## Voraussetzung: upstream-Remote

Einmalig prüfen/anlegen:

```bash
git remote -v                       # ist 'upstream' schon da?
git remote add upstream https://github.com/Lenardo1/Loxpanel   # falls nicht
```

## Ablauf A – Ein Feature entwickeln (→ Upstream)

Für alles Allgemeine. **Immer von `upstream/main` aus starten**, nicht vom
Fork-`main` – dann ist der Branch sauber gegen Upstream, ohne Identitäts-Ballast.

```bash
git fetch upstream
git checkout -b feature/mein-baustein upstream/main
# ... entwickeln, committen, Rauchtest (siehe unten) ...
git push origin feature/mein-baustein
```

Dann eine Pull Request **gegen `Lenardo1/Loxpanel:main`** öffnen (Basis-Repo =
Lenardo1, Compare = dieser Branch). Das funktioniert unabhängig von
Schreibrechten – der klassische Fork-→-Upstream-Weg. Mit Schreibrechten kann der
Branch auch direkt nach `upstream` gepusht werden; nötig ist das nicht.

Lenardo hat die Geschichte seines Repos am 04.10.2026 neu begonnen. Ein Zweig,
der davor von `upstream/main` abging, hat mit seinem heutigen `main` keine
gemeinsame Basis mehr, und GitHub kann einen PR daraus nicht mergen. So einen
Zweig auf `upstream/main` neu aufsetzen (die eigenen Commits per
`git cherry-pick`), wie am 13.10.2026 bei #83 geschehen.

Ist die PR bei Upstream gemergt → **Ablauf C** holt sie in den Fork zurück.

## Ablauf D – Den Fork-Stand in Etappen einreichen

Ist der Fork weit voraus (am 17.10.2026: über 30 000 Zeilen, `webvisu.py`
zerlegt), lässt sich nicht jedes Feature einzeln auf Lenardos Stand
nachbauen. Dann geht der Fork-Stand selbst zu ihm, in Etappen entlang der
Fork-Geschichte (am 17.10.2026 Lenardos #102–#108, TODO §0b):

- Je Etappe ein Zweig `up/etappe-<n>-<thema>` auf dem vorigen, der erste auf
  `upstream/main`. Jeder Commit hat als Baum den Fork-Baum des entsprechenden
  Fork-Commits; Lenardos eigene Pfade (README, `loxberry-plugin/`,
  `docker-image.yml`) und die Fork-eigenen (`tests/`, `docs/`, `CLAUDE.md`,
  `unraid/`, `deploy/UNRAID.md`, `tests.yml`, `android-tests.yml`,
  `pytest.ini`, `requirements-dev.txt`) nimmt er aus `upstream/main`, den
  Image-Namen in `docker-compose.yml` setzt er auf `lenardo1`. Gebaut mit
  `git read-tree`, `git update-index` und `git commit-tree`, kein
  Cherry-Pick: so gibt es keine Konflikte, und jede Etappe ist genau ein
  Fork-Stand.
- Ab dem letzten Abgleich (gemeinsame Geschichte) ein Commit je Fork-Commit,
  mit Autor, Datum und Text; `(#N)` wird `(CHief-Wiggum1203/Loxpanel#N)`,
  sonst zeigt es bei Lenardo auf seine PRs. Commits ohne Änderung danach
  (Version, TODO, nur Tests) entfallen. Davor ein Gesamtstand.
- Prüfen: Die letzte Etappe darf vom Fork-Code nur in den ersetzten Zeilen
  abweichen (`git diff` ohne die Pfade oben), Lenardos eigene Pfade gar
  nicht. Die Fork-Tests über die letzte Etappe legen (`git archive … tests
  pytest.ini requirements-dev.txt`) und laufen lassen: rot nur, was
  Fork-Eigenes prüft.
- PR-Texte nennen die Reihenfolge und bitten um Merge-Commit oder „Rebase
  and merge“: Bei Squash zeigt die nächste Etappe die gemergten Änderungen
  noch einmal. Mehr als ein Commit füllt GitHub die Beschreibung nicht vor;
  die Links tragen Titel und Text darum als `title=` und `body=`.
- Was nur ein Teil des Plugins betrifft und dringend ist (LoxBerry, #103),
  geht zusätzlich für sich (Ablauf A) und bleibt aus den Etappen heraus.

## Ablauf B – Etwas rein Fork-eigenes (Identität / Unraid)

Das, was nicht nach Upstream soll. Normal im Fork, Squash/Rebase ist hier ok
(diese Commits sieht Upstream nie). Klein halten und auf die Identitäts-/
Deployment-Dateien beschränken, damit die Sync-Konflikte berechenbar bleiben.

```bash
git checkout -b fix/unraid-xyz main
# ... ändern ...
git push -u origin fix/unraid-xyz     # PR gegen den Fork-main
```

## Ablauf E – LoxOS (Fork-eigenes Feature)

LoxOS ist die eine bewusste Ausnahme vom Mentalmodell oben: ein allgemeines
Feature, das trotzdem im Fork bleibt. Ziel, Roadmap und Datenformat stehen in
[`VISION.md`](VISION.md). Damit die Fork-Schicht trotz LoxOS berechenbar bleibt,
gelten die Fork-Regeln aus `VISION.md`: Logik in eigenen Dateien, in
Upstream-Dateien nur kleine, zusammenhängende Andockstellen.

```bash
git checkout -b feat/loxos-<thema> main
# ... entwickeln, Rauchtest (siehe unten) ...
git push -u origin feat/loxos-<thema>   # PR gegen den Fork-main
```

Beim Upstream-Abgleich (Ablauf C) laufen die LoxOS-Tests mit. Ein Konflikt an
einer Andockstelle wird dort gelöst; Upstream-Code wird nicht in LoxOS-Dateien
kopiert, um einem Konflikt auszuweichen.

## Ablauf C – Den Fork synchron halten (das „gleich halten")

Immer wenn Upstream etwas Neues released. Als Repo-Owner ist der einfachste Weg:
**lokal mergen und direkt auf `main` pushen**. Das umgeht die „nur Squash/
Rebase"-Einstellung und löst die Tests und danach den `:latest`-Build
automatisch aus (weil der Push mit den eigenen Zugangsdaten erfolgt, nicht über
einen Bot-Token). Das Image entsteht erst, wenn die Tests dieses Pushs grün sind.

```bash
# 1. Upstream-Stand holen
git fetch upstream

# 2. Auf aktuellen Fork-main
git checkout main && git pull origin main

# 3. Upstream als ECHTEN Merge-Commit reinziehen (NICHT squashen!)
git merge upstream/main
#    Konflikte fast nur in den Identitäts-Dateien (release.cfg ARCHIVEURL,
#    plugin.cfg VERSION, Image-Name): Fork-Identität behalten, Upstream-Code
#    übernehmen. Die Version bleibt die des Forks: Seit 1.0.0 zählt er
#    eigenständig (VERSION in plugin.cfg und release.cfg; das .deb nimmt
#    sie beim Bauen aus plugin.cfg).
#    Ausnahme .github/workflows/docker-image.yml („deleted in HEAD and
#    modified in upstream/main“): gelöscht lassen (git rm), sonst
#    veröffentlicht sie wieder ohne Tests. Nötiges in den Job
#    veroeffentlichen in tests.yml übertragen (Fork-eigene Patches unten).
#    Workflows: Upstream schreibt `uses: …@v4`, der Fork den Commit
#    (`@<sha> # v4.x.y`). Den Commit behalten; hebt Upstream eine Action auf
#    eine neue Hauptversion, deren Commit eintragen (Abschnitt
#    „Abhängigkeiten“ unten). Ändert der Merge requirements.txt, die
#    Sperrliste neu erzeugen, sonst wird tests/test_abhaengigkeiten.py rot.

# 4. Rauchtest (siehe unten), mindestens die Wache über die Workflows:
.venv/bin/pytest tests/test_workflows.py
#    Bringt der Merge eine NEUE Workflow-Datei mit, die nach ghcr.io
#    veröffentlicht, gibt es keinen Konflikt. Die Wache meldet sie hier;
#    nach dem Push veröffentlichte die Datei schon neben den Tests her.

# 5. Direkt pushen -> Tests laufen, nach grünen Tests wird :latest neu gebaut
git push origin main
```

Weil es ein **echter Merge-Commit** ist, kennt `main` danach die neuen
Upstream-Commits als Vorfahren → beim nächsten Sync keine Wiederholungskonflikte.
Alternativ über eine PR: dann kurz „Allow merge commits" aktivieren und mit
„Create a merge commit" mergen – **niemals** squashen/rebasen, sonst geht die
Upstream-Historie verloren.

## Sync-Checkliste (vor und nach jedem Upstream-Abgleich)

Der Fork soll strukturell nur Identität/Deployment enthalten (siehe
Mentalmodell) — dann kann ein Sync keinen Fix „verschlucken". Diese Liste
sichert das ab. Sie entstand aus einem realen Fehler: Beim 0.4.0-Sync wurde
`bin/webvisu.py` komplett von Upstream übernommen und dabei eine Fork-eigene
Audio-Weiche überschrieben, die nur im Fork lag → die Bedienung eines
gekoppelten Audioservers war tot. **Merke:** Ein Fork-Fix an einer Datei, die
Upstream ebenfalls ändert, geht verloren, sobald man Upstream übernimmt.

**1. Vor dem Sync — Divergenz prüfen:**

```bash
git fetch upstream
git log --oneline upstream/main..main    # Fork-Commits, die Upstream NICHT hat
```

Jeder gelistete Commit ist entweder (a) Identität/Deployment (ok, bleibt im
Fork) oder (b) ein echter Code-Fix / ein Feature. **Fall (b) gehört zuerst nach
Upstream** (Ablauf A) — sonst geht er beim Übernehmen verloren. Idealzustand:
die Liste enthält nur noch (a).

**2. Beim Auflösen von Konflikten:**

Nie `git checkout --theirs <datei>` auf eine Datei mit Fork-eigener Logik, ohne
diese Logik vorher zu sichern: erst `git diff main upstream/main -- <datei>`
ansehen, Fork-Änderungen erkennen und nach dem Übernehmen wieder einspielen
(besser: die Änderung vorher upstream einreichen, dann ist sie in beiden).

**3. Nach dem Sync — Funktionstest der kritischen Pfade** (nicht nur der
`py_compile`-Rauchtest), bevor `main` gepusht wird. Danach baut der
Workflow `:latest`, sobald die Tests grün sind, und die kennen nur den Nachbau:

- Musik: play/pause + Lautstärke an einer `AudioZone`/`AudioZoneV2`
- PIN-Tür, Intercom-Bild, eine Jalousie / ein Licht schalten
- Front/Screensaver lädt (Kalender/Wetter)

**4. Fork-eigene Patches (Stand pflegen):**

Falls etwas unvermeidbar nur im Fork liegt, hier eintragen, damit ein Sync es
nicht unbemerkt entfernt:

Seit dem 17.10.2026 ist alles in dieser Liste mit den Etappen #102–#108 bei
Lenardo eingereicht (Ablauf D, TODO §0b). Mergt er sie, steht es in beiden;
bis dahin gelten die Hinweise unten für jeden Abgleich weiter.

- Icon-Bibliothek einer freien Seite (`pickIcoGridNeu()` und
  `bindPickIcons()` in `config.html`): Kommt die Bibliothek nach, füllt sie nur
  das Icon-Raster neu statt des ganzen Editors, sonst verliert der Seitenname
  mitten im Tippen Fokus und Buchstaben. Geht es zu Lenardo, sobald der
  Panel-Assistent (`wzIcoGrid()`) dasselbe kann. Geht es verloren, schlägt
  `test_name_tippen_waehrend_die_icon_bibliothek_laedt` an.
- Neuer Kachel-Aufbau und Schriftgrößen je Aufbau (`.lx` in `panel.html`,
  `subInfo`/`big`/`bigSub` in `_control_item()`, `ui.tileLayout`,
  `GROESSEN_STANDARD`, `sizeDefaults` in `/api/meta`, `theme.example.json` ohne
  Größen): Lenardo erst vorschlagen, er plant ein frei konfigurierbares
  Display. Bis dahin reiben sich Upstream-Merges an `render()`, `updateGrid()`
  (der Fork behält dort zusätzlich `aufbauKlassen()` und `eng<n>`), an
  `sizeField()` und der Vorlage. Wachen: `tests/test_kachel_aufbau.py`,
  `tests/browser/test_kachel_aufbau_browser.py`,
  `test_mini_verlauf_im_neuen_aufbau`.
- Automatisches Raster für Tablets (`ui.grid`/`ui.tileSize`, `KACHEL_ZIEL`,
  `gridAuto` in der theme-Nachricht, `autoRaster()` und `.screen.auto` in
  `panel.html`, Kachel-Layout „Automatisch“ und Assistent in `config.html`,
  Raster in der Bildschirmmeldung `rc`/`rr`): gehört zum selben Vorschlag an
  Lenardo. Reibt sich bei Upstream-Merges an `rasterFuer()`, `applyPane()`
  und `applyScale()`. Wachen: `tests/test_auto_raster.py`,
  `tests/browser/test_auto_raster_browser.py`.
- Pane 2 nutzt ihre Fläche (`wetterEinpassen()`, `kalenderEinpassen()`,
  `werteEinpassen()`, `paneEinpassen()` am `ResizeObserver` von `#frontpane`,
  `fpCurve()` mit Größe, die Regeln `.fp-page.wx`/`.kal`/`.werte` in
  `panel.html`; Verbindungspunkt auf Widget-Seiten aus): baut auf den
  fork-eigenen Wetter- und Kalender-Tabs auf (`fpNowHTML()`/`fpCurveHTML()`,
  `renderWertePane()`); für Lenardo erst auf seinen Wetter-Aufbau
  (`fpWeatherMainHTML()`, `renderSvStatus()`) umbauen. Reibt sich bei
  Upstream-Merges an `renderWeatherPane()`,
  `renderCalendarPane()` und `renderSvStatus()`. Dazu gehört
  `vorschauDatumEinpassen()` (Fork #108): Eng bleibt das Datum der
  Wetter-Vorschau einzeilig. Wache:
  `tests/browser/test_pane_hoehe_browser.py` (`test_wetter_eng_langes_datum`).
- Uhr-Seite wegtippen löst die Kachel darunter nicht aus (`saverGeste` und
  die Capture-Abfänger auf `window` vor `el('saver')` in `panel.html`, Fork
  #107): seit dem Abgleich vom 13.10.2026 auch in Upstream (#85). Nur im
  Fork lauscht die Zeile darunter zusätzlich auf `input` (Android-Tastaturen
  melden nicht jedes Zeichen als `keydown`); bei Upstream-Merges dort die
  Fork-Fassung behalten. Wache:
  `tests/browser/test_saver_wecken_browser.py`.
- Die vier Bausteine nach der Loxone-Strukturdoku (Oktober 2026): Wecker mit
  Weckzeiten bearbeiten, Bewässerung mit Einzelzonen und Laufzeit, verpasste
  Klingeln des Intercoms samt `/bellimg`, UpDownAnalog wie der Slider. Dazu die
  neuen Blöcke `stepper`, `field`, `timepick`, `chips`, `gallery` und die
  Zellen mit `nav`/`form`/`confirm`/`back` in `panel.html`. Die allgemeinen
  Teile (`panelEinpassen()` mit `.pantop{flex:1 0 auto}` für volle
  Detailseiten, die Rundung von `nudgeSld()` und die Signatur der
  Weckzeiten-Liste in `blockSig()`) sind seit 0.7.0 in Upstream (#81); die
  Bausteine selbst gehen erst nach der Prüfung an der Anlage zu Lenardo
  (TODO §8.1). Reibt sich bei Upstream-Merges an
  `_control_item()`, `_view_control_inner()`, `renderPanel()` und
  `updatePanel()`. Wachen: `tests/test_auf_ab_wert.py`,
  `tests/test_bewaesserung.py`, `tests/test_wecker.py`,
  `tests/test_intercom.py`, `tests/browser/test_bausteine_browser.py`.
- Stabilität der LoxPanel-App (`Waechter.kt`, Wächter und einmaliger Start in
  `ServerService`, `onRenderProcessGone` und `HaengerWaechter` in
  `KioskActivity`): kann zu Lenardo, aber nur zusammen mit `/api/health`, das
  der Wächter abfragt und das es bei ihm nicht gibt (siehe unten). Wache:
  `WaechterTest` (`gradle testDebugUnitTest`).
- PIN auf jedem Bedienweg und Musik-Favoriten (Fork #112): `nudgeSld()` und
  die übrigen Bedienwege geben `secured` und den Abbruch an `sendCmd()`
  weiter, `ui.pinMerken` steht in `_panel_export()` und `/api/meta`, und
  `blockSig()` vergleicht die Favoriten nach Name, Cover und Befehl statt nur
  nach ihrer Anzahl. Auch bei Lenardo betroffen: eingereicht als #99 (Zweig
  `up/visu-neuverbindung` mit den Widget-Abos aus Fork #112, ohne „PIN
  merken“, am 13.10.2026 auf Lenardos Stand gesetzt). Beim Abgleich auf 0.7.0 gab es an
  `nudgeSld()`, `blockSig()` und der Schlüsselliste in `_panel_export()`
  Konflikte mit #80 und #81. Kommt der Beitrag zurück, reibt sich der
  PIN-Block in `panel.html`: Im Fork stehen dort `pinMerk`, weitere Auslöser
  von `pinVergessen()` (Display aus, Nachtbeginn), ein anderer Kopfkommentar
  und `pinSenden()` mit `neu`/`halten`. Die Fork-Fassung behalten;
  `job.seite`, `pinSeite()` aus `stack`, der Abbruch einer abgelehnten PIN
  auf fremder Seite und die Rümpfe von `pinVergessen()` stehen in beiden
  gleich.
  Wachen: `tests/test_pin.py`, `tests/browser/test_pin_browser.py`,
  `test_favoriten_folgen_dem_server`, `test_abo_neuverbindung_browser.py`.
- Weitere Korrekturen des Prüfberichts (Fork #111, #113–#116): seit dem
  Abgleich vom 13.10.2026 in Upstream (#86–#92), bis auf
  `up/miniserver-verbindung` (stumme Verbindung erkennen, Zertifikat mit den
  CAs des Systems), eingereicht als #100. Kommt #100 zurück: In
  `bin/webvisu.py` gibt es `_ms_antwortfrist()` danach nur einmal, die
  Fassung mit `_ms_sekunden()`. Git meldet eine Doppelung nicht immer,
  `ruff check --select F,E9` schon (F811); beim Abgleich vom 13.10.2026 kam
  so der Import `audioserver_auth` doppelt herein.
  In `reconnect()` und `config/loxpanel.cfg.example` die Fork-Fassung
  behalten. README und `deploy/DEPLOY.md` haben die Absätze im Fork in
  anderer Umgebung (Unraid, Intercom), dort sind kleine Textkonflikte zu
  erwarten. Der Agent-Code ist gleich, `loxpanel-ctl.sh` und `preroot.sh`
  weichen nur in Kommentaren zu den Testpfaden ab. Wachen:
  `tests/test_miniserver_zugang.py`, `test_miniserver_ws.py`, `test_tls.py`,
  `test_schema_wahl.py`,
  `test_stabilitaet.py`, `test_front_abruf.py`, `test_installation.py`,
  `test_agent.py`, `test_loxberry_ctl.py`, `test_loxberry_update.py`,
  `test_loxberry_widget.py`, `test_loxberry_zeitzone.py`,
  `tests/browser/test_kachel_tasten_browser.py`.

- Korrekturen aus der Prüfliste vom 12.10.2026 (Fork #161, dazu #146 und
  #166): bei Lenardo eingereicht als #94 (APK nur mit Vorlagen), #95
  (Energiefluss mit NaN und unendlichen Werten), #96 (freie Seiten löschen),
  #97 (unbekannte Ansicht gilt als Standardprofil) und #98 (Speichern während
  einer laufenden Anfrage; nur bei Lenardo, der Fork speichert über die
  Speicherleiste mit `ansichtenSpeichern()`). Kommen sie zurück, die
  Fork-Fassung behalten: `ansicht_wirksam()` steht im Fork neben `_ui_roh()`
  mit Entwurf, bei Lenardo neben `_ui_profil()` (das im Fork entfällt);
  `pickBezuegeNeu()` nummeriert im Fork auch `ui.valueBar` um; der Kommentar
  in `syncLoxpanelAssets` nennt im Fork die Wache. Wachen:
  `tests/test_apk_inhalt.py`, `tests/test_haus.py`, `tests/test_agent.py`,
  `tests/test_profil_geloescht.py`,
  `tests/browser/test_seiten_loeschen_browser.py`,
  `tests/browser/test_speicherleiste_browser.py`.
- SIP Schritt 1 (`bin/loxone_secure.py`, `bin/sip_probe.py`,
  `secured_details()`, `/api/sip`, Reiter SIP): bei Lenardo eingereicht als
  #83 (Zweig `up/sip-zugang`), noch offen, TODO §0b. Am 13.10.2026 auf
  Lenardos Stand nach seinem Neuanfang gesetzt (vorher ohne gemeinsame Basis,
  nicht mergebar), mit der Absicherung der Digest-Anmeldung aus #127; seitdem
  ist `bin/sip_probe.py` dort und im Fork gleich. Die Stellen im Fork sind
  dieselben wie im Beitrag, damit ein Abgleich keine Konflikte bringt. Wachen:
  `tests/test_loxone_secure.py`, `test_sip_probe.py`, `test_sip.py`,
  `tests/browser/test_sip_browser.py`.
- Versionsnummer: seit 0.7.0 in Upstream (#84). Nur im Fork bleiben
  `version` in `/api/health` und die Ausnahme `!loxberry-plugin/plugin.cfg` in
  `.dockerignore` (Lenardo schließt `loxberry-plugin/` nicht aus). Wachen:
  `test_settings_und_health_nennen_die_version` in `tests/test_version.py`;
  für die Ausnahme der Probe-Build des Images in `tests.yml` (ohne sie
  scheitert `COPY loxberry-plugin/plugin.cfg` im `Dockerfile`).
- Intercom v1 und v2 (Oktober 2026): `IntercomV2` neben `Intercom` überall,
  wo Türsprechstellen vorkommen (`INTERCOM_TYPES`; Antworten, Stumm und
  Gerätezustand in `_control_item()` und `_view_control_inner()`), die Kamera
  vom Miniserver (`intercom_video()`, `_kamera_aus_details()`,
  `_intercom_video_block()`, `mjpeg_handler()`), das Kennzeichen
  `securedDetails` in `secured_details()`, `type` und `ohneSip` in `/api/sip`,
  die Hinweise im Reiter SIP und `INTERCOM_TYPEN` in `config.html`. Baut auf
  SIP Schritt 1 (#83) auf und ändert dessen Stellen (Kennzeichen, `ohneSip`,
  Hinweistext mit „Host für Audio (intern)“); geht als Nachtrag zu Lenardo,
  sobald #83 bei ihm ist. Reibt sich bei Upstream-Merges an `_control_item()`,
  `_view_control_inner()`, `api_sip()` und `mjpeg_handler()`. Wachen:
  `tests/test_intercom_v2.py`, `test_intercom_video.py`, `test_sip.py`,
  `tests/browser/test_sip_browser.py`, `test_intercom_v2` in
  `tests/browser/test_bausteine_browser.py`.
- Native Gen-1-Gegensprechen (`feature/intercom-gen1-talk`): baut auf dem
  aktualisierten PR #110 und `main` auf. `sip_call.py` und `intercom_talk.py`
  ergänzen SIP und Sitzungsverwaltung, Android übernimmt G.711-RTP mit
  AudioRecord/AudioTrack. Die native `LoxKiosk`-Brücke zeigt Sprechen/Auflegen
  nur für `Intercom`; `IntercomV2` bleibt bei der Bedienung aus #110. Beim
  Zusammenführen `_talk_credentials()`, die `intercom-talk`-Blöcke in
  Detailseite/Kamera-Pane und deren Signaturen erhalten. Kamera-, Klingel-
  und Türbefehle dürfen durch Sprechen nicht geändert werden. Fehlendes
  `audioInfo` bleibt ein Fehler; `videoInfo` liefert keinen SIP-Ersatz.
  Wachen: `tests/test_sip_call.py`, `test_intercom_talk.py`,
  `tests/browser/test_intercom_talk_browser.py`, die Intercom-Tests aus #110
  und Android-JUnit-Tests. Umfang, ursprüngliche Prüfergebnisse und
  Hardware-Abnahme: [`INTERCOM_GEN1.md`](INTERCOM_GEN1.md).

Seit 0.7.0 in Upstream und deshalb nicht mehr in der Liste (ihre Wachen
laufen weiter): `type="text"` am `.mzname`, „Spielt in 1 Raum“ und der
Ruhe-Text der Radiotasten, `catFilter` in `_panel_export()` und
`ctrltight`/`ctrlnarrow` in `updateGrid()` (#80); die allgemeinen Teile der
Detailseiten (#81); Neu laden gegen Einfrieren ohne Eintrag jede Nacht (#82);
die zwei Korrekturen zum Verlauf-Stapel (#79, von Lenardo in den Zweig von
#77 übernommen und mit #77 gemergt); die Versionsnummer (#84). Seit dem
Abgleich vom 13.10.2026 (Lenardos `main` bis `c34320c`): Uhr-Seite wegtippen
(#85); `roomCats` im Export und das Zurücksetzen beim Moduswechsel in
`renderTabMode()`, Geräte erst nach dem Schreiben übernehmen, das
Display-Kennwort bleibt auf dem Server (#86); Miniserver-Zugang erst prüfen,
dann speichern (#87); Audioserver-Kopplung (#88); Kalender-Ausnahmen (#89);
Installationsdoku (#90); Ansicht und Betriebsmodus am Linux-Agenten (#91);
LoxBerry-Sicherung und Zeitzone (#92); die `.deb`-Version aus `plugin.cfg` samt
`bin/version.json` (#93); dazu von Lenardo das `.deb` mit gzip und die
erweiterte englische Übersetzung des Konfigurators.

Bewusst nur im Fork, nicht zum Einreichen gedacht (mit Test, damit ein Sync sie
nicht still entfernt):

- Kalender- und Wetter-Tabs (`FRONT_TABS` in `bin/webvisu.py`,
  `renderFrontTab()` in `panel.html`, Fork #84; Lenardo hat Wetter und Kalender
  inzwischen als Widget-Seite): `tests/browser/test_front_tabs_browser.py`.
- Image nur nach grünen Tests: Der Job `veroeffentlichen` in
  `.github/workflows/tests.yml` baut und veröffentlicht das Image erst, wenn
  alle Prüf-Jobs desselben Laufs grün sind. Lenardos `docker-image.yml`
  veröffentlichte neben den Tests her und ist im Fork gelöscht, nicht nur
  geleert: Ändert Upstream die Datei, hält ein Konflikt den Merge an (Ablauf C,
  Schritt 3), statt dass sich die Änderung still in eine Restfassung mischt.
  Dazu gehört der Kommentar beim Build-Argument `LOXPANEL_COMMIT` im
  `Dockerfile`. Beim Abgleich auf 0.7.0 hat das gegriffen: #84 ergänzte in
  `docker-image.yml` das Build-Argument, das der Job `veroeffentlichen` schon
  übergibt. Wache: `tests/test_workflows.py`.
- Docker-Betrieb: `/api/health` für den `HEALTHCHECK` und
  `LOXPANEL_LOG_LEVEL`: `test_health_meldet_beendete_aufgabe`,
  `test_log_level` in `tests/test_unraid.py`. Seit Oktober 2026 fragt auch der
  Wächter der LoxPanel-App `/api/health` ab; geht die App-Stabilität zu
  Lenardo, gehört der Endpunkt dazu.

## Drei Fallstricke

1. **Merge-Commit-Regel:** Upstream-Syncs nie squashen/rebasen. Lokal mergen +
   `git push origin main` ist der sauberste Weg.
2. **`:latest`-Build:** Ein Push auf `main` mit eigenen Zugangsdaten baut das
   Image automatisch neu, sobald die Tests desselben Laufs grün sind (rund zehn
   Minuten). Merges über einen GitHub-Bot-Token lösen den `push`-Trigger
   **nicht** aus – dann den Lauf manuell starten (Actions → „Tests und Image“ →
   „Run workflow“ auf `main`; von anderen Zweigen veröffentlicht er nicht). War
   ein Test nur zufällig rot, startet „Re-run failed jobs“ das Veröffentlichen
   mit. Beide Re-runs, „failed jobs“ wie „all jobs“, nur am neuesten Lauf auf
   `main` starten: An einem älteren setzt das Veröffentlichen `latest` auf
   dessen Stand zurück, und wartet gerade ein neuerer Lauf, verdrängt der
   Re-run ihn (je Gruppe wartet nur einer).
3. **Identität schützen:** Nach jedem Sync prüfen, dass
   `ghcr.io/chief-wiggum1203/loxpanel` (klein), `ARCHIVEURL` auf den Fork und
   `plugin.cfg` NAME/FOLDER/AUTHOR unverändert sind.

## Abhängigkeiten

Fremder Code kommt nur festgenagelt ins Image, damit eine neue oder
manipulierte Version nicht still beim nächsten Bauen hineinrutscht:

| Quelle | Festgenagelt in | Aktualisiert durch |
|---|---|---|
| Python-Pakete, auch die mitgezogenen | `requirements-lock.txt`: genaue Versionen, jede Datei mit Prüfsumme; Image und CI installieren mit `--require-hashes` | Dependabot (Gruppe `python`), monatlich |
| Grundimage `python:3.12-slim` | `FROM …@sha256:` im `Dockerfile` | Dependabot, monatlich, nur neue Stände von 3.12 |
| GitHub Actions | `uses: …@<Commit> # vX.Y.Z` in allen Workflows | Dependabot (Gruppe `actions`), monatlich |

`requirements.txt` bleibt die Liste mit Bereichen: Danach installieren die App
(Chaquopy bringt eigene Android-Pakete mit), das `.deb` und die Anleitungen ohne
Docker, jeweils mit ihrem eigenen Python. Die Sperrliste gilt nur für Python
3.12, wie Image und CI.

**Ein Paket hinzufügen oder einen Bereich ändern:** `requirements.txt`
anpassen, dann die Sperrliste unter Python 3.12 neu erzeugen (derselbe Befehl
steht in ihrem Kopf):

```bash
python3.12 -m venv /tmp/pt && /tmp/pt/bin/pip install pip-tools
/tmp/pt/bin/pip-compile --generate-hashes --allow-unsafe --strip-extras \
    --no-emit-index-url --output-file=requirements-lock.txt requirements.txt
```

Ohne `--upgrade` bleiben alle übrigen Pakete, wie sie sind. `pip-compile` lädt
jede Datei einmal, um ihre Prüfsumme selbst zu rechnen; das dauert einige
Minuten. `tests/test_abhaengigkeiten.py` meldet eine Sperrliste, die nicht mehr
zu `requirements.txt` passt.

**Pull Requests von Dependabot** laufen durch dieselben Tests wie jede andere
Änderung; grün heißt mergen. Eine Obergrenze in `requirements.txt` (etwa
`icalendar<7`) ist Absicht: `.github/dependabot.yml` schließt die nächste
Hauptversion aus, angehoben wird sie von Hand. Sicherheitsupdates kommen davon
unabhängig sofort, wenn in den Repo-Einstellungen unter „Code security“ die
„Dependabot security updates“ an sind.

## Prüfen vor jedem Push

Die GitHub-Action „Tests und Image“ (`.github/workflows/tests.yml`) läuft auf
jedem PR, jedem Push auf `main` und jedem `v*`-Tag: Syntax, Lint
(Fehlerregeln), pytest mit Miniserver-Nachbau und Rauchtest,
Visu-/Konfigurator-Tests in Chromium, für PRs ein Probe-Build des Images. Auf
`main` und bei `v*`-Tags veröffentlicht sie danach das Image, aber nur, wenn
alles davor grün ist. Ein PR wird erst gemergt, wenn sie grün ist. Lokal
dasselbe (Einzelheiten in `CLAUDE.md`):

```bash
.venv/bin/pip install --require-hashes -r requirements-lock.txt   # Python 3.12
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/ruff check --select F,E9 bin agent tests
.venv/bin/pytest
```

Die Tests ersetzen nicht den Funktionstest an der echten Anlage nach einem
Upstream-Sync (Abschnitt oben): sie kennen nur den Nachbau.
