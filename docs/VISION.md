# LoxOS – Vision und Roadmap

LoxOS macht aus Loxpanel eine Oberfläche für flache Streifen-Displays neben
dem Monitor (Zielgerät 2560×720 Touch, z. B. ein Klon des Corsair Xeneon
Edge). Vorbild ist die Widget-Fläche des Xeneon Edge: verschieden große
Widgets und Kacheln frei in einem Raster, alles auf einem Bildschirm.

LoxOS ist **Fork-eigen** und geht nicht nach Upstream (`Lenardo1/Loxpanel`).
Wie das zum Mentalmodell „Fork = Upstream + dünne Identitätsschicht“ passt,
steht unten unter „Fork-Regeln“ und in [`CONTRIBUTING.md`](CONTRIBUTING.md).

Diese Datei beschreibt das Ziel aller Stufen. Umgesetzt wird Stufe für Stufe;
was umgesetzt ist, wandert nach [`ARCHITEKTUR.md`](ARCHITEKTUR.md) und steht
dort als Wahrheit. Hier bleibt die Richtung.

## Begriffe

| Begriff | Bedeutung |
|---|---|
| Streifen | Flaches Breitformat-Display, typisch 32:9 bis 4:1 (2560×720, 1920×480, 1280×400) |
| Bento-Seite | Freie Seite (`pickTabs[]`), deren Inhalt ein Raster mit fest platzierten Zellen ist |
| Zelle | Rechteck im Bento-Raster mit Spalte, Zeile, Breite, Höhe; trägt Bausteine oder ein Widget |
| Widget | Inhalt ohne eigenen Loxone-Baustein-Typ: Uhr, Wetter, Kalender, Audio, Energie, Kamera, Verlauf, Werte, Webseite |
| Fließraster | Das heutige Raster freier Seiten: Kacheln fließen in Reihenfolge, die Visu rechnet die Position |
| Hülle | Die Desktop-App „LoxOS“ (Electron), die die Visu auf dem Streifen zeigt |
| Edge-Look | Das Kachel-Set `edge` (Aufbau `lx`, Leiste `links`) |

## Was Bento ist – und was nicht

Der Unterschied zum Fließraster liegt darin, wer entscheidet, wo etwas steht.

**Fließraster (heute):** Die Ansicht legt Bausteine, Reihenfolge und im
Seiten-Editor die Größe fest (1×1, 2×1, 2×2). Die Position rechnet
`raster.js`: Kacheln fließen von links oben nach rechts unten, bei zu vielen
entsteht ein weiteres Blatt. Widgets stehen nie zwischen Kacheln, sondern als
ganze Seite (`pickTabs[].widget`) oder als Pane daneben (`ui.panes`).

**Bento:** Die Seite hat ein Raster aus Spalten und Zeilen. Jede Zelle hat
Spalte, Zeile, Breite und Höhe. Kacheln und Widgets mischen sich frei, Lücken
sind erlaubt, alles steht auf einem Bildschirm. Das Fließraster ist wie Text
in einer Textverarbeitung, Bento wie eine Folie in einer Präsentation.

Bento ist ein **Feature**: eine weitere Wahl unter „Seiteninhalt“ neben
„Kacheln“ und „Widget“, je freie Seite. Wer sie nicht wählt, merkt nichts.
Auf einer Bento-Seite gilt dafür:

- **Der Platz ist begrenzt.** Spalten × Zeilen Felder, es gibt kein zweites
  Blatt.
- **Neue Bausteine erscheinen nicht von selbst.** Ein Pick ohne Zelle zeigt
  der Editor als „nicht platziert“; die Visu zeigt ihn nicht.
- **Das Blatt gehört zu einem Seitenverhältnis.** Die Seite merkt sich, für
  welches Format sie gebaut ist; passt das Gerät nicht, warnt der
  Konfigurator.

Raum-, Kategorie- und Detailseiten bleiben im Fließraster. Bento ist für
Übersichten (Streifen, Startseite eines Tablets, Wand-Dashboard), nicht für
die Bedienung eines ganzen Hauses.

## Roadmap

### Stufe 1 – Fundament

Bento-Layout in Loxpanel mit Editor; LoxOS-Hülle (Vollbild auf dem Streifen,
Widget-/Desktop-Modus per Tastenkürzel, Autostart, Tray).

### Stufe 2 – Wow-Design

