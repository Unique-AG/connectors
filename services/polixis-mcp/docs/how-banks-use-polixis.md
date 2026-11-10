# How banks use Polixis

Research notes, November 2026, from Polixis' own site and news, trade press and partner
announcements. Most product claims are the vendor's own and no bank has published a case
study, so read the figures as marketing. Sources are listed at the end.

## Who Polixis is

A Swiss RegTech company in Geneva, founded in 2012 as a compliance consultancy and 100%
owned by its employees, with offices in London and Zurich and research and development in
Yerevan. It describes itself as "the only Swiss independent full-circle Compliance Data
provider (UBOs, PEPs, sanctions and more)", and says it owns and operates its data rather than
reselling it.

Its customers, as it names them, are "Tier 1 Private Banks, Wealth & Asset Managers, and
Regulatory & Governmental Bodies". The site claims "200+ banks & financial institutions —
including a national central bank and regulators", and the about page names its base as the
"most demanding wealth-management banks in Switzerland, Monaco, Liechtenstein and Luxembourg".
Its published testimonials come from chief compliance officers of private banks and a bank in
the Middle East. Two Swiss wealth platforms, Etops (May 2024) and WealthArc (September 2024),
embed its data, and through them independent asset managers and family offices screen their
clients with it.

What sets it apart, in its own words and in the press, is coverage of **emerging markets and
Eastern Europe**, where western vendors are thin: names in Cyrillic, Chinese and Arabic script,
with their transliterations ("Is this the local property tycoon or the international
terrorist?"), and the people and companies around a sanctioned party.

## The data

| Dataset | What it holds | Scale it claims |
|---|---|---|
| Sanctions | International and national sanctions and enforcement actions, updated several times a day, with the parties around a listed one, including those caught by the OFAC/EU 50% rule | 1.9M persons and entities |
| PEP, RCA and watchlists | PEPs per FATF and Wolfsberg guidance and national law, their relatives and close associates (RCA), senior officials, state-owned enterprises (SOE), reputational-risk profiles | 13M profiles, 249 jurisdictions |
| Corporate and UBO | Directors, shareholders, beneficial owners, subsidiaries and signatories: ownership, control and governance | 637M corporates and UBOs, 249 jurisdictions |
| Adverse media | Region-specific press from thousands of sources | 100+ languages |
| Judicial decisions | Court records, in ARDIS | not stated |

Every profile is resolved to one stable ID, and corporate data is linked to the sanctions and
PEP records "under one umbrella ID". Every record carries its source and the date it was
retrieved, and all of it comes from public sources.

## The products

| Product | What a bank does with it |
|---|---|
| **ARDIS** (Applied Risk & Data Intelligence Solution) | A web platform and API that builds one dossier per client: corporate data, UBOs, PEP, sanctions, adverse media and court records. Used for onboarding, periodic review and ad-hoc deep dives, by compliance and the front office. Has Path Search, which finds how two parties connect, the Entity Graph Analyzer, and ARDIS Chat, an LLM over the dossier that exports a PDF |
| **PEP&REP** | Mass screening against sanctions, PEP, SOE, watchlists and adverse information, by API, web or bulk file. Also used for transaction and payment screening |
| **CheckMate** | Batch screening of a client book uploaded as Excel, with case management, periodic re-screening and alerts. Screens for sanctions, sanctioned beneficiaries, third-party exposure, PEPs and associates, and SOEs |
| **Media Monitoring** | Regional risk briefings as PDF and data files |
| **Risk Data API** and **Corporate/UBO Data API** | The datasets by REST, separately or together, with a graph endpoint that returns an entity's whole connected subgraph in one call |
| **Bulk feeds** | JSON, CSV or Excel by SFTP or S3, with deltas, including on-premise and air-gapped |
| **AiDA**, **Graph AI** and **MCP** | A chat layer over every product, a knowledge graph queried in plain language, and an MCP server of their own ("`screen_person`, `resolve_entity`, `ubo_chain`, `sanctions_check`, `adverse_media`, `graph_query`") |

## The bank workflows

1. **Client onboarding.** Screen the prospect and every related party (beneficial owners,
   directors, signatories) against sanctions and PEP lists, and resolve who controls a company.
   The 2019 press describes Swiss banks using Polixis "as a primary check or a second opinion"
   at onboarding.
2. **Beneficial owner identification.** Swiss banks must establish the controlling person of a
   company under the bankers' due-diligence agreement. CDB 27, published on 30 October 2026,
   replaces CDB 20 on 1 January 2027 with a four-month transition. It keeps the 25% threshold
   but also asks whether someone controls "by other discernible means", and Form K now asks
   for date of birth and nationality. Polixis argues it is "a data project": relations must be
   typed, sourced and dated, and conflicting values kept rather than overwritten.
3. **Indirect sanctions exposure.** A company not on any list is still blocked when blocked
   persons own 50% or more of it, directly or indirectly, alone or together (OFAC). An owner
   under sectoral restrictions only, such as a Directive 3 debt and equity ban, passes those
   restrictions on, not a block. In the EU, a company more than 50% owned or otherwise
   controlled by a listed person is presumed to pass on what it receives to that person, a
   presumption the bank can rebut case by case, and neither control nor its rebuttal shows in
   share data alone. Banks walk the ownership chain up from the client and the graph out from
   it. Polixis' news follows the court cases that draw this line, such as informal political
   control (Inter RAO Lietuva) and state-owned payees (DNO Yemen).
4. **PEP and RCA identification.** Find whether a client, or someone behind it, holds or held a
   prominent public function, or is family or a close associate of someone who does, and which
   positions, since the bank applies enhanced due diligence and its own rules on former PEPs.
5. **SOE exposure.** Identify companies owned or controlled by a state, which matters for both
   sanctions (state-ownership restrictions in the EU's Russia packages) and corruption risk.
6. **Source of wealth.** Corroborate what a client says about where their wealth comes from
   against the companies they own or ran, their positions, and the press.
7. **Periodic review and ongoing monitoring.** Re-screen the whole book on a schedule or on
   deltas, and re-review a relationship when its ownership changes, for example a parent's
   stake falling below an exemption threshold.
8. **Payment and counterparty screening.** Screen the counterparties of a transaction, and the
   owners behind them.
9. **Forensic investigation.** Investigate a suspicious-activity case: find how two parties are
   connected and through whom.
10. **Front-office prospecting.** Brief a relationship manager on a prospect's risk before the
    first meeting.

## What this MCP covers

The MCP serves the Corporate Data and Graph API (spec v3), not the whole product range.

| Workflow | Covered | How |
|---|---|---|
| Name screening, sanctions and PEP flags | Yes | `search_entities`, then `get_entity_profiles` |
| Which lists sanction an entity, and since when | Yes | `get_entity_profiles` with `sanctions` and `sanction_statuses` |
| PEP positions held | Yes | `get_entity_profiles` with `positions` |
| Beneficial owners | Yes | `get_ultimate_beneficial_owners`, one row per owner with the share summed over every chain |
| Subsidiaries and what an entity owns | Yes | `get_top_down_ownership`, one row per holding |
| Companies linked to a person or company | Yes | `find_linked_companies`, directly or through one person, or two at `radius` 3 |
| Directors, executives, signatories, shareholders | Yes | `get_related_parties` with `categories` |
| Indirect sanctions exposure | Yes, on an undocumented route | `get_sanctions_exposure`, at any distance, with the path to each sanctioned party |
| PEP and SOE exposure nearby | Yes | `find_flagged_parties`, with the path to each flagged party |
| How two parties connect | Yes, on an undocumented route | `find_connections`, the shortest path Polixis finds across its whole graph |
| Stale IDs in a stored client file | Yes | `resolve_permanent_id` |
| Court decisions | Yes, on an undocumented route | `find_court_decisions`, then `get_court_decision` for one text |
| Adverse media | No | Not in the API |
| Batch screening of a whole client book | No | One search per name; CheckMate or bulk feeds do this |
| RCA as a separate category | Unknown | The documentation does not say how relatives are marked; check the live `flags` and relations |

## Sources

- [Polixis homepage](https://polixis.com/), [about](https://polixis.com/about), [partners](https://polixis.com/partner), [news](https://polixis.com/news)
- [New Swiss CDB 27 is a data project](https://polixis.com/news/new-swiss-cdb-27-is-a-data-project) (Polixis, 4 November 2026)
- [Inter RAO Lietuva: the line between the 50% rule and informal control](https://polixis.com/news/inter-rao-lietuva-the-line-between-the-50-rule-and-informal-control) (Polixis, 3 September 2026)
- [DNO Yemen and the evidence behind indirect sanctions exposure](https://polixis.com/news/dno-yemen-and-the-evidence-behind-indirect-sanctions-exposure) (Polixis, 20 October 2026)
- [When sanctions compliance becomes the breach](https://polixis.com/news/when-sanctions-compliance-becomes-the-breach) (Polixis, 3 August 2026)
- [Polixis outshines compliance giants](https://www.finews.asia/finance/30258-polixis-outshines-compliance-giants-with-oft-ignored-em-data-capabilities) (finews.asia, November 2019)
- [Polixis: beware of voids in sanction-linked risks](https://www.finews.com/news/english-news/54155-polixis-beware-of-voids-sanction-linked-risks) (finews.com, November 2022)
- [Polixis vendor profile](https://www.thewealthmosaic.com/vendors/polixis/) (The Wealth Mosaic)
- [WealthArc teams up with Polixis](https://www.wealtharc.com/insights-articles/wealtharc-teams-up-with-polixis-to-automate-kyc-screening-and-enhance-compliance-efficiency) (September 2024)
- [Etops–Polixis partnership](https://www.finews.ch/news/finanzplatz/62562-fintech-etops-polixis-partnerschaft-kyc-geldwaescherei-eam) (finews.ch, May 2024)
- [OFAC FAQ 985 on the 50 Percent Rule](https://ofac.treasury.gov/faqs/985)
