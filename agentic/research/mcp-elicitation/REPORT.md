Status: we reviewed the code of 33 open-source MCP servers, tested Atlassian's hosted Rovo MCP v2 live, and read the public docs of 25 hosted servers we could not test (see [Coverage and next steps](#Coverage-and-next-steps)). Last updated 2026-11-16.

## At a glance

**About 1 in 20 popular servers uses elicitation.** Among the 22 servers we picked for relevance, 1 of the 21 with a known answer does (5%); Stripe's hosted server is unknown. Across everything we reviewed it is 13 of 33 known (39%), but 12 of those 13 were added *because* a code search had already found elicitation in them, so 39% overstates real adoption.

| Slice | Uses elicitation | Share |
|---|---|---|
| Servers picked for relevance (unbiased sample) | 1 of 21 | 5% |
| All servers reviewed (biased toward users) | 13 of 33 | 39% |
| Collaboration (Atlassian ×2, Slack, Microsoft 365, Notion, Google Workspace, Nextcloud) | 1 of 7 | 14% |
| Payments and trading (PayPal, Alpaca, Square, Adyen, Coinbase; Stripe unknown) | 0 of 5 | 0% |
| Fintech data, accounting, enterprise data | 1 of 7 | 14% |
| Cloud and developer platforms | 6 of 9 | 67% |

What the 13 servers that use it ask for (a server can do more than one, so shares add up to more than 100%):

| Asks the user to | Servers | Share |
|---|---|---|
| Confirm a destructive operation | 8 | 62% |
| Disambiguate or fill in a missing choice (project, account, region, ...) | 4 | 31% |
| Sign in, enter a secret, approve a cost or give consent | 6 | 46% |

The docs of 25 hosted servers we could not test tell the same story: only Supabase describes the server asking the user. The rest rely on approval in their own app (Stripe), a confirmation the model or agent provides, client or admin settings, or having no risky tools at all.

Of the 8 servers that confirm destructive operations, 3 refuse or hide the tool when the client can't ask the user (GitHub, Azure MCP, AWS), 2 fall back to a `confirm` argument the model sets (HubSpot, Context7), and 3 go ahead without confirmation (Kubernetes by default, Perforce, Supabase for SQL).

## Question

Which MCP servers use elicitation (the server pausing a tool call to ask the user something), what do they ask for, and what do they do when the client cannot ask the user?

## How we checked

- **Open source:** we cloned each repository, found every place the server asks the user something, and read the code around it. Each server has one finding in the same format: what it asks, for which tool, what happens when the user says no, what happens when the client can't ask, and links to the exact code. Key claims were spot-checked against the code.
- **Closed source:** a throwaway probe calls the server's tools directly, with no LLM involved. It records every question the server asks and answers "no" by default, so a guarded write never runs. Each scenario runs three ways: answering no, answering yes, and with a client that can't ask. Everything it creates is named `elicit-probe-<run>-…` and deleted at the end, and the run fails if anything is left. Code: `agentic/research/mcp-elicitation/probe/` in the connectors repo.

## Key findings

1. **No collaboration or payments server asks the user anything.** That covers Atlassian's official hosted Rovo v2 (tested live), the Atlassian community server, Slack, Microsoft 365, Notion, Google Workspace, Stripe's open code, PayPal, Alpaca, Square, Adyen and Coinbase. The servers that do ask are developer and cloud platforms (GitHub, Azure, AWS, HubSpot, Supabase, Azure DevOps), plus Kubernetes, Perforce, Context7, Home Assistant, Nextcloud, Semgrep, and one fintech server, Monarch.
2. **Confirming a destructive operation is the main use.** Examples: GitHub makes you type the repository name before deleting it; Azure shows Approve/Reject before every destructive or secret-reading command; Supabase confirms destructive SQL and notebook deletes; Perforce confirms deletes; HubSpot confirms deploys to a production account.
3. **Disambiguation is the second use.** Azure DevOps asks which project and team, HubSpot which account, project or app, and AWS Transform which profile and region, when the call doesn't say. Cloudflare has the same situation (a token that reaches several accounts) but returns the list as an error and leaves the model to ask.
4. **Sign-in and secrets.** GitHub and Supabase send the user to a browser page, so the secret never passes through the chat. Monarch asks for the password and MFA code in a form inside the chat.
5. **What happens when the client can't ask the user differs most between servers:**
   - **Refuse:** Azure MCP, AWS, Supabase notebooks.
   - **Hide the tool:** GitHub repository deletion, Supabase secret entry.
   - **Fall back to a `confirm` argument the model sets:** HubSpot, Context7, Supabase cost confirmation.
   - **Go ahead without confirmation:** Kubernetes (by default), Perforce, Supabase destructive SQL.
   - **Move the step elsewhere:** Nextcloud returns the login link in the tool result. Home Assistant waits up to 10 minutes for approval in its own UI.
