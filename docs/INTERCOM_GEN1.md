# Gegensprechen: Loxone Intercom Gen-1

Implementierungsstand auf `feature/intercom-gen1-talk`, ausgehend von
`main` bei `227c44206f5ba1e3555abbd08d5b4af60eed506d`. Der Branch wird nicht
nach `main` gemergt. Die Implementierung ist automatisiert prüfbar; eine
Freigabe für echte Hardware setzt die unten genannten Gerätetests voraus.

## Umfang und Voraussetzungen

Gegensprechen gibt es ausschließlich in der nativen LoxPanel-App für Android.
Unterstützt wird der Gen-1-Baustein „Door Controller“, Typ `Intercom`.
`deviceType` beschreibt die Türstationsvariante und ist keine zuverlässige
Generationskennung: eine echte Gen-1 kann `0` melden. `IntercomV2` (Gen-2)
bleibt ausgeschlossen.

Der konfigurierte Miniserver muss in `securedDetails.audioInfo` einen SIP-Host
liefern. LoxPanel verwendet dafür unverändert `App.intercom_sip()`; Host,
Benutzer und Passwort werden weder aus der Kameraadresse abgeleitet noch im
Frontend gespeichert. Fehlt der SIP-Zugang, meldet die App den Grund. Die
vorhandene OPTIONS-Prüfung unter Settings → SIP bleibt nutzbar.

App und Audiomodul müssen sich direkt über IPv4/UDP erreichen. Es gibt keinen
Registrar, REGISTER, STUN/ICE, NAT-Relay, SIP-Proxy, SRTP, TLS oder Gen-2-Audio.
Anrufziel ist die SIP-URI aus Host und Benutzer der gesicherten Details; ein
leerer Benutzer erlaubt den direkten anonymen Anruf. Es wird ausschließlich
G.711 PCMA oder PCMU mit 8 kHz mono angeboten, RTP/AVP mit Payload-Typ 8 bzw. 0.

## Aufbau

`bin/sip_call.py` führt INVITE, Digest-Authentifizierung, ACK, BYE und SDP aus.
URI-, Antwort- und Digest-Helfer stammen aus `sip_probe.py`. Ein INVITE wird
über UDP wiederholt; 401/407 und andere endgültige Antworten werden mit ACK
bestätigt. Wiederholte erfolgreiche Antworten erhalten erneut ACK. Stop
während des Aufbaus verwendet CANCEL; trifft gleichzeitig ein 200 ein, folgt
ACK und BYE. Ein BYE der Türstation beendet den lokalen Anruf ebenfalls.
Nicht unterstütztes SDP beendet einen bereits angenommenen Dialog mit BYE.

`IntercomTalk` besitzt genau eine Sitzung. Kurze Anrufaufgaben gehören nicht
zu den dauerhaften Aufgaben von `/api/health`. Ein Status-Poll dient als
Lebenszeichen: nach 15 Sekunden ohne Poll wird abgebrochen bzw. aufgelegt.
Die native Sitzung existiert schon vor dem HTTP-Start, damit ein schneller
Stop und verspätete Startantworten keinen neuen Anruf hinterlassen.

Android bindet zunächst seinen RTP-Port. Der Python-SIP-Socket bestimmt die
lokale IPv4-Adresse des Weges zur Türstation für das SDP. Android kodiert das
Mikrofon mit `AudioRecord` in G.711 und sendet 160 Samples je 20-ms-Paket.
Eingehendes RTP wird geprüft, dekodiert und über `AudioTrack` wiedergegeben.
Mikrofonrecht, Audiofokus, Kommunikationsmodus und Lautsprecherrouting werden
von der Activity verwaltet. Geräte-AEC und Rauschunterdrückung werden genutzt,
wenn Android sie anbietet. Bei Hintergrundwechsel, Seitenneuladung,
Renderer-Neuaufbau und Activity-Ende wird aufgelegt und Audio freigegeben.

Die App ruft lokal diese Routen auf:

