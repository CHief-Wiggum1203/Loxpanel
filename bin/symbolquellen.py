"""Symbolquellen der Kacheln und freien Seiten: die Loxone-Icon-Bibliothek
(SVGs des LoxBerry-Plugins "loxoneicons", Route /loxlib) und die Pruefung der
Icon-Angaben aus dem Konfigurator (_clean_icon, _clean_seiten_icon), die
_sanitize_panels() in konfig.py anwendet. Nur Standardbibliothek; importiert
kein anderes Server-Modul."""
import os
import re

# Loxone-Icon-Bibliothek: SVGs des LoxBerry-Plugins "loxoneicons", read-only in
# den Container gemountet (docker-compose). Fehlt der Mount/das Plugin, ist der
# Ordner leer -> die Icon-Quelle erscheint gar nicht. Ueber Env ueberschreibbar.
LOXLIB_DIR = os.environ.get("LOXPANEL_LOXLIB_DIR", "/app/loxone-icons/filled")

_LOXLIB_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}\.svg$")


def _loxlib_names() -> list:
    """Dateinamen der Loxone-Bibliothek (flache .svg im gemounteten Ordner)."""
    try:
        return sorted(fn for fn in os.listdir(LOXLIB_DIR)
                      if _LOXLIB_NAME.match(fn) and ".." not in fn)
    except OSError:
        return []


def _clean_icon(ic):
    """Icon-Referenz einer Kachel validieren (Quelle + sicherer Bezeichner).
    Nur die Quellen, die der Kachel-Editor anbietet und der Server ausliefert:
    eingebaut, Loxone-Icon des Miniservers (/icon) und Loxone-Bibliothek
    (/loxlib)."""
    if not isinstance(ic, dict):
        return None
    s = ic.get("src")
    if s == "builtin" and isinstance(ic.get("id"), str) and re.match(r"^[A-Za-z0-9_]{1,32}$", ic["id"]):
        return {"src": "builtin", "id": ic["id"]}
    if s == "loxone" and isinstance(ic.get("p"), str) and ".." not in ic["p"] \
            and (ic["p"].endswith(".svg") or ic["p"].endswith(".png")):
        return {"src": "loxone", "p": ic["p"]}
    if s == "loxlib" and isinstance(ic.get("name"), str) and _LOXLIB_NAME.match(ic["name"]) \
            and ".." not in ic["name"]:
        return {"src": "loxlib", "name": ic["name"]}
    return None


def _clean_seiten_icon(ic) -> str:
    """Icon einer freien Seite: die fertige Adresse aus der Icon-Auswahl des
    Konfigurators (/icon?p=... oder /loxlib?n=...) oder ein Loxone-Icon-Pfad,
    den der Server ueber /icon vom Miniserver holt (relativ, ohne Schema).
    Alles andere -> "", vor allem fremde Adressen: "//host/x.png" faengt mit
    "/" an und ginge sonst unveraendert an die Visu, die das Bild dann von
    dort laedt."""
    ic = str(ic or "").strip()[:200]
    if ic.startswith("/icon?") or ic.startswith("/loxlib?"):
        return ic
    if ic.startswith("/") or ":" in ic or "\\" in ic or ".." in ic:
        return ""
    return ic if ic.endswith(".svg") or ic.endswith(".png") else ""
