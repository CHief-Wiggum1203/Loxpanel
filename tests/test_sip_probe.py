"""SIP-Pruefung der Tuerstation (bin/sip_probe.py): OPTIONS ueber UDP, Anmeldung
mit Digest, Codecs aus dem SDP. Die Digest-Werte stammen aus den Beispielen von
RFC 2617 (3.5) und RFC 7616 (3.9.1); die Gegenstelle ist der Nachbau SipTuer
aus tests/lox.py, der die Anmeldung unabhaengig nachrechnet."""
import asyncio
import hashlib
import os
import re
import socket
import time

import pytest

import sip_probe as P
from lox import TUER_SDP, SipTuer

RFC7616 = ('Digest realm="http-auth@example.org", qop="auth, auth-int", algorithm={alg}, '
           'nonce="7ypf/xlj9XXwfDPEoM4URrv/xwf94BcCAzFZH4GiTo0v", '
           'opaque="FQhe/qaU925kfnzjCev0ciny7QMkPqMAFRtzCUYo5tdS"')


@pytest.mark.parametrize("host, soll", [
    ("192.168.1.20", ("192.168.1.20", 5060)),
    (" 192.168.1.20:5062 ", ("192.168.1.20", 5062)),
    ("sip:tuer@192.168.1.20", ("192.168.1.20", 5060)),
    ("SIP:tuer@tuer.local:5070;transport=udp", ("tuer.local", 5070)),
    ("[fe80::1]:5061", ("fe80::1", 5061)),
    ("[fe80::1]", ("fe80::1", 5060)),
    ("fe80::1", ("fe80::1", 5060)),
])
def test_ziel(host, soll):
    assert P.ziel(host) == soll


@pytest.mark.parametrize("host", ["", None, "sip:", "1.2.3.4:abc", "1.2.3.4:0", "1.2.3.4:70000", "[::1]:x"])
def test_ziel_ungueltig(host):
    with pytest.raises(ValueError):
        P.ziel(host)


def test_sip_uri():
    assert P.sip_uri("tuer", "192.168.1.20", 5060) == "sip:tuer@192.168.1.20"
    assert P.sip_uri("", "192.168.1.20", 5062) == "sip:192.168.1.20:5062"
    assert P.sip_uri("tuer", "fe80::1", 5060) == "sip:tuer@[fe80::1]"


def _param(kopf: str) -> dict:
    return {k: v.strip('"') for k, v in re.findall(r'(\w+)=("[^"]*"|[^,\s]+)', kopf)}


def test_digest_rfc2617():
    kopf = P.digest('Digest realm="testrealm@host.com", qop="auth,auth-int", '
                    'nonce="dcd98b7102dd2f0e8b11d0f600bfb0c093", opaque="5ccc069c403ebaf9f0171e9517f40e41"',
                    "Mufasa", "Circle Of Life", "GET", "/dir/index.html", cnonce="0a4f113b")
    assert kopf.startswith("Digest ")
    assert _param(kopf) == {"username": "Mufasa", "realm": "testrealm@host.com",
                            "nonce": "dcd98b7102dd2f0e8b11d0f600bfb0c093", "uri": "/dir/index.html",
                            "response": "6629fae49393a05397450978507c4ef1", "algorithm": "MD5",
                            "cnonce": "0a4f113b", "nc": "00000001", "qop": "auth",
                            "opaque": "5ccc069c403ebaf9f0171e9517f40e41"}


@pytest.mark.parametrize("alg, response", [
    ("MD5", "8ca523f5e9506fed4657c9700eebdbec"),
    ("SHA-256", "753927fa0e85d155564e2e272a28d1802ca10daf4496794697cf8db5856cb6c1"),
])
def test_digest_rfc7616(alg, response):
    kopf = P.digest(RFC7616.format(alg=alg), "Mufasa", "Circle of Life", "GET", "/dir/index.html",
                    cnonce="f2/wE4q74E6zIJEtWaHKaf5wv/H5QzzpXusqGemxURZJ")
    assert _param(kopf)["response"] == response and _param(kopf)["algorithm"] == alg


