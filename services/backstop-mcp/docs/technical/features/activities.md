<!-- confluence-page-id: tobefilled -->
<!-- confluence-space-key: PUBDOC -->

## Overview

Activities are the interaction record in Backstop: notes, meetings, calls, emails, documents, and
tasks, each linked to a party. This chapter covers finding and reading them, and logging and changing
them.

Code: [`features/activity_history`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/activity_history),
[`features/activity_writes`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/activity_writes),
[`features/activity_tags`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/activity_tags),
[`features/tasks`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/tasks).

| Question | Tool |
|---|---|
| What happened in a date window, firm-wide or with one party | `search_activities` (always first) |
| The full text and attachments of one activity | `get_activity_detail` |
| Which parties have gone quiet, and since when | `get_last_activity_for_parties` |
| One party's activity streams, when the search is unavailable | `get_activity_history` |
| A party's open or completed follow-ups | `get_tasks_for_party` |
| Which tag ids match a term | `list_activity_tags` |

## Searching Activities

`search_activities` runs Backstop's Activity Explorer search (`POST /entity-activities`; despite the
`POST`, it creates nothing). It is the primary read for meetings, calls, notes, emails, and documents.

**Inputs**

| Input | Behaviour |
|---|---|
| `start_date`, `end_date` | Inclusive window. A missing start is one year before the end; a missing end is today |
| `search_type` + `party_id` or `search` | Optional party scope. Without it the search is firm-wide |
| `types` | Any of `meeting_call`, `meeting`, `note`, `email`, `email_blast`, `document` |
| `activity_tag_ids` | Ids from `list_activity_tags`. A row matches if it carries **any** of them (OR) |
| `authors` | Author email addresses. Rows report the author as a system-user id |
| `attendees` | People ids. "Meetings this person attended" is this filter, not a party scope |
| `include_description` | Adds the full `description` to rows. Refused on a firm-wide search and in aggregate mode; scope it first |
| `mode` | `rows` (default) returns one page and a cursor. `aggregate` returns counts with `group_by` = `type`, `tag`, `party`, or `period` over the whole set; `group_by` is required there and a cursor is refused |
| `fields` | Selects row fields. `url` is selectable, not default |

**What comes back**

- Rows newest first, with type, title, effective date, short description, author, tags, linked
  parties (`associated_with`), and `attachments_count`. Meetings and calls add start, stop, time zone,
  location, and attendee names; emails add sender and recipients. The row `id` (also `activity_id`) works
  with `get_activity_detail` and `build_backstop_links`.
- `coverage.visible_count`: how many matched, counted for this user's permissions.
- `status: "unavailable"` when Backstop's search did not answer. That is not "no activity"; the
  fallback is `get_activity_history`.

**Limits and quirks**

- Backstop fails past offset 10,000, so the walk stops there. A set that reaches 10,000, firm-wide
  or scoped, comes back with `coverage.ceiling_hit` and a disclaimer, and a party missing from it is
  unknown, not inactive.
- Description text is not searchable. Search by date, type, tag, author, or attendee, then read the
  bodies.
- Rows that show Backstop ignored a filter it accepted are dropped, reading stops, and the filter is
  named in `server_filter_ignored`. Each occurrence increments `backstop_filter_ignored_total`, which
  the chart alerts on.

## Reading One Activity

`get_activity_detail` takes the `id` from a `search_activities` row, or the `activity_id` of a
meeting, call, note, or document row from `get_activity_history`. It returns:

- `body`: the full description converted from HTML to Markdown, not truncated.
- The attachment list. This is the only tool that names attachments; searches give a count.
- For meetings and calls: start, stop, location, time zone, and attendees.

Email rows from `get_activity_history` are `/emails` ids, a different id space, and are rejected; read
email bodies through `search_activities` with `include_description`. An unknown id is an error, not an
empty result.

## Who Has Gone Quiet

`get_last_activity_for_parties` takes 1 to 100 trusted `party_id`s (no `search`), each with its
`search_type`, and an optional window and types. The default types leave out `email_blast`. For each
party it runs one search sorted newest first and returns a `status` of `found`, `none_in_window`, or
`unknown`, the newest activity, the count in the window (10,000 means at least 10,000), and
`days_since_last_activity`. That count of days runs to the window's end date, not to today.

This answers "which investors have had no activity in 90 days" reliably because it asks once per
party, instead of inferring from a firm-wide sample that stops at 10,000 rows. A party with `status:
"unknown"` could not be checked. One failing party costs only its own answer; an authentication or
rate-limit failure stops the batch, and if every party fails the response is `status:
"unavailable"`.

A typical flow: take the open deals from `search_opportunities` with the `investor` field, pass each
distinct investor id and `search_type` here, and group by `days_since_last_activity`.

## One Party's Streams (Fallback)

`get_activity_history` reads one party's activities through Backstop's REST collections, one stream
per type: `meeting`, `call`, `note`, `document`, `email`. Use it only when `search_activities` is
unavailable.

