"""Front (Kalender + Wetter): wie oft der Kalender aus dem Netz geholt wird
und welche Termine aus dem Abo aufs Panel kommen.

Anlass: Jede Wetter-Aenderung des Miniservers lud die Front samt Kalender neu,
und jeder Durchgang fragte iCloud viermal in 38 s an, obwohl iCloud mit 503 und
`Retry-After: 60` um Pause bat. Am Tower waren das 1823 Abrufe in 30 Stunden,
und iCloud hielt die Sperre so lange aufrecht, wie LoxPanel nachfragte.

Zweiter Anlass: Ein einzeln verschobener Serientermin stand doppelt da, am
alten und am neuen Platz. Google und iCloud schicken ihn als eigenes VEVENT
mit derselben UID und einer RECURRENCE-ID auf das urspruengliche Auftreten.
"""
import asyncio
import contextlib
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiohttp
import pytest
from aiohttp import web
from icalendar import Calendar

from lox import W, serve

front_info = W.front_info
QUELLE = {"name": "Familie", "url": "https://kalender.invalid/familie.ics", "color": "#e0a24d"}


def _termin(quelle: dict) -> dict:
    return {"day": "Sa 26.9.", "date": "2099-09-26", "time": "18:00", "title": "Termin",
            "note": "", "allday": False, "cal": quelle["name"], "color": quelle["color"],
            "ck": quelle["key"]}


async def _bis(bedingung, sekunden: float = 3.0) -> None:
    ende = time.monotonic() + sekunden
    while not bedingung():
        if time.monotonic() > ende:
            raise AssertionError("Zustand nicht erreicht")
        await asyncio.sleep(0.005)


@pytest.fixture
def abrufe(monkeypatch) -> list:
    """Kalenderabrufe mitzaehlen statt ins Netz zu gehen."""
    liste = []

    async def abruf(session, url, days, quelle=None):
        liste.append(url)
        return [_termin(quelle)]
    monkeypatch.setattr(front_info, "fetch_events", abruf)
    return liste


@contextlib.asynccontextmanager
async def _front(wetter: dict):
    """App mit einem Kalender-Abo und Wetter vom Loxone-Wetterserver, front_task laeuft."""
    app = W.App({"host": "", "port": 80})
    app.calendar_cfg = {"sources": [dict(QUELLE)]}
    app._loxone_weather = lambda: dict(wetter)
    task = asyncio.create_task(app.front_task())
    try:
        await _bis(lambda: app._front is not None)
        yield app
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def test_wetter_push_ruft_kalender_nicht_ab(abrufe):
    async def lauf():
        wetter = {"temp": 5.0}
        async with _front(wetter) as app:
            assert len(abrufe) == 1 and app._front["events"]
            takt = getattr(app, "_front_cal_due", None)
            for i in range(20):                     # der Miniserver schickt neues Wetter
                wetter["temp"] = 6.0 + i
                app._on_weather("wetter-aktuell", [{"temperature": 6.0 + i}])
                await _bis(lambda: app._front["weather"]["temp"] == wetter["temp"])
            assert len(abrufe) == 1, f"{len(abrufe)} Kalenderabrufe durch Wetter-Pushes"
            assert app._front["events"], "Termine gingen beim Tausch des Wetters verloren"
            assert app._wx_source == "miniserver"
            assert app._front_cal_due == takt, "Wetter-Pushes schieben den Kalendertakt hinaus"

            app._front_cal_due = 0.0                # Takt abgelaufen: jetzt wieder holen
            app._on_weather("wetter-aktuell", [{"temperature": 99.0}])
            await _bis(lambda: len(abrufe) == 2)
    asyncio.run(lauf())


def test_unbrauchbares_wetter_laesst_letzten_stand_stehen(abrufe):
    async def lauf():
        async with _front({"temp": 5.0}) as app:
            app._loxone_weather = lambda: None     # Wetterserver liefert gerade nichts
            app._on_weather("wetter-aktuell", [{"temperature": 1.0}])
            await _bis(lambda: not app._front_refresh.is_set())
            assert app._front["weather"] == {"temp": 5.0}
            assert app._wx_source == "miniserver" and len(abrufe) == 1
    asyncio.run(lauf())


