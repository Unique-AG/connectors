LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def url_host(host: str) -> str:
    """`host` as a URL writes it, an IPv6 address in brackets."""
    return f"[{host}]" if ":" in host and not host.startswith("[") else host
