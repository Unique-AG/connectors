# Preparation plan

Two DAGs. The first is the questions that block design. The second is the implementation
order, arranged so that everything not needing API access is done before the docs and
sandbox arrive, and the critical path after that is as short as possible.

## DAG 1: questions to answer before coding

```mermaid
flowchart TD
  Q1[Q1 Access paths: which interfaces exist?<br/>Finnova threads, aggregation layer, DWH, bLink; a sandbox for each?]
  Q2[Q2 Auth and network: per-user or technical account?<br/>VPN or private link? where may we host?]
  Q3[Q3 Field to source map: each ticket field to its interface,<br/>and is it Finnova standard, bank configuration or bank-own]
  Q4[Q4 Identifiers: which ID is primary,<br/>how every other ID maps to it]
  Q5[Q5 Entitlements: does the source enforce the bank's<br/>access rights, or must we?]
  Q6[Q6 Code tables: where do labels for risk categories,<br/>mandate types and segments come from?]
  Q7[Q7 History: are daily values stored, in the core or the DWH?<br/>is performance computed by the bank or by us?]
  Q8[Q8 Operations: rate limits, freshness EOD vs intraday,<br/>how realistic is the sandbox data?]
  Q9[Q9 Data protection: may sandbox recordings live in the repo?]
  G{{Gate: first tool scope agreed}}

  Q1 --> Q2
  Q1 --> Q3
  Q1 --> Q8
  Q2 --> Q5
  Q2 --> Q9
  Q3 --> Q4
  Q3 --> Q5
  Q3 --> Q6
  Q3 --> Q7
  Q3 --> G
  Q4 --> G
  Q5 --> G
  Q7 --> G
```

Q1 to Q3 are the roots. Send the full list to the bank before the docs arrive, so the answers
come back with them.

For Q7, ask what "the time series live in Finnova" means: the core, reachable through a
thread, or the bank's warehouse. The answer decides where `get_value_history` reads from.

## DAG 2: implementation

```mermaid
flowchart TD
  subgraph now[Now, no access needed]
    A[A Use cases and evals<br/>how-banks-use-finnova.md, agent-use-cases.md, evals/cases.yaml]
    B[B Scaffold finnova-mcp with new-mcp,<br/>deploy one stub tool to qa]
    C[C Our pydantic models and tool signatures,<br/>backed by an in-memory fake adapter]
    D[D Send the DAG 1 questions]
  end
  subgraph after[After docs and sandbox]
    E[E Probe the sandbox, record to docs/json,<br/>spec to spec/, generate the client]
    F[F Real adapter: recorded responses to our models]
    G[G Swap the fake adapter for the real one,<br/>replay tests]
    H[H Evals against the sandbox]
    I[I Deploy qa then uat]
  end
  D --> E
  E --> F
  C --> F
  F --> G
  G --> H
  A --> H
  G --> I
  B --> I
```

| Step | Needs | Notes |
|---|---|---|
| A | Ticket, product pages | Fixes what "done" means before code exists, as `polixis-mcp/docs/` did. |
| B | Nothing | Takes the chart, Argo and auth plumbing off the critical path. |
| C | Nothing | Tests and evals run against the fake until the real adapter lands. |
| D | Nothing | The DAG 1 list. |
| E | Docs, sandbox, Q1, Q2 | Record every probe. Their sandbox may be down or rationed, as with Backstop and Polixis. |
| F | C, E, Q3, Q4, Q6 | Mapping and code tables per bank. |
| G | F | Replay tests run without credentials. |
| H | A, G | Grade the calls made and whether the answer holds to what the tools returned. |
| I | B, G | One stacked PR per sub-task. |

## Ship in slices

Each slice runs E → I on its own, so the first one deploys while a later one still waits on
the bank.

1. `find_customer`. Every other tool joins on it.
2. `get_portfolios` with positions.
3. `get_value_history`, once Q7 is answered. Or `get_signing_authority` if history is blocked.

## Lessons from the repo

- **`polixis-mcp`** is the pattern UN-29657 names: use-case docs first, tools of our own,
  then record and replay.
- **`temenos-mcp`**, our other core banking connector, takes the opposite approach: 49 tools,
  one per DataHub endpoint. For Finnova, follow Polixis. The fixed tools have to be exact, and
  discovery tools cover the long tail if a bank's warehouse allows them.
