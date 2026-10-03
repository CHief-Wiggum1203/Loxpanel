"""Verlaufs-Diagramme im Server: Abruf beim nachgebauten Miniserver, Diagramm-
Bloecke der Detailseite, Mini-Verlauf der Kachel in allen drei Stilen und das
Speichern der zugehoerigen Panel-Optionen."""
import asyncio
from datetime import datetime

from lox import Miniserver, W, bloecke, hauslast, neue_app, pv_leistung, v1_bausteine, zaehlerstand

JETZT = datetime.now().replace(second=0, microsecond=0)


async def _geladen(app, route):
    """Einmal rendern (stoesst den Abruf an), Abruf abwarten, erneut rendern."""
    app.render(route)
    for _ in range(40):
        await asyncio.sleep(0.05)
        if not app.stat_pending:
            break
    return app.render(route)


def test_detailseite_v1(miniserver_http):
    async def lauf():
        ms = await Miniserver().start()
        app = neue_app(ms)
        try:
            app.controls = v1_bausteine(ms, JETZT)
            app.states = {"sv": 57.3, "sa": 0.6, "st": 1024.5, "sr": 0, "sx": 5}
            v = app.render({"view": "control", "id": "T"})
            assert bloecke(v, "chart")[0]["state"] == "loading" and v["route"]["range"] == "24h"
            c = bloecke(await _geladen(app, {"view": "control", "id": "T"}), "chart")[0]
            assert c["state"] == "ok" and c["unit"] == "°C" and 30 < len(c["series"][0]["pts"]) <= W.STAT_MAX_POINTS

            cz = bloecke(await _geladen(app, {"view": "control", "id": "Z"}), "chart")
            assert [b["kind"] for b in cz] == ["counter", "line"] and "ranges" not in cz[1]
            balken = cz[0]["series"][0]["pts"]
            assert len(balken) == 24 and 18 < sum(v for _, v in balken) < 20.5     # ~0,8 kWh x 24 h

            cr = bloecke(await _geladen(app, {"view": "control", "id": "R"}), "chart")[0]
            assert cr["kind"] == "digital" and any(v >= 0.5 for _, v in cr["series"][0]["pts"])

            v7 = await _geladen(app, {"view": "control", "id": "Z", "range": "7d"})
            assert v7["route"]["range"] == "7d" and len(bloecke(v7, "chart")[0]["series"][0]["pts"]) == 7

            assert app.render({"view": "control", "id": "T", "range": "quatsch"})["route"]["range"] == "24h"
            vx = app.render({"view": "control", "id": "X"})
            assert not bloecke(vx, "chart") and "range" not in vx["route"]

            n = len(ms.stat_hits)
            app.render({"view": "control", "id": "T"})
            await asyncio.sleep(0.2)
            assert len(ms.stat_hits) == n, "Monatsdateien muessen aus dem Cache kommen"
        finally:
            await app.icon_session.close()
            await ms.stop()
    asyncio.run(lauf())


def test_detailseite_v2(miniserver_http):
    async def lauf():
        ms = await Miniserver().start()
        ms.v2 = {("NETZ", "1", "actual"): (1800, lambda t: hauslast(t) - pv_leistung(t)),
                 ("NETZ", "2", "total"): (3600, zaehlerstand(lambda x: max(0, hauslast(x) - pv_leistung(x)))),
                 ("NETZ", "2", "totalNeg"): (3600, zaehlerstand(lambda x: max(0, pv_leistung(x) - hauslast(x)))),
                 ("EFM", "1", "totalSelfConsumption"): (3600, zaehlerstand(lambda x: min(pv_leistung(x), hauslast(x)))),
                 ("EFM", "2", "OYt"): (3600, zaehlerstand(lambda x: 0.3 * max(0, pv_leistung(x) - hauslast(x))))}
        gruppen = [{"id": "1", "mode": 10, "dataPoints": [{"title": "Leistung", "format": "0,000kW", "output": "actual"}]},
                   {"id": "2", "mode": 11, "accumulated": True, "dataPoints": [
                       {"title": "Zählerstand", "format": "0,0kWh", "output": "total"},
                       {"title": "Zählerstand", "format": "0,0kWh", "output": "totalNeg"}]}]
        app = neue_app(ms)
        try:
            app.controls = {
                "N": {"name": "Netz", "type": "Meter", "uuidAction": "NETZ", "states": {"actual": "a2", "total": "t2"},
                      "details": {"actualFormat": "%.3fkW", "totalFormat": "%.1fkWh"}, "statisticV2": {"groups": gruppen}},
                "E": {"name": "Energieflussmonitor", "type": "EFM", "uuidAction": "EFM", "statisticV2": {"groups": [
                    {"id": "3", "mode": 10, "dataPoints": []},
                    {"id": "1", "mode": 11, "accumulated": True, "dataPoints": [
                        {"title": "Zählerstand", "format": "0,0kWh", "output": "totalSelfConsumption"}]},
                    {"id": "2", "mode": 11, "accumulated": True, "dataPoints": [
                        {"title": "Ertrag gesamt", "format": "0,00€", "output": "OYt"}]}]}}}
            app.states = {"a2": -5.1, "t2": 12000.0}
            v = app.render({"view": "control", "id": "N"})
            assert [b["state"] for b in bloecke(v, "chart")] == ["loading", "loading"]
            ch = bloecke(await _geladen(app, {"view": "control", "id": "N"}), "chart")
            assert ms.peak <= 2, "hoechstens zwei V2-Abrufe gleichzeitig"
            linie = ch[0]["series"][0]["pts"]
            assert min(v for _, v in linie) < 0 < max(v for _, v in linie)       # Einspeisung negativ
            bezug, einsp = [sum(v for _, v in s["pts"]) for s in ch[1]["series"]]
            assert bezug > 0 and einsp > 0 and len(ch[1]["series"][0]["pts"]) == 24

            app._stat_blocks(app.controls["E"], "7d")
            await asyncio.sleep(0.8)
            e7 = app._stat_blocks(app.controls["E"], "7d")
            assert [b["unit"] for b in e7] == ["kWh", "€"]
            assert all(b["state"] == "ok" and len(b["series"][0]["pts"]) == 7 for b in e7)
        finally:
            await app.icon_session.close()
            await ms.stop()
    asyncio.run(lauf())


