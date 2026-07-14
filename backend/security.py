"""Password hashing with the standard library only (hashlib.scrypt).

Produces and verifies hashes in Werkzeug's format
(``scrypt:N:r:p$salt$hex``) so the values in users.password stay
compatible with the original Flask app — no werkzeug dependency needed.
"""

import hashlib
import hmac
import secrets
import string

_SALT_CHARS = string.ascii_letters + string.digits
_SALT_LENGTH = 16
_N, _R, _P = 32768, 8, 1
# scrypt needs 128*N*r bytes; the default OpenSSL cap (32MiB) is too low.
_MAXMEM = 132_072_960


def _scrypt_hex(password: str, salt: str, n: int, r: int, p: int) -> str:
    return hashlib.scrypt(
        password.encode(), salt=salt.encode(), n=n, r=r, p=p, maxmem=_MAXMEM
    ).hex()


def hash_password(password: str) -> str:
    salt = "".join(secrets.choice(_SALT_CHARS) for _ in range(_SALT_LENGTH))
    return f"scrypt:{_N}:{_R}:{_P}${salt}${_scrypt_hex(password, salt, _N, _R, _P)}"


def verify_password(stored: str, password: str) -> bool:
    try:
        method, salt, hashval = stored.split("$", 2)
        scheme, n, r, p = method.split(":")
        if scheme != "scrypt":
            return False
        computed = _scrypt_hex(password, salt, int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(computed, hashval)
