# LoxPanel – ToDo

Priorisierte Liste der Änderungen für den eigenen Betrieb auf Unraid. Nummern in
Klammern verweisen auf die Befunde in [`ARCHITEKTUR.md`](ARCHITEKTUR.md)
(F = Fehler, S = Sicherheit, P = Performance, W = Wartbarkeit). Aufwand:
**S** = unter einer Stunde, **M** = ein halber Tag, **L** = mehrere Tage.

Stand 16.09.2026: Die Liste wurde vollständig gegen den Code geprüft (jeder
Eintrag einzeln, Haken ignoriert). Sieben Punkte waren längst erledigt und sind
jetzt abgehakt; die dabei gefundenen echten Defekte stehen als neue Punkte
drin.

Sicherheit ist bewusst ganz unten eingeordnet: Der Server läuft nur im Heimnetz
und ist nicht von außen erreichbar. Sollte sich das ändern, rückt Block 10 nach
oben.

---

## 0. Umbau: Android-Panels ohne Agent

Ziel: Jedes Android-Gerät mit Kiosk-App ist gleichwertig zum Linux-Panel mit
Agent. Der Agent bleibt für Linux erhalten. Hintergrund und Bewertung in
[`ARCHITEKTUR.md`](ARCHITEKTUR.md), Abschnitt 8.

- [x] **Schritt 1, Visu übernimmt die Display-Steuerung.** Server schickt
      `dpmsOff`, `reloadHours` und `agent` mit der `theme`-Nachricht. Ohne Agent
      schaltet die Seite nach `dpmsOff` Sekunden das Display über die
      JavaScript-Schnittstelle von Fully Kiosk Browser aus und bei Klingel,
      Wecker, Notify und Goto wieder ein; Auto-Neustart per `location.reload`.
      Der Agent hängt seine Gerätekennung an die Kiosk-URL, damit der Server
      Agent-Panels am WebSocket erkennt. Doku in `deploy/ANDROID.md`. **S**