def test_kachel_stile(miniserver_http):
    async def lauf():
        ms = await Miniserver().start()
        app = neue_app(ms)
        try:
            # Aufzeichnung bis zum Start dieses Tests, nicht bis JETZT (Laden der
            # Datei, im vollen Lauf Minuten frueher): der Mini-Verlauf rechnet ab
            # der Stunde, in der er gezeichnet wird.
            jetzt = datetime.now().replace(second=0, microsecond=0)
            app.controls = v1_bausteine(ms, jetzt)
            # reiner Zaehler (nur Zaehlerstand); "Z" hat zusaetzlich die Leistung
            app.controls["K"] = dict(app.controls["Z"], statistic={"frequency": 6, "outputs": [
                {"id": 0, "name": "Gesamtverbrauch", "format": "%.1fkWh", "visuType": 2}]})
            app.states = {"sv": 57.3, "sa": 0.6, "st": 1024.5, "sr": 0}
            c = app.controls
            faelle = {("T", "24h", "trend"), ("T", "24h", "pattern"), ("T", "7d", "span"), ("R", "7d", "trend"),
                      ("R", "24h", "pattern"), ("R", "24h", "span"), ("K", "24h", "pattern"), ("K", "24h", "span"),
                      ("Z", "24h", "span")}
            for u, rng, st in faelle:
                app._stat_spark(c[u], rng, st)
            await asyncio.sleep(0.6)
            while True:   # Minutenwechsel mitten im Zeichnen: noch einmal zeichnen
                gezeichnet = datetime.now().replace(second=0, microsecond=0)
                sp = {(u, st): app._stat_spark(c[u], rng, st) for u, rng, st in faelle}
                if datetime.now().replace(second=0, microsecond=0) == gezeichnet:
                    break

            t = sp[("T", "trend")]
            assert t["style"] == "trend" and t["badge"].endswith("in 24 h") and t["lo"] and t["hi"]
            assert len(t["pts"]) <= 48
            m = sp[("T", "pattern")]
            assert len(m["cells"]) == 168 and m["days"][-1] == W.STAT_WEEKDAYS[gezeichnet.weekday()]
            # Die laufende Stunde traegt den zuletzt gueltigen Wert bis zur vollen
            # Minute; in ihrer ersten Minute hat sie noch keine Dauer und bleibt
            # leer. Die Stunde davor ist immer voll (um Mitternacht: 23 Uhr in der
            # Zeile davor, Index 6 * 24 - 1).
            h = gezeichnet.hour
            assert m["cells"][6 * 24 + h - 1] is not None
            assert (m["cells"][6 * 24 + h] is None) == (gezeichnet.minute == 0)
            assert h == 23 or m["cells"][6 * 24 + 23] is None, "Stunden in der Zukunft bleiben leer"
            s = sp[("T", "span")]
            # "heute" gibt es ab der ersten vollen Minute des Tages (siehe oben)
            assert len(s["spans"]) == 7
            if (h, gezeichnet.minute) == (0, 0):
                assert "badge" not in s and s["spans"][-1] is None
            else:
                assert s["badge"].startswith("heute ")
            assert sp[("R", "trend")]["badge"].startswith("Ein ")
            assert sp[("R", "span")]["style"] == "trend" and sp[("K", "span")]["style"] == "trend"   # nur Messwerte
            assert sp[("Z", "span")]["style"] == "span" and sp[("Z", "span")]["kind"] == "line"      # Kachel zeigt die Leistung
            z = sp[("K", "pattern")]
            assert z["badge"].startswith("7 Tage · Σ") and z["kind"] == "counter"
            fertig = [v for v in z["cells"][:6 * 24] if v is not None]
            assert fertig and all(0.7 < v < 0.9 for v in fertig), "0,8 kWh je Stunde"
        finally:
            await app.icon_session.close()
            await ms.stop()
    asyncio.run(lauf())


