"""Password hashing.

bcrypt directly: it salts internally and the hash carries its own parameters,
so verification needs nothing but the stored string. Kept separate from
session signing because the two solve different problems.
"""

import bcrypt


def hash_password(plain: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode(), salt).decode()


def verify_password(plain: str, hashed: str | None) -> bool:
    """True only if `plain` matches a real stored hash.

    OAuth-only accounts have no password_hash; a None here is a definite
    "this account has no password to check", not an error.
    """
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False
