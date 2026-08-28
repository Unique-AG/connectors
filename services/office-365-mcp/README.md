# office-365-mcp

An MCP server for Microsoft 365 via Microsoft Graph API.

Users sign in with their own Microsoft account and the server acts as them. It exposes sixteen
MCP tools so far — `get_me`, the signed-in user's own profile; `list_chats`, their Microsoft Teams chats
most recently active first; `list_teams`, the teams they are a member of; `list_channels`, the
channels of one of those teams; `browse_channel`, what was posted in one of those channels;
`teams_search_messages`, full-text search across every Teams message they can see; `teams_read_message`,
one of those messages in full; `list_meeting_transcripts`, whether a Teams meeting was
transcribed and a handle for each transcript; `read_transcript`, what was said in one of those
meetings as speaker-attributed, timestamped turns; and `list_meeting_recordings`, whether a meeting
was recorded, how long each recording runs and who may download it; and `outlook_search_mail`,
which finds a message in the signed-in user's own Outlook mailbox, and `outlook_read_mail`,
which reads one of those in full; and `outlook_browse_folders`, one level of the mail folder
tree; and `outlook_find_recipient`, which resolves a name to the address it sends from — each
one a file of its own — plus `outlook_read_thread`, every message of one conversation this
mailbox holds, and `outlook_list_mail`, the newest messages of one folder in receipt order,
and more land in later PRs, stacked on top of this one, one tool per PR.

An operator chooses which of those tools a deployment runs, and the permissions sign-in asks every
user to consent to are exactly the union of what those tools need — see **Tool surface** below.

## Layout

```
src/office_365_mcp/
  app.py                 Compose the app.
  config.py              Config classes.
  auth.py                Entra auth setup.
  logging.py metrics.py  Cross-cutting utilities.
  graph_client/          Microsoft Graph transport (official SDK).
  shared/                Code that two or more tools must share.
  tools/                 One file per tool, plus the registry that selects and unions them.
  server/                /ready and /manifest endpoints (not tools).
```

This service owns no database schema or migrations. Its only table (oauth_kv) is created by the OAuth store.

**A tool is a file.** `tools/get_me.py` owns the tool name, description, Graph permissions, arguments,
output shape, Graph request, and error messages. A new tool is one file plus one line in the registry.
No base class, no decorator. A tool module publishes `TOOL_NAME`, `GRAPH_PERMISSIONS` and `register`.

`tools/__init__.py` is the central registry. `resolve()` turns an operator's selection into both
halves of one answer: the tool modules to register, and the union of their `GRAPH_PERMISSIONS` as the
scope list sign-in asks for. Both are derived from the tool modules themselves, never written by
hand. Entra must receive every Graph permission at startup—a forgotten one cannot be obtained
later—so `create_app` resolves once and hands the same `Selection` to `build_auth` and
`register_tools`. `tests/test_app.py` reads the tool *files* from disk to verify that every
registered tool's permissions reach the consent screen.

**`shared/` is what a file-per-tool costs.** Two files are free to disagree, and this package is the
list of things they must not: `handles.py` (the `teams:///` grammar — every shape this connector
mints, its parser and its speller, and the permission each Teams surface is read under),
`messages.py` (what a Teams message is — the shape it is answered in, the sender normalised out of
every identity shape Graph answers with, the Teams HTML a body is unwound from, and the test for
"did a person write this", so that the same message found by one tool and read by another is one
type normalised by one function rather than two that agree), `meetings.py` (how a meeting is
reached — a join URL resolved to the meeting it identifies, which occurrence of a series a time
window means, and how far "newest first" holds), `identity.py` (who the signed-in user
is — `get_me` reports
it, and it is the fact every other answer gets correlated against, so a second tool asking with a
`GET /me` of its own would be a second answer to one question) and `seam.py` (the Graph client a
tool is handed, with the per-tool On-Behalf-Of token inside it, and the Graph-failure-to-advice
mapping, because a model reads every refusal on this server as one voice). A
thing belongs there when two tools would otherwise each need a copy *and* a difference between the
copies would be a bug a caller could see — a handle one tool minted and another answers 404 to, two
answers to "who am I", a refusal that sounds like a different server. What does not belong there is
anything one tool could own — a description, an argument, an answer shape, a request, a refusal.

