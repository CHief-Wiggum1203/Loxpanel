"""Ein Strom je Kamera fuer /mjpeg (bin/kamerastrom.py): Der Server holt jede
Kamera nur einmal und verteilt die Bilder an alle Zuschauer, ein langsamer
haelt die anderen nicht auf, nach dem letzten trennt er mit Nachlauf, bricht
die Kamera ab, verbindet er neu. Dazu der Zerleger, der die Teile der Kameras
liest (mit und ohne Content-Length, CRLF oder LF, boundary in vielen Formen).
Kamera und Zuschauer sind Nachbauten (tests/lox.py)."""
import asyncio
import logging
import time

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import kamerastrom
from kamerastrom import MjpegZerleger
from lox import Kamera, mjpeg_bilder, mjpeg_erstes, serve, W

# Ein Bild mit Zeilenumbruechen darin; mit Content-Length darf es auch etwas
# enthalten, das wie die Grenze aussieht
JPEG = b"\xff\xd8\xff\xe0JFIF\r\n\x00\x10\n" + bytes(range(256)) + b"\xff\xd9"
JPEG2 = b"\xff\xd8\xff\xe1" + bytes(range(255, -1, -1)) + b"\xff\xd9"
MIT_GRENZE = JPEG[:-2] + b"\r\n--bild\r\nContent-Type: text/plain\r\n\r\n" + b"\xff\xd9"


def _strom(*teile: bytes, grenze: bytes = b"--bild", nl: bytes = b"\r\n", ende: bool = False) -> bytes:
    """Teile (Kopf und Inhalt schon zusammen) mit Grenzen davor."""
    s = b"".join(grenze + nl + t + nl for t in teile)
    return s + (grenze + b"--" + nl if ende else b"")


def _mit_laenge(bild: bytes, typ: bytes = b"image/jpeg", nl: bytes = b"\r\n") -> bytes:
    return b"Content-Type: " + typ + nl + b"Content-Length: %d" % len(bild) + nl + nl + bild


def _ohne_laenge(bild: bytes, nl: bytes = b"\r\n") -> bytes:
    return b"Content-Type: image/jpeg" + nl + nl + bild


ZERLEGEN = {
    "mit Content-Length, Inhalt mit einer Grenze darin":
        ("multipart/x-mixed-replace; boundary=bild", _strom(_mit_laenge(MIT_GRENZE), _mit_laenge(JPEG)),
         [MIT_GRENZE, JPEG]),
    "ohne Content-Length":
        ("multipart/x-mixed-replace; boundary=bild", _strom(_ohne_laenge(JPEG), _ohne_laenge(JPEG2), ende=True), [JPEG, JPEG2]),
    "nur LF":
        ("multipart/x-mixed-replace;boundary=bild",
         _strom(_ohne_laenge(JPEG, b"\n"), _mit_laenge(JPEG, nl=b"\n"), nl=b"\n"), [JPEG, JPEG]),
    "boundary mit fuehrenden --":
        ("multipart/x-mixed-replace; boundary=--myboundary",
         _strom(_mit_laenge(JPEG), _ohne_laenge(JPEG), grenze=b"--myboundary", ende=True), [JPEG, JPEG]),
    "boundary in Anfuehrungszeichen":
        ('multipart/x-mixed-replace; boundary="frame"; charset=x',
         _strom(_mit_laenge(JPEG), grenze=b"--frame"), [JPEG]),
    "ohne boundary im Content-Type":
        ("multipart/x-mixed-replace", _strom(_ohne_laenge(JPEG), _mit_laenge(JPEG), grenze=b"--abc123"),
         [JPEG, JPEG]),
    "Teil ohne Kopf, gleich das JPEG":
        ("multipart/x-mixed-replace; boundary=bild", _strom(JPEG, JPEG2, ende=True), [JPEG, JPEG2]),
    "leerer Kopf":
        ("multipart/x-mixed-replace; boundary=bild", _strom(b"\r\n" + JPEG, ende=True), [JPEG]),
    "Grenze direkt hinter dem Bild, ohne Zeilenumbruch (so sucht auch Chromium)":
        ("multipart/x-mixed-replace; boundary=bild",
         b"--bild\r\n" + _ohne_laenge(JPEG) + b"--bild\r\n" + _ohne_laenge(JPEG2) + b"--bild--\r\n",
         [JPEG, JPEG2]),
    "Content-Length zu klein: das erste Bild abgeschnitten, ab dann ohne Laenge":
        ("multipart/x-mixed-replace; boundary=bild",
         _strom(*(b"Content-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % (len(JPEG) - 10) + JPEG
                  for _ in range(3)), ende=True), [JPEG[:-10], JPEG, JPEG]),
    "Text vor der ersten Grenze, Abschluss am Ende":
        ("multipart/x-mixed-replace; boundary=bild",
         b"Willkommen\r\n\r\n" + _strom(_mit_laenge(JPEG), _ohne_laenge(JPEG), ende=True), [JPEG, JPEG]),
}