Farbton wählbar für das Set `edge`, Ruhemodus mit großer gedimmter Uhr, wenn
niemand da ist, Aufwachen über einen Loxone-Bewegungsmelder, Wischen zwischen
Bento-Seiten mit weichem Übergang.

### Stufe 2.5 – Einfacher einrichten

Audio-Zelle mit Raum und Raumfavoriten, LoxOS-Assistent (Streifen in fünf
Schritten einrichten), Übersicht „Was ist eingestellt?“ mit „Alles auf
Standard“.

### Stufe 3 – Ereignisse

Vollbild-Karten (Türklingel mit Kamera, Sauna bereit, Alarm, Bewässerung),
Seitenwechsel nach Loxone-Betriebsmodus.

### Stufe 4 – Erweiterungen

Bambu-P1S-Widget (Fortschritt, Restzeit, Temperaturen, Kamera),
LoxAI-Eingabe, PC-Medien über die Hülle.

## Stufe 1 im Detail

Jede Phase endet mit grünem `pytest`. Die Reihenfolge ist bindend, weil jede
Phase auf der vorigen aufbaut.

| Phase | Inhalt |
|---|---|
| 0 | Diese Datei, `pickTabs` in `ARCHITEKTUR.md` §5.3, Fork-Ausnahme in `CONTRIBUTING.md`; Mockups im Edge-Look freigeben |
| 1 | Datenformat und Sanitizer (`bento_format.py`): `pickTabs[].bento` in `_sanitize_panels()` und `_pick_tabs()`, iframe-Adresse nur http/https, Überlappung und Rand geprüft |
| 2 | Server: Mixin `bin/bento.py` rendert die Zellen mit Inline-Daten der Widgets, Weiche in `_view_tab()`, Webseiten-Prüfung als Hintergrundaufgabe `bento_task()`; Verlaufs-Zellen zeigen den Standard-Zeitraum (`STAT_DEFAULT_RANGE`) |
| 3 | Kachel-Set `edge` in `theme_colors.py` aus vorhandenen Arten (Aufbau `lx`, Leiste `links`), Kontrastprüfung wie bei allen Sets |
| 4 | `raster.js` (Bento-Raster, Kollision, Größenstufen je Achse), `panel/bento.js` und `bento.css`, keine Tab-Leiste bei nur einer Bento-Seite; Kacheln über `kachelHtml()`/`kachelBinden()` aus `render()` herausgelöst, Pane-Optik zur Laufzeit übernommen, eigener Zellen-Spieler (der Pane-Spieler hängt an festen IDs) |
| 5 | Seiten-Editor `config/bento-editor.js`: Seiteninhalt „Bento“, Spalten/Zeilen, Formatanzeige, Fläche in Geräteform (Gerätewahl und Live-Vorschau des Seiten-Editors), Ziehen, Größengriff, Tastatur, Kollision, Palette, „Nicht platziert“, Quelle bzw. Adresse (dieselbe Regel wie der Server); Grenzen aus `/api/meta` |
| 6 | Browser-Abnahme bei 2560×720, 1920×480 und 1280×400 mit Screenshots |
| 7 | Hülle `loxos/` (Electron 44, exakt gepinnt mit Sperrdatei und Dependabot): Widget-/Desktop-Modus per Tastenkürzel und Tray, Streifen automatisch erkannt (Seitenverhältnis ab 2,5), Autostart, Einrichtung beim ersten Start, Navigation nur zu Loxpanel, Mikrofon nur für Loxpanel; Logik mit Node getestet, Rauchtest der echten Hülle unter Xvfb; Installer über electron-builder (Windows NSIS ohne Adminrechte, macOS DMG, Linux AppImage), gebaut vom Workflow `loxos.yml` bei jedem Tag `loxos-v*` auf den echten Systemen, unsigniert |

## Stufe 2 im Detail

Festgelegt am 24.10.2026. Ziel ist ein Streifen, der neben dem Monitor ruhig
mitläuft: farbig im eigenen Ton, gedimmt mit großer Uhr, solange niemand da
ist, sofort wach, sobald der Bewegungsmelder auslöst, und zwischen zwei
Bento-Seiten per Wisch umschaltbar.

