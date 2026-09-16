"""Standard Backstop contact-source vocabulary.

Contact Source is a CRM field on people and organizations (`relationships.contactSource`),
not a custom field. `ListContactSourcesQuery` walks `GET /contact-sources`;
`list_contact_sources` publishes it. Caching is off by default — the collection is small.
"""

from backstop_mcp.features.contact_sources.api_responses import ContactSourceAttributes
from backstop_mcp.features.contact_sources.dependencies import (
    get_list_contact_sources_query_factory,
)
from backstop_mcp.features.contact_sources.internal_dto import ContactSourceDto
from backstop_mcp.features.contact_sources.queries import ListContactSourcesQuery
from backstop_mcp.features.contact_sources.responses import (
    ContactSourceResponse,
    ListContactSourcesResponse,
)

__all__ = [
    "ContactSourceAttributes",
    "ContactSourceDto",
    "ContactSourceResponse",
    "ListContactSourcesQuery",
    "ListContactSourcesResponse",
    "get_list_contact_sources_query_factory",
]
