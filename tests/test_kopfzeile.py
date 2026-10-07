"""Kopfzeile (Widget "header"): Uhr, Wetter und nach Wahl Werte in EINER Zeile
ueber dem Kachelraster statt einer Pane daneben. Hier die Server-Seite: die
Grammatik in ui.panes, der Rundweg durch Speichern und Export, und dass eine
freie Seite (Widget-Tab) und die Uhr-Seite die Kopfzeile nicht annehmen."""
from lox import W


def test_grammatik_der_kopfzeile():
    assert W._clean_tabpane("header") == "header"
    assert W._clean_tabpane("header:") == "header"            # ohne Werte: Uhr und Wetter
    assert W._clean_tabpane("header:A, B,,") == "header:A,B"  # Werte getrimmt, Leere weg
    zu_viele = "header:" + ",".join(f"U{i}" for i in range(W.SV_STATUS_MAX + 3))
    assert W._clean_tabpane(zu_viele).count(",") == W.SV_STATUS_MAX - 1
    assert W._clean_tabpane("headerx") == "" and W._clean_tabpane("kopf") == ""
    # Widget-Tab (ganze Seite) und Uhr-Seite kennen keine Kopfzeile
    assert W._clean_widget_tab("header") == "" and W._clean_widget_tab("header:A") == ""
    assert W._clean_widget_tab("weather") == "weather" and W._clean_widget_tab("status:A") == "status:A"
    assert W._clean_svpane("header") == "" and W._clean_svpane("header:A") == ""


def test_kopfzeile_speichern_und_exportieren():
    roh = {"test": {"title": "Test", "tabs": ["favoriten", "zentral"],
                    "ui": {"panes": {"favoriten": "header:A,B", "zentral": "header"}}}}
    p = W.App._sanitize_panels(roh)["test"]
    assert p["ui"]["panes"] == {"favoriten": "header:A,B", "zentral": "header"}
    # Rundweg: was der Konfigurator bekommt, kommt beim Speichern unveraendert an
    app = W.App({"host": "", "port": 80})
    exp = app._panel_export(p)
    assert exp["ui"]["panes"] == {"favoriten": "header:A,B", "zentral": "header"}
    assert W.App._sanitize_panels({"test": exp})["test"]["ui"]["panes"] == p["ui"]["panes"]
    assert W.App._panels_verworfen(roh, W.App._sanitize_panels(roh)) == []


def test_widget_seite_nimmt_keine_kopfzeile():
    """Eine freie Seite kann ein Widget als ganze Seite sein - die Kopfzeile
    nicht: ohne Kacheln darunter bliebe die Seite leer. Der Server verwirft
    sie und meldet das, damit der Konfigurator warnt."""
    roh = {"test": {"title": "Test", "tabs": ["auswahl"],
                    "pickTabs": [{"name": "Seite", "picks": ["S1"], "widget": "header"}]}}
    p = W.App._sanitize_panels(roh)["test"]
    assert "widget" not in p["pickTabs"][0]
    assert W.App._panels_verworfen(roh, W.App._sanitize_panels(roh))


def test_panes_werden_normiert_gespeichert():
    """Codex-Befund: Speichern und Export hielten den Rohwert ("header:A, B"),
    das Panel meldete dann " B" als UUID. Jetzt steht ueberall der normierte
    Wert - auch im aufgeloesten Profil, denn die Datei wird beim Laden nicht
    sanitisiert."""
    roh = {"test": {"title": "Test", "tabs": ["favoriten", "zentral", "raeume"],
                    "ui": {"panes": {"favoriten": "header:A, B,,", "zentral": "status: A ,B", "raeume": "header:"}}}}
    p = W.App._sanitize_panels(roh)["test"]
    assert p["ui"]["panes"] == {"favoriten": "header:A,B", "zentral": "status:A,B", "raeume": "header"}
    assert W.App._panels_verworfen(roh, W.App._sanitize_panels(roh)) == []
    app = W.App({"host": "", "port": 80})
    assert app._panel_export(roh["test"])["ui"]["panes"] == p["ui"]["panes"]
    app.panels = roh                                    # wie aus einer von Hand geschriebenen Datei
    assert app.resolve_profile("test")["panes"] == p["ui"]["panes"]
