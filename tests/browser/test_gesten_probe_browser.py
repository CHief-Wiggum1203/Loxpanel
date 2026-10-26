"""Gesten ausprobieren (Vorgaben -> Verhalten) in Chromium: neben der Karte
Gesten steht die echte Visu einer Ansicht auf der Seite eines Raums, die Maus
spielt dort zwei Finger.

Geprueft: Die Spalten der Gesten stehen ueber der Seite. Links runter zieht
die Jalousie als Vorhang bis „Geschlossen“, im Probelauf kommt am
Miniserver-Nachbau nichts an, die Liste nennt die Befehle mit Namen. Ein
ungespeicherter Taster fuer „Raum verlassen“ gilt in der Probe sofort
(Doppelklick). Ist der Entwurf weg (abgelaufen, Server neu gestartet), legt
die Karte die Probe neu an. Mit „Wirklich schalten“ ist das Bild gesperrt,
bis die Visu den Modus bestaetigt, dann gehen die Befehle raus (Klick links:
beschatten). Tasten unter der Maus (Player) sehen sie nicht.
Anlage: lox.gesten_anlage()."""
import asyncio

import pytest

from lox import KONFIGURATOR_GELADEN, Miniserver, W, gesten_anlage, neue_app, visu_starten

pytest.importorskip("playwright.async_api", reason="Playwright fehlt (requirements-dev.txt)")
from playwright.async_api import async_playwright  # noqa: E402

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("miniserver_http")]

ROUTEN = [("POST", "/api/entwurf", W.api_entwurf)]
EINBLENDUNG = """() => { const n = document.getElementById('geste');
  return n && !n.classList.contains('hidden') ? [n.className, n.querySelector('.gs-wert').textContent,
    n.querySelector('.gs-sub').textContent] : null; }"""


async def _neu_geladen(fr):
    """Warten, bis die Visu im Fenster der Probe neu geladen hat (die Marke
    von vorher ist weg) und ihre Kacheln wieder stehen."""
    for _ in range(100):
        try:
            if await fr.evaluate("typeof window.__vorher === 'undefined' && !!document.querySelector('#grid .tile[data-id]')"):
                return
        except Exception:   # waehrend der Navigation gibt es keinen Kontext
            pass
        await asyncio.sleep(0.1)
    raise AssertionError("die Visu der Probe hat nicht neu geladen")


async def _ziehen(pg, box, x_anteil, y0, y1, schritte=10):
    x = box["x"] + box["width"] * x_anteil
    await pg.mouse.move(x, box["y"] + box["height"] * y0)
    await pg.mouse.down()
    for i in range(1, schritte + 1):
        await pg.mouse.move(x, box["y"] + box["height"] * (y0 + (y1 - y0) * i / schritte))
        await asyncio.sleep(0.03)
    await pg.mouse.up()