**Nicht Teil von Stufe 2:** Hintergrund nach Sonnenstand oder Wetter (gestrichen,
der Farbton bleibt fest, bis man ihn ändert), UniFi als Anwesenheitsquelle
(gestrichen, es zählt nur der Loxone-Melder), Seitenpunkte (die Leiste links
zeigt die aktive Seite, Punkte kosteten Höhe auf 720 px), Bento-Automatik
(später). Für alle Geräte ohne die neue Einstellung ändert sich nichts.

### Farbton für `edge`

- `edge` bekommt wie `touch` einen `satz` mit `farbton` (Standard und
  Schnellwahl) und wird im Konfigurator über denselben Farbton-Regler
  eingestellt. Gefärbt werden Grund (`--bg`, `--screen`, `--rahmen`),
  Karten, Tasten und Leiste, dunkel eingetönt; das Set bleibt dunkel.
- **Der Akzent wandert mit** (`--glow`, `--accent`, zeigt „an“ im Aufbau
  `lx`). Die Rechnung hält ihn sichtbar entfernt von `--good`, `--warn` und
  `--crit`, damit „an“ nie wie „OK“, „Warnung“ oder „Alarm“ aussieht: Liegt
  der gewählte Ton zu nah an einem davon, weicht der Akzent auf den nächsten
  Ton mit genug Abstand aus (Abstand als benannte Konstante, gesucht wie in
  `_schiebe()`/`_ergaenzen()`). Die Zustandsfarben bleiben fest
  (entschieden am 24.10.2026).
- Die Rechnung aus `_touch_satz()` wird verallgemeinert: Jedes Set mit `satz`
  bringt seine Parameter mit, eine gemeinsame Funktion rechnet daraus die
  Farben. `kachel_set()`, die Kachelfarbe neben dem Regler und die
  Schnellwahl im Konfigurator (heute direkt `touch_satz()`) gehen über sie.
  `touch` sieht danach Wert für Wert aus wie vorher (Test).
- **Eigener Speicherplatz je Set:** Der Farbton von `edge` steht nicht in
  `ui.tileHue` (das bleibt bei `touch`), sondern in einem eigenen Schlüssel
  mit eigenem Standard in `PANEL_STANDARD`, freigeschaltet in
  `_sanitize_panels()` und `_panel_export()`. Eine Ansicht, die früher
  einen Farbton für `touch` gespeichert hat und jetzt `edge` nutzt, bleibt
  nach dem Update unverändert.
- Ohne gewählten Farbton bleibt `edge` genau wie heute (die festen Farben
  aus `farben`); die Rechnung greift erst, wenn ein Farbton gewählt ist. Ein
  einzelner Ton kann den heutigen Look nicht treffen, er hat zwei (Grund
  bläulich um 225°, Akzent Mint um 162°).
- Kontrast wie bei allen Sets: `tests/test_kachel_set.py` prüft `edge` über
  den ganzen Farbkreis (alle Grad oder feine Schritte), AAA Hauptschrift, AA
  Rest, 3:1 Grafik, auch für Bento-Widgets und die Nacht-Uhr (`--nacht-ink`).

### Ruhemodus

Heute zeigt jede Visu nach `SAVER_IDLE_MS` (60 s) ohne Berührung die
Uhr-Seite, auch wenn jemand davorsitzt; `{t:"display", on:false}` vom
Präsenzmelder macht in einem Browser ohne Kiosk-App (also in der Hülle)
nichts. Neu:

- **Einstellung je Gerät** neben dem Präsenzmelder (`devices[name]`,
  Einstellungen → Geräte), Name `ruhe` (bool), Standard aus. Wählbar nur mit
  gekoppeltem Präsenzmelder. Freigeschaltet in `_sanitize_devices()`
  (`konfig.py`) und zurückgegeben über `/api/devices`, damit sie ein
  Speichern übersteht; an die Visu geht sie mit der `theme`-Nachricht wie
  `presence`.
- **Mit `ruhe` an** steuert der Melder die Uhr-Seite statt der 60-s-Zeit:
  - Meldet er jemanden, bleibt die zuletzt gezeigte Seite stehen, der
    Ruhe-Timer (`resetIdle()`/`nachRuhe()`) läuft nicht.
  - Meldet er niemanden (`{t:"display", on:false}` oder `presence:false`
    beim Laden), zeigt die Visu die Nacht-Uhr, zu jeder Tageszeit: derselbe
    Weg über `.saver.nacht`/`nachtUhrSetzen()`, mit erweiterter Bedingung
    (Nacht-Uhr an **oder** Ruhe), kein zweiter Uhr-Bauer. Helligkeit aus
    `nightClockBright` der Ansicht, Drift gegen Einbrennen wie heute, Wetter,
    Termine und Kamera ruhen. Das Display wird nie ausgeschaltet.
  - Meldet er wieder jemanden (`{t:"display", on:true}`), verschwindet die
    Uhr sofort und die Seite von vorher steht wieder da (nicht die erste
    Seite wie bei `nachRuhe()`).
  - Ein Tipp weckt ebenfalls (`wake()`). Meldet der Melder dann weiter
    niemanden, kehrt die Ruhe-Uhr nach `SAVER_IDLE_MS` ohne Berührung zurück.