def test_panel_optionen_speichern():
    roh = {"test": {"title": "Test", "tabs": ["favoriten"], "ui": {"panes": {"favoriten": "chart:P"}},
                    "tiles": {"T": {"chart": "24h", "chartStyle": "pattern"}, "P": {"chart": "7d", "chartStyle": "trend"},
                              "R": {"chart": "quatsch"}, "S": {"chartStyle": "span"}, "Q": {"chart": "7d", "chartStyle": "bunt"}}}}
    p = W.App._sanitize_panels(roh)["test"]
    assert p["ui"]["panes"] == {"favoriten": "chart:P"}
    assert p["tiles"] == {"T": {"chart": "24h", "chartStyle": "pattern"}, "P": {"chart": "7d"}, "Q": {"chart": "7d"}}
    assert W._clean_tabpane("chart:P") == "chart:P" and W._clean_tabpane("chart:") == ""


def test_mehrere_bausteine_gestapelt(miniserver_http):
    """Verlaufs-Pane mit mehreren Bausteinen (Lenardos #77): je Baustein Name,
    Wert und Diagramme in der gewaehlten Reihenfolge, ein Zeitraum fuer alle.
    Bausteine ohne Aufzeichnung oder unbekannte fallen still weg."""
    async def lauf():
        ms = await Miniserver().start()
        app = neue_app(ms)
        try:
            app.controls = v1_bausteine(ms, JETZT)
            app.states = {"sv": 57.3, "sa": 0.6, "st": 1024.5, "sr": 0, "sx": 5}
            st = app.chart_stack(("R", "T", "X", "gibtsnicht"), "7d")
            assert st["controls"] == ["R", "T"] and [c["name"] for c in st["charts"]] == ["Regen", "Boiler"]
            assert st["range"] == "7d" and [r[0] for r in st["ranges"]] == list(W.STAT_RANGES)
            assert all(b["k"] == "chart" for c in st["charts"] for b in c["blocks"])
            assert app.chart_stack(("T",), "quatsch")["range"] == W.STAT_DEFAULT_RANGE
            assert app.chart_stack(("X",))["charts"] == []
            for _ in range(40):                      # angestossene Abrufe auslaufen lassen
                await asyncio.sleep(0.05)
                if not app.stat_pending:
                    break
        finally:
            await app.icon_session.close()
            await ms.stop()
    asyncio.run(lauf())
    assert W._clean_tabpane("chart:T, R,,") == "chart:T,R"
    assert W._clean_svpane(" chart:T,R ") == "chart:T,R" and W._clean_svpane("chart:") == ""


def test_veralteter_stapel_kommt_nicht_hinterher(miniserver_http):
    """Waehlt das Panel einen anderen Verlaufs-Stapel (setchart), waehrend die
    Push-Schleife noch an seine Verbindung sendet, hat setchart den neuen schon
    geschickt. Den Stapel, den die Schleife vorher berechnet hat, darf sie danach
    nicht mehr schicken - er loeste den neuen in der Pane bis zum naechsten Takt
    wieder ab."""
    async def lauf(wechseln):
        ms = await Miniserver().start()
        app = neue_app(ms)
        ws, gesendet = object(), []

        async def senden(w, msg):
            gesendet.append(msg)
            if wechseln and msg["t"] != "chart" and app.conn_chart[w] == (("T",), "24h"):
                # wie der Zweig setchart in ws_handler: merken und sofort schicken
                app.conn_chart[w] = (("R",), "24h")
                neu = {"t": "chart", **app.chart_stack(("R",), "24h")}
                gesendet.append(neu)
                app._last_sent.setdefault(w, {})["chart"] = neu
            return True
        try:
            app.controls = v1_bausteine(ms, JETZT)
            app.states = {"sv": 57.3, "sa": 0.6, "st": 1024.5, "sr": 0, "sx": 5}
            app._send_or_drop = senden
            app.conn_route[ws] = {"view": "control", "id": "T"}
            app.conn_chart[ws] = (("T",), "24h")
            app._dirty = True
            await app._broadcast_tick()
            for _ in range(40):                      # angestossene Abrufe auslaufen lassen
                await asyncio.sleep(0.05)
                if not app.stat_pending:
                    break
        finally:
            await app.icon_session.close()
            await ms.stop()
        return [m["controls"] for m in gesendet if m["t"] == "chart"]
    assert asyncio.run(lauf(False)) == [["T"]]
    assert asyncio.run(lauf(True)) == [["R"]]