def test_gesten_probe(tmp_path):
    async def lauf():
        ms = Miniserver()
        await ms.start()
        app = neue_app(ms)
        struktur, states = gesten_anlage()
        app._apply_structure(struktur)
        app.states = states
        app.panels = W.App._sanitize_panels({"test": {"title": "Küche", "tabs": ["favoriten", "raeume"],
                                                      "ui": {"split": False}}})
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1500, "height": 950}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator(".rub", has_text="Vorgaben").click()
                await pg.locator(".stab[data-sub='verhalten']").click()
                await pg.select_option("#gpAnsicht", "test")
                await pg.select_option("#gpRaum", "r1")
                await pg.wait_for_function("GP.url && GP.gesendet.includes('room:r1') && GP.bestaetigt === false")
                # das Fenster steht auf der Adresse der Probe und zeigt Kacheln
                await pg.wait_for_function("""() => { const f = document.querySelector('#gpFrame'), d = f.contentDocument;
                  return !!d && f.contentWindow.location.search.includes('entwurf=')
                    && !!d.querySelector('#grid .tile[data-id]'); }""")
                rahmen = await (await pg.query_selector("#gpFrame")).content_frame()
                spalten = await rahmen.eval_on_selector_all("#gesteSpalten .gp-name", "l => l.map(n => n.textContent)")
                modus = await pg.locator("#gpModus").text_content()

                await pg.locator("#gpVor").scroll_into_view_if_needed()
                box = await pg.locator("#gpVor").bounding_box()
                await _ziehen(pg, box, 0.15, 0.3, 0.7)
                await rahmen.wait_for_function(
                    "(() => { const n = document.getElementById('geste');"
                    " return n && n.querySelector('.gs-sub').textContent === 'Geschlossen'; })()")
                vorhang = await rahmen.evaluate(EINBLENDUNG)
                await pg.screenshot(path=str(tmp_path / "gesten_probe_jalousie.png"))
                await pg.wait_for_function("document.querySelectorAll('#gpListe .gp-befehle li').length >= 2")
                liste_jal = await pg.locator("#gpListe .gp-geste").first.inner_text()
                probelauf = list(ms.io)

                # Taster fuer "Raum verlassen", nicht gespeichert: gilt in der Probe sofort
                await rahmen.evaluate("window.__vorher = 1")
                await pg.locator("[data-gv-raum='r1']").select_option("TV")
                await _neu_geladen(rahmen)
                await pg.wait_for_timeout(300)
                box = await pg.locator("#gpVor").bounding_box()
                x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                await pg.mouse.click(x, y)
                await asyncio.sleep(0.1)
                await pg.mouse.click(x, y)
                await pg.wait_for_function("(GP.gesten[0] || {}).art === 'verlassen' && GP.gesten[0].befehle.length > 0")
                verlassen = await pg.evaluate("GP.gesten[0]")
                nach_doppel = list(ms.io)

                # Entwurf weg (abgelaufen, Server neu gestartet): die Visu bleibt ein
                # Probelauf, meldet es, und die Karte legt die Probe neu an
                alter_token = await pg.evaluate("GP.token")
                app.entwuerfe.clear()
                await rahmen.evaluate("setTimeout(() => location.reload(), 0)")
                await pg.wait_for_function(f"GP.token && GP.token !== '{alter_token}' && GP.bestaetigt === false")
                await _neu_geladen(rahmen)
                neu_angelegt = (await pg.evaluate("GP.token"), rahmen.url)
                await rahmen.evaluate("window.__vorher = 1")

                # Wirklich schalten: bis die Visu im neuen Modus verbunden ist, ist
                # das Bild gesperrt; dann beschattet ein Klick links
                await rahmen.evaluate("window.__vorher = 1")
                await pg.locator("#gpSchalten").check()
                gesperrt = await pg.evaluate("document.querySelector('#gpVor').classList.contains('gesperrt')")
                await _neu_geladen(rahmen)
                await pg.wait_for_function("GP.bestaetigt === true && !document.querySelector('#gpVor.gesperrt')")
                await pg.wait_for_timeout(300)
                await pg.mouse.click(box["x"] + box["width"] * 0.15, y)
                for _ in range(60):
                    if len(ms.io) >= 2:
                        break
                    await asyncio.sleep(0.05)
                await pg.wait_for_timeout(300)
                await pg.locator("#gpKarte").screenshot(path=str(tmp_path / "gesten_probe_karte.png"))
                modus_scharf = await pg.locator("#gpModus").text_content()
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
            await app.icon_session.close()
            await ms.stop()
        assert not fehler, fehler
        return (spalten, modus, vorhang, liste_jal, probelauf, verlassen, nach_doppel, list(ms.io), modus_scharf,
                gesperrt, neu_angelegt)

    (spalten, modus, vorhang, liste_jal, probelauf, verlassen, nach_doppel, io, modus_scharf,
     gesperrt, (token, url)) = asyncio.run(lauf())
    assert f"entwurf={token}&probe=1" in url, (token, url)
    assert gesperrt, "nach dem Umschalten ist das Bild gesperrt, bis die Visu den Modus bestaetigt"
    assert spalten == ["Beschattung", "Licht", "Musik"]
    assert modus.startswith("Probelauf") and "Gesten aus" in modus, modus   # in der Ansicht aus: Hinweis
    assert "vorhang" in vorhang[0] and vorhang[1].replace(" ", " ").strip() == "100 %", vorhang
    assert "Jalousie Terrasse" in liste_jal and "Jalousie Küche" in liste_jal and "FullDown" in liste_jal, liste_jal
    assert "links · hoch/runter wischen" in liste_jal, liste_jal
    assert probelauf == [] and nach_doppel == [], "der Probelauf schickt nichts"
    assert verlassen["befehle"] == [{"name": "EKW verlassen", "befehl": "pulse"}], verlassen
    assert verlassen["bewegung"] == "doppel" and verlassen["text"] == "Essen-Kochen-Wohnen verlassen", verlassen
    assert io == ["sps/io/J1/shade", "sps/io/J2/shade"], io
    assert modus_scharf.startswith("Schaltet wirklich"), modus_scharf


