"""pytest-Einstellungen fuer LoxPanel.

- bin/ liegt im Suchpfad (ueber lox.py), die Tests importieren webvisu direkt.
- `miniserver_http`: der Nachbau spricht HTTP; webvisu entscheidet das Schema
  sonst am Port (nur 80 = HTTP).
- Waechter: kein Test darf config/ veraendern - dort liegen im Betrieb die
  echten Einstellungen (Volume /app/config).
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
