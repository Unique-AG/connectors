from urllib.parse import parse_qsl, urlparse

UI_BASE = "https://tenant.example.test"


def path_and_query(url: str) -> str:
    parsed = urlparse(url)
    if parsed.query:
        return f"{parsed.path}?{parsed.query}"
    return parsed.path


def query_params(url: str) -> dict[str, str]:
    return dict(parse_qsl(urlparse(url).query, keep_blank_values=True))