def _h(x: str) -> str:
    return hashlib.md5(x.encode()).hexdigest()


def test_digest_alte_form_ohne_qop():
    """RFC 2069: ohne qop kein cnonce/nc, response = H(HA1:nonce:HA2)."""
    kopf = P.digest('Digest realm="tuer", nonce="n1"', "tuer", "geheim", "OPTIONS", "sip:tuer@1.2.3.4")
    p = _param(kopf)
    assert p["response"] == _h(f"{_h('tuer:tuer:geheim')}:n1:{_h('OPTIONS:sip:tuer@1.2.3.4')}")
    assert not {"cnonce", "nc", "qop", "opaque"} & set(p)


def test_digest_sess():
    """-sess: HA1 = H(H(user:realm:pass):nonce:cnonce)."""
    kopf = P.digest('Digest realm="tuer", nonce="n1", algorithm=MD5-sess, qop="auth"', "tuer", "geheim",
                    "OPTIONS", "sip:tuer@1.2.3.4", cnonce="c1")
    ha1 = _h(f"{_h('tuer:tuer:geheim')}:n1:c1")
    assert _param(kopf)["response"] == _h(f"{ha1}:n1:00000001:c1:auth:{_h('OPTIONS:sip:tuer@1.2.3.4')}")
    assert _param(kopf)["algorithm"] == "MD5-SESS"


@pytest.mark.parametrize("aufforderung, grund", [
    ('Basic realm="tuer"', "Basic statt Digest"),
    ("", "? statt Digest"),
    ('Digest realm="tuer", nonce="n1", algorithm=SHA-512-256', "SHA-512-256 wird nicht unterstützt"),
])
def test_digest_anderes_verfahren(aufforderung, grund):
    with pytest.raises(ValueError, match=re.escape(grund)):
        P.digest(aufforderung, "tuer", "geheim", "OPTIONS", "sip:tuer@1.2.3.4")


def test_codecs():
    assert P.codecs(TUER_SDP) == ["PCMU/8000", "PCMA/8000", "telephone-event/8000"]
    # ohne rtpmap gelten die festen Nutzlasttypen aus RFC 3551
    assert P.codecs("v=0\r\nm=audio 4000 RTP/AVP 0 8 9 18 97\r\n") == [
        "PCMU/8000", "PCMA/8000", "G722/8000", "G729/8000", "Typ 97"]
    assert P.codecs("v=0\r\nm=video 4002 RTP/AVP 96\r\na=rtpmap:96 H264/90000\r\n") == []
    assert P.codecs("") == [] and P.codecs(None) == []


def test_antwort_lesen():
    a = P.antwort_lesen(b"SIP/2.0 200 OK\r\n"
                        b"v: SIP/2.0/UDP 1.2.3.4:5060;branch=z9hG4bKx\r\n"
                        b"i: abc@loxpanel\r\n"
                        b"CSeq: 1 OPTIONS\r\n"
                        b"Allow: INVITE, ACK,\r\n"
                        b" CANCEL, BYE\r\n"
                        b"Allow: OPTIONS\r\n"
                        b"c: application/sdp\r\n"
                        b"l: 3\r\n\r\nv=0")
    assert (a.code, a.grund, a.rumpf) == (200, "OK", "v=0")
    assert a.wert("call-id") == "abc@loxpanel" and a.wert("via").startswith("SIP/2.0/UDP")
    assert a.alle("allow") == ["INVITE, ACK, CANCEL, BYE", "OPTIONS"]
    assert a.wert("content-type") == "application/sdp" and a.wert("server") == ""
    assert P.antwort_lesen(b"OPTIONS sip:tuer@1.2.3.4 SIP/2.0\r\nCSeq: 1 OPTIONS\r\n\r\n") is None
    assert P.antwort_lesen(b"\x00\x01Muell") is None and P.antwort_lesen(b"") is None


def _kopf(anfrage: str) -> dict:
    return {n.lower(): w for n, w in (z.split(": ", 1) for z in anfrage.split("\r\n")[1:] if ": " in z)}


