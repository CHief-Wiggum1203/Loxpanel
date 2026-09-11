"""Anmeldung am Loxone-Audioserver (Gen 2) ueber den remotecontrol-WebSocket.

Ein mit dem Miniserver gekoppelter Audioserver nimmt Befehle nur von
angemeldeten Verbindungen an. Der Ablauf ist der der Loxone-App (aus dem
Quellcode der Loxone-Weboberflaeche, AudioServerDataSource._authenticate):

  1. Banner beim Connect:  "LWSS V <fw> | ~API:<api>~ | Session-Token: <tok>"
  2. audio/cfg/getkey   -> {"getkey_result":[{"exp":65537,"pubkey":"<hex>"}]}
  3. AES-256-CBC (PKCS7) mit zufaelligem Schluessel/IV ueber das Miniserver-JWT
     des Benutzers; die App nutzt CryptoJS.AES.encrypt(jwt, passphrase) und
     schickt key/iv aus dem Ergebnis, das entspricht zufaelligem key/iv.
  4. RSA-PKCS#1-v1.5 (JSEncrypt) mit dem Audioserver-Schluessel ueber
     "<keyHex>:<ivHex>:<sessionToken>".
  5. secure/authenticate/<benutzer>/<urlenc(rsa b64)>/<urlenc(chiffre b64)>
     -> {"authenticate_result":"authentication successful"}

Danach beantwortet dieselbe Verbindung Befehle wie audio/cfg/getroomfavs.
Benoetigt das Paket `cryptography` (requirements.txt).
"""
from __future__ import annotations

import base64
import os
import re
from urllib.parse import quote

try:
    from cryptography.hazmat.primitives import padding as _padding
    from cryptography.hazmat.primitives.asymmetric import padding as _apadding
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    HAVE_CRYPTO = True
except ImportError:            # Server laeuft weiter, nur ohne Anmeldung
    HAVE_CRYPTO = False

GREETING_RE = re.compile(r"^LWSS V (?P<firmware>\S+) \| ~API:(?P<api>[^~]*)~ \| Session-Token: (?P<token>.+)$")
AUTH_OK = "authentication successful"


def parse_greeting(text: str) -> dict | None:
    """Banner des Audioservers -> {"firmware", "api", "token"} oder None."""
    m = GREETING_RE.match((text or "").strip())
    return m.groupdict() if m else None


def public_key_from_getkey(result) -> "object | None":
    """RSA-Public-Key aus getkey_result ([{"exp":65537,"pubkey":"<hex modulus>"}])."""
    if not HAVE_CRYPTO:
        return None
    entries = result.get("getkey_result") if isinstance(result, dict) else result
    if isinstance(entries, list) and entries:
        entries = entries[0]
    if not isinstance(entries, dict):
        return None
    try:
        exp = int(entries.get("exp") or 65537)
        mod = int(str(entries.get("pubkey") or ""), 16)
    except (TypeError, ValueError):
        return None
    if mod <= 0:
        return None
    return RSAPublicNumbers(exp, mod).public_key()


def build_authenticate(user: str, jwt: str, session_token: str, public_key) -> str:
    """Den secure/authenticate-Befehl fuer diese Verbindung bauen."""
    if not HAVE_CRYPTO:
        raise RuntimeError("Paket 'cryptography' fehlt")
    key, iv = os.urandom(32), os.urandom(16)
    padder = _padding.PKCS7(128).padder()
    data = padder.update(jwt.encode("utf-8")) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    cipher_b64 = base64.b64encode(enc.update(data) + enc.finalize()).decode("ascii")
    rsa_plain = f"{key.hex()}:{iv.hex()}:{session_token}".encode("utf-8")
    rsa_b64 = base64.b64encode(public_key.encrypt(rsa_plain, _apadding.PKCS1v15())).decode("ascii")
    return f"secure/authenticate/{user}/{quote(rsa_b64, safe='')}/{quote(cipher_b64, safe='')}"


def auth_result(msg) -> str | None:
    """authenticate_result aus einer Antwort (auch verschachtelt) oder None."""
    if isinstance(msg, dict):
        if "authenticate_result" in msg:
            return str(msg.get("authenticate_result") or "")
        for v in msg.values():
            r = auth_result(v)
            if r is not None:
                return r
    elif isinstance(msg, list):
        for v in msg:
            r = auth_result(v)
            if r is not None:
                return r
    return None
