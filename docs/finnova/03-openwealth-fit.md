# Can OpenWealth deliver UN-29657?

**Mostly no.** OpenWealth covers the shared core of wealth data. UN-29657 exists for data that
a direct Finnova connection gives and the bank's current read-only feed does not: the bank's
own classifications, roles, access rights, mandate and strategy data, ESG and revenue
metrics, and value history. The standard models almost none of that.

## The precondition

[OpenWealth-MCP](https://github.com/OpenWealth/OpenWealth-MCP) is a client for a server that
speaks OpenWealth. It does not talk to Finnova. The only known route from Finnova to
OpenWealth is bLink custody services, which works only if the bank is live on bLink as a
custody provider and Unique registers as a bLink service user with each client's consent.

## Ticket tools against the spec

| UN-29657 asks for | OpenWealth |
|---|---|
| **1. Customer master lookup** | **Partly** |
| Look up by any of the bank's identifiers (customer number with and without dots, portfolio ID, warehouse IDs, …) | **No.** `/customers` takes only `cursor` and `limit`; there is no search. A customer has `customerId` and one `externalReference`. |
| Identity, domicile, correspondence language | Yes: `countryOfDomicile`, `language`, addresses with `isDomicile` / `isMailingAddress` |
| Customer type | Roughly: `personType` and `customerSegment` |
| The bank's own risk categories | **Only PEP**, via `kyc.politicalStatus.pepStatus` |
| Servicing roles (investment advisor, relationship manager) | Only free-text names: `bankAdvisor`, `bankDeputyAdvisor` |
| Access rights | **No** |
| **2. Portfolio and positions** | **Partly** |
| Holdings, value, valuation date, portfolio currency | Yes: `ValuatedPosition`, `portfolioInformation.referenceCurrency` |
| List a client's portfolios | Indirectly: group accounts on `portfolioInformation.identification` |
| Portfolio status, investment model and strategy, mandate type, SFDR 8/9, PAI, EET, fee and brokerage income, income-to-AuM | **No** |
| **3. Historical values and performance** | **Weak** |
| Time series | No time-series endpoint. Positions take a `date` parameter that may return a snapshot as of that date, if the provider supports it. A daily series means one call per day, and performance would be computed by us without cash-flow adjustment. |
| Powers of attorney and signing authority (the ticket's alternative) | **Yes.** `person2customerRelation.relationList[].type` (`authorisedSignatoryIndividual`, `authorisedSignatoryCollective`, `beneficialOwner`, …) with `cardinality` |

## OpenWealth-MCP as a dependency

Not a fit. It runs over stdio only and takes one bearer token from an environment variable,
while our servers are hosted and sign in each user. Its three servers wrap the endpoints one
to one: custody (10 read-only tools), trading (18) and customer management (26).

Worth taking from it: the vendored specs and its tool list as a reference. If bLink turns out
to be available at a bank, our scaffold plus `mcp-openapi-codegen` on those specs gives a
client quickly, and our own tools add the joins (portfolio grouping, as-of series).

## When OpenWealth does matter

As a later, cross-bank product: one bLink connector reaches every bank on bLink for standard
holdings, transactions and account information, whatever their core system. For UN-29657 it
can be a fallback for tool 2 and for signing authority at most.