@pytest.mark.parametrize("fall", list(ZERLEGEN))
def test_zerleger(fall):
    """Auf einmal gefuettert und Byte fuer Byte (so zerstueckelt das Netz)
    kommen dieselben Bilder heraus. Ein Teil ohne Content-Length endet erst mit
    der naechsten Grenze, darum schliessen solche Faelle mit der Abschlussgrenze."""
    ctype, strom, soll = ZERLEGEN[fall]
    am_stueck = MjpegZerleger(kamerastrom._boundary(ctype)).futter(strom)
    z = MjpegZerleger(kamerastrom._boundary(ctype))
    einzeln = [b for i in range(len(strom)) for b in z.futter(strom[i:i + 1])]
    assert [d for _, d in am_stueck] == soll
    assert einzeln == am_stueck


def test_zerleger_typ_der_teile():
    strom = _strom(_mit_laenge(JPEG, b"image/png"), _mit_laenge(JPEG, b"<script>"), _ohne_laenge(JPEG), ende=True)
    assert [t for t, _ in MjpegZerleger("bild").futter(strom)] == ["image/png", "image/jpeg", "image/jpeg"]


def test_zerleger_grenzen(monkeypatch):
    """Ein Bild ohne Ende, ein zu grosses Content-Length, ein endloser Kopf oder
    Text ohne Grenze: ValueError, der Strom verbindet dann neu."""
    monkeypatch.setattr(kamerastrom, "BILD_MAX", 1000)
    with pytest.raises(ValueError):
        MjpegZerleger("bild").futter(_strom(b"Content-Type: image/jpeg\r\n\r\n" + b"x" * 2000))
    with pytest.raises(ValueError):
        MjpegZerleger("bild").futter(_strom(b"Content-Length: 5000\r\n\r\n"))
    with pytest.raises(ValueError):
        MjpegZerleger("bild").futter(b"--bild\r\n" + b"X-Lang: " + b"y" * 10000)
    with pytest.raises(ValueError):
        MjpegZerleger("bild").futter(b"z" * 10000)


async def _aufbau(cfg: dict, *, abschalten: bool = False):
    """App mit Kameras (intercom_cfg) und der Route /mjpeg -> (app, ui).
    abschalten: dazu on_shutdown aus webvisu, wie im Betrieb."""
    app = W.App({"host": "", "port": 80})
    app.intercom_cfg = cfg
    ui = web.Application()
    ui["app"] = app
    ui.router.add_get("/mjpeg", W.mjpeg_handler)
    if abschalten:
        ui.on_shutdown.append(W.on_shutdown)
    return app, ui


async def _bilder(cl, uuid: str, n: int) -> list[bytes]:
    """n Bilder aus einer Antwort, danach trennen."""
    r = await cl.get("/mjpeg", params={"id": uuid})
    assert r.status == 200
    out = []
    async for b in mjpeg_bilder(r):
        out.append(b)
        if len(out) == n:
            break
    r.close()
    return out


def _nr(bild: bytes) -> int:
    return int(bild.split()[1].rstrip(b"."))


def test_zwei_zuschauer_ein_strom():
    """Zwei Panels auf derselben Kamera, auch ueber zwei Intercoms mit derselben
    Adresse: ein Abruf bei der Kamera. Ein spaeter Zuschauer beginnt mit einem
    ganzen, frischen Bild, ohne neuen Abruf."""
    async def lauf():
        cam = await Kamera().start()
        app, ui = await _aufbau({"A": {"url": cam.adresse("/tuer")}, "B": {"url": cam.adresse("/tuer")}})
        try:
            async with TestClient(TestServer(ui)) as cl:
                a, b = await asyncio.gather(_bilder(cl, "A", 5), _bilder(cl, "B", 5))
                spaet = await mjpeg_erstes(cl, "A")
                return a, b, spaet, list(cam.abrufe), max(cam.offen.values())
        finally:
            await app.close()
            await cam.stop()
    a, b, spaet, abrufe, offen = asyncio.run(lauf())
    assert abrufe == ["/tuer"] and offen == 1
    for bilder in (a, b):
        nummern = [_nr(x) for x in bilder]
        assert nummern == sorted(nummern) and len(set(nummern)) == 5, nummern
    assert spaet[0] == 200 and _nr(spaet[1]) >= max(_nr(x) for x in a)


