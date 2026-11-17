# Agent use cases

Questions a bank's compliance officer, analyst or relationship manager asks an agent connected
to this MCP, drawn from the workflows in [how-banks-use-polixis.md](how-banks-use-polixis.md).
Each one gives the prompt, the tools the agent should call, and what a good answer contains, so
they double as a manual test plan and as evaluation cases.

The names in the prompts are made up. To run a case against the live API, swap in a real entity
of the same kind: a listed company, a sanctioned person, a state-owned company.

Every case starts the same way: `search_entities` turns a name into a `pid`, and every other
tool takes that `pid` as its `id`. When the search returns several plausible matches, the
agent narrows them by country, date of birth or identifier, or asks, and never picks one
silently. A good answer always names the `pid` it used and the sources Polixis gives.
An ownership tree with `truncated` true is incomplete, and an answer built on it says so.

## Onboarding

### 1. Screen a new private client

> We're onboarding Elena Varga, born March 1971, Hungarian national. Is she sanctioned or a PEP?

- `search_entities` with `entity_type` `PERSON` and `countries` `["hu"]`. The tool takes no date,
  so the agent compares each match's birth date with 1971-03 itself, on every page of hits
  before it reports no match. A match without a birth date stays a possible match.
- `get_key_identifiers` on the match, for flags, alerts and sanction statuses.
- If she is a PEP: `get_profile_fields` with `positions`.

A good answer says which match is her and why (the birth date and nationality agree), whether
she carries `#SANCTION`, `#PEP` or `#FORMER_PEP`, and lists her positions with institutions and
dates. With no match, it says so plainly and shows what was searched, since "no hit" is itself
the record the bank files.

### 2. Screen a company and everyone behind it

> Onboard Kestrel Marine Services Ltd, Cyprus. Screen the company, its directors, its
> shareholders and its beneficial owners, and give me one table.

- `search_entities` with `entity_type` `ORGANIZATION`, `countries` `["cy"]`.
- `get_corporate_profile` with `category` `["executive", "executiveSenior", "shareholdingInformation", "signature"]`.
- `get_ultimate_beneficial_owners`.

A good answer is one table, one row per party: name, role, share held, country, flags. Former
roles are marked as former. Any flagged party is called out above the table.

### 3. Who controls this company?

> Who are the beneficial owners of Aurelia Trading SA, Geneva, above 25%? And is anyone
> controlling it without holding shares?

- `get_ultimate_beneficial_owners`, then each owner's effective share through the chain. Its
  nodes carry pids, not names, so `get_basic_identifiers` names the owners the answer lists.
- `get_corporate_profile` with `executive`, `executiveSenior` and `signature`, for the people who
  run it.

A good answer lists the natural persons at the top of each chain, multiplying shares through
intermediate holdings and adding up each person's chains, and the ones whose total reaches 25%,
even when no single chain does. When nobody reaches 25%, it names the senior managers, as the
controlling-person rules then require. It flags control by other means, such as one person
signing for the company while a nominee holds the shares, as a lead to assess and not a finding:
a shared address or network is not control.

### 4. Corroborate source of wealth

> The client, Marco Bellandi, says his wealth comes from selling his stake in a logistics group
> in 2019. What does Polixis show about his companies and roles?

- `search_entities`, then `get_corporate_profile` with `ownershipInOtherEntities`,
  `executiveSenior` and `executive`.
- `get_profile_fields` with `positions`.

A good answer lists the companies he holds or held, with shares and the dates they start and
end, and says whether a logistics holding that ended around 2019 is there. It separates what
Polixis shows from what it doesn't, and says that the size of a sale is not in this data.

## Sanctions

### 5. Indirect sanctions exposure under the 50% rule

> Is Borealis Grain LLC caught by the 50% rule? It isn't listed itself.

- `get_ultimate_beneficial_owners`.
- `get_key_identifiers` for each owner without flags in the tree.

A good answer applies OFAC's rule one level at a time, from the listed owners down: a company in
which blocked persons together hold 50% or more is blocked itself, and its own stake then counts
in full at the next level, so a 50% holding of a 50% subsidiary blocks the target where the
multiplied 25% would not. It adds up the stakes of listed owners per sanctions regime and shows
the chain behind each. It notes that the EU also blocks an entity controlled without a majority,
which share data alone cannot settle.

### 6. Sanctioned parties anywhere near a client

> Is there any sanctioned person or company within two hops of Halvorsen Shipping AS?

- `get_subgraph` with `radius` 2 and a filter whose rules set `requireSanction`.
- `get_key_identifiers` or `get_profile_fields` (`sanctions`) on each sanctioned node.

A good answer lists each sanctioned party, the path from the client to it with the role at
every hop (shareholder, director, subsidiary), whether the relation is current or former, and
the lists that sanction it. A sanctioned company's former director two hops away is far weaker
than a current majority shareholder, and the answer ranks them that way.

### 7. Which lists, and since when

> Pull the sanctions detail for Tarkov Industrial Holding: which regimes list it and when?

- `get_profile_fields` with `sanctions`, `sanctionStatuses` and `nameRecords`.

A good answer gives one row per list: regime, country, status, dates and source. It lists the
aliases and former names, which the bank's own screening must also match on.

