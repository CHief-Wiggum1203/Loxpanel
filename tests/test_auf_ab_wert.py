"""Auf/Ab-Taster mit Wert (UpDownAnalog): frueher nur Anzeige. Laut
Loxone-Strukturdoku ("UpDownLeftRight analog") ist der Befehl der neue Wert
zwischen details.min und details.max, die -/+ Tasten schalten um details.step
weiter - dieselbe Detailseite wie der Schieberegler (Slider). Der Baustein
kommt aus tests/lox.py (aufab_baustein, Name wie an einer echten Anlage)."""
from lox import W, anlage, aufab_baustein, bloecke


def _app(**kw) -> W.App:
    control, states = aufab_baustein(**kw)
    app = W.App({"host": "", "port": 80})
    app._apply_structure(anlage({"UDA": control}))
    app.states = states
    return app


def test_kachel():
    it = _app(wert=2)._control_item("UDA")
    assert it["sublabel"] == "2" and it["nav"] == {"view": "control", "id": "UDA"}


def test_detail_regler_mit_grenzen_und_schritt():
    v = _app(wert=2).render({"view": "control", "id": "UDA"})
    assert [b["text"] for b in bloecke(v, "big")] == ["2"]
    assert bloecke(v, "slider") == [{"k": "slider", "icon": "switch", "value": 2, "min": 1, "max": 3,
                                     "step": 1, "cmd": {"uuid": "UDA", "tmpl": "{v}"}}]
    assert not bloecke(v, "status")


def test_kommastellen():
    v = _app(wert=20, format="%.1f", min=0, max=30, step=0.5).render({"view": "control", "id": "UDA"})
    assert [b["text"] for b in bloecke(v, "big")] == ["20,0"]
    sl = bloecke(v, "slider")[0]
    assert (sl["value"], sl["min"], sl["max"], sl["step"]) == (20, 0, 30, 0.5)


def test_ungueltiger_wert():
    """State error: der Wert des virtuellen Eingangs ist ungueltig."""
    v = _app(fehler=1).render({"view": "control", "id": "UDA"})
    assert [b["text"] for b in bloecke(v, "status")] == ["Ungültiger Wert"]


def test_kategorie_ampel_neutral():
    """Kein an/aus: auch in einer Kategorie mit Zustandsfarben bleibt die
    Kachel neutral, wie beim Schieberegler."""
    app = _app()
    app.theme = {"categories": {"Energie": {"on": "#0000ff", "off": "#333333"}}}
    assert "bg" not in (app._control_item("UDA").get("style") or {})


def test_status_voll():
    assert {t["type"]: t["status"] for t in _app().types_overview()["types"]}["UpDownAnalog"] == "full"
