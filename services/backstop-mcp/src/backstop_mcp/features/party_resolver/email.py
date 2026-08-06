def looks_like_email(value: str) -> bool:
    """Return True when `value` has a non-empty local and domain around `@`."""
    local, separator, domain = value.strip().partition("@")
    return separator == "@" and bool(local) and bool(domain)