def test_probe_faengt_tasten_ab():
    """Die Maus geht an die Geste, bevor eine Taste darunter sie sieht: Die
    Lautstaerke-Taste des Players schickt schon beim Druecken einen Befehl;
    in der Probe wird daraus ein Tipp rechts (Wiedergabe), die Visu schickt
    kein t:"cmd", und im Probelauf kommt am Miniserver nichts an."""
    async def lauf():
        ms = Miniserver()
        await ms.start()
        app = neue_app(ms)
        struktur, states = gesten_anlage()
        app._apply_structure(struktur)
        app.states = states
        app.panels = W.App._sanitize_panels({"test": {"title": "Küche", "tabs": ["room:r1"],
                                                      "ui": {"grid": "auto", "panes": {"room:r1": "player:AZ"}}}})
        runner, port, bc = await visu_starten(app, ROUTEN)
        fehler = []
        try:
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page(viewport={"width": 1500, "height": 950}, locale="de-DE")
                pg.on("pageerror", lambda e: fehler.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/config")
                await pg.wait_for_function(KONFIGURATOR_GELADEN)
                await pg.locator(".rub", has_text="Vorgaben").click()
                await pg.locator(".stab[data-sub='verhalten']").click()
                geraete = await pg.eval_on_selector_all("#gpGeraet option", "l => l.map(o => o.value)")
                await pg.select_option("#gpGeraet", next(g for g in geraete if "Galaxy Tab A9 quer" in g))
                await pg.select_option("#gpAnsicht", "test")
                await pg.select_option("#gpRaum", "r1")
                await pg.wait_for_function("GP.url && GP.gesendet.includes('room:r1') && GP.bestaetigt === false")
                rahmen = await (await pg.query_selector("#gpFrame")).content_frame()
                knopf = rahmen.locator(".ppvol .sbtn[data-sd='up']")
                await knopf.wait_for(state="visible")
                await rahmen.evaluate("""() => { window.__gesendet = []; const s0 = window.send;
                  window.send = m => { window.__gesendet.push(m); s0(m); }; }""")
                await pg.locator("#gpVor").scroll_into_view_if_needed()
                bb = await knopf.bounding_box()
                await pg.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
                await pg.mouse.down()
                await asyncio.sleep(0.2)
                await pg.mouse.up()
                await pg.wait_for_function("(GP.gesten[0] || {}).art === 'wiedergabe'")
                await pg.wait_for_timeout(500)
                gesendet = await rahmen.evaluate("""window.__gesendet.filter(m => m.t === 'cmd' || m.t === 'geste')
                  .map(m => m.t + ':' + (m.art || m.cmd || ''))""")
                await b.close()
        finally:
            bc.cancel()
            await runner.cleanup()
            await app.icon_session.close()
            await ms.stop()
        assert not fehler, fehler
        return gesendet, list(ms.io)

    gesendet, io = asyncio.run(lauf())
    assert gesendet == ["geste:wiedergabe"], gesendet
    assert io == []
