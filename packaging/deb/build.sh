#!/bin/sh
# Baut das LoxPanel-Server .deb. Auszufuehren auf einem Debian-Host (dpkg-deb).
# Nimmt den Code aus dem Repo (bin/webfrontend/config), Config OHNE echte
# Zugangsdaten (nur .example/Schema). Ergebnis-.deb liegt im Repo-Wurzel.
set -e

HERE=$(cd "$(dirname "$0")" && pwd)     # packaging/deb
REPO=$(cd "$HERE/../.." && pwd)         # Repo-Wurzel
# Version aus der gemeinsamen Projektquelle loxberry-plugin/plugin.cfg (wie
# APK, Docker-Image und LoxBerry-Plugin), nicht aus control. Muster wie in
# bin/version_info.py: VERSION=x.y.z, jede Stelle mindestens eine Ziffer;
# Windows-Zeilenenden (CR) stoeren nicht.
VERSION=$(tr -d '\r' < "$REPO/loxberry-plugin/plugin.cfg" \
    | sed -n 's/^VERSION=\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\)[[:space:]]*$/\1/p' | head -n 1)
if [ -z "$VERSION" ]; then
    echo "loxberry-plugin/plugin.cfg: keine Zeile VERSION=x.y.z" >&2
    exit 1
fi
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT             # auch bei Abbruch aufraeumen
trap 'exit 1' HUP INT TERM
PKG="$STAGE/loxpanel-server_${VERSION}_all"

install -d "$PKG/DEBIAN" "$PKG/opt/loxpanel/app/config" \
          "$PKG/usr/lib/systemd/system" "$PKG/usr/bin" "$PKG/etc/loxpanel"

# --- App-Code aus dem Repo ---
cp -r "$REPO/bin"          "$PKG/opt/loxpanel/app/bin"
cp -r "$REPO/webfrontend"  "$PKG/opt/loxpanel/app/webfrontend"
[ -d "$REPO/deploy" ] && cp -r "$REPO/deploy" "$PKG/opt/loxpanel/app/deploy" || true
cp "$REPO/requirements.txt" "$PKG/opt/loxpanel/app/requirements.txt"
# Config credential-frei: nur Vorlagen/Schema, keine echten Daten
for f in "$REPO"/config/*.example* "$REPO"/config/*.schema.json; do
    [ -e "$f" ] && cp "$f" "$PKG/opt/loxpanel/app/config/"
done

# --- Control + Maintainer-Skripte ---
# control traegt keine eigene Version: sie wird hier hinter Package: eingesetzt
# und geprueft (genau eine Zeile Version:, die aus plugin.cfg).
awk -v v="$VERSION" '{print} /^Package:/{print "Version: " v}' "$HERE/control" > "$PKG/DEBIAN/control"
if [ "$(grep '^Version:' "$PKG/DEBIAN/control")" != "Version: $VERSION" ]; then
    echo "packaging/deb/control: braucht eine Zeile Package: und keine eigene Zeile Version: (die Version kommt aus loxberry-plugin/plugin.cfg)" >&2
    exit 1
fi
cp "$HERE/conffiles" "$PKG/DEBIAN/"
for s in postinst prerm postrm; do
    cp "$HERE/$s" "$PKG/DEBIAN/$s"; chmod 0755 "$PKG/DEBIAN/$s"
done

# --- systemd + Kiosk + Display-Abschaltung + Conf ---
cp "$HERE/loxpanel-server.service"  "$PKG/usr/lib/systemd/system/"
cp "$HERE/loxpanel-display.service" "$PKG/usr/lib/systemd/system/"
cp "$HERE/loxpanel-kiosk"   "$PKG/usr/bin/loxpanel-kiosk";   chmod 0755 "$PKG/usr/bin/loxpanel-kiosk"
cp "$HERE/loxpanel-display" "$PKG/usr/bin/loxpanel-display"; chmod 0755 "$PKG/usr/bin/loxpanel-display"
cp "$HERE/browser.conf"     "$PKG/etc/loxpanel/browser.conf"
cp "$HERE/display.conf"     "$PKG/etc/loxpanel/display.conf"

OUT="$REPO/loxpanel-server_${VERSION}_all.deb"
dpkg-deb --root-owner-group --build "$PKG" "$OUT"
echo "Fertig: $OUT"
