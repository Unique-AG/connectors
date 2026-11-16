# Finnova landscape

Finnova (finnova AG Bankware, finnova.com) is a Swiss core banking system, used by roughly
100 Swiss banks, several cantonal banks among them. Do not confuse it with finnovacorp.com,
an unrelated company selling an "AI Workforce" platform.

## Where a Finnova bank's data lives

```
┌──────────────────────────────┐
│ Finnova core (the product)   │  application + its own database
│ the bank's live data:        │
│ customers, accounts, Depots, │
│ positions, transactions      │
└──────┬──────────────┬────────┘
       │ API "threads" │ extracts / ETL (typically nightly)
       │ (use-case     ▼
       │  specific)  ┌───────────────────────────────┐
       │             │ Data warehouse (DWH)          │  separate system, the bank's
       │             │ Finnova data + other sources, │  choice of technology
       │             │ history, reporting, KPIs      │
       │             └──────────┬────────────────────┘
       ▼                        ▼
┌───────────────────────────────────────────────┐
│ Bank's own aggregation layer (their API)      │  optional, bank-built
└───────────────────────────────────────────────┘
```

1. **Finnova core.** One product shared by every Finnova bank, with the modules the bank
   licenses (credit, investment, payments, …). It holds the full data model, but only inside
   its own database, and direct database access is not an integration route we can count on.
   Banks run different releases.
2. **Data warehouse.** A separate system fed from Finnova and from other sources. Finnova
   markets an Analytical Framework of its own, and a bank may use that or its own warehouse.
   Reporting history and KPIs often live here, not in the core.
3. **Aggregation layer.** A bank's own API in front of both, if it built one.

On top of the product, every bank configures its own product catalogue, customer
classifications, risk categories, fee models, roles and access rules. The software is the
same, but the codes and their meanings differ per bank.

Finnova describes the core relationship as: **a customer holds several accounts and custody
accounts (Depots), which can be grouped into one or more portfolios.**

## Ways in today

| Path | What it is | Data | Documentation |
|---|---|---|---|
| **Finnova Partner APIs** | REST APIs on the bank's Finnova installation, built per use case ("threads") | See below | OpenAPI with field-level detail and a changelog, behind the Partner Portal |
| **SIX bLink** | Hub between fintechs and banks; Finnova connected to it in 2022 | Account information, payments, custody (positions, transactions), customer management | Public, see [02](02-openwealth-data-model.md) |
| **Bank's DWH / aggregation layer** | Whatever the bank exposes itself | Bank-specific | From the bank |
| **finnova.neo** | Finnova's next platform, 2000+ APIs announced | Everything, as an API | Not expected before end of 2027 |

### Partner Portal

Registration is required. It is free for Finnova licensees and product or technology
partners; other parties pay a small fee. The docs describe each interface at field level,
including mandatory fields and a changelog. A licensee bank can also request a mapping of
interface attributes to Finnova Core Suite attributes. Access may require us to register as a
technology partner, or the bank requests the docs for us.

### Finnova Partner APIs named publicly

From the openbankingproject.ch catalog. None of these pages give fields, auth or protocol.

| API | Direction | Data |
|---|---|---|
| Client Overview | Read | Master, address, communication and additional data of a customer, for a 360-degree overview |
| Data Import Credit Consulting | Write | A credit application prepared in a third-party system, written into the Credit Advice module |
| Foreign Tax Statements | Read, then import | Customer data, transactions, positions, securities, security and exchange rates, for foreign tax registers |

### bLink is a hub, not an aggregator

bLink does not collect or hold bank data. It provides a standard interface that **each bank
implements itself**, routes each request to that bank (the `X-CorAPI-Source` response header
says whether bLink or the bank produced the answer), and handles client consent, onboarding
and the contract between the service user (us) and the provider (the bank). For one bank,
bLink is a gateway to the subset that bank chose to implement.

Its value is breadth: one connector reaches every bank on bLink for **standard** data,
whatever core system they run. That makes it a candidate for a later, cross-bank product, not
for UN-29657.

## Sources

- [openbankingproject.ch: Finnova back end and its APIs](https://www.openbankingproject.ch/en/catalog/back-end-systems/finnova/)
- [Client Overview API](https://www.openbankingproject.ch/en/catalog/apis/vendor/finnova-client-overview/)
- [Foreign Tax Statements API](https://www.openbankingproject.ch/en/catalog/apis/vendor/finnova-foreign-tax-statements/)
- [Finnova Partner FAQ (Partner Portal access)](https://www.finnova.com/de/partner-faq). The
  site renders client-side and returns no content to non-browser fetches.
- [Finnova brochure: customer → accounts and Depots → portfolios](https://docplayer.org/62425238-Finnova-banking-software-end-to-end-effizient-offen-innovativ.html)
- [SIX: Finnova connects to bLink (2022)](https://www.six-group.com/en/newsroom/media-releases/2022/20220126-finnova-blink.html)
- [Contovista: data-driven banking and the Analytical Framework](https://www.contovista.com/en/news/latest-news/data-driven-banking-und-analytical-framework/)
- The UN-29657 ticket, for the "threads" limitation and the finnova.neo timeline.
