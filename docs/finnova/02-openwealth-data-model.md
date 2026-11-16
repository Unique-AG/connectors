# OpenWealth and bLink data model

The public, standard view of the data a Finnova bank can expose through SIX bLink. Read from
the OpenWealth OpenAPI specs (Custody Services v3.2.0, Customer Management v2.0.6) and from
SIX's bLink example payloads (AIS v6). Fields marked `*` are required.

## Custody Services v3.2.0

```
Customer                          id*, number, referenceCurrency
 ├─ Account                       id*, type* (cashAccount | safekeepingAccount | other),
 │   │                            referenceCurrency*, iban, number, name, designation,
 │   │                            portfolioInformation { identification, referenceCurrency }
 │   └─ Position                  id*, account*, financialInstrument*, currency,
 │                                safekeepingPlace, name
 │        + valuation fields      positionDate*, endOfDayIndicator*,
 │                                quantity* { type: unit|faceAmount|amortisedValue|digitalTokenUnit, value },
 │                                valuation* { valueInPositionCurrency, valueInReferenceCurrency, valuationDate },
 │                                price, foreignExchangeRate, costPrice, costForeignExchangeRate,
 │                                accruedInterest, numberOfDaysAccrued, blockedQuantity
 └─ Transaction                   id*, type*, transactionDate*, customerId*, reversalIndicator*,
      │                           endOfDayIndicator*, tradeDate, settlementDate, exDate,
      │                           reversedTransactionId, placeOfTrade, triggeringFinancialInstrument,
      │                           triggeringQuantity, triggeringPrice, settlementCurrency
      ├─ movementList[]           type*, positionId*, account*, financialInstrument*, quantity*,
      │                           movementDate*, valueDate, price, foreignExchangeRate
      └─ postingAmountList[]      amount*, currency*, account*
```

Endpoints: `/customers`, `/customers/{customerId}`, `/customers/{customerId}/accounts[/{accountId}]`,
`/customers/{customerId}/positions[/{positionId}]`, `/accounts/{accountId}/positions[/{positionId}]`,
`/customers/{customerId}/transactions[/{transactionId}]`.

Positions and transactions take `date`, `endOfDayIndicator`, `cursor` and `limit`. The spec
describes `date` only as "A date value", so whether it returns an as-of snapshot for a past
date is up to the provider.

### What the shape implies

- **A portfolio is not a resource of its own.** It is `portfolioInformation.identification`
  on an account. To list a client's portfolios, list the accounts and group them on that field.
- **Cash is a position.** A cash account is an `Account` of type `cashAccount`, and its
  balance is a `Position` whose `financialInstrument.type` is `cash`. One positions call gives
  the full picture.
- **Transactions belong to the customer, not the account.** The spec only has
  `/customers/{customerId}/transactions`. For the history of one holding, filter on
  `movementList[].positionId`. bLink's guide also lists `/accounts/{id}/transactions` and
  `/positions/{id}/transactions`, but its v3 reference does not, so pin the version.
- **Currency exists at three levels.** Each position has its own currency, and customer,
  account and portfolio each have a `referenceCurrency`. Valuations come in both position and
  reference currency. Do not add values across positions without converting them.
- **Intraday and end-of-day data mix.** `endOfDayIndicator` and `positionDate` say which one a
  figure is.
- **Instruments come in 19 types**, selected by `type`: cash, bond, equity, fund, index,
  commodity, option, future, fxForward, fxSwap, fxOption, mortgage, credit, moneyMarket,
  interestRateSwap, totalReturnSwap, creditDefaultSwap, cryptoAsset, other. Each has its own
  fields. Identifiers are in `identificationList[]`, typed `isin`, `valoren` (the Swiss valor
  number), `cusip`, `sedol`, `wertpapier` and others. A position can carry several.
- **Transaction `type` has 56 values** (buy, sell, coupon, dividendCash, fees,
  internalTransfer, …). **Movement `type` has 23 values**, including asset, cash and a set of
  fee and tax kinds (withholdingTax, stampDuty, custodyFee, …). Fees and taxes are separate
  movements inside one transaction.

