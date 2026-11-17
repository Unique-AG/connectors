# Agent use cases

Questions a bank's compliance officer, analyst or relationship manager asks an agent connected
to this MCP, drawn from the workflows in [how-banks-use-polixis.md](how-banks-use-polixis.md).
Each one gives the prompt, the tools the agent should call, and what a good answer contains, so
they double as a manual test plan.

The names in the prompts are made up. [`evals/cases.yaml`](../evals/cases.yaml) holds every case
here, plus cases for no match, bad pids, other languages and what the agent declines, as
evaluation cases an agent runs against the live API. Its prompts take real entities from a
gitignored `evals/entities.local.yaml`, and it grades the calls made and whether the answer
holds to what the tools returned, not fixed facts, since Polixis data changes.

Every case starts the same way: `search_entities` turns a name into a `pid`, and every other
tool takes that `pid`. Results come ranked, with their totals and flagged entries up front, so
the first page usually answers the question. A result with a `next_cursor` has more pages: the
agent passes it back alone as `cursor` only while the question needs what is left, and says so
when it stops early. When the search returns several plausible matches, the
agent narrows them by country, date of birth or identifier, or asks, and never picks one
silently. A good answer always names the `pid` it used and the sources Polixis gives.
A result with `truncated_by_polixis` true is incomplete, and an answer built on it says so.

## Onboarding

### 1. Screen a new private client

> We're onboarding Elena Varga, born March 1971, Hungarian national. Is she sanctioned or a PEP?

- `search_entities` with `entity_type` `PERSON`, `countries` `["hu"]` and `dates` `["1971-03"]`.
  Each match carries its birth date, sanctions and PEP flags and sanction statuses.
- `get_entity_profiles` on her match: only the profile's `flags` show a former PEP, and for a
  PEP or former PEP `sections` `["flags", "positions"]` adds the offices she held.

A good answer says which match is her and why (the birth date and nationality agree), whether
she carries `#SANCTION`, `#PEP` or `#FORMER_PEP`, and lists her positions with institutions and
dates. With no match, it says so plainly and shows what was searched, since "no hit" is itself
the record the bank files.

### 2. Screen a company and everyone behind it

> Onboard Kestrel Marine Services Ltd, Cyprus. Screen the company, its directors, its
> shareholders and its beneficial owners, and give me one table.

- `search_entities` with `entity_type` `ORGANIZATION`, `countries` `["cy"]`.
- `get_related_parties` with `categories` `["board", "executiveSenior", "executive", "shareholdingInformation", "signature"]`.
  Polixis files directors under `board`, but registers differ, so it asks for the executive ones too.
  A small company fits on one page; for a large one, say how many parties there are and page on
  only if the user wants every row.
- `get_ultimate_beneficial_owners`, whose `total_by_risk` counts the flagged owners of the tree
  and whose first page lists up to 25 of them, the sanctioned first.

A good answer is one table, one row per party: name, role, share held, country, flags. Former
roles are marked as former. Any flagged party is called out above the table.

### 3. Who controls this company?

> Who are the beneficial owners of Aurelia Trading SA, Geneva, above 25%? And is anyone
> controlling it without holding shares?

- `get_ultimate_beneficial_owners`: one row per owner, its `effective_share_percent` summed over
  every chain, largest first, so the agent stops once the shares fall below 25%, unless
  `total_share_unknown` counts an owner it has not read yet, whose share may be higher. The MCP
  computes that share from the per-link shares Polixis reports, and the answer says so.
- `get_related_parties` with `board`, `executiveSenior`, `executive` and `signature`, for the
  people who run it.

A good answer lists the natural persons at the end of a chain (`end_of_chain`) at or above 25%,
with the `strongest_chain` behind each, and flags a `share_unknown_on_some_chain` owner whose
true share may be higher. When nobody reaches 25%, it names the
senior managers, as the controlling-person rules then require. It flags control by other means,
such as one person signing for the company while a nominee holds the shares, as a lead to
assess and not a finding: a shared address or network is not control.

### 4. Corroborate source of wealth

> The client, Marco Bellandi, says his wealth comes from selling his stake in a logistics group
> in 2019. What does Polixis show about his companies and roles?

- `search_entities`, then `get_related_parties` with `ownershipInOtherEntities`, `board`,
  `executiveSenior` and `executive`.
- `get_entity_profiles` with `positions`.

A good answer lists the companies he holds or held, with shares and the dates they start and
end, and says whether a logistics holding that ended around 2019 is there. It separates what
Polixis shows from what it doesn't, and says that the size of a sale is not in this data.

## Sanctions

### 5. Indirect sanctions exposure under the 50% rule

> Is Borealis Grain LLC caught by the 50% rule? It isn't listed itself.

