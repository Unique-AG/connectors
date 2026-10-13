from pydantic import BaseModel, Field

from tiingo_mcp.params import StrDate


class FinancialPeriod(BaseModel):
    date: StrDate | None = Field(
        None, description="Date the statements were released to the public."
    )
    year: int | None = Field(None, description="Fiscal year.")
    quarter: int | None = Field(None, description="Fiscal quarter, 1 to 4.")
    statements: dict[str, dict[str, float | None]] = Field(
        description="Section name (overview, incomeStatement, balanceSheet, cashFlow) mapped to "
        "its Tiingo data codes and their values."
    )
