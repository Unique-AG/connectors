# office-mcp

An MCP server over Microsoft 365, via the Microsoft Graph API.

Users sign in with their own Microsoft account and the server acts as them. It exposes ten tools
so far — `get_me`, `list_chats`, `list_teams`, `list_channels`, `browse_channel`, `search_messages`,
`read_message`, `list_meeting_transcripts`, `read_transcript` and `list_meeting_recordings` — and
more land in later PRs, stacked on top of this one.

## Layout

```
src/office_mcp/
  app.py                 composition root — every config and collaborator is built here, once
  config.py              one BaseSettings class per concern, read only at the root
  auth.py                Entra auth: which app registration, and where its state lives
  logging.py metrics.py  cross-cutting, used by both sides below
  graph_client/          the Microsoft Graph transport — the official SDK, one caller's token
  features/              what the connector does — one module per slice (identity, chats, channels,
                         message search/read, meeting transcripts, meeting recordings)
  server/                how it's exposed over MCP — the tools, the errors they report, /ready
```

This service owns no database schema and has no ORM, no engine and no migrations. Its only table
(`oauth_kv`) belongs to the OAuth state store, which creates it itself — see **State** below.

A feature module owns three things that belong together: the Graph request it makes, the shape it
answers with, and the delegated Graph permissions that request needs. `server/tools.py` declares the
MCP tools over them and is the only place that knows about MCP.

Where two features answer about the same thing, the shared vocabulary lives in one of them rather
than in both: `message_search` owns the `teams:///` message handle — its three shapes, its parser and
which permission each surface is read under — and the sender shape, and `message_read` imports both.
Search is where a handle and a search-shaped sender are minted, and two modules that each knew how
to spell a handle would be free to disagree; the disagreement would surface as a search result that
cannot be read. The same rule runs one step further out: `channels` takes the message shape and the
"did a person write this" test from `message_read`, so a post browsed in a channel and a message read
by handle are the same type, normalised by the same function. The meeting-side handles
(`teams:///meetings/…`, `teams:///transcripts/…`) belong to `transcripts` for the same reason and by
the same rule, and `chats` asks it for one rather than assembling a URI: a layering rule says each
handle *family* has exactly one speller, and names which module owns which. `recordings` borrows the
most of any module — the meeting handle, the join-URL resolve, the occurrence window and the "is an
empty answer settled" inference — and mints no handle of its own, because there is nothing to read:
a recording is answered as metadata, never as video.

The layering rules are that **nothing under `features/` may import from `server/`** — the server
wires features together, never the reverse — nor **from FastMCP**, since deciding what an MCP client
is told (a `ToolError`, a schema, an annotation) is the tool layer's job; that **`graph_client/`
imports neither `features/` nor `config`**, taking its own frozen `GraphSettings` instead, that
**`server/` does not import the Graph SDK** — nor the `kiota_*`/`msgraph_core` request layer
underneath it, which is how a Graph call gets shaped without ever spelling `msgraph` — since a tool
declares and exposes while the request belongs to a feature, and that
**only `create_app` constructs a config**, so nothing downstream can quietly re-read the
environment and disagree with the app it runs in. `tests/test_layering.py` enforces all of them, and
each rule is paired with a guard that fails if the rule has gone vacuous — an empty tree to walk, a
missing file to forbid reaching past. None of them is conditional on a package that has yet to land,
because they all have now: a rule that stops running is a failure there and not a skip.

## Auth

Microsoft Entra, through FastMCP's own `AzureProvider`. There is no OAuth code in this service:
the provider is an OAuth 2.1 proxy that presents a DCR-capable authorization server to MCP clients
and translates it onto the app registration, so `/authorize`, PKCE on both hops, the redirect
callback, refresh, and the On-Behalf-Of exchange that turns a user's token into a Graph one are all
its own. `auth.py` decides only which app registration to use and where the state is kept.

The endpoints it mounts, all of which must be reachable unauthenticated — they *are* the
authentication — and must not be swallowed by an ingress path prefix:

```
/authorize  /token  /register  /auth/callback  /consent
/.well-known/oauth-authorization-server
/.well-known/oauth-protected-resource/mcp
```

**App registration requirements.** The provider will not start, or will reject every login, unless
all of these hold:

- a **Web** platform redirect URI of exactly `$PUBLIC_BASE_URL/auth/callback`;
- an Application ID URI (defaults to `api://$ENTRA_CLIENT_ID`) exposing a scope named
  **`access_as_user`** — Entra leaves OIDC scopes out of the `scp` claim, so a custom API scope is
  the only thing that can gate access to this server;