- `get_ultimate_beneficial_owners`: `total_by_risk` says how many owners of the tree are
  sanctioned, and the `flagged` list names them first, with their effective shares, up to 25.
  When there are more, the agent reads the flags on the rows of the further pages.
- `get_entity_profiles` with `sanction_statuses` for those owners, ten at a time.

A good answer applies OFAC's rule one level at a time, from the listed owners down: a company in
which blocked persons together hold 50% or more is blocked itself, and its own stake then counts
in full at the next level, so a 50% holding of a 50% subsidiary blocks the target where the
multiplied 25% would not. It adds up the stakes of listed owners per sanctions regime and shows
the chain behind each. It notes that the EU also blocks an entity controlled without a majority,
which share data alone cannot settle.

### 6. Sanctioned parties anywhere near a client

> Is there any sanctioned person or company connected to Halvorsen Shipping AS?

- `get_sanctions_exposure`, which gives the client's own listings, then each sanctioned party
  Polixis relates to it at any distance, nearest first, with its lists and the relations
  leading to it.

A good answer lists each sanctioned party, the path from the client to it with the role at
every hop (shareholder, director, subsidiary), whether the relation is current or former, and
the lists that sanction it. The route is undocumented and has returned different counts for
the same entity, so the answer says what it found rather than "nothing else exists". A sanctioned company's former director two hops away is far weaker
than a current majority shareholder, and the answer ranks them that way.

### 7. Which lists, and since when

> Pull the sanctions detail for Tarkov Industrial Holding: which regimes list it and when?

- `get_entity_profiles` with `sections` `["sanctions", "sanction_statuses", "name_records"]`, or
  `get_sanctions_exposure`, whose `own_listings` give each list's status, programmes and
  listing date.

A good answer gives one row per list: regime, country, status, dates and source. It lists the
aliases and former names, which the bank's own screening must also match on.

### 8. Screen a payment counterparty

> We have an outgoing payment to Sahel Petroleum Trading FZE in the UAE. Screen the
> beneficiary and its owners before we release it.

- `search_entities` with `countries` `["ae"]`.
- `get_ultimate_beneficial_owners`.

A good answer gives a clear result (no hit, hit or possible hit) with the evidence, and the
owners' flags. On a possible hit it says what would settle it, such as a registration number,
and does not decide itself.

## PEP and state ownership

### 9. Is the company owned by a state?

> Is Northfield Power Distribution a state-owned enterprise, and which state?

- `get_ultimate_beneficial_owners`, looking for a state body or ministry at the top.
- `total_by_risk` on the owners' first page counts the `STATECO` owners, and the `flagged` list
  names them; `find_flagged_parties` finds one nearby if the tree alone doesn't settle it.

A good answer names the state owner and its share, and what that implies: corruption risk, and
sanctions where a regime targets state-owned companies of a country.

### 10. PEPs behind a company

> Are there politically exposed persons among the owners, directors or signatories of Lindqvist
> Capital Partners?

- `find_flagged_parties` with `radius` 1: every PEP among the company's owners, directors and
  signatories, with the relation each holds. Its `total_by_risk` says how many there are, so a
  0 settles the question in one call, unless `truncated_by_polixis` is true: the network is
  then incomplete, and the answer says so.
- `get_entity_profiles` with `positions` for the flagged people, ten at a time.

A good answer lists each PEP with the function, institution and dates, says whether they are
current or former, and the relation they hold to the company.

### 11. Family and close associates

> Elena Varga is a PEP. Which companies is she connected to, directly or through people around
> her?

- `find_linked_companies` with `radius` 2: the companies she is tied to directly, then those
  tied to her through one person, such as a relative or associate, each with the links along
  the way. `radius` 3 adds those tied through two people in a row, when the question reaches
  that far.

A good answer lists the companies she owns or runs, and those of the people linked to her, with
the relation at each step. Because the documentation doesn't say how relatives are marked, it
reports the relation types the data actually holds rather than assuming "family".

Asked next to include historic ties and signatory roles, the agent calls `find_linked_companies`
again on the same `pid` with `scope` `all`, marks the historic ties as historic, and says when a
linked company comes without a name.

## Periodic review and monitoring

### 12. Annual review of a client file

> Annual review for client file pid `<pid>`. What changed? Flags, owners, directors.

- `resolve_permanent_id` first: the ID may have been merged into another.
- `get_entity_profiles`, `get_related_parties` and `get_ultimate_beneficial_owners` on the
  current ID.

A good answer starts by saying whether the stored ID is still active or which one replaced it.
It then gives the current flags, owners and directors, and points out relations that ended and
roles marked as former. Polixis returns the present state, not a diff, so the agent compares
with what the user gives it from the last review and says so.

### 13. A change in the ownership structure

