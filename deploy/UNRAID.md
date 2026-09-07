# LoxPanel auf Unraid

LoxPanel läuft auf Unraid als normaler Docker-Container. Ein LoxBerry wird dafür
nicht gebraucht: Was dort das Plugin-Widget übernimmt (Start/Stop, Update,
Sicherung), erledigt auf Unraid die Docker-Oberfläche bzw. das appdata-Verzeichnis.
Der Miniserver-Zugang wird über die Einstellungen-Seite des Containers oder über
Variablen im Template gesetzt.

## Voraussetzungen

- Unraid mit aktiviertem Docker-Dienst (*Settings → Docker*).
- Der Unraid-Server erreicht den Loxone Miniserver im Netz (Port 443 bei Gen2,
  Port 80 bei Gen1).
- Das Image `ghcr.io/chief-wiggum1203/loxpanel:latest`. Es wird vom GitHub-Workflow
  dieses Repos bei jedem Push auf `main` gebaut (multi-arch: amd64 / arm64 / armv7)
  und muss im GitHub-Package auf **public** stehen, damit Unraid es ohne Login zieht.

## Installation über das Template

1. **Docker**-Tab öffnen und ganz nach unten zu **Template repositories** scrollen.
2. Dort `https://github.com/CHief-Wiggum1203/Loxpanel` eintragen und **Save** klicken.
   Unraid liest daraus das Template [`unraid/loxpanel.xml`](../unraid/loxpanel.xml).
3. **Add Container** klicken und im Dropdown **Template** den Eintrag **LoxPanel** wählen.
4. Felder prüfen:

| Feld | Standard | Bedeutung |
|---|---|---|
| Web-Port | `8099` | Port für Visu, Konfigurator und Einstellungen (`/config`) |
| Konfiguration (appdata) | `/mnt/user/appdata/loxpanel/config` | persistente Konfiguration (`loxpanel.cfg`, `panels.json`, `theme.json`) |
| Miniserver-Host / -Benutzer / -Passwort | leer | optional; alternativ später unter `/config` → *Settings → Miniserver* eintragen |
| Miniserver-Port | `443` | Gen2 = 443, Gen1 = 80 (unter *Show more settings*) |
| Miniserver TLS prüfen | `false` | Gen2 nutzt ein selbstsigniertes Zertifikat, daher `false` |

5. **Apply**. Unraid zieht das Image und startet den Container.

## Manuell ohne Template

*Add Container* ohne Template-Auswahl, dann:

| Einstellung | Wert |
|---|---|
| Name | `LoxPanel` |
| Repository | `ghcr.io/chief-wiggum1203/loxpanel:latest` |
| Network Type | `bridge` |
| WebUI | `http://[IP]:[PORT:8099]/config` |
| Port | Container `8099` → Host `8099` (TCP) |
| Path | Container `/app/config` → Host `/mnt/user/appdata/loxpanel/config` |
| Variablen (optional) | `LOXPANEL_MS_HOST`, `LOXPANEL_MS_USER`, `LOXPANEL_MS_PASS`, `LOXPANEL_MS_PORT`, `LOXPANEL_MS_VERIFY_TLS` |

## Ersteinrichtung

1. Im Docker-Tab auf das LoxPanel-Icon klicken und **WebUI** wählen. Das öffnet
   `http://<unraid-ip>:8099/config`.
2. Miniserver-Zugang unter `http://<unraid-ip>:8099/config` im Reiter
   **Settings → Miniserver** eintragen und speichern. LoxPanel verbindet sich und liest die Struktur automatisch ein.
3. Panels unter `/config` anlegen und gestalten. Die Visu läuft dann unter
   `http://<unraid-ip>:8099/?panel=<id>`.

**Vorrang der Zugangsdaten:** Ein unter *Settings → Miniserver* gespeicherter Zugang (liegt in
`loxpanel.cfg` im appdata-Ordner) hat Vorrang vor den Template-Variablen. Die
Variablen sind dann sinnvoll, wenn der Zugang von Anfang an feststehen soll oder
der appdata-Ordner leer ist.

## Wandpanel mit Panel-Agent

