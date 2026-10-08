"""Gen1-Anrufe gegen einen echten lokalen UDP-SIP-Dialogpartner.

Der Nachbau berechnet Digest selbst und zeichnet alle SIP-Pakete auf. Die
Tests pruefen damit Dialogzustand und Protokollfolge, nicht interne Methoden.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass

import pytest
from sip_call import SipCall, parse_sdp

SDP = ("v=0\r\no=door 1 1 IN IP4 127.0.0.1\r\ns=-\r\n"
       "c=IN IP4 127.0.0.1\r\nt=0 0\r\nm=audio 7092 RTP/AVP 8 0\r\n"
       "a=rtpmap:8 PCMA/8000\r\na=rtpmap:0 PCMU/8000\r\na=sendrecv\r\n")
MEDIA = {"remoteHost": "127.0.0.1", "remotePort": 7092, "codec": "PCMA",
         "payloadType": 8, "sampleRate": 8000, "ptime": 20}


@dataclass
class Paket:
    start: str
    headers: dict[str, str]
    body: str
    raw: bytes

    @classmethod
    def read(cls, data: bytes) -> Paket:
        head, _, body = data.decode().partition("\r\n\r\n")
        lines = head.split("\r\n")
        headers = {}
        for line in lines[1:]:
            name, sep, value = line.partition(":")
            if sep:
                headers[name.lower()] = value.strip()
        return cls(lines[0], headers, body, data)

    @property
    def method(self) -> str:
        return self.start.split()[0]

    @property
    def uri(self) -> str:
        return self.start.split()[1]

    @property
    def branch(self) -> str:
        match = re.search(r"(?:^|;)branch=([^; ]+)", self.headers["via"])
        assert match, "SIP-Anfrage ohne branch"
        return match.group(1)


class DialogTuer(asyncio.DatagramProtocol):
    """Kleiner UAS mit Authentifizierung, Verlust, CANCEL-Races und Remote-BYE."""

    def __init__(self, *, auth=None, proxy=False, qop=True, hold=False,
                 provisional=False, cancel_race=False, final=200, sdp=SDP,
                 routes=False, foreign=False, drop_invites=0, drop_byes=0,
                 bye_auth=False, reject_auth=False):
        self.auth, self.proxy, self.qop = auth, proxy, qop
        self.hold, self.provisional, self.cancel_race = hold, provisional, cancel_race
        self.final, self.sdp, self.routes, self.foreign = final, sdp, routes, foreign
        self.drop_invites, self.drop_byes = drop_invites, drop_byes
        self.bye_auth, self.reject_auth = bye_auth, reject_auth
        self.packets: list[Paket] = []
        self.responses: list[Paket] = []
        self.changed = asyncio.Event()
        self.invite = None
        self.peer = None
        self.transport = None
        self.port = 0
        self.auth_validations: list[bool] = []
        self.timers = []

    async def __aenter__(self):
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: self, local_addr=("127.0.0.1", 0))
        self.port = self.transport.get_extra_info("sockname")[1]
        return self

    async def __aexit__(self, *_):
        for timer in self.timers:
            timer.cancel()
        self.transport.close()
        await asyncio.sleep(0)

    @property
    def host(self):
        return f"127.0.0.1:{self.port}"

    @property
    def contact(self):
        return f"sip:door-dialog@127.0.0.1:{self.port}"

    def requests(self, method):
        return [packet for packet in self.packets if packet.method == method]

    async def wait(self, method, count=1):
        async def ready():
            while len(self.requests(method)) < count:
                self.changed.clear()
                await self.changed.wait()
            return self.requests(method)[count - 1]
        return await asyncio.wait_for(ready(), 3)

    def datagram_received(self, data, addr):
        packet = Paket.read(data)
        if packet.method == "SIP/2.0":
            self.responses.append(packet)
            self.changed.set()
            return
        self.packets.append(packet)
        self.peer = addr
        self.changed.set()
        if packet.method == "INVITE":
            self.invite = packet
            if self.drop_invites:
                self.drop_invites -= 1
                return
            if self.foreign:
                self.respond(packet, 486, overrides={"call-id": "foreign@example"})
                self.respond(packet, 486, overrides={"cseq": packet.headers["cseq"].replace("INVITE", "BYE")})
                self.respond(packet, 486, overrides={"via": packet.headers["via"].replace(packet.branch, "z9hG4bKforeign")})
            if self.auth:
                auth = packet.headers.get("proxy-authorization" if self.proxy else "authorization")
                if not auth or self.reject_auth:
                    self.challenge(packet)
                    return
                valid = self.digest_ok(auth, "INVITE", packet.uri)
                self.auth_validations.append(valid)
                if not valid:
                    self.respond(packet, 403)
                    return
            if self.provisional:
                self.respond(packet, 180)
            if not self.hold:
                self.respond(packet, self.final, self.sdp if self.final == 200 else "")
        elif packet.method == "CANCEL":
            self.respond(packet, 200)
            if self.cancel_race:
                self.respond(self.invite, 200, self.sdp)
            else:
                self.respond(self.invite, 487)
        elif packet.method == "BYE":
            if self.drop_byes:
                self.drop_byes -= 1
                return
            auth = packet.headers.get("proxy-authorization" if self.proxy else "authorization")
            if self.bye_auth and not auth:
                self.challenge(packet)
                return
            if self.bye_auth:
                valid = self.digest_ok(auth, "BYE", packet.uri)
                self.auth_validations.append(valid)
                if not valid:
                    self.respond(packet, 403)
                    return
            self.respond(packet, 200)
        # ACK ist eine Bestaetigung und erhaelt niemals eine Antwort.

    def challenge(self, packet):
        header = "Proxy-Authenticate" if self.proxy else "WWW-Authenticate"
        challenge = (f'{header}: Digest realm="door.local", nonce="nonce-{packet.method}", '
                     f'algorithm={self.auth or "MD5"}')
        if self.qop:
            challenge += ', qop="auth"'
        self.respond(packet, 407 if self.proxy else 401, extra=[challenge])

    def digest_ok(self, header, method, uri):
        params = {key: value.strip('"') for key, value in
                  re.findall(r'(\w+)=("[^"]*"|[^,\s]+)', header)}
        hasher = hashlib.sha256 if self.auth == "SHA-256" else hashlib.md5

        def h(value):
            return hasher(value.encode()).hexdigest()
        ha1, ha2 = h("tuer:door.local:geheim"), h(f"{method}:{uri}")
        nonce = f"nonce-{method}"
        if self.qop:
            response = h(f"{ha1}:{nonce}:{params.get('nc')}:{params.get('cnonce')}:auth:{ha2}")
        else:
            response = h(f"{ha1}:{nonce}:{ha2}")
        return (params.get("username") == "tuer" and params.get("nonce") == nonce
                and params.get("uri") == uri and params.get("response") == response)

    def respond(self, packet, code, body="", *, overrides=None, extra=()):
        reasons = {180: "Ringing", 200: "OK", 401: "Unauthorized", 403: "Forbidden",
                   407: "Proxy Authentication Required", 486: "Busy Here", 487: "Request Terminated"}
        headers = {name: packet.headers[name] for name in ("via", "from", "to", "call-id", "cseq")}
        if ";tag=" not in headers["to"]:
            headers["to"] += ";tag=door-tag"
        headers.update(overrides or {})
        lines = [f"SIP/2.0 {code} {reasons[code]}"]
        lines += [f"{name}: {value}" for name, value in headers.items()]
        lines += list(extra)
        if code == 200 and packet.method == "INVITE":
            lines.append(f"Contact: <{self.contact}>")
            if self.routes:
                lines.append(f"Record-Route: <sip:router@127.0.0.1:{self.port};lr>")
        if body:
            lines.append("Content-Type: application/sdp")
        lines += [f"Content-Length: {len(body.encode())}", "", body]
        self.transport.sendto("\r\n".join(lines).encode(), self.peer)

    def remote_bye(self, *, wrong_dialog=False):
        invite = self.invite
        lines = [f"BYE {invite.headers['contact'].strip('<>')} SIP/2.0",
                 f"Via: SIP/2.0/UDP 127.0.0.1:{self.port};branch=z9hG4bKremote;rport",
                 f"From: {invite.headers['to']};tag={'foreign' if wrong_dialog else 'door-tag'}",
                 f"To: {invite.headers['from']}", f"Call-ID: {invite.headers['call-id']}",
                 "CSeq: 77 BYE", "Content-Length: 0", "", ""]
        self.transport.sendto("\r\n".join(lines).encode(), self.peer)


def call_for(door, **kwargs):
    return SipCall(door.host, "tuer", "geheim", 7094, timeout=2, **kwargs)


async def aborted(task):
    with pytest.raises(ValueError, match="abgebrochen"):
        await asyncio.wait_for(task, 3)


def test_parse_sdp_statisches_pcmaund_reihenfolge():
    assert parse_sdp(SDP) == MEDIA
    pcmu = SDP.replace("RTP/AVP 8 0", "RTP/AVP 101 0 8")
    assert parse_sdp(pcmu) == {**MEDIA, "codec": "PCMU", "payloadType": 0}
    no_maps = "\r\n".join(line for line in SDP.split("\r\n") if not line.startswith("a=rtpmap:"))
    assert parse_sdp(no_maps) == MEDIA


def test_parse_sdp_audio_verbindung_ueberschreibt_session_und_video():
    sdp = SDP.replace("a=rtpmap:8", "c=IN IP4 192.0.2.40\r\na=rtpmap:8")
    sdp += "m=video 8000 RTP/AVP 96\r\nc=IN IP4 192.0.2.99\r\na=rtpmap:96 H264/90000\r\n"
    assert parse_sdp(sdp) == {**MEDIA, "remoteHost": "192.0.2.40"}


def test_parse_sdp_media_direction_ueberschreibt_session():
    sdp = SDP.replace("t=0 0\r\n", "t=0 0\r\na=inactive\r\n")
    assert parse_sdp(sdp) == MEDIA


@pytest.mark.parametrize("sdp", [
    "", SDP.replace("m=audio", "m=video"),
    SDP.replace("c=IN IP4 127.0.0.1\r\n", ""),
    SDP.replace("c=IN IP4 127.0.0.1", "c=IN IP6 ::1"),
    SDP.replace("c=IN IP4 127.0.0.1", "c=IN IP4 invalid-address"),
    SDP.replace("audio 7092", "audio 0"), SDP.replace("audio 7092", "audio 65536"),
    SDP.replace("RTP/AVP", "RTP/SAVP"),
    SDP.replace("RTP/AVP 8 0", "RTP/AVP 101"),
    SDP.replace("RTP/AVP 8 0", "RTP/AVP 8").replace("PCMA/8000", "PCMA/16000"),
    SDP.replace("RTP/AVP 8 0", "RTP/AVP 8").replace("PCMA/8000", "PCMA/8000/2"),
    SDP.replace("a=sendrecv", "a=inactive"),
    SDP.replace("a=sendrecv", "a=sendonly"),
    SDP.replace("a=sendrecv", "a=recvonly"),
], ids=["empty", "video-only", "no-connection", "ipv6", "invalid-ip", "disabled-port",
        "invalid-port", "srtp", "no-common-codec", "wrong-clock", "stereo", "inactive", "sendonly", "recvonly"])
def test_parse_sdp_ungueltig(sdp):
    with pytest.raises(ValueError):
        parse_sdp(sdp)


def test_anruf_ohne_digest_dialog_target_ack_und_bye():
    async def run():
        async with DialogTuer() as door:
            call = call_for(door)
            try:
                assert await call.start() == MEDIA
                assert call.state == "connected" and call.error == "" and call.media == MEDIA
                invite = await door.wait("INVITE")
                ack = await door.wait("ACK")
                assert invite.uri == f"sip:tuer@{door.host}"
                assert invite.headers["cseq"].endswith(" INVITE")
                assert invite.headers["content-type"] == "application/sdp"
                assert int(invite.headers["content-length"]) == len(invite.body.encode())
                assert "m=audio 7094 RTP/AVP" in invite.body
                assert "PCMA/8000" in invite.body and "PCMU/8000" in invite.body
                assert ack.uri == door.contact and ack.branch != invite.branch
                assert ack.headers["cseq"] == invite.headers["cseq"].replace("INVITE", "ACK")
                assert ack.headers["to"].endswith(";tag=door-tag")
                assert "geheim" not in invite.raw.decode()
                await call.stop()
                bye = await door.wait("BYE")
                assert bye.uri == door.contact and bye.headers["to"] == ack.headers["to"]
                assert bye.headers["from"] == invite.headers["from"]
                assert bye.headers["call-id"] == invite.headers["call-id"]
                assert int(bye.headers["cseq"].split()[0]) > int(invite.headers["cseq"].split()[0])
                assert bye.branch not in {invite.branch, ack.branch}
                assert call.state == "idle"
                await call.stop()
                assert len(door.requests("BYE")) == 1
            finally:
                await call.stop()
    asyncio.run(run())


@pytest.mark.parametrize("algorithm, proxy, qop", [
    ("MD5", False, True), ("SHA-256", False, True),
    ("MD5", True, True), ("MD5", False, False),
])
def test_digest_ack_vor_neuem_invite(algorithm, proxy, qop):
    async def run():
        async with DialogTuer(auth=algorithm, proxy=proxy, qop=qop) as door:
            call = call_for(door)
            try:
                assert await call.start() == MEDIA
                first, second = door.requests("INVITE")
                challenge_ack, success_ack = door.requests("ACK")
                assert [packet.method for packet in door.packets[:4]] == ["INVITE", "ACK", "INVITE", "ACK"]
                assert challenge_ack.branch == first.branch
                assert challenge_ack.headers["cseq"] == first.headers["cseq"].replace("INVITE", "ACK")
                assert challenge_ack.headers["to"].endswith(";tag=door-tag")
                assert second.branch != first.branch
                assert int(second.headers["cseq"].split()[0]) == int(first.headers["cseq"].split()[0]) + 1
                assert second.headers["call-id"] == first.headers["call-id"]
                assert second.headers["from"] == first.headers["from"]
                assert second.headers["to"] == first.headers["to"]
                assert success_ack.branch != second.branch
                assert door.auth_validations == [True]
                auth_header = "proxy-authorization" if proxy else "authorization"
                assert auth_header in second.headers and auth_header not in first.headers
                assert all("geheim" not in packet.raw.decode() for packet in door.packets)
            finally:
                await call.stop()
    asyncio.run(run())


@pytest.mark.parametrize("code", [403, 486])
def test_invite_fehler_wird_bestaetigt(code):
    async def run():
        async with DialogTuer(final=code) as door:
            call = call_for(door)
            try:
                with pytest.raises((RuntimeError, ValueError)):
                    await call.start()
                assert call.state == "error" and call.error
                invite, ack = await door.wait("INVITE"), await door.wait("ACK")
                assert ack.branch == invite.branch
                assert ack.headers["cseq"] == invite.headers["cseq"].replace("INVITE", "ACK")
                assert not door.requests("BYE")
            finally:
                await call.stop()
    asyncio.run(run())


def test_fremde_callid_cseq_methode_und_branch_ignorieren():
    async def run():
        async with DialogTuer(foreign=True) as door:
            call = call_for(door)
            try:
                assert await call.start() == MEDIA
                assert call.state == "connected"
                assert len(door.requests("ACK")) == 1
            finally:
                await call.stop()
    asyncio.run(run())


@pytest.mark.parametrize("race", [False, True], ids=["cancel-487", "cancel-200-race"])
def test_stop_waehrend_start_cancel_und_annahmerace(race):
    async def run():
        async with DialogTuer(hold=True, provisional=True, cancel_race=race) as door:
            call = call_for(door)
            task = asyncio.create_task(call.start())
            try:
                invite = await door.wait("INVITE")
                await asyncio.wait_for(call.stop(), 3)
                await aborted(task)
                cancel = await door.wait("CANCEL")
                ack = await door.wait("ACK")
                assert cancel.uri == invite.uri and cancel.branch == invite.branch
                assert cancel.headers["from"] == invite.headers["from"]
                assert cancel.headers["to"] == invite.headers["to"]
                assert cancel.headers["cseq"] == invite.headers["cseq"].replace("INVITE", "CANCEL")
                if race:
                    bye = await door.wait("BYE")
                    assert ack.uri == door.contact and bye.uri == door.contact
                    assert ack.branch != invite.branch
                    assert door.packets.index(ack) < door.packets.index(bye)
                else:
                    assert ack.branch == invite.branch and not door.requests("BYE")
                assert call.state == "idle"
                await call.stop()
                assert len(door.requests("CANCEL")) == 1
            finally:
                await call.stop()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_cancel_vor_1xx_wartet_auf_vorlaeufige_antwort():
    async def run():
        async with DialogTuer(hold=True) as door:
            call = call_for(door)
            task = asyncio.create_task(call.start())
            stop_task = None
            try:
                invite = await door.wait("INVITE")
                stop_task = asyncio.create_task(call.stop())
                await asyncio.sleep(0.05)
                assert not door.requests("CANCEL")
                door.respond(invite, 180)
                await asyncio.wait_for(stop_task, 3)
                await aborted(task)
                await door.wait("CANCEL")
                assert call.state == "idle"
            finally:
                await call.stop()
                for pending in (task, stop_task):
                    if pending is not None and not pending.done():
                        pending.cancel()
                await asyncio.gather(task, *([stop_task] if stop_task else []), return_exceptions=True)
    asyncio.run(run())


def test_doppeltes_200_wird_erneut_bestaetigt():
    async def run():
        async with DialogTuer() as door:
            call = call_for(door)
            try:
                await call.start()
                first_ack = await door.wait("ACK")
                door.respond(door.invite, 200, SDP)
                second_ack = await door.wait("ACK", 2)
                assert second_ack.headers["cseq"] == first_ack.headers["cseq"]
                assert second_ack.headers["to"] == first_ack.headers["to"]
                assert second_ack.uri == door.contact
                assert call.state == "connected" and len(door.requests("INVITE")) == 1
            finally:
                await call.stop()
    asyncio.run(run())


def test_verlorenes_invite_und_bye_identisch_wiederholen():
    async def run():
        async with DialogTuer(drop_invites=1, drop_byes=1) as door:
            call = call_for(door)
            try:
                assert await call.start() == MEDIA
                first, repeat = door.requests("INVITE")
                assert first.raw == repeat.raw
                await call.stop()
                first_bye, repeat_bye = door.requests("BYE")
                assert first_bye.raw == repeat_bye.raw
                assert call.state == "idle"
            finally:
                await call.stop()
    asyncio.run(run())


def test_bye_digest_benutzt_bye_und_contact_uri():
    async def run():
        async with DialogTuer(auth="MD5", bye_auth=True) as door:
            call = call_for(door)
            try:
                await call.start()
                await call.stop()
                first, second = door.requests("BYE")
                assert first.uri == second.uri == door.contact
                assert first.branch != second.branch
                assert int(second.headers["cseq"].split()[0]) > int(first.headers["cseq"].split()[0])
                assert door.auth_validations == [True, True]
                assert call.state == "idle"
            finally:
                await call.stop()
    asyncio.run(run())


def test_remote_bye_prueft_dialog_und_beantwortet_gueltiges_bye():
    async def run():
        async with DialogTuer() as door:
            call = call_for(door)
            try:
                await call.start()
                await door.wait("ACK")
                door.remote_bye(wrong_dialog=True)
                await asyncio.sleep(0.05)
                assert call.state == "connected"
                door.remote_bye()

                async def ended():
                    while call.state != "idle":
                        await asyncio.sleep(0.01)
                await asyncio.wait_for(ended(), 2)
                valid = [packet for packet in door.responses
                         if packet.start.startswith("SIP/2.0 200") and packet.headers["cseq"] == "77 BYE"]
                assert len(valid) == 1
                answer = valid[0]
                assert answer.headers["from"].endswith(";tag=door-tag")
                assert answer.headers["to"] == door.invite.headers["from"]
                assert answer.headers["call-id"] == door.invite.headers["call-id"]
                await call.stop()
                assert not door.requests("BYE")
            finally:
                await call.stop()
    asyncio.run(run())


@pytest.mark.parametrize("options", [{"sdp": SDP.replace("RTP/AVP 8 0", "RTP/AVP 101")},
                                      {"routes": True}], ids=["unsupported-sdp", "record-route"])
def test_angenommenen_unbrauchbaren_dialog_bestaetigen_und_beenden(options):
    async def run():
        async with DialogTuer(**options) as door:
            call = call_for(door)
            try:
                with pytest.raises((ValueError, RuntimeError)):
                    await call.start()
                assert call.state == "error" and call.error
                if options.get("routes"):
                    assert "route" in call.error.lower()
                ack, bye = await door.wait("ACK"), await door.wait("BYE")
                assert door.packets.index(ack) < door.packets.index(bye)
                assert ack.headers["to"] == bye.headers["to"]
            finally:
                await call.stop()
    asyncio.run(run())


def test_ausbleibende_antwort_begrenzt_warten_und_stop_idempotent():
    async def run():
        async with DialogTuer(hold=True) as door:
            call = SipCall(door.host, "tuer", "geheim", 7094, timeout=0.2)
            with pytest.raises((ValueError, RuntimeError)):
                await asyncio.wait_for(call.start(), 2)
            assert call.state == "error" and call.error
            await call.stop()
            await call.stop()
            assert call.state == "idle" and not door.requests("BYE")
    asyncio.run(run())


def test_wiederholte_auth_challenge_begrenzt_anmeldeversuche():
    async def run():
        async with DialogTuer(auth="MD5", reject_auth=True) as door:
            call = call_for(door)
            try:
                with pytest.raises((ValueError, RuntimeError)):
                    await asyncio.wait_for(call.start(), 3)
                assert call.state == "error" and call.error
                assert len(door.requests("INVITE")) <= 3
                assert len(door.requests("ACK")) == len(door.requests("INVITE"))
            finally:
                await call.stop()
    asyncio.run(run())


def test_dns_aufloesung_zaehlt_zur_anruffrist(monkeypatch):
    async def lauf():
        async def keine_antwort(*args, **kwargs):
            await asyncio.sleep(10)
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", keine_antwort)
        call = SipCall("door.example", "", "", 17000, timeout=0.05)
        try:
            with pytest.raises(ValueError, match="Keine Antwort"):
                await asyncio.wait_for(call.start(), 0.5)
            assert call.state == "error"
            assert call.error == "Keine Antwort auf den SIP-Anruf"
        finally:
            await call.stop()
        assert call.state == "idle"
    asyncio.run(lauf())


def test_gleichzeitiges_stop_sendet_nur_ein_bye():
    async def run():
        async with DialogTuer() as door:
            call = call_for(door)
            await call.start()
            await asyncio.gather(call.stop(), call.stop(), call.stop())
            assert len(door.requests("BYE")) == 1 and call.state == "idle"
    asyncio.run(run())