def test_nach_wetter_push_nur_restzeit_warten(abrufe, monkeypatch):
    echt, zeiten = asyncio.wait_for, []

    async def warte(aw, timeout):
        zeiten.append(timeout)
        return await echt(aw, timeout)

    async def lauf():
        async with _front({"temp": 5.0}) as app:
            await _bis(lambda: zeiten)
            assert zeiten[-1] == pytest.approx(W.FRONT_INTERVAL, abs=5)
            app._front_cal_due = time.monotonic() + 30   # Kalender in 30 s wieder faellig
            vorher = len(zeiten)
            app._on_weather("wetter-aktuell", [{"temperature": 7.0}])
            await _bis(lambda: len(zeiten) > vorher)
            assert zeiten[-1] <= 30, f"wartet {zeiten[-1]:.0f} s statt der Restzeit"
            assert len(abrufe) == 1
    monkeypatch.setattr(asyncio, "wait_for", warte)
    asyncio.run(lauf())


def test_speichern_holt_kalender_sofort(abrufe, monkeypatch):
    gespeichert: dict = {}
    monkeypatch.setattr(W, "_load_cfg", lambda: {})
    monkeypatch.setattr(W, "_write_cfg", gespeichert.update)
    monkeypatch.setattr(W, "_calendar_config", lambda: gespeichert.get("calendar", {}))

    async def lauf():
        async with _front({"temp": 5.0}) as app:
            ui = web.Application()
            ui["app"] = app
            ui.router.add_post("/api/settings/calendar", W.api_settings_calendar)
            runner, port = await serve(ui)
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.post(f"http://127.0.0.1:{port}/api/settings/calendar",
                                      json={"sources": [QUELLE], "name": "Family"}) as r:
                        assert (await r.json())["ok"]
                await _bis(lambda: len(abrufe) == 2)
            finally:
                await runner.cleanup()
    asyncio.run(lauf())


@pytest.mark.parametrize("kopf, anfragen_erwartet", [
    ("60", 1),                               # iCloud: 503 mit Retry-After 60
    ("Thu, 01 Oct 2099 07:28:00 GMT", 1),    # Datumsform: ebenfalls laenger
    (None, 4),                               # ohne Angabe: wiederholen wie bisher
    ("0", 4),                                # kuerzer als die eigene Pause
])
def test_retry_after_wird_beachtet(monkeypatch, kopf, anfragen_erwartet):
    monkeypatch.setattr(front_info, "_RETRY_PAUSEN", (0.01, 0.01, 0.01))
    anfragen = []

    async def gesperrt(request):
        anfragen.append(request.path)
        return web.Response(status=503, headers={"Retry-After": kopf} if kopf else {})

    async def lauf():
        ui = web.Application()
        ui.router.add_get("/familie.ics", gesperrt)
        runner, port = await serve(ui)
        try:
            async with aiohttp.ClientSession() as s:
                with pytest.raises(aiohttp.ClientResponseError):
                    await front_info.fetch_events(s, f"http://127.0.0.1:{port}/familie.ics", 14)
        finally:
            await runner.cleanup()
    asyncio.run(lauf())
    assert len(anfragen) == anfragen_erwartet


# --- Geaenderte und abgesagte Einzeltermine einer Serie (RECURRENCE-ID) ---

BERLIN = ZoneInfo("Europe/Berlin")


@pytest.fixture
def ortszeit(monkeypatch):
    """Ortszeit des Servers fest auf Europe/Berlin: Das Panel zeigt Termine in
    Ortszeit, und "heute" richtet sich danach. Beim Aufraeumen erst monkeypatch
    zuruecksetzen, dann tzset(), sonst bliebe Berlin fuer alle spaeteren Tests."""
    monkeypatch.setenv("TZ", "Europe/Berlin")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _tag(n: int) -> date:
    """Tag relativ zu heute. Termine erst im Test bauen, wenn die Ortszeit steht."""
    return date.today() + timedelta(days=n)


def _d(n: int) -> str:
    return _tag(n).strftime("%Y%m%d")


def _ics(*vevents: str) -> bytes:
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//LoxPanel//Test//DE\r\n"
            + "".join(vevents) + "END:VCALENDAR\r\n").encode()


def _ev(*zeilen: str) -> str:
    return "BEGIN:VEVENT\r\n" + "".join(z + "\r\n" for z in zeilen) + "END:VEVENT\r\n"


def _termine(daten: bytes, tage: int = 10) -> list:
    out = front_info._parse_events(daten, tage, {"name": "Familie", "color": "#e0a24d", "key": "k"})
    return [(e["date"], e["time"], e["title"]) for e in out]