Der Agent läuft auf dem Wandpanel, nicht auf Unraid. Das Installationsskript liefert
der LoxPanel-Container selbst aus. Per SSH auf dem Panel:

```bash
curl -fsSL -o install-agent.sh http://<unraid-ip>:8099/install-agent.sh
SERVER=<unraid-ip>:8099 bash install-agent.sh
```

Alles Weitere (Kiosk, Display-Abschaltung, Fernstart) steht in
[`DEPLOY.md`](DEPLOY.md). Als `SERVER` gilt überall die Unraid-IP mit dem gewählten
Host-Port.

## Updates

- **Docker**-Tab → **Check for Updates**. Zeigt LoxPanel *update ready*, auf
  **update** klicken. Unraid zieht das neue Image und startet den Container neu.
- Automatisch geht das mit dem Community-Applications-Plugin **Auto Update
  Applications**.
- Panels und Einstellungen bleiben erhalten, sie liegen im appdata-Ordner und nicht
  im Image.

## Sicherung

Die komplette Konfiguration liegt in `/mnt/user/appdata/loxpanel/config`:

| Datei | Inhalt |
|---|---|
| `loxpanel.cfg` | Miniserver-Zugang, Intercom-Zugänge, Audio-Einstellungen |
| `panels.json` | Panel-Profile, Kacheln, Layout |
| `theme.json` | globales Design (optional) |

- **Sichern:** den Ordner kopieren, oder das Community-Applications-Plugin
  **Appdata Backup** einsetzen, das alle appdata-Ordner regelmäßig sichert.
- **Wiederherstellen:** Container stoppen, die Dateien zurückkopieren, Container
  starten.

## Netzwerk und Zeitzone

- **bridge** mit Port-Mapping reicht. Eingehend wird nur der Web-Port gebraucht,
  ausgehend verbindet sich der Container per WebSocket mit dem Miniserver.
- Bekommt der Container eine eigene IP (Custom-Network wie `br0`), entfällt das
  Port-Mapping. Die Visu ist dann direkt unter `http://<container-ip>:8099` erreichbar.
- Liegt der Miniserver in einem anderen VLAN, muss der Unraid-Server ihn ausgehend
  erreichen dürfen.
- Die **Zeitzone** übergibt Unraid jedem Container automatisch als `TZ`-Variable
  (*Settings → Date and Time*). LoxPanel nutzt sie für Anzeigen wie „Heute/Morgen"
  beim Wecker.

## Unterschiede zum LoxBerry-Plugin

| LoxBerry-Plugin | Unraid |
|---|---|
| Widget: Starten / Stoppen / Neu starten | Docker-Tab, Klick auf das Container-Icon |
| Widget: „Jetzt updaten" | **Check for Updates** im Docker-Tab |
| Widget: Backup & Wiederherstellung | appdata-Ordner bzw. **Appdata Backup** |
| Widget: „Aus LoxBerry übernehmen" | Zugang unter `/config` (Settings) oder Template-Variablen |
| Statuslog im Widget | Docker-Tab → Container-Icon → **Logs** |

## Fehlersuche

- **Logs:** Docker-Tab → Container-Icon → **Logs**. Dort steht, ob die Struktur vom
  Miniserver geladen wurde und ob die WebSocket-Verbindung steht.
- **Keine Verbindung zum Miniserver:** im Log steht dann
  `Miniserver nicht verbunden (...) — neuer Versuch in 10s`. Zugangsdaten unter
  `/config` (Settings → Miniserver) prüfen, Port (443 Gen2 / 80 Gen1) und bei Gen2 *TLS prüfen* auf
  `false` lassen. LoxPanel versucht es alle 10 Sekunden erneut, ein Neustart ist
  nicht nötig.
- **Port 8099 belegt:** im Template einen anderen Host-Port wählen (z. B. `8100`).
  Panels und Agent dann mit `SERVER=<unraid-ip>:8100` ansprechen.
- **Image lässt sich nicht ziehen:** das GitHub-Package
  `chief-wiggum1203/loxpanel` muss auf *public* stehen und der Workflow
  *Docker Image* muss mindestens einmal auf `main` gelaufen sein.
