# Writing data

> **Before you read.** [Reading the API](reading-the-api.md) (response format) and the
> chapter for the record you want to write: [Contacts](contacts.md),
> [Activities](activities.md), [Opportunities](opportunities.md),
> [Products and accounts](products-and-accounts.md) (time series),
> [Entity relationships](entity-relationships.md) or
> [Custom fields](custom-fields-and-reference-data.md).

> **Never write to a customer's production tenant.** No `POST`, `PATCH`, `PUT` or `DELETE` against
> it, from scripts, tests, an agent or the connector during development, not even to try out a
> payload from this chapter. Try writes against test records on a tenant you are allowed to change.

The rules here come from the help centre, the swagger, and write experiments our connector ran
earlier against test records. Most of them were learned from a `400` that the swagger does not
mention. These rules are for code paths that write on a user's behalf.

## The basics

A `POST /notes` body:

```json
{
  "data": {
    "type": "notes",
    "attributes": {
      "title": "Quarterly update",
      "effectiveDate": "2026-10-13",
      "attachedTo": {"resourceType": "organizations", "resourceId": "101"}
    },
    "relationships": {
      "author": {"data": {"type": "system-users", "id": "12345"}},
      "activityTags": {"data": [{"type": "activity-tags", "id": "2001"}]}
    }
  }
}
```

| Action | Answer |
|---|---|
| `POST /{collection}` | `201` with the new record |
| `PATCH /{collection}/{id}` (body includes `id`) | `200` with the record |
| `DELETE /{collection}/{id}` | `204`, empty body. **A hard delete**: there is no recycle bin. |

- Use `Content-Type: application/vnd.api+json`.
- **PATCH merges.** Attributes and relationships you leave out are untouched. `"attr": null`
  clears an attribute; `"data": []` clears a to-many relationship. Clearing a required field gives
  `400 Field <x> is required`.
- **Creates are not idempotent.** Sending the same `POST` twice makes two records.
- Views are read-only (`contacts`, `employees`, `products`, `accounts`): write the underlying
  collection.

## Rule 1: links to records use the collection name

Fields that point at a record (`attachedTo`, `regarding`, `linkedResources`, `resources`,
`secondaryRegarding`, `sourceEntity`, `destinationEntity`, and the `resource` of bulk calls) take an
object `{resourceType, resourceId}` in **attributes**, and `resourceType` is the plural
**collection name**: `organizations`, `people`, `contacts`, `employees`, `opportunities`.

| You send | Answer |
|---|---|
| `"resourceType": "organizations"` | Works |
| `"resourceType": "OrganizationBean"` | `400 Can not find OrganizationBean with id …` |
| `"resourceType": "EmployeeBean"` in `linkedResources` | `400 Invalid LinkResourceType EmployeeBean` |

An `employees` link is stored and read back as `people`. A `linkedResources` entry that repeats the
main record is dropped without a word.

## Rule 2: users and other records go in `relationships`

`author`, `createdBy` and `assignedUser` point at system users and must be **relationships**:

```json
"relationships": {"author": {"data": {"type": "system-users", "id": "12345"}}}
```

Sending them as attributes gives
`400 author should not be in the 'attributes' but 'relationship.` (the same message for the
others). `attendees`, `activityTags`, `stage`, `product`, `investor`, `categories` and
`entityRelationshipType` are set the same way. An unknown id gives a `404` such as
`Resource activity-tags not found by id …`.

## Rule 3: required fields differ from the swagger

| Record | Required in practice |
|---|---|
| `notes` | `title`, `effectiveDate`, `attachedTo`, `author` |
| `meeting-or-calls` | `title`, `type`, `timeZone`, `startTimestamp`, `stopTimestamp`, `author`, and `regarding` |
| `tasks` | `name`, `dueDate`, `attachedTo`, `assignedUser` (*inferred*; we always send it) |
| `emails` | `data` (the message file) **and** `emailFormat` (`eml` or `msg`) |
| `documents` | `attachedTo`, `title`, `effectiveDate`, and exactly one of `data` or `documentUri` |
| `opportunities` | `name`, `currencyCode`, `isErisa`, `investor` |
| `people` | `lastName`, `gender` |
| `organizations` | `name` |
| `entity-relationships` | `sourceEntity`, `destinationEntity`, `entityRelationshipType` |

`/resource-metadata` lists required fields more accurately than the swagger, but it also misses
some (the meeting `regarding`, the task `attachedTo`, both email fields).

The API **cannot log an email without its file**: a metadata-only `POST /emails` gives
`400 Field data is required in POST request.` The web app can; the API cannot.

## Rule 4: send the defaults you mean

- `sendNotification` on tasks defaults to **true**, which emails the assignee. Send it explicitly.
- `isDraft` defaults to false.

## Rule 5: file content is gzip, then URL-safe base64

