"""Englische Oberflaeche des Konfigurators: Jeder Text, den config.html
uebersetzen laesst - per T('...') im Skript oder als Element mit data-i18n -,
hat einen Eintrag im englischen Katalog von i18n.js. Fehlt einer, bleibt der
Text im Englischen deutsch stehen, ohne dass es auffaellt.

Der Schluessel eines data-i18n-Elements ist, wie in i18n.js apply(), sein
Text ohne Tags mit aufgeloesten Entities (el.textContent.trim())."""
import re
from html.parser import HTMLParser

from lox import ROOT

HTML = ROOT / "webfrontend" / "html"
ZEICHENKETTE = r"'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\""


def _ohne_kommentare(js: str) -> str:
    """// und /* */ ausserhalb von Zeichenketten entfernen."""
    out, i, q = [], 0, None
    while i < len(js):
        c = js[i]
        if q:
            out.append(c)
            if c == "\\":
                out.append(js[i + 1])
                i += 2
                continue
            if c == q:
                q = None
        elif c in "'\"":
            q = c
            out.append(c)
        elif js.startswith("//", i):
            i = js.find("\n", i)
            if i < 0:
                break
            continue
        elif js.startswith("/*", i):
            i = js.index("*/", i) + 2
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _text(literal: str) -> str:
    """JS-Zeichenkette samt Anfuehrungszeichen -> Text."""
    def ersatz(m):
        e = m.group(1)
        if e.startswith("u") and len(e) == 5:
            return chr(int(e[1:], 16))
        return {"n": "\n", "t": "\t"}.get(e, e)
    return re.sub(r"\\(u[0-9a-fA-F]{4}|.)", ersatz, literal[1:-1])


def _paare() -> list:
    """Alle Eintraege des englischen Katalogs in Dateireihenfolge, auch doppelte."""
    js = _ohne_kommentare((HTML / "i18n.js").read_text(encoding="utf-8"))
    start = js.index("{", js.index("en:", js.index("var CAT")))
    tiefe, q, i = 0, None, start
    while i < len(js):
        c = js[i]
        if q:
            if c == "\\":
                i += 1
            elif c == q:
                q = None
        elif c in "'\"":
            q = c
        elif c == "{":
            tiefe += 1
        elif c == "}":
            tiefe -= 1
            if tiefe == 0:
                break
        i += 1
    block = js[start:i + 1]
    return [(_text(k), _text(v)) for k, v in re.findall(rf"({ZEICHENKETTE})\s*:\s*({ZEICHENKETTE})", block)]


def _katalog_en() -> dict:
    """Wirksamer Katalog: bei doppeltem Schluessel gilt wie in JS der spaetere."""
    return dict(_paare())


class _Markiert(HTMLParser):
    """Sammelt den Text aller Elemente mit data-i18n (ohne Attributwert)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.texte: list[str] = []
        self._offen: list[list] = []      # je markiertem Element: [Tag, Tiefe, Text]

    def handle_starttag(self, tag, attrs):
        for e in self._offen:
            if e[0] == tag:
                e[1] += 1
        a = dict(attrs)
        if "data-i18n" in a:
            if a["data-i18n"]:
                self.texte.append(a["data-i18n"])
            else:
                self._offen.append([tag, 1, ""])

    def handle_endtag(self, tag):
        for e in list(self._offen):
            if e[0] == tag:
                e[1] -= 1
                if e[1] == 0:
                    self._offen.remove(e)
                    self.texte.append(e[2].strip())

    def handle_data(self, data):
        for e in self._offen:
            e[2] += data


def _zu_uebersetzen(datei: str) -> set:
    quelle = (HTML / datei).read_text(encoding="utf-8")
    p = _Markiert()
    p.feed(quelle)
    texte = {t for t in p.texte if t}
    texte |= {_text(m) for m in re.findall(rf"\bT\(\s*({ZEICHENKETTE})\s*\)", quelle)}
    return texte


def test_katalog_wird_gelesen():
    kat = _katalog_en()
    assert kat["Speichern"] == "Save" and kat["Baustein"] == "Block"
    assert len(kat) > 300


def test_kein_schluessel_mit_zwei_verschiedenen_uebersetzungen():
    """Ein doppelter Schluessel ueberschreibt still den frueheren: "Baustein"
    stand einmal als "Block" und weiter unten als "block" im Katalog."""
    werte: dict = {}
    for k, v in _paare():
        werte.setdefault(k, set()).add(v)
    widersprueche = {k: sorted(v) for k, v in werte.items() if len(v) > 1}
    assert widersprueche == {}, widersprueche


def test_jeder_text_des_konfigurators_hat_eine_englische_uebersetzung():
    kat = _katalog_en()
    texte = _zu_uebersetzen("config.html")
    assert "Bausteintypen der Anlage anzeigen" in texte, "der Link zu /api/types ist zum Uebersetzen markiert"
    fehlt = sorted(t for t in texte if t not in kat)
    assert fehlt == [], "ohne englischen Eintrag in i18n.js: " + "; ".join(fehlt)
