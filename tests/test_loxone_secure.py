"""Verschluesselte Befehle an den Miniserver (bin/loxone_secure.py). Die
Gegenseite ist hier unabhaengig nach der Loxone-Doku ("Communicating with the
Miniserver" 16.0, Command Encryption) mit cryptography nachgebaut: eigener
RSA-Schluessel, Sitzungsschluessel entschluesseln, Befehl entschluesseln."""
import base64
import hashlib
import hmac
from urllib.parse import unquote

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.x509.oid import NameOID

import loxone_secure as S

SCHLUESSEL = rsa.generate_private_key(public_exponent=65537, key_size=1024)


def _spki_b64() -> str:
    der = SCHLUESSEL.public_key().public_bytes(serialization.Encoding.DER,
                                               serialization.PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(der).decode("ascii")


def _miniserver_entschluesselt(pfad: str) -> tuple[str, bytes, bytes]:
    """Wie der Miniserver: sk mit dem privaten Schluessel oeffnen, dann den
    Befehl. -> (Klartext ohne Nullbytes, key, iv)"""
    assert pfad.startswith("jdev/sys/fenc/") and "?sk=" in pfad
    chiffre, sk = pfad[len("jdev/sys/fenc/"):].split("?sk=")
    key_hex, iv_hex = SCHLUESSEL.decrypt(base64.b64decode(unquote(sk)), padding.PKCS1v15()).decode().split(":")
    key, iv = bytes.fromhex(key_hex), bytes.fromhex(iv_hex)
    roh = base64.b64decode(unquote(chiffre))
    assert len(roh) % 16 == 0
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    klar = dec.update(roh) + dec.finalize()
    assert klar.endswith(b"\0"), "Nullbytes als Ende und Auffuellung"
    return klar.rstrip(b"\0").decode(), key, iv


@pytest.mark.parametrize("text", [
    f"-----BEGIN CERTIFICATE-----{_spki_b64()}-----END CERTIFICATE-----",        # so liefert ihn der Miniserver
    f"-----BEGIN PUBLIC KEY-----\n{_spki_b64()}\n-----END PUBLIC KEY-----\n",
    _spki_b64(),
], ids=["miniserver", "pem", "nur-base64"])
def test_oeffentlicher_schluessel(text):
    key = S.public_key_from_pem(text)
    assert key.public_numbers() == SCHLUESSEL.public_key().public_numbers()


def test_echtes_zertifikat_geht_auch():
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ms")])
    import datetime as dt
    jetzt = dt.datetime(2026, 1, 1)
    zert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(SCHLUESSEL.public_key()).serial_number(1)
            .not_valid_before(jetzt).not_valid_after(jetzt + dt.timedelta(days=1))
            .sign(SCHLUESSEL, hashes.SHA256()))
    pem = zert.public_bytes(serialization.Encoding.PEM).decode()
    assert S.public_key_from_pem(pem).public_numbers() == SCHLUESSEL.public_key().public_numbers()


@pytest.mark.parametrize("text", ["", "kein Schluessel", "-----BEGIN CERTIFICATE-----!!-----END CERTIFICATE-----",
                                  base64.b64encode(b"irgendwas").decode(), None, 42])
def test_kein_schluessel(text):
    assert S.public_key_from_pem(text) is None


@pytest.mark.parametrize("cmd, bloecke", [
    ("jdev/sps/io/0b734138-0123-1234-ffffeeeeddddcccc/securedDetails?autht=ab12&user=lox%20panel", 7),
    ("jdev/sps/io/0123456789", 3),            # "salt/abcd/" + Befehl fuellt genau 2 Bloecke: das Ende-Nullbyte braucht einen dritten
])
def test_befehl_verschluesseln(cmd, bloecke):
    enc = S.encrypt_command(cmd, SCHLUESSEL.public_key())
    klar, key, iv = _miniserver_entschluesselt(enc.pfad)
    salz, rest = klar[len("salt/"):].split("/", 1)
    assert klar.startswith("salt/") and len(salz) == 2 * S.SALZ_BYTES and int(salz, 16) >= 0
    assert rest == cmd and (key, iv) == (enc.key, enc.iv) and len(key) == 32 and len(iv) == 16
    chiffre = enc.pfad[len("jdev/sys/fenc/"):].split("?sk=")[0]
    assert len(base64.b64decode(unquote(chiffre))) == 16 * bloecke


def test_jedes_mal_neuer_schluessel_und_neues_salz():
    a = S.encrypt_command("jdev/sps/io/0123456789", SCHLUESSEL.public_key())
    b = S.encrypt_command("jdev/sps/io/0123456789", SCHLUESSEL.public_key())
    assert a.key != b.key and a.iv != b.iv and a.pfad != b.pfad


def _antwort(text: str, key: bytes, iv: bytes) -> bytes:
    roh = text.encode() + b"\0" * (-len(text.encode()) % 16)
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return base64.b64encode(enc.update(roh) + enc.finalize())


def test_antwort_entschluesseln():
    key, iv = bytes(range(32)), bytes(range(16))
    text = '{"LL": {"control": "x", "value": "{\\"audioInfo\\":{}}", "Code": "200"}}'
    assert S.decrypt_response(_antwort(text, key, iv), key, iv) == text
    assert S.decrypt_response(b'"' + _antwort(text, key, iv) + b'"\n', key, iv) == text


@pytest.mark.parametrize("body", [b"", b"kein base64!", base64.b64encode(b"zu kurz"), b"Unauthorized"])
def test_antwort_kaputt(body):
    with pytest.raises(ValueError):
        S.decrypt_response(body, bytes(32), bytes(16))


@pytest.mark.parametrize("alg, fn", [("SHA1", hashlib.sha1), ("SHA256", hashlib.sha256), ("sha256", hashlib.sha256)])
def test_token_hash(alg, fn):
    key_hex = "41424344"
    assert S.token_hash(key_hex, "jwt.token", alg) == hmac.new(b"ABCD", b"jwt.token", fn).hexdigest()