- Klingel, Wecker, `notify` und `goto` wecken wie heute.
- **„Nie aus“ gilt für alle Wege:** Mit `ruhe` an zeigt das Gerät bei
  „niemand da“ die Ruhe-Uhr statt abzuschalten, auch wenn es sonst
  abschalten könnte (Display-Treiber in `verteilung.py`, `screenOff()` der
  Kiosk-App, `idle` nach `dpmsOff`, `setDisplayOff()` der Android-App).
  Ohne `ruhe` bleibt jeder dieser Wege, wie er ist.
- Die Visu in der Hülle zeigt die Ruhe-Uhr selbst. Die Hülle verhindert
  dazu, dass der Energiesparplan des PCs die Bildschirme abschaltet
  (`powerSaveBlocker('prevent-display-sleep')`); das hält auch den
  Hauptmonitor an. Schalter `bildschirmWach` in `loxos.json`, Standard an,
  in der Einrichtung und im Tray änderbar (entschieden am 24.10.2026).

### Wischen zwischen Bento-Seiten

- Gilt in jeder Ansicht mit mindestens zwei Bento-Seiten und nur auf
  Bento-Seiten. Das Ziel ist die nächste bzw. vorige Bento-Seite in der
  Reihenfolge der Leiste; normale Seiten dazwischen werden übersprungen.
- Ein Finger waagerecht über die Fläche (Mindestweg und Richtungsregel nach
  dem Muster der Gesten in `gesten.js`, `GESTE_MINDESTWEG`, als eigene
  benannte Konstanten in `panel/bento.js`; die Kachelseiten des Tablets
  blättern dagegen per nativem Scroll-Snap und haben keine), beim Loslassen
  wechselt die Seite über `goTab()`/`nav()`. Am Rand der ersten bzw. letzten
  Seite passiert nichts (kein Rundlauf).
- **Übergang:** Der Server rendert nur die aktuelle Seite; die Nachbarseite
  liegt nicht im DOM. Die Seite folgt dem Finger darum nicht, sondern gleitet
  nach dem Loslassen in Wischrichtung hinaus und die neue herein, sobald die
  `view`-Nachricht da ist (View Transitions in Chromium/Electron; ohne die
  Schnittstelle wechselt sie hart). Dauer als benannte Konstante. Ein Tipp in
  die Leiste wechselt mit demselben Übergang.
- Was nicht blättert: Wischen auf Kachel-Tasten, Reglern und Diagrammen
  (sie behalten ihre Gesten), Zwei-Finger-Gesten (unverändert), Wischen in
  einer Webseiten-Zelle (das iframe bekommt die Berührung, die Visu sieht sie
  nicht).

### Phasen

| Phase | Inhalt |
|---|---|
| 8 | Farbton für `edge`: Rechnung verallgemeinert, `edge` mit `satz`, Konfigurator-Regler, Kontrasttest über den Farbkreis, `touch` unverändert |
| 9 | Ruhemodus: Geräte-Einstellung `ruhe` (Sanitizer, `/api/devices`, `theme`), Ruhe-Uhr über die Nacht-Uhr, Melder statt 60-s-Zeit, kein Abschalten mit `ruhe`; Hülle mit `bildschirmWach` (Node-Test); Tests am Miniserver-Nachbau und im Browser |
| 10 | Wischen zwischen Bento-Seiten mit Übergang, Browser-Tests bei 2560×720 und 1920×480 |

Jede Phase endet mit grünem `pytest`, umgesetztes wandert nach
`ARCHITEKTUR.md`.