- The first call (`request.type="first"`) resolves the party and fetches the first page of every
  requested stream. Later calls (`request.type="next"`) pass back each stream's `next` object.
- Each stream is a separate group with its own page and date range, not a merged timeline. A page
  holds up to `limit` rows per stream, by default `ACTIVITY_HISTORY_PAGE_SIZE` (10).
- Bodies are a `gist`: the first `ACTIVITY_HISTORY_GIST_CHARS` (300) characters converted to
  Markdown. `get_activity_detail` has the full body.
- `activity_tag_ids` here require **all** tags (AND), unlike the search. Emails have no tags and are
  omitted when tags are given.
- There is no default window, and future-dated meetings are included.
- A `403` on one stream (Backstop refusing a linked record) is reported on that group; the other
  streams are kept.

## Tasks

`get_tasks_for_party` returns one party's tasks with `status` `open`, `completed`, or `all`. Backstop
cannot filter tasks by status, so the server reads the party's tasks and filters. It always sends both
of Backstop's entity filters, because either one alone is ignored and returns every task in the
instance. It reads at most 5,000 tasks per party; beyond that `scan_truncated` is true.

## Activity Tags

`list_activity_tags` returns each tag's id, name, how many activities carry it, and whether it is
shown in the UI. `search` keeps tags whose name contains the text, ignoring case, and `refresh=true`
reloads the cached list. To find activities about a term, list the tags matching it and pass every
returned id to `search_activities`.

## Writing

| Tool | Kinds | Backstop collection |
|---|---|---|
| `log_activity` | `note`, `meeting`, `call`, `task` | `/notes`, `/meeting-or-calls`, `/tasks` |
| `attach_file` | `document`, `email` | `/documents`, `/emails` |
| `update_activity` | `note`, `meeting`, `call`, `task`, `email`, `document` | PATCH on the same collections |
| `delete_activity` | `note`, `meeting`, `call`, `task`, `email`, `document` | DELETE on the same collections |

### Logging an activity

Every kind needs a party (`search_type` plus `party_id` or `search`) and a `title`. An optional
secondary party can be linked too.

| Kind | Required | Optional |
|---|---|---|
| `note` | title | `description`, `effective_date`, `activity_tag_ids` |
| `meeting` | title, `time_zone`, `start`, `stop` | `location`, `attendee_party_ids`, `effective_date`, `activity_tag_ids` |
| `call` | title, `time_zone`, `start`, `stop` | `direction` (`PHONE_OUT`, the default, or `PHONE_IN`), and the same as meeting |
| `task` | title, `assigned_user` (a login from `list_system_users`), `due_date` | `description`, `send_notification` |

- **The author is the connected user**, taken from the system-user record stored at login. It is not
  a parameter. Tasks have no author.
- **Time zones** are Backstop short names such as `US/Eastern`; an id or a unique display name is
  also accepted and converted.
- **Tags must exist.** Ids come from `list_activity_tags`; the server never creates tags.
- **Task notifications** are always sent explicitly. Backstop defaults `sendNotification` to true and
  would email the assignee; the server sends `false` unless the caller sets it.
- **A note's `effective_date`** defaults to today; meetings and calls leave it unset unless given.
- Notes, meetings, and calls are written to Backstop's top-level collections, with the party as
  `attachedTo` (notes) or `regarding` (meetings, calls). Backstop's per-party routes either refuse the write for some party types or create a
  meeting that never appears in the party's activity feed.

### Attaching a file

`attach_file` creates a document, or imports a real `.eml` or `.msg` email, against a party.

- `content` is standard base64 of the raw file. The server re-encodes it the way Backstop requires
  (gzip, then URL-safe base64 without padding).
- A document's `title` defaults to `file_name` and its `effective_date` to today. An email's
  `email_format` is taken from a `.eml` or `.msg` file name, and is required otherwise. An email
  takes no secondary party.
- Files above 3,096,576 bytes are rejected before anything is sent to Backstop. The cap comes from the
  4 MiB request limit of the MCP transport, less base64 overhead and room for the rest of the request.
  In practice the base64 has to pass through the model's context, so much smaller files are realistic.
- **This is the only way to create an email record.** Backstop refuses an email without the message
  file, so `log_activity` has no email kind.

### Updating and deleting

- `update_activity` changes only the fields given; at least one is required. For an email, only
  `display_subject` and tags can change; the parsed subject, sender, and recipients cannot. A
  document's file cannot be replaced.
- Tags and attendees are replaced, not merged; an empty list clears them.
- A meeting or call update sends the meeting type only when `direction` is given, so an update never
  turns a call into a meeting by accident.
- `delete_activity` takes `kind` and `activity_id`. When the client supports elicitation it shows
  the activity and asks for confirmation; otherwise it deletes at once. A decline, a cancel, or no
  answer within `RESOLUTION_ELICIT_TIMEOUT_SECONDS` (120) deletes nothing. Deletion is permanent.

## Related

- [Features overview](./README.md)
- [Opportunities](./opportunities.md) (inactivity of deals)
- [Tools: Activities](../tools.md#Activities)
