"""Richtung der Abhaengigkeiten beim Zerlegen des Servers: webvisu.py importiert
die herausgeloesten Module, nie umgekehrt. Ein Import von webvisu aus konfig,
sicherung oder bausteine waere ein Kreis (und beim Start als Skript ein zweites
Exemplar des Servers). Dazu: die statischen Sanitizer der App sind genau die
Funktionen aus konfig.py, und die Pfade der Konfigdateien gibt es in jedem
Modul, das sie liest, unter demselben Namen (Fixture cfg_ordner)."""
import ast
from pathlib import Path

from lox import SERVER_MODULE, W, konfig, sicherung

ROOT = Path(__file__).resolve().parents[1]
UNTEN = ["bin/konfig.py", "bin/sicherung.py", *sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "bin/bausteine").glob("*.py"))]


def _importe(datei: Path) -> set:
    tree = ast.parse(datei.read_text(encoding="utf-8"))
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            out.add(n.module.split(".")[0])
    return out


def test_untere_module_importieren_webvisu_nicht():
    for rel in UNTEN:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        # Laufzeit-Importe (nicht unter TYPE_CHECKING)
        laufzeit = set()
        for n in tree.body:
            if isinstance(n, ast.Import):
                laufzeit.update(a.name.split(".")[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module:
                laufzeit.add(n.module.split(".")[0])
            elif isinstance(n, ast.FunctionDef):
                for x in ast.walk(n):
                    if isinstance(x, (ast.Import, ast.ImportFrom)):
                        laufzeit.add((getattr(x, "module", None) or x.names[0].name).split(".")[0])
        assert "webvisu" not in laufzeit, f"{rel} importiert webvisu"


def test_webvisu_nutzt_die_unteren_module():
    assert {"konfig", "sicherung", "bausteine"} <= _importe(ROOT / "bin/webvisu.py")


def test_sanitizer_der_app_sind_die_aus_konfig():
    for name in ("_sanitize_panels", "_panels_verworfen", "_panels_doc", "_sanitize_devices",
                 "_sanitize_display", "_devices_export", "_sanitize_theme_ui", "_sanitize_categories"):
        assert getattr(W.App, name) is getattr(konfig, name), name


def test_pfade_heissen_ueberall_gleich():
    """cfg_ordner ersetzt die Pfade in jedem Modul, das sie kennt; webvisu und
    konfig muessen dieselben Objekte tragen, sonst schreibt eines daneben."""
    for name in ("_CFGDIR", "CFG_FILE", "CFG_EXAMPLE", "PANELS_FILE", "THEME_FILE"):
        traeger = [m for m in SERVER_MODULE if hasattr(m, name)]
        assert konfig in traeger, name
        assert all(getattr(m, name) == getattr(konfig, name) for m in traeger), name
    assert sicherung.CFG_FILE == konfig.CFG_FILE and W.PANELS_FILE == konfig.PANELS_FILE
    assert len(SERVER_MODULE) == 3
