#!/bin/bash
# LoxPanel Docker-Steuerung.  Nutzung: loxpanel-ctl.sh start|stop|restart|check|backup|restore <datei>
#   start   pullt das aktuelle Image und startet den Container
#   stop    stoppt den Container (merkt sich das -> check startet ihn NICHT neu)
#   restart stop + start  (zieht dabei das neueste Image = manuelles Update)
#   check   startet den Container, falls er (unerwartet) nicht laeuft
#           (fuer Boot-daemon und 5-Minuten-Cron; ein bewusst gestopptes
#            Panel wird NICHT wieder gestartet)
#   backup  sichert die Konfiguration (Panels/Theme/Miniserver) als tar.gz
#   restore <datei>  spielt ein Backup zurueck (sichert vorher den Ist-Stand)
# REPLACELBPCONFIGDIR / REPLACELBPDATADIR werden beim Install durch echte Pfade ersetzt.
# LOXPANEL_CTL_CONFIGDIR / LOXPANEL_CTL_DATADIR setzen nur die Tests
# (tests/test_loxberry_ctl.py), im Betrieb gelten die Pfade der Installation.

CONFIGDIR="${LOXPANEL_CTL_CONFIGDIR:-REPLACELBPCONFIGDIR}"
COMPOSE="$CONFIGDIR/docker-compose.yml"
STOPPED="$CONFIGDIR/loxpanel_stopped.cfg"
# Konfig-Daten liegen im gemounteten Volume (panels.json, theme.json,
# loxpanel.cfg) und gehoeren root (der Container schreibt als root). Backup/
# Restore laufen deshalb als root IM Container (sonst darf der Widget-Benutzer
# loxberry die root-Dateien nicht ueberschreiben -> "tar: Cannot open: File
# exists"). Sicherungen liegen in data/backups und ueberleben Plugin-Updates
# (pre-/postroot.sh sichern die Konfiguration ueber das Update hinweg).
DATADIR="${LOXPANEL_CTL_DATADIR:-REPLACELBPDATADIR}"
CONFIGDATA="$DATADIR/config"
BACKUPDIR="$DATADIR/backups"
KEEP=20                 # so viele Backups behalten, aeltere werden entfernt
# Dateien, die LoxPanel in config/ schreibt (CFG_FILE, PANELS_FILE, THEME_FILE
# in bin/webvisu.py). Ein Backup ohne eine davon ist keine LoxPanel-Konfiguration.
KONFIG_DATEIEN="loxpanel.cfg panels.json theme.json"
NICHTS=3                # Status von _sichern: config/ fehlt oder ist leer
# backup und restore nie gleichzeitig (zweites Fenster, Doppelklick im Widget)
SPERRE="$DATADIR/.loxpanel-ctl.lock"

# Image aus der Compose-Datei lesen (Fallback fest).
_img() {
	local i
	i=$(sed -n 's/^[[:space:]]*image:[[:space:]]*//p' "$COMPOSE" | head -1)
	[ -n "$i" ] && echo "$i" || echo "ghcr.io/chief-wiggum1203/loxpanel:latest"
}

# Einen sh-Befehl als root im Container ausfuehren. $DATADIR wird nach /data
# gemountet -> config=/data/config, backups=/data/backups. Weitere Argumente
# stehen im Befehl als $1, $2 ... (Dateinamen nie in den Befehlstext).
_indocker() {
	local cmd=$1; shift
	sudo docker run --rm -v "$DATADIR":/data "$(_img)" sh -c "$cmd" sh "$@"
}

running() {
	[ -n "$(sudo docker ps --filter 'name=^/loxpanel$' --filter status=running -q 2>/dev/null)" ]
}

