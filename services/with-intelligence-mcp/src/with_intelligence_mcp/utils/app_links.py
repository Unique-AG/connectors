"""Links to the With Intelligence web app, which addresses records by the ids the v3 API returns.

The app documents none of these. They were read off the app's own pages and checked against
the API (UN-30437). They open only for a user signed in to With Intelligence.
"""

from typing import Literal
from urllib.parse import quote, urlsplit

_APP_BASE_URL = "https://platform.withintelligence.com"
_CMS_UPLOADS_PATH = "/wp-content/uploads/"

APP_LINK_DESCRIPTION = (
    "Its page in the With Intelligence app. It opens for a user signed in to With Intelligence."
)

type ExploreCollection = Literal[
    "consultants", "funds", "investors", "managers", "mandates", "people"
]


def explore_url(collection: ExploreCollection, record_id: int) -> str:
    return f"{_APP_BASE_URL}/explore/{collection}/{record_id}"


def article_url(article_id: int, slug: str | None) -> str:
    # The app finds the article by `a` alone and ignores the slug, so any slug opens it.
    return f"{_APP_BASE_URL}/insights/{quote(slug or 'article', safe='')}?a={article_id}"


def attachment_url(cms_url: str) -> str:
    """The app's link to an article attachment the API gives as a CMS upload.

    The app serves the CMS's `/wp-content/uploads/<path>` under `/files/<path>` to a signed-in
    user, so citing it keeps the With Intelligence login.
    """
    path = urlsplit(cms_url).path
    if not path.startswith(_CMS_UPLOADS_PATH):
        return cms_url
    return f"{_APP_BASE_URL}/files/{path.removeprefix(_CMS_UPLOADS_PATH)}"
