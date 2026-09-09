# LoxPanel – Hinweise für die Entwicklung

Web-Touch-Visu für den Loxone Miniserver. Fork von `Lenardo1/Loxpanel`, hier
eigenständig weiterentwickelt und auf Unraid betrieben. Ausführliche Analyse in
[`docs/ARCHITEKTUR.md`](docs/ARCHITEKTUR.md), dort stehen Datenfluss, Routen,
Konfigurationsformate, Erweiterungs-Rezepte und bekannte Schwachstellen. Die
priorisierte Arbeitsliste steht in [`docs/TODO.md`](docs/TODO.md).

## Aufbau in einem Satz

`bin/webvisu.py` (aiohttp) verbindet sich per WebSocket mit dem Miniserver, rendert
alle Ansichten serverseitig als JSON und schickt sie per WebSocket an
`webfrontend/html/panel.html`, das nur noch anzeigt. Konfigurator und Einstellungen
liegen seit Upstream 0.3.2 gemeinsam in `config.html` (Rubriken „Panel
Configuration" und „Settings"), `settings.html` leitet nur noch weiter; beide
sprechen `/api/*`.

## Wichtige Dateien

| Datei | Inhalt |
|---|---|
| `bin/webvisu.py` | gesamter Server, 3.000 Zeilen, Routen in `main()` am Ende |
| `bin/loxone_ws.py` | Loxone-WebSocket und Binärparser |
| `bin/audioserver.py`, `bin/audioserver_events.py`, `bin/audioserver_auth.py` | Audioserver-Backends: Gen1/MS4H, Gen2-Events (Port 7091) und die App-Anmeldung am gekoppelten Audioserver (RSA/AES, braucht `cryptography`) |
| `webfrontend/html/*.html`, `i18n.js` | Frontend, Vanilla JS, kein Build |
| `agent/loxpanel-agent.py` | Panel-Agent für Wandpanels; Kopie liegt als Heredoc in `deploy/install-agent.sh` |
| `config/*.example` | Vorlagen; echte Dateien liegen im Volume `/app/config` |
| `unraid/loxpanel.xml`, `deploy/UNRAID.md` | Unraid-Betrieb |
| `loxberry-plugin/` | LoxBerry-Wrapper, nur für Releases relevant |

## Lokal starten

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
LOXPANEL_MS_HOST=<ip> LOXPANEL_MS_USER=<user> LOXPANEL_MS_PASS=<pass> \
  .venv/bin/python bin/webvisu.py          # http://localhost:8099
```

Ohne Miniserver startet der Server trotzdem und versucht alle 10 s die
Verbindung. `/config` und `/api/settings` sind dann erreichbar, das
reicht als Rauchtest. Docker: `docker compose up -d --build`.

## Prüfen vor einem Push

Es gibt keine automatisierten Tests. Mindestens:

```bash
python3 -m py_compile bin/webvisu.py bin/loxone_ws.py agent/loxpanel-agent.py
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/docker-image.yml'))"
python3 -c "import xml.dom.minidom as m; m.parse('unraid/loxpanel.xml')"
```

Dazu den Server starten und `/api/settings` sowie `/config` abrufen.

## Konventionen und Stolperfallen

- Oberfläche und Kommentare sind deutsch. Admin-Texte laufen über `i18n.js`
  (Schlüssel = deutscher Text), Panel-Texte stehen hart im Server.
- Neue Panel-Optionen müssen in `_sanitize_panels()` freigeschaltet werden, sonst
  verwirft der Server sie beim Speichern still.
- Neue Bausteintypen kommen in die beiden Ketten `_control_item()` und
  `_view_control_inner()`, nicht in `adapters.py`. Reihenfolge der Zweige ist
  relevant.
- `loxpanel.cfg` aus `/config` (Settings → Miniserver) hat Vorrang vor
  `LOXPANEL_MS_*`-Variablen.
- Beim Ändern des Agenten beide Stellen anfassen: `agent/loxpanel-agent.py` und
  den Heredoc in `deploy/install-agent.sh`.
- Keine Authentifizierung auf den Routen. Nichts bauen, was das Netz nach außen
  öffnet, ohne das vorher zu lösen.
- Image-Name `ghcr.io/chief-wiggum1203/loxpanel` in Kleinbuchstaben. Ein Push auf
  `main` baut `:latest` neu.
- Root-`plugin.cfg`, `daemon/`, `postinstall.sh`, `apt`,
  `webfrontend/htmlauth/index.php`, `config/visu.*` sind Altlasten ohne Funktion.

## Git

Entwicklung auf Feature-Branches, PR gegen `main` dieses Forks (nicht gegen das
Original). Das Repo erlaubt nur Squash oder Rebase, keine Merge-Commits.
Upstream-Updates: `git remote add upstream https://github.com/Lenardo1/Loxpanel`,
dann `git fetch upstream && git merge upstream/main`. Upstream-Merges als echten
Merge-Commit nach `main` bringen (PR mit „Create a merge commit", nicht
squashen), sonst kennt der Fork die Upstream-Commits nicht und dieselben
Konflikte kommen beim nächsten Release wieder.
