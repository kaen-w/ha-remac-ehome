"""Minimal PKCS#1 v1.5 RSA encryption (standard library only).

The REMAC cloud publishes a 1024-bit RSA public key at
``POST /sl/home/config/getConfig`` with ``{"type": "rsa"}`` and expects the
login password as ``base64(RSA_PKCS1v15(password))``.

Kept dependency-free so the integration works on a stock Home Assistant
installation without extra ``requirements``.
"""

from __future__ import annotations

import base64
import os

__all__ = ["encrypt", "parse_public_key"]


def _read_tlv(buf: bytes, idx: int) -> tuple[int, bytes, int]:
    """Read one BER/DER TLV triple starting at ``idx``."""
    tag = buf[idx]
    idx += 1
    length = buf[idx]
    idx += 1
    if length & 0x80:
        nbytes = length & 0x7F
        length = int.from_bytes(buf[idx : idx + nbytes], "big")
        idx += nbytes
    return tag, buf[idx : idx + length], idx + length


def parse_public_key(public_key_b64: str) -> tuple[int, int]:
    """Return ``(modulus, exponent)`` from a base64 SubjectPublicKeyInfo."""
    der = base64.b64decode(public_key_b64)
    _, outer, _ = _read_tlv(der, 0)  # SEQUENCE
    _, _, after_alg = _read_tlv(outer, 0)  # AlgorithmIdentifier
    _, bit_string, _ = _read_tlv(outer, after_alg)  # BIT STRING
    _, rsa_key, _ = _read_tlv(bit_string[1:], 0)  # skip unused-bits octet
    _, modulus_bytes, offset = _read_tlv(rsa_key, 0)
    _, exponent_bytes, _ = _read_tlv(rsa_key, offset)
    return int.from_bytes(modulus_bytes, "big"), int.from_bytes(exponent_bytes, "big")


def encrypt(plaintext: str, public_key_b64: str) -> str:
    """RSA/PKCS#1 v1.5 encrypt ``plaintext`` and return base64."""
    modulus, exponent = parse_public_key(public_key_b64)
    size = (modulus.bit_length() + 7) // 8
    message = plaintext.encode()
    if len(message) > size - 11:
        raise ValueError("plaintext too long for the RSA key size")

    pad_len = size - 3 - len(message)
    padding = b""
    while len(padding) < pad_len:
        padding += bytes(b for b in os.urandom(pad_len - len(padding)) if b != 0)
    block = b"\x00\x02" + padding + b"\x00" + message
    cipher = pow(int.from_bytes(block, "big"), exponent, modulus)
    return base64.b64encode(cipher.to_bytes(size, "big")).decode()
