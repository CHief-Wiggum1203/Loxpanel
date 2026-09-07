"""Gen-2-Audioserver-Event-Client (Loxone-Audioprotokoll ueber WebSocket 7091).

Der Loxone-Audioserver (Original ODER Nachbau wie Sonn/Audioserver4Home) sendet
Now-Playing und Favoriten NICHT ueber die Miniserver-Struktur-States, sondern
ueber einen eigenen Event-Kanal: die App verbindet sich direkt per WebSocket zum
Audioserver (Port 7091, unverschluesselt, OHNE Auth) und bekommt beim Connect +
bei jeder Aenderung `audio_event`-Push-Nachrichten fuer alle Zonen. So bekommen
AudioZoneV2-Zonen im Panel Cover/Titel/Interpret/Status — universell, egal
welcher Audioserver, mit Live-Push statt Polling.

Nachrichtenformate (verifiziert gegen Sonn 4.0.0-beta.20 / LWSS API 1.6):
  Banner (kein JSON):  "LWSS V 17.1.05.05 | ~API:1.6~ | Session-Token: ..."
  Push:  {"audio_event":[{playerid,name,title,artist,album,coverurl,station,
                          mode(play/pause/stop),volume,plrepeat,plshuffle,...}]}
  Abruf: audio/<id>/status            -> {"status_result":[{...wie audio_event}]}
         audio/cfg/getroomfavs/<id>   -> {"getroomfavs_result":[{id,items:[
                                          {slot,name,title,coverurl,type,...}]}]}

Steuerung (play/pause/next/volume/roomfav) laeuft weiter ueber den Miniserver
(`sps/io/<uuid>/<cmd>` -> `audio/<id>/<cmd>`), nicht ueber dieses Modul.
"""
from __future__ import annotations

import asyncio
import json
import logging

import aiohttp

log = logging.getLogger("loxpanel.audioevents")


class AudioEventClient:
    """Haelt per WebSocket (7091) den Live-Zustand aller Audioserver-Zonen.

    now:  playerid -> Now-Playing-Dict {title,artist,album,cover,playing,volume,name}
    favs: playerid -> [ {slot,name,cover} ]

    Zuordnung Control->Zone laeuft ueber die playerid (aus control.details.
    playerid), NICHT ueber den Namen — das ist eindeutig und kollisionsfrei.
    """

    def __init__(self, host: str, port: int = 7091):
        self.host = host
        self.port = port
        self.now: dict[int, dict] = {}
        self.favs: dict[int, list] = {}
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._on_change = None
        self._stop = False

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}/"

    def _apply_event(self, entries) -> bool:
        changed = False
        for e in entries or []:
            if not isinstance(e, dict):
                continue
            pid = e.get("playerid")
            if pid is None:
                continue
            np = {
                "name": (e.get("name") or "").strip(),
                "title": e.get("title") or "",
                "artist": e.get("artist") or "",
                "album": e.get("album") or e.get("station") or "",
                "cover": e.get("coverurl") or "",
                "playing": (e.get("mode") == "play"),
                "volume": e.get("volume"),
            }
            if self.now.get(pid) != np:
                self.now[pid] = np
                changed = True
        return changed

    def _apply_favs(self, results) -> bool:
        changed = False
        for grp in results or []:
            if not isinstance(grp, dict):
                continue
            pid = grp.get("id")
            items = []
            for it in (grp.get("items") or []):
                if not isinstance(it, dict) or it.get("slot") is None:
                    continue
                # Abspiel-Index: manche Server (Sonn/Audioserver4Home) erwarten die
                # numerische Item-`id` (2,3,4), der Loxone-Musikserver dagegen den
                # `slot` (1,2,3). Regel: ganzzahlige `id` bevorzugen, sonst `slot`.
                try:
                    play = int(it.get("id"))
                except (TypeError, ValueError):
                    play = it.get("slot")
                items.append({
                    "slot": it.get("slot"),
                    "play": play,
                    "name": it.get("name") or it.get("title") or f"Favorit {it.get('slot')}",
                    "cover": it.get("coverurl") or "",
                })
            if self.favs.get(pid) != items:
                self.favs[pid] = items
                changed = True
        return changed

    def _handle(self, data: str) -> bool:
        try:
            msg = json.loads(data)
        except (ValueError, TypeError):
            return False   # Banner o.ae. -> ignorieren
        if not isinstance(msg, dict):
            return False
        if "audio_event" in msg:
            return self._apply_event(msg.get("audio_event"))
        if "status_result" in msg:
            return self._apply_event(msg.get("status_result"))
        if "getroomfavs_result" in msg:
            return self._apply_favs(msg.get("getroomfavs_result"))
        return False

    async def _send(self, cmd: str) -> None:
        ws = self._ws
        if ws is not None and not ws.closed:
            try:
                await ws.send_str(cmd)
            except Exception as err:
                log.debug("audioevents send %s: %s", cmd, err)

    async def request_favs(self, playerid: int) -> None:
        """Raumfavoriten einer Zone anfordern (Ergebnis kommt async im Reader).

        Die Range-Form `.../<start>/<count>` ist zwingend: ohne sie liefert der
        Server die Favoriten mit `slot: null` (nicht abspielbar). Mit Range
        kommen echte Slot-Nummern (1..N) fuer roomfav/play/<slot>.
        """
        if playerid is not None:
            await self._send(f"audio/cfg/getroomfavs/{int(playerid)}/0/50")

    async def run(self, on_change=None) -> None:
        """Verbindungs-/Lese-Schleife mit Auto-Reconnect. `on_change` wird bei
        jeder Zustandsaenderung aufgerufen (setzt im Server _dirty)."""
        self._on_change = on_change
        while not self._stop:
            try:
                if self._session is None or self._session.closed:
                    self._session = aiohttp.ClientSession()
                async with self._session.ws_connect(
                        self.url, timeout=8, heartbeat=30) as ws:
                    self._ws = ws
                    log.info("Audioserver-Events verbunden: %s", self.url)
                    async for m in ws:
                        if m.type == aiohttp.WSMsgType.TEXT:
                            if self._handle(m.data) and self._on_change:
                                self._on_change()
                        elif m.type in (aiohttp.WSMsgType.CLOSED,
                                        aiohttp.WSMsgType.ERROR):
                            break
            except Exception as err:
                log.debug("Audioserver-Events (%s): %s", self.url, err)
            self._ws = None
            if self._stop:
                break
            await asyncio.sleep(5)

    async def close(self) -> None:
        self._stop = True
        try:
            if self._ws is not None and not self._ws.closed:
                await self._ws.close()
        except Exception:
            pass
        try:
            if self._session is not None and not self._session.closed:
                await self._session.close()
        except Exception:
            pass
