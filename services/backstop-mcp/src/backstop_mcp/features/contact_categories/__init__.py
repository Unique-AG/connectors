"""Standard Backstop contact-category vocabulary.

Contact categories are a CRM relationship on people and organizations
(`relationships.categories`), not a custom field. `ListContactCategoriesQuery` walks
`GET /contact-categories`; `list_contact_categories` publishes it. Caching is off by
default — the collection is small enough to walk.
"""

from backstop_mcp.features.contact_categories.api_responses import ContactCategoryAttributes
from backstop_mcp.features.contact_categories.dependencies import (
    get_list_contact_categories_query_factory,
)
from backstop_mcp.features.contact_categories.internal_dto import ContactCategoryDto
from backstop_mcp.features.contact_categories.queries import ListContactCategoriesQuery
from backstop_mcp.features.contact_categories.responses import (
    ContactCategoryResponse,
    ListContactCategoriesResponse,
)

__all__ = [
    "ContactCategoryAttributes",
    "ContactCategoryDto",
    "ContactCategoryResponse",
    "ListContactCategoriesQuery",
    "ListContactCategoriesResponse",
    "get_list_contact_categories_query_factory",
]
