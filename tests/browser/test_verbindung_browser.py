"""Verbindungsleiste der Visu in Chromium (t:"verbindung", verbindungZeigen).

Fehlt die Verbindung zum Server oder die des Servers zum Miniserver, sperrt
die Visu sofort jeden Befehl; die Leiste mit "seit" und dem letzten
bestaetigten Stand und die blasse Darstellung kommen nach
VERBINDUNG_HINWEIS s, oder sofort, wenn ein Tipp gesperrt wurde. Kommt die
Verbindung zurueck, verschwindet beides und Befehle gehen wieder raus.
Schweigt der Server laenger als VERBINDUNG_STUMM s, baut die Visu den
WebSocket neu auf, ohne dass die Leiste aufblitzt. Am 4"-Panel (480 x 480)
mit und ohne Kachel-Set; die Texte kommen aus VERBINDUNG_TEXTE, die Uhrzeiten
rechnet der Test in der Ortszeit nach, in der auch Chromium laeuft."""
import asyncio
import time
from datetime import datetime

import pytest

from lox import anlage, ersetzen, verteilung, visu_starten, W

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

HINWEIS = 1   # s: VERBINDUNG_HINWEIS im Test


def _schalter(u, name):
    return {"name": name, "type": "Switch", "uuidAction": u, "room": "r1", "cat": "c1",
            "isFavorite": True, "states": {"active": u.lower()}}


STRUKTUR = anlage({u: _schalter(u, n) for u, n in (("S1", "Stehlampe"), ("S2", "Leselampe"),
                                                    ("S3", "Terrasse"), ("S4", "Küche"))})
STATES = {"s1": 1, "s2": 0, "s3": 0, "s4": 1}

LEISTE = """() => { const b = document.getElementById('verbindung');
  return {sichtbar: !b.hidden && getComputedStyle(b).display !== 'none',
          titel: b.querySelector('.vb-titel').textContent, stand: b.querySelector('.vb-stand').textContent,
          blass: document.querySelector('.screen').classList.contains('verbweg')}; }"""


@pytest.fixture(autouse=True)
def _kurz(monkeypatch):
    ersetzen(monkeypatch, "VERBINDUNG_HINWEIS", HINWEIS)


def _app(ui=None):
    app = W.App({"host": "", "port": 80})
    app._apply_structure(STRUKTUR)
    app.states = dict(STATES)
    app.panels = W.App._sanitize_panels({"test": {"title": "Test", "tabs": ["favoriten"],
                                                  "ui": {"split": False, **(ui or {})}}})
    app.befehle = []

    async def command(uuid, cmd, pin=None):
        app.befehle.append((uuid, cmd))
        return "200"
    app.command = command
    return app