| Route | Daten |
|---|---|
| `POST /api/intercom/talk/start` | `{session, uuid, rtpPort}`; liefert sofort den Startstatus |
| `GET /api/intercom/talk/status?session=…` | Zustand und bei Verbindung `{remoteHost, remotePort, codec, payloadType, sampleRate, ptime}` |
| `POST /api/intercom/talk/stop` | `{session}`; wiederholtes Stop ist erlaubt |

Die Routen verlangen Loopback und einen zufälligen Prozess-Token im Header
`X-LoxPanel-Intercom`, den `ServerService` direkt an den Python-Bootstrap gibt.
Der Token und SIP-Zugang werden nicht an JavaScript weitergegeben. Auf einem
normalen Server ohne nativen Bootstrap sind die Routen gesperrt.

Die WebView-Brücke bietet `startIntercom(uuid)` und `stopIntercom()` mit einem
Boolean für die Annahme des Auftrags; `intercomStatus()` liefert einen
JSON-String `{state, uuid, message}`. Zustände sind `idle`, `connecting`,
`connected`, `ending`, `error`. Die Visu zeigt Sprechen/Auflegen nur bei
vollständiger Brücke auf Detailseite und Kamera-Pane. Klingel-Popups führen
bereits zur Detailseite. Statusupdates ändern nur die Sprechbedienung;
Kamerastream, Türimpulse, Klingel-Abstellen und Klingelverlauf behalten ihre
vorhandenen Abläufe. Sprechen sendet insbesondere kein zusätzliches `answer`.

Android injiziert die öffentliche Fassade nur in das lokale Hauptdokument.
Die rohen nativen Gesprächsmethoden verlangen einen pro Seite erneuerten
Zugang aus einer privaten Closure; fremde eingebettete Webseiten bekommen
ihn nicht. Die späte Freigabe ergänzt die Bedienung ohne Kameraneuladung.

## Automatisierte Prüfungen

- `tests/test_sip_call.py`: echte lokale UDP-Transaktionen, Digest, ACK/BYE,
  Wiederholungen, Abbruchrennen und gültige/abgelehnte SDP-Antworten.
- `tests/test_intercom_talk.py`: Sitzungsbesitz, Start/Stop-Reihenfolge,
  Lebensfrist, verschlüsselte gesicherte Details aus dem Miniserver-Nachbau,
  native API und unveränderte Tür-/Klingelbefehle.
- `tests/browser/test_intercom_talk_browser.py`: echte Chromium-Visu mit
  nachgebildeter nativer Brücke; Browser/Fully/alte App/Gen-2 ohne Bedienung,
  Zustände, Auflegen und unveränderte Kamera-Elemente.
- Android-JUnit-Tests: unabhängige G.711-Referenzwerte, RTP-Paketstruktur und
  Abbruch einer Sitzung mit verspäteter Antwort. Der Android-Testworkflow
  führt `testDebugUnitTest` und `compileDebugKotlin` aus.

Die abschließenden lokalen Prüfergebnisse und etwaige Buildgrenzen stehen im
Abschnitt „Prüfergebnis“ am Ende dieses Dokuments. Ein JVM-/Browser-Test
ersetzt keinen Mikrofon- oder Türstationstest.

## Notwendige Hardwaretests und offene Punkte

1. **SIP-Zugang:** echte Gen-1 und Miniserverversion dokumentieren; AudioInfo
   unter Settings → SIP prüfen. Die früher getestete Anlage lieferte keinen
   SIP-Host. Dort zuerst die Konfiguration des Audiomoduls klären.
2. **Verbindung:** direkte SIP-URI, anonymer und gegebenenfalls authentifizierter
   INVITE; PCMA und PCMU je separat; SIP-Contact, SDP-Adresse und ausgehandelte
   RTP-Ports auf echter Firmware prüfen. Mit Paketmitschnitt bestätigen, dass
   SDP die Tablet-LAN-Adresse enthält und ACK/BYE die Türstation erreichen.
