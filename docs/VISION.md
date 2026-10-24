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

Hintergrund nach Sonnenstand und Wetter, Ruhemodus mit großer Uhr, Aufwachen
über Anwesenheit (UniFi/Loxone), weiche Seitenübergänge.

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
| 7 | Hülle `loxos/` (Electron 44, exakt gepinnt mit Sperrdatei und Dependabot): Widget-/Desktop-Modus per Tastenkürzel und Tray, Streifen automatisch erkannt (Seitenverhältnis ab 2,5), Autostart, Einrichtung beim ersten Start, Navigation nur zu Loxpanel, Mikrofon nur für Loxpanel; Logik mit Node getestet, Rauchtest der echten Hülle unter Xvfb |

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
5. **Leere `cells`** sind gültig und heißen ab Stufe 2 „Bento-Automatik“: Der
   Server verteilt die `picks` selbst. In Stufe 1 zeigt eine leere Seite
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
  Stufe 2 (die Rechnung ist heute fest an `touch` gebunden).
- **Hülle mit Electron** in `loxos/`, Einstellungen in `loxos.json`. Die
  Abhängigkeiten sind festgenagelt wie die übrigen (Sperrdatei, Dependabot).

## Was Stufe 1 für später vorbereitet

| Stufe | Baut auf |
|---|---|
| 2 Hintergrund | Set-Variablen des Kachel-Sets; Sonnenauf- und -untergang und Wetterlage aus `{t:"front"}` |
| 2 Farbton für `edge` | die Rechnung aus `touch_satz()` auf mehrere Sets verallgemeinert |
| 2 Ruhemodus | Nacht-Uhr und Uhr-Widget |
| 2 Aufwachen | `devices.presence` (Loxone), UniFi als weitere Quelle |
| 2 Bento-Automatik | leere `cells` (Regel 5) |
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