- [x] **Schritt 2, Geräteverwaltung an der Gerätekennung.** `GET /api/devices`
      führt Agenten, verbundene Browser und konfigurierte Geräte zusammen;
      *Einstellungen → Panels* (seit Upstream #50 *Displays*) zeigt eine
      Liste mit Typ (Agent / Fully Kiosk / Browser), Online-Status, Ansicht und Aktionen (Ansicht wechseln, Neu
      laden, Display aus/an). Browser ohne Kennung werden nach IP gelistet und
      per „Namen vergeben" benannt (Visu merkt sich den Namen, `setdevice`).
      Neu `/api/display` zum Schalten des Displays, auch aus Loxone. **M**
- [x] **Schritt 3, serverseitige Display-Treiber.** Je Gerät unter
      *Einstellungen → Panels* (heute *Displays → Betriebsmodus-Automatik &
      Display-Steuerung*) ein Treiber: Fully Kiosk Remote Admin (Port
      2323, Passwort) oder WallPanel HTTP (Port 2971), gespeichert in
      `panels.json` unter `devices[name].display`. Der Server schaltet damit
      bei `/api/display`, Klingel, Wecker, Notify, Goto und nach der
      Leerlauf-Meldung der Visu (`idle`). **M**
- [x] **Schritt 4, Einstellungen und Doku.** *Neues Panel* hat zwei Karten:
      Start-URL-Generator für Android (Gerätename, Ansicht, kopieren) und der
      SSH-Weg für Linux. `deploy/ANDROID.md` beschreibt Fully Kiosk (JS und
      Remote Admin) und WallPanel. **S**
- [ ] **Offen nach dem Umbau:** Test auf echter Hardware (Fully Kiosk und
      WallPanel), danach ggf. Feinschliff an den Bezeichnungen der
      App-Einstellungen in der Anleitung. **S**

## 0b. Upstream-Abgleich

Zuletzt eingepflegt am **04.10.2026** (`upstream/main` @ `e8acd1a`,
**Release 0.7.0**), als echter Merge-Commit. Lenardo hatte an dem Tag unsere
Beiträge #80, #81, #82 und #84 per Squash gemergt, jeden patch-gleich mit dem
eingereichten Zweig, dazu seinen #77 (Verlauf-Widget mit mehreren Bausteinen)
samt unserem #79: Den hatte er zuerst in seinen Zweig
`feature/verlauf-stapelbar` übernommen, der Stand von #77 in `main` ist
baum-gleich mit `up/verlauf-stapel`. Außerdem sein
[#78](https://github.com/Lenardo1/loxpanel/pull/78) (die APK enthält auch
`armeabi-v7a`, läuft also auch auf 32-bit-Tablets, etwa einem Galaxy Tab S2
mit Android 7), die Reparatur des APK-Builds (`setup-android` nur mit
`platform-tools`) und das README mit drei Installationswegen und Changelog
bis 0.7.0. Der Fork trägt jetzt `VERSION=0.7.0`. Sieben Konfliktdateien:
`docker-image.yml` bleibt gelöscht (#84 hatte dort das Build-Argument
`LOXPANEL_COMMIT` ergänzt, das der Job `veroeffentlichen` in `tests.yml`
schon übergibt), im `Dockerfile` bleibt der Kommentar dazu, `release.cfg` mit
0.7.0 und der `ARCHIVEURL` des Forks, `README.md` mit Lenardos drei Wegen
(der erste als Docker-Container auf Unraid, einem Docker-Host oder dem
LoxBerry), Image und Release-Link des Forks, der Roadmap-Zeile mit dem
SIP-Zugang und Lenardos Changelog. In `bin/webvisu.py`, `config.html` und
`panel.html` gilt die Fork-Fassung: Sie hatte Lenardos Zeilen schon und ist
seit Fork #101, #102 und #112 weiter (CONTRIBUTING, Fork-eigene Patches).
Jede Zeile, die Lenardo seit `415ffd5` hinzufügt, steht im Ergebnis, außer
den bewusst ersetzten (Image-Name, Release-Links, Kommentar im
`Dockerfile`, ältere Fassungen derselben Zeilen). Offen bei ihm bleibt #83
(SIP Schritt 1, siehe unten).

Davor, am **03.10.2026**, Lenardos damals offener PR #77: „Verlauf-Widget:
mehrere Bausteine stapeln“ (Zweig `feature/verlauf-stapelbar`, `364a448`)
stand als echter Merge-Commit im Fork, bevor Lenardo ihn nach `main`
brachte. Die Verlaufs-Pane zeigt damit einen oder mehrere Bausteine
untereinander, die Zeitraum-Leiste steht fest darüber (`ARCHITEKTUR.md`
§3.9). Ein Konflikt in `bin/webvisu.py` (`conn_chart`, `setchart`), sonst
Zeile für Zeile seine Änderungen. Beim Übernehmen fielen zwei Fehler auf, die
der Fork gleich behob und Lenardo als Beitrag zu #77 eingereicht hat
([#79](https://github.com/Lenardo1/loxpanel/pull/79), in seinen Zweig von
#77): Auf der Uhr-Seite wurden die Diagramme wieder unten abgeschnitten (bei
960 × 480 um 144 px), und nach einem Wechsel der Pane konnte der vorige
Stapel samt Namen stehen bleiben. Mit 0.7.0 sind beide in `main`.

Davor, am **02.10.2026** (`upstream/main` @ `415ffd5`, Version
weiterhin 0.6.0), als echter Merge-Commit. Lenardo hatte an dem Tag alle
unsere offenen Beiträge übernommen, jeden patch-gleich: #63 Sicherung, #64
Ersteinrichtung, #66 Kachel-Tasten erst beim Tippen, #71 Uhr-Seite, #72 tote
Zuweisung, #73 Textfelder, #74 „1 Betriebsart“, #75 Beschattungs-Tasten und
#76 Übersetzungs-Lücken; die App-Beiträge #65 und #67–#70 zuerst in seinen
Zweig `ci/android-apk-pipeline`, der dann als #61 nach `main` ging. Neu damit
im Fork: die **LoxPanel-App** unter `android/` (Server im Gerät, eigene
Kiosk-Anzeige, Bildschirmschoner mit Näherungssensor, Display-Abschaltung)
mit dem Workflow `android-apk.yml`, Lenardos **`.deb`-Paket** (#62) unter
`packaging/deb/` mit `deb.yml` (beide nur bei Tags `v*` oder von Hand), und
die App-Teile in Server, Visu und Konfigurator, die bisher nur in der
Test-APK steckten: die App als Kiosk-Typ (`KIOSK_APPS`) mit „Display an/aus“,
Leerlaufzeit und Präsenzmelder an ihren Schoner, nachts die echte Helligkeit
(`ARCHITEKTUR.md` Abschnitt 8). Test-APKs entstehen damit direkt aus dem
Fork: der Build nimmt `bin/`, `webfrontend/`, `deploy/` und `config/` aus dem
Arbeitsbaum. Sechs Konfliktdateien: `.dockerignore` (der Fork hält
`config/theme.json` aus dem Image), `README.md` (Lenardos Absätze zu App und
Sicherung, dazu bleiben der Unraid-Absatz und die genauere Beschreibung der
Ersteinrichtung), `bin/webvisu.py` (`/api/health` und der Unraid-Pfad in der
Sicherung bleiben), `config.html` (`TYPE_LABEL` aus #65 mit `type="text"` am
`.mzname`), `i18n.js` und `panel.html` (jeweils Lenardos Fassung aus #65).
Eine Zeile hatte Git ohne Konflikt doppelt übernommen (`DISP.presence` in
`applyDisplayCfg()`), sie steht jetzt wie bei Lenardo einmal vor
`appLeerlauf()`. Die Browser-Tests mit nachgebauter Brücke `LoxKiosk` liegen
jetzt in `tests/browser/` (Block 0c).

Davor, am **30.09.2026** (`upstream/main` @ `fba03be`, Version
weiterhin 0.6.0), als echter Merge-Commit. Darin unsere acht Beiträge
#52–#59, die Lenardo am 29.09.2026 gemergt hat, und sein eigener #60
„Verlauf-Widget: Diagramme teilen sich die Pane-Höhe, volle Breite“: In der
Verlaufs-Pane und auf einer Widget-Seite ragen die Diagramme nicht mehr
unten aus der Fläche, das SVG füllt die volle Breite und wird dafür leicht
gestreckt. #52–#59 kamen patch-gleich zurück (`README.md`, `bin/webvisu.py`
und `config.html` byte-gleich mit dem Fork). Ein Konflikt in `i18n.js`: der
verwaiste Schlüssel „Visu + rechte Fläche (je Tab wählbar).“, den der Fork
in #92 entfernt hat, bleibt draußen. #60 ließ zusammen mit #52 die
Diagramme der Uhr-Seite hochkant auf 0 px zusammenfallen; im Fork gelten
seine Regeln deshalb nur im `#frontpane` (`ARCHITEKTUR.md` §3.9), mit neuen
Prüfungen in den Browser-Tests der Split-Pane und der Uhr-Seite.

Davor, am **27.09.2026** (`upstream/main` @ `fba3e4a`,
**Release 0.6.0**), als echter Merge-Commit. Neu damit im Fork: Lenardos #51
„Widgets überall + Panel-Assistent-Ausbau“ — eine freie Seite kann statt
Kacheln ein **Widget als Vollbild-Tab** sein (`pickTabs[].widget`, im Panel
`view.widget`, `.screen.widgettab`), **Werte** (`status:`) auch als Pane 2,
**Audio** (Now Playing) als zweite Spalte der Uhr-Seite, der Begriff
„Widget“ statt „Zusatz“ in Konfigurator und Assistent und eine Übersicht der
Assistenten-Schritte. Drei Konfliktdateien: `release.cfg` (Version 0.6.0,
`ARCHIVEURL` bleibt beim Fork), `panel.html` (Lenardos `paneRawNow()`,
Widget-Seite und Audio-Push mit unserem Hochformat, den Kalender-/Wetter-Tabs
und dem Raster), `config.html` (Lenardos Wortlaut mit unseren
Hochkant-Ergänzungen, dazu seine neuen Texte; die Wahl „Springen/Filtern“
entfällt bei einer freien Seite, die ein Widget ist) — aufgelöst wie in den
Upstream-Zweigen #52–#54. In `i18n.js` wurden die verwaisten Fork-Schlüssel
zu Lenardos neuen Texten „Widget je Tab“ und „Visu + Widget je Tab – …“
umbenannt, die damit auch englisch sind. Neuer Test:
`test_widget_seite_quer_und_hochkant`.

Davor, am **26.09.2026** (`upstream/main` @ `a37c022`), als
echter Merge-Commit. Neu damit im Fork: der **Panel-Assistent** im
Konfigurator (Anzeige, Inhalt, Design, Screensaver, Aktiv-Overlay), die
**freie Auswahl mit bis zu vier Seiten** samt Name und Icon (`auswahl`,
`auswahl2` … `auswahl4`, `pickTabs` im Profil), **Tab-Icons**, der **Verlauf
als zweite Spalte der Uhr-Seite** und der neue Hauptreiter **Displays** mit
**Betriebsmodus-Assistent** (#47, #50). „Settings → Panels“ ist in diesen
Reiter umgezogen, README, `deploy/` und `ARCHITEKTUR.md` nennen den neuen
Weg. Lenardos #49 vervollständigt die englischen Übersetzungen und ersetzt
#33; die 38 Schlüssel, die der Fork schon hatte, gelten jetzt in seinem
Wortlaut. Unser Kalender-Fix #46 kam patch-gleich zurück. Fünf
Konfliktstellen, jede mit beiden Seiten aufgelöst: Der Fork behält die
Kalender-/Wetter-Tabs (#84) und die Rubrik „Sicherung“.

Davor, am 24.09.2026 (`946af6a`, Sammel-Merge #45): nur Geschichte. Die elf
Commits darin waren unsere Beiträge #34–#44 und im Fork schon enthalten.

Davor, am 19.09.2026 (`f5bdb01`, **Release 0.5.0**). Neu damit im Fork:
**Zurück-Button der Tab-Leiste exakt mittig** (links `ceil(N/2)`, rechts
`floor(N/2)`, fehlende Zelle als Abstandhalter), **`--accent` folgt der
OK-Farbe auch ohne gesetzte Panel-Grundfarbe**, und der YC-SM55P steht im
Gerätekatalog bei den 2-Pane-Geräten. Der Fork trägt seitdem ebenfalls `VERSION=0.5.0` — bewusst im
Gleichschritt mit Upstream, weil die Versionszeile sonst bei jedem Release von
Hand aufzulösen wäre; `ARCHIVEURL` zeigt weiterhin auf die Releases **dieses**
Forks.

Davor, am 18.09.2026 (`a76ed83`): **Kamera als Split-Pane** (Intercom-Livebild
mit Tür-Buttons), **gerahmte Split-Panes** mit Seiten-Snap, **zweispaltiger
Screensaver** im Querformat, **konfigurierbarer Kachelrahmen** für helle
Displays, vereinheitlichte Lautstärkeleiste, **Anlagenschema (SystemScheme)**,
Rubrik „unterstützte Geräte" und der GHCR-Login-Fallback. Dazu `LICENSE.md`:
Upstream steht seit `cade27a` unter der PolyForm Noncommercial License 1.0.0.

Neue Upstream-Releases per `git fetch upstream && git merge upstream/main`
holen, Konflikte lösen, als **Merge-Commit** nach `main` — nicht squashen,
sonst kennt der Fork die Upstream-Commits nicht und dieselben Konflikte kommen
beim nächsten Mal wieder.

- [ ] **Neu Eingepflegtes an der Anlage prüfen:** Kamera-Pane (Intercom-Bild +
      Tür-Buttons), gerahmte Split-Panes, zweispaltiger Screensaver im
      Querformat, Kachelrahmen-Einstellung, Lautstärkeleiste in beiden
      Player-Ansichten, Anlagenschema, Verlaufs-Pane nach #60 (Diagramme
      teilen sich die Höhe). **S**
- [ ] **Panel-Assistent und Displays an der Anlage prüfen:** den Assistenten
      einmal für ein neues Panel durchlaufen, freie Auswahl mit mehreren Seiten
      und Icons, Geräteliste und Display-Treiber unter *Displays*,
      Betriebsmodus-Assistent samt fertiger Loxone-Adresse, Verlauf als
      Uhr-Spalte. Geräteliste, Display-Treiber und die vier Auswahl-Seiten
      prüfen seit 02.10.2026 Browser-Tests (siehe unten), Panel-Assistent,
      Betriebsmodus-Assistent und Verlauf als Uhr-Spalte nur der Blick an der
      Anlage. **S**
- [x] **Tests für die neuen Upstream-Teile (02.10.2026):**
      `tests/browser/test_displays_browser.py` bedient den Reiter *Displays*
      wie von Hand: Geräteliste mit einem Tablet mit Kennung, einem ohne und
      einem nur konfigurierten Gerät (Typ, Zustand, Ansicht, Bildschirm),
      „Ansicht wechseln“ (das Tablet lädt sich mit dem neuen Profil neu) und
      „Namen vergeben“ (das Gerät verbindet sich mit Kennung neu, erscheint in
      Liste und Editor, behält den Namen nach dem Neuladen). Im Editor
      Display-Treiber mit vorbelegter IP und Port, Passwort, Modus,
      Automatik und Präsenzmelder; danach stimmt `panels.json`, und nach dem
      Neuladen des Konfigurators und einem Neustart des Servers steht alles
      wieder da. `tests/browser/test_auswahl_seiten_browser.py` legt vier
      Seiten mit Name, Icon und Inhalt an (Kacheln in Klickreihenfolge, eine
      über zwei Räume, eine als Wetter-Widget), speichert, lädt neu,
      bearbeitet weiter, speichert wieder und prüft die vier Seiten in der
      Visu. Gegenproben: 16 Verschlechterungen beim ersten, 12 beim zweiten
      Test, jede fällt auf, darunter der Fehler aus #47 (ohne `pickTabs` in
      `/api/meta` kennt der Editor nach dem Neuladen nur „Seite 1“). Dabei
      gefunden und behoben: Fünf Textfelder standen browserweiß im dunklen
      Konfigurator, weil ihnen `type="text"` fehlte (unter *Displays*
      Namensfeld, Modus, IP und Port, im Betriebsmodus-Assistenten das
      Namensfeld); die Tests prüfen ihren Stil mit. **M**
- [x] **Lenardos #33 (englische Übersetzungen):** kam als #49, das #33
      ersetzt. Die 38 doppelten Schlüssel sind aufgelöst, es gilt Lenardos
      Wortlaut; geprüft am wirksamen Wert, kein Text wird anders angezeigt als
      bei Upstream. **S**
- [ ] **Konfigurator auf Englisch vervollständigen:** Mit englischer
      Browsersprache bleiben im Konfigurator 164 sichtbare Textstellen deutsch,
      im Fork und bei Lenardo gleich (Chromium auf `en-US` durch alle
      Rubriken, Reiter und beide Assistenten, Stand 02.10.2026 nach
      `up/uebersetzung-luecken`). Fast alles stammt aus Teilen, die nie an die
      Übersetzung angeschlossen wurden: *Übersicht*, Panel-Assistent,
      *unterstützte Geräte* und die Hilfetexte unter *Darstellung*. Vier
      Ursachen: Texte ohne `T()` oder `data-i18n`; Absätze mit `<b>` oder
      `<code>`, die `autoChrome()` nicht anfasst, weil es nur Elemente ohne
      Kind-Elemente übersetzt; 21 Texte mit Katalog-Eintrag, die kein
      übersetztes Element erreichen (etwa „Raum-Panel“, „Schriftfarbe (Name)“);
      und `renderEditor()` ruft `I18N.autoChrome()` mit einer engeren Liste auf
      und schaltet damit `.lead`, `.muted`, `[data-i18n]` und weitere für den
      Rest der Seite ab, wovor `bindPick()` selbst warnt. Dazu verwaiste
      Schlüssel, 10 in beiden Katalogen (Vorgänger heutiger Texte, etwa
      „Panels & Kacheln“, „Kacheln pro Zeile“) und 6 nur bei Lenardo: erst die
      Nachfolger übersetzen, dann löschen. Vorher mit Lenardo abstimmen, die
      Übersetzungen kamen zuletzt von ihm (#49). Am Ende ein Browser-Test, der
      auf Englisch keinen deutschen Text mehr findet. **L**
- [x] **Tote Zuweisung bei Lenardo eingereicht:**
      [#72](https://github.com/Lenardo1/loxpanel/pull/72), Zweig
      `up/wetter-tote-zuweisung`, ein Commit auf `upstream/main`. Ohne
      `t_jetzt = t_roh + versatz` (ruff F841) ist `bin/loxone_weather.py` dort
      gleich wie im Fork, und `ruff --select F,E9` über `bin/` und `agent/` ist
      ohne Fund. Am 02.10.2026 gemergt. **S**
- [x] **Weiße Textfelder bei Lenardo eingereicht:**
      [#73](https://github.com/Lenardo1/loxpanel/pull/73), Zweig
      `up/textfelder-dunkel`: die vier Felder unter *Displays* ohne
      `type="text"` (Namensfeld, Modus, IP, Port). Gegen seinen Stand laufen
      die Browser-Tests dazu mit dem Zweig grün, ohne ihn scheitern genau die
      Feldstil-Prüfungen. Am 02.10.2026 gemergt. **S**
- [x] **Namensfeld im Betriebsmodus-Assistenten bei Lenardo eingereicht:**
      `.mzname` hat denselben Fehler wie die Felder aus #73. Gewartet wurde
      auf #65, das dieselbe Zeile ändert; seit 02.10.2026 ist es übernommen.
      Am 03.10.2026 eingereicht als
      [#80](https://github.com/Lenardo1/loxpanel/pull/80), Zweig `up/kleine-fehler`,
      zusammen mit vier weiteren kleinen Fehlern, siehe Upstream-Beiträge. Im
      Fork ist er drin, `test_geraeteliste_umschalten_und_benennen` prüft
      ihn. Am 04.10.2026 gemergt (0.7.0). **S**
- [x] **Uhr-Seiten-Fix zu #60 bei Lenardo eingereicht:**
      [#71](https://github.com/Lenardo1/loxpanel/pull/71), Zweig
      `up/verlauf-uhrseite`. In seinem `main` fallen die Verlaufs-Diagramme
      der Uhr-Seite hochkant auf 0 px zusammen (#52 und #60 zusammen). Mit dem
      Zweig gelten die drei Fit-Regeln aus #60 nur im `#frontpane`, und auf der
      Uhr-Seite schrumpfen die Diagramme, wenn der Kasten nicht reicht. Eine
      unabhängige Gegenprüfung hatte gezeigt, dass die erste Fassung (nur
      `#frontpane`, Stand des Forks vom 30.09.) quer bei drei Diagrammen das
      dritte abschnitt (bei 960 × 480 164 px); geprüft mit
      `test_uhrseite_verlauf_schrumpft_statt_abzuschneiden`. Gegen Lenardos
      `main` laufen die vier Verlaufs-Tests aus dem Fork mit dem Zweig grün,
      ohne ihn scheitern zwei. Am 02.10.2026 gemergt, seitdem kein
      Fork-eigener Patch mehr. **S**
- [x] **Auf/Ab auf der Beschattungs-Kachel bei Lenardo eingereicht:**
      [#75](https://github.com/Lenardo1/loxpanel/pull/75), Zweig
      `up/beschattung-tasten`, ein Commit auf `up/kachel-tasten` (#66), weil
      die Tasten erst seit dort beim Tippen auslösen. Dieselbe Änderung wie im
      Fork, samt `placeCtrls()` für enge Kacheln. Gegen den Zweig bestehen die
      14 Tests aus dem Fork, ohne die Änderung scheitern 10, darunter die
      Player-Tasten in 2x3 und 3x3, die bei Lenardo schon abgeschnitten
      wurden. Am 02.10.2026 nach #66 gemergt. **S**
- [x] **Übersetzungs-Lücken bei Lenardo eingereicht:**
      [#76](https://github.com/Lenardo1/loxpanel/pull/76), Zweig
      `up/uebersetzung-luecken`, ein Commit auf `upstream/main`. Drei Stellen, an denen die englische Übersetzung gewollt
      ist, aber nicht ankommt: Der Link „Bausteintypen der Anlage anzeigen“
      unter *Settings → Miniserver* samt Erläuterung stand in keinem
      übersetzten Element (jetzt `data-i18n`); vier `T()`-Texte hatten keinen
      Eintrag („Werte“, „Kein passender Baustein“, die zwei Hinweise des
      Assistenten zu Widget-Seiten); und „Baustein“ stand zweimal im Katalog,
      der spätere Eintrag „block“ überschrieb „Block“. Im Fork gleich, dazu
      `tests/test_uebersetzung.py`: Jeder `T()`-Text und jedes
      `data-i18n`-Element in `config.html` hat einen englischen Eintrag, und
      kein Schlüssel hat zwei verschiedene Übersetzungen. Gegen Lenardos Stand
      bestehen die drei Tests mit dem Zweig, ohne ihn scheitern alle drei; mit
      englischer Browsersprache erscheinen der Link und seine Erläuterung dann
      englisch. Am 02.10.2026 gemergt. **S**
- [x] **„1 Betriebsart“ bei Lenardo eingereicht:**
      [#74](https://github.com/Lenardo1/loxpanel/pull/74), Zweig
      `up/weckzeit-einzahl`, ein Commit auf `upstream/main`. Lassen sich die Betriebsmodi einer Weckzeit nicht zu Namen
      auflösen, zeigt die Wiederholung ihre Anzahl; bei genau einem stand dort
      „1 Betriebsarten“. Der Fork hat die Einzahl seit #82,
      `test_weckzeiten_liste` prüft sie: gegen Lenardos Stand mit dem Zweig
      grün, ohne ihn rot. Am 02.10.2026 gemergt. **S**
- [ ] **Icon-Bibliothek darf das Tippen nicht unterbrechen (Assistent, dann
      Lenardo):** Der Editor einer freien Seite lädt die Icon-Bibliothek nach
      (`/api/loxicons`) und baute danach den ganzen Editor neu auf. Wer gerade
      den Namen tippte, verlor Fokus und Buchstaben; auf der CI von #99 ging so
      der Name der ersten Seite verloren. Im Fork füllt `pickIcoGridNeu()` jetzt
      nur das Icon-Raster neu, samt laufender Suche und Icon-Wahl, geprüft mit
      `test_name_tippen_waehrend_die_icon_bibliothek_laedt` (scheitert ohne die
      Änderung, ebenso ohne Suche oder ohne neu gebundene Knöpfe). Offen: Der
      Panel-Assistent hat dasselbe Muster (`wzIcoGrid()` ruft nach dem Laden
      `wzRender()` für den ganzen Schritt, dort tippt man die Seitennamen).
      Danach beides als ein Beitrag bei Lenardo einreichen, der Code ist von
      ihm (#47). **S**
- [x] **Lenardos offene PRs #61 und #62 angesehen** (01.10.2026): #61, die
      Android-App mit eingebautem Server, ist unser Weg ohne Unraid und wird
      mitentwickelt (Block 0c). #62, das `.deb`-Paket, verfolgen wir nicht
      weiter. Lenardo hat beide am 02.10.2026 gemergt, seitdem liegen
      `android/` und `packaging/deb/` auch im Fork. **S**
- [x] **Allgemein nützliche Fork-Teile Upstream anbieten:** die sieben
      Bausteintypen und `/api/types` sind in Upstream angekommen. Das
      Unraid-Template bleibt bewusst fork-eigen (siehe
      [`CONTRIBUTING.md`](CONTRIBUTING.md), Spalte „Nur in den Fork"), damit
      ist der Punkt abgeschlossen. **M**

### Upstream-Beiträge

Stand 04.10.2026. **In `upstream/main`** sind die Tabelle weiter unten und
#34–#44 über unseren Sammel-PR #45 (Zweig `up/sammel`). **Eingereicht und
offen** ist noch ein Beitrag vom 03.10.2026, ein Commit auf `main`
(`415ffd5`). Er sagt Lenardo im Text, was als Schritt 2 und 3 kommt. Gegen
seinen Stand vom 03.10.2026 bestanden die SIP-Tests aus dem Fork.

| PR | Zweig | Inhalt |
|---|---|---|
| [#83](https://github.com/Lenardo1/loxpanel/pull/83) | `up/sip-zugang` (`e424371`) | SIP Schritt 1: Zugang der Intercom aus den gesicherten Details (Command Encryption), Prüfung der Türstation (OPTIONS mit Digest), Reiter *Settings → SIP* statt „Coming soon“ mit Diagnose und Hinweis |

- [ ] **#83 auf 0.7.0 neu aufsetzen:** Seit Lenardos README-Commit
      `e8acd1a` geht `up/sip-zugang` nicht mehr konfliktfrei auf seinen
      `main`: Beide ändern die Roadmap-Zeile zum Gegensprechen (Probe mit
      `git merge-tree upstream/main e424371`, nur `README.md` im Konflikt;
      Server, Konfigurator und Übersetzungen gehen ohne). Den Commit auf
      `upstream/main` neu aufsetzen, die Zeile wie im Fork („SIP-Client in der
      LoxPanel-App für Android; Zugang und Prüfung der Türstation gibt es
      schon“, die Bausteinzeile wie bei Lenardo ohne AudioZoneV2), die
      SIP-Tests aus dem Fork gegen den neuen Zweig laufen lassen und ihn mit
      `--force-with-lease` pushen; der PR folgt dem Zweig. **S**

**Vorbereitet, noch nicht eingereicht** (04.10.2026): elf Zweige, jeder auf
`upstream/main` (`e8acd1a`, 0.7.0) und im Fork auf GitHub. Sie stammen aus Fork
#107 und den Korrekturen des Prüfberichts (Fork #111–#116). Was nur der Fork
hat, fehlt darin: Tests, `docs/ARCHITEKTUR.md`, Unraid, „PIN merken“ und die
fork-eigenen Bausteine. Jeder Zweig ist gegen Lenardos Code gegengeprüft: Die
Fork-Tests lagen vorübergehend auf dem Zweig, mit der Änderung grün, ohne sie
rot, keiner neu rot; das `.deb` prüfte ein Bau-Skript mit dem echten
`build.sh`. Der PR geht vom Fork-Zweig gegen `Lenardo1/Loxpanel:main`;
Titel und Text hat der Besitzer.

| Zweig | Fork | Inhalt |
|---|---|---|
| `up/saver-wegtippen` (`9c27852`) | #107 | Uhr-Seite wegtippen löst die Kachel darunter nicht mehr aus: Loslassen, `click` und Langdruck derselben Berührung werden bis zur nächsten verschluckt (iPad/Safari, wenn der Finger kurz liegen bleibt) |
| `up/konfig-speichern` (`7aeae0d`) | #111 | Kategorie-Tabs eines Raum-Panels (`roomCats`) im Export an den Konfigurator, Geräte erst nach erfolgreichem Schreiben übernehmen, Display-Kennwort verlässt den Server nicht |
| `up/miniserver-zugang` (`ed064f3`) | #111, #116 | Miniserver-Zugang erst prüfen, dann speichern (abgelehnt: nichts gespeichert, nicht erreichbar: gespeichert mit Warnung), `miniserver.response_timeout`; das LoxBerry-Widget zeigt die Antwort richtig an |
| `up/visu-neuverbindung` (`635ea4c`) | #112 | Widget-Abos nach einer Neuverbindung, Musik-Favoriten folgen dem Server, PIN auf jedem Bedienweg (ohne „PIN merken“), eine PIN-Abfrage und ihr Ergebnis gehören zur Seite, auf der getippt wurde |
| `up/miniserver-verbindung` (`2337507`) | #113 | Stumme Verbindung erkennen (Fristen, keepalive, `miniserver.keepalive_interval`), „Zertifikat prüfen“ lädt die Standard-CAs |
| `up/audioserver-kopplung` (`b026632`) | #113 | Ein HTTP-Fehler gilt nicht dauerhaft als ungekoppelt, der Raumfavorit meldet Sendefehler |
| `up/kalender-ausnahmen` (`377b340`) | #113 | Ein verschobener Serientermin ersetzt das Original, eine Serie ohne Zeitzone bleibt nach der Zeitumstellung in Ortszeit |
| `up/installdoku` (`bdc7fcd`) | #114 | Pakete aus `requirements.txt`, Vorrang des gespeicherten Zugangs, keine feste glibc-Grenze für `cryptography` |
| `up/agent-ansicht` (`5f6f34d`) | #115 | „Ansicht wechseln“ erreicht den Linux-Agenten, die Ansicht übersteht Neustarts, ein abgestürztes Chromium startet neu |
| `up/loxberry-sicherung` (`61bfd1d`) | #116 | Wiederherstellen prüft das Backup, Sicherungen überleben Plugin-Updates, der Container übernimmt die Zeitzone des LoxBerry |
| `up/deb-version` (`4f2f1b7`) | – | Das `.deb` nimmt die Version aus `loxberry-plugin/plugin.cfg` statt fest aus `control` (Tag-Prüfung, Aufräumen bei Abbruch) und zeigt Version, Commit und Bauzeit im Konfigurator (`build.sh` schreibt `bin/version.json` ohne Python). Nur bei Lenardo, der Fork entwickelt das `.deb` nicht weiter |

Beim Einreichen auf die Reihenfolge achten:
- `up/miniserver-zugang` und `up/miniserver-verbindung` bringen beide
  `_ms_antwortfrist()` und `response_timeout` mit. Git meldet Konflikte in
  `reconnect()` und `loxpanel.cfg.example`, fügt die Funktion aber still
  doppelt ein. Wer als Zweiter gemergt wird, auf den neuen `upstream/main`
  setzen, nur die Fassung mit `_ms_sekunden()` behalten und
  `ruff check --select F,E9 bin` laufen lassen; Lenardo hat keine Lint-CI.
- `up/installdoku` und `up/miniserver-verbindung` ändern denselben
  README-Absatz („Zugangsdaten per Env …“). Der Konflikt ist rein textlich,
  beide Sätze bleiben.
- Alle anderen Paare gehen konfliktfrei auf seinen `main` (`git merge-tree`).

- [ ] **Vor `up/visu-neuverbindung` an der Anlage prüfen:** Unter PIN geht ein
      Musik-Favorit als `sps/ios/…/roomfav/play/{n}` über den Miniserver,
      nicht über die Verbindung zum Audioserver; bei Favoriten aus dem
      Audioserver-Kanal ist `n` die Item-id. Geprüft ist das nur gegen den
      Nachbau, der PR-Text sagt das. Dazu einmal Regler, Favorit und
      Türöffner unter PIN an einer gesicherten Zone mit gekoppeltem
      Audioserver. Dasselbe gilt für den Fork. **S**
- [ ] **Nach jedem Merge bei Lenardo:** Zeile in die Tabelle der gemergten
      Beiträge unten, beim nächsten Abgleich (Ablauf C) die Hinweise unter
      „Fork-eigene Patches“ in `CONTRIBUTING.md` beachten und den Eintrag dort
      auf „in Upstream“ setzen, den Zweig im Fork löschen.

Fork #108 (Datum der Wetter-Vorschau bleibt eng einzeilig) geht nicht mit:
Er sitzt in `wetterEinpassen()`, das zu „Pane 2 nutzt ihre Fläche“ gehört
und bei Lenardo fehlt.

Noch nicht reif zum Einreichen: die vier Bausteine (erst die Prüfung an der
Anlage, §8.1), die Stabilität der App (braucht `/api/health` und einen Test
auf dem Gerät), „Pane 2 nutzt ihre Fläche“ (baut auf den fork-eigenen
Wetter- und Kalender-Tabs auf, für Lenardo erst auf seinen Wetter-Aufbau
umbauen), Kachel-Aufbau, automatisches Raster und Schriften (erst
vorschlagen) und die Icon-Bibliothek (oben).

| PR | Inhalt |
|---|---|
| [#13](https://github.com/Lenardo1/loxpanel/pull/13) | Struktur-Änderungen live übernehmen |
| [#15](https://github.com/Lenardo1/loxpanel/pull/15) | Kalender-Zeitzone + eingefrorene Statuszeilen |
| [#19](https://github.com/Lenardo1/loxpanel/pull/19) | Nachtmodus (Dimmen + freier Auslöser) |
| [#20](https://github.com/Lenardo1/loxpanel/pull/20) | Panel-Theme aus einer Grundfarbe |
| [#21](https://github.com/Lenardo1/loxpanel/pull/21) | Nur senden, was sich geändert hat |
| [#23](https://github.com/Lenardo1/loxpanel/pull/23) | Positionsring auf der Kachel |
| [#24](https://github.com/Lenardo1/loxpanel/pull/24) | Wetter vom Loxone-Wetterserver |
| [#25](https://github.com/Lenardo1/loxpanel/pull/25) | Split-Pane: schlanke Scrollleiste |
| [#27](https://github.com/Lenardo1/loxpanel/pull/27) | Raum als Startseite (Raum-Direkt-Tab) + Tab-Reihenfolge |
| [#30](https://github.com/Lenardo1/loxpanel/pull/30) | Positionsring: Strichstärke regelbar, gleitend, Fahrt auf der Kachel |
| [#31](https://github.com/Lenardo1/loxpanel/pull/31) | Kalender: ein Aussetzer der Quelle löscht die Termine nicht mehr |
| [#32](https://github.com/Lenardo1/loxpanel/pull/32) | Beschattung: Fahrtrichtung als Verb |
| [#45](https://github.com/Lenardo1/loxpanel/pull/45) | Sammel-PR: #34–#44 nacheinander auf einem Zweig, Konflikte dort aufgelöst, von Lenardo unverändert gemergt |
| [#46](https://github.com/Lenardo1/loxpanel/pull/46) | Kalender: Wetter-Push löst keinen Abruf mehr aus, Retry-After wird beachtet (Fork #87), am 25.09.2026 per Squash gemergt |
| [#52](https://github.com/Lenardo1/loxpanel/pull/52) | Hochformat: Split übereinander, „Screen füllen“ nach unten, Uhr-Seite mit zweiter Fläche unten, Konfigurator und Assistent (Fork #91, #92) |
| [#53](https://github.com/Lenardo1/loxpanel/pull/53) | Sprungmarken: Sprung rutscht nicht mehr auf die Folgeseite, Gruppe leuchtet auf, Filter-Modus als Option (Fork #93) |
| [#54](https://github.com/Lenardo1/loxpanel/pull/54) | Assistenten: ✕ und Esc, Betriebsmodus-Assistent benennt Geräte ohne Namen, `?device=<name>` sichtbar (Fork #93) |
| [#55](https://github.com/Lenardo1/loxpanel/pull/55) | Energiefluss: Speicher-Vorzeichen richtig herum, schließt Issue [#14](https://github.com/Lenardo1/loxpanel/issues/14) (Fork #94) |
| [#56](https://github.com/Lenardo1/loxpanel/pull/56) | Alte Raumregelung (`IRoomController`, IRC v1) mit Kachel und Detailseite (Fork #94) |
| [#57](https://github.com/Lenardo1/loxpanel/pull/57) | Betriebsart der Raumregelung (V2 und alt) umschaltbar, beim V2 kein angenommener Komfortwert (Fork #95) |
| [#58](https://github.com/Lenardo1/loxpanel/pull/58) | Hausverbrauch aus der Bilanz statt „Verbrauch 0 W“ (Fork #95) |
| [#59](https://github.com/Lenardo1/loxpanel/pull/59) | Nicht Übernommenes beim Speichern melden (Fork #95, #96) |
| [#63](https://github.com/Lenardo1/loxpanel/pull/63) | Sicherung: Einstellungen herunterladen und wieder einspielen (Fork #98) |
| [#64](https://github.com/Lenardo1/loxpanel/pull/64) | Ersteinrichtung: Panel zeigt, wo der Konfigurator zu öffnen ist; Konfigurator führt zum Miniserver (Fork #98) |
| [#65](https://github.com/Lenardo1/loxpanel/pull/65) | LoxPanel-App: Display wecken und Präsenzmelder (in `ci/android-apk-pipeline`, mit #61 in `main`) |
| [#66](https://github.com/Lenardo1/loxpanel/pull/66) | Kachel-Tasten und Favoriten lösen erst beim Tippen aus, Wischen scrollt |
| [#67](https://github.com/Lenardo1/loxpanel/pull/67) | LoxPanel-App: Nachtmodus über die echte Display-Helligkeit (wie #65) |
| [#68](https://github.com/Lenardo1/loxpanel/pull/68) | LoxPanel-App: zuletzt angezeigte Ansicht nach Neustart wieder laden (wie #65) |
| [#69](https://github.com/Lenardo1/loxpanel/pull/69) | Android-APK: Python-Pakete aus `requirements.txt` (wie #65) |
| [#70](https://github.com/Lenardo1/loxpanel/pull/70) | Android-APK: Release mit festem Schlüssel, Version aus `plugin.cfg` (wie #65) |
| [#71](https://github.com/Lenardo1/loxpanel/pull/71) | Uhr-Seite: Verlauf fällt hochkant nicht mehr auf 0 px zusammen |
| [#72](https://github.com/Lenardo1/loxpanel/pull/72) | Wetterserver: tote Zuweisung `t_jetzt` entfernt |
| [#73](https://github.com/Lenardo1/loxpanel/pull/73) | Konfigurator: Textfelder unter *Displays* nicht mehr browserweiß |
| [#74](https://github.com/Lenardo1/loxpanel/pull/74) | Weckzeiten: „1 Betriebsart“ statt „1 Betriebsarten“ |
| [#75](https://github.com/Lenardo1/loxpanel/pull/75) | Auf/Ab auf der Beschattungs-Kachel |
| [#76](https://github.com/Lenardo1/loxpanel/pull/76) | Konfigurator auf Englisch: Link zu `/api/types`, vier Widget-Texte, „Block“ (Fork #99) |
| [#79](https://github.com/Lenardo1/loxpanel/pull/79) | Zu #77: Uhr-Seite schneidet nicht ab, kein Diagramm des vorigen Stapels nach einem Wechsel der Pane (in Lenardos Zweig `feature/verlauf-stapelbar`, mit #77 in `main`) |
| [#80](https://github.com/Lenardo1/loxpanel/pull/80) | Kleine Fehler: Namensfeld `.mzname`, „1 Raum“, Ruhe-Text der Radiotasten, `catFilter` im Export an den Konfigurator, `ctrltight`/`ctrlnarrow` in `updateGrid()` |
| [#81](https://github.com/Lenardo1/loxpanel/pull/81) | Detailseiten: volle Seiten überlappen nicht mehr (Sauna bei 480 × 480), halbe Schritte an Schiebereglern, Weckzeiten-Liste folgt Änderungen |
| [#82](https://github.com/Lenardo1/loxpanel/pull/82) | Neu laden gegen Einfrieren: ohne Eintrag jede Nacht um 3 Uhr, nur auf der Uhr-Seite |
| [#84](https://github.com/Lenardo1/loxpanel/pull/84) | Version, Commit und Bauzeit in der Seitenleiste des Konfigurators und als `versionName` der APK (`bin/version.json` aus Gradle und Dockerfile) |

#52–#59 hat Lenardo am 29.09.2026 per Squash gemergt; beim Abgleich am
30.09.2026 kamen sie patch-gleich zurück. #63–#76 hat er am 02.10.2026
gemergt, #65 und #67–#70 über seinen Zweig `ci/android-apk-pipeline` (#61);
beim Abgleich am selben Tag kamen alle patch-gleich zurück. #80–#82 und #84
hat er am 04.10.2026 per Squash gemergt, #79 zuvor in seinen Zweig von #77,
der als #77 nach `main` ging; beim Abgleich am selben Tag kamen #80–#82 und
#84 patch-gleich zurück, #77 baum-gleich mit `up/verlauf-stapel`.

Über #45 übernommen:

| PR | Zweig | Inhalt |
|---|---|---|
| [#34](https://github.com/Lenardo1/loxpanel/pull/34) | `up/kleinigkeiten` | `ValueError` bei leerer `LOXPANEL_MS_PORT`; veralteter `/settings`-Hinweis |
| [#35](https://github.com/Lenardo1/loxpanel/pull/35) | `up/raumtab-leiste` | Raum-Tab in einer mehrteiligen Leiste sperrt die übrigen Seiten aus (steckt in #36) |
| [#36](https://github.com/Lenardo1/loxpanel/pull/36) | `up/eigene-auswahl` | Freie Bausteinauswahl, ganzes Feature |
| [#37](https://github.com/Lenardo1/loxpanel/pull/37) | `up/raumzeile-kontrast` | Raumzeile tritt zurück und schafft wieder AA (Fork #63) |
| [#38](https://github.com/Lenardo1/loxpanel/pull/38) | `up/kalender-abos` | Kalender: mehrere Abos, mehrtägige Termine, vier Parser-Fehler (Fork #66, #67, #74) |
| [#39](https://github.com/Lenardo1/loxpanel/pull/39) | `up/uhrseite-spalte` | Uhr-Seite: rechte Spalte wählbar (Fork #68–#70) |
| [#40](https://github.com/Lenardo1/loxpanel/pull/40) | `up/anzeige-skalierung` | Anzeigegröße und Skalierung (Fork #71, #72) |
| [#41](https://github.com/Lenardo1/loxpanel/pull/41) | `up/energiefluss-icons` | Energiefluss: Loxone-Icons sitzen auf Safari, iPad und in WebViews wieder in ihren Kreisen (Fork #77) |
| [#42](https://github.com/Lenardo1/loxpanel/pull/42) | `up/kalender-wochentage` | Monatskalender: Tage stehen wieder unter dem richtigen Wochentag (F16 aus Fork #84) |
| [#43](https://github.com/Lenardo1/loxpanel/pull/43) | `up/token-stabilitaet` | Miniserver-Token erneuern, Befehlsfehler im Panel, kleinere Stabilitätsfehler (Fork #81) |
| [#44](https://github.com/Lenardo1/loxpanel/pull/44) | `up/verlaeufe` | Verlaufs-Diagramme: Detailseite, Split-Hälfte, Mini-Verlauf in der Kachel (Fork #78–#80, #82) |

- [ ] **#34–#44 bei Lenardo schließen, danach die Zweige löschen.** #45
      enthält ihre Commits neu aufgesetzt, mit anderen Kennungen; GitHub
      markiert die Einzel-PRs deshalb nicht selbst als gemergt. Nachsehen, ob
      Lenardo sie geschlossen hat, offene mit Verweis auf #45 schließen. Erst
      dann die elf Zweige aus der Tabelle und `up/sammel` im Fork löschen: Ein
      gelöschter Zweig schließt seinen offenen PR ohne Hinweis. Geprüft am
      25.09.2026: Der Inhalt aller zwölf steckt in `upstream/main`, und
      Lenardos `refs/pull/34`–`45` halten die Commits, auch nach dem Löschen.
      Am 02.10.2026 hatte keiner von #34–#44 mehr eine Merge-Referenz, sie sind
      also geschlossen oder nicht mehr mergebar; vor dem Löschen kurz auf
      GitHub nachsehen.
      Die Session-Umgebung darf keine Zweige löschen (HTTP 403), das geht nur
      von Hand. **S**
- [ ] **Zweige der gemergten Beiträge löschen:** `up/kalender-wetterpush`
      (#46) und die acht Zweige von #52–#59: `up/hochformat-split`,
      `up/sprungmarken`, `up/assistent-ausweg`, `up/speicher-vorzeichen`,
      `up/raumregelung-v1`, `up/betriebsart`, `up/hausverbrauch`,
      `up/speichern-meldung`. Dazu seit 02.10.2026 die Zweige von #63–#76:
      `up/sicherung`, `up/ersteinrichtung`, `up/apk-display-wecken`,
      `up/apk-praesenz`, `up/kachel-tasten`, `up/apk-nachthelligkeit`,
      `up/apk-start-adresse`, `up/apk-requirements`, `up/apk-signatur`,
      `up/verlauf-uhrseite`, `up/wetter-tote-zuweisung`,
      `up/textfelder-dunkel`, `up/weckzeit-einzahl`, `up/beschattung-tasten`,
      `up/uebersetzung-luecken`. Seit 04.10.2026 dazu die Zweige von #79–#82
      und #84: `up/verlauf-stapel`, `up/kleine-fehler`, `up/detailseiten`,
      `up/neuladen-nachts`, `up/versionsnummer`. Alle PRs sind gemergt, das
      Löschen schließt nichts mehr; Lenardos `refs/pull/<n>/head` halten die
      Commits. Geht nur von Hand (siehe oben). **S**

Für den nächsten Beitrag wieder genauso vorgehen: EIN Commit direkt auf
`upstream/main` aufsetzen, damit GitHub Titel und Beschreibung selbst füllt,
und über diesen Link einreichen:
`https://github.com/Lenardo1/loxpanel/compare/main...CHief-Wiggum1203:Loxpanel:<zweig>?expand=1`
Bei gestapelten Zweigen mit mehreren Commits füllt GitHub nichts aus; Titel
und Text dann aus der Meldung des obersten Commits übernehmen und oben
vermerken, auf welchem PR er aufsetzt. Hängen mehrere offene Beiträge an
denselben Stellen, hat sich ein Sammel-PR wie #45 bewährt: die Zweige
nacheinander auf einen Zweig bringen, Konflikte dort einmal auflösen.

Der Fork ist mit `upstream/main` gleichgezogen (`e8acd1a`, Release 0.7.0,
Stand 04.10.2026).

## 0c. Ohne Unraid: Lenardos Android-App mitentwickeln

Entscheidung vom 01.10.2026: Unraid soll wegfallen. Neue Panels und Tablets
laufen mit Android, und auf jedem Gerät läuft LoxPanel als App, die direkt mit
dem Miniserver spricht: Lenardos
[#61](https://github.com/Lenardo1/loxpanel/pull/61) (Server per Chaquopy im
Gerät, eigene Kiosk-Anzeige). Wir bauen keine eigene App, sondern entwickeln
seine mit. Seit 02.10.2026 ist sie in seinem `main` und mit dem Abgleich unter
`android/` auch im Fork; neue Beiträge gehen deshalb wie alle anderen als ein
Commit auf `upstream/main`, nicht mehr in seinen Zweig
`ci/android-apk-pipeline`. Nicht weiter verfolgt: das `.deb`
([#62](https://github.com/Lenardo1/loxpanel/pull/62), liegt seit dem Abgleich
unter `packaging/deb/`), weil Debian 11 seit dem 31.08.2026 keine
Sicherheitsupdates mehr bekommt, und eine iPad-App.

Geräte: das Portworld YC-SM41P mit **Android 13** bestellen. Android 11 bringt
das WebView 83 vom Mai 2020 mit, darauf liegen Bildschirmschoner, Uhr-Seite und
PIN-Feld der Visu falsch und Abstände fehlen; die Visu braucht etwa Chrome 88,
Android 13 bringt 101 bis 109. Tablets mit Google Play halten ihr WebView
selbst aktuell.

- [x] **Drei weitere Beiträge zu #61 bei Lenardo eingereicht.** Je ein
      Commit auf seinem `ci/android-apk-pipeline` (`ad5fcd6`), am 01.10.2026
      gebaut und geprüft, zusammen konfliktfrei. Der vierte,
      `up/apk-display-wecken` (Klingel, Notify, Goto, Wecker und der Server
      schalten den Schoner der App; `LoxKiosk` bekommt `turnScreenOn`,
      `turnScreenOff` und `isScreenOn` wie Fully), steckt in #65 (siehe
      Präsenzmelder unten).

  | PR | Zweig | Inhalt |
  |---|---|---|
  | [#68](https://github.com/Lenardo1/loxpanel/pull/68) | `up/apk-start-adresse` | Die App merkt sich die zuletzt angezeigte Ansicht statt fest `?panel=default`; Port und Adresse an einer Stelle (`Visu.kt`) |
  | [#69](https://github.com/Lenardo1/loxpanel/pull/69) | `up/apk-requirements` | Python-Pakete aus `requirements.txt` statt eigener Liste (das Gerät bekam `icalendar` 7.3.0 statt 6.3.2) |
  | [#70](https://github.com/Lenardo1/loxpanel/pull/70) | `up/apk-signatur` | Release mit festem Schlüssel aus den Repo-Secrets, Version aus `loxberry-plugin/plugin.cfg`, Tag-Prüfung im Workflow |

  Lenardo hat alle drei am 02.10.2026 in seinen Zweig gemergt, der mit #61
  nach `main` ging; mit dem Abgleich am selben Tag sind sie im Fork. **S**
- [ ] **Mit Lenardo klären:** den Paketnamen vor dem ersten echten Einsatz
      festlegen (heute `com.loxpanel.spike`; ein späterer Wechsel heißt
      Neuinstallation und damit Konfiguration weg) und den Signierschlüssel
      anlegen (Anleitung in `android/README.md`, Abschnitt „Version und
      Release-Signierung“). **S**
- [x] **Präsenzmelder bei Lenardo eingereicht:**
      [#65](https://github.com/Lenardo1/loxpanel/pull/65) mit beiden Commits,
      `up/apk-display-wecken` und darauf `up/apk-praesenz` (braucht dessen
      `turnScreenOn` und `turnScreenOff`). Dieselbe Funktion wie im Fork, dazu
      die Kopplung an die App: Solange jemand da ist, gibt die Visu ihr
      `LoxKiosk.setDisplayOff(0)`, sonst dunkelte ihr Schoner trotz
      Anwesenheit ab; wird der Raum leer, wieder die Leerlaufzeit und gleich
      `turnScreenOff()`. Der Hinweis unter *Displays* nennt die LoxPanel-App.
      Die Kopplung baut sich selbst neu auf, sobald Geräte oder Struktur
      ersetzt sind (`_presence_quelle`), die Reihenfolge der Beiträge bei
      Lenardo ist also egal. Alle sieben Beiträge sind zusammen konfliktfrei;
      auf dem Gesamtstand laufen die Fork-Tests zu Präsenz, Ersteinrichtung
      und Sicherung (89) und ein Test mit nachgebauter `LoxKiosk`-Brücke.
      **S**
- [x] **Nachtmodus über die echte Display-Helligkeit bei Lenardo eingereicht:**
      [#67](https://github.com/Lenardo1/loxpanel/pull/67), Zweig
      `up/apk-nachthelligkeit`, ein Commit auf `up/apk-praesenz` (#65), Stand
      01.10.2026. Nachts legte die Visu nur eine dunkle Fläche über
      sich, die Hintergrundbeleuchtung blieb voll an (Schwarz leuchtet grau).
      In der App senkt jetzt die App die echte Helligkeit:
      `LoxKiosk.setDisplayBrightness(prozent)`, Prozent der eingestellten
      Systemhelligkeit, nur für ihr Fenster. Die Visu rechnet „Nachts
      abdunkeln“ auf dieselbe Leuchtdichte um wie mit der Fläche (die wirkt
      auf die Farbwerte, Potenz 2,2: 70 % = 7 %). Bei automatischer
      Helligkeit lehnt die App ab, dann bleibt es bei der Fläche, ebenso bei
      Fully Kiosk und im Browser. Hinweis im Konfigurator (de/en), Rechnung
      in `Helligkeit.kt` mit Unit-Test. Geprüft: APK gebaut, 5 Unit-Tests;
      in Chromium mit nachgebauter Brücke 6 Tests, die ohne die Änderung alle
      scheitern; Präsenz- und App-Tests aus #65 laufen; alle App-Beiträge
      zusammen bauen, beide Unit-Tests bestehen. Bis #65 gemergt ist, zeigt
      #67 auch dessen zwei Commits. Die Browser-Tests mit
      nachgebauter Brücke `LoxKiosk` liefen erst gegen Lenardos Zweig; seit
      dem Abgleich vom 02.10.2026 liegen sie im Fork:
      `tests/browser/test_loxkiosk_browser.py` (Kiosk-Typ, Display an/aus,
      Notify weckt, Konfigurator), `test_praesenz_app_browser.py` und
      `test_nacht_app_browser.py`. **S**
- [x] **Sicherung einspielen im Fork** (01.10.2026): *Settings → Sicherung →
      ZIP-Datei wählen und einspielen*, `POST /api/restore`. Erst alles prüfen,
      dann schreiben (vorher `.bak`) und ohne Neustart auffrischen; ein
      vorhandenes Kennwort bleibt nur beim selben Ziel, ein Zugang aus
      `LOXPANEL_MS_*` oder ohne Miniserver in der Sicherung bleibt stehen.
      Ältere Sicherungen ohne `sicherung.json` nennen fehlende Kennwörter
      über die Liste in `LIESMICH.txt`. Gegen präparierte Dateien (keine
      Anmeldung auf den Routen): nur Deflate oder ungepackt, je Datei höchstens
      2 MiB, 32 Ebenen und 200.000 Einträge; keine Eingabe blockiert den
      Server länger als etwa eine Sekunde. Geprüft in
      `tests/test_sicherung.py` und `tests/browser/test_sicherung_browser.py`.
      **M**
- [x] **Sicherung und Einspielen bei Lenardo eingereicht:**
      [#63](https://github.com/Lenardo1/loxpanel/pull/63). Ohne Unraid hat
      jedes Gerät seine eigene Konfiguration in der App, und an den
      Config-Ordner kommt dort niemand. Lenardo hat noch gar keine Sicherung.
      Zweig `up/sicherung` (ein Commit auf `upstream/main`, Stand 01.10.2026):
      Herunterladen und Einspielen, Rubrik *Settings → Sicherung*, englische
      Texte, README-Absatz, `.bak` in `.gitignore`/`.dockerignore`. Ohne
      Präsenzmelder (gibt es dort noch nicht). Die Tests aus dem Fork laufen
      gegen diesen Stand durch, bis auf die Präsenz-Prüfung. **S**
- [x] **Ersteinrichtung am Gerät im Fork** (01.10.2026): Solange der Server
      keine Struktur vom Miniserver hat und kein Zugang eingetragen ist oder
      der letzte Versuch scheiterte, zeigt jedes Panel über der Uhr-Seite eine
      Karte mit dem Grund und der Adresse des Konfigurators; in der App (Visu
      über `127.0.0.1`) die WLAN-Adresse des Panels. Dazu nimmt der Server den
      Platzhalter-Zugang aus `loxpanel.cfg.example` nicht mehr: Ein frisches
      App-Panel meldete sich damit endlos bei `192.168.1.50` mit `CHANGEME` an,
      und Settings zeigte „Kennwort gesetzt“. Geprüft in
      `tests/test_einrichtung.py` und `tests/browser/test_einrichtung_browser.py`.
      **S**
- [x] **Ersteinrichtung bei Lenardo eingereicht:**
      [#64](https://github.com/Lenardo1/loxpanel/pull/64), Zweig
      `up/ersteinrichtung` auf `upstream/main`, dieselbe Änderung wie im
      Fork; dort bringt die App den Platzhalter genauso mit. Ein zweiter
      Commit rückt den Nachrichten-Zweig `einrichtung` in `panel.html` vom
      `display`-Zweig weg, den `up/apk-praesenz` ändert; direkt benachbart
      hätten beide beim Zusammenführen einen Konflikt gemeldet. Im Fork steht
      die Zeile an derselben Stelle. Zusammen mit `up/sicherung` konfliktfrei,
      die Tests aus dem Fork laufen gegen beide zusammen. **S**
- [x] **Geführte Ersteinrichtung im Konfigurator** (01.10.2026): Das Panel
      zeigte die Karte, der Konfigurator öffnete aber mit der Übersicht, und
      alle Rubriken waren offen, obwohl ohne Struktur keine taugt. Jetzt öffnet
      er ohne Struktur *Settings → Miniserver* mit einem Hinweis samt Stand
      (kein Zugang, verbindet, Fehler mit Grund) und sperrt alles außer
      Miniserver und Sicherung. Er fragt alle 3 s nach; steht die Verbindung,
      lädt er neu und bietet Einrichtungsassistent und Sicherung an. Das
      Neuladen behebt auch einen Fehler vom ersten Gerät: Der Konfigurator
      holt Räume und Bausteine nur beim Öffnen (`/api/meta`); wer ihn vor dem
      Verbinden geöffnet hatte, sah danach „verbunden · 225 Controls“, aber
      unter *Räume* „alle 0 sichtbar“, bis er die Seite neu lud. Den Stand
      liefert `/api/settings` (`_einrichtung_info()`), die Karte der Panels
      kommt aus derselben Quelle. Geprüft in `tests/test_einrichtung.py` und
      `tests/browser/test_einrichtung_konfigurator_browser.py`; neun
      Gegenproben, die je einen Teil ausbauen oder einen Katalog-Schlüssel
      verfälschen, schlagen an. Bei Lenardo als dritter Commit in #64
      (`up/ersteinrichtung`). Der Aufruf nach dem Neuladen steht in `load()`,
      die Texte stehen hinter „Verbinden & Speichern“, damit sich #63 und #64
      nicht stören. Alle Beiträge bleiben paarweise und zusammen
      konfliktfrei. Gegen Lenardos Zweig bestehen 18 Einrichtungs-Tests aus
      dem Fork (ohne #63 fehlt nur der Reiter Sicherung), gegen den
      Gesamtstand mit allen Beiträgen 97 Tests zu Ersteinrichtung,
      Sicherung, Präsenz und Kachel-Tasten. **S**
- [x] **Welche Test-APK installiert ist, sieht man** (gewünscht am
      03.10.2026): Version, Commit und Bauzeit stehen in der Seitenleiste des
      Konfigurators und in `/api/health`, der Commit auch unter App-Info in
      Android (`bin/version.json`, `bin/version_info.py`; ARCHITEKTUR §9.3).
      Gilt ebenso für das Docker-Image. **S**
- [ ] **Erstes Gerät prüfen:** `adb shell getprop ro.product.cpu.abilist`
      (muss `arm64-v8a` enthalten), `adb shell dumpsys webviewupdate`
      (WebView-Version), dann APK installieren und Klingel, Notify,
      Ansichtswechsel und Neustart der App durchspielen. **S**
      Stand 01.10.2026, Samsung Galaxy Tab A9 mit der Test-APK (alle
      Beiträge, arm64): Installation und Update über die vorhandene App
      (Einstellungen bleiben) laufen. Nach „Daten löschen“ zeigt das Panel
      die Einrichtungskarte, der Konfigurator führt zum Miniserver, und
      nach dem Verbinden sind die Räume da. Offen: Klingel, Notify,
      Ansichtswechsel, Neustart der App, Nachtmodus, dazu das Zielgerät
      YC-SM41P.
- [x] **Ansicht am Tablet ohne Einstellerei** (gemeldet 01.10.2026 am ersten
      Gerät). Eingestellt waren Kachel-Layout 3 × 3, „Bildschirm füllen“ an,
      Skalierung aus, Split-Screen an und als Widget das Wetter. Ergebnis:
      Links standen fünf sehr große Kacheln mit kleinem Icon oben und Text
      unten, die untere Hälfte der Visu blieb leer. Rechts stand das Wetter,
      darunter wieder eine große Leerfläche. Für ein gutes Bild mussten fünf
      Regler zusammenpassen: Kachel-Layout, „Bildschirm füllen“, Skalierung,
      Split-Screen und Widget je Tab.

      Gelöst am 02.10.2026 mit dem Kachel-Layout **„Automatisch (Tablet)“**.
      Das Panel rechnet Spalten und Zeilen selbst aus seiner Bildschirmgröße
      und einer Kachelgröße in drei Stufen (klein, mittel, groß). Ein größerer
      Schirm zeigt so mehr Kacheln statt größerer: am Tab A9 quer 5 × 3,
      hochkant 3 × 5, am 10″-Tablet quer 7 × 4. Ein Widget belegt ganze
      Kachelspalten (quer) bzw. -zeilen (hochkant), etwa 40 % der Fläche. Die
      Kacheln bleiben dabei gleich groß: am Tab A9 quer stehen 3 × 3 neben
      dem Wetter. „Bildschirm füllen“ und Skalierung braucht es dann nicht,
      der Konfigurator blendet sie aus. Geblättert wird seitenweise wie
      bisher, beim Drehen rechnet das Panel neu. Unter *Displays* zeigt die
      Geräteliste, welches Raster ein Tablet daraus macht. Der Assistent
      „Neues Panel“ schlägt „Automatisch“ für 2 Panes vor. Das 4″-Panel
      bleibt beim festen Raster. Festgelegt am 02.10.2026: Wahl je Panel,
      seitenweise blättern, Kachelgröße in Stufen, Widget auf ganzen
      Kachelspalten. Details in [`ARCHITEKTUR.md`](ARCHITEKTUR.md) §7.1,
      Tests in `tests/test_auto_raster.py` und
      `tests/browser/test_auto_raster_browser.py`. Nebenbei: Der Hinweis bei
      der Skalierung verweist jetzt auf *Displays* statt auf „Settings →
      Panels“. **L**
- [x] **Widget in Pane 2 nutzt seine Fläche** (02.10.2026). Gemessen am
      Tab A9: Unter dem Wetter blieben quer 59 px leer, unter dem Monat 30 %
      (die Termine standen auf einer zweiten Seite), unter zwei Werten 69 %.
      Mit „Automatisch“ quetschte sich die Beschreibung des Wetters zu einer
      Spalte, die Vorschau lief seitlich und hochkant unten aus dem Rahmen.
      Jetzt misst die Visu die Fläche und passt den Inhalt in Stufen an:
      Die Wetterkurve nimmt die freie Höhe, in echter Größe gezeichnet; passen
      die Details mit darauf, entfällt Seite 2. Breite Flächen setzen Lage und
      Kurve nebeneinander, schmale die Beschreibung darunter, die Vorschau
      lässt sich dort wischen. Der Kalender zeigt unter dem Monat (breit:
      daneben) die Termine, ein Tipp auf einen Tag zeigt dessen Termine gleich
      darunter. Die Werte füllen die Höhe, wenige werden groß wie Kacheln.
      Geprüft über 180 Fälle (neun Bildschirmgrößen von 480×480 bis
      1340×800, vier Raster, Widget-Seiten), 15 Browser-Tests; 29
      Gegenproben schlagen an. Nebenbei: Auf einer Widget-Seite saß der
      Verbindungspunkt mitten im Widget, jetzt ist er dort aus wie auf der
      Kalender- und Wetter-Seite. Details in
      [`ARCHITEKTUR.md`](ARCHITEKTUR.md) §7.1. **M**
- [ ] **Tablet-Ansicht, was noch offen ist:** „Automatisch“ und die
      angepasste Pane 2 am Tab A9 prüfen (Raster quer und hochkant, Widget,
      Drehen). Aus den Ideen offen: eine Listen-Darstellung als Alternative
      zu großen Kacheln. **M**
- [x] **App läuft wochenlang ohne Eingriff** (02.10.2026). Bisher blieb die
      Anzeige bei der Fehlerseite stehen, wenn der eingebettete Server hing
      oder eine seiner Aufgaben endete, bis jemand die App neu startete. Stürzte
      der Renderer der WebView ab, beendete Android die ganze App. Und ohne
      Eintrag bei *Auto-Neustart* lud die Visu nie neu, mit Eintrag auch
      mitten in der Bedienung. Jetzt:
      - **Server-Wächter** im Server-Dienst: fragt `/api/health` alle 30 s;
        nach drei Fehlschlägen in Folge startet die App neu (Android holt
        Dienst und Anzeige zurück), höchstens dreimal je Stunde, beim Start
        bis zu 5 Minuten Geduld. Server und Wächter starten je Prozess
        einmal; bisher konnten Anzeige und Boot zwei Starts gleichzeitig
        anstoßen, die dieselben Dateien kopierten.
      - **Anzeige baut sich neu auf**, wenn ihr Renderer abstürzt oder
        Android ihn beendet (ab Android 8), und beendet einen hängenden
        Renderer nach einer halben Minute (ab Android 10).
      - **Visu lädt ohne Eintrag jede Nacht um 3 Uhr neu**, mit Zahl alle so
        viele Stunden, mit 0 nie; immer nur, während die Uhr-Seite steht. Ein
        dunkles Display bleibt dunkel. Der Konfigurator zeigt im leeren Feld
        „nachts um 3 Uhr“.

      Geprüft: 12 Unit-Tests für die Regeln des Wächters, Android-Lint ohne
      neue Befunde, APK gebaut; Neuladen mit gestellter Uhr in Chromium
      (auch mit nachgebauter App-Brücke) und am Server, 19 Tests; 30
      Gegenproben schlagen an, 19 in Visu, Server und Konfigurator, 11 in
      den Regeln des Wächters. Ohne Emulator nicht nachgestellt: der
      Neustart durch den Wächter und der Neuaufbau nach einem
      Renderer-Absturz. Beim nächsten Gerätetest im Log nachsehen
      (`adb logcat -s LPSERVER LPANZEIGE`). Details in
      [`android/README.md`](../android/README.md) und
      [`ARCHITEKTUR.md`](ARCHITEKTUR.md) §8. **M**
- [ ] **Nur falls doch Android-11-Panels:** die Visu so anpassen, dass sie ab
      Chrome 83 richtig aussieht (`inset` an 5 Stellen, `gap` in rund 40
      Flex-Layouts, `aspect-ratio` an 3 Stellen in `panel.html`). **M**

## 1. Konfiguration vor Datenverlust schützen

- [x] **Atomares Schreiben** von `loxpanel.cfg`, `panels.json`, `theme.json`:
      in `<datei>.tmp` schreiben, `fsync`, `os.replace`. Stellen: `_write_cfg`,
      `_persist_panels_file`, `_write_theme` in `bin/webvisu.py`. (F5) **S**
- [x] **Fehlerbehandlung beim Schreiben**: `OSError` in `_write_cfg` und den
      beiden Settings-Handlern fangen und als `{"ok": false, "error": ...}`
      zurückgeben statt 500. (F6) **S**
- [x] **Sicherung vor dem Überschreiben**: vor jedem Schreiben von `panels.json`
      eine Kopie `panels.json.bak` behalten, eine Generation reicht. **S**
- [x] **Unvollständige `loxpanel.cfg` abfangen**: `reconnect()` mit `.get()` statt
      `ms["user"]`, verständliche Fehlermeldung in `/config` (Settings). (F7) **S**
- [x] **Miniserver-Zugang erst prüfen, dann speichern**: Settings → Miniserver
      schrieb den Zugang vor der Prüfung und nahm ihn nach einem Fehlschlag
      nicht zurück. Ein Tippfehler im Kennwort blieb in der Datei, und nach dem
      nächsten Neustart war die Verbindung weg. Zwei Fenster konnten Datei und
      Verbindung auseinanderbringen. Mit Zugang aus `LOXPANEL_MS_*` zeigte
      Settings Port 443 und meldete „Passwort fehlt“. Jetzt gilt: abgelehnt =
      nichts gespeichert, nicht erreichbar = gespeichert mit Warnung, Speichern
      nacheinander, Anzeige und Speichern wie `_config()`. Die Frist der
      Anmeldung steht in `miniserver.response_timeout` (Standard 10 s,
      `ARCHITEKTUR.md` §5.1). **M**

## 2. Server-Stabilität

- [x] **Befehle nach ein bis zwei Tagen wirkungslos (Token läuft ab)**: Das
      Miniserver-Token wurde nur erneuert, wenn der WebSocket abriss. Blieb er
      stabil, lief es ab — die Anzeige lief weiter, aber jeder Befehl (auch
      Icons und Verläufe) scheiterte still mit 401. Jetzt laufen alle
      HTTP-Anfragen über `_ms_http()`, das sich bei 401 einmal neu anmeldet und
      wiederholt; gescheiterte Befehle zeigt das Panel als Hinweis an. (F15,
      `ARCHITEKTUR.md` §3.4) An Upstream eingereicht als
      [#43](https://github.com/Lenardo1/loxpanel/pull/43). **S**
- [x] **Broadcaster absichern**: Upstream 0.3.2 fängt Render-Fehler je
      Verbindung im `broadcaster()` und bei `nav` ab. `_push()`, `switch_mode()`
      und `api_testtone` fingen schon jeden Fehler, hatten aber kein Zeitlimit;
      sie senden jetzt über `_send_or_drop()` (5 s, trennt hängende
      Verbindungen). (F3) **S**
- [x] **`op_modes` in `App.__init__` initialisieren**, `getattr`-Workaround
      entfernt. Ohne Miniserver warf `/api/types` vorher einen
      `AttributeError`. (F2) **S**
- [x] **Timeout für Icon- und Cover-Abrufe**: `fetch_icon` hatte schon 6 s,
      `fetch_cover` hat jetzt `COVER_TIMEOUT` und fängt `asyncio.TimeoutError`.
      (F8) **S**
- [x] **`icon_cache` begrenzen**: `ICON_CACHE_MAX` = 500, der am längsten
      unbenutzte Eintrag fliegt zuerst. (F4) **S**
- [x] **HTTP-Handler für die vier HTML-Dateien**: `_web_file()` liefert bei
      fehlender Datei einen 404 mit Dateinamen statt eines Stacktrace. **S**
- [x] **`JSON.parse` im WebSocket-Handler** der Visu in `try/catch`. (F9) **S**
- [x] **Reconnect mit Backoff**: `MS_RETRY` 5, 10, 20, 40, 60 s; von vorn erst,
      wenn eine Verbindung mindestens 60 s lang Daten lieferte. **S**
- [x] **Stumme Miniserver-Verbindung hing dauerhaft**: Der WebSocket für die
      Live-Werte hatte kein Zeitlimit, und nach der Anmeldung sendete LoxPanel
      dort nichts mehr. Riss die Verbindung still ab oder schwieg der
      Miniserver, wartete `stream_task` für immer und die Panels zeigten
      eingefrorene Werte. Jetzt: Frist je Schritt der Anmeldung
      (`miniserver.response_timeout`), `keepalive` alle
      `miniserver.keepalive_interval` Sekunden (Standard 60), ohne Nachricht
      binnen Abstand + Frist wird neu verbunden. Die Pause beginnt nur nach
      einer Verbindung, die Daten lieferte, von vorn. (F17, `ARCHITEKTUR.md`
      §3.4) An der echten Anlage prüfen, ob das Log einmal je Verbindung
      „Miniserver beantwortet keepalive“ zeigt. **M**
- [x] **Rückfall auf Miniserver-Favoriten ist unerreichbar**: `_view_sources`
      verzweigt nur danach, ob ein Ereignis-Client existiert, nicht darauf, ob
      die Anmeldung am Audioserver geklappt hat. Schlägt sie fehl, greift der
      dafür gedachte Rückfall (`_audio_favs`) nie — der Zweig ist toter Code.
      Prüft jetzt dieselbe Bedingung wie `prime_favs()` (nicht gekoppelt oder
      angemeldet). **S**

## 3. Sichtbare Fehler in der Visu

- [x] **Escaping in `panel.html`**: `esc()` um `"` und `'` ergänzen. Betrifft
      Attribute mit Miniserver-Namen und Freitext-Schriftarten. (F10) **S**
- [ ] **Panel-`states`-Farben validieren** mit `_color_ok` in
      `_sanitize_panels`, oder das Feld entfernen, da der Konfigurator es nicht
      anbietet. (F11) **S**
- [ ] **Icon-Routen `/gicon` und `/uicon`**: entweder registrieren (Google
      Material Icons per Proxy, Upload-Verzeichnis für eigene Icons) oder die
      Erzeugung in `_apply_tile_style` und die Annahme in `_clean_icon`
      entfernen, bis das Feature gebaut wird. (F1) **S** (entfernen) / **M** (bauen)
- [x] **`updatePanel()` robust machen**: gelöst über eine Struktur-Signatur
      (`blockSig()`): weicht Art/Reihenfolge der Blöcke vom zuletzt Gerenderten
      ab, wird komplett neu aufgebaut, sonst weiter in-place (kein Flackern).
      Zusätzlich werden alle Blöcke einer Art über ihre Position gepatcht statt
      nur der erste Treffer — das war die Ursache für eingefrorene Statuszeilen
      auf der Sauna-Detailseite. (F12) **M**
- [x] **Stiller Verlust beim Speichern**: `/api/panels` antwortet zusätzlich
      mit `verworfen` – was `_sanitize_panels` nicht übernommen hat, als
      lesbare Pfade („Wohnzimmer: ui.cols“, „… tabs: quatsch“, Kacheln mit
      Bausteinnamen statt UUID). Der Konfigurator zeigt es als gelbe Warnung,
      die bis zur nächsten Änderung stehen bleibt; das Server-Log nennt es
      auch. Gemeldet wird nur, was einen Inhalt hatte: leere Werte,
      begrenzte/gekürzte Werte und Standardwerte, die bewusst nicht
      gespeichert werden (`PANEL_STANDARD`: `ui.split = true`,
      `tiles.*.chartStyle = "trend"`), nicht. Geprüft: was Editor und
      Assistent „Neues Panel“ schreiben, behält der Server; Speichern ohne
      Änderung meldet nichts. Tests: `tests/test_nicht_uebernommen.py`,
      `tests/browser/test_speichern_browser.py`. An Upstream eingereicht als
      [#59](https://github.com/Lenardo1/loxpanel/pull/59). (W7) **M**
- [ ] **Freie Seite: fremde Icon-Adressen**: `_sanitize_panels` soll laut
      Kommentar externe URLs als Seiten-Icon verwerfen, lässt aber jede
      Adresse durch, die auf `.svg`/`.png` endet (z. B.
      `https://fremd.example/x.png`). Das Panel lädt das Bild dann von dort.
      Beim Bau der Meldung für den stillen Verlust gefunden; Adressen mit
      Schema (`://`) ausschließen, Loxone-Icon-Pfade sind relativ. **S**
- [x] **Speicher-Vorzeichen im Energiefluss**: Loxone zählt aus Sicht des
      Hauses, ein positiver `Spwr` heißt „Speicher entlädt“ (fließt ins Haus,
      wie Netzbezug). `classify()` und die Texte der Detailseiten hatten es
      umgekehrt, der Speicher lief also beim Entladen in die Batterie hinein.
      Im Loxone-Forum an einer Anlage mit Speicher bestätigt (Energieflussmonitor,
      Lenardo1/Loxpanel#14). Jetzt entlädt er grün zur Mitte und lädt orange
      nach außen, für EFM-Knoten mit `nodeType` Storage wie für den
      Summen-Knoten aus `Spwr`; bei 0 kW steht „Speicher“ ohne Richtung.
      Tests: `tests/test_energiefluss.py`. An Upstream eingereicht als
      [#55](https://github.com/Lenardo1/loxpanel/pull/55). **S**
- [x] **„Verbrauch 0 W“ beim Energiemanager**: Unter dem Radial stand beim
      `EnergyManager2` (und beim EFM ohne Verbraucher-Knoten) immer
      „Verbrauch 0 W“, der Server rechnete ihn nicht, das Panel setzte 0 ein.
      Jetzt aus der Bilanz des Hauses: Erzeugung + Netz + Speicher (was
      hereinkommt, wird verbraucht), nie negativ. Ohne Netzwert, oder solange
      PV/Speicher angelegt sind, aber keinen Wert haben, ist er unbekannt und
      die Fußzeile lässt „Verbrauch“ weg. EFM mit Verbraucher-Knoten wie
      bisher: deren Summe. Tests in `tests/test_energiefluss.py` und
      `tests/browser/test_energiefluss_browser.py`. An Upstream eingereicht
      als [#58](https://github.com/Lenardo1/loxpanel/pull/58). **S**
- [x] **Kacheltexte: „1 Räumen“ und „–“ bei Radiotasten.** Audio Zentral
      und Licht Zentral zeigten bei genau einem Raum „Spielt in 1 Räumen“
      bzw. „In 1 Räumen aktiv“, jetzt steht die Einzahl. Radiotasten ohne
      aktiven Ausgang (etwa Lüfterstufen) zeigten auf der Kachel „–“, auf der
      Detailseite den Ruhe-Text aus der Struktur (`allOff`, etwa
      „Automatik“). Jetzt zeigen beide den Ruhe-Text. Tests:
      `tests/test_kachel_texte.py`. **S**
- [x] **„Tipp auf eine Sprungmarke: Filtern“ ging beim nächsten Speichern
      verloren.** `_sanitize_panels()` behielt `ui.catFilter`, aber
      `_panel_export()` gab es nicht an den Konfigurator weiter. Der schickt
      beim Speichern zurück, was er bekam. Ein Test prüft jetzt beide Listen
      gegeneinander. **S**
- [x] **Kategorie-Tabs eines Raum-Panels gingen beim Speichern verloren.**
      `_panel_export()` gab `roomCats` nicht an den Konfigurator weiter,
      derselbe Fehler wie bei `catFilter`. Der Editor zeigte deshalb die
      ersten vier Kategorien, und jedes Speichern, auch eines anderen Profils,
      löschte die Auswahl ohne Warnung. Der bisherige Test prüfte nur `ui`.
      Jetzt muss ein Profil, das jedes gespeicherte Feld belegt, Laden und
      Speichern unverändert überstehen, und ein neues Feld im Sanitizer, das
      in dieser Vorlage fehlt, lässt einen Test scheitern. Ein Moduswechsel im
      Editor setzt die Auswahl jetzt zurück wie ein Raumwechsel. **S**
- [x] **Enge Kachel verlor die Lage ihrer Tasten.** Am 4″-Panel (3×3) rücken
      die Player-Tasten in den Kopf (`ctrltight`, `ctrlnarrow`). Bei einem
      Zustandswechsel ohne neuen Text (Pause) setzte `updateGrid()` die
      Klassen neu und warf beide weg, und `placeCtrls()` maß bei gleichem
      Text nicht nach. Die Tasten standen danach ohne ihre Regeln im Kopf.
      Jetzt bleiben die gemessenen Klassen stehen, in beiden Kachel-Aufbauten
      geprüft. **S**
- [ ] **Online-Punkt bei 3×3:** Der Verbindungspunkt sitzt in der Mitte des
      Rasters. Bei 2×2 liegt er in der Fuge, bei 3×3 mitten auf der mittleren
      Kachel und überdeckt dort Text. Gehört zum Vorschlag „Verbindung“ in
      Block 9 (Vorschläge aus der Kachel-Analyse). **S**

## 4. Performance

- [x] **Nur senden, was sich geändert hat**: umgesetzt in `broadcast_task`
      (`bin/webvisu.py`, `self._last_sent` pro WebSocket). Nicht nur `view`,
      sondern auch `player`, `energy` und `camera` werden je Verbindung
      verglichen und bei Gleichheit übersprungen. Upstream angenommen als
      [#21](https://github.com/Lenardo1/loxpanel/pull/21). (P1) **S**
- [ ] **Nur rendern, was betroffen ist**: pro Route die Menge der State-UUIDs
      merken, die sie liest, und nur bei Änderung einer dieser UUIDs neu rendern.
      Zweiter Schritt nach dem ersten Punkt. (P1) **M**
- [ ] **JSON-States einmal parsen**: `moodList`, `entryList`, `sourceList`
      beim Eintreffen in `_on_value` parsen und geparst cachen statt bei jedem
      Rendering. (P1) **M**
- [ ] **`panels.json` einmal lesen**: `load_panels` und `load_devices`
      zusammenlegen. (P2) **S**
- [ ] **Klingel- und Wecker-Pushes filtern**: nur an Panels, die den
      betreffenden Baustein überhaupt anzeigen dürfen. (P3) **S**

## 5. Unraid-Betrieb

- [x] **`HEALTHCHECK` im Dockerfile** über `/api/health`: unhealthy nur, wenn
      eine Hintergrund-Aufgabe beendet ist (dann hilft ein Neustart); ein
      fehlender Miniserver wird gemeldet, macht den Container aber nicht
      unhealthy. **S**
- [x] **Altlasten aus dem Image halten**: `.dockerignore` um
      `webfrontend/htmlauth`, `config/visu.*`, `daemon/`, `postinstall.sh`,
      `apt`, `plugin.cfg` ergänzt, dazu Tests und `loxberry-plugin/`. **S**
- [x] **Log-Level per Umgebungsvariable** (`LOXPANEL_LOG_LEVEL`, auch im
      Unraid-Template): Zugriffs-Log von aiohttp nur bei `DEBUG`. **S**
- [x] **Backup-Endpunkt** `GET /api/backup`: die drei Config-Dateien als ZIP,
      Kennwörter leer (die Route hat keine Anmeldung), `LIESMICH.txt` nennt sie;
      Settings → *Sicherung* mit Download-Knopf. **M**

## 6. Wartbarkeit

- [ ] **Agent nur einmal pflegen**: Server liefert `agent/loxpanel-agent.py`
      unter `/loxpanel-agent.py` aus, `install-agent.sh` holt die Datei per
      `curl` statt sie als Heredoc zu enthalten. (W2) **S**
- [ ] **Duplikate zusammenführen**: `esc()` doppelt, `ICONS`/`BICONS`,
      Overlay-Berechnung,
      Config-Leser `_config`/`_audio_config`/`_intercom_config`,
      `api_testtone` gegen `_push`. (W3) **M**
- [ ] **Magische Zahlen als Konstanten** am Dateianfang: Broadcaster-Takt,
      Reconnect-Pausen, Agent-Timeouts, Ports, Daytimer-Dauern,
      Farbtemperaturen. (W5) **S**
- [ ] **Bausteinketten aufteilen**: Tabelle `Typ → (kachel_fn, detail_fn)`
      statt der `elif`-Ketten, ein Modul pro Bausteinfamilie. Protokoll bleibt
      gleich. (W1) **L**
- [ ] **Kategorie-Farben exakt statt per Teilstring** zuordnen, mit
      Rückwärtskompatibilität für bestehende `theme.json`. (W6) **S**
- [ ] **`_irc_modes`-Filter** nicht über den Text „schutz", sondern über die
      Modus-ID. (W4) **S**
- [ ] **Altlasten entfernen**: `daemon/`, `postinstall.sh`, `apt`, Root-
      `plugin.cfg`, `webfrontend/htmlauth/index.php`, `bin/loxone_live.py`,
      `bin/loxone_client.py`, `bin/importer.py`, `config/visu.*`,
      `deploy/kiosk.sh`, `deploy/loxpanel-webvisu.service`,
      `agent/loxpanel-agent.service`. Vorher entscheiden, wie eng dem Upstream
      gefolgt wird, sonst Merge-Konflikte. **S**
- [ ] **Diagnose-Skripte in `bin/`** bereinigen: fest kodierte UUIDs und IPs
      durch Argumente ersetzen oder die Skripte in einen Ordner `tools/`
      verschieben und aus dem Image ausschließen. `requests` in
      `requirements.txt` aufnehmen oder die drei Nutzer umstellen. (F14) **M**
- [ ] **Doku angleichen**: Changelog ab 0.3.0 nachtragen, `armhf` durch
      `armv7l` ersetzen, Stromspar-Pause als optional beschreiben,
      `loxpanel-kiosk.conf.example` vervollständigen, `DOCKER.md`/`DEPLOY.md`
      vom „späteren Plugin" befreien, Root-`docker-compose.yml` auf das fertige
      Image umstellen. **S**
- [ ] **Toter Zweig im EFM-Detail entfernen**: in `_view_control_inner` kann
      `energy_blocks()` im `EFM`-Zweig nie `None` liefern, damit sind die dort
      aufgebauten `rows` und der `else`-Zweig unerreichbar. Entweder entfernen
      oder den Aufruf absichern. **S**
- [ ] **`loxpanel-kiosk.conf.example` vervollständigen**: der Agent liest 15
      Schlüssel, die Beispieldatei dokumentiert 13. Es fehlen `PROFILE_DIR` und
      `BL_DEVICE`; besonders `BL_DEVICE` ist nutzerrelevant, wenn die
      Backlight-Erkennung danebengreift. **S**

## 7. Tests und CI

- [x] **pytest für reine Funktionen**: `_fmt_num`, `_color_parse`,
      `_alarm_next_text`, `_alarm_entries`, `_audio_favs`, `_tracker_lines`,
      `_resolve_ids`, `_sanitize_panels`, `LoxoneWS._parse_values`,
      `LoxoneWS._parse_texts` in `tests/test_reine_funktionen.py`, dazu die
      Statistik-Rechnungen. Eine `App` ohne Verbindung reicht dafür. (W8) **M**
- [x] **Server-Tests gegen einen Miniserver-Nachbau** (`tests/lox.py`):
      Verläufe V1/V2, Kachel-Stile, Token-Erneuerung, Stabilität; Visu und
      Konfigurator in Chromium (`tests/browser/`). **M**
- [x] **Lint im Workflow** (`ruff`): gleich als harte Prüfung, weil mit den
      Fehlerregeln (`F`, `E9`) nur eine tote Zuweisung übrig war
      (`loxone_weather.py`, entfernt). **S**
- [x] **Rauchtest im Workflow**: `tests/test_rauchtest.py` startet den Server
      als eigenen Prozess ohne Miniserver und ruft alle Oberflächen und die
      Lese-APIs ab; kein Stacktrace im Log. **S**
- [x] **Workflow auch für Pull Requests**: `tests.yml` auf jedem PR und Push auf
      `main`, dazu bei PRs ein Probe-Build des Images (amd64, ohne Push); der
      Multi-Arch-Build mit Push bleibt in `docker-image.yml` auf `main`. **S**
- [x] **Image nur nach grünen Tests**: `docker-image.yml` veröffentlichte
      neben den Tests her, meist Minuten bevor sie fertig waren, und bei Tags
      `v*` ganz ohne Tests; am 04.10.2026 stand so ein `:latest` mit roten
      Browser-Tests draußen. Jetzt veröffentlicht der Job `veroeffentlichen` in
      `tests.yml`, der auf beide Test-Jobs desselben Laufs wartet; `tests.yml`
      läuft dafür auch bei Tags `v*`, `docker-image.yml` ist gelöscht. Wache:
      `tests/test_workflows.py`. **S**

## 8. Bausteine: was fehlt

Stand aus dem Code (Commit `de31d76`): `_control_item()` und
`_view_control_inner()` in `bin/webvisu.py` behandeln 59 Typen. Ein
unbekannter Typ ergibt eine tote Kachel ohne Untertitel und ohne Reaktion, so
wie „Energieflussmonitor" in der Testanlage. Vorgehen je Typ: Rezept (a) in
[`ARCHITEKTUR.md`](ARCHITEKTUR.md), State- und Befehlsnamen aus der eigenen
Strukturdatei (`LoxAPP3.json`) des Miniservers ablesen.

### 8.1 Zuerst

- [x] **Diagnose-Endpunkt `/api/types`**: listet alle Bausteintypen der
      verbundenen Anlage mit Anzahl, Beispielnamen, Unterstützungsstatus
      (voll / teilweise / keine), State-Namen und `details`-Schlüsseln je Typ
      sowie die toten Kacheln mit Raum. `?format=text` für den Browser, Link
      unter *Einstellungen → Miniserver*. **S**
- [ ] **Bedienung der vier neuen Bausteine an der Anlage prüfen** (seit
      03.10.2026, Befehle aus der Loxone-Strukturdoku, Stand 16.0, und der
      Wissensdatenbank; an einem echten Miniserver noch nicht gesehen):
      Bewässerung eine Zone starten und stoppen: läuft die richtige? Laut Doku
      ist die Zone mit `id` 0 `select/1`; wenn nicht, `IRR_SELECT_*` in
      `bin/webvisu.py` und `select/{id+1}` in `_view_irr_zone()` anpassen
      (`bin/steuer_probe.py --zones --write` misst es, lässt aber kurz Wasser
      laufen). Laufzeit einer Zone ändern und in der Loxone-App nachsehen
      (`setDuration/{id}`). Wecker: Weckzeit aus- und einschalten, Uhrzeit,
      Tage und Namen ändern, neue anlegen, löschen, Schlummerdauer. Intercom:
      verpasste Klingeln mit Bildern, „Klingel abstellen“ beim Klingeln.
      UpDownAnalog: −/+ bei „2=Opt. Helligkeit 3= Opt. Kühlung“. **S**
- [ ] **Gesperrte Bedienung anzeigen (`jLocked`)**: Laut Strukturdoku kann
      jeder Baustein mit `details.jLockable` gesperrt sein; der Text-State
      `jLocked` ist dann ein JSON mit `locked` (1 = per Visu, 2 = per Logik)
      und `reason`. LoxPanel wertet das bei keinem Typ aus: Kachel und
      Detailseite sollten „Gesperrt“ samt Grund zeigen und keine Befehle
      anbieten. Betrifft alle Typen, an der eigenen Anlage u. a. Wecker,
      Bewässerung, Intercom und UpDownAnalog. **M**
- [ ] **Unbekannte Typen sichtbar machen**: im Fallback von `_control_item()`
      Untertitel „Typ nicht unterstützt" statt leerer Kachel, und die Kachel
      per `hide` ausblendbar lassen. **S**
- [ ] **README-Tabelle angleichen**: `AudioZoneV2` und `EIBDimmer` sind im Code
      umgesetzt, fehlen aber in der Tabelle (die Roadmap nennt `AudioZoneV2`
      noch als offen). `ColorPicker` steht als „voll" in der Tabelle, der Code
      prüft `Colorpicker` (kleines p); den tatsächlichen Typnamen in der
      Strukturdatei prüfen und Code oder Tabelle korrigieren. **S**

### 8.2 Komplett fehlend, im README als geplant geführt (16)

Kurz: was der Baustein ist und was ein Zweig mindestens braucht.

- [ ] `MoodSwitch` (Stimmungsschalter): wie `LightControllerV2`, Stimmungsliste
      und aktive Stimmung, Befehl `changeTo/<id>`; Licht-Adapter wiederverwenden. **S**
- [ ] `Sequential` (Sequenzer): aktueller Schritt, Befehle Weiter/Start/Stop. **S**
- [ ] `Heatmixer` (Heizungsmischer): Ist- und Solltemperatur, Ventilstellung,
      nur Anzeige. **S**
- [ ] `LoadManager` (Lastmanager): Lastliste mit Zustand, nur Anzeige. **S**
- [ ] `NfcCodeTouch`: letzter Zutritt und Zustand, nur Anzeige; Codes werden
      nicht in der Visu gepflegt. **S**
- [ ] `SolarPumpController` (Solarpumpe): Temperaturen, Pumpenzustand, Modus
      umschalten. **M**
- [ ] `ClimateController` (Klimaregelung EU): Betriebsart, Solltemperatur,
      Zustände Heizen/Kühlen. **M**
- [x] `IRoomController` (alte Raumregelung, IRC v1): Kachel und Detailseite
      wie beim V2. Ist/Soll, aktive Temperatur, heizt/kühlt (Ventile) und
      Fenster; −/+ verstellt Komfort der laufenden Periode (`settemp/1` bzw.
      `/2`, manuell die manuelle Temperatur `settemp/7`), Eco/Komfort für eine
      Stunde (`starttimer/<Nr>/3600`), Automatik (`stoptimer`). Befehle und
      Nummern aus der Loxone-Strukturdoku, die Strukturform (Liste
      `temperatures`, `details.temperatures[].isAbsolute`) von einer echten
      Anlage. Ohne bekannten, absoluten Komfortwert gibt es kein −/+. Im
      Loxone-Forum gemeldet („IRC v1 does nothing“). Die Betriebsart
      (`mode/…`) ist umschaltbar, siehe „Betriebsart umschalten“. Tests:
      `tests/test_raumregelung_v1.py`, Browser-Test bis zum Befehl am
      Miniserver. An Upstream eingereicht als
      [#56](https://github.com/Lenardo1/loxpanel/pull/56). **M**
- [x] `Sauna` (Sauna-Steuerung): **vollständig**. Anzeige von Ist/Soll/Bank,
      Betriebsart (`mode` 0..6 als Klartext), Feuchte (Ist/Soll), Lüftung,
      Trocknung, Tür, Betriebstemperatur, Wassermangel, Timer und Störung.
      Bedienung: Ein/Aus (`on`/`off`), Solltemperatur (`temp/<wert>`, ±1/±5 °C)
      und Betriebsart (`mode/<0..6>` als Aufklapper). States und Befehle an der
      echten Anlage verifiziert (`bin/sauna_probe.py`). **M**
- [ ] `PoolController` (Pool): Modus, Temperaturen, Filterlauf, Befehle. **M**
- [ ] `LightsceneRGB` (RGB-Lichtszene): Szenenliste, aktive Szene, Farbe
      setzen; Farbwahl aus `ColorPickerV2` wiederverwenden. **M**
- [ ] `Remote` (Fernbedienung): Modusliste und Tastenbefehle als Button-Raster. **M**
- [ ] `Wallbox` (Ladestation): Ladeleistung, Energie, Ladezustand, Modus und
      Leistungsgrenze setzen. **M**
- [x] `EnergyManager2` (Energiemanager): Erzeugung, Netz, Speicher mit
      Ladestand und Reserve, Verbraucherliste aus `loads`; nur Anzeige. **M**
- [ ] `SpotPriceOptimizer` (Strompreis-Optimierer): Preisverlauf und Plan,
      nur Anzeige. **M**
- [ ] `MediaClient` (Media Client, alt): Steuerung veralteter Geräte;
      niedrige Priorität, nur bei Bedarf. **L**

### 8.3 Weder im Code noch im README erwähnt

Typen, die Loxone in der Strukturdatei liefert, hier aber nirgends vorkommen.
Welche davon relevant sind, zeigt der Diagnose-Endpunkt aus 8.1.

- [x] `EFM` (Energieflussmonitor, Typname in der Strukturdatei ist `EFM`):
      Erzeugung, Netz mit Bezug/Einspeisung, Speicher mit Laden/Entladen,
      Knoten aus `details.nodes` mit `actual0..5`; nur Anzeige. Vorzeichen
      aus Sicht des Hauses (positiv = Netzbezug bzw. Speicher entlädt), beim
      Speicher an einer Anlage bestätigt (siehe Abschnitt 3). **M**
- [x] `PvProductionForecast` (PV-Produktionsvorhersage): heute, morgen,
      Zeitraum, danach, Anlagenleistung. **S**
- [x] `SteakThermo` (Touch & Grill Thermometer): Fühlertemperaturen aus
      `currentTemperatures`, Zielwerte, Alarmtext, Timer, Akku. Struktur von
      `currentTemperatures` auf der Anlage gegenprüfen. **S**
- [ ] `EnergyManager` (Energiemanager, alte Version), `Wallbox2`, `CarCharger`:
      ältere bzw. neuere Varianten der Energie-Bausteine. **M**
- [ ] `IntercomV2`: neue Türsprechstelle, nach dem Muster von `Intercom`. **M**
- [ ] `IRCDaytimer`, `IRCV2Daytimer`: Zeitpläne der Raumregelung, nach dem
      Muster von `Daytimer`. **S**
- [x] `Irrigation` (Bewässerung): Zustand, aktive Zone, Zonenliste,
      erwarteter Niederschlag als Anzeige; Bedienung Start/Erzwingen/Stopp und
      alle Zonen an/aus (`start`/`startForce`/`stop`/`select/9`/`select/0`, aus
      der Loxone-Structure-File-Doku). Seit 03.10.2026 auch jede Zone einzeln:
      eigene Seite mit Starten/Stoppen und Laufzeit (−/+). Die Nummerierung
      steht jetzt fest: `zones[].id` zählt ab 0 (Strukturdoku), `select`
      folgt dem Eingang „Sel“ des Bausteins (Wissensdatenbank: Ventil 1..8),
      also `select/{id+1}`; die Laufzeit setzt `setDuration/{id}={Sekunden}`,
      nicht bei `setByLogic`. Dazu Regen der letzten 24 h und die Grenze für
      den erwarteten Niederschlag. An der Anlage prüfen, siehe 8.1. **M**
- [ ] `AlarmChain`, `AalEmergency`, `AalSmartAlarm` (Alarmkette, Notfall,
      Smart Alarm): Zustand und Quittieren nach dem Muster von `Alarm`. **S**
- [x] `MailBox` (Briefkasten): Post da / Paket da / leer als Anzeige.
      Offen: Quittieren, Befehlsname auf der Anlage prüfen. **S**
- [ ] `LeafSystem`, `PowerUnit`: Anzeige-Bausteine, nur Werte. **S**
- [ ] `UpDownLeftRightAnalog`, `UpDownLeftRightDigital`: vier Richtungstasten,
      nach dem Muster von `UpDownDigital`. **S**
- [ ] `Application`, `MsShortcut`: Verknüpfungen, in der Visu ausblenden statt
      tote Kachel. **S**

### 8.4 Nur teilweise umgesetzt (noch 3 offen)

- [x] `AudioZoneV2` (Loxone Audioserver Gen 2, gekoppelt): vollständig.
      Play/Pause/Skip und Lautstärke laufen über den Miniserver (`sps/io`),
      Titel/Sender/Cover live über den Ereigniskanal (`remotecontrol`). Die
      Raumfavoriten liefert der gekoppelte Audioserver nur einer angemeldeten
      Verbindung; die Anmeldung wurde wie in der Loxone-App nachgebaut
      (`bin/audioserver_auth.py`): Session-Token aus dem Banner,
      `audio/cfg/getkey` → RSA-Schlüssel, Miniserver-JWT mit AES-256-CBC
      verschlüsselt, `key:iv:sessionToken` mit RSA-PKCS#1-v1.5, dann
      `secure/authenticate/<user>/<rsa>/<chiffre>`. Danach `getroomfavs` und
      `roomfav/play/<id>` auf derselben Verbindung. An der echten Anlage (LWSS
      17.2) verifiziert. **M**
- [x] `AudioZone` (Musikserver Gen 1, MS4H, Sonn) und `AudioZoneV2`
      (Audioserver Gen 2): Favoriten und Steuerung laufen direkt am
      Audioserver (Port 7091) — aber nur bei einem **ungekoppelten**
      Audioserver (`paired is False`). Am gekoppelten Audioserver läuft die
      Steuerung bewusst über den Miniserver (`sps/io`); so seit dem Fix der
      Paired-Weiche. **M**
- [x] `AlarmClock` (Wecker): Anzeige + Weckton; beim Klingeln Schlummer
      (`snooze`) und Aus (`dismiss`). Seit 03.10.2026 vollständig nach der
      Strukturdoku: je Weckzeit ein Schalter, Bearbeiten von Name, Uhrzeit und
      Tagen (Mo–So, dazu Feiertag/Urlaub aus den Betriebsarten der Anlage),
      neue Weckzeit, Löschen mit Rückfrage (`entryList/put`,
      `entryList/delete`); Einstellungen für Schlummerdauer, maximale
      Weckdauer und Vorweckzeit, mit Touch Nightlight auch Wecksound, lauter
      werdend, Signalton, Lautstärke und Helligkeit. Ein Master-Ein/Aus gibt
      es laut Doku nicht: der Eingang DisA schaltet per Logik ab, die Visu
      zeigt dann „Ausgeschaltet“. **M/L**
- [ ] `Intercom`: Kamera, Live-Klingelanzeige (`bell`) auf Kachel/Detail,
      Tür/Ausgänge öffnen (`pulse` je Sub-Control). Seit 03.10.2026 dazu
      „Klingel abstellen“ (`answer`) und die verpassten Klingeln
      (`lastBellEvents`) mit Bildern (`camimage/{uuidAction}/{Zeitstempel}`
      über `/bellimg`). Offen: Gegensprechen (SIP). Ziel ist die Loxone
      Intercom Gen 1 (Baustein „Door Controller“, Typ `Intercom`), die auch die
      Loxone-App direkt per SIP anruft; geklingelt wird weiter über `bell` und
      das Klingel-Popup, eine Anmeldung am SIP-Server braucht es nicht. Nur in
      der LoxPanel-App für Android, weil der Browser kein SIP über UDP kann.
      Drei Schritte: **L**
      1. [x] *Zugang und Prüfung* (03.10.2026): Den SIP-Zugang gibt der
         Miniserver nur auf einen verschlüsselten Befehl heraus
         (`securedDetails`, `bin/loxone_secure.py`). Settings → SIP zeigt ihn
         je Intercom ohne Passwort; „Verbindung prüfen“ schickt ein OPTIONS
         mit Anmeldung (`bin/sip_probe.py`), ohne einen Anruf auszulösen.
         Ablauf in [`ARCHITEKTUR.md`](ARCHITEKTUR.md) §3.10.
         **An der Anlage geprüft (03.10.2026, Test-APK):** Die „Eingang
         Intercom“ meldet `deviceType` 0 („andere oder unbekannte
         Türstation“), und ihre gesicherten Details nennen keinen SIP-Zugang.
         Seitdem zeigt der Reiter in dem Fall, welche Felder der Miniserver
         liefert (ohne Werte). **Offen:** diese Zeile von der Anlage holen und
         klären, ob das Audiomodul der Intercom in Loxone Config eingetragen
         ist (Loxone-KB „Intercom Gen. 1“: eigenes SIP-Audiomodul, die
         Loxone-App ruft es anonym an). Davon hängt Schritt 2 ab (Adresse,
         Codec, Anmeldung).
      2. [ ] *App:* SIP-Client in Kotlin: INVITE/ACK/BYE mit derselben
         Digest-Anmeldung, RTP mit G.711, Echounterdrückung des Geräts,
         Mikrofon-Recht. Ein eigener kleiner Stack: Linphone und PJSIP stehen
         unter GPL, eingebaut müsste die App unter GPL stehen, LoxPanel steht
         unter PolyForm Noncommercial; Androids `android.net.sip` ist seit
         Android 12 abgekündigt. Den Zugang holt der Kotlin-Teil im selben
         Prozess vom Server (Chaquopy), nicht über eine Route im LAN. **L**
      3. [ ] *Visu:* „Sprechen“ und „Auflegen“ auf der Intercom-Seite und im
         Klingel-Popup, über die Brücke `LoxKiosk`; ohne App zeigt die Visu
         sie nicht. **M**
- [ ] `TextInput`: nur Anzeige, keine Eingabe. **S**
- [x] `UpDownAnalog`: seit 03.10.2026 bedienbar. Laut Strukturdoku
      („UpDownLeftRight analog“) ist der Befehl der Wert selbst, zwischen
      `details.min` und `details.max`; −/+ um `details.step`, dieselbe
      Detailseite wie der Slider. **S**
- [ ] `Ventilation` (Lüftung): nur Stufe anzeigen, kein Umschalten. **S**

## 9. Weitere Funktionen

- [x] **Positionsring: eingefroren, zu kräftig, und die Kachel schwieg zur
      Fahrt.** Drei Befunde aus einer Messung am echten Code, nicht aus dem
      Gefühl:
      *(a)* `updateGrid()` patcht die Kachel in-place, fasste `.posring` aber
      nie an — der Bogen blieb auf dem Stand vom letzten Vollrender stehen,
      während die Zweitzeile weiterzählte (im Browser nachgestellt: Text 20 →
      95 %, Ring unverändert bei 20 %). Jetzt wird er mitgezogen, dazu
      `transition:stroke-dasharray .4s` — er folgt der Fahrt, animiert aber
      nichts im Stand.
      *(b)* Die Strichstärke hing an einem festen `stroke-width:6` in einer
      Box von `--ico-size + 18px`. Durch den festen Summanden fällt der Ring
      bei kleinen Icons dicker aus als die Icon-Linien: gemessen 1,25× bei
      38 px, 1,48× bei 24 px, 2,75× bei 8 px. Jetzt über `ring`/`rtrk`/`rw`
      im vorhandenen `overlay`-Dict regelbar, Defaults = die alten Hartwerte.
      *(c)* Die Kachel kannte nur die Stellung, nicht die Fahrt, obwohl der
      Server `up`/`down` für die Detailansicht längst liest. Sie zeigt jetzt
      „▲ fährt … 40% zu". **M**

      *Upstream angenommen* als PR #30. Lenardo hatte den eingefrorenen Ring
      unabhängig selbst gefunden (`updateTileRing()`) und die Strichstärke als
      Live-Regler `?ring=` gebaut; beim Zusammenführen hat seine Benennung
      gewonnen — die CSS-Variablen heißen `--posring-w`/`--posring-op`/
      `--posring-trk`, die Schlüssel in `panels.json` unverändert
      `rw`/`ring`/`rtrk`. Sein `?ring=` schlägt die Konfiguration
      (`posringOverride()` greift nach dem Theme-Push erneut).

- [x] **Bedientasten auf der Kachel: erst den Auslöser reparieren**
      (01.10.2026). Die Mini-Player-Tasten (◀ ⏯ ▶ der AudioZone) und die
      Favoriten der Musikauswahl lösten per `pointerdown` schon beim
      Aufsetzen des Fingers aus. Ein Wischer, der auf so einer Taste begann,
      sprang einen Titel weiter oder startete einen Sender und verließ die
      Seite, statt das Raster zu scrollen. Jetzt hören beide auf `click`: Den
      meldet der Browser nur, wenn der Finger ohne Wischen aufsetzt und
      loslässt, wie bei der Kachel selbst. Wird aus der Berührung ein
      Wischer, scrollt das Raster, und es geht nichts raus. Tests:
      `tests/browser/test_kachel_tasten_browser.py` (Touch-Display in
      Chromium: Wischen scrollt und sendet nichts, Tippen genau einmal, Maus
      wie bisher; mit dem alten Auslöser scheitern beide). An Upstream
      eingereicht als [#66](https://github.com/Lenardo1/loxpanel/pull/66)
      (Zweig `up/kachel-tasten`, ein Commit auf `upstream/main`, mit allen
      übrigen Beiträgen konfliktfrei).
      Weiter mit `pointerdown`: die Tasten der
      Detailseiten und des Split-Players (`.btn` mit `touch-action:none`,
      Halten fährt die Jalousie), −/+ am Schieberegler und die Zeitraum-Tasten
      der Diagramme. **S**
- [x] **Auf/Ab auf der Beschattungs-Kachel** (01.10.2026). Über die
      `controls`-Mechanik des Audioplayers, die seit der Reparatur oben erst
      beim Tippen auslöst; ein Wischer über die Kachel lässt die Beschattung
      nicht losfahren. ▲ ▼ senden dieselben Befehle wie Auf/Ab der
      Detailansicht (`_jal_fahrt()`): im Stand `Up`/`Down`, während der Fahrt
      halten beide an, die fahrende Richtung zeigt ■. Dabei aufgefallen: In
      Rastern mit drei Zeilen ist die Kachel zu niedrig für eine Tastenreihe,
      auch die Tasten des Players wurden dort schon abgeschnitten. Jetzt
      rücken sie in die Kopfzeile neben das Icon, in 3x3 an seine Stelle
      (`placeCtrls()`). Neue Symbole `triup`/`tridown`, weil `up`/`down`
      Linien sind. Geprüft in `tests/test_beschattung.py` und
      `tests/browser/test_kachel_tasten_browser.py`; fünf Gegenproben
      (Platzierung, Icon-Ersatz, Tasten, Stop, `pointerdown`) schlagen an.
      **S**

- [x] **Raum als Startseite (Raum-Direkt-Tab).** Aus dem Forum: die kleinen
      Panels bedienen meist EINEN Raum, nicht das ganze Haus — sie sollen nach
      dem Aufwecken direkt in diesem Raum stehen, ohne vorher Raum oder
      Kategorie zu wählen. Umgesetzt als Gegenstück zum vorhandenen
      Kategorie-Direkt-Tab: `room:<uuid>` in `_is_tab()`, `_view_tab()` und
      `_tab_meta()`, in der Tab-Auswahl der Konfiguration angeboten. Am
      Aufwach-Verhalten war nichts zu ändern — es hängt am ersten Tab
      (`conn_route` beim Verbinden, `resetIdle()` nach 60 s Leerlauf). Dazu ein
      Bugfix, ohne den die Direkt-Tabs ihren Zweck nicht erfüllen konnten:
      `toggleTab()` sortierte die gewählten Tabs hart nach der Reihenfolge von
      `/api/meta`, wo Kategorien und Räume hinten stehen — sie rutschten damit
      immer ans Ende und konnten nie Startseite sein, außer als einziger Tab.
      Das betraf auch die schon vorhandenen `cat:`-Tabs. Jetzt ist die
      Klickreihenfolge die Reihenfolge der Leiste. **S**

- [x] **Frei zusammengestellte Seite („Eigene Auswahl").** Aus dem Forum: eine
      Seite aus beliebigen Bausteinen, unabhängig von Raum und Kategorie. Eine
      je Panel, Schlüssel `auswahl` (`PICK_TAB`), Profil trägt `picks` (geordnete
      UUID-Liste, gedeckelt bei 60) und `pickName`. Der Panelfilter gilt hier
      bewusst **nicht** — wer einen Baustein ausdrücklich wählt, will ihn sehen;
      nur `hide` bleibt als Sicherheitsnetz.

      Danach nachgebessert, weil sich die Bedienung nicht gut anfühlte: die
      Seite ist jetzt der **dritte Modus** der unteren Leiste, neben Raum-Panel
      und Klassisch. Der Umschalter wechselt in Wahrheit die *Bedeutung* der
      Leiste — bei Raum-Panel und Eigener Auswahl sind es Sprungmarken statt
      Seiten. Die Auswahl gruppiert nach **Raum**, die Leiste zeigt bis zu vier
      Räume als Sprungmarken (erst ab zwei Räumen), ein Tipp scrollt zur Gruppe.
      Dieselbe Mechanik wie beim Raum-Panel (`catKey` als Anker, `catTabs`).
      Zusammenstellen und Sichtbarmachen liegen damit an einer Stelle; der
      eigene Unterreiter ist entfallen. Dazu eine geführte Einrichtung in drei
      Schritten, ein Raumfilter über der Bausteinliste und eine Vorschau der
      Sprungmarken. Drei Fehler nebenbei behoben: der Chip in der Konfiguration
      zeigte das feste Serverlabel statt des vergebenen Namens; ein
      Moduswechsel verwarf eine selbst zusammengestellte Tab-Leiste ohne
      Rückfrage; und eine leere `catTabs`-Liste wurde im Panel als „kein Wert"
      statt als Aussage gelesen, sodass Sprungmarken stehen blieben, die ins
      Leere zeigten. Raumnamen stehen als Text in der Leiste, wenn der Raum
      kein Bild hat — mit vier gleichen Symbolen wäre sie nicht zu treffen.

      Eine Gegenprüfung des fertigen Standes vor dem Merge fand noch einen
      **kritischen Fehler**: Sprungmarken ersetzen im Panel die *ganze* untere
      Leiste. Stand der Auswahl-Tab in einer klassischen Leiste neben anderen
      Seiten, waren diese damit unerreichbar — der Zurück-Knopf hilft nicht,
      weil die Seite die unterste im Stapel ist, und der Leerlauf springt nach
      60 s wieder auf denselben ersten Tab. Behoben an beiden Enden: der Server
      liefert Sprungmarken und Anker nur noch, wenn die Seite allein in der
      Leiste steht (`prof["tabs"] == [PICK_TAB]`), und `renderTabs()` ersetzt
      die Leiste nur noch im Ein-Seiten-Modus. Die zweite Sperre behebt
      dieselbe Falle für einen `room:`-Tab in einer klassischen Leiste, die es
      schon vorher gab — **dafür lohnt ein Hinweis an Upstream**.

      Dazu drei kleinere Funde derselben Prüfung: die Konfiguration zählte
      ausgeblendete Bausteine bei der Gruppierung mit (der Server wirft sie per
      `_shown()` vorher weg), wodurch ein unsichtbarer Baustein die
      Raumreihenfolge und alle Nummern dahinter verschob; ein enger
      `I18N.autoChrome()`-Aufruf im Auswahl-Editor hätte den modulweiten
      Selektor verengt und damit die Übersetzung der restlichen
      Konfigurationsseite abgeschaltet (jetzt `applyChrome` auf den Teilbaum);
      und zwei neue Code-Kommentare trugen Umlaute entgegen der Konvention. **M**

- [x] **Front: Kalender + Wetter auf dem Screensaver.** Neu `bin/front_info.py`
      (eigenständig, keine Fremdabhängigkeit): iCal-Abo laden und parsen
      (`icalendar` + `python-dateutil`, löst Serientermine auf) und Wetter von
      Open-Meteo (kein API-Key, nur Koordinaten). Der Server holt beides alle
      15 Min (`front_task`) und pusht `{t:"front"}`; die Uhr-Startseite zeigt
      Wetter oben und die nächsten Termine unten. Pflegbar unter *Settings →
      Kalender & Wetter*, gespeichert im `calendar`-Block von `loxpanel.cfg`. **M**
- [x] **Screensaver: rechte Spalte nutzbar machen.** Im Querformat stand rechts
      neben der Uhr nur die Terminliste — gab es keine Termine (oder kein
      iCal-Abo), blieb die halbe Fläche leer, während das Wetter links auf 50 %
      gedrängt blieb. Jetzt entscheidet je Panel `ui.svPane`, was dort steht:
      Automatik (Termine, sonst die Wetter-Details mit Stundenverlauf,
      Luftfeuchte, Wind, Sonne), fest Termine, fest Wetter, Energiefluss,
      Kamera, frei gewählte Bausteine als Werte-Kacheln (neu `status_blocks()`
      + `{t:"svstatus"}`, gebaut über `_control_item()` wie jede Kachel) oder
      gar nichts — dann rücken Uhr und Wetter auf die volle Breite. Geprüft an
      einer Stelle (`_clean_svpane()`), einstellbar unter *Panels → Aussehen &
      Verhalten*. Hochkant und auf dem 4″-Panel unverändert. Nebenbei behoben:
      eine Kamera-Pane streamte bisher hinter dem Screensaver weiter. **M**
- [x] **Display-Auflösungen erkennen und die Visu darauf skalieren.** Die Visu
      rechnet mit festen 240er Kacheln; auf einem größeren Display stand der
      Kasten mit schwarzem Rand da (1280×800: 55 % ungenutzt), und „Bildschirm
      füllen" vergrößerte nur die Kacheln, nicht Schrift und Icons. Jetzt
      meldet jedes Panel seine Größe (Anzeige unter Displays → Geräte & Ansicht:
      sichtbare Fläche, physische Pixel, Faktor, genutzter Anteil), und je
      Profil lässt sich eine Skalierung wählen: aus, automatisch oder ein
      fester Faktor. Pro Gerät übersteuerbar, sodass zwei Displays mit
      demselben Profil unterschiedlich laufen können; die Geräteeinstellung
      wirkt ohne Neuladen. Geräte, die nur eine Skalierung tragen, fielen beim
      Speichern bisher still weg (Server und Konfigurator) — behoben. **L**
- [x] **Skalierung auch global unter Global → Darstellung.** Gilt für alle
      Panels, deren Profil „Wie global" eingestellt hat (das ist jedes Profil,
      das keine eigene Skalierung trägt); das Profil zeigt den geerbten Wert in
      Klammern. Nebenbei behoben: `_write_theme()` und `/api/meta` führten je
      eine eigene Liste der globalen Darstellungs-Keys, ein neuer Key ging so
      beim Speichern still verloren. Die Liste steht jetzt einmal in
      `THEME_UI_KEYS`. Die Skalierungs-Auswahl schnitt bei „Automatisch
      (Bildschirm ausnutzen)" ab (allgemeine 220-px-Grenze für Auswahlfelder)
      — behoben. **S**
- [x] **Uhr-Seite mit Energiefluss/Kamera: Proportionen.** Links nutzten Uhr
      und Wetter nur 49 % der Höhe, die Uhr hatte noch die 60 px des
      Querformats, die Box rechts wirkte dadurch übergroß. Jetzt gleich breite
      Spalten, Uhr 96 px, links 70 % der Höhe genutzt. Energiegrafik unverändert
      392 px (höhenbegrenzt), Kamerabild 454×341 → 418×314. **S**
- [x] **Energiefluss: Beschriftungen ab sieben Knoten laufen in die Nachbarringe.**
      Erledigt mit „Beschriftung außerhalb der Ringe" (#31), an der Anlage
      bestätigt.
      Die Namen und Werte stehen mit festem Abstand über bzw. unter ihrem Ring.
      Ab sieben Knoten rücken die Ringe so eng zusammen (40° Abstand, Radius 34),
      dass die Beschriftungen der Seitenknoten in die Ringe der Nachbarn ragen —
      gemessen bei neun Knoten mit üblichen Namen („Klimaanlage OG",
      „Wärmepumpe Keller"): sechs Überschneidungen. Betrifft Hauptschirm und
      Screensaver gleichermaßen, weil beide dasselbe SVG zeichnen
      (`energyInner()` in `panel.html`). Die Grafik trägt dann die Klasse
      `dicht`; der Screensaver vergrößert die Namen in dem Fall bewusst nicht.
      Lösungsidee: Beschriftung der Seitenknoten nach außen statt nach oben/unten
      setzen. **M**
- [x] **Kalender/Wetter als eigener Tab**: Tabs `kalender` und `wetter`
      (`FRONT_TABS`), im Konfigurator wie die übrigen Tabs wählbar. Kalender:
      Monat mit Blättern und Tagesauswahl, daneben alle Termine des
      eingestellten Zeitraums (bis 60 Tage) zum Durchscrollen. Wetter: Lage und
      Details, Tageskurve und bis zu 7 Tage Vorhersage. Quer zwei Spalten, hoch
      oder quadratisch untereinander. Dabei gefunden: der Monatskalender stellte
      jeden Monat ab Montag dar (F16), behoben. Die Korrektur allein ist an
      Upstream eingereicht als
      [#42](https://github.com/Lenardo1/loxpanel/pull/42), die Tabs nicht.
      **M**
- [x] **Heizung: Betriebsart umschalten** für beide Raumregelungen, als
      Aufklapper „Betriebsart“ zwischen − und + auf der Detailseite; eine
      manuelle Betriebsart steht in der Statuszeile (dann läuft kein
      Zeitplan). `IRoomControllerV2`: `operatingMode` 0–5,
      `setOperatingMode/<Nr>` (Bedeutung wie in der openHAB-Loxone-Anbindung).
      `IRoomController`: `mode/<Nr>` mit 0, 3–6 laut Loxone-Strukturdoku,
      1/2 („Automatik, heizt/kühlt gerade“) gelten als Automatik,
      `restrictedToMode` blendet Heizen bzw. Kühlen aus. Dabei beim V2 die
      Annahme „Komfort unbekannt → Soll oder 20 °C“ entfernt: ohne bekannten
      Komfortwert gibt es kein −/+. Beim V2 wird nicht nach Heizen/Kühlen
      gefiltert – das Detail `possibleCapabilities` nennt nur PyLoxone, eine
      zweite Quelle fehlt. Tests: `tests/test_betriebsart.py`, Browser-Test
      bis zum Befehl am Miniserver. An Upstream eingereicht als
      [#57](https://github.com/Lenardo1/loxpanel/pull/57). **M**
- [ ] **Panel-Texte mehrsprachig**: die rund 90 hart deutschen Strings im Server
      in einen Katalog ziehen, `lang` aus dem Profil auswerten. Nur nötig,
      wenn ein Panel nicht deutsch sein soll. **L**

- [x] **Verlaufs-Diagramme** (#78–#80): Aufzeichnungen des Miniservers
      (`statistic` V1 und `statisticV2`) auf der Detailseite, als Split-Hälfte
      (`chart:<uuid>`) und als Mini-Verlauf in der Kachel mit drei Stilen
      (Trend, Tagesmuster, Tagesspanne). Beschreibung in `ARCHITEKTUR.md` §3.9.
      An Upstream eingereicht als
      [#44](https://github.com/Lenardo1/loxpanel/pull/44), setzt auf #43 auf
      (siehe 0b).
- [x] **Wetterdaten vom Loxone-Wetterserver bevorzugen**: Hat die Anlage den
      Loxone-Wetterdienst, schickt der Miniserver das Wetter über den WebSocket
      als eigene Binärtabelle (Kennung 7). `loxone_ws.py` zerlegt sie,
      `loxone_weather.py` rechnet sie in dieselbe Form wie
      `front_info.fetch_weather()` um; Open-Meteo bleibt Rückfall und wird gar
      nicht mehr abgefragt, solange der Miniserver liefert. Wetterlage-Texte
      (`weatherTypeTexts`) und Einheiten (`format`) kommen aus der Struktur des
      Miniservers — im Code steht keine Tabelle mit Loxone-Wettercodes, weil die
      Nummern je nach Quelle unterschiedlich dokumentiert sind. Was der Dienst
      nicht führt, bleibt leer (Regenwahrscheinlichkeit, UV-Index); lässt sich
      ein Wert nicht sicher beschriften, fällt er weg statt falsch angezeigt zu
      werden. Diagnose unter *Settings → Diagnose* (`weatherServer`). **M**
- [x] **Nachtmodus über ein frei wählbares Control auslösen**: Statt am
      Sonnenstand soll der Nachtmodus an einem Baustein hängen können — Auswahl
      über die Controls der Anlage, gewählter Baustein `active` = Nacht.
      Rangfolge dann: gewähltes Control → Sonnenzeiten (Miniserver →
      Wetterdienst) → festes Fenster. Das deckt **Betriebsmodi mit ab**, sobald
      sie in der Visu liegen: Der Modus selbst ist nicht abgreifbar, wohl aber
      ein Status-Baustein, auf den er in Loxone Config gelegt wird — wie
      „Fernsehen abend" (`InfoOnlyDigital`) und „Frostsicherung" (`Switch`) in
      der untersuchten Anlage. Begründung und Messwerte siehe „Grundregel" in
      [`ARCHITEKTUR.md`](ARCHITEKTUR.md), Abschnitt 6. **M**
- [x] **Split im Hochformat übereinander.** Ein hochkant hängendes Tablet
      (Anlass: Galaxy Tab A9 im Sauna-Vorraum) zeigte Visu und Pane 2 als zwei
      schmale Streifen nebeneinander: gemessen auf 533×893 ein Kasten von
      533×480 mit rund 200 px leerer Fläche darüber und darunter, Kacheln
      118×198 mit abgeschnittenen Namen. Jetzt liegen hochkant oben die
      Kacheln (225×195), darunter die Pane über die volle Breite, unten die
      Tab-Leiste; quer bleibt alles wie bisher. Die Pane ist hochkant fast so
      groß wie quer (480×419 gegen 480×425); Verlauf, Wetter und Kalender
      sind hochkant geprüft, Energie, Kamera und Player bekommen dieselbe
      Fläche. Drehen im Betrieb stellt um, auch auf einer Detailseite. Details in
      [`ARCHITEKTUR.md`](ARCHITEKTUR.md) unter „Split hochkant“. **M**
- [x] **Hochformat vervollständigt.** Nach dem Split fehlte hochkant noch:
      Tabs ohne Pane 2 blieben ein 2×2-Quadrat (533×893: je 180 px leer
      darüber und darunter, mit „Bildschirm füllen“ auf 252×404 gestreckte
      Kacheln), und die Uhr-Seite sah aus wie am 4″-Panel (440×442 in der
      Mitte, die gewählte zweite Fläche erschien nie). Jetzt verdoppelt
      „Screen füllen“ hochkant die Zeilen (2×2 → 2×4, Kacheln 225×197; 2×3
      bleibt, es ist schon ein Hochformat-Raster), und die Uhr-Seite zeigt
      Uhr, Wetter und darunter die zweite Fläche (Verlauf 451×456, mittig).
      Nachgezogen: Assistent „Neues Panel“ (Zusatzfläche quer rechts,
      hochkant darunter), Editor-Hinweise, Übersicht und Geräteseite mit
      Hochkant-Skizzen, englische Übersetzungen, Android-Anleitung. Details in
      [`ARCHITEKTUR.md`](ARCHITEKTUR.md) unter „Screen füllen“ und
      „Screensaver“. **M**
- [x] **Sprungmarken: Sprung auf die richtige Seite, Aufleuchten, Filter.**
      Im Raum-Panel (und in der freien Auswahl) rutschte ein Tipp auf eine
      Sprungmarke eine Seite zu weit, sobald die Gruppe unten auf einer Seite
      begann: die Kachelfläche rastet seitenweise ein, und der Sprung landete
      am nächsten Rastpunkt. Gemessen verschwand die Zielkachel 199 px (2×2)
      bzw. 210 px (2×3 hochkant) über dem sichtbaren Bereich. Jetzt springt
      das Panel auf die Seite, auf der die Gruppe beginnt, und ihre Kacheln
      leuchten kurz auf. Neu als Option je Panel („Tipp auf eine Sprungmarke“,
      `ui.catFilter`): Filtern zeigt nur die Gruppe, ein zweiter Tipp oder eine
      Minute Ruhe wieder alle. Anlass: im Sauna-Raum (wenige Kacheln) bewirkte
      ein Tipp auf „Licht“ sichtbar nichts. Details in
      [`ARCHITEKTUR.md`](ARCHITEKTUR.md) unter „Sprungmarken“. **M**
- [x] **Betriebsmodus-Assistent: Ausweg und Geräte ohne Namen.** Aus dem
      Assistenten kam man nur per Klick neben das Fenster heraus: kein
      Schließen-Knopf, kein Esc, und in Schritt 1 waren „Zurück“ und ohne
      bekanntes Gerät auch „Weiter“ gesperrt. Dazu meldete er „Noch kein Gerät
      bekannt“, obwohl ein Gerät ohne Namen verbunden war. Jetzt haben beide
      Assistenten (Betriebsmodus, Neues Panel) ein ✕ und schließen mit Esc; ein
      verbundenes Gerät ohne Namen wird im Assistenten benannt und ist danach
      gewählt. Nebenbei: „?device=<name>“ erschien als „?device=“, weil
      `<name>` als HTML-Tag gelesen wurde (auch in der Geräteliste). Die
      Automatik selbst war in Ordnung: nachgestellt schaltet `/api/mode/<modus>`
      das Gerät auf die zugeordnete Ansicht um. Geprüft in
      `test_betriebsmodus_assistent_ausweg_und_benennen`. **S**
- [x] **Display nach Präsenzmelder.** Je Gerät unter *Displays →
      Betriebsmodus-Automatik & Display-Steuerung* ein Baustein mit
      `active`-State (Präsenzmelder, Schalter, digitaler Status): Solange er
      jemanden meldet, bleibt das Display hell und die Leerlaufzeit ist
      ausgesetzt; wird der Raum leer, geht es aus, kommt jemand, wieder an.
      Wirkt mit Fully Kiosk (JavaScript-Schnittstelle, Remote Admin) und
      WallPanel, nicht bei Linux-Panels mit Agent. Neben der Auswahl steht der
      aktuelle Stand. Details in [`ARCHITEKTUR.md`](ARCHITEKTUR.md) §8,
      Einrichtung in `deploy/ANDROID.md`; geprüft in `tests/test_praesenz.py`
      und `tests/browser/test_praesenz_browser.py`. **M**
- [ ] **Präsenzmelder an der Anlage prüfen:** am Android-Panel mit Fully
      Kiosk einen Melder koppeln, den Raum verlassen und wieder betreten, die
      Nachlaufzeit des Melders in Loxone Config passend einstellen. **S**
- [ ] **Hochformat an der Anlage prüfen**, sobald das Tab A9 hängt:
      echte Bildschirmgröße unter *Displays → Geräte & Ansicht* ablesen,
      Sauna-Profil mit „Bildschirm füllen“, Verlaufs-Pane und Uhr-Seite
      ansehen. Danach das Tab A9 in die Geräteseite aufnehmen (sie nennt nur
      erprobte Geräte). **S**
- [x] **Neuer Kachel-Aufbau nach den Kacheln der Loxone-App** (Standard für
      alle Panels, „Klassisch“ je Panel wählbar unter *Panels → Aussehen &
      Verhalten → Kachel-Aufbau*). Der Raum steht klein oben rechts, der Pfeil
      fällt weg. Bei Anzeige-Bausteinen steht der Zustand groß und der Name
      klein darunter („Leer“ über „Postkasten“). Bei Kacheln, die direkt
      schalten, und bei reinen Beschreibungen („Türsprechanlage“) bleibt der
      Name vorn. Raumregelung und Sauna zeigen die Temperatur groß an Stelle
      des Symbols, darunter Soll und Tätigkeit untereinander. Tasten liegen
      als Leiste unten über die ganze Breite, 44 px hoch statt 34 px rund.
      Lange Namen werden getrennt statt mit „…“ gekappt. Das Raster bleibt,
      auch am 4″-Panel (2×2, 3×3). Dort weicht auf enger Kachel Stufe für Stufe
      das Unwichtigste: erst einzeilig, dann die Angabe zum Mini-Verlauf, dann
      die zweite Zeile. Gemessen bei 3×3 schneidet der klassische Aufbau 9 von
      13 Namen ab, der neue 4. Er schneidet nirgends etwas ab, was der
      klassische ganz zeigt, auch nicht mit den Größen 20/15 älterer
      Installationen. Der Mini-Verlauf bleibt auch dort, wo der klassische
      Aufbau keinen Platz für ihn hat (18 Kacheln auf 800×480). Details in
      [`ARCHITEKTUR.md`](ARCHITEKTUR.md) §7.1. Tests:
      `tests/test_kachel_aufbau.py`, `tests/browser/test_kachel_aufbau_browser.py`,
      `test_mini_verlauf_im_neuen_aufbau`. **L**
- [x] **Schriften anpassbar.** Unter *Global → Darstellung* und je Panel:
      Haupttext, Zweittext (früher „Name-“/„Sub-Größe“), dazu neu Raum und
      Messwert. Die Schrift einer Kachel aus „Kacheln gestalten“ (Farbe, fett,
      kursiv) trifft im neuen Aufbau auch den Zustand, wenn er vorn steht.
      Ohne Einstellung gilt der Standard des Kachel-Aufbaus (neu etwas kleiner
      als klassisch). Leere Felder zeigen grau, was gilt, im Panel erst den
      globalen Wert. Vorher wirkte kein Standard: `load_theme()` und die
      Vorlage `theme.example.json` setzten feste Größen, der Konfigurator
      zeigte Werte, die niemand gewählt hatte. Eine `theme.json` aus der
      früheren Vorlage trägt noch 20/15, für den neuen Standard die Felder
      leeren. Details in [`ARCHITEKTUR.md`](ARCHITEKTUR.md) §5.4. **M**
- [x] **Kopfzeile statt Pane 2** (06.10.2026). Neues Widget je Tab:
      `"header"` bzw. `"header:<uuid>,…"` in `ui.panes` legt eine Zeile
      **über** das Kachelraster mit Uhr, Wetter in Kurzform und nach Wahl bis
      zu acht Werten (dieselbe Anmeldung wie „Werte“, `setsvstatus`). Vorbild
      ist die Startseite der Loxone-App: Uhrzeit, Wetter und der Haus-Status
      auf einen Blick, darunter die Kacheln. Auf einem Tablet quer nimmt die
      Zeile 64 px statt der 40 % eines Widgets, und das Raster bleibt
      ungeteilt; „Automatisch“ rechnet die Zeile von der freien Höhe ab, beim
      festen Raster geht sie vom Kasten ab. Was rechts nicht mehr passt,
      bleibt weg. Sie gilt auch mit Split „Aus“ (4″-Panel), denn sie ist
      keine Pane. Widget-Seiten und die Uhr-Seite kennen die Kopfzeile nicht
      (dort wäre sie doppelt oder leer), der Server meldet sie als
      `verworfen`. Konfigurator: Auswahlfeld „Widget je Tab“ → „Kopfzeile
      (Uhr, Wetter, Werte)“ mit Werteliste wie bei „Werte“, ohne Split nur
      sie; Assistent ebenso (für 1 Pane „Kopfzeile je Tab“). Nebenbei aus
      dem Codex-Review: `ui.panes` wird jetzt normiert gespeichert und
      exportiert („header:A, B“ → „header:A,B“), vorher ging der Rohwert
      durch und ein Leerzeichen wurde Teil der UUID. Tests:
      `tests/test_kopfzeile.py` (4), `tests/browser/test_kopfzeile_browser.py`
      (8: quer, hochkant, 10″, 4″ mit Split „Aus“, zu viele Werte, Drehen,
      Konfigurator mit und ohne Split, Assistent). Details in
      [`ARCHITEKTUR.md`](ARCHITEKTUR.md) §5.3 und §7.1. **M**
- [ ] **Anzeige und Einrichtung: angenommene Vorschläge vom 06.10.2026.**
      Grundlage war eine Messreihe mit 23 Favoriten in acht Bildschirmgrößen
      (480×480 bis 2560×1600) und fünf Profilvarianten: Die Kachel*anzahl*
      passt sich dem Schirm an, der Kachel*inhalt* nicht (Symbol 38 px,
      Schrift 16/14 px von 122- bis 628-px-Kacheln), „Automatisch“ kennt die
      Zahl der Kacheln nicht (23 auf 112 Zellen), und die Kachelstufen sind
      CSS-Pixel ohne Bezug zum Gerät. Entschieden am 06.10.2026, alle
      umsetzen, in dieser Reihenfolge:
      1. **Kachelinhalt skaliert mit der Kachelbreite:** Faktor Breite ÷ 170,
         begrenzt auf 0,85 bis 2,0, einmal je Raster gesetzt, multipliziert
         Symbol, Name, Zweittext, Messwert, Tastenleiste, Innenabstand und
         `--kopf-h`. Nutzergrößen gelten als „bei 170-px-Kachel“. **M**
         *Erledigt 06.10.2026:* dazu begrenzt die Höhe den Faktor (flache
         225×128-Kachel: 0,85 statt 1,32), Tasten schrumpfen nie unter ihr
         Maß, und Textstufen `kst1`–`kst3` nehmen einen Text zurück, der in
         seine Zeilen nicht passt (über Faktor 1 nie unter den Stand ohne
         Faktor). Messreihe: 800×480 mit 3×3 15 → 1 abgeschnittene Namen,
         4″ 3×3 8 → 0, 415-px-Kachel 32-px-Schrift und 76-px-Symbol.
         Details in [`ARCHITEKTUR.md`](ARCHITEKTUR.md) §7.1, Tests in
         `tests/browser/test_kachel_faktor_browser.py` (16).
      2. **Automatik rechnet mit der Kachelanzahl und einem Zielwert je
         Gerät:** passt alles auf eine Seite, wachsen die Kacheln bis 1,4 ×
         Ziel; Zielkachel als Zahl statt drei Stufen, je Gerät unter
         *Displays* übersteuerbar, Vorschlag aus gemeldeter Größe und
         Pixeldichte (`{t:"screen"}`). **M**
         *Erledigt 06.10.2026:* `ui.tileSize` ist eine Zahl (100–400 px, die
         Stufen bleiben lesbar), `devices[name].tileTarget` geht vor und wirkt
         beim Speichern sofort (`{t:"gridAuto"}`), der Vorschlag kommt vom
         Server (`tileSuggest`: Tablet 170, Monitor ein Fünftel der kürzeren
         Seite bis 300), `autoRaster()` lässt wenige Kacheln ohne Widget
         daneben bis `KACHEL_WACHSEN` (1,4) wachsen. Details in
         [`ARCHITEKTUR.md`](ARCHITEKTUR.md) §7.1.
      3. **Breite Kacheln:** Feld `w` je Eintrag (Standard nach Typ: Audio,
         Raumregelung, Energiefluss 2×1; je Kachel übersteuerbar),
         `grid-column: span` mit dichtem Fluss, Blättern und `fitTile()`
         angepasst. **M**
         *Erledigt 06.10.2026:* `tiles[uuid].w` (1 | 2), Standard aus
         `KACHEL_BREIT_TYPEN`, Klasse `w2` mit `grid-auto-flow: row dense`,
         `rasterLage()` rechnet Seiten, Rastpunkte und das Wachsen der
         Automatik mit, der Kachelfaktor misst sich an einer schmalen Kachel.
         Kachel-Editor: „Breite“. Details in [`ARCHITEKTUR.md`](ARCHITEKTUR.md) §7.1.
      4. **Raumnamen aus Kachelnamen streichen,** wenn die Seite den Raum
         schon nennt („Jalousie Wohnzimmer Süd“ auf der Wohnzimmer-Seite).
         Trifft die meisten abgeschnittenen Namen der Messung. **S**
         *Erledigt 06.10.2026:* `_ohne_raum()` auf Raum-Seiten (Tab
         `room:<uuid>` und Raum aus „Räume“), nur ganze Wörter, Seiten über
         mehrere Räume behalten den vollen Namen. Details in
         [`ARCHITEKTUR.md`](ARCHITEKTUR.md) §7.1.
      5. **Werte als schmale Leiste statt als Kacheln,** je Seite wählbar:
         Anzeige-Bausteine in eine Zeile, das Raster für Bedienbares. **M**
         *Erledigt 06.10.2026:* `ui.valueBar` nennt die Seiten, der Server
         trennt die Anzeige-Bausteine (`WERTE_LEISTE_TYPEN`) als
         `view.leiste` ab, die Visu zeigt sie als Chips in einer Zeile über
         dem Raster (scrollt waagerecht, Tipp öffnet die Wertseite), das
         Raster rechnet die Zeile ab. Kästchen je Tab im Konfigurator.
         Details in [`ARCHITEKTUR.md`](ARCHITEKTUR.md) §7.1.
      6. **Tasten nur, wenn die Kachel hoch genug ist** (aus dem Faktor),
         sonst Detailseite; löst das Drei-Zeilen-Problem ohne Sonderfälle. **S**
      7. **Widget-Breite im Editor ziehen** (1 bis 3 Kachelspalten statt
         fest 40 %). **S**
      8. **Seiten waagerecht wischen mit Punkten** auf Tablets, das 4″-Panel
         bleibt bei senkrechtem Einrasten. **M**
      9. **Assistent Schritt 1 aus dem Gerät:** Geräteliste aus
         `/api/devices` mit gemeldeter Größe, „Dieser Browser“ und Katalog
         als Ausweg; nur passende Anzeigen anbieten, jede mit vorgerechnetem
         Raster (eine `raster.js` für Visu und Konfigurator); zum Schluss
         Gerät umschalten und Zielkachel am Gerät merken. **L**
      10. **Seiten-Editor mit Drag & Drop** als Reiter im Panel-Editor und
          als Schritt 5 des Assistenten: Palette (Bausteine, Widgets),
          Arbeitsfläche in Geräteform, Größen 1×1/2×1/2×2, Pointer-Events
          mit Pfeiltasten als Ersatz; Server: `pickTabs[i].layout`
          `[{id,w,h}]`, Raum-Gruppierung dort abschaltbar; Entwurfs-Endpunkt
          für die Vorschau in der echten Visu. **L**
      11. **Kopplungscode am Panel:** Gerät ohne Profil zeigt „Dieses Gerät
          einrichten“ mit Code, derselbe Code steht unter *Displays*. **S**
      12. **Live-Vorschau am Zielgerät** während des Assistenten (Entwurf an
          das gewählte Gerät schicken). **M**
      13. **Vorschlag statt leerer Seite:** Gerätename ↔ Loxone-Raum, sonst
          Loxone-Favoriten; drei Pflichtschritte, Rest mit Standardwerten. **M**
      14. **Profil duplizieren mit Raumtausch.** **S**
      15. **Profil merkt sich sein Zielgerät,** *Displays* warnt bei
          Abweichung. **S**
      16. **Lesbarkeits-Prüfung als Browser-Test:** auf den Standardgeräten
          kein abgeschnittener Name, keine Seite mehr als ein Drittel leer. **S**
          *Teil Abschneiden erledigt mit Punkt 1*
          (`test_lesbarkeit_auf_standardgeraeten`: mit Faktor nicht mehr
          abgeschnitten als ohne, keine Kachel läuft über); der Teil „keine
          Seite mehr als ein Drittel leer“ kommt mit Punkt 2.
      Mockup (Seiten-Editor, Assistent, vier Ansichten) im Canvas „LoxPanel
      Seiten-Editor“, Messreihe in der Sitzung vom 06.10.2026.
- [ ] **Weitere Vorschläge aus der Kachel-Analyse vom 02.10.2026** (noch
      nicht entschieden):
      - Herauslegen: wichtigste Funktion auf die Kachel, nur was die
        Detailseite schon sendet und gefahrlos ist. Schalter-Schieber,
        Zeitschalter ⏱, Taster, Licht Ein/Aus mit Stimmungswahl, Dimmer,
        Fenster ▲▼, Audio Lautstärke und ⏯, Raumregelung −/+, Radiotasten
        −/+, Klima und Bewässerung Ein/Aus, Wecker Schlummern/Aus. Bewusst
        nicht: Tor, Türöffner, Alarmanlage, „Sauna Ein“. Je Kachel wählbar
        („automatisch“/„keine“). Überschneidet sich mit dem nächsten Punkt.
      - Doppelt breite Kacheln für Audio und Energiefluss.
      - Startseite wie die Loxone-App: Uhr und Wetter, darunter Favoriten
        zum direkten Bedienen. *Erledigt als Kopfzeile (Widget „header“),
        siehe oben.*
      - Ruhigerer Aktiv-Zustand: nur Symbol und Zustand farbig, nicht die
        ganze Kachel (die Einstellung gibt es, es wäre ein neuer Standard).
      - Stabilität in der App: Server über `/api/health` überwachen und neu
        starten, WebView-Absturz abfangen, nächtliches Neuladen als Standard.
      - Verbindung: bei Störung ein klarer Hinweis und gesperrte Tasten statt
        des Punkts mitten im Raster.
      - Tipp-Regel: lang drücken öffnet immer die Detailseite.
- [ ] **Bedienelemente direkt auf der Kachel** (zurückgestellt am
      02.10.2026). Vorbild ist der Fork von najrefisch („LoxPanel
      Favoriten-Fork 0.19.0-fav4“,
      [actionhero-zz/loxohnepanel](https://github.com/actionhero-zz/loxohnepanel),
      vorgestellt im Loxforum-Thread „loxpanel“ mit „Bedient euch gerne!“,
      gleiche Lizenz). Heute haben nur Beschattung (▲▼, während der Fahrt
      Stop) und Audio (⏮ ⏯ ⏭) Tasten auf der Kachel (`controls`, `.tctrls`).
      Es fehlen:
      - Schalter und Zeitschalter: ein Schieber oben rechts, der den Zustand
        zeigt und erst beim Tippen schaltet (`click` wie die übrigen
        Kachel-Tasten; bei najrefisch `pointerdown`, dort schaltet also auch
        ein Wischer übers Raster). Der Tipp auf die übrige Kachel schaltet
        weiterhin.
      - Lichtsteuerung: ‹ › für die vorige und die nächste Stimmung
        (`changeTo/<id>`, „Aus“ übersprungen, wie bei najrefisch). Der Tipp auf
        die Kachel öffnet weiter die Detailseite. Nicht übernehmen: seinen
        Doppeltipp für Aus (jeder einfache Tipp wartet dafür 350 ms) und das
        feste Gelb `#f2c14e`, das am abgeleiteten Farbsatz vorbeigeht.
      - Taster: ein runder Knopf; heute löst der Tipp auf die Kachel aus.

      Dazu Browser-Tests (Tippen schaltet, Wischen nicht), danach als Beitrag
      zu Lenardo. **M**

## 10. Sicherheit (zurückgestuft)

Nur relevant, wenn der Server jemals außerhalb des Heimnetzes erreichbar wird
oder Gäste im WLAN nicht vertrauenswürdig sind.

- [ ] **Optionales Zugriffs-Token** für `/config` und alle
      schreibenden `/api/*`-Routen; `/`, `/ws` und die Bild-Proxys bleiben frei.
      Abschaltbar per Umgebungsvariable. (S1) **M**
- [ ] **Cover-Proxy auf bekannte Hosts** (Miniserver, Audioserver)
      einschränken. (S2) **S**
- [ ] **Agent-HTTP absichern**: gemeinsames Token zwischen Server und Agent,
      alternativ nur Anfragen von der Server-IP annehmen. (S4) **S**
- [ ] **Gleichzeitige MJPEG-Streams begrenzen**. (S6) **S**
- [ ] **HTTPS** über einen Reverse-Proxy auf Unraid; dann muss der
      Installer-Befehl in `config.html` das Schema übernehmen. (S3) **M**
- [ ] LoxBerry-`sudoers` enger fassen. Betrifft nur den LoxBerry-Betrieb. (S5) **S**
