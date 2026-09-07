# LoxPanel auf Android-Panels und Tablets (ohne Agent)

Der Panel-Agent läuft nur auf Linux. Auf Android übernimmt eine Kiosk-App seine
Aufgaben, und die Visu selbst steuert das Display. Damit eignen sich
Android-Wandpanels, Tablets in einer Wandhalterung und das SONOFF NSPanel Pro
als Anzeigegeräte.

## Was ohne Agent funktioniert

| Funktion | Android mit Kiosk-App | Linux mit Agent |
|---|---|---|
| Visu, Kacheln, Detailseiten, PIN, Weckton | ja | ja |
| Betriebsmodus-Umschaltung, Reload, Goto, Notify | ja, per WebSocket-Push | ja |
| Auto-Neustart nach `reloadHours` | ja, die Seite lädt sich selbst neu | ja, Chromium-Neustart |
| Display aus nach `dpmsOff`, Wecken bei Klingel / Wecker / Notify / Goto | ja, mit Fully Kiosk Browser (JavaScript-Schnittstelle) | ja, per DPMS und Backlight |
| Anzeige in *Einstellungen → Panels* mit Name, Typ, Online-Status und Ansicht | ja | ja |
| Ansicht wechseln und neu laden aus den Einstellungen | ja, per WebSocket-Push | ja |
| Display aus/an aus den Einstellungen oder per HTTP (`/api/display`) | ja, mit Fully Kiosk | nein, der Agent regelt das selbst |
| Fernstart / Stopp des Kiosks aus den Einstellungen | nein, das macht die Kiosk-App | ja |
| Installationsskript | nein, Kiosk-App von Hand einrichten | ja |

Die Display-Steuerung aus der Seite heraus setzt eine Kiosk-App voraus, die eine
JavaScript-Schnittstelle in die Seite einblendet. Derzeit wird **Fully Kiosk
Browser** erkannt (`window.fully`). In einem normalen Browser passiert nichts,
dort bleibt es beim Screensaver mit Uhr.

## Fully Kiosk Browser einrichten

Fully Kiosk Browser gibt es im Play Store und als APK vom Hersteller. Die
Display-Steuerung braucht die kostenpflichtige PLUS-Lizenz (einmalig pro Gerät),
ohne sie läuft die Visu trotzdem, nur ohne Abschaltung durch die Seite.

1. **Start-URL** setzen:
   `http://<server-ip>:8099/?panel=<profil-id>&device=<gerätename>`
   Der Gerätename ist frei wählbar und erscheint unter *Einstellungen → Panels*.
   Ohne `panel=` startet das Profil `default`.
2. **JavaScript-Schnittstelle aktivieren:** *Advanced Web Settings → Enable
   JavaScript Interface (PLUS)*. Ohne diesen Schalter gibt es kein
   `window.fully`, und die Seite kann das Display nicht schalten.
3. **Eigene Bildschirm-Timer von Fully abschalten**, damit sich beide nicht in
   die Quere kommen: *Device Management → Screen Off Timer* auf 0, *Keep Screen
   On* einschalten. Die Abschaltzeit kommt aus dem Panel-Profil
   (*Konfigurator → Darstellung → Display aus nach*).
4. **Aufwachen durch Berühren:** In Fully unter *Device Management* den Modus
   wählen, bei dem ein Tippen den Bildschirm wieder einschaltet (bei vielen
   Geräten die weiche Abschaltung, nicht *Real Screen Off*). Klingel, Wecker,
   Notify und Goto schalten das Display zusätzlich aus der Seite heraus ein.
5. **Autostart:** *Device Management → Launch on Boot*.
6. **Ton:** *Web Content Settings → Autoplay Videos/Audio* erlauben, sonst
   bleibt der Weckton stumm.
7. **Kiosk-Modus** mit PIN sperren, damit niemand die App verlässt.

Die Bezeichnungen der Einstellungen können je nach Fully-Version leicht
abweichen.

## Gerät benennen und steuern

Ein Gerät erscheint unter *Einstellungen → Panels*, sobald es die Visu mit
`?device=<name>` öffnet. Fehlt die Kennung in der URL, steht das Gerät dort
unter „Ohne Kennung" mit seiner IP. Dort einen Namen eintragen und „Namen
vergeben" klicken: Die Visu merkt sich den Namen im Browser und verbindet sich
neu, ab dann ist das Gerät dauerhaft gelistet und per Betriebsmodus schaltbar.
Der Name bleibt auch ohne `?device=` in der URL erhalten, solange die
Browserdaten der Kiosk-App nicht gelöscht werden.

Je Gerät gibt es in der Liste: Ansicht wechseln (Profil wählen, Browser lädt
sich neu), Neu laden, und bei Fully Kiosk „Display aus" / „Display an". Das
Display lässt sich auch aus Loxone oder einem Skript schalten:

```
GET http://<server-ip>:8099/api/display?on=0&device=<name>   # aus
GET http://<server-ip>:8099/api/display?on=1&device=<name>   # an
GET http://<server-ip>:8099/api/display?on=0                 # alle Panels
```

`device=` oder `panel=` grenzen ein, ohne Filter sind alle offenen Visus
gemeint. Die Antwort nennt, wie viele Verbindungen erreicht wurden.

## WallPanel

WallPanel ist quelloffen, kostenlos und auf F-Droid verfügbar. Es zeigt die Visu
wie jeder Browser an, hat aber keine JavaScript-Schnittstelle in der Seite. Die
Display-Abschaltung aus der Seite heraus funktioniert damit nicht. Vorgesehen
ist dafür ein serverseitiger Treiber über die HTTP-Schnittstelle von WallPanel
(siehe `docs/TODO.md`, Schritt 3 des Umbaus).

## Geräte

- **Android-Wandpanels** (4 Zoll, 480×480, PoE, Unterputz) von deutschen
  Händlern: Fully Kiosk installieren, fertig. Das ist das Format, für das die
  Visu entworfen wurde.
- **Tablets** in einer Wandhalterung: größer, günstig, überall erhältlich. Das
  4×3-Kachel-Layout und *Bildschirm füllen* im Panel-Profil nutzen den Platz.
- **SONOFF NSPanel Pro:** Android, unterstützt F-Droid ab Firmware 4.0. Für
  Fully Kiosk ist meist der Entwicklermodus und ADB nötig, was die Garantie
  berührt. Zigbee, Matter und Relais des Geräts bleiben mit Loxone ungenutzt.

## Testen ohne Kauf

Jedes vorhandene Android-Handy oder -Tablet mit Fully Kiosk reicht, um den
Ablauf zu prüfen: Start-URL eintragen, JavaScript-Schnittstelle einschalten,
im Konfigurator *Display aus nach* auf 30 Sekunden setzen. Nach 30 Sekunden
ohne Berührung muss der Bildschirm ausgehen; ein `GET
http://<server-ip>:8099/api/notify?device=<gerätename>&text=Hallo` muss ihn
wieder einschalten.