def _pruefen(tuer: SipTuer, user="tuer", passwort="geheim", **kw) -> dict:
    async def lauf():
        await tuer.start()
        try:
            return await P.pruefen(f"127.0.0.1:{tuer.port}", user, passwort, **kw)
        finally:
            tuer.stop()
    return asyncio.run(lauf())


def test_anmeldung_angenommen():
    tuer = SipTuer()
    erg = _pruefen(tuer)
    assert erg == {"ziel": f"sip:tuer@127.0.0.1:{tuer.port}", "erreichbar": True, "ms": erg["ms"],
                   "antwort": "200 OK", "anmeldung": "angenommen", "gegenstelle": "Nachbau-Tuer/1.0",
                   "methoden": ["INVITE", "ACK", "CANCEL", "BYE", "OPTIONS"],
                   "codecs": ["PCMU/8000", "PCMA/8000", "telephone-event/8000"]}
    assert isinstance(erg["ms"], int) and erg["ms"] >= 0
    erste, zweite = tuer.anfragen
    assert erste.startswith(f"OPTIONS sip:tuer@127.0.0.1:{tuer.port} SIP/2.0\r\n") and erste.endswith("\r\n\r\n")
    k1, k2 = _kopf(erste), _kopf(zweite)
    assert (k1["cseq"], k2["cseq"]) == ("1 OPTIONS", "2 OPTIONS")
    assert k1["call-id"] == k2["call-id"] and k1["from"] == k2["from"] and ";tag=" in k1["from"]
    assert k1["via"] != k2["via"], "jede Transaktion hat einen eigenen branch"
    assert re.fullmatch(r"SIP/2\.0/UDP 127\.0\.0\.1:\d+;branch=z9hG4bK[0-9a-f]+;rport", k1["via"])
    assert k1["max-forwards"] == "70" and k1["content-length"] == "0"
    assert "authorization" not in k1 and k2["authorization"].startswith("Digest ")
    assert not any("geheim" in a for a in tuer.anfragen), "das Passwort geht nie im Klartext raus"


@pytest.mark.parametrize("tuer", [SipTuer(algorithmus="SHA-256"), SipTuer(qop=False), SipTuer(proxy=True)],
                         ids=["sha-256", "ohne-qop", "proxy"])
def test_anmeldung_varianten(tuer):
    erg = _pruefen(tuer)
    assert (erg["antwort"], erg["anmeldung"]) == ("200 OK", "angenommen")
    k2 = _kopf(tuer.anfragen[1])
    auth = k2["proxy-authorization" if tuer.proxy else "authorization"]
    assert ("authorization" in k2) is not tuer.proxy
    assert ("qop=auth" in auth) is tuer.qop and f"algorithm={tuer.algorithmus}" in auth


@pytest.mark.parametrize("user, passwort", [("tuer", "falsch"), ("jemand", "geheim")])
def test_anmeldung_abgelehnt(user, passwort):
    erg = _pruefen(SipTuer(), user, passwort)
    assert erg["erreichbar"] is True
    assert (erg["antwort"], erg["anmeldung"]) == ("403 Forbidden", "abgelehnt")
    assert "error" not in erg


def test_ohne_anmeldung():
    tuer = SipTuer(anmeldung=False)
    erg = _pruefen(tuer)
    assert (erg["antwort"], erg["anmeldung"], erg["gegenstelle"]) == ("200 OK", "nicht verlangt", "Nachbau-Tuer/1.0")
    assert len(tuer.anfragen) == 1


def test_ohne_sdp():
    erg = _pruefen(SipTuer(sdp=False))
    assert (erg["antwort"], erg["anmeldung"]) == ("200 OK", "angenommen") and "codecs" not in erg


def test_kein_passwort():
    """Andere Tuerstationen nennen in den gesicherten Details kein Passwort."""
    tuer = SipTuer()
    erg = _pruefen(tuer, passwort="")
    assert (erg["antwort"], erg["anmeldung"]) == ("401 Unauthorized", "kein Passwort")
    assert len(tuer.anfragen) == 1 and "methoden" not in erg


