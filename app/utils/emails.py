"""Email canonicalization.

A single normal form for addresses so case and whitespace variants of the same
inbox cannot become separate accounts. Applied at every write and lookup path
(signup, login, password reset, OAuth linking).
"""


def normalize_email(email: str) -> str:
    """Return the canonical form of an email: trimmed and lower-cased.

    Domains are case-insensitive, and every mainstream provider treats the
    local part that way too, so lower-casing the whole address is the safe,
    duplicate-proof choice.
    """
    return email.strip().lower()
