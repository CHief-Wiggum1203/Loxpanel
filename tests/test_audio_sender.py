"""Sender (Favoriten) einer Audio-Zone direkt auf ihrer Detailseite: frueher
nur hinter den drei Punkten (Musikauswahl), dort mit dem Platzhalter
"Playlisten". Jetzt eine Reihe Cover unter dem Titel, die Seite bleibt beim
Antippen stehen (bleiben). Liefert die Zone keine Favoriten, nennt die Seite
den Grund, wenn er bekannt ist (Audioserver nicht verbunden, Anmeldung
abgelehnt). Anlage: lox.haus_anlage() (Zone AZ mit fuenf Favoriten im
sourceList-State, Zone AB ohne)."""
from lox import HAUS_FAVORITEN, W, bloecke, haus_anlage

import diagnose  # noqa: E402  # bin/ liegt durch lox auf dem Pfad


def _app(**states) -> W.App:
    struktur, st = haus_anlage()
    app = W.App({"host": "", "port": 80})
    app._apply_structure(struktur)
    app.states = {**st, **states}
    return app


def _kanal(**felder):
    """Audioserver-Ereignis-Client wie AudioEventClient (nur die Felder, die
    die Seiten lesen); Zone 1 ohne Favoriten."""
    class Kanal:
        favs, now = {}, {}
        verbunden, paired, authed, anmeldung = True, False, False, ""
    k = Kanal()
    for n, w in felder.items():
        setattr(k, n, w)
    return k


def test_sender_auf_der_detailseite():
    v = _app().render({"view": "control", "id": "AZ"})
    arten = [b["k"] for b in v["blocks"]]
    assert arten.index("title") < arten.index("favs") < arten.index("row")
    favs = bloecke(v, "favs")[0]
    assert favs["bleiben"] is True and "wrap" not in favs
    assert [i["label"] for i in favs["items"]] == HAUS_FAVORITEN
    assert favs["items"][0]["cmd"] == {"uuid": "AZ", "cmd": "roomfav/play/1"}
    assert bloecke(v, "more") == [{"k": "more", "route": {"view": "sources", "id": "AZ"}}]


def test_ohne_favoriten_nichts_dazwischen():
    """Zone ohne Favoriten und ohne bekannten Grund: kein leerer Block."""
    for app, zone in ((_app(az4=""), "AZ"), (_app(), "AB")):
        v = app.render({"view": "control", "id": zone})
        assert not bloecke(v, "favs") and not bloecke(v, "status")


def test_musikauswahl_ohne_platzhalter():
    v = _app().render({"view": "sources", "id": "AZ"})
    assert [b["text"] for b in bloecke(v, "head")] == ["Favoriten"]
    assert bloecke(v, "favs")[0]["wrap"] is True and "bleiben" not in bloecke(v, "favs")[0]
    leer = _app(az4="").render({"view": "sources", "id": "AZ"})
    assert [b["text"] for b in bloecke(leer, "status")] == ["noch keine – in der Loxone-App anlegen"]


def test_grund_ohne_verbindung():
    app = _app(az4="")
    app._audio_client_for = lambda c: (_kanal(verbunden=False), 1)
    for route in ({"view": "control", "id": "AZ"}, {"view": "sources", "id": "AZ"}):
        assert [b["text"] for b in bloecke(app.render(route), "status")] == ["Keine Verbindung zum Audioserver"]


def test_grund_anmeldung_gescheitert():
    """Gekoppelt ohne Anmeldung: die Favoriten kaemen nur ueber den Kanal,
    der Ausweg ueber den Miniserver ist leer."""
    app = _app(az4="")
    app._audio_client_for = lambda c: (_kanal(paired=True, anmeldung="abgelehnt (denied)"), 1)
    v = app.render({"view": "control", "id": "AZ"})
    assert [b["text"] for b in bloecke(v, "status")] == ["Anmeldung am Audioserver gescheitert: abgelehnt (denied)"]


def test_kein_grund_solange_nicht_angemeldet_wird():
    """Ungekoppelt (der Kanal darf liefern) oder die Anmeldung laeuft noch:
    kein Grund, die Favoriten kommen gleich."""
    for kanal in (_kanal(), _kanal(paired=True)):
        app = _app(az4="")
        app._audio_client_for = lambda c, k=kanal: (k, 1)
        assert app._favoriten_grund("AZ") == ""


def test_favoriten_vom_kanal_auf_der_detailseite():
    app = _app(az4="")
    app._audio_client_for = lambda c: (_kanal(favs={1: [{"name": "Radio 7091", "slot": 1, "play": 4,
                                                          "cover": ""}]}), 1)
    favs = bloecke(app.render({"view": "control", "id": "AZ"}), "favs")[0]
    assert [(i["label"], i["cmd"]["cmd"]) for i in favs["items"]] == [("Radio 7091", "roomfav/play/4")]


def test_diagnose_nennt_den_grund():
    s = diagnose.zusammenfassung({"audioserver": [
        {"host": "as1", "verbunden": True, "gekoppelt": True, "angemeldet": False, "anmeldung": "keine Antwort"},
        {"host": "as2", "verbunden": True, "gekoppelt": True, "angemeldet": False, "anmeldung": ""}]})
    assert [z for z in s if z.startswith("Audioserver")] == ["Audioserver as1 verbunden (gekoppelt, nicht angemeldet: keine Antwort).",
                 "Audioserver as2 verbunden (gekoppelt, nicht angemeldet)."]
