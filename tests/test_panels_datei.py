"""config/panels.json einmal lesen (ARCHITEKTUR P2): load_panels_doc() liefert
Ansichten und Geraete aus einem Lesen, die App holt sich beides beim Start in
einem Zug. Eine kaputte Datei gibt beides leer, statt den Start abzubrechen."""
import json
from pathlib import Path

import pytest

from lox import konfig, W


def _schreiben(cfg_ordner, inhalt) -> Path:
    f = cfg_ordner / "panels.json"
    f.write_text(inhalt if isinstance(inhalt, str) else json.dumps(inhalt), encoding="utf-8")
    return f


def test_app_liest_panels_json_einmal(cfg_ordner, monkeypatch):
    f = _schreiben(cfg_ordner, {"panels": {"wz": {"title": "Wohnzimmer"}, "_notiz": {}},
                                "devices": {"wand": {"panel": "wz"}}})
    gelesen = []
    echt = Path.read_text

    def read_text(self, *a, **k):
        if self.name == f.name:
            gelesen.append(self)
        return echt(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", read_text)
    app = W.App({"host": "", "port": 80})
    assert app.panels == {"wz": {"title": "Wohnzimmer"}} and app.devices == {"wand": {"panel": "wz"}}
    assert len(gelesen) == 1


@pytest.mark.parametrize("inhalt", ["[1, 2]", "kaputt", '{"panels": [1], "devices": "x"}', "\"text\""])
def test_kaputte_datei_gibt_beides_leer(cfg_ordner, inhalt):
    _schreiben(cfg_ordner, inhalt)
    assert konfig.load_panels_doc() == ({}, {})
    assert konfig.load_panels() == {}


def test_ohne_datei_beides_leer(cfg_ordner):
    assert konfig.load_panels_doc() == ({}, {})
