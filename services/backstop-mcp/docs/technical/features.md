<!-- confluence-page-id: tobefilled -->
<!-- confluence-space-key: PUBDOC -->

## Overview

What Backstop MCP lets an AI assistant do in Backstop, feature by feature. Every call reads or
writes Backstop live, as the connected user, so Backstop's own permissions decide what each user
sees and changes. For one line per tool, see [Tools](./tools.md); for how calls flow through the
server, see [Architecture](./architecture.md).

| Feature | Reads | Writes |
|---|---|---|
| [Contacts](#Contacts) | Organizations, people, who works where, colleagues | Create, update, delete people and organizations; start and end employment |
| [Activities and Tasks](#Activities-and-Tasks) | Meetings, calls, notes, emails, documents, tasks; last contact per party | Log activities and tasks, attach files, update, delete |
| [Opportunities](#Opportunities) | One investor's deals, the firm-wide pipeline, stage history | Create, update, move stage, backfill history, delete |
| [Products and Accounts](#Products-and-Accounts) | Products, holdings, investors, balances, subscriptions and redemptions | None |
| [Custom Fields](#Custom-Fields) | Field catalog and layout, values on records | Values on people, organizations, deals |
| [Saved Reports](#Saved-Reports) | Report Center reports | None |
| [Backstop Links](#Backstop-Links) | Links into the Backstop web app, and reading pasted links | None |

## Contacts

Look up, search, and maintain the organizations and people in Backstop, and the employment links
between them.

### Questions it answers

- Show me everything about this organization, or this person.
- Who works at this organization, and who has left?
- Which people have the title "CIO" in Zurich? Which organizations have a given custom field value?
- Who are our own colleagues in Backstop?
- Add this person, update their email, record that they moved to a new firm.

### Behaviour

- Name or email lookups that match several records ask the user to pick, or return the candidates.
  See [Architecture: Party resolution](./architecture.md#Party-resolution).
- Firm-wide searches return one page at a time with a cursor, and can filter on location, title,
  company, and custom fields.
- Current versus former employment is derived from Backstop's relationship records, including firms
  that record a departure as its own relationship type
  ([configurable](../operator/configuration.md#Departed-Contact-Detection)).
- Deletes are permanent and ask the user to confirm when the client supports it.

Code: [`org_people`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/org_people),
[`org_people_writes`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/org_people_writes),
[`data_hygiene`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/data_hygiene),
[`system_users`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/system_users).

## Activities and Tasks

Find and read the interaction record (meetings, calls, notes, emails, documents) and follow-up tasks,
and log new ones.

### Questions it answers

- What happened with this investor last quarter? Which meetings did this person attend?
- Show me the full notes and attachments of that meeting.
- Which of these investors have had no contact in 90 days?
- How many meetings did each colleague log this year?
- Which follow-ups are still open for this client?
- Log a call with this contact, or attach this email to their record.

### Behaviour

- `search_activities` searches by date window, type, tag, author, and attendee, firm-wide or for one
  party, and can return counts instead of rows. Activity text itself is not searchable in Backstop.
- `get_last_activity_for_parties` checks each of up to 100 parties with its own request, so "no
  recent contact" is reliable rather than inferred from a sample.
- New activities are authored by the connected user. Task notifications are off unless asked for.
- `attach_file` is the only way to add an email, since Backstop needs the message file.

Code: [`activity_history`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/activity_history),
[`activity_writes`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/activity_writes),
[`tasks`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/tasks),
[`activity_tags`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/activity_tags).

## Opportunities

Read and manage the sales pipeline: deals with an investor, a product, a stage, and a stage history.

### Questions it answers

- What deals does this investor have, and how did each reach its stage?
- What is the pipeline by colleague, stage, or product? How many deals moved stage this month?
- Which open deals have had no recent activity?
- Move this deal to "Due Diligence", or create a new one for this investor.

### Behaviour

- `search_opportunities` filters by representative, stage, product, stage-change window, and custom
  fields, and can group counts by stage, product, period, or investor.
- `update_opportunity` is the only way to move a stage, one deal per call. The deal is read back and
  a stage that did not land is reported.
- `backfill_opportunity_stage_history` adds past stage moves without changing the current stage.

Code: [`opportunities`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/opportunities),
[`opportunity_writes`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/opportunity_writes).

## Products and Accounts

Read-only access to the fund side of Backstop: products, investor accounts, dated figures, and capital
flows.

### Questions it answers

- What does this investor hold, and since when?
- Who invests in this fund, and how much?
- What was this account's balance on a given date? What are the fund's assets under management?
- Which subscriptions and redemptions happened last quarter, and in which share class?

### Behaviour

- Holdings report tenure as unbroken stretches of ownership across all of an investor's accounts,
  not the start date of one account.
- Missing figures stay missing. A `0` means Backstop published a zero, except a balance shown as
  `-`, which means nothing is recorded.
- Capital flows return completed subscriptions and redemptions only, within a required date window.

Code: [`accounts`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/accounts).

## Custom Fields

Read the firm's own custom fields (picklists, flags, dates, links) and set their values on people,
organizations, and deals.

### Questions it answers

- Which custom fields do we have, and what options does this picklist allow?
- What are the custom field values on this person or deal?
- Which organizations have "Client Status" set to "Active"?
- Set this person's "Client Status" to "Active".

### Behaviour

- Values on single-record reads are joined to the catalog, so they come with their name, tab, and
  group.
- `update_custom_field_values` checks each value against the catalog before writing, and reports each
  one as applied or failed. It is the only tool that writes custom fields.

Code: [`custom_fields`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/custom_fields).

## Saved Reports

Run a report saved in Backstop's Report Center and read it as a table.

### Questions it answers

- Run our "Quarterly AUM" report and show me the rows.
- Which rows in that report are above 10 million?

### Behaviour

- The report is named exactly; Backstop has no way to list reports.
- A slow report returns `running` and keeps building, so asking again collects the result.

Code: [`reports`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/reports).

## Backstop Links

Link answers back to the Backstop web app, and understand links users paste in.

### Questions it answers

- Give me the Backstop link to this organization, or to its opportunities tab.
- What record does this Backstop link point to?

### Behaviour

- Most records carry a `url` to their Backstop page when the deployment has a UI address
  [configured](../operator/configuration.md#CRM-links); without one, no link is guessed. Search
  rows include the link only when asked for, and emails have none.
- A pasted link is turned into the record id and the tool to call next.

Code: [`ui_links`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/ui_links).

## Safeguards

- **Every call runs as the user.** Two users can get different answers to the same question, and
  records they create are authored by them.
- **Deletes are permanent** and take one record id per call. When the client supports it, the user
  sees the record and confirms first. The tools tell the assistant to refuse bulk or
  search-then-delete sweeps.
- **Creates are not idempotent.** Repeating a create makes a second record.
- Write tools are annotated as destructive, so MCP clients that honour the hint ask before running
  them. `log_activity` and `attach_file` only add records and are not.

## Not Supported

- Listing saved reports. `run_report` needs the exact report name.
- Writing products, accounts, capital flows, time series, activity tags, contact categories, contact
  sources, or system users.
- Setting *Key employee* on a person or employment. Set it in the Backstop UI.
- Creating an email record without the message file. Backstop requires the file.
- Moving several deals' stages in one call.
- Reading the account record behind an account link. Its id still works for balances and capital
  flows.
- Editing a person's or organization's email address book. Use the three email fields instead.
- Changing permission buckets.

## Related Documentation

- [Technical Reference](./README.md)
- [Overview](../README.md)
- [Architecture](./architecture.md)
- [Tools](./tools.md)
