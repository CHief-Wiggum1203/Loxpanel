"""Richtung der Abhaengigkeiten beim Zerlegen des Servers: webvisu.py importiert
die herausgeloesten Module, nie umgekehrt. Ein Import von webvisu aus konfig,
sicherung oder bausteine waere ein Kreis (und beim Start als Skript ein zweites
Exemplar des Servers). Dazu: die statischen Sanitizer der App sind genau die
Funktionen aus konfig.py, und die Pfade der Konfigdateien gibt es in jedem
Modul, das sie liest, unter demselben Namen (Fixture cfg_ordner)."""
import ast
import subprocess
import sys
from pathlib import Path

from lox import konfig, PAKETE, SERVER_MODULE, sicherung, W, ZERLEGT

ROOT = Path(__file__).resolve().parents[1]
UNTEN = [*(f"bin/{n}.py" for n in ZERLEGT),
         *sorted(p.relative_to(ROOT).as_posix() for paket in PAKETE
                 for p in (ROOT / "bin" / paket.__name__).glob("*.py"))]


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


def test_jedes_untere_modul_haengt_am_server():
    """Kein herausgeloestes Modul liegt tot herum: webvisu importiert es selbst
    oder ein anderes Server-Modul tut es (sicherung etwa nur noch die Routen)."""
    genutzt = _importe(ROOT / "bin/webvisu.py")
    for rel in UNTEN:
        genutzt |= _importe(ROOT / rel) - {Path(rel).stem}
    assert {*ZERLEGT, *(p.__name__ for p in PAKETE)} <= genutzt


def test_jedes_herausgeloeste_modul_ist_ein_server_modul():
    """ersetzen() und cfg_ordner wirken nur in SERVER_MODULE; ein Modul, das aus
    webvisu herausgeloest wurde und dort fehlt, behielte gepatchte Werte."""
    namen = {m.__name__ for m in SERVER_MODULE}
    assert {"webvisu", *ZERLEGT} <= namen
    for paket in PAKETE:
        assert {f"{paket.__name__}.{p.stem}" for p in (ROOT / "bin" / paket.__name__).glob("*.py")
                if p.stem != "__init__"} <= namen, paket.__name__
    for datei in (ROOT / "bin").glob("*.py"):
        if datei.stem not in ("webvisu", *ZERLEGT):
            assert "from webvisu" not in datei.read_text(encoding="utf-8"), datei


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
    assert sicherung.CFG_FILE == konfig.CFG_FILE and konfig.PANELS_FILE == konfig.PANELS_FILE


def test_bausteine_importieren_keine_themen():
    """Die Bausteine sind die untere Schicht: die Themenmodule (statistik,
    miniserver, seiten ...) importieren aus bausteine, nie umgekehrt. Sonst
    laedt bausteine/__init__.py beim ersten Import eines Themas dessen halb
    fertiges Modul (Kreis)."""
    erlaubt = {"bausteine", "adapters", "__future__", *sys.stdlib_module_names}
    for datei in sorted((ROOT / "bin/bausteine").glob("*.py")):
        fremd = _importe(datei) - erlaubt
        assert not fremd, f"{datei.name} importiert {sorted(fremd)}"


def test_jedes_modul_laedt_auch_als_erstes():
    """Kein Kreis zwischen den Server-Modulen: jedes laesst sich als erstes
    importieren, nicht nur ueber webvisu (Werkzeuge, Tests, ein kuenftiger
    Einstieg). Ein eigener Interpreter; vor jedem Modul fliegen die Module aus
    bin/ wieder aus sys.modules, sonst laege der Rest schon geladen da."""
    skript = (
        "import importlib, sys\n"
        "bin_ = sys.argv[1]; sys.path.insert(0, bin_); fehler = []\n"
        "for name in sys.argv[2:]:\n"
        "    for k in [k for k, m in list(sys.modules.items()) if (getattr(m, '__file__', '') or '').startswith(bin_)]:\n"
        "        del sys.modules[k]\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "    except Exception as e:\n"
        "        fehler.append(f'{name}: {e!r}')\n"
        "print('\\n'.join(fehler))\n")
    namen = sorted(m.__name__ for m in SERVER_MODULE)
    r = subprocess.run([sys.executable, "-c", skript, str(ROOT / "bin"), *namen],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and not r.stdout.strip(), r.stdout + r.stderr