def _serie() -> str:
    """Training taeglich 18:00 Berliner Zeit, von morgen an viermal."""
    return _ev("UID:training@test", f"DTSTART;TZID=Europe/Berlin:{_d(1)}T180000",
               f"DTEND;TZID=Europe/Berlin:{_d(1)}T190000", "RRULE:FREQ=DAILY;COUNT=4",
               "SUMMARY:Training")


def _ausnahme(dtstart: str, titel: str, *extra: str, rid: str | None = None) -> str:
    """Geaendertes Auftreten der Serie von Tag 2 (18:00)."""
    return _ev("UID:training@test", rid or f"RECURRENCE-ID;TZID=Europe/Berlin:{_d(2)}T180000",
               f"DTSTART;TZID=Europe/Berlin:{dtstart}", f"SUMMARY:{titel}", "SEQUENCE:1", *extra)


def _serie_ohne_tag2(*ersatz) -> list:
    """Die Serie ohne ihr Auftreten an Tag 2, dazu die erwarteten Ersatztermine."""
    basis = [(_tag(n).isoformat(), "18:00", "Training") for n in (1, 3, 4)]
    return sorted(basis + list(ersatz), key=lambda x: (x[0], x[1].zfill(5), x[2]))


@pytest.mark.parametrize("tag, uhr, sichtbar", [
    (2, "20:00", True),     # spaeter am selben Tag
    (6, "10:00", True),     # auf einen anderen Tag
    (30, "18:00", False),   # aus dem angezeigten Zeitraum hinaus
], ids=["selber-tag", "anderer-tag", "ausserhalb"])
def test_verschobener_einzeltermin_ersetzt_original(ortszeit, tag, uhr, sichtbar):
    daten = _ics(_serie(), _ausnahme(f"{_d(tag)}T{uhr.replace(':', '')}00", "Training (verlegt)"))
    erwartet = [(_tag(tag).isoformat(), uhr, "Training (verlegt)")] if sichtbar else []
    assert _termine(daten) == _serie_ohne_tag2(*erwartet)


def test_recurrence_id_in_utc_trifft_dasselbe_auftreten(ortszeit):
    """Google schreibt die RECURRENCE-ID auch in UTC, die Serie aber mit TZID."""
    original = datetime.combine(_tag(2), datetime.min.time().replace(hour=18), BERLIN)
    rid = f"RECURRENCE-ID:{original.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}"
    daten = _ics(_serie(), _ausnahme(f"{_d(2)}T200000", "Training (verlegt)", rid=rid))
    assert _termine(daten) == _serie_ohne_tag2((_tag(2).isoformat(), "20:00", "Training (verlegt)"))


@pytest.mark.parametrize("ausnahme_zuerst", [False, True], ids=["serie-vorn", "ausnahme-vorn"])
def test_nur_titel_geaendert_unabhaengig_von_der_reihenfolge(ortszeit, ausnahme_zuerst):
    """Gleiche Uhrzeit, anderer Titel: Der neue Titel steht da, egal wo er im Feed steht."""
    teile = [_serie(), _ausnahme(f"{_d(2)}T180000", "Training in Halle B")]
    daten = _ics(*(reversed(teile) if ausnahme_zuerst else teile))
    assert _termine(daten) == _serie_ohne_tag2((_tag(2).isoformat(), "18:00", "Training in Halle B"))


def test_auf_ein_anderes_auftreten_verlegt_bleiben_beide(ortszeit):
    """Auf Tag 3 18:00 verlegt: Dort stehen dann zwei Termine, keiner wird verschluckt."""
    daten = _ics(_serie(), _ausnahme(f"{_d(3)}T180000", "Training (verlegt)"))
    assert _termine(daten) == _serie_ohne_tag2((_tag(3).isoformat(), "18:00", "Training (verlegt)"))


def test_ganztaegige_serie(ortszeit):
    serie = _ev("UID:muell@test", f"DTSTART;VALUE=DATE:{_d(1)}", f"DTEND;VALUE=DATE:{_d(2)}",
                "RRULE:FREQ=DAILY;INTERVAL=2;COUNT=4", "SUMMARY:Biotonne")
    feiertag = _ev("UID:muell@test", f"RECURRENCE-ID;VALUE=DATE:{_d(3)}",
                   f"DTSTART;VALUE=DATE:{_d(4)}", f"DTEND;VALUE=DATE:{_d(5)}",
                   "SUMMARY:Biotonne (Feiertag)")
    assert _termine(_ics(serie, feiertag)) == [
        (_tag(1).isoformat(), "ganztägig", "Biotonne"),
        (_tag(4).isoformat(), "ganztägig", "Biotonne (Feiertag)"),
        (_tag(5).isoformat(), "ganztägig", "Biotonne"),
        (_tag(7).isoformat(), "ganztägig", "Biotonne"),
    ]


