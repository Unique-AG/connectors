# Architecture for a Finnova MCP

Each Finnova bank differs in its codes, in which modules and release it runs, and in where
data outside the core lives. These are the decisions on how the MCP absorbs that.

## Three layers per bank

| Layer | Example | Same across banks? |
|---|---|---|
| Finnova standard | Core entities, the Partner API's shape | Yes, apart from release and licensed modules |
| Bank configuration | Risk categories, customer segments, mandate types, roles, access rules | Structure yes, codes and meanings no |
| Bank-built systems | Data warehouse IDs, value history in a warehouse, an aggregation layer | No |

## Code labels: read at runtime

Code meanings differ per bank, so the server learns them and never hardcodes them.

- Load the bank's code tables at startup and cache them app-wide. They come from a Finnova
  code-table endpoint if one exists, otherwise from per-bank configuration.
- Tool output carries code and label together, for example
  `riskCategory: {code: "…", label: "…"}`, so the agent reads the label and never guesses.
- Expose the tables as an MCP resource or a small lookup tool, so the agent can answer "what
  does code X mean at this bank".

## Data paths: fixed tools, plus discovery where the source allows it

```
Agent
  │
  ├─ fixed tools        find_customer, get_portfolios, get_value_history, get_signing_authority
  │                     deterministic, tested; for the questions that must be exact
  │
  └─ discovery tools    describe_catalog, lookup_codes, query (read-only, as the signed-in user)
                        adapts to each bank's warehouse; for the long tail
  ▼
Our model           Customer, Portfolio, Position, ValuePoint, Authority (pydantic)
  │                 + code tables → labels
  ▼
Per-bank adapter    configuration: canonical field → source + mapping
  ├─ Finnova Partner API (threads)
  ├─ bank aggregation layer / data warehouse
  └─ (later) bLink / OpenWealth for standard holdings
```

### Fixed tools

- The **same tool surface for every bank**, so prompts, skills and evals carry over.
- The differences between banks live in the **adapter configuration**, reviewed and versioned
  per deployment.
- A field with no mapping at a bank comes back as **not available at this bank**. The tool
  does not go looking for it.
- **Financial calculations stay in code.** Performance needs time-weighted returns, cash-flow
  adjustment and currency conversion. An agent assembling that from raw rows produces
  plausible, wrong numbers.

### Discovery tools

Letting the agent read the warehouse's catalog, work out which data model holds what, and
query it is a valid design, and it adapts to each bank without a new adapter. It is safe only
when all of these hold:

1. **The source enforces access per user.** The agent queries as the signed-in user and the
   warehouse applies the bank's access rights and row-level security itself. Relying on the
   agent to filter what a technical account returns fails the bank's review.
2. **Read-only.**
3. **The catalog describes structure, not just codes.** A code label says what a value means,
   not where it is stored, how it joins to the customer or which row is current. The agent
   needs table and column descriptions, relationships and validity dates.
4. **Every query is logged**, so the bank can audit what was asked.

The Finnova API itself is not a discovery target: its use-case threads have no catalog to
explore.

## Using an agent at onboarding, not at runtime

Working out a new bank's data paths is a job for an agent at **onboarding**, not on every
request. An internal skill reads the bank's API docs and samples and drafts the adapter
mapping and code tables. An engineer reviews them, records the probes, and ships the result
as configuration.

## How far a cross-bank standard holds

Likely to hold:

- The core entities (customer, person, portfolio, position, valuation, signing authority).
  OpenWealth working across banks on different core systems is evidence of that.
- The questions agents ask.
- Finnova's own API shape, apart from release and module differences.

Likely to break:

- Code values. Per-bank configuration handles them.
- Extra fields, present at some banks, absent or different at others.
- Where data lives (core, warehouse, nowhere). The least portable part.
- Hosting, network and sign-in per bank.

So do not design the standard up front:

1. Build for the pilot bank, behind the adapter boundary (tools → our models → adapter).
2. Keep the models narrow, plus a labelled `bankSpecific` bag for fields we cannot place yet.
3. Extract the canonical model at bank 2, from what both banks actually share.

When finnova.neo ships, the bank-specific part should shrink to the code tables. That is
another reason to keep the adapter boundary and not hard-wire a warehouse into the tools.