def test_langsamer_zuschauer_haelt_niemanden_auf():
    """Ein Panel liest nicht weiter (WLAN weg, Tab im Hintergrund): Das andere
    bekommt seine Bilder trotzdem, und das langsame springt danach zum
    neuesten, statt alte Bilder nachzuholen."""
    async def lauf():
        cam = await Kamera(groesse=256 * 1024, takt=0.005).start()
        app, ui = await _aufbau({"A": {"url": cam.adresse("/a")}})
        try:
            async with TestClient(TestServer(ui)) as cl:
                langsam = await cl.get("/mjpeg", params={"id": "A"})      # angemeldet, liest aber nicht
                beginn = time.monotonic()
                schnell = await asyncio.wait_for(_bilder(cl, "A", 150), 30)
                dauer = time.monotonic() - beginn
                nummern = []
                async for bild in mjpeg_bilder(langsam):
                    nummern.append(_nr(bild))
                    if len(nummern) > 1 and nummern[-1] - nummern[-2] > 1 or len(nummern) == 400:
                        break
                langsam.close()
                return schnell, dauer, nummern, list(cam.abrufe)
        finally:
            await app.close()
            await cam.stop()
    schnell, dauer, nummern, abrufe = asyncio.run(lauf())
    assert len(schnell) == 150 and dauer < 30
    assert nummern == sorted(nummern), nummern
    assert any(b - a > 1 for a, b in zip(nummern, nummern[1:])), "das langsame Panel ueberspringt Bilder"
    assert abrufe == ["/a"]


def test_nach_dem_letzten_zuschauer_trennt_er(monkeypatch):
    """Nach dem letzten Zuschauer haelt der Strom noch NACHLAUF_S (ein Wechsel
    der Seite holt ihn ohne neuen Abruf zurueck), dann trennt er."""
    monkeypatch.setattr(kamerastrom, "NACHLAUF_S", 0.3)

    async def lauf():
        cam = await Kamera().start()
        app, ui = await _aufbau({"A": {"url": cam.adresse("/a")}})
        try:
            async with TestClient(TestServer(ui)) as cl:
                await mjpeg_erstes(cl, "A")
                await asyncio.sleep(0.1)
                im_nachlauf = cam.offen["/a"]
                await mjpeg_erstes(cl, "A")
                abrufe = len(cam.abrufe)
                await asyncio.sleep(0.8)
                return im_nachlauf, abrufe, cam.offen["/a"], app.kamerastroeme.anzahl()
        finally:
            await app.close()
            await cam.stop()
    assert asyncio.run(lauf()) == (1, 1, 0, 0)


def test_bricht_die_kamera_ab_verbindet_er_neu(monkeypatch):
    """Die Kamera beendet ihren Strom nach drei Bildern: Der Server verbindet
    neu, der Zuschauer bleibt in derselben Antwort und bekommt weiter Bilder."""
    monkeypatch.setattr(kamerastrom, "PAUSE_MIN_S", 0.05)

    async def lauf():
        cam = await Kamera(abbruch_nach=3).start()
        app, ui = await _aufbau({"A": {"url": cam.adresse("/a")}})
        try:
            async with TestClient(TestServer(ui)) as cl:
                bilder = await asyncio.wait_for(_bilder(cl, "A", 10), 10)
                return [_nr(b) for b in bilder], len(cam.abrufe)
        finally:
            await app.close()
            await cam.stop()
    nummern, abrufe = asyncio.run(lauf())
    assert nummern == list(range(1, 11))
    assert abrufe >= 4


