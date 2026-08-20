import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient, BackstopResponseSchemaError
from backstop_mcp.features.party_resolver.search_by_email import (
    looks_like_email,
    normalized_email,
    search_by_email,
)
from tests.features.party_resolver.helpers import BASE_URL


class TestNormalizedEmail:
    def test_returns_normalized_simple_email(self) -> None:
        assert normalized_email("bob@example.com") == "bob@example.com"

    def test_strips_surrounding_whitespace(self) -> None:
        assert normalized_email("  bob@example.com  ") == "bob@example.com"

    def test_extracts_address_from_display_name_form(self) -> None:
        assert normalized_email('"Bob Smith" <bob@example.com>') == "bob@example.com"

    def test_returns_none_for_plain_name(self) -> None:
        assert normalized_email("Capstone Partners") is None


class TestLooksLikeEmail:
    def test_accepts_simple_email(self) -> None:
        assert looks_like_email("bob@example.com") is True

    def test_accepts_email_with_surrounding_whitespace(self) -> None:
        assert looks_like_email("  bob@example.com  ") is True

    def test_accepts_display_name_form(self) -> None:
        assert looks_like_email('"Bob Smith" <bob@example.com>') is True

    def test_rejects_missing_local_part(self) -> None:
        assert looks_like_email("@example.com") is False

    def test_rejects_missing_domain(self) -> None:
        assert looks_like_email("bob@") is False

    def test_rejects_plain_name(self) -> None:
        assert looks_like_email("Capstone Partners") is False

    def test_rejects_empty_string(self) -> None:
        assert looks_like_email("") is False

    def test_rejects_double_at(self) -> None:
        assert looks_like_email("a@@b") is False

    def test_rejects_at_with_spaces(self) -> None:
        assert looks_like_email("@ @") is False

    def test_rejects_domain_without_period(self) -> None:
        assert looks_like_email("bob@example") is False


class TestSearchByEmailSchemaValidation:
    @pytest.mark.asyncio
    @respx.mock
    async def test_malformed_resource_raises_schema_error(self, client: BackstopClient) -> None:
        email = "ops@capstone.com"
        respx.get(f"{BASE_URL}/organizations", params={"filter[email][eq]": email}).mock(
            return_value=httpx.Response(
                200,
                # No `id` field at all — fails BackstopApiResource schema validation, the same
                # way a present-but-blank id does (see test_resolve.py's equivalent case).
                json={"data": [{"type": "organizations", "attributes": {"name": "Capstone"}}]},
            )
        )

        with pytest.raises(BackstopResponseSchemaError) as exc_info:
            await search_by_email(client, search_type="organizations", email=email)

        assert exc_info.value.path == "/organizations"
        assert exc_info.value.schema_name == "BackstopApiCollectionDocument[PartyAttributes]"
