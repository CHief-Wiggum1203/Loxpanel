"""Bausteine der Visu, Familie Zentralbausteine (Typen mit Praefix Central): nur die Kachel, die Detailseite ist die Gruppe.

Kachel (@kachel) und Detailseite (@detail) je Typ, siehe bausteine/__init__.py.
Die Helfer (app._state, app._fmt_num ...) sind Methoden von App in webvisu.py."""
from __future__ import annotations

from bausteine import kachel_praefix


@kachel_praefix("Central")
def kachel_zentralbaustein(app, uuid, c, it):
    t = c.get("type")
    n = app._zentral_an(c)
    # Einzahl bei genau einem: "Spielt in 1 Raum", nicht "in 1 Räumen"
    if t == "CentralLightController":
        it["sublabel"] = f"In {n} {'Raum' if n == 1 else 'Räumen'} aktiv" if n else "Aus"
    elif t == "CentralAudioZone":
        it["sublabel"] = f"Spielt in {n} {'Raum' if n == 1 else 'Räumen'}" if n else "Aus"
    elif t in ("CentralGate", "CentralWindow"):
        it["sublabel"] = f"{n} offen" if n else "Alle geschlossen"
    elif t == "CentralJalousie":
        it.update(sublabel="Beschattung", subInfo=True)
    elif t == "CentralAlarm":
        it.update(sublabel="Alarmzentrale", subInfo=True)
    if "sublabel" not in it:
        it.update(sublabel="Zentral", subInfo=True)
    it.update(icon="central", on=(n > 0),
              nav={"view": "group", "kind": "central", "id": uuid})
