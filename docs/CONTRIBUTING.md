# Mitentwickeln & den Fork synchron halten

Dieser Fork (`CHief-Wiggum1203/Loxpanel`) wird eigenständig weiterentwickelt und
auf Unraid betrieben, bleibt aber eng an das Original
(`Lenardo1/Loxpanel`, hier `upstream`) angelehnt. Diese Datei beschreibt, wie
Entwicklung und Abgleich praktisch ablaufen. Kurzfassung der Git-Konventionen
steht in [`CLAUDE.md`](../CLAUDE.md), Architektur in
[`ARCHITEKTUR.md`](ARCHITEKTUR.md).

## Mentalmodell: „Fork = Upstream + dünne Identitätsschicht"

Der Fork bleibt genau dann leicht synchron, wenn möglichst wenig ihn vom
Upstream unterscheidet:

> So viel wie möglich gehört nach Upstream. Im Fork bleibt nur, was wirklich nur
> diese Installation betrifft.

Je dünner die Fork-eigene Schicht, desto reibungsloser jeder Abgleich. Neue
Bausteine, Bugfixes und allgemeine Verbesserungen fließen daher nach Upstream –
nicht nur in den Fork. Wer allgemeine Arbeit nur im Fork ablegt, baut sich bei
jedem Upstream-Update dieselben Konflikte neu.

## Was gehört wohin?

| Nach Upstream (`Lenardo1/Loxpanel`) | Nur in den Fork |
|---|---|
| Neue Bausteintypen, Steuer-Logik | Image-Name `ghcr.io/chief-wiggum1203/loxpanel` (klein) |
| Front/Screensaver, Audio, Bugfixes | Repo-/Archiv-Links, `ARCHIVEURL` in `loxberry-plugin/release.cfg` |
| Allgemeine Doku (`ARCHITEKTUR.md`, `TODO.md`) | `plugin.cfg` NAME/FOLDER/AUTHOR |
| Alles, wovon andere Nutzer profitieren | `unraid/`-Template + Unraid-Doku, diese `CONTRIBUTING.md`, `CLAUDE.md` |

## Voraussetzung: upstream-Remote

Einmalig prüfen/anlegen:

```bash
git remote -v                       # ist 'upstream' schon da?
git remote add upstream https://github.com/Lenardo1/Loxpanel   # falls nicht
```

## Ablauf A – Ein Feature entwickeln (→ Upstream)

Für alles Allgemeine. **Immer von `upstream/main` aus starten**, nicht vom
Fork-`main` – dann ist der Branch sauber gegen Upstream, ohne Identitäts-Ballast.

```bash
git fetch upstream
git checkout -b feature/mein-baustein upstream/main
# ... entwickeln, committen, Rauchtest (siehe unten) ...
git push origin feature/mein-baustein
```

Dann eine Pull Request **gegen `Lenardo1/Loxpanel:main`** öffnen (Basis-Repo =
Lenardo1, Compare = dieser Branch). Das funktioniert unabhängig von
Schreibrechten – der klassische Fork-→-Upstream-Weg. Mit Schreibrechten kann der
Branch auch direkt nach `upstream` gepusht werden; nötig ist das nicht.

Ist die PR bei Upstream gemergt → **Ablauf C** holt sie in den Fork zurück.

## Ablauf B – Etwas rein Fork-eigenes (Identität / Unraid)

Das, was nicht nach Upstream soll. Normal im Fork, Squash/Rebase ist hier ok
(diese Commits sieht Upstream nie). Klein halten und auf die Identitäts-/
Deployment-Dateien beschränken, damit die Sync-Konflikte berechenbar bleiben.

```bash
git checkout -b fix/unraid-xyz main
# ... ändern ...
git push -u origin fix/unraid-xyz     # PR gegen den Fork-main
```

## Ablauf C – Den Fork synchron halten (das „gleich halten")

Immer wenn Upstream etwas Neues released. Als Repo-Owner ist der einfachste Weg:
**lokal mergen und direkt auf `main` pushen**. Das umgeht die „nur Squash/
Rebase"-Einstellung und löst den `:latest`-Build automatisch aus (weil der Push
mit den eigenen Zugangsdaten erfolgt, nicht über einen Bot-Token).

```bash
# 1. Upstream-Stand holen
git fetch upstream

# 2. Auf aktuellen Fork-main
git checkout main && git pull origin main

# 3. Upstream als ECHTEN Merge-Commit reinziehen (NICHT squashen!)
git merge upstream/main
#    Konflikte fast nur in den Identitäts-Dateien (release.cfg ARCHIVEURL,
#    plugin.cfg VERSION, Image-Name): Fork-Identität behalten, Upstream-Code
#    und -Version übernehmen.

# 4. Rauchtest (siehe unten)

# 5. Direkt pushen -> :latest wird automatisch neu gebaut
git push origin main
```

