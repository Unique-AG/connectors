<!-- confluence-page-id: tobefilled -->
<!-- confluence-space-key: PUBDOC -->

## Table of Contents

- [General](#General)
  - [What is Backstop MCP?](#What-is-Backstop-MCP?)
  - [Does it copy Backstop data into Unique?](#Does-it-copy-Backstop-data-into-Unique?)
  - [What infrastructure does it need?](#What-infrastructure-does-it-need?)
  - [Can it run with one shared Backstop service account?](#Can-it-run-with-one-shared-Backstop-service-account?)
  - [Which MCP clients work?](#Which-MCP-clients-work?)
  - [What is "tenant guidance"?](#What-is-"tenant-guidance"?)
- [Connection and Login](#Connection-and-Login)
  - [Where does a user get a personal API token?](#Where-does-a-user-get-a-personal-API-token?)
  - [Why does the login form say "This Backstop login has no matching system user"?](#Why-does-the-login-form-say-"This-Backstop-login-has-no-matching-system-user"?)
  - [Why does it say "Invalid username or API token"?](#Why-does-it-say-"Invalid-username-or-API-token"?)
  - [Why does it say "Backstop is unreachable right now"?](#Why-does-it-say-"Backstop-is-unreachable-right-now"?)
  - [Why does it say "Too many failed attempts for this username"?](#Why-does-it-say-"Too-many-failed-attempts-for-this-username"?)
  - [Why does it say "This login link is invalid or has expired"?](#Why-does-it-say-"This-login-link-is-invalid-or-has-expired"?)
  - [Why does it say "This form expired before it was submitted"?](#Why-does-it-say-"This-form-expired-before-it-was-submitted"?)
  - [Why does a tool say "Not connected to Backstop yet" or "No Backstop credential on file"?](#Why-does-a-tool-say-"Not-connected-to-Backstop-yet"-or-"No-Backstop-credential-on-file"?)
  - [How long does a user stay connected?](#How-long-does-a-user-stay-connected?)
  - [When does a user have to log in again?](#When-does-a-user-have-to-log-in-again?)
  - [A user replaced their API token in Backstop. What happens?](#A-user-replaced-their-API-token-in-Backstop.-What-happens?)
  - [Why did a tool say "Backstop temporarily rejected the request. Please retry."?](#Why-did-a-tool-say-"Backstop-temporarily-rejected-the-request.-Please-retry."?)
  - [Can a user connect several MCP clients?](#Can-a-user-connect-several-MCP-clients?)
- [Permissions, Data, and Privacy](#Permissions,-Data,-and-Privacy)
  - [What can a user see and change?](#What-can-a-user-see-and-change?)
  - [Why do counts differ from what a colleague sees?](#Why-do-counts-differ-from-what-a-colleague-sees?)
  - [What does the server store?](#What-does-the-server-store?)
  - [Can someone with database access read API tokens?](#Can-someone-with-database-access-read-API-tokens?)
  - [Do logs contain user names or tokens?](#Do-logs-contain-user-names-or-tokens?)
  - [Where does Backstop data go?](#Where-does-Backstop-data-go?)
  - [How do we cut off a user immediately?](#How-do-we-cut-off-a-user-immediately?)
  - [Is a user's stored credential deleted when they leave?](#Is-a-user's-stored-credential-deleted-when-they-leave?)
- [Finding Things](#Finding-Things)
  - [Why can't I find a record that exists in Backstop?](#Why-can't-I-find-a-record-that-exists-in-Backstop?)
  - [Why was I asked which record I meant?](#Why-was-I-asked-which-record-I-meant?)
  - [Why are search results not sorted by name?](#Why-are-search-results-not-sorted-by-name?)
  - [Why are colleagues not found by search_people?](#Why-are-colleagues-not-found-by-search_people?)
  - [Why does get_organization say 0 employees when people are linked?](#Why-does-get_organization-say-0-employees-when-people-are-linked?)
  - [Why is a person shown as a former employee?](#Why-is-a-person-shown-as-a-former-employee?)
  - [Why is a custom field I just created not visible?](#Why-is-a-custom-field-I-just-created-not-visible?)
- [Activities](#Activities)
  - [Which tool should be used for meetings, calls, notes, and emails?](#Which-tool-should-be-used-for-meetings,-calls,-notes,-and-emails?)
  - [Why does search_activities say the results are partial?](#Why-does-search_activities-say-the-results-are-partial?)
  - [How do I find which parties have had no activity for 90 days?](#How-do-I-find-which-parties-have-had-no-activity-for-90-days?)
  - [How do I see attachment names?](#How-do-I-see-attachment-names?)
  - [Why is the body in get_activity_history cut short?](#Why-is-the-body-in-get_activity_history-cut-short?)
  - [Why can't I search the text of notes?](#Why-can't-I-search-the-text-of-notes?)
  - [Why do tag filters behave differently in the two activity tools?](#Why-do-tag-filters-behave-differently-in-the-two-activity-tools?)
- [Opportunities](#Opportunities)
  - [Why does filtering by a colleague's name return no deals?](#Why-does-filtering-by-a-colleague's-name-return-no-deals?)
  - [What does backfill_opportunity_stage_history do?](#What-does-backfill_opportunity_stage_history-do?)
- [Products and Accounts](#Products-and-Accounts)
  - [Why has a balance no date?](#Why-has-a-balance-no-date?)
  - [Why are commitment and share of master missing?](#Why-are-commitment-and-share-of-master-missing?)
- [Reports and Links](#Reports-and-Links)
  - [Why does run_report return status: "running"?](#Why-does-run_report-return-status:-"running"?)
  - [Can the server list the available reports?](#Can-the-server-list-the-available-reports?)
  - [Why are record links missing?](#Why-are-record-links-missing?)
- [Writing Data](#Writing-Data)
  - [Can a delete be undone?](#Can-a-delete-be-undone?)
  - [Why was a record created twice?](#Why-was-a-record-created-twice?)
  - [Who is recorded as the author of a logged activity?](#Who-is-recorded-as-the-author-of-a-logged-activity?)
  - [Why can't I log an email with log_activity?](#Why-can't-I-log-an-email-with-log_activity?)
  - [What is the largest file attach_file accepts?](#What-is-the-largest-file-attach_file-accepts?)
  - [Can the server create activity tags?](#Can-the-server-create-activity-tags?)
  - [Does logging a task email the assignee?](#Does-logging-a-task-email-the-assignee?)
  - [Why can't I set Key employee?](#Why-can't-I-set-Key-employee?)
  - [Why did update_custom_field_values partly fail?](#Why-did-update_custom_field_values-partly-fail?)
  - [Why did create_employment fail with "No employment entity-relationship type matched" or "is ambiguous"?](#Why-did-create_employment-fail-with-"No-employment-entity-relationship-type-matched"-or-"is-ambiguous"?)
- [Operations](#Operations)
  - [Why does the server refuse to start with a PUBLIC_BASE_URL error?](#Why-does-the-server-refuse-to-start-with-a-PUBLIC_BASE_URL-error?)
  - [Why does the server refuse to start with a tenant guidance error?](#Why-does-the-server-refuse-to-start-with-a-tenant-guidance-error?)
  - [What happens if PostgreSQL goes down?](#What-happens-if-PostgreSQL-goes-down?)
  - [What happens if the encryption key changes?](#What-happens-if-the-encryption-key-changes?)
  - [Can we run more than one replica?](#Can-we-run-more-than-one-replica?)
  - [What do 429 errors from Backstop mean?](#What-do-429-errors-from-Backstop-mean?)
  - [Why do some tool calls take long or time out?](#Why-do-some-tool-calls-take-long-or-time-out?)
  - [What does the BackstopFilterIgnored alert mean?](#What-does-the-BackstopFilterIgnored-alert-mean?)
  - [Do upgrades need users to reconnect?](#Do-upgrades-need-users-to-reconnect?)
- [Related Documentation](#Related-Documentation)

## General

### What is Backstop MCP?

An MCP server that gives AI assistants 44 tools to read and write a firm's Backstop CRM: organizations,
people, activities, opportunities, products and accounts, custom fields, and saved reports. See the
[overview](./README.md) and [Tools](./technical/tools.md).

### Does it copy Backstop data into Unique?

No. Nothing is ingested. Each tool call reads Backstop live and returns the result to the MCP client.
The server's database holds only authentication state. A few reference catalogs, such as custom-field
definitions, are cached in memory, and report results are held in memory for up to an hour. See
[Architecture: Caching](./technical/architecture.md#Caching).

### What infrastructure does it need?

One container and one PostgreSQL database, plus a public HTTPS hostname. It does not need RabbitMQ,
the Unique knowledge base, or a Zitadel service account. See the [Operator Guide](./operator/README.md).

### Can it run with one shared Backstop service account?

No. Every user connects with their own Backstop username and personal API token, and every call runs
as that user. There is no setting for a shared credential.

### Which MCP clients work?

Any client that supports MCP over streamable HTTP with OAuth 2.1, PKCE, and dynamic client
registration. Elicitation (asking the user to pick between matches, or to confirm a delete) is used
when the client supports it; without it the tools return structured candidate lists, and deletes run
without a prompt.

### What is "tenant guidance"?

Optional text, set per deployment, that is appended to the server instructions and to individual tool
or parameter descriptions. It tells the AI about the firm's own setup, such as what a custom field
means. See [Configuration: Tenant guidance](./operator/configuration.md#Tenant-Guidance).

## Connection and Login

### Where does a user get a personal API token?

In Backstop: *Main Menu › System Tools › Administrative › Update Your Profile*, API Security section.
The login form links to [Backstop's help article](https://backstopsolutions.elevio.help/en/articles/236).
The login form takes this token, never a password.

### Why does the login form say "This Backstop login has no matching system user"?

The username and token are valid, but the login does not belong to a Backstop system user. The server
needs that record to author activities as the user, so it refuses the login. Ask your Backstop
administrator to check the user.

### Why does it say "Invalid username or API token"?

Backstop answered `401` or `403` to the check. The token may be mistyped, expired, or revoked, or the
username may not match the token's owner.

### Why does it say "Backstop is unreachable right now"?

The check got an unexpected status from Backstop or could not connect. For an operator, this usually
means the pod cannot reach `BACKSTOP_BASE_URL`, or the URL is wrong. These attempts do not count
toward the login throttle.

### Why does it say "Too many failed attempts for this username"?

After 10 failed logins for that username within 15 minutes, further attempts are refused until the
oldest failure is out of the window. A successful login clears the count. The limit is per username,
not per IP. Operators set it with `AUTH_LOGIN_MAX_ATTEMPTS` and `AUTH_LOGIN_ATTEMPT_WINDOW_MINUTES`. See
[Authentication: Login throttling](./operator/authentication.md#Login-Throttling).

### Why does it say "This login link is invalid or has expired"?

The login link is valid for 10 minutes after the client starts the flow. Start the connection again
from the MCP client.

### Why does it say "This form expired before it was submitted"?

The form's security cookie was missing or did not match the form. That usually means the same login
link was opened in a second tab, which replaces the cookie, or the browser blocks cookies for this
site. A form that was only left open runs into the 10-minute link limit first and shows "This login
link is invalid or has expired" instead. The page is shown again with a fresh token; submit it again
from that tab.

### Why does a tool say "Not connected to Backstop yet" or "No Backstop credential on file"?

The MCP token is valid, but the server has no Backstop credential to call Backstop with. "Not
connected to Backstop yet" means the request carried no connected user. "No Backstop credential on
file for this connection" means the user's stored credential is gone, for example because an operator
deleted it. The MCP token still works, so the client does not ask for a login: remove the server from
the client, add it again, and log in.

### How long does a user stay connected?

Access tokens last 15 minutes and are refreshed automatically. Refresh tokens last 30 days and are
renewed on every refresh, so a client used at least once a month stays connected. See
[Authentication: Token lifetimes](./operator/authentication.md#Token-Lifetimes).

### When does a user have to log in again?

After 30 days without use; when Backstop rejects their API token (expired, revoked, replaced); when a
refresh token is reused; or when the operator rotates the encryption key following
[Disaster Recovery: Rotating the encryption key](./operator/disaster-recovery.md#Rotating-the-Encryption-Key).
A key change made any other way does not prompt a login; see
[What happens if the encryption key changes?](#What-happens-if-the-encryption-key-changes?) and
[Authentication: Reconnecting](./operator/authentication.md#Reconnecting).

### A user replaced their API token in Backstop. What happens?

Their next tool call gets `401` from Backstop. The server re-checks for up to 10 seconds, then revokes
their MCP tokens and answers `401`, and the client asks them to log in again with the new token.

### Why did a tool say "Backstop temporarily rejected the request. Please retry."?

Backstop returned `401`, but the follow-up check showed the credential still works, or the check itself
failed for another reason. The session is kept; retry the call.

### Can a user connect several MCP clients?

Yes. Each client registers and gets its own tokens; they share the one stored credential for that
Backstop username. A new login from any client replaces the stored token.

## Permissions, Data, and Privacy

### What can a user see and change?

Exactly what Backstop allows their own login to. The server adds no permissions and has none of its
own. Two users can get different answers to the same question.

### Why do counts differ from what a colleague sees?

Counts such as `coverage.visible_count` and `activity_count` cover what the calling user can see.

### What does the server store?

Each user's Backstop username, their encrypted username and API token, and their system-user record
captured at login; OAuth clients and SHA-256 hashes of tokens; and recent login attempts with source
IP. No CRM data. See [Authentication: Data stored](./operator/authentication.md#Data-Stored).

### Can someone with database access read API tokens?

Not without the encryption key. Tokens are encrypted with Fernet (AES-128-CBC with HMAC-SHA256), and
the key lives only in the pod's environment. MCP tokens are stored only as SHA-256 hashes.

### Do logs contain user names or tokens?

API tokens are never logged. Tool events write Backstop logins as `sha256:<hex>` under the default
`LOGS_DIAGNOSTICS_DATA_POLICY=conceal`, and in plain text with `disclose`. The Backstop HTTP client's
own events (`backstop.request.*`, `backstop.auth_recheck.*`) carry the plain username under either
policy.

### Where does Backstop data go?

From Backstop to the server, and from the server to the MCP client that called the tool. Report runs
are kept in the pod's memory for up to an hour so a slow report can be collected; catalogs are cached
in memory. Nothing from tool calls is written to disk or the database.

### How do we cut off a user immediately?

Revoke their API token in Backstop. Their next tool call fails the re-check and the server revokes
their MCP tokens.

### Is a user's stored credential deleted when they leave?

No. Nothing deletes a stored credential automatically; a later login with the same username replaces
it. Revoking the API token in Backstop makes the stored copy useless. To remove it, an operator revokes
the user's MCP tokens and deletes the row. `backstop_username` is the login as the user typed it:

```sql
UPDATE mcp_auth_oauth_tokens SET revoked_at = now()
WHERE revoked_at IS NULL
  AND subject = (SELECT user_id FROM backstop_credentials WHERE backstop_username = '<login>');
DELETE FROM backstop_credentials WHERE backstop_username = '<login>';
```

## Finding Things

### Why can't I find a record that exists in Backstop?

- **The user's login cannot see it.** Every call runs as the user's own Backstop login, so a record
  Backstop hides from that login is not found.
- **The text does not match.** Backstop matches text literally: abbreviations, synonyms, and other
  spellings do not match. Name lookups use Backstop's quick search, which matches from the start of the
  name; when it finds nothing, the server tries a substring search on organization names and on
  people's last names. Contacts have no substring fallback. Try the full name, the abbreviation, and
  other spellings.
- **An email must match exactly.** An email address is looked up as an exact match on each of a
  person's three email fields.

### Why was I asked which record I meant?

Several records matched the name. The server asks through the MCP client when it can. If the client
cannot ask, or nobody answers within `RESOLUTION_ELICIT_TIMEOUT_SECONDS` (120), the tool returns the
`candidates` instead. See [Architecture: Party resolution](./technical/architecture.md#Party-resolution).

### Why are search results not sorted by name?

`search_organizations`, `search_people`, and `search_opportunities` read Backstop in id order. Backstop
returns records that tie on a sort field in a different order between requests, so paging by name would
repeat or skip rows.

### Why are colleagues not found by `search_people`?

`search_people` reads the people in the CRM: contacts and employees of organizations. Your own firm's
staff are Backstop system users; use `list_system_users`.

### Why does `get_organization` say 0 employees when people are linked?

`numberOfEmployees` is a field someone fills in, not a roster. `get_people_for_party` lists the people
linked to the organization.

### Why is a person shown as a former employee?

Their link to the organization has a type that means former employment, or an end date in the past.
Which types count as former is configurable; see
[Configuration: Departed-contact detection](./operator/configuration.md#Departed-Contact-Detection).

### Why is a custom field I just created not visible?

The custom-field catalog is cached for 120 minutes by default. Call `list_custom_fields` with
`refresh=true`, or wait for the cache to expire.

See [Features: Contacts](./technical/features/contacts.md).

## Activities

### Which tool should be used for meetings, calls, notes, and emails?

`search_activities`, always first. `get_activity_history` is the fallback when the search returns
`status: "unavailable"`.

### Why does `search_activities` say the results are partial?

Backstop's activity search stops at 10,000 rows, and the response sets `coverage.ceiling_hit`. Narrow
the window, scope it to a party, or filter by type or tag.

### How do I find which parties have had no activity for 90 days?

Use `get_last_activity_for_parties` with up to 100 parties. It checks each party separately, so a party
missing from a capped firm-wide search is not mistaken for inactive.

### How do I see attachment names?

`get_activity_detail` with the activity's id. Searches only return `attachments_count`.

### Why is the body in `get_activity_history` cut short?

It is a `gist`: the first 300 characters (`ACTIVITY_HISTORY_GIST_CHARS`). `get_activity_detail` returns the
full body.

### Why can't I search the text of notes?

Backstop's activity search cannot filter on description text. Filter by date, type, tag, author, or
attendee, then read the bodies (`include_description` on a scoped search, or `get_activity_detail`).

### Why do tag filters behave differently in the two activity tools?

`search_activities` matches a row with any of the given tags; `get_activity_history` requires all of
them. That is how Backstop's two endpoints work.

See [Features: Activities](./technical/features/activities.md).

## Opportunities

### Why does filtering by a colleague's name return no deals?

`representative` takes the colleague's Backstop **login**, from `list_system_users`, not their display
name. A disabled login can also return nothing.

### What does `backfill_opportunity_stage_history` do?

It adds past stage moves to deals' history. It does not move the current stage, but Backstop does
overwrite `previous_stage` with the backfilled stage.

See [Features: Opportunities](./technical/features/opportunities.md).

## Products and Accounts

### Why has a balance no date?

`get_accounts_for_party` normally answers from Backstop's UI account table, which gives balances without
an as-of date or actual/estimate label. `source` and `data_caveat` say which source answered. A dated,
labelled balance is `get_time_series` on the account's `values`.

### Why are commitment and share of master missing?

The UI account table failed and the server fell back to Backstop's documented account endpoints, which
do not provide those figures. They are listed in `omitted_fields`, never shown as zero.

See [Features: Products and Accounts](./technical/features/products-and-accounts.md).

## Reports and Links

### Why does `run_report` return `status: "running"`?

Backstop is still building the report, which can take minutes for a report it has not built recently.
Call again with the same name, date, limit, and offset to collect the result.

### Can the server list the available reports?

No. Backstop has no endpoint for that; the user has to give the exact Report Center name.

### Why are record links missing?

The deployment has no UI origin: `BACKSTOP_UI_BASE_URL` is unset and `BACKSTOP_BASE_URL` is the shared
API host. See [Configuration: CRM links](./operator/configuration.md#CRM-links).

See [Features: Reports and Links](./technical/features/reports-and-links.md).

## Writing Data

### Can a delete be undone?

No. Backstop has no recycle bin. The delete tools show the record and ask for confirmation when the
client supports elicitation; otherwise they delete immediately.

### Why was a record created twice?

Creates are not idempotent. Repeating a create call, for example after a timeout, makes a second
record. Check before retrying.

### Who is recorded as the author of a logged activity?

The connected user, using the system-user record captured at login. Tasks have no author in Backstop.

### Why can't I log an email with `log_activity`?

Backstop refuses to create an email without the message file. Import the `.eml` or `.msg` file with
`attach_file(kind="email")`.

### What is the largest file `attach_file` accepts?

3,096,576 bytes (about 2.95 MiB), derived from the MCP transport's 4 MiB request limit. The file also has
to pass through the model's context as base64, so much smaller files are realistic.

### Can the server create activity tags?

No. Tag ids must come from `list_activity_tags`.

### Does logging a task email the assignee?

Only when `send_notification` is true. The server always sends the flag, because Backstop would
otherwise default to notifying.

### Why can't I set Key employee?

The server rejects `is_key_employee` on person and employment writes. Set it in the Backstop UI. The
current value is read from `get_people_for_party`.

### Why did `update_custom_field_values` partly fail?

Backstop answers a bulk write with success even when some values fail. Each value is reported as
`applied` or `failed` with the error. Common causes are a picklist value that is not a current option,
and a missing or unexpected `effective_date`. See [Custom Fields](./technical/features/custom-fields.md#Writing-Values).

### Why did `create_employment` fail with "No employment entity-relationship type matched" or "is ambiguous"?

The server picks the employment relationship type from the instance's types using the configured
vocabulary, and found none or several. Set `BACKSTOP_EMPLOYMENT_RELATIONSHIP_TYPE_IDS` to the exact id.
See [Configuration: Departed-contact detection](./operator/configuration.md#Departed-Contact-Detection).

See [Features](./technical/features/README.md).

## Operations

### Why does the server refuse to start with a `PUBLIC_BASE_URL` error?

With `APP_ENV=production`, a loopback or `0.0.0.0` URL is refused, because clients would be sent to a
login form on their own machine. Set it to the public `https://` hostname.

### Why does the server refuse to start with a tenant guidance error?

The guidance is not valid JSON, or names a tool or parameter that does not exist. For an unknown name,
the error lists the valid ones.

### What happens if PostgreSQL goes down?

`/ready` returns `503` and the pod is taken out of service, but not restarted. Every `/mcp` request
needs the database to validate its token. Users carry on once it is back. If its data is lost, see
[Disaster Recovery](./operator/disaster-recovery.md#PostgreSQL-Data-Lost).

### What happens if the encryption key changes?

Every stored credential becomes unreadable. Tool calls fail, and because MCP tokens stay valid,
clients do not prompt a new login: users must remove and re-add the server, then log in. To avoid
that, follow [Disaster Recovery: Rotating the encryption key](./operator/disaster-recovery.md#Rotating-the-Encryption-Key),
which revokes the MCP tokens too, so each client asks its user to log in again.

### Can we run more than one replica?

Yes, but some state lives in each pod:

- **MCP sessions.** A session belongs to the pod that handled the client's `initialize`. A request for
  it on another pod gets `404 Session not found`, so route each client to one pod with session
  affinity.
- **The per-user limit of 5 concurrent Backstop requests.** With N replicas one user can reach 5×N.
  Backstop answers the excess with concurrency `429`s, which the server retries with backoff.
- **Catalog caches.** Each pod fetches its own.
- **Running report builds.** A `run_report` follow-up that lands on another pod starts the build again.

See [Operator Guide: Scaling](./operator/README.md#Scaling).

### What do `429` errors from Backstop mean?

Backstop rate-limited the user. A concurrency `429` is retried with backoff. A minute, hour, or day quota
`429` is not retried. `backstop_rate_limited_total` shows which kind.

### Why do some tool calls take long or time out?

Calls that walk whole collections (searches with only server-side filters, `get_product_investors` with
values, reports) can take tens of seconds. The chart's values note that the Unique chat client can
cancel a tool call at 60 seconds. Narrow the request; for searches that time out,
`exclude_custom_fields=true` shows whether reading custom fields is the cause.

### What does the `BackstopFilterIgnored` alert mean?

Backstop accepted a search filter but returned rows that do not match it. The server drops those rows
and flags the response, and `backstop_filter_ignored_total` counts each case by endpoint and filter.
That data is the evidence to take to Backstop support.

### Do upgrades need users to reconnect?

No, unless the encryption key changes. Database migrations run as a Helm hook (`alembic upgrade head`)
as part of the upgrade. Tokens live in PostgreSQL, so a replaced pod's MCP sessions end but clients
start new ones without a new login.

## Related Documentation

- [Overview](./README.md)
- [Operator Guide](./operator/README.md)
  - [Authentication](./operator/authentication.md)
  - [Configuration](./operator/configuration.md)
  - [Disaster Recovery](./operator/disaster-recovery.md)
  - [Local Development](./operator/local-development.md)
- [Technical Reference](./technical/README.md)
  - [Architecture](./technical/architecture.md)
  - [Features](./technical/features/README.md)
  - [Tools](./technical/tools.md)