`data` on `/documents` and `/emails` is the file **gzip-compressed, then base64-encoded with the
URL-safe alphabet** (`-` and `_`) and no padding. The result starts with `H4sI`. Plain base64 gives
`400 You should Zip and encode dto data with Base64 schema`. Reading never returns the bytes:
documents give a `documentUri`, emails a `contentUrl`.

## Rule 6: times are local wall-clock plus a time zone

Meetings take `startTimestamp` without an offset (`"2026-09-10T10:00:00"`) and a `timeZone` short
name from `GET /time-zones` (`US/Eastern`). Backstop reads the time in that zone. A wrong meeting
`type` gives `400 Invalid value for type, valid options are [PHONE_IN, PHONE_OUT, FACE_TO_FACE]`.

## Rule 7: use the top-level collection, not a sub-route

| Request | Result |
|---|---|
| `POST /contacts/{id}/notes` | `403 contacts/notes is read only.` |
| `POST /organizations/{id}/notes` | `201`, works |
| `POST /{record}/{id}/meetingOrCalls` (the camelCase relationship name, see [Reading the API › The response format](reading-the-api.md#the-response-format)) | `201`, but the meeting **does not appear** in the record's activity list |
| `POST /meeting-or-calls` with `regarding` | Works |

Prefer the top-level collections for every activity type: `/notes`, `/meeting-or-calls`, `/tasks`,
`/emails`, `/documents`.

## Things a token cannot change

- The type of an existing entity relationship: `400 Relationship type can not be modified`.
- The key-employee flag: the update answers `200` (and echoes the value) but nothing is saved.
- Nested `PATCH /organizations/{id}/employees/{id}` gives a 500.
- Activity tags, custom field definitions and lists of values cannot be created through the API
  we use.

## Bulk endpoints

Three endpoints load many values for **one record per call**: `POST /bulk-custom-field-values`,
`POST /bulk-opportunity-stage-history` and `POST /bulk-time-series` (*documented*, articles 1074 and
1063).

**They always answer `201`, whatever happened.** The outcome is in
`attributes.bulkLoadSummary`:

```json
"bulkLoadSummary": {
  "totalCount": 2,
  "successCount": 1,
  "errorMessages": [{"index": 1, "message": "Error load record #1, Resource opportunities not found by id 999999999"}]
}
```

`successCount: 0` means nothing was saved. Good records in a partly failed call are still saved.

### Custom field values

A `POST /bulk-custom-field-values` body:

```json
{"data": {"type": "bulk-custom-field-values", "attributes": {
  "resource": {"resourceType": "organizations", "resourceId": "101"},
  "records": [
    {"definitionId": 100101, "value": "Active Client"},
    {"definitionId": 100103, "value": null}
  ]
}}}
```

- Value formats: dropdown, radio and check box by **display text**; multi-select as `"A|B"`; a user
  list as `[{"resourceType": "system-users", "resourceId": "…"}]`; an entity as
  `{"resourceType": "people", "resourceId": "…"}`.
- To clear a value send `"value": null`. Leaving the record out changes nothing.
- `effectiveDate` is **required** for time-series fields and **rejected** for regular ones.
- Typical errors: `Invalid value for <x>, valid options are [...]`,
  `TimeSeriesCustomField(<id>) need effectiveDate`, `RegularCustomField(<id>) does not need effectiveDate`.
- The echo is not a faithful copy: a dropdown can come back as its code (`"3"`) instead of the text.
  Read the record again to check.

### Time series

`POST /bulk-time-series` with `timeSeriesName` (`values`, `returns`, `aums`, …). `values` and
`returns` need a `valueStatus` of `FINAL` or `ESTIMATE` (`PARTIAL_PERIOD_ESTIMATE` for returns);
returns are fractions. Reads show `ACTUAL` where writes said `FINAL` (*inferred*).

### Opportunities and stage history

- Setting `stage` on a create writes the first history row, dated today.
- `PATCH` with a new `stage` writes a history row dated today and updates `previousStage`.
- `PATCH` with `stage` and `stageEffectiveDate` back-dates the move. If the back-dated row ends up
  older than the current one, **the current stage does not change**.
- `POST /bulk-opportunity-stage-history` with
  `records: [{effectiveDate, opportunity: {resourceType, resourceId}, stage: {resourceType, resourceId}}]`
  appends history rows and recomputes `previousStage`. **It never moves the current stage**,
  `dateEnteredCurrentStage` or `isOpen`, so `previousStage` can end up naming a stage the deal
  never left.
- Calculated fields cannot be written: `weightedValue`, `isOpen`, `previousStage`, the day counts,
  `dateEnteredCurrentStage`, `closedDate`, `effectiveDate`.

## Size limits

Backstop returns its own `413` for oversized uploads. Before a request gets that far, our
connector's MCP endpoint caps incoming request bodies at 4 MiB. The file travels inside that body
as base64, so `attach_file` rejects raw files over about 2.9 MB (`attach_file_max_bytes.py`).