# Sperre fuer backup/restore: ein zweiter Lauf bricht sofort ab, statt auf
# halbe Zwischenstaende des ersten zu treffen. Danach Reste abgebrochener Laeufe
# (Stromausfall, kill) wegraeumen - unter der Sperre laeuft sonst keiner.
_sperren() {
	local reste
	exec 9>"$SPERRE" && flock -n 9 || {
		echo "Es läuft schon eine Sicherung oder Wiederherstellung – bitte warten und erneut versuchen."; exit 1; }
	shopt -s nullglob
	reste=("$DATADIR"/.restore.* "$BACKUPDIR"/*.part)
	shopt -u nullglob
	[ ${#reste[@]} -eq 0 ] && return
	echo "Räume Reste eines abgebrochenen Laufs weg: ${reste[*]##*/}"
	_indocker 'cd /data && rm -rf -- "$@"' "${reste[@]#"$DATADIR"/}"
}

# Config-Ordner als backups/$1 sichern: erst unter $1.part schreiben, ganz
# zuruecklesen (tar -tzf prueft dabei die gzip-Pruefsumme), auf die Platte
# bringen und erst dann umbenennen. Ein halbes Archiv (Datentraeger voll,
# Abbruch) liegt so nie unter einem Namen, den das Widget anbietet; ein
# vorhandenes Archiv wird nie ersetzt. Status 0, $NICHTS oder Fehler.
_sichern() {
	_indocker 'cd /data/config 2>/dev/null && [ -n "$(ls -A)" ] || exit "$2"
z=/data/backups/$1
[ ! -e "$z" ] || { echo "$1 gibt es schon." >&2; exit 1; }
tar -czf "$z.part" . && tar -tzf "$z.part" >/dev/null && sync && mv "$z.part" "$z" && exit 0
rm -f "$z.part"; exit 1' "$1" "$NICHTS"
}

# Freier Archivname loxpanel-config-<Zeit>$1.tar.gz; in derselben Sekunde mit
# laufender Nummer, ein vorhandenes Archiv wird nie ersetzt (unter der Sperre
# legt sonst niemand eins an).
_freier_name() {
	local ts f n=1
	ts=$(date +%Y%m%d-%H%M%S)
	f="loxpanel-config-$ts$1.tar.gz"
	while [ -e "$BACKUPDIR/$f" ]; do n=$((n+1)); f="loxpanel-config-$ts-$n$1.tar.gz"; done
	echo "$f"
}

# Zwischenordner von restore loeschen (als root, der Inhalt gehoert root).
_wegraeumen() {
	_indocker 'rm -rf -- "/data/$1"' "$1"
}

# Den fuer restore angehaltenen Container wieder starten (ohne pull).
_wieder_starten() {
	[ "$1" = 1 ] || { echo "Panel ist gestoppt – die Konfiguration gilt beim nächsten Start."; return; }
	if sudo docker start loxpanel >/dev/null; then echo "Panel neu gestartet."
	else echo "Panel ließ sich nicht starten – die 5-Minuten-Prüfung versucht es weiter."; fi
}

backup() {
	mkdir -p "$BACKUPDIR"     # als loxberry -> Verzeichnis bleibt loxberry-eigen (Loeschen moeglich)
	_sperren
	local f rc
	f=$(_freier_name "")
	_sichern "$f"; rc=$?
	case $rc in
		0) echo "Backup erstellt: $f ($(du -h "$BACKUPDIR/$f" 2>/dev/null | cut -f1))" ;;
		"$NICHTS") echo "Keine Konfiguration vorhanden – nichts zu sichern."; exit 1 ;;
		*) echo "Backup fehlgeschlagen – es wurde kein Archiv angelegt."; exit 1 ;;
	esac
	# aelteste ueber KEEP hinaus loeschen (Sicherungen vor Restore eingeschlossen)
	ls -1t "$BACKUPDIR"/loxpanel-config-*.tar.gz 2>/dev/null | tail -n +$((KEEP+1)) | xargs -r rm -f
}