6. **Model-set confirmation arguments.** Context7 reports that in an internal eval strong models set `confirm: true` without asking the user, which is why it ignores the argument whenever it can ask the user directly. Microsoft 365 (Softeria), Grafana and Salesforce DX rely on this kind of model-mediated confirmation.
7. **Clients misbehave.** Azure's changelog records clients that reported "approved" when the user picked "Reject", so Azure now checks the chosen value too. Supabase's telemetry shows clients cancelling prompts within about half a second without showing them. Home Assistant lets the user's answer only stop a call, never approve one; approval happens in its own UI.
8. **Some servers tie the answer to the exact request.** Supabase asks again if the arguments or the quoted cost changed between the question and the retry, and expires a confirmation after 10 minutes.
9. **Servers that don't ask use other safeguards:**
   - read-only modes and tool allowlists (nearly everyone)
   - sandbox or paper-trading defaults (PayPal CLI, Adyen, Alpaca)
   - drafts that a person approves in the product (Xero)
   - approval links in the product's own UI (Stripe refunds and transfers)
   - write tools only for granted permissions (Sentry)
   - marking tools as destructive and leaving the confirmation to the client (Atlassian Rovo, most others)

## Summary

| MCP | Elicits for destructive operations | Elicits for disambiguation | Other things it asks for | Details |
|---|---|---|---|---|
| Atlassian Rovo v2 (official, hosted, tested live) | No | No | – | {{collaboration}} |
| Atlassian (community) | No | No | – | {{collaboration}} |
| Slack (community) | No | No | – | {{collaboration}} |
| Microsoft 365 / Teams (Softeria) | No | No | – | {{collaboration}} |
| Notion (official, local) | No | No | – | {{collaboration}} |
| Google Workspace (community) | No | No | – | {{collaboration}} |
| Nextcloud | No | No | Sign-in | {{collaboration}} |
| Stripe (hosted) | Unknown (docs describe an approval link in the Dashboard) | Unknown | – | {{payments}} |
| PayPal | No | No | – | {{payments}} |
| Alpaca | No | No | – | {{payments}} |
| Square | No | No | – | {{payments}} |
| Adyen | No | No | – | {{payments}} |
| Coinbase | No | No | – | {{payments}} |
| Monarch Money | No | No | Sign-in credentials (password, MFA code) | {{fintech}} |
| Xero | No | No | – | {{fintech}} |
| QuickBooks | No | No | – | {{fintech}} |
| Massive (formerly Polygon) | No | No | – | {{fintech}} |
| Financial Datasets | No | No | – | {{fintech}} |
| Salesforce DX | No | No | – | {{fintech}} |
| Snowflake Labs | No | No | – | {{fintech}} |
| GitHub | Yes: delete a repository (type its name) | No | Sign-in | {{platform}} |
| Azure MCP | Yes: every destructive or secret-reading command | Yes: clarifying questions from its resiliency agent | Consent before uploading a local file | {{platform}} |
| AWS Labs | Yes: writes, stopping SAP systems, Redshift writes | Yes: profile and region; whether to stop dependent apps | – | {{platform}} |
| Azure DevOps | No | Yes: project and team | – | {{platform}} |
| HubSpot | Yes: deploy or upload to a production account | Yes: account, project, app | Default-account preference | {{platform}} |
| Supabase | Yes: destructive SQL, running or deleting notebooks | No | Cost approval, secret entry | {{platform}} |
| Sentry | No | No | – | {{platform}} |
| Cloudflare | No | No (returns the account list as an error) | – | {{platform}} |
| Grafana | No | No | – | {{platform}} |
| Kubernetes | Yes: configurable rules on tools and cluster operations | No | Licence (EULA) consent | {{other}} |
| Context7 | Yes: admin deletes (type the target) | No | Sign-in suggestion | {{other}} |
| Perforce P4 | Yes: deletes | No | – | {{other}} |
| Home Assistant | No | No | Approval for calls its security policy holds (the answer can only decline) | {{other}} |
| Semgrep | No | No | Feedback on findings (off by default) | {{other}} |

## From vendor documentation (hosted servers, not tested)

For 25 hosted servers we could neither test nor read the code, so this section comes from the vendors' public docs only. Where the docs say nothing, the cell says "not described".

**None of these 25 servers' docs describes the server asking the user through elicitation, except Supabase, whose docs match its open code.** Instead, the docs describe one of these:

- **Approval in the vendor's own app:** Stripe sends the user an approval link for refunds and money transfers; the user approves in the Dashboard, then the agent retries.
- **A confirmation the model or agent provides:** Notion deletes need `user_confirmed: true`; Asana access changes need a second confirming call; Ramp bookings need a preview call then a confirm call, and its published agent instructions say to ask the user; Snowflake's coding agent stops before changing anything and returns the options to the client.
- **Left to the AI client or an admin:** Microsoft blocks writes and sending mail until an admin allows them; HubSpot and PitchBook tell users to set write tools to "Needs Approval" in their AI client; Salesforce tool descriptions say "Confirm with the user before deleting"; Brex recommends approval in the client.
- **No risky tools to confirm:** Box, Linear and Slack document no delete tools; Plaid and most market-data servers are read-only; Quartr offers a read-only option at sign-in.

| MCP | Elicits for destructive operations | Elicits for disambiguation | Other things it asks for | Details |
|---|---|---|---|---|
| Slack (official) | Not described; no delete or edit tools listed | Not described | Sign-in, admin app approval | {{docs}} |
| Microsoft Work IQ (Microsoft 365, Teams, Outlook) | No; writes, deletes and sending mail are off until an admin allows them | Not described | Sign-in | {{docs}} |
| Notion (hosted) | No; deletes need a `user_confirmed: true` argument the model sets | Not described | Sign-in | {{docs}} |
| Linear | Not described; no delete tools documented | No; an ambiguous name returns the matches to the client | Sign-in | {{docs}} |
| Asana | Not described for deletes; access changes need a second confirming call | Not described; workspace chosen at sign-in | Sign-in | {{docs}} |
| Box | Not applicable; no delete tools, sharing tools off by default | Not described | Sign-in | {{docs}} |
| GitHub (hosted) | Unclear; docs say repository deletion "still requires its existing confirmation flow" | Not described | Sign-in, missing-permission prompts | {{docs}} |
| Stripe (hosted) | Approval link for refunds and money movement, approved in the Dashboard (not in the chat) | Not described | Sign-in per account and environment | {{docs}} |
| PayPal (hosted) | Not described, although refund and capture tools exist | Not described | Sign-in | {{docs}} |
| Plaid (Dashboard) | Not applicable; read and diagnostic tools only | Not described; team chosen by argument | Sign-in | {{docs}} |
| Ramp | Agent asks in chat per Ramp's agent instructions; bookings use preview then confirm | Agent asks "which one" per the same instructions | Read-only or full access chosen at sign-in | {{docs}} |
| Brex | Not described; docs recommend approval in the AI client | Not described | Sign-in | {{docs}} |
| FactSet | Not applicable; data tools only | Not described | Sign-in | {{docs}} |
| LSEG | Not applicable; data tools only | Not described; instruments resolved by search tools | Sign-in | {{docs}} |
| S&P Global (Kensho) | Not applicable; data retrieval only | No; the user must give precise identifiers | Sign-in | {{docs}} |
| Moody's | Not applicable for the credit server; the insurance risk server can write with no confirmation described | Not described | Sign-in; the insurance risk server has the user paste an API key into chat | {{docs}} |
| Morningstar | Not applicable; data tools only | Not described; an ID lookup tool exists | Sign-in | {{docs}} |
| PitchBook | Not applicable; data tools only; approval per call is a client setting | Not described | Sign-in | {{docs}} |
| Quartr | Not described, although 10 destructive tools exist; read-only option at sign-in | Not described | Sign-in | {{docs}} |
| HubSpot (hosted) | Writes need "explicit user confirmation", method not described; no delete tools | Not described; account chosen at sign-in | Sign-in | {{docs}} |
| Salesforce (hosted) | Left to the client; delete tools say "Confirm with the user before deleting" | Not described | Admin enables each server | {{docs}} |
| Snowflake (managed) | Coding agent stops before changes and returns options to the client | Not described | – | {{docs}} |
| Azure DevOps (hosted) | Not described, although write and delete tools exist | No; a missing project is an error | Sign-in | {{docs}} |
| Sentry (hosted) | Not described | Not applicable; organisation and project fixed in the URL | Permissions chosen at sign-in | {{docs}} |
| Supabase (hosted) | Yes: destructive SQL, risky notebook runs, notebook deletes | Not described | Cost approval, secret entry in the dashboard | {{docs}} |

## Coverage and next steps

- **Atlassian Rovo v2, hosted: done.** We ran 4 tests: answering no, answering yes, with a client that can't ask, and on the older protocol version. Each created a throwaway child page, edited it, ran a write and two destructive operations on it, then deleted it and emptied it from the trash. The server never asked the user anything and behaved the same in every run.
- **Slack's official hosted server:** not tested, because our organisation blocks it. Covered from the community server's code and Slack's docs.
- **Covered from docs only (25 hosted servers):** everything in the section above. None was signed in to or called. Live tests would need accounts or sandboxes: Stripe test mode, PayPal sandbox and Plaid sandbox are free; Microsoft, Notion, Linear, Asana, Box, HubSpot, Salesforce and the market-data vendors need company accounts.