**Stand 24.10.2026:** Die Phasen 8, 9 und 10 sind umgesetzt und stehen in
`ARCHITEKTUR.md`: Farbton für `edge` (`tileHueEdge`) in §5.3 (`panels.json`)
und §5.4 (`theme.json`), Ruhemodus (`ruhe`, `{t:"display"}`) in §3.6
(Nachrichtenprotokoll), §7.1 (`ruhe.js`) und §8; `bildschirmWach` der Hülle
in der Zeile `loxos/` der Dateitabelle und in `loxos/README.md`; Wischen
zwischen Bento-Seiten (`tabMeta`) in §3.6 und §7.1 (Bento: Wischen). Die
Abschnitte oben bleiben als Richtung stehen.

## Stufe 2.5 im Detail

Festgelegt am 24.10.2026 aus den Befunden am Streifen: „Ich habe generell
ein kleines Problem mit dem Einrichten, es ist schon viel“ und „man hat
keinen Überblick, was eingestellt ist“. Der Nutzer hat die Entscheidungen
an die Umsetzung übergeben; sie stehen hier als getroffen.

**Ziel:** Wer einen Streifen hat, richtet ihn ohne Wissen über Rubriken und
Reiter ein; wer herumprobiert hat, sieht, was er geändert hat, und kommt mit
einem Klick zurück.

**Nicht Teil von Stufe 2.5:** Bento-Automatik für bestehende Seiten, ein
Assistent für andere Geräte als Streifen, Übersicht über Geräte-Einstellungen
(die stehen schon gesammelt unter „Geräte“).

### Audio-Zelle mit Raum und Raumfavoriten

- Die Zelle zeigt oben klein in Großbuchstaben den **Raum der Audiozone**
  (Loxone-Raum des Bausteins), wie der Raumname auf den Kacheln; ohne Raum
  den Namen der Zone.
- Darunter bzw. unter den Tasten eine **Reihe der Raumfavoriten**: derselbe
  `favs`-Block, den Spieler-Pane und Detailseite aus dem Server bekommen
  (`_sender_bloecke()`/`_zonen_favoriten()`), dieselben Befehle, Cover und
  Name. Die Reihe scrollt waagerecht; das Seitenwischen lässt waagerechte
  Scroller schon aus.
- Reicht die Höhe der Zelle nicht (Höhenstufe `klein`, `data-hstufe`),
  fällt die Reihe weg. Ein Tipp auf den Raumnamen öffnet dann wie überall
  die Musikauswahl (`view: sources`), so bleiben die Favoriten auch in
  kleinen Zellen erreichbar.
- Ohne Favoriten (Audioserver nicht verbunden o. ä.) bleibt die Zeile leer;
  den Grund zeigt die Musikauswahl.

### LoxOS-Assistent

- Eigenes Overlay im Konfigurator (`config/loxos-assistent.js`, Fork), nach
  dem Muster des Mehrschritt-Ablaufs der Betriebsmodi (`mzFlow()` in
  `geraete.js`). Einstieg: Knopf **„LoxOS-Streifen einrichten“** in der Rubrik
  „Geräte“ und auf der Übersicht neben „Gerät einrichten“.
- **Schritt 1 – Gerät:** Auswahl aus den bekannten Geräten; Geräte, deren
  gemeldeter Schirm ein Streifen ist (Seitenverhältnis ab 2,5), stehen oben.
  Die Schwelle ist eine benannte Konstante im Server, über `/api/meta`
  erreichbar; ein Test prüft, dass sie der Schwelle der Hülle
  (`loxos/src/monitor.js`) entspricht. Ein noch unbenanntes Gerät wird hier
  benannt (`/api/device/name`).
- **Schritt 2 – Anwesenheit:** Präsenz- oder Bewegungsmelder wählen (dieselbe
  Auswahl wie unter „Geräte“), „Ruhe-Uhr statt Display aus“ vorausgewählt;
  „ohne Melder“ ist erlaubt und lässt beides weg.
- **Schritt 3 – Aussehen:** Set `edge` ist gesetzt; Farbton über dieselbe
  Schnellwahl wie im Konfigurator, „Original“ vorausgewählt.
