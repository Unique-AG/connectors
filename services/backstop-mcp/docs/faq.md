<!-- confluence-page-id: tobefilled -->
<!-- confluence-space-key: PUBDOC -->

## Table of Contents

- [About Backstop MCP](#About-Backstop-MCP)
  - [What is Backstop MCP?](#What-is-Backstop-MCP?)
  - [What can I ask the assistant?](#What-can-I-ask-the-assistant?)
  - [What can it not do?](#What-can-it-not-do?)
  - [Can it change data, or only read it?](#Can-it-change-data,-or-only-read-it?)
  - [Does it copy our Backstop data into Unique?](#Does-it-copy-our-Backstop-data-into-Unique?)
  - [Which AI assistants can use it?](#Which-AI-assistants-can-use-it?)
  - [Do all our users share one Backstop login?](#Do-all-our-users-share-one-Backstop-login?)
  - [What does it take to set up?](#What-does-it-take-to-set-up?)
  - [Can we tell the assistant about our own Backstop setup?](#Can-we-tell-the-assistant-about-our-own-Backstop-setup?)
- [Connecting and Signing In](#Connecting-and-Signing-In)
  - [Where does a user get a personal API token?](#Where-does-a-user-get-a-personal-API-token?)
  - [How long does a user stay connected?](#How-long-does-a-user-stay-connected?)
  - [When does a user have to sign in again?](#When-does-a-user-have-to-sign-in-again?)
  - [A user replaced their API token in Backstop. What happens?](#A-user-replaced-their-API-token-in-Backstop.-What-happens?)
  - [Can a user connect several AI assistants?](#Can-a-user-connect-several-AI-assistants?)
  - [Why does the login form say it has no matching system user?](#Why-does-the-login-form-say-it-has-no-matching-system-user?)
  - [Why does it say 'Invalid username or API token'?](#Why-does-it-say-'Invalid-username-or-API-token'?)
  - [Why does it say 'Backstop is unreachable right now'?](#Why-does-it-say-'Backstop-is-unreachable-right-now'?)
  - [Why does it say 'Too many failed attempts for this username'?](#Why-does-it-say-'Too-many-failed-attempts-for-this-username'?)
  - [Why does it say 'This login link is invalid or has expired'?](#Why-does-it-say-'This-login-link-is-invalid-or-has-expired'?)
  - [Why does it say 'This form expired before it was submitted'?](#Why-does-it-say-'This-form-expired-before-it-was-submitted'?)
  - [Why does a tool say 'Not connected to Backstop yet' or 'No Backstop credential on file'?](#Why-does-a-tool-say-'Not-connected-to-Backstop-yet'-or-'No-Backstop-credential-on-file'?)
  - [Why did a tool say 'Backstop temporarily rejected the request. Please retry.'?](#Why-did-a-tool-say-'Backstop-temporarily-rejected-the-request.-Please-retry.'?)
- [Permissions, Data and Privacy](#Permissions,-Data-and-Privacy)
  - [What can a user see and change?](#What-can-a-user-see-and-change?)
  - [Why do counts differ from what a colleague sees?](#Why-do-counts-differ-from-what-a-colleague-sees?)
  - [What does the server store?](#What-does-the-server-store?)
  - [Can someone with database access read API tokens?](#Can-someone-with-database-access-read-API-tokens?)
  - [Do logs contain user names or tokens?](#Do-logs-contain-user-names-or-tokens?)
  - [Where does Backstop data go?](#Where-does-Backstop-data-go?)
  - [How do we cut off a user immediately?](#How-do-we-cut-off-a-user-immediately?)
  - [Is a user's stored credential deleted when they leave?](#Is-a-user's-stored-credential-deleted-when-they-leave?)
- [Finding Records](#Finding-Records)
  - [Why can't I find a record that exists in Backstop?](#Why-can't-I-find-a-record-that-exists-in-Backstop?)
  - [Why was I asked which record I meant?](#Why-was-I-asked-which-record-I-meant?)
  - [Why are search results not in alphabetical order?](#Why-are-search-results-not-in-alphabetical-order?)
  - [Why are our own colleagues not found when I search for people?](#Why-are-our-own-colleagues-not-found-when-I-search-for-people?)
  - [Why does an organization say 0 employees when people are linked?](#Why-does-an-organization-say-0-employees-when-people-are-linked?)
  - [Why is a person shown as a former employee?](#Why-is-a-person-shown-as-a-former-employee?)
  - [Why is a custom field I just created not visible?](#Why-is-a-custom-field-I-just-created-not-visible?)
- [Meetings, Calls, Notes and Emails](#Meetings,-Calls,-Notes-and-Emails)
  - [How do I find which investors or other parties have had no activity for 90 days?](#How-do-I-find-which-investors-or-other-parties-have-had-no-activity-for-90-days?)
  - [Why does the assistant say the activity results are partial?](#Why-does-the-assistant-say-the-activity-results-are-partial?)
  - [How do I see the names of attachments?](#How-do-I-see-the-names-of-attachments?)
  - [Why can't I search the text of notes?](#Why-can't-I-search-the-text-of-notes?)
  - [Why is a note or email body cut short?](#Why-is-a-note-or-email-body-cut-short?)
  - [Why do tag filters give different results depending on the question?](#Why-do-tag-filters-give-different-results-depending-on-the-question?)
- [Opportunities](#Opportunities)
  - [Why does filtering deals by a colleague's name return nothing?](#Why-does-filtering-deals-by-a-colleague's-name-return-nothing?)
  - [What does backfilling stage history do?](#What-does-backfilling-stage-history-do?)
- [Products and Accounts](#Products-and-Accounts)
  - [Why does a balance have no date?](#Why-does-a-balance-have-no-date?)
  - [Why are commitment and share of master missing?](#Why-are-commitment-and-share-of-master-missing?)
- [Reports and Links](#Reports-and-Links)
  - [Why does a report say it is still running?](#Why-does-a-report-say-it-is-still-running?)
  - [Can the assistant list our saved reports?](#Can-the-assistant-list-our-saved-reports?)
  - [Why are links to Backstop records missing?](#Why-are-links-to-Backstop-records-missing?)
- [Making Changes](#Making-Changes)
  - [Can a delete be undone?](#Can-a-delete-be-undone?)
  - [Why was a record created twice?](#Why-was-a-record-created-twice?)
  - [Who is recorded as the author of a logged activity?](#Who-is-recorded-as-the-author-of-a-logged-activity?)
  - [Can I log an email?](#Can-I-log-an-email?)
  - [What is the largest file that can be attached?](#What-is-the-largest-file-that-can-be-attached?)
  - [Can the assistant create activity tags?](#Can-the-assistant-create-activity-tags?)
  - [Does logging a task email the person it is assigned to?](#Does-logging-a-task-email-the-person-it-is-assigned-to?)
  - [Why can't I set Key employee?](#Why-can't-I-set-Key-employee?)
  - [Why did a change to custom fields partly fail?](#Why-did-a-change-to-custom-fields-partly-fail?)
  - [Why did adding an employment fail with 'No employment entity-relationship type matched' or 'is ambiguous'?](#Why-did-adding-an-employment-fail-with-'No-employment-entity-relationship-type-matched'-or-'is-ambiguous'?)
- [Speed and Reliability](#Speed-and-Reliability)
  - [Why do some questions take a long time or time out?](#Why-do-some-questions-take-a-long-time-or-time-out?)
  - [What do 'rate limit' errors from Backstop mean?](#What-do-'rate-limit'-errors-from-Backstop-mean?)
- [For IT Administrators](#For-IT-Administrators)
  - [Why does the server refuse to start?](#Why-does-the-server-refuse-to-start?)
  - [What happens if PostgreSQL goes down?](#What-happens-if-PostgreSQL-goes-down?)
  - [What happens if the encryption key changes?](#What-happens-if-the-encryption-key-changes?)
  - [Can we run more than one replica?](#Can-we-run-more-than-one-replica?)
  - [Do upgrades need users to reconnect?](#Do-upgrades-need-users-to-reconnect?)
  - [What does the BackstopFilterIgnored alert mean?](#What-does-the-BackstopFilterIgnored-alert-mean?)

## About Backstop MCP

### What is Backstop MCP?

Backstop MCP connects an AI assistant to your firm's Backstop CRM. Users ask questions in plain
language, such as "which investors have I not spoken to in 90 days?", and the assistant looks the
answer up in Backstop. It can also make changes when asked, such as logging a meeting or moving a deal
to the next stage. MCP (Model Context Protocol) is the standard that lets AI assistants talk to
business systems like Backstop. See the [overview](./README.md).

### What can I ask the assistant?

The assistant can answer questions and make changes in these areas of Backstop:

| Area | Example questions | More detail |
|---|---|---|
| Organizations and people | Who works at this organization? Show me everything about this contact. Which people have the title "CIO"? | [Contacts](./technical/features.md#Contacts) |
| Meetings, calls, notes, emails and tasks | What happened with this investor last quarter? Which meetings did this person attend? What follow-ups are still open? | [Activities](./technical/features.md#Activities-and-Tasks) |
| Sales pipeline | What deals does this investor have, and how did each reach its stage? How many deals does each colleague have open? | [Opportunities](./technical/features.md#Opportunities) |
| Products and investor accounts | What does this investor hold? Who invests in this fund, and how much? What was the balance on a given date? | [Products and Accounts](./technical/features.md#Products-and-Accounts) |
| Custom fields | Which custom fields do we have? Which organizations have this field set to a given value? | [Custom Fields](./technical/features.md#Custom-Fields) |
| Saved reports and links | Run our saved report. Give me the link to this record in Backstop. | [Saved Reports](./technical/features.md#Saved-Reports), [Backstop Links](./technical/features.md#Backstop-Links) |

### What can it not do?

It cannot list your saved reports, so the user has to give the exact report name. It cannot change
funds, accounts, capital flows, or activity tags, and it cannot set the *Key employee* flag; do those
in Backstop. See [Not Supported](./technical/features.md#Not-Supported) for the full list.

### Can it change data, or only read it?

Both. Reading is always safe. Creating and changing records works the way it does in Backstop and is
recorded under the user's own name. Deleting a record is permanent, because Backstop has no recycle
bin. Assistants that honour Backstop MCP's safety hints ask the user before running a change, and the
delete tools show the record and ask for confirmation first when the assistant supports it. See
[Making Changes](#Making-Changes).

### Does it copy our Backstop data into Unique?

No. Nothing is imported or indexed. Each question is answered by reading Backstop at that moment and
passing the result to the assistant. Only login information is stored (see
[What does the server store?](#What-does-the-server-store?)). A few reference lists, such as the custom
field definitions, are remembered for a short time, and a report that was run is held in memory for up
to an hour. See [Architecture: Caching](./technical/architecture.md#Caching).

### Which AI assistants can use it?

Any assistant that supports MCP over streamable HTTP with OAuth 2.1, PKCE, and dynamic client
registration. If the assistant can ask the user questions during a task, it asks which record is meant
when a name matches several, and asks for confirmation before a delete. If it cannot, the server
returns the list of matches instead, and deletes run without a prompt.

### Do all our users share one Backstop login?

No. Every user connects with their own Backstop username and personal API token, and everything the
assistant does runs as that user. There is no shared account and no setting for one.

### What does it take to set up?

One container, one PostgreSQL database, and a public HTTPS address. Nothing else from Unique's platform
is needed. Your IT team follows the [Operator Guide](./operator/README.md), or Unique runs it for you
as a service.

### Can we tell the assistant about our own Backstop setup?

Yes. An administrator can add text, called tenant guidance, that tells the assistant what your custom
fields and conventions mean, such as what a custom field is used for. See
[Configuration: Tenant Guidance](./operator/configuration.md#Tenant-Guidance).

## Connecting and Signing In

### Where does a user get a personal API token?

In Backstop: *Main Menu › System Tools › Administrative › Update Your Profile*, API Security section.
The login form links to [Backstop's help article](https://backstopsolutions.elevio.help/en/articles/236).
The login form asks for this token, never for the user's password.

### How long does a user stay connected?

A user who works with the assistant at least once a month stays connected without signing in again.
The connection ends after 30 days without use. See
[Authentication: Token Lifetimes](./operator/authentication.md#Token-Lifetimes).

### When does a user have to sign in again?

- After 30 days without using it.
- When Backstop no longer accepts their API token, because it expired, was revoked, or was replaced.
- When an administrator rotates the encryption key as described in
  [Disaster Recovery: Rotating the Encryption Key](./operator/disaster-recovery.md#Rotating-the-Encryption-Key).

See [Authentication: Reconnecting](./operator/authentication.md#Reconnecting).

### A user replaced their API token in Backstop. What happens?

Their next question fails. The server re-checks for up to 10 seconds, then ends their connection, and
the assistant asks them to sign in again with the new token.

### Can a user connect several AI assistants?

Yes. Each assistant signs in separately and gets its own connection. They share the one stored Backstop
credential for that username, and a new sign-in from any assistant replaces the stored token.

### Why does the login form say it has no matching system user?

The full message is "This Backstop login has no matching system user". The username and token are
valid, but the login does not belong to a Backstop system user. The server needs that record to record
activities under the user's name, so it refuses the login. Ask your Backstop administrator to check the
user.

### Why does it say 'Invalid username or API token'?

Backstop refused the username and token. The token may be mistyped, expired, or revoked, or the
username may not belong to that token.

### Why does it say 'Backstop is unreachable right now'?

The server could not get a clear answer from Backstop. Try again in a few minutes. If it keeps
happening, ask your IT team to check that the server can reach Backstop. These attempts do not count
toward the sign-in attempt limit.

### Why does it say 'Too many failed attempts for this username'?

After 10 failed sign-ins for the same username within 15 minutes, further attempts are refused until
the oldest failure is 15 minutes old. A successful sign-in clears the count. The limit is per username,
not per computer. Administrators can change it; see
[Authentication: Login Throttling](./operator/authentication.md#Login-Throttling).

### Why does it say 'This login link is invalid or has expired'?

The login link works for 10 minutes after the assistant starts the connection. Start the connection
again from the assistant.

### Why does it say 'This form expired before it was submitted'?

This usually means the same login link was opened in a second browser tab, or the browser blocks
cookies for this site. The page is shown again with a fresh form; submit it again from that tab. A
form that was only left open too long shows "This login link is invalid or has expired" instead.

### Why does a tool say 'Not connected to Backstop yet' or 'No Backstop credential on file'?

The assistant is signed in, but the server has no Backstop credential to use for the user, for example
because an administrator deleted it. Remove the server from the assistant, add it again, and sign in.

### Why did a tool say 'Backstop temporarily rejected the request. Please retry.'?

Backstop refused one request, but a follow-up check showed the user's credential still works. The user
stays connected; ask the question again.

## Permissions, Data and Privacy

### What can a user see and change?

Exactly what Backstop allows their own login to see and change. The server adds no permissions of its
own, and two users can get different answers to the same question.

### Why do counts differ from what a colleague sees?

Counts cover what the asking user is allowed to see in Backstop, not firm-wide totals.

### What does the server store?

Each user's Backstop username, their encrypted API token, and their Backstop system-user record taken
at sign-in. It also stores each AI assistant's registration and its access and refresh tokens (the tokens
only as one-way hashes), and recent sign-in attempts with the source IP address. It stores no CRM data. See
[Authentication: Data Stored](./operator/authentication.md#Data-Stored).

### Can someone with database access read API tokens?

Not without the encryption key. Tokens are encrypted, and the key exists only in the server's
configuration, not in the database. Connection tokens are stored only as one-way hashes.

### Do logs contain user names or tokens?

API tokens are never logged. By default, Backstop usernames in tool logs are replaced by a one-way
hash; an administrator can switch to plain text. The log lines of the connection to Backstop itself
always contain the plain username. See [Configuration](./operator/configuration.md).

### Where does Backstop data go?

From Backstop to the server, and from the server to the AI assistant that asked. A report that was run
is kept in the server's memory for up to an hour so a slow report can be collected, and reference lists
are remembered for a short time. Nothing from a question is written to disk or to the database.

### How do we cut off a user immediately?

Revoke their API token in Backstop. Their next question fails and the server ends their connection.
This is the only step needed. See [Authentication: Cutting Off a User](./operator/authentication.md#Cutting-Off-a-User).

### Is a user's stored credential deleted when they leave?

Not automatically. A later sign-in with the same username replaces it. Once the API token is revoked in
Backstop, the stored copy is useless. An administrator can delete it; see
[Authentication: Cutting Off a User](./operator/authentication.md#Cutting-Off-a-User).

## Finding Records

### Why can't I find a record that exists in Backstop?

- **The user's login cannot see it.** Everything runs as the user's own Backstop login, so a record
  Backstop hides from that login is not found.
- **The text does not match.** Backstop matches text literally: abbreviations, synonyms, and other
  spellings do not match. Name lookups match from the start of the name; when that finds nothing, the
  server tries a search inside organization names and people's last names. Contacts have no such second
  try. Ask the assistant to try the full name, the abbreviation, and other spellings.
- **An email must match exactly.** An email address matches only when it is identical to one of the
  person's three stored email addresses.

### Why was I asked which record I meant?

Several records matched the name. The assistant asks the user to pick one. If it cannot ask, or nobody
answers within 2 minutes, it lists the matches instead. See
[Architecture: Party Resolution](./technical/architecture.md#Party-resolution).

### Why are search results not in alphabetical order?

Searches for organizations, people, and opportunities page through records in id order. Backstop
does not return records in a stable order when they tie on a sort field, so paging by name would
repeat or skip records, and Backstop refuses to sort people by name at all. Ask the assistant to
sort the results it received.

### Why are our own colleagues not found when I search for people?

Searching for people covers the people in the CRM: contacts and employees of organizations. Your own
firm's staff are Backstop system users. Ask for "our colleagues" or "Backstop users" instead.

### Why does an organization say 0 employees when people are linked?

The employee count is a number someone types in, not a count of the linked people. Ask for the people
who work at the organization to see the real list.

### Why is a person shown as a former employee?

Their link to the organization has a type that means former employment, or an end date in the past.
Administrators can configure which link types count as former; see
[Configuration: Departed Contact Detection](./operator/configuration.md#Departed-Contact-Detection).

### Why is a custom field I just created not visible?

The list of custom fields is remembered for 120 minutes by default. Ask the assistant to refresh the
list, or wait for the time to pass.

## Meetings, Calls, Notes and Emails

### How do I find which investors or other parties have had no activity for 90 days?

Ask for the last activity per party, for up to 100 parties at a time. The server checks each party
separately, so a party is never wrongly reported as inactive just because a large search ran out of
room. A party that could not be checked is marked as unknown. See
[Activities and Tasks](./technical/features.md#Activities-and-Tasks).

### Why does the assistant say the activity results are partial?

Backstop's activity search stops after 10,000 matches. Ask for a shorter time window, one party, or one
type of activity or tag.

### How do I see the names of attachments?

Ask for the full details of the activity. Searches only show how many attachments there are.

### Why can't I search the text of notes?

Backstop's activity search cannot filter on the text of a note or meeting description. Search by date,
type, tag, author, or attendee first, and then ask the assistant to read the descriptions of what it
found.

### Why is a note or email body cut short?

When the assistant reads one party's activity by type, each body is shortened to its first 300
characters. Ask for the full details of that activity to read the complete text.

### Why do tag filters give different results depending on the question?

In the main search an activity matches when it has any of the given tags. In the by-type view used when
the main search is unavailable, an activity must have all of them. That is how Backstop's two lookups
work. See [Activities](./technical/features.md#Activities-and-Tasks).

## Opportunities

### Why does filtering deals by a colleague's name return nothing?

The deal's representative is matched by the colleague's Backstop **login**, not by their display name.
Ask for the list of Backstop users first so the assistant can use the right login. A disabled login can
also return nothing.

### What does backfilling stage history do?

It adds past stage moves to the history of deals. It does not move the current stage, but Backstop
does overwrite the deal's previous stage with the backfilled one. See
[Opportunities](./technical/features.md#Opportunities).

## Products and Accounts

### Why does a balance have no date?

Account balances normally come from the account table in Backstop's screens, which gives a balance with
no as-of date and no actual or estimate label. The response says which source answered. A dated,
labelled balance comes from the account's time series; ask for the balance history instead.

### Why are commitment and share of master missing?

The account table could not be read, so the server used Backstop's documented account data, which does
not include those two figures. They are listed as omitted, never shown as zero. See
[Products and Accounts](./technical/features.md#Products-and-Accounts).

## Reports and Links

### Why does a report say it is still running?

Backstop is still building the report, which can take minutes if it was not built recently. Ask again
with the same report name and date to collect the result.

### Can the assistant list our saved reports?

No. Backstop has no way to list them, so the user has to give the exact name from Backstop's Report
Center.

### Why are links to Backstop records missing?

The deployment does not know your Backstop web address. An administrator sets it; see
[Configuration: CRM Links](./operator/configuration.md#CRM-links). See also
[Backstop Links](./technical/features.md#Backstop-Links).

## Making Changes

### Can a delete be undone?

No. Backstop has no recycle bin. When the AI assistant supports it, it shows the record and asks for
confirmation first; otherwise the record is deleted immediately.

### Why was a record created twice?

Creating records is not safe to repeat. If a request is repeated, for example after a timeout, a second
record is created. Check in Backstop before asking again.

### Who is recorded as the author of a logged activity?

The connected user. Tasks have no author in Backstop.

### Can I log an email?

Only by importing the email file (`.eml` or `.msg`). Backstop refuses to create an email without the
message file, so an email cannot be typed in as a note.

### What is the largest file that can be attached?

About 2.95 MiB (3,096,576 bytes). The file also passes through the assistant as text, so much smaller
files work better in practice.

### Can the assistant create activity tags?

No. Tags must already exist in Backstop.

### Does logging a task email the person it is assigned to?

Only when the user asks for a notification. Backstop would notify by default, so the server turns it
off unless requested.

### Why can't I set Key employee?

Setting the *Key employee* flag is not allowed through the assistant. Set it in the Backstop screens.
The assistant can still read the current value.

### Why did a change to custom fields partly fail?

Backstop reports success for a batch even when some values fail, so the assistant reports each value as
applied or failed, with the reason. Common causes are a picklist choice that is not a current option and
a missing or unexpected effective date. See
[Custom Fields](./technical/features.md#Custom-Fields).

### Why did adding an employment fail with 'No employment entity-relationship type matched' or 'is ambiguous'?

The server could not tell which of your Backstop relationship types means employment. An administrator
can set the exact type; see
[Configuration: Departed Contact Detection](./operator/configuration.md#Departed-Contact-Detection).

## Speed and Reliability

### Why do some questions take a long time or time out?

Questions that read a whole collection, such as a search that Backstop cannot narrow itself, a fund's
investors with their values, or a large report, can take tens of seconds. Some assistants cancel a
tool at 60 seconds. Ask a narrower question, for example one colleague, one product, or a shorter time
window.

### What do 'rate limit' errors from Backstop mean?

Backstop limits how many requests a user can make. Short bursts are retried automatically. A minute,
hour, or day quota being used up is not retried; wait and ask again.

## For IT Administrators

These questions are about running the server. The [Operator Guide](./operator/README.md) has the full
steps.

### Why does the server refuse to start?

Two causes are common. In production, the public address must be an `https://` hostname, not a local
address. And the tenant guidance must be valid JSON that names only tools and parameters that exist; the
error lists the valid names. See [Configuration](./operator/configuration.md).

### What happens if PostgreSQL goes down?

The server reports itself as not ready and stops receiving requests, because every request needs the
database to check its token. Users carry on once it is back. If the data is lost, see
[Disaster Recovery: PostgreSQL Data Lost](./operator/disaster-recovery.md#PostgreSQL-Data-Lost).

### What happens if the encryption key changes?

Every stored credential becomes unreadable and questions fail. Because the assistants' connections
stay valid, they do not ask for a new sign-in, so users must remove and re-add the server and sign in.
To avoid that, follow
[Disaster Recovery: Rotating the Encryption Key](./operator/disaster-recovery.md#Rotating-the-Encryption-Key),
which ends all connections so each assistant asks its user to sign in again.

### Can we run more than one replica?

Yes, with session affinity so that each assistant keeps talking to the same pod. See
[Operator Guide: Scaling](./operator/README.md#Scaling) for what else differs per pod.

### Do upgrades need users to reconnect?

No, unless the encryption key changes. Database migrations run automatically during the upgrade. A
replaced pod ends its open sessions, and the assistants start new ones without a new sign-in. See
[Operator Guide: Upgrades](./operator/README.md#Upgrades).

### What does the BackstopFilterIgnored alert mean?

Backstop accepted a search filter but returned rows that do not match it. The server drops those rows
and flags the response, and a counter records each case by endpoint and filter. That is the evidence
to take to Backstop support. See [Operator Guide](./operator/README.md).

## Related Documentation

- [Overview](./README.md)
- [Operator Guide](./operator/README.md)
  - [Authentication](./operator/authentication.md)
  - [Configuration](./operator/configuration.md)
  - [Disaster Recovery](./operator/disaster-recovery.md)
  - [Local Development](./operator/local-development.md)
- [Technical Reference](./technical/README.md)
  - [Architecture](./technical/architecture.md)
  - [Features](./technical/features.md)
  - [Tools](./technical/tools.md)
