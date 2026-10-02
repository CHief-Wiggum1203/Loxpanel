"""pytest-Einstellungen fuer LoxPanel.

- bin/ liegt im Suchpfad (ueber lox.py), die Tests importieren webvisu direkt.
- `miniserver_http`: der Nachbau spricht HTTP; webvisu entscheidet das Schema
  sonst am Port (nur 80 = HTTP).
- Waechter: kein Test darf config/ veraendern - dort liegen im Betrieb die
  echten Einstellungen (Volume /app/config).
- `cfg_ordner`: config/ fuer einen Test nach tmp_path umleiten, Lesen UND
  Schreiben (siehe dort).
"""
from __future__ import annotations

import pytest

from lox import ROOT, W


def _config_stand() -> dict:
    cfg = ROOT / "config"
    return {p.name: p.stat().st_mtime_ns for p in cfg.iterdir()} if cfg.is_dir() else {}


@pytest.fixture(autouse=True, scope="session")
def config_unveraendert():
    vorher = _config_stand()
    yield
    assert _config_stand() == vorher, "Tests haben Dateien in config/ angelegt oder veraendert"


@pytest.fixture
def miniserver_http(monkeypatch):
    monkeypatch.setattr(W, "_ms_https", lambda port: False)


@pytest.fixture
def cfg_ordner(tmp_path, monkeypatch):
    """config/ nach tmp_path/config umleiten. Geschrieben wird ueber die
    Konstanten (CFG_FILE, PANELS_FILE, THEME_FILE), gelesen ueber die Leser,
    die Path(__file__) erst beim Aufruf auswerten - darum beides. Die App erst
    danach anlegen, sie liest in __init__."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setattr(W, "__file__", str(tmp_path / "bin" / "webvisu.py"))
    for name, pfad in (("_CFGDIR", cfg), ("CFG_FILE", cfg / "loxpanel.cfg"),
                       ("CFG_EXAMPLE", cfg / "loxpanel.cfg.example"),
                       ("PANELS_FILE", cfg / "panels.json"), ("THEME_FILE", cfg / "theme.json")):
        monkeypatch.setattr(W, name, pfad)
    monkeypatch.delenv("LOXPANEL_MS_HOST", raising=False)   # sonst nimmt _config() die Umgebung
    return cfg