- **Schritt 4 – Startseite:** Eine Bento-Seite mit **Vorbelegung**, die der
  Server rechnet (reine Funktion `bento_vorschlag()` in `bento_format.py`,
  Endpunkt im Konfigurator): Raster im Standard (`BENTO_*`), Uhr, Wetter,
  Energiefluss (wenn die Anlage einen hat), Audio (erste Zone der Anlage),
  Kalender (wenn ein Abo eingerichtet ist), freie Zellen mit den
  Favoriten-Bausteinen der Anlage (`isFavorite`), höchstens so viele, wie
  Zellen frei sind. Was die Anlage nicht hat, fällt weg; die Lücken füllen
  Favoriten. Der Vorschlag trägt `format` (`vw`, `vh`) aus dem gemeldeten
  Schirm des Geräts, sonst warnt der Bento-Editor sofort. `bento_vorschlag()`
  bleibt rein (kein Import aus `konfig.py` oder der App): Der Endpunkt
  sammelt, was die Anlage hat, und reicht es als einfache Daten hinein; der
  Vorschlag besteht `bento_seite()` unverändert, nichts wird verworfen
  (Test). Rechts eine Live-Vorschau in Gerätegröße (wie „Gerät einrichten“,
  `/api/entwurf`).
- **Schritt 5 – Fertig:** Legt eine **neue** Ansicht „LoxOS · <Gerät>“ an
  (bestehende werden nie überschrieben; gibt es den Namen schon, wird
  durchgezählt), ordnet sie dem Gerät zu (`/api/device/switch`), speichert
  Melder und `ruhe` (`/api/devices`). Danach steht der Bento-Editor offen,
  um die Seite anzupassen.
- Abbrechen ändert nichts; gespeichert wird nur in Schritt 5.

### Übersicht „Was ist eingestellt?“

- Neue Karte oben im Reiter „Allgemein“ jeder Ansicht und der Vorgaben
  (`config/abweichungen.js`, Fork; Einhängen als ein Aufruf in
  `ansicht-editor.js`): eine Liste **aller Einstellungen, die vom Standard
  abweichen**, je Zeile Name, eigener Wert, was ohne ihn gälte
  (`wasGiltOhneEigenen()`/`giltText()`), ein Knopf „× zurücksetzen“ und ein
  Sprung zum Reiter, in dem die Einstellung steht.
- Grundlage sind die vorhandenen Bausteine: `standardWert()`, `wertText()`,
  `wasGiltOhneEigenen()`; dazu eine Tabelle Schlüssel → Name → Reiter für alle
  `ui`-Schlüssel, die `_panel_export()` ausgibt (`ABWEICHUNG_FELDER`), Namen
  über `i18n.js`. Ein Schlüssel ohne Eintrag erscheint mit seinem
  technischen Namen, nie gar nicht; ein Test prüft, dass jeder `ui`-Schlüssel
  aus der Liste von `_panel_export()` einen Eintrag hat.
- **„Alles auf Standard“** setzt alle aufgelisteten **Darstellungs- und
  Verhaltenswerte** zurück (Größen, Schrift, Farben, Raster, Nacht, Display,
  Gesten). **Nicht** zurückgesetzt werden Inhalt und Look: Seiten, Räume,
  Kategorien, Widgets/Panes, Kachel-Set und Farbton; sie stehen in der Liste,
  aber mit eigenem Knopf. Welche Schlüssel zu welcher Gruppe gehören, steht
  als benannte Liste im Code (`ABWEICHUNG_BLEIBT`), nicht nur hier. Vor dem
  Zurücksetzen fragt eine Bestätigung in der Seite (kein Browser-Dialog), was
  zurückgesetzt wird; in den Vorgaben nennt sie dazu, für wie viele Ansichten
  die Werte gelten („gilt für n von m“).
- Zurückgesetzt wird in der Arbeitskopie; wirksam erst mit „Speichern“, wie
  jede andere Änderung im Konfigurator.

### Phasen

| Phase | Inhalt |
|---|---|
| 11 | Audio-Zelle: Raum oben, Favoriten-Reihe, Tipp auf den Raum öffnet die Musikauswahl; Server liefert Raum und `favs` in den Zelldaten; Tests am Nachbau und im Browser |
| 12 | LoxOS-Assistent: `bento_vorschlag()` mit Tests, Endpunkt, Overlay mit fünf Schritten, Live-Vorschau, Speichern; Browser-Test vom Gerät bis zur fertigen Bento-Seite |
| 13 | Übersicht „Was ist eingestellt?“ mit Zurücksetzen je Zeile und „Alles auf Standard“, für Ansichten und Vorgaben; Browser-Tests |

## Datenformat

Bento erweitert eine freie Seite um den Schlüssel `bento`. Fehlt er, bleibt
die Seite, was sie heute ist (Kacheln oder Widget).

