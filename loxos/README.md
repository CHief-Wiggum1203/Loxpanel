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
| macOS | `LoxOS-<Version>-mac.dmg` | Signiert und von Apple beglaubigt, wenn die Secrets für die Mac-Signatur im Repo stehen (unten): öffnen, nach „Programme“ ziehen, starten. Ohne sie baut der Workflow unsigniert; dann nach dem Kopieren einmal im Terminal `codesign --force --deep -s - /Applications/LoxOS.app` und `xattr -cr /Applications/LoxOS.app`. |
| Linux | `LoxOS-<Version>-x86_64.AppImage` | Ausführbar machen (`chmod +x`) und starten; Autostart richtet die Desktop-Umgebung ein. |

Beim ersten Start fragt LoxOS nach der Adresse von Loxpanel und dem Namen des
Geräts. Unter diesem Namen erscheint der Rechner in Loxpanel unter „Geräte“;
dort ordnest du ihm die Ansicht mit der Bento-Seite zu.

## Signierte Mac-Version

Mit einem Apple-Entwicklerkonto signiert der Workflow die Mac-Version mit
deiner „Developer ID“ und lässt sie von Apple beglaubigen (Notarisierung).
Dann startet LoxOS auf jedem Mac ohne Warnung von Gatekeeper. Dafür braucht
das Repo fünf Secrets. Die Werte gehören nur dorthin, nie in eine Datei des
Repos und nie in einen Chat.

1. **Zertifikat „Developer ID Application“** anlegen (nur der Kontoinhaber
   kann das): in Xcode unter Einstellungen → Accounts → „Manage
   Certificates…“ → „+“ → „Developer ID Application“, oder auf
   developer.apple.com unter „Certificates, IDs & Profiles“ mit einer
   Zertifikatsanfrage aus der Schlüsselbundverwaltung.
2. In der **Schlüsselbundverwaltung** unter „Meine Zertifikate“ das
   Zertifikat „Developer ID Application: <Name> (<Team-ID>)“ samt
   privatem Schlüssel als `.p12` exportieren und ein Kennwort vergeben.
3. Die `.p12` in Base64 umwandeln: `base64 -i Zertifikat.p12 | pbcopy`.
   Das ist das Secret `MAC_ZERTIFIKAT_P12`, das Kennwort aus Schritt 2 das
   Secret `MAC_ZERTIFIKAT_KENNWORT`.
4. **Schlüssel für die Notarisierung** in App Store Connect: „Benutzer und
   Zugriff“ → „Integrationen“ → „App Store Connect API“ → „Team-Schlüssel“
   (beim ersten Mal den Zugriff anfordern) → „+“, Zugriff „Developer“.
   Die Datei `AuthKey_<Schlüssel-ID>.p8` lässt sich nur einmal laden.
   Ihr ganzer Inhalt (mit den Zeilen `BEGIN` und `END`) ist das Secret
   `APPLE_API_KEY`, die Schlüssel-ID das Secret `APPLE_API_KEY_ID`, die
   „Issuer ID“ über der Liste das Secret `APPLE_API_ISSUER`.
5. Auf GitHub im Repo unter Settings → Secrets and variables → Actions je
   Wert „New repository secret“ mit genau diesen Namen anlegen.

Beim nächsten Tag `loxos-v…` (oder einem Lauf von Hand) baut der Workflow die
Mac-Version signiert. electron-builder signiert mit Hardened Runtime und den
Rechten aus `build/entitlements.mac.plist`: drei, die Electron braucht, und
das Mikrofon für das Gegensprechen. Der Text, mit dem macOS nach dem Mikrofon
fragt, steht in `package.json` (`NSMicrophoneUsageDescription`). Danach
schickt electron-builder die App zu Apple (`notarytool`) und heftet die
Beglaubigung an. Der Schritt „Signatur und Beglaubigung pruefen“ prüft das
Ergebnis mit `codesign`, `spctl` und `stapler`. Fehlt eines der vier
übrigen Secrets, bricht der Lauf ab, statt still unbeglaubigt zu bauen.

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
  Bildschirme wach halten, Beenden.

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
| `bildschirmWach` | verhindert im Widget-Modus, dass der Energiesparplan des PCs die Bildschirme abschaltet (auch den Hauptmonitor); Standard an, im Desktop-Modus ruht die Sperre |

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