## Customer Management v2.0.6

A **customer is the contract or business relationship. A person is a separate natural or
legal person** linked to it. Joint accounts and companies with signatories fit this model.

- `customer`: `customerId`, `externalReference`, `name`, `status` (active | inactive),
  `referenceCurrency`, `openingDate`, `language`, `customerSegment`, `bankAdvisor`,
  `bankDeputyAdvisor`, `bankPreviousAdvisor`. The advisor fields are free text (full name,
  max 35 characters), not a role model.
- `personBase`: `personId`, `externalReference`, `language`, `countryOfDomicile`,
  `openingDate`, `taxDomicileList`, `personType` (naturalPerson | legalPerson |
  personAssociation).
- `person2customerRelation.relationList[]`: `type` (beneficialOwner, accountOwner,
  registeredOwner, authorisedSignatoryIndividual, authorisedSignatoryCollective, beneficiary,
  externalAssetManagerFirm, externalAssetManagerEmployee, ownerParentalAuthority, other) and
  `cardinality` (individually | inTwos | inThrees | fourway). This is signing authority.
- Persons own `contacts`, `addresses` (with `isDomicile`, `isMailingAddress`) and `kyc`.
- `kyc`: purpose of relationship, sole beneficial owner, fund flows, source of wealth, total
  wealth and income, employment, corporate insider and major shareholder data,
  `politicalStatus` (`pepStatus`, `pepFunction`, `pepAssociations`, `pepRelation`,
  `sanctions`), `fatca`, external asset manager. Very sensitive; keep it out of a first version
  unless asked.
- Lists (`/customers`) take only `cursor` and `limit`. There is no search.

## bLink account information (AIS v6)

From SIX's example payloads.

- **Account:** `id` (opaque), `account { type: "IBAN", identification }`, `accountOwnerName`,
  `accountTypeCode` (ISO codes such as `TRAN`, `NFCA`), `currency`, `designation`.
- **Balance:** `date`, `balanceType` (`CLBD` booked, `ITBD` interim),
  `balance { amount, currency }`.
- **Transactions** are shaped like camt.053. `entries[]` carry `bookingDate`, `valueDate`,
  `entryStatus`, `transactionType` (CRDT | DBIT), `bankTransactionCode { domainCode,
  familyCode, subFamilyCode }`, `amount`, `entryReference`. Each entry nests `transactions[]`
  with `endToEndId`, `uetr`, `instructionId`, `counterparty { name, postalAddress, account,
  agent }`, `remittanceInformation`, `remittanceReference` and `instructedAmount` (with FX). One
  collective booking can hold many payments.

## Mechanics shared by the bLink APIs

- HAL `_links` on responses.
- Paging with an opaque cursor in the `nextCursor` **response header**, plus `limit`. Paging
  counts the listed object (accounts, positions, customers).
- OAuth2 bearer tokens. A caller only sees "customers accessible for the logged in user", so
  access is per user and per consent.
- `X-Correlation-ID` on requests and responses.

## Sources

- [OpenWealth spec repository](https://github.com/OpenWealth/OpenWealth), read at
  `c3e63aed2676bb272fa3027bdc0218fccc4ab72e` (`custodyAPI.yaml`, Apache-2.0)
- [OpenWealth-MCP vendored specs](https://github.com/OpenWealth/OpenWealth-MCP/tree/0aef72f3ced1ab207662360f9d2424eac9edf21e/specs)
  (`customerAPI.yaml` v2.0.6)
- [bLink custody services guide](https://docs.blink.six-group.com/docs/services/openwealth/custody-services)
- [bLink custody services v3 release notes](https://docs.blink.six-group.com/blog/custody-services-v3).
  The v3 spec is missing from the bLink API reference because of a `oneOf` typing issue.
- [bLink downloads: example payloads and Postman collection](https://docs.blink.six-group.com/docs/downloads/)
- [Swiss NextGen API (account information and payments)](https://openbankingproject-ch.github.io/obp-apis)