```jsonc
"pickTabs": [{
  "name": "Streifen", "icon": "", "picks": ["<control-uuid>", "…"],
  "bento": {
    "cols": 6, "rows": 2,                  // Grenzen: BENTO_SPALTEN_MIN..MAX, BENTO_ZEILEN_MIN..MAX
    "format": {"vw": 2560, "vh": 720},     // für welches Format gebaut (CSS-px des Vorschaugeräts)
    "cells": [
      {"x": 0, "y": 0, "w": 1, "h": 2, "widget": "clock"},
      {"x": 2, "y": 1, "w": 1, "h": 1, "ids": ["<control-uuid>", "<control-uuid>"]},
      {"x": 3, "y": 0, "w": 2, "h": 1, "widget": "energy:<uuid>"},
      {"x": 5, "y": 1, "w": 1, "h": 1, "widget": "iframe", "url": "https://…"}
    ]
  }
}]
```

Regeln, die alle Stufen einhalten:

1. **`picks` bleibt die Wahrheit** darüber, welche Bausteine zur Seite
   gehören. Eine Zelle nennt nur Bausteine aus `picks`; fällt ein Pick weg,
   fällt er aus der Zelle (wie heute im `layout`). `hide` gilt weiter.
2. **Zellen sind Whitelist-Objekte.** Unbekannte Schlüssel verwirft der
   Sanitizer und meldet sie (`verworfen`). Spätere Stufen fügen Schlüssel
   hinzu, alte Dateien bleiben gültig.
3. **Zellen liegen im Raster und überlappen nicht.** Was über den Rand ragt
   oder eine andere Zelle trifft, verwirft der Sanitizer und meldet es.
4. **Widget-Grammatik wie bei den Panes** (`_clean_tabpane`), dazu `clock`
   und `iframe`. Die Adresse des iframe steht im eigenen Feld `url`, weil
   Adressen Doppelpunkte enthalten; erlaubt sind nur `http` und `https`.
5. **Leere `cells`** sind gültig und heißen später „Bento-Automatik“: Der
   Server verteilt die `picks` selbst. Bis dahin zeigt eine leere Seite
   einen Hinweis zum Editor.
6. **Nichts im Code festgelegt:** Grenzen sind benannte Konstanten
   (`BENTO_*` in `bento_format.py`, über `konfig.py` erreichbar), Farben
   kommen aus dem Kachel-Set, Inhalte vom Miniserver oder aus der
   Konfiguration.
7. **Widgets mit Quelle dürfen mehrfach stehen** (Audio, Kamera, Verlauf,
   Werte, Energie, Webseite – je mit eigener Quelle), Widgets ohne Quelle
   (Uhr, Wetter, Kalender) einmal je Seite. Der Editor blendet bereits
   gesetzte aus, der Sanitizer verwirft Doppelte und meldet sie.

## Architektur-Entscheidungen

- **Widget-Daten inline in den Zellen.** Die Widget-Kanäle (`conn_energy`,
  `conn_camera`, `conn_chart`, `conn_player`, `conn_status`) gibt es je
  Verbindung nur einmal. Eine Bento-Seite braucht mehrere zugleich. Der
  Server rendert die Widget-Inhalte darum mit denselben Blockbauern in die
  Zellen der view-Nachricht. Lesespur über `self.states` und `_dirty`
  sorgen für Aktualität, `_last_sent` verhindert doppeltes Senden. Uhr,
  Wetter und Kalender brauchen nichts Neues: Die Uhr tickt in der Visu,
  Wetter und Kalender kommen mit `{t:"front"}`.
- **Webseiten prüft der Server.** Ob eine fremde Seite im iframe lädt oder
  Einbetten verbietet (`X-Frame-Options`, CSP `frame-ancestors`), kann die
  Visu nicht zuverlässig erkennen. Der Server prüft Erreichbarkeit und
  Kopfzeilen und schreibt das Ergebnis in die Zelle; die Visu ergänzt einen
  Lade-Timeout. Grenze: Eine Adresse, die nur vom Gerät erreichbar ist
  (etwa `localhost` neben der Hülle), kann der Server nicht prüfen.
