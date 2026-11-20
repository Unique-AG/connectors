import json

from with_intelligence_mcp.models import OmitNoneModel, WebLinkedRecord


class _Firm(WebLinkedRecord):
    name: str
    website: str | None = None
    phone: str | None = None


class _Plain(OmitNoneModel):
    name: str
    web_url: str | None = None


class TestWebLinkedRecord:
    def test_sends_a_null_web_url_ahead_of_the_website(self) -> None:
        """A present but null link key stops the chat citing the website as the record."""
        firm = _Firm(name="Example Partners", website="https://example.invalid")

        assert json.loads(firm.model_dump_json()) == {
            "web_url": None,
            "name": "Example Partners",
            "website": "https://example.invalid",
        }

    def test_still_omits_every_other_absent_field(self) -> None:
        assert "phone" not in _Firm(name="Example Partners").model_dump()

    def test_a_plain_model_omits_a_null_web_url(self) -> None:
        assert _Plain(name="Example Partners").model_dump() == {"name": "Example Partners"}
