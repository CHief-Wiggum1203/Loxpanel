# LoxOS – Hülle für Streifen-Displays

LoxOS zeigt die Visu von Loxpanel auf einem flachen Streifen-Display neben dem
Monitor (etwa 2560 × 720, ein Klon des Corsair Xeneon Edge). Ziel und Roadmap
stehen in [`docs/VISION.md`](../docs/VISION.md). Fork-eigen, nicht für Upstream.

## Installieren

Die Installer baut der Workflow `LoxOS` (`.github/workflows/loxos.yml`) auf
echten Windows-, macOS- und Linux-Rechnern. Sie hängen am Release `loxos-v…`
(oder als Artefakt am Lauf, wenn der Workflow von Hand gestartet wurde):

| System | Datei | Hinweis |
|---|---|---|
| Windows | `LoxOS-Setup-<Version>.exe` | Installiert für den angemeldeten Benutzer, ohne Adminrechte. Das Programm ist nicht signiert: SmartScreen fragt beim ersten Start, „Weitere Informationen“ → „Trotzdem ausführen“. |
| macOS | `LoxOS-<Version>-mac.dmg` | Nicht signiert. Nach dem Kopieren nach „Programme“ einmal im Terminal: `codesign --force --deep -s - /Applications/LoxOS.app` und `xattr -cr /Applications/LoxOS.app`, dann starten. |
| Linux | `LoxOS-<Version>-x86_64.AppImage` | Ausführbar machen (`chmod +x`) und starten; Autostart richtet die Desktop-Umgebung ein. |

Beim ersten Start fragt LoxOS nach der Adresse von Loxpanel und dem Namen des
Geräts. Unter diesem Namen erscheint der Rechner in Loxpanel unter „Geräte“;
dort ordnest du ihm die Ansicht mit der Bento-Seite zu.

## Aus dem Quelltext starten

Voraussetzung: Node.js 20 oder neuer.

```bash
cd loxos
npm ci          # Electron und Pakete genau aus package-lock.json (mit Prüfsummen)
npm start
```

## Neues Release

1. In `loxos/package.json` die `version` anheben (etwa `1.0.1`).
2. Committen, dann den Tag setzen und pushen:
   `git tag loxos-v1.0.1 && git push origin loxos-v1.0.1`.
3. Der Workflow prüft, dass Tag und Version zusammenpassen, lässt die Tests
   laufen, baut die drei Installer und hängt sie an den Release.

Selbst bauen geht mit `npm run dist` – auf jedem System nur dessen eigener
Installer (Windows-Programme lassen sich unter Linux nicht sauber bauen).

## Bedienung

- **Widget-Modus:** die Visu rahmenlos im Vollbild auf dem Streifen.
- **Desktop-Modus:** das Fenster ist weg, der Streifen ein normaler Bildschirm.
- Umschalten mit dem Tastenkürzel (Standard `Strg+Alt+L`, am Mac `Cmd+Alt+L`),
  mit einem Klick auf das Symbol im Tray oder über dessen Menü.
- Im Tray außerdem: Neu laden, Konfigurator öffnen, Einstellungen, Autostart,
  Beenden.

## Einstellungen

`loxos.json` im Benutzerordner der App (Windows `%APPDATA%\loxos`, macOS
`~/Library/Application Support/loxos`, Linux `~/.config/loxos`); die
Einrichtung im Tray schreibt sie.

| Feld | Bedeutung |
|---|---|
| `server` | Adresse von Loxpanel, nur http/https, ohne Zugangsdaten |
| `geraet` | Name, unter dem sich LoxOS meldet (`?device=`), Standard: Rechnername |
| `monitor` | `"auto"` (der Streifen: breitestes Seitenverhältnis ab 2,5) oder `{"breite": 2560, "hoehe": 720}` bzw. `{"id": …}` |
| `modus` | Start im `"widget"`- oder `"desktop"`-Modus |
| `kuerzelModus` | Tastenkürzel zum Umschalten (Electron-Schreibweise) |
| `autostart` | mit der Anmeldung starten (Windows, macOS) |

## Sicherheit

Das Visu-Fenster läuft isoliert, im Sandbox-Prozess und ohne Node. Es
navigiert nur innerhalb von Loxpanel; Links nach draußen öffnet der Browser
des Systems. Das Mikrofon (Gegensprechen an der Türstation) bekommt nur
Loxpanel.

## Tests

```bash
npm test                                   # reine Logik (Node)
cd .. && python -m pytest tests/test_loxos_huelle.py
```

Der Python-Test prüft außerdem die festgenagelten Versionen, die
Build-Konfiguration und den Workflow und startet die echte Hülle unter Xvfb –
aus dem Quelltext, sobald `npm ci` gelaufen ist, und gepackt nach `npm run dist`.