def test_ist_die_kamera_weg(monkeypatch):
    """Geht die Kamera vom Netz, bekommt ein neuer Zuschauer das letzte Bild,
    solange es frisch ist; danach 502 wie bisher, wenn sie nicht erreichbar ist."""
    monkeypatch.setattr(kamerastrom, "BILD_FRISCH_S", 0.5)
    monkeypatch.setattr(kamerastrom, "PAUSE_MIN_S", 0.05)

    async def lauf():
        cam = await Kamera().start()
        app, ui = await _aufbau({"A": {"url": cam.adresse("/a")}})
        try:
            async with TestClient(TestServer(ui)) as cl:
                erster = await cl.get("/mjpeg", params={"id": "A"})
                letztes = await anext(mjpeg_bilder(erster))
                await cam.stop()
                gleich = await mjpeg_erstes(cl, "A")
                await asyncio.sleep(0.8)
                spaeter = await mjpeg_erstes(cl, "A")
                erster.close()
                return letztes, gleich, spaeter
        finally:
            await app.close()
    letztes, gleich, spaeter = asyncio.run(lauf())
    assert gleich[0] == 200 and _nr(gleich[1]) >= _nr(letztes)
    assert spaeter == (502, b"camera unreachable")


def test_kamera_wieder_da_waehrend_der_pause(monkeypatch):
    """Ist die Kamera eine Weile weg, wartet der Strom immer laenger bis zum
    naechsten Versuch. Kommt sie zurueck, darf ein neuer Zuschauer nicht bis
    zum Ende der Pause 502 bekommen: Er kuerzt sie ab und wartet auf den
    Versuch von jetzt (bisher machte jeder Abruf einen eigenen)."""
    monkeypatch.setattr(kamerastrom, "BILD_FRISCH_S", 0.1)
    monkeypatch.setattr(kamerastrom, "PAUSE_MIN_S", 60)

    async def lauf():
        cam = await Kamera().start()
        app, ui = await _aufbau({"A": {"url": cam.adresse("/a")}})
        try:
            async with TestClient(TestServer(ui)) as cl:
                erster = await cl.get("/mjpeg", params={"id": "A"})
                await anext(mjpeg_bilder(erster))
                await cam.stop()
                await asyncio.sleep(0.3)                     # Strom abgerissen, Bild nicht mehr frisch
                weg = await mjpeg_erstes(cl, "A")             # kuerzt ab, Versuch scheitert, jetzt 60 s Pause
                cam = await Kamera().start(cam.port)          # dieselbe Kamera ist wieder da
                beginn = time.monotonic()
                wieder = await mjpeg_erstes(cl, "A")
                dauer = time.monotonic() - beginn
                erster.close()
                return weg, wieder, dauer
        finally:
            await app.close()
            await cam.stop()
    weg, wieder, dauer = asyncio.run(lauf())
    assert weg == (502, b"camera unreachable")
    assert wieder[0] == 200 and wieder[1].startswith(b"/a ") and dauer < 5, (wieder, dauer)


def test_langsame_kamera_zeigt_ihr_letztes_bild_sofort(monkeypatch):
    """Schickt die Kamera selten ein Bild, sieht ein neuer Zuschauer trotzdem
    sofort das letzte: Solange ihr Strom laeuft, ist es das aktuelle, auch wenn
    es aelter als BILD_FRISCH_S ist."""
    monkeypatch.setattr(kamerastrom, "BILD_FRISCH_S", 0.2)

    async def lauf():
        cam = await Kamera(takt=3).start()
        app, ui = await _aufbau({"A": {"url": cam.adresse("/a")}})
        try:
            async with TestClient(TestServer(ui)) as cl:
                erster = await cl.get("/mjpeg", params={"id": "A"})
                await anext(mjpeg_bilder(erster))
                await asyncio.sleep(0.5)
                beginn = time.monotonic()
                zweiter = await mjpeg_erstes(cl, "A")
                dauer = time.monotonic() - beginn
                erster.close()
                return zweiter, dauer
        finally:
            await app.close()
            await cam.stop()
    zweiter, dauer = asyncio.run(lauf())
    assert zweiter == (200, b"/a 1") and dauer < 1, (zweiter, dauer)


