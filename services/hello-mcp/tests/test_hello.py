from hello_mcp.main import hello


def test_hello_returns_greeting() -> None:
    assert hello("World") == "Hello, World!"


def test_hello_includes_name() -> None:
    assert hello("Alice") == "Hello, Alice!"