- **Skalierung über den Kachelfaktor.** Schrift, Icons und Diagramme
  wachsen je Zelle über `kachelFaktorFuer()` in `raster.js`; ein 6×2-Blatt
  bleibt auf jedem Streifen 6×2. Reicht Schrumpfen nicht, zeigt ein Widget
  weniger statt abzuschneiden: `raster.js` gibt jeder Zelle eine Stufe
  (`data-stufe`, aus der Zellgröße im Verhältnis zur Zielkachel), und je
  Stufe fallen Nebenzeilen weg (Wind beim Wetter, Tagessummen bei der
  Energie, Prozentzahl beim Audio). Die Schwellen leiten sich aus den
  vorhandenen Kachel-Ziel-Konstanten ab, nicht aus eigenen Zahlen.
- **Edge-Look als Kachel-Set.** Das Set `edge` wirkt auf die ganze Visu,
  nicht nur auf Bento-Seiten. Es nutzt vorhandene Arten – Aufbau `lx`
  (Zustand über Tönung und Akzent) und Leiste `links` (auf einem
  32:9-Streifen kostet eine Seitenleiste Breite statt der knappen Höhe) –
  und bringt nur Farben und Maße mit; die feine Kante der Karten ist ein
  Innenrand über `--kachel-schatten`. Ein eigener Aufbau wäre eine zweite
  Kachel-Darstellung in Upstream-Dateien gewesen. Regeln hängen wie immer
  an der Art, nie am Namen. Die Kontrastprüfung gilt auch für Widgets.
  Feste Farben in Stufe 1; ein Farbton-Regler wie bei `touch` folgt in
  Stufe 2 (siehe „Stufe 2 im Detail“).
- **Hülle mit Electron** in `loxos/`, Einstellungen in `loxos.json`. Die
  Abhängigkeiten sind festgenagelt wie die übrigen (Sperrdatei, Dependabot).

## Was Stufe 1 für später vorbereitet

| Stufe | Baut auf |
|---|---|
| 2 Farbton für `edge` | die Rechnung aus `touch_satz()` auf mehrere Sets verallgemeinert |
| 2 Ruhemodus | Nacht-Uhr (`.saver.nacht`, `nightClockBright`) |
| 2 Aufwachen | `devices.presence` (Loxone) und `{t:"display"}` |
| später Bento-Automatik | leere `cells` (Regel 5) |
| 3 Ereigniskarten | Server-Push über `push()`, eine Karte ist eine Zelle über die ganze Fläche |
| 3 Seitenwechsel | `devices.modes` ordnet heute Betriebsmodi Ansichten zu; erweitert auf Seiten |
| 4 Bambu P1S | ein weiterer Zellbauer im Mixin `bento.py` |
| 4 LoxAI | ein Widget, Eingabe in der Zelle |
| 4 PC-Medien | eine Brücke der Hülle nach dem Muster der `LoxKiosk`-Brücke der Android-App |

## Fork-Regeln

LoxOS bleibt im Fork. Damit jeder Upstream-Abgleich berechenbar bleibt:

- **Neue Dateien statt Änderungen.** Logik steht in eigenen Modulen
  (`bin/bento_format.py`, `bin/bento.py`, `panel/bento.js`, `panel/bento.css`,
  `config/bento-editor.js`, `loxos/`).
- **Kleine Andockstellen** in Upstream-Dateien, jede als zusammenhängender
  Block: Aufruf des Prüfers in `_sanitize_panels()` und `_pick_tabs()`
  (`konfig.py`, laut `CLAUDE.md` der Pflichtort; die Prüfung selbst steht in
  `bento_format.py`, weil `konfig.py` an der Längengrenze von
  `test_dateigroessen.py` liegt), Weiche in `_view_tab()` (`seiten.py`), Set in
  `theme_colors.py`, Datenparameter der Widget-Renderer (`front.js`,
  `kacheln.js`), das Set in `KACHEL_SETS` mit seiner Übersetzung, Weiche im Seiten-Editor, Script- und Stylesheet-Tags in
  `panel.html` und `config.html`.
- **Nach jedem Upstream-Merge** laufen die LoxOS-Tests mit; ein Konflikt an
  einer Andockstelle wird dort gelöst, nicht durch Kopieren von
  Upstream-Code in LoxOS-Dateien.
- Branches heißen `feat/loxos…`, PRs gehen gegen `main` des Forks.

## Offene Punkte

- Mehrere Kamera-Zellen heißen mehrere Video-Streams zur Türstation.
- Monitor-Erkennung der Hülle unter Windows und macOS (Streifen über
  Auflösung oder Kennung aus `loxos.json`).
