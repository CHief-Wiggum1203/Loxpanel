"""Ersteinrichtung in Chromium: Ein Panel, dessen Server noch keine Struktur
vom Miniserver hat, zeigt ueber der Uhr-Seite, wo der Konfigurator zu oeffnen
ist - bei 127.0.0.1 (App auf dem Panel) mit der Adresse des Servers im Netz.
Ein Fehlertext bleibt Text; mit der Struktur verschwindet die Karte."""
import asyncio

import pytest

from lox import W, anlage, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = pytest.mark.browser

BAUSTEINE = {"L": {"name": "Licht", "type": "Switch", "uuidAction": "L", "room": "r1", "cat": "c1",
                   "isFavorite": True, "states": {"active": "l"}}}


def test_karte_bis_die_struktur_da_ist(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "_lan_adressen", lambda: ["192.168.1.37"])

    async def lauf():
        app = W.App({"host": "", "port": 443})
        runner, port, bc = await visu_starten(app)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 480, "height": 480})
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/?panel=default")
                await pg.wait_for_selector("#einrichtung:not(.hidden)", timeout=5000)
                await pg.screenshot(path=str(tmp_path / "einrichtung.png"))
                frisch = await pg.inner_text("#einrichtung")
                ebenen = await pg.evaluate("""() => {
                    const z = id => +getComputedStyle(document.getElementById(id)).zIndex;
                    const r = document.getElementById('einrichtung').getBoundingClientRect();
                    return {karte: z('einrichtung'), uhr: z('saver'),
                            uhrSichtbar: !document.getElementById('saver').classList.contains('hidden'),
                            imBild: r.top >= 0 && r.bottom <= innerHeight && r.height > 0}; }""")
                fremd = await pg.evaluate("""einrichtungsUrls({hostname: '10.0.0.9', host: '10.0.0.9:8099',
                                              port: '8099', protocol: 'http:'},
                                             {pfad: '/config', adressen: ['192.168.1.37']})""")
                # Zugang eingetragen, Versuch gescheitert: der Fehler kommt als Text an
                app.host, app._ms_fehler = "10.0.0.5", "<img src=x onerror=alert(1)>"
                await pg.wait_for_function("document.getElementById('einrichtung').textContent"
                                           ".includes('Keine Verbindung')")
                gescheitert = await pg.inner_text("#einrichtung")
                bilder = await pg.locator("#einrichtung img").count()
                app._apply_structure(anlage(BAUSTEINE))
                await pg.wait_for_selector("#einrichtung.hidden", state="attached", timeout=5000)
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
        assert not fehler, fehler
        return frisch, ebenen, fremd, gescheitert, bilder, port
    frisch, ebenen, fremd, gescheitert, bilder, port = asyncio.run(lauf())

    assert frisch.split("\n") == [
        "Miniserver einrichten", "Noch kein Miniserver eingetragen.",
        "Konfigurator im Browser eines Computers oder Handys im selben Netz öffnen:",
        f"http://192.168.1.37:{port}/config"]
    assert ebenen["uhrSichtbar"] and ebenen["karte"] > ebenen["uhr"] and ebenen["imBild"], ebenen
    assert fremd == ["http://10.0.0.9:8099/config"], "ueber eine echte Adresse geladen: diese"
    assert "10.0.0.5: <img src=x onerror=alert(1)>" in gescheitert and bilder == 0