Weil es ein **echter Merge-Commit** ist, kennt `main` danach die neuen
Upstream-Commits als Vorfahren → beim nächsten Sync keine Wiederholungskonflikte.
Alternativ über eine PR: dann kurz „Allow merge commits" aktivieren und mit
„Create a merge commit" mergen – **niemals** squashen/rebasen, sonst geht die
Upstream-Historie verloren.

## Sync-Checkliste (vor und nach jedem Upstream-Abgleich)

Der Fork soll strukturell nur Identität/Deployment enthalten (siehe
Mentalmodell) — dann kann ein Sync keinen Fix „verschlucken". Diese Liste
sichert das ab. Sie entstand aus einem realen Fehler: Beim 0.4.0-Sync wurde
`bin/webvisu.py` komplett von Upstream übernommen und dabei eine Fork-eigene
Audio-Weiche überschrieben, die nur im Fork lag → die Bedienung eines
gekoppelten Audioservers war tot. **Merke:** Ein Fork-Fix an einer Datei, die
Upstream ebenfalls ändert, geht verloren, sobald man Upstream übernimmt.

**1. Vor dem Sync — Divergenz prüfen:**

```bash
git fetch upstream
git log --oneline upstream/main..main    # Fork-Commits, die Upstream NICHT hat
```

Jeder gelistete Commit ist entweder (a) Identität/Deployment (ok, bleibt im
Fork) oder (b) ein echter Code-Fix / ein Feature. **Fall (b) gehört zuerst nach
Upstream** (Ablauf A) — sonst geht er beim Übernehmen verloren. Idealzustand:
die Liste enthält nur noch (a).

**2. Beim Auflösen von Konflikten:**

Nie `git checkout --theirs <datei>` auf eine Datei mit Fork-eigener Logik, ohne
diese Logik vorher zu sichern: erst `git diff main upstream/main -- <datei>`
ansehen, Fork-Änderungen erkennen und nach dem Übernehmen wieder einspielen
(besser: die Änderung vorher upstream einreichen, dann ist sie in beiden).

**3. Nach dem Sync — Funktionstest der kritischen Pfade** (nicht nur der
`py_compile`-Rauchtest), bevor `:latest` gebaut/deployt wird:

- Musik: play/pause + Lautstärke an einer `AudioZone`/`AudioZoneV2`
- PIN-Tür, Intercom-Bild, eine Jalousie / ein Licht schalten
- Front/Screensaver lädt (Kalender/Wetter)

**4. Fork-eigene Patches (Stand pflegen):**

Falls etwas unvermeidbar nur im Fork liegt, hier eintragen, damit ein Sync es
nicht unbemerkt entfernt:

- Paired-Audio-Weiche in `bin/webvisu.py` (`App.command()`): leitet Transport
  bei gekoppeltem Audioserver über den Miniserver. Liegt vorerst nur im Fork;
  die identische Änderung ist als Upstream-PR eingereicht. Sobald Lenardo sie
  merged, ist es kein Fork-eigener Patch mehr und der nächste Sync übernimmt sie.

## Drei Fallstricke

1. **Merge-Commit-Regel:** Upstream-Syncs nie squashen/rebasen. Lokal mergen +
   `git push origin main` ist der sauberste Weg.
2. **`:latest`-Build:** Ein Push auf `main` mit eigenen Zugangsdaten baut das
   Image automatisch neu. Merges über einen GitHub-Bot-Token lösen den
   `push`-Trigger **nicht** aus – dann den Build manuell starten
   (Actions → „Docker Image" → „Run workflow").
3. **Identität schützen:** Nach jedem Sync prüfen, dass
   `ghcr.io/chief-wiggum1203/loxpanel` (klein), `ARCHIVEURL` auf den Fork und
   `plugin.cfg` NAME/FOLDER/AUTHOR unverändert sind.

## Prüfen vor jedem Push

Die GitHub-Action „Tests" (`.github/workflows/tests.yml`) läuft auf jedem PR und
jedem Push auf `main`: Syntax, Lint (Fehlerregeln), pytest mit Miniserver-Nachbau
und Rauchtest, Visu-/Konfigurator-Tests in Chromium und für PRs ein Probe-Build
des Images. Ein PR wird erst gemergt, wenn sie grün ist. Lokal dasselbe
(Einzelheiten in `CLAUDE.md`):

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/ruff check --select F,E9 bin agent tests
.venv/bin/pytest
```

Die Tests ersetzen nicht den Funktionstest an der echten Anlage nach einem
Upstream-Sync (Abschnitt oben): sie kennen nur den Nachbau.