def test_ablehnung_ist_endgueltig(monkeypatch):
    """Ein falsches Kennwort (401) wird nicht wiederholt, auch nicht im
    Nachlauf: Manche Kameras sperren nach Fehlanmeldungen die Adresse, dann
    auch fuer den richtigen Zugang. Lehnt die Kamera beim Neuverbinden eines
    laufenden Stroms ab (Kennwort an der Kamera geaendert), versucht er es
    einmal und entlaesst seine Zuschauer."""
    monkeypatch.setattr(kamerastrom, "PAUSE_MIN_S", 0.02)

    async def lauf():
        cam = await Kamera(anmeldung=("tuer", "geheim"), abbruch_nach=2, takt=0.3).start()
        app, ui = await _aufbau({"A": {"url": cam.adresse("/a"), "user": "tuer", "pass": "falsch"},
                                 "B": {"url": cam.adresse("/b"), "user": "tuer", "pass": "geheim"}})
        try:
            async with TestClient(TestServer(ui)) as cl:
                falsch = await mjpeg_erstes(cl, "A")
                await asyncio.sleep(0.5)
                r = await cl.get("/mjpeg", params={"id": "B"})
                bilder = mjpeg_bilder(r)
                erstes = await anext(bilder)
                cam.anmeldung = ("tuer", "neu")              # an der Kamera geaendert
                rest = await asyncio.wait_for(_alle(bilder), 5)   # die Antwort endet
                await asyncio.sleep(0.3)
                return falsch, erstes, rest, list(cam.abrufe), app.kamerastroeme.anzahl()
        finally:
            await app.close()
            await cam.stop()
    falsch, erstes, rest, abrufe, stroeme = asyncio.run(lauf())
    assert falsch == (502, b"camera status 401")
    assert erstes == b"/b 1" and rest == [b"/b 2"]
    assert abrufe == ["/a", "/b", "/b"] and stroeme == 0


async def _alle(bilder) -> list[bytes]:
    return [b async for b in bilder]


def test_kein_mjpeg_beim_neuverbinden(monkeypatch):
    """Antwortet die Kamera beim Neuverbinden einmal ohne multipart (etwa eine
    Fehlerseite unter Last), zaehlt das wie ein Abriss: Die Zuschauer bleiben
    verbunden, bekommen die Seite nicht als Bild und danach wieder Bilder."""
    monkeypatch.setattr(kamerastrom, "PAUSE_MIN_S", 0.05)
    cam = Kamera(abbruch_nach=2, takt=0.05)
    cam.inhalt = lambda pfad, n: b"SEITE" if cam.einzelbild else b"%s %d" % (pfad.encode(), n)

    async def lauf():
        await cam.start()
        app, ui = await _aufbau({"A": {"url": cam.adresse("/a")}})
        try:
            async with TestClient(TestServer(ui)) as cl:
                r = await cl.get("/mjpeg", params={"id": "A"})
                bilder = mjpeg_bilder(r)
                gesehen = [await anext(bilder), await anext(bilder)]
                cam.einzelbild = True                         # der naechste Abruf: keine multipart-Antwort
                await asyncio.sleep(0.3)
                cam.einzelbild = False
                for _ in range(3):
                    gesehen.append(await asyncio.wait_for(anext(bilder), 5))
                r.close()
                return gesehen, len(cam.abrufe)
        finally:
            await app.close()
            await cam.stop()
    gesehen, abrufe = asyncio.run(lauf())
    assert all(b.startswith(b"/a ") for b in gesehen) and len(gesehen) == 5, gesehen
    assert abrufe >= 3


def test_ein_bild_je_verbindung(monkeypatch, caplog):
    """Eine Kamera, die je Verbindung ein Bild schickt und schliesst: Die Pause
    vor dem naechsten Versuch waechst trotzdem (sonst ein Abruf je Sekunde),
    und das Log bleibt leer ("getrennt" nur nach einem Strom, der LAUF_MIN_S
    lief; sonst schriebe die Kamera Log und Diagnosepaket voll)."""
    monkeypatch.setattr(kamerastrom, "PAUSE_MIN_S", 0.05)
    caplog.set_level(logging.INFO, logger="loxpanel.webvisu")

    async def lauf():
        cam = await Kamera(abbruch_nach=1).start()
        app, ui = await _aufbau({"A": {"url": cam.adresse("/a")}})
        try:
            async with TestClient(TestServer(ui)) as cl:
                r = await cl.get("/mjpeg", params={"id": "A"})
                await asyncio.sleep(1.6)
                r.close()
                return len(cam.abrufe)
        finally:
            await app.close()
            await cam.stop()
    abrufe = asyncio.run(lauf())
    # Pausen 0,05 + 0,1 + 0,2 + 0,4 + 0,8 s: in 1,6 s etwa fuenf Abrufe, bei fester Pause ueber zwanzig
    assert 3 <= abrufe <= 7, abrufe
    assert "getrennt" not in caplog.text


def test_nach_dem_herunterfahren_kein_neuer_strom():
    """Ein Abruf, der erst nach on_shutdown ankommt (etwa noch beim Miniserver
    nach der Kamera gefragt), bekommt keinen Strom mehr: Den beendete niemand,
    und aiohttp wartete auf ihn."""
    async def lauf():
        verteiler = kamerastrom.Kameraverteiler()
        await verteiler.schliessen()
        return verteiler.anmelden({"url": "http://127.0.0.1:9/a"}), verteiler.anzahl()
    assert asyncio.run(lauf()) == (None, 0)


