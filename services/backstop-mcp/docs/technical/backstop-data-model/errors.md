# Errors

> **Before you read.** [Reading the API](reading-the-api.md#the-response-format) for the two
> error formats. This chapter is a reference: look up the message you got.

Messages are quoted as Backstop sends them, typos included. `<x>` stands for the value that
varies. Messages that no test in this repo records were seen live only (*observed*).

## 400

### Filters, sorting, fields and includes

| Message | Cause | What to do |
|---|---|---|
| `Invalid filter field <x>` | The field is not filterable here, **or** an unknown query parameter on a collection, **or** an unsortable field in `sort` | Check the route's filter and sort lists ([Filtering](reading-the-api.md#filtering)) |
| `Invalid filter field <field>.<op>` (e.g. `city.in`) | `<op>` is not an operator | Use `eq`, `neq`, `gt`, `ge`, `lt`, `le` or `like` |
| `Unsupported filter operator: LIKE` (or `NEQ`, `GT`, `GE`) | The operator is valid but not on this field | Use `eq`, or another field (`lastName` instead of `name` on people) |
| `Like should be applied to string-valued filter` | `like` on a non-text field | Use `eq` |
| `Can not convert <v> to java.util.Date type.` | Wrong date format | `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS` |
| `Can not convert <v> to …RegularCustomFieldValueDto type.` | Filtering on custom field values | Not possible on the server; filter in code |
| `Can not convert <v> to …EntityRelationshipTypeDto type.` | `filter[entityRelationshipType]` | Use `filter[entityRelationshipTypeId]` |
| `Can not convert <id> to …ContactDto type.` | `filter[owner]` on accounts | Use `filter[owner.id]` |
| `No enum constant …EntityType.<x>` | A collection name where a Bean name is expected | `OpportunityBean`, `OrganizationBean`, … |
| `You can only sort by one field.` | `sort=a,b` | One field |
| `The system does not support fields for <x>` | Unknown attribute in `fields` | Check the attribute name for that type |
| `The system does not support includes for <x>` | Not includable on this route | Follow the sub-route instead |

### Paging and parameters

| Message | Cause |
|---|---|
| `offset <o> is not a multiple of limit <l>` | Offsets must be multiples of the limit |
| `Page limit should be larger than zero` | `page[limit]=0` |
| `Request parameters error` / `page[size]=[…]` | Only `page[limit]` and `page[offset]` exist |
| `Request parameters error` / `expected a Long for page[offset]=[]` | Empty page value |
| `Request parameters error` / `failed to parse parameter  sort` | A space in a parameter name |
| `Invalid filter field transactionDate ` (trailing space) | A space at the end of a sort value |

### Collections that need something first

| Message | Cause |
|---|---|
| `Find all <type> is not allowed.` | This collection cannot be listed (`contact-locations`, `lov-entries`, `features`, `time-series`, `bulk-*`). Read through a parent or by id. |
| `You can not query all notes without filter criteria.` | Add a filter (`createdTimestamp`, `modifiedTimestamp`, `activityTagIds`) |
| `You can not query this resource without filter criteria.` | Subscriptions and redemptions need a `transactionDate` filter |
| `Parameter searchText can not be empty` | `/quick-search` without `filter[searchText][eq]` |
| `Invalid value for searchTypes, valid options are [...]` | Upper-case `searchTypes` values only |
| `entityId must be provided for this repository.` | `/bsg-account-table-data` without `entityId` |
| `Either a reportDefinition or a reportName is required.` / `Report '<name>' not found.` | `/reports` needs an exact saved report name |

### Ids

| Message | Cause |
|---|---|
| `Resource <type> with id <x> is invalid` | The id is not a number or is too large (for example a short name used as an id) |
| `Can not find resource type from <id>` | `/activities/<id>` needs the composite id (`notes_<id>`) |
| `NumberFormatException For input string: "me"` | `/system-users/me` does not exist |

### Writes

| Message | Cause |
|---|---|
| `Field <x> is required` / `Field data is required in POST request.` | A required field is missing ([Rule 3](writing-data.md#rule-3-required-fields-differ-from-the-swagger)) |
| `<x> should not be in the 'attributes' but 'relationship.` | `author`, `createdBy` or `assignedUser` sent as an attribute |
| `Can not find OrganizationBean with id <id>` / `Invalid LinkResourceType EmployeeBean` | A Bean name in a record link; use the collection name |
| `You should Zip and encode dto data with Base64 schema` | File content not gzip + URL-safe base64 |
| `Invalid value for type, valid options are [PHONE_IN, PHONE_OUT, FACE_TO_FACE]` | Wrong meeting type |
| `Maximum length of locationTitle is 30` / `Location Names for a party must be unique.` | Contact location limits |
| `Relationship type can not be modified` | Changing the type of an existing relationship |
| `Unsupported relationships PATCH` | `PATCH` on a `/relationships/<name>` link |

### Activity search (`POST /entity-activities`)

| Message | Cause |
|---|---|
| `Invalid field <x>` | Unknown key in the body |
| `Invalid format <x>` | Wrong enum value |

## 401

| Body | Meaning |
|---|---|
| HTML "Invalid username/password provided." | Wrong credentials. With "The next unsuccessful login attempt … will temporarily disable the account", stop now. |
| Plain text "You are not authorized to access this API." | **Not a credentials problem.** The path does not exist in the API: a misspelt collection, `/me`, `/parties`, `/vehicles/{id}`, `/meeting-or-calls/{id}/regarding`. |

`/system-info` sometimes returns a 401 for a valid token. Mid-session, our connector re-probes
`/system-info` with backoff (1 s, 2 s, 4 s, …) for up to 10 s, and treats the token as revoked only
if every probe returns 401 or 403. The check at login does not retry.

## 403

| Body | Meaning |
|---|---|
| `AuthenticationException` "You are not allowed to perform GET on this resource" | The user may not read this record type at all (for example `contact-sources`). Also triggered by `include`-ing such a type. |
| `AuthenticationException` "You don't have permission to operate the entity <id>" | This record is in a permission bucket the user cannot see |
| Plain text "<collection> is read only." | A write to a view (`contacts`, `employees`) or to `/contacts/{id}/notes` |
| Plain text "Message signature could not be validated …" | The route needs signed requests (`/system-user-by-names`) |

## 404

| Body | Meaning |
|---|---|
| `ResourceNotFoundException` "Resource <type> not found by id <id>" | The record does not exist in **this** collection. Often the id belongs to another id space (a person id on `/organizations`). Also after a hard delete. |
| `PartyNotFoundException` "Party with id <id> was not found." | A location whose contact was deleted |
| HTML "Backstop - 404 Not Found" page | An unknown **relationship** name (`/organizations/{id}/meeting-or-calls` instead of `meetingOrCalls`), `/accounts/{id}/navs`, or the header `Accept: application/json` |

A 405 has never been seen. A `GET` on a write-only route gives a 400 instead.

## 413, 414, 429

| Status | Meaning |
|---|---|
| 413 | Upload too large |
| 414 | HTML from the web server: the URL is too long (for example a report definition in the query string). Use `POST`. |
| 429 | HTML page "Too Many Connections": more than 5 requests in flight for one user. Wait for running requests and retry. There is no JSON body to inspect, so this server does not retry it (see [Reading the API › Limits and speed](reading-the-api.md#limits-and-speed)). |

## 500

| Body | Typical causes |
|---|---|
| `InternalServerException` "Internal error! Please contact the administrator." | `/people?sort=name`; `filter[id][eq]=<comma list>`; `filter[id][eq]` on `/notes`; `filter[id][gt]` on subscriptions; activity search positions past 10,000; wrong shapes in activity search filters; `/features/<key>`; `GET /entity-activities-filters` |
| "Resource error" / "RelationshipsPath and FieldPath cannot contain ids" | An id after a relationship (`/organizations/{id}/employees/{id}`) |
| "Resource error" / "Exception while reading …EntityActivitiesQueryDto…" | Wrong value type in an activity search body |
| `QueryException` "Error loading ReportQueryDto:<id>" | `/reports/{id}` |

## No answer

A request that has not answered after 2 minutes (for example `GET /emails` with a very broad
`sentTimestamp` filter) should be abandoned. Narrow the request. If small requests also hang,
treat the API as down.
