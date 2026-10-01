# LoxPanel — Chaquopy-Machbarkeits-Spike (Android)

Beantwortet **eine** Frage: Läuft der LoxPanel-Server (Python) eingebettet in einer
Android-App? Konkret werden auf dem Gerät geprüft:

1. `cryptography` importieren **und** eine native AES-GCM-Operation ausführen
2. `aiohttp` importieren
3. `loxone-api` importieren
4. einen echten `aiohttp`-Server auf `127.0.0.1:8099` starten und lokal abfragen

Das Ergebnis erscheint als PASS/FAIL-Liste direkt auf dem App-Bildschirm.
Kein UI-Framework, kein WebView — nur der Tragfähigkeits-Test.

## Voraussetzungen (hast du durch thermobreeze schon)
- Android SDK: `C:\Users\Lenar\AppData\Local\Android\sdk`
- JDK 17 (kommt mit Android Studio / Flutter JBR)
- Ein **echtes Android-Tablet** (arm64) per USB, Entwickleroptionen + USB-Debugging an
  (der Emulator ginge auch, dann zählt der `x86_64`-ABI).

## Bauen & Starten — einfachster Weg: Android Studio
1. Android Studio → **File ▸ Open** → diesen Ordner (`loxpanel-android-spike`) wählen.
2. Beim ersten Sync bietet Studio an, den **Gradle-Wrapper** zu erzeugen → zulassen.
   (Diese Vorlage enthält absichtlich **keine** `gradle-wrapper.jar` — die ist binär.
   Alternativ auf der Kommandozeile einmalig: `gradle wrapper --gradle-version 8.7`.)
3. Tablet auswählen → **Run ▶**. Der erste Build lädt die Python-Wheels (dauert).
4. Auf dem Tablet erscheint die Ergebnisliste.

## Was das Ergebnis bedeutet
- **Alle vier OK** → Android-Variante ist grundsätzlich bestätigt; der Rest
  (WebView-Kiosk, Foreground-Service, Android-Display-Steuerung statt Agent) ist Fleißarbeit.
- **`cryptography` FAIL** → der erwartete Knackpunkt. Dann Optionen: andere
  Chaquopy-Version, Krypto-Nutzung im Server kapseln/ersetzen, oder Krypto-Feature
  (Audioserver-Login) auf Android optional machen.
- **`loxone-api` FAIL** → meist nur der Import-Name; im Test sind mehrere Namen
  hinterlegt. Zur Not das Paket weglassen — es ist reines Python auf aiohttp.

## Typische Stolpersteine (bewusst offen gelassen — an deiner Toolchain justieren)
- **Versionskonflikt beim Sync**: In `build.gradle.kts` (Root) die drei Plugin-
  Versionen an dein Android Studio anpassen — AGP (`com.android.application`),
  Kotlin, Chaquopy müssen zueinander passen. Aktuell: AGP 8.5.2 / Kotlin 1.9.24 /
  Chaquopy 16.0.0 / Gradle 8.7.
- **"buildPython" nicht gefunden** (Windows): Chaquopy braucht evtl. ein lokales
  Python 3.x auf dem PC (für reine sdists). Dann in `app/build.gradle.kts` im
  `chaquopy { defaultConfig { } }`-Block `buildPython("py", "-3.12")` (oder Pfad
  zur `python.exe`) setzen.
- **ABI**: Für ein ARM-Tablet reicht `arm64-v8a`; `x86_64` nur für Emulator.
  In `app/build.gradle.kts` unter `ndk.abiFilters` reduzieren = schnellerer Build.

## Wenn der Spike grün ist
Nächste Schritte für die echte App (separat, kein Teil dieses Spikes):
- WebView auf `http://127.0.0.1:8099/?panel=...&device=...`
- Server als **Foreground-Service** (dauerhafte Notification) statt in der Activity
- Display-Steuerung über Android-APIs (Brightness/WakeLock) statt des Linux-Agents
- LoxPanel-Code (`bin/`, `webfrontend/`, `config/`) als Python-Assets bündeln

## Schnittstelle zur Visu (`LoxKiosk`)
Die App hängt das Objekt `LoxKiosk` in die WebView. Die Visu erkennt es wie
`window.fully` von Fully Kiosk und meldet sich beim Server mit `kiosk=loxpanel`.
Unter *Displays* erscheint das Gerät dann als „LoxPanel-App“, mit „Display aus“
und „Display an“.

| Funktion | Wer ruft sie | Wirkung in der App |
|---|---|---|
| `setDisplayOff(sekunden)` | Visu beim Laden der Einstellungen (`dpmsOff`) | Leerlaufzeit bis zum Bildschirmschoner, `0` schaltet ihn ab |
| `turnScreenOn()` | Visu bei Klingel, Wecker, Notify, Goto und wenn der Server das Display einschaltet | Schoner weg, Leerlaufzeit beginnt neu |
| `turnScreenOff()` | Visu, wenn der Server das Display abschaltet (*Displays*, `/api/display`) | Schoner an |
| `isScreenOn()` | Visu vor `turnScreenOn()` | `true`, solange kein Schoner zu sehen ist |

Die drei letzten heißen wie bei Fully Kiosk, damit die Visu beide Apps gleich
behandelt.