The layering rules are that **`shared/` imports no tool module, and only `shared/seam.py` imports
FastMCP** — the seam is where the framework is spoken, which is what keeps it out of the handle
grammar and the rest of the vocabulary; that **`graph_client/` imports nothing of this application
at all**, taking its own frozen `GraphSettings` instead of reading config; that **`tools/` imports
`shared/`, `graph_client/` and FastMCP and nothing else of this package** — not `server/`, or the
tool file is one in name only; that **no tool module imports another tool module**, which is what
independent means and is the rule the whole layout exists for; that **only `create_app` constructs a
config**, so nothing downstream can quietly re-read the environment and disagree with the app it
runs in; that **`shared/handles.py` is the only module that builds or parses a `teams:///` URI**
(showing the shape to a model in a description, an `examples=` or a refusal is prose and is not
that); and that **a package is entered through its `__init__`** — `graph_client/`, `server/` and
`tools/` each publish an `__all__`, and `shared/` deliberately does not, being a grouping whose
modules are the units and whose consumers say which one they depend on at the import line.

`tests/test_layering.py` enforces them, and each rule is paired with a guard that fails if the rule
has gone vacuous — an empty tree to walk, a missing file to forbid reaching past, a framework
nothing imports any more, a second tool module that stopped existing so that "another tool module"
named nothing, a package with no `__all__` to insist on. One rule of the finished set is still
absent for exactly that reason and is named in that module: nothing may address a single meeting
recording, which needs a recordings listing to be the surface it protects. It arrives with the tool
that lists them, and the numbering is the finished one so that arriving costs a class.

## Auth

Entra via FastMCP's AzureProvider. FastMCP handles OAuth 2.1: /authorize, PKCE, callback, refresh, and
On-Behalf-Of exchange. This service chooses the app registration and state store only.

The provider mounts these endpoints (must be reachable unauthenticated, not behind an ingress prefix):
```
/authorize  /token  /register  /auth/callback  /consent
/.well-known/oauth-authorization-server
/.well-known/oauth-protected-resource/mcp
```

**App registration requirements.** Missing values here do not always stop the provider from
starting. Some only make every login fail, with no startup error:

- A **Web platform** redirect URI of exactly `$PUBLIC_BASE_URL/auth/callback`
- An Application ID URI (defaults to `api://$ENTRA_CLIENT_ID`) exposing the scope **access_as_user**
  (Entra omits OIDC scopes from the scp claim, so a custom scope is the only gate)
- `"requestedAccessTokenVersion": 2` in the manifest
- A client secret (ENTRA_CLIENT_SECRET required for On-Behalf-Of)
- A single tenant ID (common/organizations/consumers rejected at startup; the provider validates
  all tokens against one issuer derived from this value, so multi-tenant values would reject all of
  them rather than accept all tenants due to issuer mismatch)

**Graph permissions.** Tools declare what they need. `create_app` passes the union of the *selected*
tools' permissions to the provider as `additional_authorize_scopes`. Entra issues one token per
resource. The code exchange asks for this service's scope only. Tools redeem Graph permissions per
call via On-Behalf-Of. A permission never requested at sign-in cannot be consented to.