async def _visu(b, port, fehler):
    pg = await b.new_page(viewport={"width": 480, "height": 480})
    pg.on("pageerror", lambda e: fehler.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{port}/?panel=test")
    await pg.wait_for_selector("#grid .tile[data-id]", state="attached")
    if await pg.locator("#saver:not(.hidden)").count():
        await pg.click("#saver")
    await pg.wait_for_function("verb.server && verb.texte")
    return pg


def _uhr(ms: int, sekunden=False) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%H:%M:%S" if sekunden else "%H:%M")


@pytest.mark.parametrize("ui", [{}, {"tileSet": "touch"}, {"tileSet": "loxone"}], ids=["ohne_set", "touch", "loxone"])
def test_miniserver_weg_sperrt_und_zeigt_die_leiste(ui, tmp_path):
    async def lauf():
        app = _app(ui)
        runner, port, bc = await visu_starten(app)
        fehler, m = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _visu(b, port, fehler)
                await pg.click('#grid .tile[data-id="S2"] .name')
                await pg.wait_for_timeout(300)
                m["vorher_befehle"] = list(app.befehle)

                app._ms_bestaetigt, app._ms_weg_seit = time.time() - 4, time.time()
                await pg.wait_for_function("!verb.ms")
                m["sofort"] = await pg.evaluate(LEISTE)
                await pg.wait_for_timeout(HINWEIS * 1000 + 400)
                m["nach_frist"] = await pg.evaluate(LEISTE)
                await pg.screenshot(path=str(tmp_path / f"verbindung_ms_weg_{'_'.join(ui.values()) or 'ohne'}.png"))
                await pg.click('#grid .tile[data-id="S3"] .name')
                await pg.wait_for_timeout(300)
                m["gesperrt_befehle"] = list(app.befehle)

                app._ms_weg_seit = None
                await pg.wait_for_function("verb.ms")
                m["zurueck"] = await pg.evaluate(LEISTE)
                await pg.click('#grid .tile[data-id="S3"] .name')
                await pg.wait_for_timeout(300)
                m["danach_befehle"] = list(app.befehle)
                await b.close()
            return m, round(app._ms_bestaetigt * 1000)
        finally:
            bc.cancel()
            await runner.cleanup()

    m, stand = asyncio.run(lauf())
    assert len(m["vorher_befehle"]) == 1, m
    # gesperrt sofort, die Leiste erst nach der Frist
    assert not m["sofort"]["sichtbar"] and not m["sofort"]["blass"], m
    leiste = m["nach_frist"]
    assert leiste["sichtbar"] and leiste["blass"], leiste
    t = verteilung.VERBINDUNG_TEXTE
    assert leiste["titel"].startswith(t["ms"].split("{seit}")[0]) and "{" not in leiste["titel"], leiste
    assert leiste["stand"] == t["stand"].replace("{stand}", _uhr(stand, True)) + " · " + t["gesperrt"], leiste
    assert m["gesperrt_befehle"] == m["vorher_befehle"], "gesperrt: kein Befehl"
    # zurueck: Leiste weg, Befehle gehen wieder
    assert not m["zurueck"]["sichtbar"] and not m["zurueck"]["blass"], m
    assert len(m["danach_befehle"]) == 2, m


def test_gesperrter_tipp_zeigt_die_leiste_sofort():
    """Wer waehrend der Frist tippt, soll sehen, warum nichts passiert."""
    async def lauf():
        app = _app()
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _visu(b, port, fehler)
                app._ms_bestaetigt, app._ms_weg_seit = time.time() - 4, time.time()
                await pg.wait_for_function("!verb.ms")
                await pg.click('#grid .tile[data-id="S2"] .name')
                leiste = await pg.evaluate(LEISTE)
                await b.close()
            return leiste, app.befehle, fehler
        finally:
            bc.cancel()
            await runner.cleanup()

    leiste, befehle, fehler = asyncio.run(lauf())
    assert leiste["sichtbar"] and leiste["blass"] and befehle == [] and not fehler, (leiste, befehle, fehler)


def test_server_weg_und_zurueck():
    """Server beendet (Neustart, Strom): die Leiste nennt ihn, nicht den
    Miniserver, und den Stand der letzten Nachricht. Laeuft er wieder, verbindet
    die Visu von selbst neu, die Leiste geht und Befehle wirken."""
    async def lauf():
        app = _app()
        runner, port, bc = await visu_starten(app)
        fehler, m = [], {}
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _visu(b, port, fehler)
                bc.cancel()
                vorher = time.time()
                # wie beim Beenden des Prozesses: die Verbindungen gehen zu (sonst
                # wartete cleanup() bis zu 60 s auf die offenen WebSockets)
                for w in list(app.conn_route):
                    await w.close()
                await runner.cleanup()
                await pg.wait_for_function("!verb.server")
                await pg.wait_for_timeout(HINWEIS * 1000 + 400)
                m["weg"] = await pg.evaluate(LEISTE)
                m["zeiten"] = await pg.evaluate("[verb.serverSeit, verbBestaetigt]")
                m["vorher"] = vorher
                runner, _, bc = await visu_starten(app, port=port)
                await pg.wait_for_function("verb.server", timeout=10000)
                await pg.wait_for_timeout(500)
                m["zurueck"] = await pg.evaluate(LEISTE)
                await pg.click('#grid .tile[data-id="S2"] .name')
                await pg.wait_for_timeout(300)
                m["befehle"] = list(app.befehle)
                await b.close()
            return m, fehler
        finally:
            bc.cancel()
            await runner.cleanup()

    m, fehler = asyncio.run(lauf())
    seit, bestaetigt = m["zeiten"]
    t = verteilung.VERBINDUNG_TEXTE
    assert m["weg"]["sichtbar"] and m["weg"]["blass"], m
    assert m["weg"]["titel"] == t["server"].replace("{seit}", _uhr(seit)), m
    assert m["weg"]["stand"] == t["stand"].replace("{stand}", _uhr(bestaetigt, True)) + " · " + t["gesperrt"], m
    # bestaetigt vor dem Stopp, "seit" danach (50 ms Spielraum zwischen den Uhren)
    assert bestaetigt <= m["vorher"] * 1000 + 50 and seit >= m["vorher"] * 1000 - 50, m
    assert not m["zurueck"]["sichtbar"] and [u for u, _ in m["befehle"]] == ["S2"] and not fehler, (m, fehler)


def test_stummer_server_wird_neu_verbunden(monkeypatch):
    """Ein Server, der die Verbindung offen haelt, aber nichts mehr schickt,
    wird nach VERBINDUNG_STUMM s aufgegeben und neu verbunden - ohne Leiste,
    weil die neue Verbindung binnen der Frist steht."""
    ersetzen(monkeypatch, "VERBINDUNG_TAKT", 60)
    ersetzen(monkeypatch, "VERBINDUNG_STUMM", 1.5)
    ersetzen(monkeypatch, "VERBINDUNG_HINWEIS", 8)

    async def lauf():
        app = _app()
        runner, port, bc = await visu_starten(app)
        fehler, gesehen, sichtbar = [], set(), []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await _visu(b, port, fehler)
                bc.cancel()                      # ab jetzt schickt der Server nichts mehr
                ende = time.monotonic() + 6
                while time.monotonic() < ende and len(gesehen) < 2:
                    gesehen.update(id(w) for w in app.conn_route)
                    sichtbar.append((await pg.evaluate(LEISTE))["sichtbar"])
                    await asyncio.sleep(0.1)
                await b.close()
            return gesehen, sichtbar, fehler
        finally:
            await runner.cleanup()

    gesehen, sichtbar, fehler = asyncio.run(lauf())
    assert len(gesehen) >= 2, "die Visu hat nicht neu verbunden"
    assert not any(sichtbar) and not fehler, (sichtbar, fehler)