def test_unbekanntes_verfahren():
    erg = _pruefen(SipTuer(algorithmus="SHA-512-256"))
    assert erg["anmeldung"] == "unbekanntes Verfahren"
    assert erg["error"] == "Digest-Verfahren SHA-512-256 wird nicht unterstützt"


def test_keine_antwort_mit_wiederholung():
    """Ohne Antwort wiederholt die Pruefung nach T1 dieselbe Anfrage (RFC 3261,
    17.1.2.2): bei 1,2 s Wartezeit bei 0 und 0,5 s."""
    tuer = SipTuer(stumm=True)
    erg = _pruefen(tuer, warten=1.2)
    assert erg == {"ziel": f"sip:tuer@127.0.0.1:{tuer.port}", "erreichbar": False,
                   "error": "Keine Antwort: an dieser Adresse meldet sich kein SIP-Dienst"}
    assert len(tuer.anfragen) == 2 and tuer.anfragen[0] == tuer.anfragen[1]


def test_vorlaeufige_antwort_beendet_die_wiederholung(monkeypatch):
    """Nach "100 Trying" weiss die Pruefung, dass die Anfrage ankam: keine
    Wiederholung mehr, sie wartet auf die endgueltige Antwort."""
    monkeypatch.setattr(P, "T1", 0.1)
    tuer = SipTuer(vorlaeufig=0.45)
    erg = _pruefen(tuer)
    assert (erg["antwort"], erg["anmeldung"]) == ("200 OK", "angenommen")
    assert len(tuer.anfragen) == 2, "je Transaktion eine Anfrage, keine Wiederholung nach 100 Trying"


def test_port_geschlossen():
    """Auf dem Port laeuft nichts: ICMP "Port unerreichbar" beendet die Pruefung
    sofort, statt die volle Wartezeit abzuwarten."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    beginn = time.monotonic()
    erg = asyncio.run(P.pruefen(f"127.0.0.1:{port}", "tuer", "geheim", warten=3.0))
    assert time.monotonic() - beginn < 2.0
    assert erg == {"ziel": f"sip:tuer@127.0.0.1:{port}", "erreichbar": False,
                   "error": "Port geschlossen: an dieser Adresse läuft kein SIP-Dienst"}


def test_ungueltige_adresse():
    assert asyncio.run(P.pruefen("1.2.3.4:abc", "tuer", "geheim")) == {
        "ziel": "", "erreichbar": False, "error": "Ungültiger Port in '1.2.3.4:abc'"}


class StoerTuer(SipTuer):
    """Schickt vor jeder Antwort Pakete, die nicht dazugehoeren: ein 200 mit
    fremder Call-ID, eine Antwort mit fremder CSeq, eine Anfrage, ein leeres
    Paket und Muell. Die Pruefung muss sie alle uebergehen."""

    def datagram_received(self, data: bytes, addr) -> None:
        call_id = _kopf(data.decode())["call-id"]
        # asyncio verwirft b"" in sendto(); das leere Paket geht darum ueber
        # eine Kopie des Sockets raus (derselbe Absender-Port)
        roh = socket.socket(fileno=os.dup(self.transport.get_extra_info("socket").fileno()))
        try:
            for paket in ("SIP/2.0 200 OK\r\nCall-ID: fremd@x\r\nCSeq: 1 OPTIONS\r\nUser-Agent: Fremd\r\n\r\n",
                          f"SIP/2.0 486 Busy Here\r\nCall-ID: {call_id}\r\nCSeq: 9 OPTIONS\r\n\r\n",
                          f"OPTIONS sip:loxpanel SIP/2.0\r\nCall-ID: {call_id}\r\nCSeq: 1 OPTIONS\r\n\r\n",
                          "", "\x00\x01Muell"):
                roh.sendto(paket.encode(), addr)
        finally:
            roh.close()
        super().datagram_received(data, addr)


def test_fremde_pakete_werden_uebergangen():
    erg = _pruefen(StoerTuer())
    assert (erg["antwort"], erg["anmeldung"], erg["gegenstelle"]) == ("200 OK", "angenommen", "Nachbau-Tuer/1.0")