> Our client is exempt because its listed parent owns more than 75% of it. Check that still holds
> for Fenwick Industrial Components GmbH.

- `get_ultimate_beneficial_owners` for the parent's effective share.
- `get_related_parties` with `shareholdingInformation`, for the start and end dates of the
  parent's stake, which the owner rows do not carry.
- `get_entity_profiles` on the parent, for its listing.

A good answer gives the parent's current stake and dates, and says plainly if it has fallen to
75% or below, which ends the exemption and calls for a review of the controlling person.

### 14. A merged or dissolved record

> Our system still holds pid `<old pid>` for a client. Is it still valid?

- `resolve_permanent_id`.

A good answer says active, merged (with the replacing `pid`) or dissolved (a 410), and what the
user should update.

## Group and investigation

### 15. Map a group

> Map everything Halden Group Holding owns, with percentages, and flag anything sanctioned or
> state-owned.

- `get_top_down_ownership`: one row per holding, the controlled ones first. `total_by_risk`
  counts the group's sanctioned and state-owned holdings, and the first page names up to 25 of
  them; the others carry their flags on their own rows.

A good answer gives the holdings with the share the group carries in each, the chain behind
the main ones, and flags called out. If `truncated_by_polixis` is
true, it says the group is larger than one request returns (300 nodes per level, 5,000 in all)
and suggests starting from a sub-holding.

### 16. How are these two connected?

> Is there any link between our client Orsolya Kertész and Tarkov Industrial Holding?

- `search_entities` for both.
- `find_connections` from the client to the other: the shortest path Polixis finds across its
  whole graph.

A good answer shows the path between the two, with the roles, shares and flags along it, or says
Polixis found none, which does not prove there is no link.

### 17. Disambiguate a common name

> Screen Mohammed Al-Hassan, born 1984, Jordanian. There will be many hits.

- `search_entities` with `entity_type` `PERSON`, `countries` `["jo"]` and `dates` `["1984"]`.
  The filters do the narrowing: a common name runs to a thousand hits, a hundred pages, so the
  agent pages on only while candidates remain that the filters could not rule out. Each match carries its birth dates, countries and original-script names.
- `get_entity_profiles` on the candidates still standing, for every name record.

A good answer narrows the hits with evidence, by birth date first and then nationality and the
original-script name, and lists the ones it couldn't rule out with the reason. It says how many
hits there were in total, not only the first page.

### 18. Identify by identifier

> Look up LEI `<20-character LEI>` and tell me who owns it.

- `search_entities` with the LEI as `name`, whose match lists its identifiers, then
  `get_ultimate_beneficial_owners`.

A good answer confirms that the identifier on the profile matches the one asked for before
using it.

An IMO number finds a vessel the same way: Polixis holds vessels and aircraft as organizations,
with the IMO number among their identifiers.

### 19. Court decisions

> Has Kestrel Marine Services or anyone around it been named in a court decision?

- `find_court_decisions`: the decisions naming the company first, then those naming its related
  parties, each with its court, country, year and the passages naming them.
- `get_court_decision` for one whose snippets don't settle what it is about.

A good answer lists the decisions naming the company with what each concerns, then those of its
related parties, and reads a full text only where the snippet leaves the subject unclear. With
none, it says so and that a wrong pid also returns none.

## Front office

### 20. Brief a relationship manager

> I'm meeting the CFO of Kestrel Marine Services tomorrow. Give me a one-page risk brief on the
> company.

- `search_entities`, `get_related_parties`, `get_ultimate_beneficial_owners`,
  `get_sanctions_exposure`, `find_flagged_parties` for the state-owned links, which the
  sanctions exposure leaves out, and `find_court_decisions`, each on its first page.

A good answer is short: who owns it, who runs it, the flags on any of them, and the nearest
sanctioned or state-owned link, and any court decision naming the company. It ends with what
the brief doesn't cover: adverse media, which this MCP doesn't reach.

## What the agent should decline or qualify

- **Adverse media.** Not in the API. The agent says so rather than presenting a clean result as
  "no adverse media". Court decisions are covered by `find_court_decisions`, but a wrong pid
  also returns none, so the agent checks the pid before reporting a clean record.
- **Screening a whole client book.** One search per name, so a list of hundreds is slow and the
  answer only as good as each match. Batch screening belongs in CheckMate or a bulk feed.
- **The final decision.** The agent shows evidence and possible matches. Whether a hit is the
  client, and whether to onboard, block or file a report, is the compliance officer's.
- **Polixis is not the client file.** Every user shares one set of Polixis credentials, and a
  Polixis response is reused for the cache's TTL, an hour at most, and deleted by a periodic,
  best-effort cleanup after that, so the bank's own record of the check stays its job.