def test_serie_ohne_zeitzone_mit_until_in_utc(ortszeit):
    """Google-Form: DTSTART ohne Zeitzone, UNTIL mit Z (eigener Weg in _occurrences)."""
    serie = _ev("UID:dienst@test", f"DTSTART:{_d(1)}T070000", f"DTEND:{_d(1)}T080000",
                f"RRULE:FREQ=DAILY;UNTIL={_d(4)}T235959Z", "SUMMARY:Dienst")
    spaet = _ev("UID:dienst@test", f"RECURRENCE-ID:{_d(2)}T070000",
                f"DTSTART:{_d(2)}T090000", "SUMMARY:Dienst spät")
    assert _termine(_ics(serie, spaet)) == [
        (_tag(1).isoformat(), "7:00", "Dienst"), (_tag(2).isoformat(), "9:00", "Dienst spät"),
        (_tag(3).isoformat(), "7:00", "Dienst"), (_tag(4).isoformat(), "7:00", "Dienst"),
    ]


@pytest.mark.parametrize("start, until, verlegt", [
    # Ende der Sommerzeit am 25.10.2026; UNTIL ist das letzte Auftreten in UTC (7:00 MEZ)
    (date(2026, 10, 22), "20261028T060000Z", date(2026, 10, 27)),
    # Beginn der Sommerzeit am 28.3.2027 (7:00 MESZ)
    (date(2027, 3, 25), "20270331T050000Z", date(2027, 3, 30)),
], ids=["herbst", "fruehjahr"])
def test_serie_ohne_zeitzone_ueber_die_zeitumstellung(ortszeit, start, until, verlegt):
    """Google-Form ueber eine Zeitumstellung hinweg: Jedes Auftreten bleibt um
    7:00 Ortszeit, das letzte faellt nicht aus dem UNTIL, und die RECURRENCE-ID
    nach der Umstellung trifft ihr Original. Feste Daten und _occurrences()
    direkt, damit der Test nicht vom heutigen Tag abhaengt."""
    cal = Calendar.from_ical(_ics(
        _ev("UID:dienst@test", f"DTSTART:{start:%Y%m%d}T070000",
            f"RRULE:FREQ=DAILY;UNTIL={until}", "SUMMARY:Dienst"),
        _ev("UID:dienst@test", f"RECURRENCE-ID:{verlegt:%Y%m%d}T070000",
            f"DTSTART:{verlegt:%Y%m%d}T090000", "SUMMARY:Dienst spät")))
    serie = next(c for c in cal.walk() if c.name == "VEVENT" and "recurrence-id" not in c)
    tage = [start + timedelta(days=n) for n in range(7)]
    auftreten = front_info._occurrences(serie, start, tage[-1] + timedelta(days=2),
                                        front_info._cancelled_single(cal)["dienst@test"])
    assert [occ for occ, _, _ in auftreten] == [
        datetime.combine(d, datetime.min.time()).replace(hour=7) for d in tage if d != verlegt]


def test_ausnahme_ohne_auftreten_im_zeitraum_bleibt_sichtbar(ortszeit):
    """Einladung zu nur einem Termin einer fremden Serie, Original in der
    Vergangenheit, oder ein Einzeltermin ohne RRULE als Original."""
    neu = _ev("UID:arzt@test", f"RECURRENCE-ID;TZID=Europe/Berlin:{_d(-3)}T090000",
              f"DTSTART;TZID=Europe/Berlin:{_d(2)}T090000", "SUMMARY:Arzt (neu)")
    alt = _ev("UID:arzt@test", f"DTSTART;TZID=Europe/Berlin:{_d(-3)}T090000",
              "RRULE:FREQ=WEEKLY;COUNT=1", "SUMMARY:Arzt")
    assert _termine(_ics(neu)) == [(_tag(2).isoformat(), "9:00", "Arzt (neu)")]
    assert _termine(_ics(alt, neu)) == [(_tag(2).isoformat(), "9:00", "Arzt (neu)")]
    einzeln = _ev("UID:zahnarzt@test", f"DTSTART;TZID=Europe/Berlin:{_d(2)}T100000",
                  "SUMMARY:Zahnarzt")
    verlegt = _ev("UID:zahnarzt@test", f"RECURRENCE-ID;TZID=Europe/Berlin:{_d(2)}T100000",
                  f"DTSTART;TZID=Europe/Berlin:{_d(2)}T110000", "SUMMARY:Zahnarzt (verlegt)")
    assert _termine(_ics(einzeln, verlegt)) == [(_tag(2).isoformat(), "11:00", "Zahnarzt (verlegt)")]