| Permission | Type | Admin consent | Used by |
| --- | --- | --- | --- |
| `User.Read` | Delegated | No | `get_me`, `list_meeting_recordings` (the organiser-only check) |
| `Chat.Read` | Delegated | No | `list_chats`, `teams_search_messages`, `teams_read_message` (chats) |
| `Team.ReadBasic.All` | Delegated | No | `list_teams` |
| `Channel.ReadBasic.All` | Delegated | No | `list_channels` |
| `ChannelMessage.Read.All` | Delegated | Yes, in most tenants | `browse_channel`, `teams_search_messages`, `teams_read_message` (channels) |
| `OnlineMeetings.Read` | Delegated | No | `list_meeting_transcripts`, `list_meeting_recordings` (resolving a join URL to a meeting) |
| `OnlineMeetingTranscript.Read.All` | Delegated | **Yes** | `list_meeting_transcripts`, `read_transcript` |
| `OnlineMeetingRecording.Read.All` | Delegated | **Yes** | `list_meeting_recordings` |
| `Mail.Read` | Delegated | No | `outlook_search_mail`, `outlook_read_mail`, `outlook_browse_folders`, `outlook_find_recipient` (the fallback), `outlook_read_thread`, `outlook_list_mail` |
| `People.Read` | Delegated | No | `outlook_find_recipient` |

`Team.ReadBasic.All` is the least-privileged one Microsoft documents for `/me/joinedTeams`, and it
is a separate scope from the broad message permission below on purpose: a tenant that refuses
`ChannelMessage.Read.All` can still list its teams, and `list_teams`' own 403 names only the
permission its own request needed rather than sending an administrator after one that was never
missing.

`Chat.Read` rather than the least-privileged `Chat.ReadBasic` because listing chats by recency needs
`$expand=lastMessagePreview`, and a message preview is a message — which "read the names and members
of chats" does not cover. It is spelled in `shared/handles.py` rather than in the tool file, because
which Teams surface a permission covers is the handle grammar's knowledge; the tool still declares
its own tuple, which is what its 403 is worded from.

The two rows a tool appears in *parenthesised* are the per-surface case, and it is the reason
`MessageHandle.permission` exists. Graph's permissions for a message read are per surface, so
`teams_read_message` has to redeem both — the token is exchanged before the tool sees its argument — while
its 403 names only the one the read was actually made under. Naming both there would be the same
defect as naming none: an administrator handed two names may grant the one that was never missing.