### 8. Screen a payment counterparty

> We have an outgoing payment to Sahel Petroleum Trading FZE in the UAE. Screen the
> beneficiary and its owners before we release it.

- `search_entities` with `countries` `["ae"]`, then `get_key_identifiers`.
- `get_ultimate_beneficial_owners`.

A good answer gives a clear result (no hit, hit or possible hit) with the evidence, and the
owners' flags. On a possible hit it says what would settle it, such as a registration number,
and does not decide itself.

## PEP and state ownership

### 9. Is the company owned by a state?

> Is Northfield Power Distribution a state-owned enterprise, and which state?

- `get_ultimate_beneficial_owners`, looking for a state body or ministry at the top.
- `get_subgraph` with `requireSoe` on the rules, if the tree alone doesn't settle it.

A good answer names the state owner and its share, and what that implies: corruption risk, and
sanctions where a regime targets state-owned companies of a country.

### 10. PEPs behind a company

> Are there politically exposed persons among the owners, directors or signatories of Lindqvist
> Capital Partners?

- `get_corporate_profile` with every relation category.
- `get_profile_fields` with `positions` for each flagged person.

A good answer lists each PEP with the function, institution and dates, says whether they are
current or former, and the relation they hold to the company.

### 11. Family and close associates

> Elena Varga is a PEP. Which companies is she connected to, directly or through people around
> her?

- `get_subgraph` around her with `radius` 2. `get_smart_graph` leaves out signatory and
  third-party relations, where associates often sit. The subgraph's `meta` holds only the
  `fields` asked for, so `get_basic_identifiers` names the parties the answer lists.

A good answer lists the companies she owns or runs, and those of the people linked to her, with
the relation at each step. Because the documentation doesn't say how relatives are marked, it
reports the relation types the data actually holds rather than assuming "family".

## Periodic review and monitoring

### 12. Annual review of a client file

> Annual review for client file pid `<pid>`. What changed? Flags, owners, directors.

- `resolve_permanent_id` first: the ID may have been merged into another.
- `get_key_identifiers`, `get_corporate_profile` and `get_ultimate_beneficial_owners` on the
  current ID.

A good answer starts by saying whether the stored ID is still active or which one replaced it.
It then gives the current flags, owners and directors, and points out relations that ended and
roles marked as former. Polixis returns the present state, not a diff, so the agent compares
with what the user gives it from the last review and says so.

### 13. A change in the ownership structure

> Our client is exempt because its listed parent owns more than 75% of it. Check that still holds
> for Fenwick Industrial Components GmbH.

- `get_ultimate_beneficial_owners`, then `get_key_identifiers` on the parent.

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

- `get_top_down_ownership`.

A good answer is the tree with the share at each level and flags called out. If `truncated` is
true, it says the group is larger than one request returns (300 nodes per level, 5,000 in all)
and suggests starting from a sub-holding.

### 16. How are these two connected?

> Is there any link between our client Orsolya Kertész and Tarkov Industrial Holding?

- `search_entities` for both.
- `get_subgraph` around the client with `radius` 3, looking for the other's `pid` among the
  nodes.

A good answer shows each path between the two, with the roles and the shares along it, or says
none was found within three hops and that a longer path could still exist.

### 17. Disambiguate a common name

> Screen Mohammed Al-Hassan, born 1984, Jordanian. There will be many hits.

- `search_entities` with `entity_type` `PERSON` and `countries` `["jo"]`, paging through every
  result.
- `get_key_identifiers` on each candidate to compare birth dates, nationalities and name
  records.

A good answer narrows the hits with evidence, by birth date first and then nationality and the
original-script name, and lists the ones it couldn't rule out with the reason. It says how many
hits there were in total, not only the first page.

### 18. Identify by identifier

> Look up LEI `<20-character LEI>` and tell me who owns it.

- `search_entities` with the LEI as `name`, then `get_basic_identifiers` and
  `get_ultimate_beneficial_owners`.

A good answer confirms that the identifier on the profile matches the one asked for before
using it.

## Front office

### 19. Brief a relationship manager

> I'm meeting the CFO of Kestrel Marine Services tomorrow. Give me a one-page risk brief on the
> company.

- `search_entities`, `get_corporate_profile`, `get_ultimate_beneficial_owners`, and
  `get_subgraph` at `radius` 2 twice, once with `requireSanction` and once with `requireSoe`,
  since a rule follows only the links it requires.

A good answer is short: who owns it, who runs it, the flags on any of them, and the nearest
sanctioned or state-owned link. It ends with what the brief doesn't cover: adverse media and
court records, which this MCP doesn't reach.

## What the agent should decline or qualify

- **Adverse media and court decisions.** Not in the documented API. The agent says so rather
  than presenting a clean result as "no adverse media".
- **Screening a whole client book.** One search per name, so a list of hundreds is slow and the
  answer only as good as each match. Batch screening belongs in CheckMate or a bulk feed.
- **The final decision.** The agent shows evidence and possible matches. Whether a hit is the
  client, and whether to onboard, block or file a report, is the compliance officer's.
- **Polixis is not the client file.** Every user shares one set of Polixis credentials, and no
  answer is stored, so the bank's own record of the check stays its job.