def test_absage_und_exdate_wie_bisher(ortszeit):
    abgesagt = _ev("UID:training@test", f"RECURRENCE-ID;TZID=Europe/Berlin:{_d(2)}T180000",
                   f"DTSTART;TZID=Europe/Berlin:{_d(2)}T180000", "STATUS:CANCELLED",
                   "SUMMARY:Training")
    exdate = _ev("UID:training@test", f"DTSTART;TZID=Europe/Berlin:{_d(1)}T180000",
                 "RRULE:FREQ=DAILY;COUNT=4", f"EXDATE;TZID=Europe/Berlin:{_d(2)}T180000",
                 "SUMMARY:Training")
    assert _termine(_ics(_serie(), abgesagt)) == _serie_ohne_tag2()
    assert _termine(_ics(exdate)) == _serie_ohne_tag2()


def test_ausnahme_mit_eigener_rrule_ersetzt_nur_ein_auftreten(ortszeit):
    """RANGE=THISANDFUTURE wird bewusst nicht aufgeloest: Die Ausnahme ersetzt
    nur ihr eines Auftreten, die Serie laeuft danach unveraendert weiter und
    steht nicht doppelt da."""
    rid = f"RECURRENCE-ID;RANGE=THISANDFUTURE;TZID=Europe/Berlin:{_d(2)}T180000"
    neu = _ausnahme(f"{_d(2)}T180000", "Training neu", "RRULE:FREQ=DAILY;COUNT=3", rid=rid)
    erwartet = _serie_ohne_tag2((_tag(2).isoformat(), "18:00", "Training neu"))
    assert _termine(_ics(_serie(), neu)) == erwartet


@pytest.mark.parametrize("rid_zeilen", [
    # zwei Zeilen: icalendar liefert eine Liste statt eines Werts
    ("RECURRENCE-ID;TZID=Europe/Berlin:{d2}T180000", "RECURRENCE-ID;TZID=Europe/Berlin:{d3}T180000"),
    # unlesbarer Wert: icalendar verwirft ihn
    ("RECURRENCE-ID:quatsch",),
    # am Rand des Kalenders: in Ortszeit (Berlin) jenseits des Jahres 9999
    ("RECURRENCE-ID:99991231T235959Z",),
], ids=["zwei-zeilen", "unlesbar", "jenseits-des-kalenders"])
def test_kaputte_recurrence_id_legt_die_quelle_nicht_lahm(ortszeit, rid_zeilen):
    """Kein Absturz: Der Termin steht wie bisher als eigener Termin da."""
    zeilen = [z.format(d2=_d(2), d3=_d(3)) for z in rid_zeilen]
    kaputt = _ev("UID:training@test", *zeilen,
                 f"DTSTART;TZID=Europe/Berlin:{_d(2)}T200000", "SUMMARY:Training (verlegt)")
    assert _termine(_ics(_serie(), kaputt)) == [
        (_tag(1).isoformat(), "18:00", "Training"), (_tag(2).isoformat(), "18:00", "Training"),
        (_tag(2).isoformat(), "20:00", "Training (verlegt)"),
        (_tag(3).isoformat(), "18:00", "Training"), (_tag(4).isoformat(), "18:00", "Training"),
    ]


def test_ausnahme_ohne_uid_trifft_keine_fremde_serie(ortszeit):
    """Ohne UID gehoert eine RECURRENCE-ID zu keiner Serie, auch nicht zu einer
    anderen, die ebenfalls keine UID hat."""
    serie = _ev(f"DTSTART;TZID=Europe/Berlin:{_d(1)}T090000", "RRULE:FREQ=DAILY;COUNT=3",
                "SUMMARY:Gießen")
    fremd = _ev(f"RECURRENCE-ID;TZID=Europe/Berlin:{_d(2)}T090000",
                f"DTSTART;TZID=Europe/Berlin:{_d(5)}T090000", "SUMMARY:Fremd")
    assert _termine(_ics(serie, fremd)) == [
        (_tag(1).isoformat(), "9:00", "Gießen"), (_tag(2).isoformat(), "9:00", "Gießen"),
        (_tag(3).isoformat(), "9:00", "Gießen"), (_tag(5).isoformat(), "9:00", "Fremd"),
    ]