**Transcripts need a tenant setting as well as a permission, and this is the one that surprises
people.** Microsoft Graph access to Teams meeting transcripts is off by default and *"agents and
apps can't access meeting transcripts, regardless of app-level permissions"* until a Teams
administrator turns it on — Teams admin centre → Meetings → Meeting settings → Transcript API
access, or `Set-CsTeamsMeetingConfiguration -EnableGraphTranscriptAccess $true -Identity Global`.
There is no Graph API to set it and no request-side workaround, so it is an onboarding step next to
admin consent rather than something this connector can fix; `services/teams-mcp` learned this in PR
#762 and `docs/recordings-and-transcripts/operator.md` documents it. Until it is on, every call to
`list_meeting_transcripts` and `read_transcript` fails with that remedy named — and only those two:
Microsoft scopes the setting to transcript resources, so nothing else here is affected. The
neighbouring `-EnableAttributedTranscripts` setting is *not* a prerequisite: when it is off,
`read_transcript` degrades to Microsoft's unattributed format and reports `speaker_attribution:
false` rather than failing.

**That setting does not cover recordings, and the asymmetry is why they are a separate tool.**
Microsoft scopes it to transcript resources only — the change-notification reference says so in as
many words — and neither recordings reference page publishes a tenant control or an inner error code
of its own. So in a default tenant (the switch off, admin consent granted) `list_meeting_transcripts`
answers `403` while `list_meeting_recordings` answers normally, which one combined artifact tool
could not do without either failing the whole call or growing a status per artifact — and the
per-artifact status is exactly what makes the "read `status` first" shape unreadable.
`OnlineMeetingRecording.Read.All` needs admin consent in its own right and separately from the
transcript permission, so a tenant can grant either without the other. Each tool names only the
permissions its own request needs, and it names all of them, because neither Graph nor Entra says
which one is missing.

**A recording is answered as metadata and availability; its bytes are never returned, by anything
here.** Graph streams an MP4 inline with no ranged contract on that path, a Teams meeting can run
thirty hours, and a model cannot watch video — so a tool that returned one would be a defect wearing
a feature's clothes. `recordingContentUrl` is no better: it opens only with this connector's own
bearer token, so passing it on is either useless or a token leak. What `list_meeting_recordings`
answers is "there is a 47-minute recording from Tuesday, only the organiser can download it, and
here is the transcript instead" — existence, start and end, a derived `duration_seconds` (Microsoft
publishes no duration property at all), and `content_correlation_id`, which is Microsoft's own link
to the transcript of the same call. Layering rule 7 forbids any module from addressing a single
recording, because that is the only door to those bytes and the change that opens it looks like a
convenience. The organiser-only rule is reported rather than recited: Microsoft permits only the
meeting organiser to download a recording under delegated access, the *metadata* is not so
restricted, and answering "there is no recording" for a participant would be a wrong answer nobody
could detect — so an unreachable recording is always listed, with `content_access` saying which side
of the rule this user is on.

The two meeting permissions are separate scopes and are granted independently, which is the point of
asking for both: `OnlineMeetings.Read` is the least privilege Microsoft documents for resolving a
join URL to a meeting and needs no administrator, while reading a transcript resource needs one.
A tenant can grant the first and withhold the second. Neither Graph's 403 nor Entra's AADSTS65001
says which of the two is missing, so every refusal names both. Only the lister spends both —
`read_transcript` is handed a meeting id somebody already resolved, so it declares the
admin-consented one alone and still answers in a tenant that withholds `OnlineMeetings.Read`.

`ChannelMessage.Read.All` is the broad one, and it is requested deliberately. `Chat.Read` alone is
enough for Graph to *accept* a `chatMessage` search, but Microsoft documents that a search never
returns more than the equivalent GET would, and every channel-message GET in v1.0 requires
`ChannelMessage.Read.All` — so without it a search silently covers chats only and reports nothing
missing. Asking for it at sign-in makes a tenant that withholds it fail visibly at consent rather
than serve half an answer per query. It is also what `browse_channel` spends on its one request, and
what `teams_read_message` needs for a channel message. It is the first permission here that needs an
administrator, and the first row where one tool needs two: neither Graph's 403 nor Entra's
AADSTS65001 says which of the two was missing, so
`teams_search_messages` names both in every refusal — handed one name, an administrator may grant the
permission that was never missing and watch the identical failure. A search has no choice about
that, because a search happens before anything knows which surface a hit will be on; a *read* does,
which is why its 403 names one. `shared/seam.py` writes the same names out once more, by hand, as
`REQUESTABLE_PERMISSIONS`: every other check compares the tool files against a list derived from
those same files, so a misspelling is on both sides of the comparison and holds — and Entra rejects
an authorize request carrying a scope it does not know, which fails every sign-in for every user.
Adding a name there is the deliberate act this table records.

**`Mail.Read` is the first permission here that needs no administrator and still reads a message
body.** Microsoft publishes `AdminConsentRequired: No` for every delegated `Mail.*` permission, so
an Outlook read surface costs a tenant nothing an administrator has to sign, where every Teams
preset past `teams-chat` costs one. That is Microsoft's rule about the permission and not a promise
about a tenant: a tenant running a restricted user-consent policy still stops an unprivileged user
at "Need admin approval", and nothing in this service's logs says so.

`Mail.ReadBasic` is deliberately not used. It withholds `body`, `previewBody`, attachments and
extended properties, and a hit list with no preview is a list of subjects a model cannot triage —
so it would buy a second name on the consent screen and no narrower access to anything read here.

The channel inventory is two permissions, and they are separate scopes on purpose:
`Channel.ReadBasic.All` lists a team's channels, `ChannelMessage.Read.All` reads what was posted in
one. Each is the least-privileged permission Microsoft documents for its collection. A tenant
refusing the message permission still lists teams and channels, and each tool's 403 names only the
permission its own request needed.

**State.** Every token is a reference token re-validated on each request. State location decides
whether a restart or second replica causes loss. FastMCP defaults to an encrypted file tree in
process home. This service uses Postgres. The store creates table oauth_kv on first use. The
database user needs CREATE on its schema. No migration exists because the columns are the store
library's to define and keep in sync — a revision duplicating them would be ours to keep in sync,
which breaks when the library changes its schema. Rows are encrypted with a key derived from the
client secret. Rotating the secret requires each signed-in user to re-login once. A decryption
failure is a cache miss, not an error. Widening the tool surface costs the same re-login, for the
same reason: the authorize request changes.

## Tool surface

Which tools a deployment runs, and therefore which delegated permissions every one of its users is
asked to consent to. Set **exactly one** of:

```bash
TOOLS_PRESET=teams                       # a named surface
TOOLS_ENABLED=get_me                     # or name the tools
```

Both set is a startup error naming which to remove. Neither set is a startup error too: there is
**no default**, because a default of "every tool" would make the widest consent screen what a
deployment gets by not choosing. `TOOLS_PRESET=teams` keeps "everything" a one-word but chosen value.

| preset | what it can do | tools besides `get_me` | permissions | admin consents |
| --- | --- | --- | --- | :-: |
| `teams-chat` | name the live conversations — not read them | `list_chats` | `User.Read`, `Chat.Read` | 0 |
| `teams-messages` | find a message anywhere and read it in full | `list_chats`, `teams_search_messages`, `teams_read_message` | + `ChannelMessage.Read.All` | 1 |
| `teams-channels` | walk a team's channels and read what was posted | `list_teams`, `list_channels`, `browse_channel` | `User.Read`, `Team.ReadBasic.All`, `Channel.ReadBasic.All`, `ChannelMessage.Read.All` | 1 |
| `teams-transcripts` | find a meeting and read what was said | `list_chats`, `list_meeting_transcripts`, `read_transcript` | `User.Read`, `Chat.Read`, `OnlineMeetings.Read`, `OnlineMeetingTranscript.Read.All` | 1 |
| `teams-recordings` | say whether a meeting was recorded and who may get at it | `list_chats`, `list_meeting_recordings` | `User.Read`, `Chat.Read`, `OnlineMeetings.Read`, `OnlineMeetingRecording.Read.All` | 1 |
| `teams-meetings` | both of the above for one meeting | `list_chats`, `list_meeting_transcripts`, `read_transcript`, `list_meeting_recordings` | + both meeting permissions | 2 |
| `teams` | every Teams tool | the nine of them | all eight | 3 |
| `outlook-read` | find a message in your own mailbox, read it in full, walk the folder tree, resolve a name to an address, read a whole thread, and list a folder in receipt order | `outlook_search_mail`, `outlook_read_mail`, `outlook_browse_folders`, `outlook_find_recipient`, `outlook_read_thread`, `outlook_list_mail` | `User.Read`, `Mail.Read`, `People.Read` | 0 |

`get_me` is always on, which is why no preset lists it — each of those seven rows is one
tool wider than its third column. Read the second column before choosing: `teams-chat` is the narrowest surface there
is and the only one that asks for **no** administrator, and the reason it costs nothing is exactly
that it cannot read a *chat* message — the two tools that can (`teams_search_messages`, `teams_read_message`)
both declare `ChannelMessage.Read.All`, which an administrator has to grant even though the message
is a chat. Reading chat messages is `teams-messages`.

Every preset is a named set written out by hand, `teams` included, each with a test asserting what
it costs a tenant and that every *argument* its tools require can be minted by another member of
the same preset. `teams` names the nine Teams tools rather than the registry, and that is the one
line of maintenance this table buys: a preset derived from the registry would take in the first
tool of another product on the day it lands, put that tool's permission on the consent screen of
every `teams` deployment, and cost every signed-in user a fresh sign-in — with no edit for anyone
to review. `tests/test_tool_selection.py` refuses a derived preset, and refuses a registered tool
that no preset names. The names carry a product axis from the
start: `outlook-*` and `sharepoint-*` join the table as those tools land, without re-cutting these.

The `teams-transcripts` row is the one this knob was built for: reading meeting transcripts costs
**one** admin consent and does not drag in `ChannelMessage.Read.All`, the permission to read every
channel message in the tenant. It does need one thing no permission can carry — Graph access to Teams
transcripts is a tenant-wide Teams setting, off by default, that only a Teams administrator can turn
on (Teams admin centre → Meetings → Meeting settings → Transcript API access). `list_meeting_recordings`
is **not** behind that switch, which is why the two are separately selectable.

Nothing stops a hand-written `TOOLS_ENABLED` from enabling a tool whose arguments nothing in the
selection can mint — `read_transcript` without `list_meeting_transcripts`, say. That is deliberate:
a tool that takes a `teams:///` handle names the tool that mints it in its own refusal, on first use,
and the alternative is a declaration on every tool file plus a validator to read it. (A tool that
takes a plain Graph id, like `list_channels`, answers a fabricated one with the generic "check the id
came from a tool response verbatim".) The presets we ship are checked, per argument.

`get_me` is **always on**, whatever the selection. It is how the server resolves "me"—the identity
every other answer is correlated against—and `User.Read` is the least-privileged delegated permission
Microsoft publishes and needs no administrator. So `TOOLS_ENABLED` lists only the rest, presets need
not mention it, and **no deployment asks for zero permissions**: every one asks for at least
`User.Read`. Naming it explicitly is accepted, not an error.

An unknown tool name, an unknown preset, an empty list, both variables, or neither each aborts
startup and names the remedy. A typo never quietly costs a tool.

**The manifest.** At startup, and on `GET /manifest`, the server prints what it resolved to: the
tools, the exact delegated permissions in Entra's spelling, and which of them need admin consent.
That list is what an operator hands their Entra administrator, and it is the only place it is written
down—so it is worth reading before the first sign-in rather than after. A scope the app registration
does not carry fails at the *authorize* hop, for every user, with nothing in this service's logs:
Azure omits Graph scopes from the session token, so the server cannot check its own ask against the
registration. The manifest prints no consent URL; provisioning the registration is out of scope.

The manifest also warns when an exposed tool's description points a model at a tool this deployment
does not expose. It only warns—tool prose references its siblings densely, and requiring every
mention would drag permissions into a deployment that wanted none of them.

Narrowing a live deployment is free. Widening one adds a permission to the authorize request, so
every signed-in user meets AADSTS65001 on the new tool until they sign in again.

In Helm, this rides the chart's existing `env:` map. `values.yaml` deliberately defaults neither
variable, and `values.schema.json` requires exactly one and carries the preset names as an `enum`, so
a missing or misspelled selection fails `helm install` instead of crash-looping a pod.

## Microsoft Graph

`graph_client/` wraps the official msgraph-sdk. It does not acquire tokens. FastMCP's On-Behalf-Of
exchange hands the caller's Graph token as a string; this package sends it.

- **One transport, many callers.** `create_graph_transport(settings)` builds the `httpx.AsyncClient`
  (connection pool + SDK middleware) once. `graph_client_for(transport, token)` wraps it per call.
  Per-call clients cause TLS handshakes and leak pools.

- **Throttling is the SDK's.** Its retry middleware waits out Retry-After on 429/503/504 three
  times, on asyncio.sleep, so a wait never blocks the event loop. This is Graph's documented
  contract. Nothing here re-implements it. There is no rate limiter. What is added is the typed
  outcome: throttling that outlasts the retries reaches callers as GraphThrottled with
  retry_after_seconds, not a status code to re-interpret. Graph rate limits with a 503 as well as
  with a 429, and Retry-After is the only thing that says which it did — so a 5xx carrying that
  header is GraphThrottled and the same status without it is GraphUnavailable. Counted as an
  outage, throttling sends an operator after an incident when the remedy is quota.

- **How long a call may take** is `GRAPH_REQUEST_TIMEOUT_SECONDS` (30), `GRAPH_CONNECT_TIMEOUT_SECONDS`
  (10) and `GRAPH_MAX_RETRIES` (3), translated into `GraphSettings` at the composition root — nothing
  under `graph_client/` reads the environment. What an operator is turning is the worst case of one
  tool call: the request timeout times `GRAPH_MAX_RETRIES + 1` attempts, before any Retry-After wait,
  per Graph call, and a paged walk makes several.

- **Errors are four types (four remedies):** `GraphThrottled` (429, or a retriable 5xx that named a
  delay), `GraphForbidden` (401/403), `GraphNotFound` (404), `GraphUnavailable` (a 5xx with nothing
  to wait for, unreachable, or an SDK failure carrying no response at all). Wrap a tool's Graph work
  with `with graph_errors(TOOL_NAME):`, and each Graph call inside it with `with graph_step(STEP):`.

- **Two levels of measurement, and why both.** `graph_operations_total` and
  `graph_operation_duration_seconds` count one *tool call*; `graph_steps_total` and
  `graph_step_duration_seconds` count one *Graph call inside it*. The operation says a tool got
  slower, the step says which of its Graph calls did — `list_meeting_recordings` makes three. Both
  labels are names chosen in code and never read off a URL, which is a hard rule rather than a
  preference: a Graph URL here is made of almost nothing but chat, message and meeting ids, and a
  label taken off one is a time series per id. `tests/test_graph_metrics.py` enforces that over every
  module and pins the step vocabulary to an exact set, so adding a step is a deliberate act.

- **Paging follows @odata.nextLink** via `collect_pages`, with item and scan caps. A channel's
  messages are the exception and are not walked at all: Graph allows about one request a second on
  a given channel for the whole app across the tenant, so `browse_channel` makes exactly one and
  `$top` is its window. Search uses from/size offsets.


- **An empty page carrying a next link means keep going, and the walk is ours because of it.**
  Microsoft documents both halves: "A page of results might contain zero or more results", and read
  on "until the `@odata.nextLink` property is no longer returned"
  ([paging](https://learn.microsoft.com/en-us/graph/paging)). The stop condition is the absence of
  the link, never an empty `value`. The SDK's `PageIterator.enumerate` returns `False` for a page
  whose `value` is empty and its `iterate` reads that as the end of the collection — so a collection
  Graph answers `[1 item + nextLink]`, `[nothing + nextLink]`, `[3 more]` came back as one item.
  This is not hypothetical on this service's own endpoints: a
  [known issue](https://learn.microsoft.com/en-us/graph/known-issues) has `getAllRecordings` and
  `getAllTranscripts` returning "a `200 OK` response with an empty collection and an
  `@odata.nextLink`", with the published workaround "Continue following `@odata.nextLink` even when
  the collection is empty." Every list-shaped tool here says "that is all of it" by coming back short
  of `limit`, so believing an empty page does not merely lose items: it turns a window with more
  behind it into a claim that there is not. `collect_pages` walks through them, bounds a *run* of
  them (`MAX_EMPTY_PAGES`, and it is not pooled with the scan cap: an empty page spends no scan
  budget, so a shared budget is no bound on empty pages at all), and raises `GraphPagingUnending`
  rather than answering short — because a short answer means a cap.

- **Trap:** The SDK bearer provider does not consult the allowed-hosts validator, so the host and
  scheme checks live in `_CallerTokenProvider` itself. The live exposure is `@odata.nextLink`: a next
  link re-enters `send_async` and therefore re-authenticates, so a link pointing off Graph would be
  handed the caller's delegated token. Redirects cannot reach it — the auth provider is consulted
  once per logical request, before the middleware pipeline the redirect handler loops inside.

## Logs

Every line is one pino-json object on **stderr**, at `LOG_LEVEL` (default `info`), which is what the
chart's `logging.unique.app/format: pino-json` pod label promises the log pipeline. Nothing is
written to stdout: uvicorn's access lines, FastMCP's own lines and Python warnings are all routed
through the same handler, because each one arrives outside that contract by default —
`src/office_365_mcp/logging.py` says how and why for each.

Every line carries `correlation_id`, so a line can always be grouped: the trace id of the active
span, else the MCP request id of the message being handled, else the id of the HTTP request, else the
id of this process's boot. `trace_id`, `request_id`, `session_id` and `http_request_id` appear beside
it when they are known. An `x-request-id` from a gateway is used as-is.

Secrets never reach a line. A field whose name reads like a credential (`Authorization`,
`x-api-key`, `client_secret`, however it is spelled) is replaced with `[Redacted]`, nested inside an
`extra=` as well; so is a value shaped like one — a bearer token, a JWT, a password in a URL, a
credential in a query string — wherever it appears, including inside an exception's stack. Two
independent nets, because a secret with an innocent name and an innocent-looking secret are
different failures.

## Run locally

```bash
cd services/office-365-mcp
cp .env.example .env   # fill DB_* and ENTRA_*
uv sync
uv run office-365-mcp
```

No migration needed. The database needs an empty schema the app user can CREATE in. The OAuth
store creates its table on first use.

- MCP endpoint: `http://localhost:9544/mcp` (HTTP, authenticated)
- Health: `GET /health` (liveness via unique_mcp.monitoring.setup_ops)
- Probe: `GET /probe` (process-up via setup_ops)
- Ready: `GET /ready` (503 when Postgres unreachable; asks the OAuth store, the only connection
  a sign-in depends on. A different connection could report ready while sign-in still fails.)
- Manifest: `GET /manifest` (the resolved tool surface and the exact permissions sign-in asks for;
  unauthenticated, and it leaks nothing—the same scopes are in the authorize URL already)
- Metrics: `GET /metrics` (Prometheus via setup_ops). Beside unique_toolkit's own HTTP series, four
  say what this connector asked Microsoft Graph for: `graph_requests_total{operation,status}`,
  `graph_request_duration_seconds{operation}`, `graph_throttled_total{operation,retried}` and
  `graph_pages_scanned{operation}`. `operation` is the tool's own name and never a URL — a label
  taken off a Graph URL would be one time series per chat. `status` is the remedy the failure needs
  (`forbidden`, `not_found`, `throttled`, `unavailable`), not the HTTP code. `retried` says whether
  the SDK spent its retries on the throttling or refused the wait Graph asked for.
- Traces: off unless an `OTEL_*` variable says where to send them. `OTEL_TRACES_EXPORTER=console`
  prints spans to stderr; an `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` sends them to a collector and
  needs nothing else. `.env.example` lists the knobs, the chart wires them from
  `internalServices.dependencies.otelTraces.enabled`. Latency stays on `/metrics` only: the ASGI
  instrumentation's own duration histogram is switched off so one series measures it. No span
  carries a Graph URL: the SDK sets the full URL as `url.full` by default in two places—the request
  span and the URL replacer's own span—and both are closed, because a Graph URL here is a chat,
  message or transcript id and almost nothing else. The request span keeps `url.uri_template`,
  which is what a latency breakdown groups by.

## Tests

Integration tests start a Postgres container (Docker must be running). The app under test
creates the one table it needs, as in production.

```bash
uv run pytest
```

## Lint & type-check

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run basedpyright .        # type check
```
