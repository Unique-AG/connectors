from pydantic import BaseModel


class Quote(BaseModel):
    ticker: str
    last_price: float | None
    previous_close: float | None
    as_of: str | None