- `"requestedAccessTokenVersion": 2` in the manifest;
- a client secret (`ENTRA_CLIENT_SECRET`), which On-Behalf-Of cannot be done without;
- a single tenant. `ENTRA_TENANT_ID=common`/`organizations`/`consumers` is rejected at startup:
  the provider validates every token against one issuer derived from that value, so a
  multi-tenant authority would reject all of them rather than accept all tenants.

**Graph permissions** belong to the tools that need them, and `create_app` passes their union to
the provider as `additional_authorize_scopes`. They ride the authorize request only — Entra issues
one token per resource, so the code exchange asks for this API's own scope and each tool redeems a
Graph one per call via On-Behalf-Of. That redemption can only succeed for a permission already
consented to, which is why sign-in has to ask for it:

| Permission | Type | Admin consent | Used by |
| --- | --- | --- | --- |
| `User.Read` | Delegated | No | `get_me` |
| `Chat.Read` | Delegated | No | `list_chats`, `search_messages`, `read_message` (chats) |
| `Team.ReadBasic.All` | Delegated | No | `list_teams` |
| `Channel.ReadBasic.All` | Delegated | No | `list_channels` |
| `ChannelMessage.Read.All` | Delegated | Yes, in most tenants | `browse_channel`, `search_messages`, `read_message` (channels) |
| `OnlineMeetings.Read` | Delegated | No | `list_meeting_transcripts`, `list_meeting_recordings` (resolving a join URL to a meeting) |
| `OnlineMeetingTranscript.Read.All` | Delegated | **Yes** | `list_meeting_transcripts`, `read_transcript` |
| `OnlineMeetingRecording.Read.All` | Delegated | **Yes** | `list_meeting_recordings` |

**Transcripts need a tenant setting as well as a permission, and this is the one that surprises
people.** Microsoft Graph access to Teams meeting transcripts is off by default and *"agents and apps
can't access meeting transcripts, regardless of app-level permissions"* until a Teams administrator
turns it on — Teams admin centre → Meetings → Meeting settings → Transcript API access, or
`Set-CsTeamsMeetingConfiguration -EnableGraphTranscriptAccess $true -Identity Global`. There is no
Graph API to set it and no request-side workaround, so it is an onboarding step next to admin
consent rather than something this connector can fix; `services/teams-mcp` learned this in PR #762
and `docs/recordings-and-transcripts/operator.md` documents it. The neighbouring
`-EnableAttributedTranscripts` setting is *not* a prerequisite: when it is off, `read_transcript`
degrades to Microsoft's unattributed format and reports `speaker_attribution: false` rather than
failing.

**That setting does not cover recordings, and the asymmetry is why they are a separate tool.**
Microsoft scopes it to transcript resources only — the change-notification reference says so in as
many words — and neither recordings reference page publishes a tenant control or an inner error code
of its own. So in a default tenant (the switch off, admin consent granted) `list_meeting_transcripts`
answers `403` while `list_meeting_recordings` answers normally, which one combined artifact tool
could not do without either failing the whole call or growing a status per artifact.
`OnlineMeetingRecording.Read.All` does need admin consent in its own right, separately from the
transcript permission, so a tenant can grant either without the other.

`Chat.Read` rather than the least-privileged `Chat.ReadBasic` because listing chats by recency needs
`$expand=lastMessagePreview`, and a message preview is a message.

`ChannelMessage.Read.All` is the broad one, and it is requested deliberately. `Chat.Read` alone is
enough for Graph to *accept* a `chatMessage` search, but Microsoft documents that a search never
returns more than the equivalent GET would, and every channel-message GET in v1.0 requires
`ChannelMessage.Read.All` — so without it a search silently covers chats only and reports nothing
missing. Asking for it at sign-in makes a tenant that withholds it fail visibly at consent rather
than serve half an answer per query. It is also what `browse_channel` and `read_message` need for a
channel message — Graph's permissions for a message read are per surface, so the reader's own 403
names whichever one the handle it was given required.

The two channel-inventory permissions are the least-privileged ones Microsoft documents for their
collections, and they are separate scopes on purpose: a tenant that refuses
`ChannelMessage.Read.All` can still list its teams and channels, and each tool's 403 names only the
permission its own request needed rather than sending an administrator after one that was never
missing.

