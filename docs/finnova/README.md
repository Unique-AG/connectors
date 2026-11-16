# Finnova research

What we know about Finnova before we get API docs and a sandbox, and how we plan to build
the first Finnova MCP ([UN-29657](https://unique-ch.atlassian.net/browse/UN-29657), epic
UN-24672). Written 2026-11-16 from public sources only. Nothing here comes from Finnova's
Partner Portal or from a bank's environment yet.

> **Public repository.** This folder is not gitignored. Keep client names, people's names,
> internal Confluence links and a bank's own codes or configuration out of it. When the pilot
> bank's docs arrive, put what they reveal in a gitignored subfolder (as `docs/backstop/` does
> for its client set) and keep only the standard Finnova facts here.

| File | Answers the question |
|---|---|
| [01-finnova-landscape.md](01-finnova-landscape.md) | What Finnova is, which ways in exist today, and where a bank's data actually lives. |
| [02-openwealth-data-model.md](02-openwealth-data-model.md) | The public OpenWealth / bLink model a Finnova bank can expose: customers, accounts, positions, transactions, persons. |
| [03-openwealth-fit.md](03-openwealth-fit.md) | Can OpenWealth, or the existing OpenWealth MCP, deliver UN-29657? (Mostly no.) |
| [04-architecture.md](04-architecture.md) | How the MCP handles each bank's own codes and data sources: fixed tools, discovery tools, the adapter boundary, and how far a cross-bank standard holds. |
| [05-preparation-plan.md](05-preparation-plan.md) | The two DAGs: questions to answer before coding, and the implementation order that ships soonest. |

## The short version

- Finnova's current core has **no general-purpose API**, only use-case-specific "threads".
  The API that exposes everything, **finnova.neo**, is not expected before end of 2027.
- Finnova's REST docs are OpenAPI, behind a **Partner Portal** that needs registration.
- **bLink** (SIX) is a hub that routes requests to each bank's own implementation of a
  standard API. It does not aggregate data. Its custody and customer APIs follow
  **OpenWealth**.
- OpenWealth covers the shared core (customer, account, position, transaction, signing
  authority) but **not** the bank-specific data UN-29657 is about, so it is not the path for
  the first version.
- Much of what the ticket wants likely sits in the bank's **configuration** or its **own
  systems** (data warehouse, aggregation layer), not in standard Finnova.
- Plan: **fixed tools** for the core questions, behind a **per-bank adapter**. Code labels are
  read at runtime. Read-only **discovery tools** over the bank's warehouse come in only if it
  enforces each user's access itself. Standardize across banks at bank 2, not before.