3. **Audio:** beide Richtungen gleichzeitig, Verständlichkeit, Lautstärke,
   Echo, Rückkopplung, AEC-Verfügbarkeit und Audiofokus auf den eingesetzten
   Tablets prüfen. 8-kHz-Aufnahme und Kommunikationslautsprecher können sich
   je nach Android-Gerät unterscheiden.
4. **Abbruch:** Auflegen während INVITE, unmittelbar nach 200, mehrfaches
   Tippen, Remote-BYE, Mikrofonrecht verweigert/erteilt, App im Hintergrund,
   Display aus, WebView-Neuladen, Renderer-Absturz und Prozessabbruch. Nach
   Stop muss das Mikrofon sofort frei sein; fehlt der native Status-Poll,
   endet auch SIP spätestens nach Lebensfrist und Signalisierungsfrist.
   Audioeinstellungen müssen zurückgesetzt sein. Ein rein visueller Kiosk-
   Schoner pausiert die Activity nicht und beendet derzeit keinen Anruf;
   dieses Verhalten am Wandpanel ausdrücklich prüfen.
5. **Bestehende Bedienung:** während des Gesprächs Kamerastream, Klingeln,
   Klingel abstellen, verpasste Klingeln und Türimpuls auf der echten Anlage
   prüfen; außerdem Browser und Fully ohne Sprechbuttons.
6. **Netz und Dauerlauf:** Paketverlust, schwankendes WLAN, Gegenstelle offline,
   SIP-Ablehnung und viele aufeinanderfolgende Gespräche. Die erste Version
   nutzt Android-Audiopuffer und verwirft doppelte/alte RTP-Pakete; ein eigener
   adaptiver Jitterbuffer und Paketverlustausgleich sind nicht implementiert.
   Audioqualität unter schlechten Netzbedingungen bleibt zu messen.

Nicht behauptet wird eine bereits erfolgte Hardwarefreigabe. Weitere SIP-
Funktionen und Gen-2 bleiben außerhalb dieses Branches.


## Prüfergebnis (05.10.2026)

- Python-Gesamtlauf: **735 bestanden**, 219 Browserfälle abgewählt.
  Darunter alle SIP-UDP-, SDP- und Sitzungs-/Miniserver-Integrationstests.
- Neue native Bedienung in Chromium: **12 bestanden**, einschließlich
  später Brückenfreigabe ohne Kameraneuladung. Zusätzlich **5 bestandene**
  bestehende Kiosk-/Präsenz-Brückentests nach Erweiterung ihrer Nachbauten.
- Android: **Kotlin-Kompilierung erfolgreich**, **48 JUnit-Tests bestanden**
  mit Gradle 8.7, Kotlin 1.9.24, JDK 17, SDK 34 und Python 3.11.
  Lokal `compileDebugKotlin` und `testDebugUnitTest`; nur der Asset-Kopiertask
  wurde für diesen Kompilierungs-/Testlauf ausgelassen.
- Python-Syntax, Ruff F/E9, Workflow-YAML, Manifest/Unraid-XML und
  `git diff --check` ohne Fehler.
- Vollständiger Browserlauf mit lokalem Chromium 151: **206 bestanden,
  12 fehlgeschlagen**. Alle 12 Layoutfehler wurden separat am unveränderten
  Ausgangsstand `main`/`227c442` reproduziert: drei 4-Zoll-/Kacheltests,
  drei Wetterhöhen-Tests und sechs Uhr-/Kachel-/Verlaufstests. Ihre Ursache
  bleibt außerhalb dieser Umsetzung offen; ein grüner Gesamtbrowserlauf
  wird deshalb nicht behauptet. Der zusätzliche späte Brückenfall wurde
  nach diesem Gesamtlauf ergänzt und im erfolgreichen 12-Fälle-Lauf geprüft.

Es war keine echte Intercom und kein Android-Gerät angeschlossen.
Mikrofon, Lautsprecher, Echo-Unterdrückung und Gen-1-Firmware-Kompatibilität
sind daher weiterhin gemäß Hardware-Prüfliste abzunehmen.