def test_einzelbild_wie_bisher():
    """Schickt die Kamera ein Einzelbild statt eines Stroms (snap.jpeg), geht es
    unveraendert durch, und jeder Abruf holt ein neues."""
    async def lauf():
        cam = await Kamera(einzelbild=True).start()
        app, ui = await _aufbau({"A": {"url": cam.adresse("/snap.jpeg")}})
        try:
            async with TestClient(TestServer(ui)) as cl:
                out = []
                for _ in range(2):
                    r = await cl.get("/mjpeg", params={"id": "A"})
                    out.append((r.status, r.headers["Content-Type"], await r.read()))
                return out, len(cam.abrufe), app.kamerastroeme.anzahl()
        finally:
            await app.close()
            await cam.stop()
    out, abrufe, stroeme = asyncio.run(lauf())
    assert out == [(200, "image/jpeg", b"/snap.jpeg 1"), (200, "image/jpeg", b"/snap.jpeg 2")]
    assert abrufe == 2 and stroeme == 0


def test_status_der_kamera():
    """Lehnt die Kamera ab oder ist sie nicht da: 502 mit dem Grund."""
    async def lauf():
        cam = await Kamera(anmeldung=("tuer", "geheim")).start()
        frei, frei_port = await serve(web.Application())
        await frei.cleanup()                                   # dort lauscht niemand mehr
        app, ui = await _aufbau({"A": {"url": cam.adresse("/a")},
                                 "B": {"url": cam.adresse("/a"), "user": "tuer", "pass": "geheim"},
                                 "C": {"url": f"http://127.0.0.1:{frei_port}/x"}})
        try:
            async with TestClient(TestServer(ui)) as cl:
                return [(await mjpeg_erstes(cl, i)) for i in ("A", "B", "C")]
        finally:
            await app.close()
            await cam.stop()
    assert asyncio.run(lauf()) == [(502, b"camera status 401"), (200, b"/a 1"), (502, b"camera unreachable")]


def test_zu_viele_zuschauer(monkeypatch):
    """Je Kamera hoechstens ZUSCHAUER_MAX (docs/ARCHITEKTUR.md, S6), dann 503;
    geht einer, kommt der naechste wieder an."""
    monkeypatch.setattr(kamerastrom, "ZUSCHAUER_MAX", 2)

    async def lauf():
        cam = await Kamera().start()
        app, ui = await _aufbau({"A": {"url": cam.adresse("/a")}})
        try:
            async with TestClient(TestServer(ui)) as cl:
                zwei = [await cl.get("/mjpeg", params={"id": "A"}) for _ in range(2)]
                dritter = (await cl.get("/mjpeg", params={"id": "A"})).status
                zwei[0].close()
                await asyncio.sleep(kamerastrom.PRUEF_S + 0.5)    # bis der Server es merkt
                wieder = await mjpeg_erstes(cl, "A")
                zwei[1].close()
                return [r.status for r in zwei], dritter, wieder[0]
        finally:
            await app.close()
            await cam.stop()
    assert asyncio.run(lauf()) == ([200, 200], 503, 200)


def test_herunterfahren_beendet_die_stroeme():
    """Beim Herunterfahren beendet on_shutdown die offenen Kamerastroeme. Sonst
    endet eine /mjpeg-Antwort nie von selbst, und aiohttp wartete 60 s."""
    async def lauf():
        cam = await Kamera().start()
        app, ui = await _aufbau({"A": {"url": cam.adresse("/a")}}, abschalten=True)
        runner, port = await serve(ui)
        try:
            async with aiohttp.ClientSession() as sess:
                r = await sess.get(f"http://127.0.0.1:{port}/mjpeg", params={"id": "A"})
                await anext(mjpeg_bilder(r))
                beginn = time.monotonic()
                await runner.cleanup()
                dauer = time.monotonic() - beginn
                rest = [b async for b in mjpeg_bilder(r)]   # die Antwort endet
                await asyncio.sleep(0.2)
                return dauer, cam.offen["/a"], app.kamerastroeme.anzahl(), len(rest) < 100
        finally:
            await app.close()
            await cam.stop()
    dauer, offen, stroeme, endet = asyncio.run(lauf())
    assert dauer < 5 and offen == 0 and stroeme == 0 and endet