**State.** Every token the server issues is a reference token re-validated on each request, so
where that state lives decides whether the deployment survives a restart or a second replica.
FastMCP's default is an encrypted file tree under the process's home directory; this service uses
Postgres instead, in a table (`oauth_kv`) the store creates itself on first use — so the database
user needs `CREATE` on its schema, and there is no migration for it (the columns are the store
library's to define, and a revision duplicating them would be ours to keep in sync). The rows are
encrypted
with a key derived from the client secret, which means rotating that secret costs each signed-in
user one re-login (a failed decryption is treated as a cache miss, not an error).

## Microsoft Graph

`graph_client/` is the official `msgraph-sdk`, and nothing else. It acquires no tokens: FastMCP's
On-Behalf-Of exchange hands a tool the caller's Graph access token as a string, and this package
gets that string onto the wire.

- **One transport, many callers.** `create_graph_transport(settings)` builds the `httpx.AsyncClient`
  — connection pool plus the SDK's middleware pipeline — once, and `graph_client_for(transport,
  token)` wraps it per call. The token is the only thing that varies; a client per call would mean
  a TLS handshake per call and a leaked pool.
- **Throttling is the SDK's, deliberately.** Its retry middleware already waits out `Retry-After`
  on 429/503/504 (on `asyncio.sleep`, not a blocking one) three times, which is exactly Graph's
  documented contract. Nothing here re-implements it and there is no rate limiter. What is added is
  the *typed* outcome: when the retries are outlasted, callers get `GraphThrottled` carrying
  `retry_after_seconds`, not a status code to re-interpret.
- **Errors are four categories**, because those are the four remedies: `GraphThrottled` (429),
  `GraphForbidden` (401/403), `GraphNotFound` (404) and `GraphUnavailable` (5xx, or never reached).
  Wrap Graph work in `with graph_errors():`. Anything else stays the base `GraphFailure`.
- **Paging follows `@odata.nextLink`** via `collect_pages`, replaying the URL verbatim, with an item
  cap, a *scan* cap — the teams-mcp lesson that a filtered collection can walk a long way for very
  few kept items — and a bound on how many pages of nothing it will follow in a row. There are three
  ways a read is bounded here and
  `graph_client/pagination.py` sets all three out together: an inventory walks until it has `limit`
  items, a meeting's artifacts are walked to a tighter *scan* cap (they are filtered and ordered
  here, so the walk cannot stop at `limit`), and a channel's messages are not walked at all — Graph
  allows about one request a second on a given channel for the whole app, so `browse_channel` makes
  exactly one and `$top` is its window. Search is not paged this way either: `POST /search/query`
  takes stateless `from`/`size` offsets, so a search tool resumes by re-issuing rather than by
  carrying a cursor.
- **An empty page carrying a next link means keep going, and the walk is ours because of it.** The
  SDK's `PageIterator.enumerate` returns `False` for a page whose `value` is empty and its `iterate`
  reads that as the end of the collection — so a collection Graph answers `[3 items + nextLink]`,
  `[nothing + nextLink]`, `[the newest one]` was walked as far as the middle page and then reported
  as having been cut by a cap. Downstream that put "this meeting has more transcripts than one call
  reads (200)" on a four-transcript meeting: a fabricated claim about the user's own meeting, from a
  flag whose two causes nobody could tell apart. `collect_pages` therefore drives the pages itself
  (keeping `enumerate` and `next`, which are the parts worth having) and stops only on a cap or on
  the end of the collection. Following empty pages needs a bound of its own, and *its own* is the
  point: `MAX_EMPTY_PAGES` counts empty pages **in a row**, and counts them against nothing else. It
  used to be half of one pooled request budget (`max_scanned` requests plus an allowance), which
  bounded the walk but not the empty pages — a collection answering nothing but empty pages spends no
  scan budget, so the whole pool was theirs and `list_chats` followed 1010 of them before giving up.
  Counted on their own, an endlessly empty collection costs 11 requests. Counted per run rather than
  per walk, a large collection that sprinkles the odd empty page is not killed for making progress: a
  page carrying an item starts the count again, and what a run of nothing means is that Graph will
  not end this collection. That is refused rather than answered short, because a short answer means a
  cap everywhere above and that would not be one.
- **The caller's token goes to `graph.microsoft.com` and nowhere else.** The SDK's bearer provider
  does not check its own allowed-hosts validator, so a redirect or an off-Graph `nextLink` would
  otherwise be handed a user's delegated credential.

## Tools

| Tool | What it answers | Graph |
| --- | --- | --- |
| `get_me` | Who the signed-in user is: `user_id`, `display_name`, `email`, `user_principal_name`, `job_title` | `GET /me` |
| `list_chats` | The user's Teams chats, most recently active first | `GET /me/chats` |
| `list_teams` | The teams the user is a member of | `GET /me/joinedTeams` |
| `list_channels` | The channels of one team the user can see | `GET /teams/{id}/channels` |
| `browse_channel` | One channel's posts, each with its newest replies, in Graph's reply-chain order | `GET /teams/{id}/channels/{id}/messages?$expand=replies` |
| `search_messages` | Teams messages matching keywords, a sender, mentions, a date range, attachment or read state | `POST /search/query` |
| `read_message` | One Teams message in full — text, sender, mentions, attachments, edits, deletion | `GET /chats/{id}/messages/{id}`, `GET /teams/{id}/channels/{id}/messages/{id}[/replies/{id}]` |
| `list_meeting_transcripts` | Whether a meeting was transcribed, and a handle per transcript | `GET /me/onlineMeetings?$filter=JoinWebUrl eq '…'`, `GET /me/onlineMeetings/{id}/transcripts` |
| `read_transcript` | What was said in a meeting: speaker-attributed, timestamped turns | `GET /me/onlineMeetings/{id}/transcripts/{id}/content` |
| `list_meeting_recordings` | Whether a meeting was recorded, how long each recording runs, and whether this user may download it | `GET /me/onlineMeetings?$filter=JoinWebUrl eq '…'`, `GET /me/onlineMeetings/{id}/recordings`, `GET /me` |

All are read-only, all take their caller's identity from the token rather than from a parameter, and
all are described to the model in prose that names the traps rather than only the fields — `email` is
null for guests (use `user_principal_name`, which may be on a different domain), a chat's recency is
its last message rather than the `lastUpdatedDateTime` that Graph moves on a rename, and a search
hit's `summary` is a snippet rather than the message.

Decisions worth knowing:

- **The tools are one surface, and the conventions are asserted, not just intended.** A name is
  `verb_noun` — which is why the identity tool is `get_me` and not `whoami`, the shell idiom having
  made the odd one out of the tool a model calls first (Microsoft's own M365 connector landed on
  `get_me` too). A result field is snake_case, and one thing has one name across every tool: a
  person's Entra id is `user_id` wherever it appears, an address is `email`, a time is `…_at`. No
  answer carries an unasked-for "there is more" flag: a window filled to `limit` may have more behind
  it and a short one is all there was, and where paging exists a `next_offset` says it outright and
  says where to continue — the exceptions are opt-in, null unless asked for, and are the two facts no
  answer could carry implicitly (see `truncated` below). `tests/test_mcp_tools.py` checks all of that against the live schemas, because
  a convention nothing enforces is how a new tool comes out different from the ones before it.
- **`truncated` came off all eight tools that reported it, and it is the one field clients asked to
  lose.** Five of them lost it outright: on `list_chats`, `list_teams` and `list_channels` a full
  window is the "there may be more" and a short one is the answer (which is only exactly true because
  of the empty-page fix above — before it, a short page could be a paging artefact), and on
  `search_messages` and `read_transcript` a non-null `next_offset` already said it and said where to
  continue. The other three kept the information a caller could *not* work out and made it opt-in and
  null by default, with one field per fact rather than one field over several:
  - The two meeting listers report `include_scan_completeness` → `scan_incomplete`, because there the
    flag had come to mean two things with opposite remedies: "the window held more than your `limit`"
    (raise it) and "the read stopped at the 200-artifact cap" (nothing helps, and the first entry may
    not be the meeting's latest). The first is what a full window says; the second is the one a
    caller cannot work out, has no remedy for, and only meets on a series recorded daily for most of
    a year. Nothing was made quieter where it mattered: an empty answer over a scan that stopped
    short is still `status: scan_incomplete` whether or not anybody asked.
  - `browse_channel` reports `include_window_completeness` → `more_posts_in_channel` and
    `posts_cut_to_limit`. It is the one tool that follows no paging — one request, because Graph
    allows about one a second on a channel for the whole connector — so it is also the one whose
    short answer means nothing either way: system messages are dropped out of the page after Graph
    counted them into it. Graph's `@odata.nextLink` on that page is an accurate "there is more of
    this channel" and is the only thing that says so, so it is reported rather than inferred; the
    ordinary "more posts on the page than your `limit`" is the second field, because a wider `limit`
    fixes that one and reaches none of the first.
- **Every result has a declared output schema.** So `next_offset` and `members_may_be_incomplete` are
  typed fields rather than prose or, worse, an extra object appended to the results array that a
  model can mistake for a result.
- **`list_chats` does not paginate.** `limit` (max 50, which is Graph's own `$top` ceiling on that
  collection) is a window on the most recent chats, and getting fewer than that many back is how a
  caller sees it has them all. A
  cursor over a collection that reorders itself on every message returns duplicates and gaps, and
  the window is what "recent chats" means; `services/teams-mcp` ships the same shape. What the
  `chat_id` it returns is *for* is naming: it is the same id `search_messages` puts on every chat
  message it finds, so the list is how a found message gets a topic and a set of participants. No
  tool here takes a chat id as an argument, a search cannot be narrowed to one chat, and a handle
  cannot be assembled out of one — so the description says all three rather than promising a
  chat-scoped tool that does not exist.
- **`browse_channel` is the only channel-message tool, because browsing is the only thing missing.**
  `search_messages` already searches channel content and cannot be scoped to one channel; a
  `get_channel_messages` beside it would have been a second way to ask a question one of them already
  answers. What neither could do is walk a single channel in order, so that is the tool: one channel
  per call, `$expand=replies` so a thread is one request rather than one per post, and no sweep —
  Graph allows this whole connector about one request a second on a given channel *per tenant*, so a
  loop over a team's channels would degrade every other user of the app registration.
- **`browse_channel` says what Graph's order actually is.** Microsoft sorts a channel's messages by
  the last modified date of the *entire reply chain*, so a two-year-old post returns to the front the
  moment somebody replies to it. The list is therefore not reordered here (that would invent an order
  Graph never gave) and the description tells the model to read `created_at` rather than the position
  — a tool that let "newest first" be assumed would have it reporting an old post as today's news.
  The same fact is why paging is bounded by a count and never by a date: "stop when a page is older
  than X" is unsound on this collection, and Graph accepts no `$filter` or `$orderby` here at all, so
  a date-bounded question goes to `search_messages` instead. Neither `$top` on `/me/joinedTeams` nor
  on `/teams/{id}/channels` is sent, either: both are documented as unsupported and `teams-mcp` had
  to remove them.
- **A channel reply got the handle grammar's third shape.** Graph addresses a reply *under* the post
  it answers (`…/messages/{root}/replies/{reply}`), which the two shapes minted by search could not
  express — and since the search projection carries no `replyToId`, a hit on a reply produced a
  root-post handle that Graph answers 404 to. `browse_channel` walks a channel post by post and so
  knows each reply's parent, which makes it the one tool that can mint the shape; the grammar itself
  stayed in `message_search` where the other two live, and `read_message` grew one request branch.
  The 404 advice now names this as the one well-formed handle that always fails, and says to browse
  the channel instead.
- **`search_messages` is one Graph request, always.** No fan-out, and specifically no per-chat scan
  when a date filter is set or a permission is missing — which is what the connector this replaces
  falls back to, up to 50 chats × 50 messages. Graph's read budget is "one request per second per
  app per tenant … on a given channel or chat", and *per app* means one user's sweep degrades every
  other user in the tenant; the connector we compared against returned zero results and a rate-limit
  note from that path in a live tenant. Date bounds go into the query string as `sent>=` / `sent<=`
  instead, where Microsoft's index applies them — inclusive, and covering channels as well as chats.
- **`search_messages` reports no result total,** because Graph does not give one: for Teams messages
  the `total` it returns is the count on the page. `next_offset` is the whole of the paging contract
  and the whole completeness signal — set while the index holds more, null on the last page — and a
  page can be shorter than `size` because system messages (`from: null`, a body of
  `<systemEventMessage/>`) are dropped and offsets index Graph's own hits.
- **`query` is words, not a phrase.** Multi-word free text reaches Microsoft's index as separate
  terms, which KQL ANDs: every word must appear, anywhere in the message and in any order. Wrapping
  the whole query in the quotes that guard a *filter value* would make it an exact-adjacency phrase
  and silently drop every match whose words are not side by side — the recall loss a caller cannot
  see, since the tool answers with fewer messages than exist and says nothing. A caller who wants
  adjacency quotes the words themselves, and that phrase is passed through as one. The injection
  guard is unweakened, only moved: it now runs a word at a time, so `from:ceo`, `sent>2026-01-01`,
  `(`, `*`, a leading `-` and a bare `OR` are each quoted into literal text rather than obeyed —
  `services/teams-mcp`'s guard, applied where a scope term's *value* is built and per word where
  the caller's own text is.
- **"At least one search criterion" is in the schema,** as an `anyOf` of one-element `required`
  lists, and re-checked at the tool boundary because FastMCP validates against the signature rather
  than the advertised schema. It is the only constraint of that kind here: nothing else about
  Microsoft's KQL scope terms makes two of these parameters genuinely incompatible, so nothing else
  is invented.
- **The reader is `read_message`, not a polymorphic `read_resource`.** It takes a URI handle, which
  pairs with a search that returns one, but its name says only what it reads. Two reasons, and the
  second is the load-bearing one. A tool called `read_resource` that serves Teams messages alone
  invites `mail:///`, `site:///` and `drive:///` — the connector we compared against exposes exactly
  that one polymorphic reader over every M365 entity — and every one of those is a failure a model
  could not have predicted from the name. More importantly, a message read's permission is per
  surface (`Chat.Read` in a chat, `ChannelMessage.Read.All` in a channel) and a token is exchanged
  per tool, so one reader over every entity type would have to redeem the union of every read
  permission on every call: a tenant unwilling to grant meeting-transcript access would break
  reading a chat message. That is no longer hypothetical — `read_transcript` is the second reader,
  it takes its own handle shape, and it redeems `OnlineMeetingTranscript.Read.All` and nothing else,
  so a tenant that withholds transcript access still reads messages.
- **A message body is normalised, never passed through as Teams HTML.** Wrapper divs, `<at>`
  mentions, `<emoji alt="👀">`, hostedContents `<img>`, `<attachment>` placeholders and adaptive-card
  JSON all become readable text (`@Name`, the emoji itself, `[image]`, `[attachment: name]`,
  `[card]`), and `mentions` / `attachments` come back resolved so the placeholders have a key. This
  is `services/teams-mcp`'s normaliser ported, not a second attempt at it.
- **A message with no text says why.** Microsoft Graph has no rendered text for a system event
  message — `from` is null and the body is the literal `<systemEventMessage/>`, because Teams writes
  "Ada joined the chat" in the client — so a read that lands on one reports the event named from
  `eventDetail` (`members joined`, `chat renamed`) and a null `text`. A deleted message reports
  `deleted_at` and a null `text` rather than a tombstone's leftovers. Both are the difference
  between "no content" and "they said nothing".
- **`read_message` keeps three failures distinct.** A malformed handle is ours to explain, so its
  error shows both readable shapes and says where a handle comes from; Graph's 404 on a well-formed
  handle says the message could not be read and explicitly *not* that it never existed (Graph
  answers deleted, invisible and absent identically); a 403 names the one permission that surface
  needs. The generic "check the id came from a tool response verbatim" advice is suppressed for the
  404 here, because the handle did come from one — that is `graph_tool_errors(..., not_found=...)`.
- **Meeting discovery is `list_chats`, not a tool of its own.** A meeting chat is already listed
  there, with the meeting's subject as its `topic` and its recency to order by, and Graph puts
  `onlineMeetingInfo` in that collection's default projection — so the chat carries `meeting_uri`,
  the handle `list_meeting_transcripts` takes, for no extra request and no extra permission. A
  `find_meetings` beside `list_chats` would have been a second way to ask which meeting. It also
  means no `Calendars.Read`: the connector stays Teams-only, where the M365 connector we compared
  against reaches a transcript only through a URI it got from a calendar read.
- **The join URL is the only route from a chat to a meeting, and it is not guaranteed.** Graph
  documents exactly three delegated ways to reach an `onlineMeeting` — its id, its `joinWebUrl`, its
  `joinMeetingId` — and a chat id is none of them. `chat.onlineMeetingInfo.joinWebUrl` is the one
  value a delegated caller is handed. That the property is *populated*, and populated for meetings
  the user did not organise, is **not verified against a live tenant**: it is documented on the
  resource and modelled by the SDK, nothing says it is organiser-only, and no call has been made
  that asked for it. So a null is a first-class outcome — `meeting_uri` is null, the description says
  that meeting's transcripts are unreachable here, and nothing is invented from the chat id to stand
  in. (`onlineMeeting` carries a `chatInfo.threadId`; filtering on it is undocumented and is not
  shipped.)
- **The `$filter` escaping is one line of doc and a live bug class.** *"joinWebUrl must be URL
  encoded"*, and Microsoft's own example shows how far that goes: a `%3a` already in the stored URL
  goes on the wire as `%253a`. `services/teams-mcp` doubles the OData quote and then hands the raw
  URL to a JavaScript SDK that concatenates query parameters without encoding, so a join URL with an
  `&` or a `#` — real ones have both — silently resolves to "meeting not found". Here the two
  transforms are separate: the quote doubling is ours, the percent-encoding is the Python SDK's
  (form-style URI-template expansion escapes `%`, `&`, `#`, `?` and `=`), and doing it twice would be
  as wrong as not at all. Tests pin the bytes that reach the wire, at the feature level and again
  over the protocol.
- **`200 OK` with an empty `value` is an answer, not an error.** The `JoinWebUrl` filter never 404s,
  so "no match" is `status: meeting_not_found` — reported as not proof the meeting is gone.
- **Five statuses, because there are five different things to do.** `available`, `not_ready`,
  `not_transcribed` (`not_recorded` for the other artifact), `scan_incomplete`,
  `meeting_not_found`. `not_ready` and the settled absence are the *same* empty collection from
  Graph and the opposite advice — wait, or stop — and Graph publishes no "processing" status and no
  availability SLA, so the split is inferred from the end of the *window that was asked about*,
  falling back to the meeting's own end time where no window was, with a deliberately generous
  allowance; the field says so. A meeting Graph gave no end time for counts as `not_ready`: one
  wasted call is cheaper than telling a caller a transcript will never exist ten minutes before it
  arrives. `scan_incomplete` is the fifth because an absence is only knowable from a collection
  that was read to the end: a meeting with more artifacts than one call looks through, none of them
  in the window, used to answer "there is none" *and* "there is more" in the same breath, which
  cannot both be true and which a caller cannot see through. Now the scan that stopped short is the
  answer, it claims nothing, and — since the walk underneath it no longer stops for any reason but
  the cap — the sentence it gives a model about the meeting's size is simply true.
- **"Newest first" is a promise about the collection, not about a page of it.** Both meeting
  listers take the whole window (up to a 200-artifact scan cap, which is this call's whole cost),
  order it, and only then cut it to `limit` — because Graph documents no `$orderby` on either
  collection, so a `limit` applied to the order Graph chose returns an arbitrary handful sorted
  among themselves and calls them the latest. "The latest transcript of this series" is the
  question the tools exist for, and that shape answered it wrongly with the shape of a right
  answer. The order, the cut, the scan cap and what the cap is worth admitting to are one function
  (`features/transcripts.newest_in_window`) shared by both, which is why the recordings lister
  inherited the bug and why both were fixed at once.
- **The tenant switch gets its own remedy, keyed on the inner error code.** `403` +
  `GraphAccessToTranscriptsDisabled` is not a permission problem and not a consent problem, so the
  message names a Teams administrator and the cmdlet, and explicitly rules out re-consent and
  signing in again. Microsoft says to branch on `innerError.code` and never on the message text, so
  `GraphFailure` now carries `inner_code` — the SDK has no typed field for it, and it arrives in the
  model's `additional_data`.
- **Speaker attribution degrades instead of failing.** A tenant can permit transcripts and forbid
  speaker names; Graph's documented remedy is to ask again for
  `application/vnd.microsoft.graph.transcript+text`, which `read_transcript` does exactly once and
  only for that inner code — the tenant switch answers with the same status and has no workaround.
  `speaker_attribution: false` then says the words and the timings are all there and the names are
  not. That is the gap `teams-mcp` still has (it hardcodes `Accept: text/vtt`).
- **A recurring series is one meeting.** One join URL, one meeting id, one transcript collection, and
  no occurrence addressing anywhere in Graph — so `started_after`/`started_before` scope to an
  occurrence by when transcription began, filtered while paging rather than as a `$filter` (the
  collection advertises `$filter` without documenting a single filterable property).
- **A recording is answered as metadata and availability. The bytes are never returned, by anything
  here.** Graph streams an MP4 inline with no ranged contract on that path, a Teams meeting can run
  thirty hours, and a model cannot watch video — so a tool that returned one would be a defect
  wearing a feature's clothes. `recordingContentUrl` is no better: it opens only with this
  connector's own bearer token, so passing it on is either useless or a token leak. What
  `list_meeting_recordings` answers is "there is a 47-minute recording from Tuesday, only the
  organiser can download it, and here is the transcript instead" — existence, start and end,
  a derived `duration_seconds` (Microsoft publishes no duration property at all), and
  `content_correlation_id`, which is Microsoft's own link to the transcript of the same call.
  Layering rule 10 forbids any module from addressing a single recording, because that is the only
  door to its bytes and the change that opens it looks like a convenience.
- **The organiser-only rule is a reported state, not a footnote.** Microsoft: *"In delegated
  permission scenarios, getting callRecording content is supported only for the meeting organizer.
  Meeting participants don't have permission to download meeting recordings"* — unless an
  administrator unblocked participants. The *metadata* is not so restricted, so for most meetings a
  participant asks about the recording is visible and its video is out of reach, and answering "there
  is no recording" would be a wrong answer nobody could detect. `content_access` says which side of
  the rule the signed-in user is on (`you_are_the_organizer` / `organizer_only` / `unknown`), which
  is why the listing spends one `GET /me`: Graph returns the organiser's `displayName` as null in
  every documented sample, so the comparison has to be made here rather than handed to the model as
  a bare object id.
- **Two artifacts, two tools — argued rather than assumed.** One tool listing a meeting's
  transcripts *and* its recordings is the tidier surface and it loses answers: Microsoft gates the
  two independently, the transcript gate is off by default, and a combined tool in that tenant either
  fails the whole call or carries a verdict per artifact instead of the single `status` that makes
  either answer actionable. It would also blunt a 403, which is only useful here because each tool
  names the permissions its own request was made under. So the artifacts are siblings that share
  everything shareable — the handle, the window, the resolve, the newest-first walk and the
  five-outcome vocabulary — and differ in one word of it: `not_transcribed` against `not_recorded`.
  `tests/test_mcp_tools.py` asserts the two answers stay the same shape, that they teach the same
  status words, and that the tenant switch stops at transcripts.
- **A search query is never logged. Neither is a transcript.** Not in a message, not as a structured
  field, not as a span attribute — what someone searched their own messages for names people and
  deals, and a transcript is a verbatim record of a room. `teams-mcp` had to remove query terms from
  its spans and logs after the fact; tests here assert both never arrive, and every transcript
  fixture in the suite is synthetic.
- **A refusal names its remedy, in one voice.** `server/errors.py` maps each Graph failure onto the
  one thing a model can do about it: 401 → ask the user to sign in again, 403 → ask an administrator
  for *this named permission*, 429 → wait Graph's own `Retry-After`, 5xx → retry once. Every one of
  them is written to the same shape, because a model reads them all as one server: "Microsoft 365"
  is what refused and is named first (not "Microsoft Graph", which is an API the caller is not
  calling), then the remedy and whether retrying could possibly help, then the diagnostics in a
  parenthesis at the end. The Graph request id rides along there, because that is what Microsoft
  support asks for, by that name. A permission that was never
  consented to fails earlier still — Entra refuses the On-Behalf-Of exchange (AADSTS65001) while
  FastMCP is resolving the tool's token, before the tool body runs — so `server/tools.py` wraps that
  exchange to give it the same named-permission remedy instead of "Failed to resolve dependency".
  Both paths name *every* permission the call was made under, which for `search_messages` is
  `Chat.Read` and `ChannelMessage.Read.All` both: neither Graph's 403 nor Entra's AADSTS65001 says
  which of the two was missing, and an administrator handed one name may grant the one that was
  already there. So the tenant that grants `Chat.Read` and withholds `ChannelMessage.Read.All` gets
  a refusal of this connector's own wording, naming both permissions and the remedy — not
  azure-identity's stack trace.

## Run locally

```bash
cd services/office-mcp
cp .env.example .env   # fill DB_* and ENTRA_*
uv sync
uv run office-mcp
```

There is no migration step: the database needs an empty schema the app's user can `CREATE` in,
and the OAuth state store makes its own table on first use.

- MCP endpoint: `http://localhost:9544/mcp` (HTTP transport, authenticated)
- Health: `GET /health` — liveness via `unique_mcp.monitoring.setup_ops`
- Probe: `GET /probe` — process-up (setup_ops)
- Ready: `GET /ready` — 503 when Postgres is unreachable. It asks the OAuth state store, which
  is the only connection a sign-in depends on; probing anything else could report ready on a
  server nobody can log in to.
- Metrics: `GET /metrics` — Prometheus (setup_ops)

## Tests

Integration tests start a Postgres container, so Docker must be running. Nothing is applied to
it — the app under test creates the one table it needs, the same way it does in production.

```bash
uv run pytest
```

## Lint & type-check

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run basedpyright .        # type check
```
