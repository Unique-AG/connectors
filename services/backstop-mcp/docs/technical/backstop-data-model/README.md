# Backstop data model

## Overview

A reference for developers changing Backstop MCP. It explains how the Backstop REST API behaves and
what Backstop's standard data model is, independent of this server's tools. It holds for every
Backstop tenant; a tenant's own custom fields, lists and stage names are not covered. To use or
operate the server, read the [Technical Reference](../README.md) and the
[Operator Guide](../../operator/README.md) instead.

## How to read it

1. Start with [Basics](./basics.md). It explains what Backstop stores, how the record types fit
   together, and the words Backstop uses everywhere. Every other chapter assumes it.
2. Read [Reading the API](./reading-the-api.md) before calling the API yourself. It covers
   authentication, the response format, paging, filters and sorting.
3. Read the rest in table order, or in any order that respects each chapter's **Before you read**
   box. That box links to what the chapter assumes.

## Chapters

| # | Chapter | What it covers |
|---|---|---|
| 1 | [Basics](./basics.md) | What Backstop is, the record families, ids, collections, Backstop's vocabulary |
| 2 | [Reading the API](./reading-the-api.md) | Authentication, response format, related data, paging, filters, sorting, limits, saved reports |
| 3 | [Contacts: organizations and people](./contacts.md) | Organizations, people, contacts, employees, addresses, emails, categories, system users, quick search |
| 4 | [Entity relationships](./entity-relationships.md) | Typed links between records, mirror rows, employment |
| 5 | [Activities](./activities.md) | Notes, meetings and calls, emails, documents, tasks, tags, the activity search |
| 6 | [Products and accounts](./products-and-accounts.md) | Funds, share classes, investor accounts, balances and other time series, subscriptions and redemptions |
| 7 | [Opportunities](./opportunities.md) | The sales pipeline, stages, stage history |
| 8 | [Custom fields and reference data](./custom-fields-and-reference-data.md) | Custom field definitions and values, lists of values, entity types, permission buckets, system info |
| 9 | [Writing data](./writing-data.md) | Payload rules for creating and changing records, bulk endpoints |
| 10 | [Errors](./errors.md) | Every error we have seen, what causes it, what to do |

## Conventions

- **Backstop's own names.** Collections, fields and relationships are written in `code` exactly as
  the API spells them (`meeting-or-calls`, `regularCustomFieldValues`).
- **How sure we are.** Most statements come from live API responses. Where it matters, a statement
  ends with one of these markers, always in this form:
  - (*documented*, article 1023): the Backstop help centre says so.
  - (*observed*): we saw it in API responses, but nothing in this server's code or tests
    records it.
  - (*inferred*): our reading of the evidence, not confirmed.
- **When sources disagree**, a live response beats the help centre, and the help centre beats the
  swagger file. [Basics: Where knowledge comes from](./basics.md#where-knowledge-comes-from)
  explains why.
- **Examples are fictional.** Names, ids and values in examples are made up.

## Sources

- Read-only `GET` requests against live Backstop tenants, up to October 2026.
- The Backstop help centre (Elevio), REST API category. Articles are cited by number, as in
  "(*documented*, article 1023)".
- The swagger file (`<API root>/backstop-api-swagger.json`) and `/resource-metadata`.
- This server's source code and its earlier write experiments against test records.
