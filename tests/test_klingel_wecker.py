"""Klingel und Wecker an die Panels (Verteilung, ARCHITEKTUR P3).

- Die Haustuer klingelt auf jedem Panel, auch einem, dessen Ansicht nur andere
  Raeume zeigt; nur eine Ansicht, die die Tuersprechanlage ausblendet (hide),
  bekommt nichts.
- Der Wecker toent nur, wo die Ansicht ihn zeigt (Raum, Kategorie, hide), und
  nur dort geht das Display an. "Aus" geht an alle, damit ein Panel, das
  waehrenddessen die Ansicht gewechselt hat, nicht weitertoent.
"""
import asyncio

import aiohttp

from lox import anlage, intercom_baustein, visu_starten, W, wecker_baustein

# Ansicht -> Geraet; beide Bausteine liegen in Raum r1 (Zentral)
ANSICHTEN = {"alle": {}, "anderer_raum": {"rooms": ["r2"]}, "ohne_klingel": {"hide": ["IC"]}}


def _app():
    app = W.App({"host": "", "port": 80})
    ic, ic_st = intercom_baustein()
    wk, wk_st = wecker_baustein()
    app._apply_structure(anlage({"IC": ic, "WK": wk}))
    app.states = {**ic_st, **wk_st}
    app.panels = W.App._sanitize_panels({pid: {"title": pid, "tabs": ["favoriten"], **f}
                                         for pid, f in ANSICHTEN.items()})
    return app


def test_klingel_ueberall_wecker_nur_wo_er_zu_sehen_ist():
    async def lauf():
        app = _app()
        geweckt = []

        async def display_drivers(on, device="", panel=""):
            geweckt.append((on, device))
            return []
        app.display_drivers = display_drivers
        runner, port, bc = await visu_starten(app)
        try:
            async with aiohttp.ClientSession() as s:
                ws = {pid: await s.ws_connect(f"http://127.0.0.1:{port}/ws?panel={pid}&device=g-{pid}")
                      for pid in ANSICHTEN}
                await asyncio.sleep(0.5)

                async def einsammeln(art):
                    erhalten = {}
                    for pid, w in ws.items():
                        try:
                            while True:
                                m = await asyncio.wait_for(w.receive_json(), 1.0)
                                if m.get("t") == art:
                                    erhalten[pid] = m
                                    break
                        except asyncio.TimeoutError:
                            pass
                    return erhalten
                app._pending_ring = "IC"
                klingel = await einsammeln("ring")
                ring_geweckt = list(geweckt)
                geweckt.clear()
                app._pending_alarm.append({"id": "WK", "on": True})
                wecker_an = await einsammeln("alarm")
                await asyncio.sleep(0.1)
                an_geweckt = sorted(geweckt)
                app._pending_alarm.append({"id": "WK", "on": False})
                wecker_aus = await einsammeln("alarm")
                for w in ws.values():
                    await w.close()
                return klingel, ring_geweckt, wecker_an, an_geweckt, wecker_aus
        finally:
            bc.cancel()
            await runner.cleanup()
    klingel, ring_geweckt, wecker_an, an_geweckt, wecker_aus = asyncio.run(lauf())
    assert sorted(klingel) == ["alle", "anderer_raum"] and klingel["alle"] == {"t": "ring", "id": "IC"}
    assert ring_geweckt == [(True, "")], "die Klingel weckt wie bisher alle Displays"
    assert sorted(wecker_an) == ["alle", "ohne_klingel"]
    assert an_geweckt == [(True, "g-alle"), (True, "g-ohne_klingel")]
    assert sorted(wecker_aus) == sorted(ANSICHTEN) and all(m["on"] is False for m in wecker_aus.values())


def test_sichtbar_wie_auf_den_seiten():
    """_sichtbar nimmt dieselben Regeln wie die Seiten: Raum, Kategorie, hide."""
    app = _app()
    for pid, soll in (("alle", True), ("anderer_raum", False), ("ohne_klingel", True)):
        assert app._sichtbar("WK", app.resolve_profile(pid)) is soll, pid
    assert app._sichtbar("IC", app.resolve_profile("ohne_klingel")) is False
    nur_andere_kategorie = W.App._sanitize_panels({"k": {"title": "k", "tabs": ["favoriten"], "cats": ["c9"]}})
    app.panels = nur_andere_kategorie
    assert app._sichtbar("WK", app.resolve_profile("k")) is False
