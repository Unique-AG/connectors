from pydantic import Field

from kyckr_mcp.upstream import BaseResponse
from kyckr_mcp.upstream import OrderDetails


class OrderData(OrderDetails):
    document_json: dict[str, object] | None = Field(
        None,
        alias="documentJson",
        description=(
            "Structured view of the ordered document, added once `status` is `Success`. Field "
            "names are PascalCase (Kyckr download-endpoint convention). Absent while `status` is "
            "`Pending` or `Failed`, and when the registry has no JSON view of the filing, in "
            "which case `details` says the document is PDF-only."
        ),
    )


class OrderResult(BaseResponse):
    data: OrderData | None = None