# Erst pruefen, dann tauschen: config/ aendert sich erst, wenn das Backup
# vollstaendig entpackt und als LoxPanel-Konfiguration erkannt und der
# Ist-Stand gesichert ist. Scheitert ein Schritt, bleibt alles, wie es war.
restore() {
	local bn tmp vor rc lief=0
	bn=$(basename "$1")     # nur Dateiname, keine Pfad-Tricks
	[ -f "$BACKUPDIR/$bn" ] || { echo "Backup nicht gefunden: $bn"; exit 1; }
	_sperren
	# 1. In einen Zwischenordner neben config/ entpacken (gleiches Dateisystem ->
	#    der Tausch unten ist nur Umbenennen) und pruefen. Der Container laeuft
	#    dabei weiter.
	tmp=$(mktemp -d "$DATADIR/.restore.XXXXXX") || { echo "Kein Zwischenordner möglich – nichts geändert."; exit 1; }
	tmp=${tmp##*/}
	echo "Prüfe $bn …"
	if ! _indocker 'mkdir "/data/$2/neu" && tar -xzf "/data/backups/$1" -C "/data/$2/neu" || exit 1
for n in $3; do [ -f "/data/$2/neu/$n" ] && sync && exit 0; done
echo "Keine LoxPanel-Konfiguration ($3) im Archiv." >&2; exit 1' "$bn" "$tmp" "$KONFIG_DATEIEN"; then
		_wegraeumen "$tmp"
		echo "Backup beschädigt, unvollständig oder ohne LoxPanel-Konfiguration – nichts geändert."; exit 1
	fi
	# 2. Container anhalten, sonst schreibt der Server womoeglich zwischen
	#    Vorher-Sicherung und Tausch (Speichern im Konfigurator).
	if running; then
		lief=1
		sudo docker stop loxpanel >/dev/null || {
			_wegraeumen "$tmp"; echo "Panel ließ sich nicht anhalten – nichts geändert."; exit 1; }
	fi
	# 3. Ist-Stand sichern - Pflicht, ausser es gibt keinen.
	vor=$(_freier_name "-vor-restore")
	_sichern "$vor"; rc=$?
	case $rc in
		0) echo "Aktuellen Stand gesichert ($vor)." ;;
		"$NICHTS") echo "Keine aktuelle Konfiguration – nichts vorher zu sichern."; vor="" ;;
		*) _wegraeumen "$tmp"; _wieder_starten "$lief"
		   echo "Aktuellen Stand nicht sichern können – nichts geändert."; exit 1 ;;
	esac
	# 4. Tauschen: Ist-Stand nach alt/, Backup nach config/. Scheitert ein
	#    Schritt, kommt der Ist-Stand zurueck (find meldet jeden Fehler von mv).
	echo "Spiele $bn ein …"
	if _indocker 'c=/data/config; t="/data/$1"
mkdir -p "$c" "$t/alt" || exit 1
if find "$c" -mindepth 1 -maxdepth 1 -exec mv -t "$t/alt" -- {} +; then
	find "$t/neu" -mindepth 1 -maxdepth 1 -exec mv -t "$c" -- {} + && sync && exit 0
	find "$c" -mindepth 1 -maxdepth 1 -exec mv -t "$t/neu" -- {} +
fi
find "$t/alt" -mindepth 1 -maxdepth 1 -exec mv -t "$c" -- {} +
exit 1' "$tmp"; then
		_wegraeumen "$tmp"
		echo "Konfiguration wiederhergestellt."
		_wieder_starten "$lief"
	else
		_wieder_starten "$lief"
		echo "Wiederherstellung fehlgeschlagen – der bisherige Stand ist zurückgestellt${vor:+ und liegt zusätzlich in $vor}."
		exit 1
	fi
}

start() {
	rm -f "$STOPPED"
	# Erst pullen, dann up -d: 'up' nutzt sonst ein evtl. veraltetes lokales
	# Image (der :latest-Tag ist rollend).
	sudo docker compose -f "$COMPOSE" pull 2>&1
	sudo docker compose -f "$COMPOSE" up -d 2>&1
}

stop() {
	touch "$STOPPED"
	sudo docker compose -f "$COMPOSE" down 2>&1
}

case "$1" in
	start)   start ;;
	stop)    stop ;;
	restart) stop; start ;;
	check)
		[ -f "$STOPPED" ] && exit 0     # bewusst gestoppt -> nichts tun
		running || start
		;;
	backup)  backup ;;
	restore) restore "$2" ;;
	*) echo "Nutzung: $0 start|stop|restart|check|backup|restore <datei>"; exit 1 ;;
esac
exit 0
